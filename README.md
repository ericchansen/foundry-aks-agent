# Foundry AKS agent

One Pydantic AI agent runs on AKS, serves an authenticated HTTP endpoint, and
makes one model call per request. Foundry Path A adds external-agent registration
and attributed traces. **Execution stays on AKS.**

> [!IMPORTANT]
> This project uses Microsoft's
> [external-agent registration for observability and evaluation (preview)](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent).
> Foundry stores registration metadata and matches OpenTelemetry traces by
> `gen_ai.agent.id`; it does not host, proxy, or invoke the AKS runtime.
> Microsoft provides the preview without a service-level agreement and does not
> recommend it for production workloads.

![The CLI reaches the authenticated AKS agent through a loopback port-forward. The agent calls a Foundry model; a separate telemetry path connects Application Insights to Foundry.](docs/assets/architecture.svg)

**[Documentation](https://ericchansen.github.io/foundry-aks-agent/)** ·
[Microsoft external agents (preview)](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent) ·
[Architecture](docs/architecture.md) ·
[Deploy and verify](docs/deployment.md) ·
[Verification](docs/evidence.md)

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

This repository contains a single-operator, synthetic-data reference deployment.
It includes a private AKS application service, shared bearer authentication,
Workload Identity, one model call per request, Path A external-agent registration,
and correlated native traces. The [verification guide](docs/evidence.md) defines
the evidence required for a deployment. Read the
[security boundaries](docs/security.md) before deployment.

Path B (APIM/AI Gateway), evaluation, tools, document search, ingestion, and an
agent web UI are outside this repository. External registration is metadata and
telemetry integration, not hosted-agent feature parity or a Foundry invocation
endpoint.

## License

This project uses the [MIT License](LICENSE).
