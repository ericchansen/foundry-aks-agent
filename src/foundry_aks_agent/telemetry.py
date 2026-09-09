from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from foundry_aks_agent.config import Settings

_agent_id: ContextVar[str | None] = ContextVar("agent_id", default=None)


@contextmanager
def agent_scope(agent_id: str) -> Iterator[None]:
    token = _agent_id.set(agent_id)
    try:
        yield
    finally:
        _agent_id.reset(token)


class AgentIdentityProcessor(SpanProcessor):
    """Enrich each span created inside this agent's async request scope."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        agent_id = _agent_id.get()
        if agent_id is not None:
            span.set_attribute("gen_ai.agent.id", agent_id)


def create_provider(settings: Settings) -> TracerProvider:
    provider = TracerProvider(
        sampler=ALWAYS_ON,
        resource=Resource.create(
            {
                "service.name": settings.agent_name,
                "service.version": settings.release_id,
                "service.instance.id": settings.pod_name,
                "k8s.pod.name": settings.pod_name,
                "k8s.namespace.name": settings.pod_namespace,
            }
        ),
    )
    provider.add_span_processor(AgentIdentityProcessor())
    provider.add_span_processor(
        BatchSpanProcessor(
            AzureMonitorTraceExporter(
                connection_string=settings.applicationinsights_connection_string.get_secret_value(),
                tracer_provider=provider,
                disable_offline_storage=True,
            )
        )
    )
    return provider
