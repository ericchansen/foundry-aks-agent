import logging
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import APIError
from opentelemetry.trace import StatusCode
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded

from foundry_aks_agent.config import Settings
from foundry_aks_agent.runtime import Runtime, open_runtime
from foundry_aks_agent.telemetry import agent_scope

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


class Question(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000, pattern=r"\S")


class Answer(BaseModel):
    answer: str
    trace_id: str
    agent_id: str
    release_id: str
    pod_name: str
    pod_namespace: str


def create_app(
    runtime_factory: Callable[[], AbstractAsyncContextManager[Runtime]] | None = None,
) -> FastAPI:
    if runtime_factory is None:

        def runtime_factory() -> AbstractAsyncContextManager[Runtime]:
            return open_runtime(Settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with runtime_factory() as runtime:
            app.state.runtime = runtime
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> Runtime:
        runtime: Runtime = app.state.runtime
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode(),
            runtime.settings.agent_api_token.get_secret_value().encode(),
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return runtime

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/ask", response_model=Answer)
    async def ask(question: Question, runtime: Annotated[Runtime, Depends(authorize)]) -> Answer:
        settings = runtime.settings
        tracer = runtime.provider.get_tracer(__name__)
        with agent_scope(settings.otel_agent_id):
            with tracer.start_as_current_span(
                "POST /ask", record_exception=False, set_status_on_exception=False
            ) as span:
                span.set_attribute("demo.release_id", settings.release_id)
                trace_id = format(span.get_span_context().trace_id, "032x")
                try:
                    answer = await runtime.answer(question.prompt)
                except (
                    APIError,
                    ModelAPIError,
                    UnexpectedModelBehavior,
                    UsageLimitExceeded,
                ) as error:
                    span.set_status(StatusCode.ERROR, "Model request failed")
                    logger.warning(
                        "Model request failed trace_id=%s type=%s", trace_id, type(error).__name__
                    )
                    raise HTTPException(
                        status_code=502,
                        detail={"error": "Model request failed", "trace_id": trace_id},
                    ) from None
                return Answer(
                    answer=answer,
                    trace_id=trace_id,
                    agent_id=settings.otel_agent_id,
                    release_id=settings.release_id,
                    pod_name=settings.pod_name,
                    pod_namespace=settings.pod_namespace,
                )

    return app


app = create_app()
