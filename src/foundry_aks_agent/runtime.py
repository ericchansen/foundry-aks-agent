from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI
from opentelemetry.sdk.trace import TracerProvider
from pydantic_ai import Agent, InstrumentationSettings
from pydantic_ai.capabilities import Instrumentation
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from foundry_aks_agent.config import Settings
from foundry_aks_agent.telemetry import create_provider


def create_agent(model: Model, settings: Settings, provider: TracerProvider) -> Agent[None, str]:
    return Agent(
        model,
        name=settings.agent_name,
        instructions="Answer the user's question briefly. Do not request or use tools.",
        retries=0,
        capabilities=[
            Instrumentation(
                settings=InstrumentationSettings(
                    tracer_provider=provider,
                    include_content=True,
                    include_binary_content=False,
                    version=5,
                )
            )
        ],
    )


@dataclass
class Runtime:
    settings: Settings
    provider: TracerProvider
    agent: Agent[None, str]

    async def answer(self, prompt: str) -> str:
        result = await self.agent.run(
            prompt,
            usage_limits=UsageLimits(request_limit=1),
            model_settings={"max_tokens": 128, "timeout": 45},
        )
        return result.output


@asynccontextmanager
async def open_runtime(settings: Settings) -> AsyncIterator[Runtime]:
    provider = create_provider(settings)
    try:
        async with DefaultAzureCredential() as credential:
            async with AsyncAzureOpenAI(
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
                azure_ad_token_provider=get_bearer_token_provider(
                    credential, "https://cognitiveservices.azure.com/.default"
                ),
                max_retries=0,
                timeout=45,
            ) as client:
                model = OpenAIChatModel(
                    settings.azure_openai_deployment,
                    provider=OpenAIProvider(openai_client=client),
                )
                yield Runtime(settings, provider, create_agent(model, settings, provider))
    finally:
        provider.shutdown()
