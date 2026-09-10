# Foundry AKS agent

One Pydantic AI agent runs on AKS, serves an authenticated HTTP endpoint, and
makes one model call per request. Foundry Path A adds external-agent registration
and attributed traces. **Execution stays on AKS.**

![The CLI reaches the authenticated AKS agent through a loopback port-forward. The agent calls a Foundry model; a separate telemetry path connects Application Insights to Foundry.](docs/assets/architecture.svg)

**[Documentation](https://ericchansen.github.io/foundry-aks-agent/)** ·
[Architecture](docs/architecture.md) ·
[Deploy and demonstrate](docs/deployment.md) ·
[Evidence](docs/evidence.md)

## Start locally

Use Python 3.12 and [uv](https://docs.astral.sh/uv/):

```powershell
uv sync --locked --all-extras
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

Local tests do not call Azure. Continue with [local development](docs/development.md),
[configuration](docs/configuration.md), and the
[staged infrastructure workflow](docs/infrastructure.md).

## Scope

A live authenticated AKS model call, Path A registration, and matching native
traces are [demonstrated in the deployment record](docs/evidence.md).
This is a single-operator, synthetic-data demo with a private application
service, shared bearer token, and Workload Identity. Read the
[security boundaries](docs/security.md) before deploying.

Path B (APIM/AI Gateway), evaluation, tools, document search, ingestion, and an
agent web UI are deferred. External registration is
[preview metadata/telemetry integration](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent),
not hosted-agent feature parity or a Foundry invocation endpoint.
