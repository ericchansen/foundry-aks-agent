# Configuration

Configure the runtime through process environment variables or Kubernetes
ConfigMap/Secret references. Never commit tenant-specific settings or secrets.
The [settings model](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/config.py)
is the authoritative validation contract.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `AGENT_API_TOKEN` | Required random bearer token, at least 32 characters |
| `AZURE_OPENAI_ENDPOINT` | Required HTTPS Azure OpenAI origin; no credentials, path, query, or fragment; trailing slash normalized |
| `AZURE_OPENAI_DEPLOYMENT` | Required chat-completion model deployment name |
| `AZURE_OPENAI_API_VERSION` | Defaults to `2024-10-21` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Required connection string for the project's linked resource |
| `AGENT_NAME` | Defaults to `boring-aks-agent` |
| `OTEL_AGENT_ID` | Defaults to `boring-aks-agent-demo`; identical in runtime and registration |
| `RELEASE_ID` | Required image/release identifier |
| `POD_NAME`, `POD_NAMESPACE` | Required workload attribution, populated by Kubernetes |
| `FOUNDRY_PROJECT_ENDPOINT` | Required by administrative registration and evaluation tooling |
| `FOUNDRY_MODEL_NAME` | Judge deployment for evaluation; defaults to `gpt-5-mini` |

Use the deployment helper's [private runtime workflow](infrastructure.md#apply-the-private-runtime)
to apply these values. It delivers secrets in memory over stdin, not in committed
files. The [deployment guide](deployment.md#4-deliver-secrets-and-deploy) also
documents manual delivery.

## Model and request limits

The deployment must support chat completions and the `max_tokens` setting, such
as a compatible `gpt-4.1-mini` deployment. Use an approved existing model or
approve a new deployment before making calls.

The [application](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/app.py)
accepts a nonblank prompt of at most 4,000 characters. The
[runtime](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/runtime.py)
allows one model request, caps output at 128 tokens, sets a 45-second model
timeout, and disables retries. It has no tools or conversation store.

Native instrumentation records the synthetic prompt and response content,
model usage, and request parameters needed by the Foundry trace and evaluation
experiences. Binary content remains excluded. Do not send sensitive or
customer data to this example.

## HTTP contract

`POST /ask` accepts JSON with a `prompt` and requires a bearer token.
Use the CLI so the token stays out of command-line arguments:

```powershell
uv run --locked aks-agent --prompt "Reply with a short greeting."
```

Generate a small domain-neutral trace corpus with the same endpoint and token:

```powershell
uv run --locked aks-agent-traffic
```

The command spaces requests to respect the example deployment's
one-request-per-minute model quota.

This requires the [authorized loopback port-forward and securely loaded token](deployment.md#5-prove-an-authenticated-aks-model-request).
The [response schema](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/app.py)
contains:

| Field | Meaning |
| --- | --- |
| `answer` | Model output |
| `trace_id` | Trace to locate in project-linked telemetry |
| `agent_id` | Stable identity matching external registration |
| `release_id` | Deployed source/image release |
| `pod_name`, `pod_namespace` | Responding workload identity |

Missing/invalid bearer credentials return `401`. Invalid prompts return `422`.
Handled model failures return `502` with a trace ID. `GET /healthz` is an
unauthenticated readiness probe, **not** proof of model authorization.
OpenAPI and interactive API documentation endpoints are disabled.

## Registration

After a real AKS request, configure the admin environment and run:

```powershell
uv run --locked --extra admin aks-agent-register
```

The [registration tool](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/register.py)
uses `FOUNDRY_PROJECT_ENDPOINT`, `AGENT_NAME`, and `OTEL_AGENT_ID`.
It reuses a matching record and rejects a conflicting kind/identity without
overwriting it. Registration changes metadata only: it provisions and invokes
no runtime. See [the complete registration and attribution procedure](deployment.md#6-register-and-prove-foundry-attribution).

## Evaluation

After synthetic traffic appears under the registered external agent, run the
one-off trace evaluation:

```powershell
uv run --locked --extra admin aks-agent-evaluate
```

The evaluator uses `FOUNDRY_PROJECT_ENDPOINT`, `AGENT_NAME`, and
`FOUNDRY_MODEL_NAME`. It evaluates recent agent traces with Foundry's
built-in `intent_resolution` criterion and prints aggregate pass, fail, and
error counts. The Foundry project managed identity requires the scoped
Foundry account and Application Insights roles documented in
[deployment step 7](deployment.md#7-evaluate-the-ingested-traces).

The same `gpt-5-mini` deployment appears in the agent's **Insights** tab as the
judge model for an on-demand scan. See
[deployment step 8](deployment.md#8-run-an-on-demand-insights-scan).
