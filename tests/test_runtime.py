import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncAzureOpenAI
from opentelemetry.trace import StatusCode
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from foundry_aks_agent.app import create_app
from foundry_aks_agent.runtime import Runtime, create_agent
from foundry_aks_agent.telemetry import agent_scope, create_provider

from .conftest import TEST_TOKEN


def setup_app(settings, telemetry, status=200):
    provider, exporter = telemetry
    requests = []

    def complete(request):
        requests.append(request)
        if status == 0:
            raise httpx.ConnectError("Model unavailable", request=request)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "Model unavailable"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-local-test",
                "created": 1,
                "model": "gpt-4.1-mini",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello from the test model!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
            },
        )

    @asynccontextmanager
    async def factory():
        async with httpx.AsyncClient(transport=httpx.MockTransport(complete)) as http:
            async with AsyncAzureOpenAI(
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
                api_key="local-fake-key",
                http_client=http,
                max_retries=0,
            ) as client:
                model = OpenAIChatModel(
                    settings.azure_openai_deployment,
                    provider=OpenAIProvider(openai_client=client),
                )
                yield Runtime(settings, provider, create_agent(model, settings, provider))

    return create_app(factory), requests, exporter


def test_answer_and_actual_pydantic_run_model_spans(settings, telemetry):
    app, requests, exporter = setup_app(settings, telemetry)
    with TestClient(app) as client:
        response = client.post(
            "/ask",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
            json={"prompt": "Reply with a short greeting."},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Hello from the test model!"
    assert body["release_id"] == "test-release"
    assert body["pod_name"] == "test-pod"
    assert body["pod_namespace"] == "boring-agent"
    assert body["agent_id"] == settings.otel_agent_id
    assert len(requests) == 1
    assert "/deployments/gpt-4.1-mini/chat/completions" in requests[0].url.path
    spans = exporter.get_finished_spans()
    runs = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "invoke_agent"]
    models = [s for s in spans if s.attributes.get("gen_ai.operation.name") == "chat"]
    assert len(runs) == len(models) == 1
    serialized = "\n".join(str(span.attributes) for span in spans)
    assert "Reply with a short greeting." in serialized
    assert "Hello from the test model!" in serialized
    for span in spans:
        assert span.attributes["gen_ai.agent.id"] == settings.otel_agent_id
        assert span.attributes["gen_ai.agent.name"] == settings.agent_name
        assert span.attributes["gen_ai.agent.version"] == settings.agent_version
        assert format(span.context.trace_id, "032x") == body["trace_id"]
    assert models[0].parent.span_id == runs[0].context.span_id


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-token", "Basic abc"])
def test_unauthorized_never_calls_model(settings, telemetry, authorization):
    app, requests, exporter = setup_app(settings, telemetry)
    with TestClient(app) as client:
        headers = {"Authorization": authorization} if authorization else {}
        response = client.post("/ask", headers=headers, json={"prompt": "Hello"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert client.get("/healthz").json() == {"status": "ready"}
    assert not requests
    assert not exporter.get_finished_spans()


@pytest.mark.parametrize("prompt", ["", "   ", "a" * 4001])
def test_invalid_prompts_do_not_invoke(settings, telemetry, prompt):
    app, requests, _ = setup_app(settings, telemetry)
    with TestClient(app) as client:
        response = client.post(
            "/ask", headers={"Authorization": f"Bearer {TEST_TOKEN}"}, json={"prompt": prompt}
        )
    assert response.status_code == 422
    assert not requests


@pytest.mark.parametrize("status", [0, 429, 500])
def test_model_error_is_not_a_success_or_retry(settings, telemetry, status):
    app, requests, exporter = setup_app(settings, telemetry, status=status)
    with TestClient(app) as client:
        response = client.post(
            "/ask", headers={"Authorization": f"Bearer {TEST_TOKEN}"}, json={"prompt": "Hello"}
        )
    assert response.status_code == 502
    assert len(requests) == 1
    assert response.json()["detail"]["error"] == "Model request failed"
    assert "Model unavailable" not in response.text
    root = next(span for span in exporter.get_finished_spans() if span.name == "POST /ask")
    assert root.status.status_code is StatusCode.ERROR
    assert root.status.description == "Model request failed"


async def test_identity_does_not_leak_between_concurrent_agents(telemetry):
    provider, exporter = telemetry
    tracer = provider.get_tracer("test")

    async def invoke(identity):
        with agent_scope(identity):
            await asyncio.sleep(0)
            with tracer.start_as_current_span(identity):
                await asyncio.sleep(0)
                with tracer.start_as_current_span(f"{identity}-child"):
                    pass

    await asyncio.gather(invoke("first"), invoke("second"))
    with tracer.start_as_current_span("unrelated"):
        pass
    spans = exporter.get_finished_spans()
    for span in spans:
        if span.name == "unrelated":
            assert "gen_ai.agent.id" not in span.attributes
        else:
            assert span.attributes["gen_ai.agent.id"] == span.name.split("-")[0]


def test_identity_resets_after_exception(telemetry):
    provider, exporter = telemetry
    tracer = provider.get_tracer("test")
    with pytest.raises(ValueError), agent_scope("failed-agent"):
        raise ValueError("test")
    with tracer.start_as_current_span("after"):
        pass
    assert "gen_ai.agent.id" not in exporter.get_finished_spans()[0].attributes


def test_azure_exporter_receives_the_scoped_provider(settings, monkeypatch, telemetry):
    _, exporter = telemetry
    captured = {}

    def create_exporter(**kwargs):
        captured.update(kwargs)
        return exporter

    monkeypatch.setattr("foundry_aks_agent.telemetry.AzureMonitorTraceExporter", create_exporter)
    provider = create_provider(settings)
    try:
        assert captured["tracer_provider"] is provider
        assert captured["disable_offline_storage"] is True
        assert provider.resource.attributes["service.instance.id"] == settings.pod_name
        with agent_scope(settings.otel_agent_id):
            with provider.get_tracer(__name__).start_as_current_span("scoped-export"):
                pass
        assert provider.force_flush()
        attributes = exporter.get_finished_spans()[0].attributes
        assert attributes["gen_ai.agent.id"] == settings.otel_agent_id
        assert attributes["gen_ai.agent.name"] == settings.agent_name
        assert attributes["gen_ai.agent.version"] == settings.agent_version
    finally:
        provider.shutdown()
