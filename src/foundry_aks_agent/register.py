import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import ExternalAgentDefinition
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential


def register(project: AIProjectClient, name: str, agent_id: str) -> str:
    try:
        existing = project.agents.get(agent_name=name)
    except ResourceNotFoundError:
        pass
    else:
        definition = existing.versions.latest.definition
        if isinstance(definition, ExternalAgentDefinition) and definition.otel_agent_id == agent_id:
            return agent_id
        raise RuntimeError("Agent name already exists with a different kind or telemetry identity")
    project.agents.create_version(
        agent_name=name,
        description="A minimal Pydantic AI agent whose runtime stays on AKS.",
        definition=ExternalAgentDefinition(otel_agent_id=agent_id),
    )
    registered = project.agents.get(agent_name=name)
    definition = registered.versions.latest.definition
    if not isinstance(definition, ExternalAgentDefinition) or definition.otel_agent_id != agent_id:
        raise RuntimeError("Registration readback did not match the requested external agent ID")
    return definition.otel_agent_id


def main() -> None:
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            credential=credential,
            allow_preview=True,
        ) as project,
    ):
        agent_id = register(
            project,
            os.environ.get("AGENT_NAME", "boring-aks-agent"),
            os.environ.get("OTEL_AGENT_ID", "boring-aks-agent-demo"),
        )
        print(f"Registered external agent with otel_agent_id={agent_id}")
