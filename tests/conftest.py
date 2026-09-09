import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from foundry_aks_agent.config import Settings
from foundry_aks_agent.telemetry import AgentIdentityProcessor

TEST_TOKEN = "local-test-token-not-for-deployment-000000"


@pytest.fixture
def settings():
    return Settings(
        agent_api_token=TEST_TOKEN,
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_deployment="gpt-4.1-mini",
        applicationinsights_connection_string="InstrumentationKey=00000000-0000-0000-0000-000000000000",
        release_id="test-release",
        pod_name="test-pod",
        pod_namespace="boring-agent",
    )


@pytest.fixture
def telemetry():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AgentIdentityProcessor())
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter
    provider.shutdown()
