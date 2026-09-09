# Foundry AKS agent

One Pydantic AI agent runs on AKS, serves an authenticated HTTP endpoint, and
makes one model call per request. Foundry Path A adds an external-agent record
and attributed telemetry without changing client routing or hosting another
runtime. See the [external-agent contract (preview)][external].

```text
CLI -> Kubernetes port-forward -> authenticated AKS service -> Foundry model
                                           |
                                           +-> OpenTelemetry -> project-linked
                                               Application Insights -> Foundry
```

## Status and scope

This repository implements the baseline runtime, command-line client,
registration tooling, tests, and deployment assets. **The AKS workload and
Foundry demonstration are not complete.** Provisioning was approved and started:
the dedicated registry/image, Foundry project/model, identity, and connected
telemetry resources exist. AKS creation stalled in two regions without a usable
control plane; the empty cluster attempts and their managed node groups were
removed. No real AKS model request, external-agent registration, or attributed
live trace is claimed. See the [deployment record](docs/deployment.md#deployment-record).

Path B (APIM/AI Gateway), evaluation, tools, document search, ingestion, and a web
UI are deferred. External registration is preview metadata/telemetry integration,
not hosted-agent feature parity or a Foundry Responses invocation endpoint.
See [Path A][external] and the separate [Path B mechanism][custom].

## Local development

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). The project targets Windows
x64 development and Linux x64 AKS containers.

```powershell
uv sync --locked --all-extras
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

Tests replace the Azure OpenAI HTTP transport, not the Pydantic AI agent or
instrumentation. They assert a single model request, rejected unauthenticated
requests, model failures, and matching agent identity/trace IDs on real
framework-generated run and model spans. These are local contract tests, not
proof of Azure model access or Foundry ingestion.

The runtime pins Pydantic AI 2.31.1 and explicitly uses its version 5
instrumentation. The handoff's research of a newer version is not an upgrade
requirement. See [Pydantic instrumentation][pydantic-tracing].

## Run and demonstrate

Follow the [deployment and evidence guide](docs/deployment.md). Configure
environment variables through local process environment or Kubernetes
ConfigMap/Secret references, never committed tenant-specific values.

The [infrastructure workflow](infra/README.md) provides two staged Bicep
deployments: dedicated foundations and prerequisite identity roles first, then
AKS and federation. Its operator helpers preview changes, submit resumable ARM
operations, and apply the private runtime without writing secrets to disk.

| Variable | Purpose |
| --- | --- |
| `AGENT_API_TOKEN` | Required random bearer token, at least 32 characters |
| `AZURE_OPENAI_ENDPOINT` | Required HTTPS Azure OpenAI origin; no credentials, path, query, or fragment (a trailing slash is normalized) |
| `AZURE_OPENAI_DEPLOYMENT` | Required chat-completion model deployment name |
| `AZURE_OPENAI_API_VERSION` | Defaults to `2024-10-21` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Required connection string for the project's linked resource |
| `AGENT_NAME` | Defaults to `boring-aks-agent` |
| `OTEL_AGENT_ID` | Defaults to `boring-aks-agent-demo`; identical in runtime and registration |
| `RELEASE_ID` | Required image/release identifier |
| `POD_NAME`, `POD_NAMESPACE` | Required workload attribution, populated by Kubernetes |
| `FOUNDRY_PROJECT_ENDPOINT` | Required only by administrative registration tooling |

The model deployment must support chat completions and the `max_tokens` setting
(for example, a compatible `gpt-4.1-mini` deployment). Use an approved existing
model or approve a new deployment before making calls. The application has no
tools, no conversation store, no retries, a 4,000-character prompt limit, and a
128-token output limit.

Once the authorized port-forward is running:

```powershell
uv run --locked aks-agent --prompt "Reply with a short greeting."
```

The response includes the answer, trace ID, agent ID, release, pod, and namespace.
After sending an actual AKS request, create and read back the registration:

```powershell
uv run --locked --extra admin aks-agent-register
```

Registration changes metadata only. It does not provision or invoke a runtime.
The SDK is kept in the optional `admin` extra, outside the serving image.

## Security and observability boundaries

This is a single-operator synthetic-data demo. Caller authentication is a shared
random bearer token, **not** user identity or delegation. The ClusterIP service
has no public ingress; operators access it through a loopback-only,
Kubernetes-RBAC-authorized port-forward. Never publish the HTTP service directly.
The CLI refuses remote plaintext HTTP and does not follow redirects.

[AKS Workload Identity][identity] supplies pod-to-Azure credentials; no model key
is stored. Assign only the required model-access role to the workload identity.
Keep the caller token in a Kubernetes Secret, rotate it by updating the Secret
and restarting the deployment, and do not put it in command-line arguments.

Prompt/response capture is disabled in Pydantic instrumentation. Use synthetic,
non-sensitive prompts only: provider exceptions may include service error
details in framework spans. Traces are fully sampled for this low-volume demo.
Scoped span enrichment sets `gen_ai.agent.id` on each span created during an
agent request, without attaching that identity to unrelated work. The normal
Pydantic run and model spans are used; no duplicate `invoke_agent` span is added.
Azure Monitor export is asynchronous: a returned answer does not prove ingestion.

The demo is done only when the same request is identified in the client output,
the deployed AKS image/pod, and the external agent's Foundry trace view, using the
project-connected Application Insights resource. Record failures and missing
evidence explicitly. Trace evaluation is a separate, deferred milestone.

[external]: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent
[custom]: https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent
[identity]: https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview
[pydantic-tracing]: https://ai.pydantic.dev/logfire/
