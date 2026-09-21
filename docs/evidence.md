# Deployment verification

Verify that an authenticated request executes on AKS and that its exact native
trace appears in the Foundry project's connected Application Insights resource
and external-agent trace view. A health check, registration record, or unrelated
trace does not satisfy this verification.

Each verification result applies only to the deployment state and request under
test.

## Required evidence

| Source | Required evidence |
| --- | --- |
| Authorization probe | A separate `POST /ask` request without a bearer token returns `401` and does not call the model |
| Client response | An authenticated request returns `answer`, `trace_id`, `agent_id`, `release_id`, `pod_name`, and `pod_namespace` |
| Deployed workload | The Deployment uses a digest-pinned image, the ConfigMap contains the matching source commit, and the responding pod reports the same image digest |
| External-agent registration | SDK readback returns an external definition whose `otel_agent_id` equals the runtime `OTEL_AGENT_ID` |
| Application Insights | The response `trace_id` identifies one `POST /ask` request span, one native `invoke_agent` span, and one native `chat` span with the expected parent chain |
| Foundry | The external agent's **Traces** view contains the same trace ID, agent span, and model span |
| Evaluation | A one-off agent-scoped trace evaluation completes and reports the `intent_resolution` criterion over the synthetic interactions |
| Insights | The agent's **Insights** tab accepts the dedicated GPT-5 judge deployment and starts an on-demand scan |

The authorization probe is separate from the successful request and produces no
model or trace evidence. All client-response, workload, telemetry, and Foundry
evidence must refer to the same authenticated request. Use synthetic,
non-sensitive prompt content.

## Correlate the request

1. Follow [deployment step 5](deployment.md#5-prove-an-authenticated-aks-model-request)
   to run the separate authorization probe and authenticated request.
2. Record the authenticated response and its `trace_id`, `agent_id`,
   `release_id`, `pod_name`, and `pod_namespace`.
3. Compare the response with the Deployment image, ConfigMap release ID, and
   responding pod image ID.
4. Follow [deployment step 6](deployment.md#6-register-and-prove-foundry-attribution).
5. Query the connected Application Insights resource for the response
   `trace_id`.
6. Open the external agent in Foundry and locate the same trace.
7. Run the one-off evaluation and open the resulting Foundry Evaluation entry.
8. Start an on-demand Insights scan with the dedicated GPT-5 judge deployment.

The native trace has this parent chain:

```text
POST /ask
└── invoke_agent <agent-name>
    └── chat <model-deployment>
```

The three spans share the response trace ID and registered
`gen_ai.agent.id`. The request span carries `demo.release_id`. The exported
resource attributes identify the serving pod and namespace.

## Acceptance criteria

- The unauthenticated request returns `401`.
- The authenticated request returns a model answer and a 32-character lowercase
  hexadecimal `trace_id`.
- The response release ID equals the ConfigMap release ID and the source commit
  associated with the deployed image.
- The Deployment and responding pod use the same non-placeholder image digest.
- Registration readback returns the same agent ID as the response and trace
  spans.
- Application Insights contains exactly one native agent span and one native
  model span for the request.
- Parent IDs connect the request, agent, and model spans in order.
- Foundry displays the same trace under the registered external agent.
- The model span contains the synthetic input and output content used by the
  evaluator.
- The agent-scoped `intent_resolution` evaluation completes and reports
  criterion counts.
- Foundry accepts the judge deployment and starts the agent's on-demand Insights
  scan without a managed-identity setup warning.

## Reject incomplete evidence

Do not substitute any of these signals for the complete correlation:

- `GET /healthz` returns `200`.
- The pod reports `Ready`.
- The model deployment reports `Succeeded`.
- External-agent registration succeeds.
- Application Insights contains an unrelated trace.
- Foundry displays a trace with a different request, release, pod, or agent ID.
- An evaluation succeeds against traces from a different agent or without the
  synthetic message content.

If Application Insights contains the trace but Foundry does not, check project
linkage, viewer permissions, registration identity, time range, and preview
support. If neither contains the trace, check exporter errors and outbound
connectivity. Record missing evidence as a failed verification.

For AKS operations that remain nonterminal, use the
[provisioning diagnostics](infrastructure.md#diagnose-a-public-ip-feature-gate)
before any retry or replacement deployment.
