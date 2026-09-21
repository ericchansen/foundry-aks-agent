from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    agent_api_token: SecretStr = Field(min_length=32)
    azure_openai_endpoint: str
    azure_openai_deployment: str = Field(min_length=1)
    azure_openai_api_version: str = "2024-10-21"
    applicationinsights_connection_string: SecretStr
    otel_agent_id: str = Field(default="boring-aks-agent-demo", min_length=1)
    agent_name: str = Field(default="boring-aks-agent", pattern=r"^[a-zA-Z0-9_-]+$")
    agent_version: str = Field(default="1", min_length=1)
    release_id: str = Field(min_length=1)
    pod_name: str = Field(min_length=1)
    pod_namespace: str = Field(min_length=1)

    @field_validator("azure_openai_endpoint")
    @classmethod
    def require_https(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or "?" in value
            or "#" in value
        ):
            raise ValueError(
                "Model endpoint must be an HTTPS origin "
                "without credentials, path, query, or fragment"
            )
        return value.rstrip("/")
