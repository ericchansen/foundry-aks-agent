import argparse
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.ai.projects.models import ExternalAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from pydantic import ValidationError

from foundry_aks_agent.client import endpoint
from foundry_aks_agent.config import Settings
from foundry_aks_agent.register import register


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example.com",
        "https://user:password@example.com",
        "https://example.com?token=secret",
        "ftp://localhost",
    ],
)
def test_client_rejects_unsafe_endpoint(url):
    with pytest.raises(argparse.ArgumentTypeError):
        endpoint(url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8000", "http://localhost:8000", "https://example.com"]
)
def test_client_accepts_secure_transport(url):
    assert endpoint(url + "/") == url


def test_config_requires_strong_token_and_https(settings):
    values = settings.model_dump()
    with pytest.raises(ValidationError):
        Settings(**(values | {"agent_api_token": "short"}))
    with pytest.raises(ValidationError):
        Settings(**(values | {"azure_openai_endpoint": "http://example.com"}))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.openai.azure.com/openai",
        "https://example.openai.azure.com//",
        "https://example.openai.azure.com?api-version=2024-10-21",
        "https://example.openai.azure.com/#fragment",
        "https://example.openai.azure.com?",
        "https://example.openai.azure.com/#",
        "https://user:password@example.openai.azure.com",
        "https://@example.openai.azure.com",
        "https:///missing-host",
    ],
)
def test_config_rejects_non_origin_model_endpoint(settings, url):
    with pytest.raises(ValidationError, match="HTTPS origin"):
        Settings(**(settings.model_dump() | {"azure_openai_endpoint": url}))


@pytest.mark.parametrize("suffix", ["", "/"])
def test_config_normalizes_model_endpoint(settings, suffix):
    origin = "https://example.openai.azure.com"
    configured = Settings(**(settings.model_dump() | {"azure_openai_endpoint": origin + suffix}))
    assert configured.azure_openai_endpoint == origin


def test_register_reads_back_external_identity():
    project = Mock()
    definition = ExternalAgentDefinition(otel_agent_id="expected")
    registered = SimpleNamespace(
        versions=SimpleNamespace(latest=SimpleNamespace(definition=definition))
    )
    project.agents.get.side_effect = [ResourceNotFoundError(), registered]
    assert register(project, "boring-aks-agent", "expected") == "expected"
    call = project.agents.create_version.call_args.kwargs
    assert call["definition"].kind == "external"
    assert call["definition"].otel_agent_id == "expected"
    assert "endpoint" not in call
    assert "protocol" not in call
    assert project.agents.get.call_count == 2
    project.agents.get.assert_called_with(agent_name="boring-aks-agent")


def test_register_fails_on_identity_mismatch():
    project = Mock()
    registered = SimpleNamespace(
        versions=SimpleNamespace(
            latest=SimpleNamespace(definition=ExternalAgentDefinition(otel_agent_id="wrong"))
        )
    )
    project.agents.get.side_effect = [ResourceNotFoundError(), registered]
    with pytest.raises(RuntimeError, match="readback"):
        register(project, "boring-aks-agent", "expected")


def test_register_does_not_overwrite_an_existing_identity():
    project = Mock()
    project.agents.get.return_value = SimpleNamespace(
        versions=SimpleNamespace(
            latest=SimpleNamespace(
                definition=ExternalAgentDefinition(otel_agent_id="another-agent")
            )
        )
    )
    with pytest.raises(RuntimeError, match="already exists"):
        register(project, "boring-aks-agent", "expected")
    project.agents.create_version.assert_not_called()


def test_register_is_idempotent_when_identity_matches():
    project = Mock()
    project.agents.get.return_value = SimpleNamespace(
        versions=SimpleNamespace(
            latest=SimpleNamespace(definition=ExternalAgentDefinition(otel_agent_id="expected"))
        )
    )
    assert register(project, "boring-aks-agent", "expected") == "expected"
    project.agents.create_version.assert_not_called()
