# Deployment evidence

**Live AKS request, Path A registration, and attributed native traces
demonstrated.** This dated record comes from the deployed workload, Foundry SDK,
and project-linked Application Insights, not local mocks or health checks alone.
It does not report the deployment's current availability.

## Deployment record

Observed on September 9-10, 2026, through Azure CLI, ARM, and the Foundry SDK:

| Component | Observed result |
| --- | --- |
| Dedicated registry and serving image | Remote build succeeded; image pinned by digest |
| Foundry account, project, and model deployment | Created; `gpt-4.1-mini` deployment reports `Succeeded` |
| Workload identity | Federation uses the successful cluster's issuer; the pod obtained model access without a model key |
| Application Insights and Log Analytics | Deployed telemetry connection equals the project SDK connection; the exact request's spans were ingested |
| AKS | ARM deployment succeeded at 02:35 UTC; two Ready system nodes and a Ready application pod |
| Authenticated AKS model request | Real `gpt-4.1-mini` response at 02:53 UTC; missing bearer token returns 401 |
| External-agent registration | SDK readback confirms external definition and `otel_agent_id=boring-aks-agent-demo` |
| Attributed live traces | One root request, one native `invoke_agent`, and one native `chat`, joined by parent IDs with matching agent/pod/trace identity |
| Foundry portal | External agent's Traces view shows the same completed trace; its trajectory displays all three spans, one chat call, and 40 total tokens |

All provisioned resources were demo-exclusive, including the separate
[AKS-managed node resource group][node-rg]. The running image was built from
[commit `7603850`](https://github.com/ericchansen/foundry-aks-agent/commit/7603850f8101acb9af149eaf288acaae25270df8)
and had digest
`sha256:533deda0bb62a71f719ed76e0443f00f9e3e44cfaea832bb26164bd8ed673d64`.
The responding pod's spec and container image ID both matched this digest.

## Live request evidence

The synthetic prompt was `Reply with a short greeting.` The authenticated
response, recorded at `2026-09-10T02:53:26Z`, contained:

```json
{
  "answer": "Hello! How can I help you today?",
  "trace_id": "bd3a4ddca4ad0a724bebf413a9750abe",
  "agent_id": "boring-aks-agent-demo",
  "release_id": "7603850f8101acb9af149eaf288acaae25270df8",
  "pod_name": "boring-agent-76d7bf87fc-8l6zs",
  "pod_namespace": "boring-agent"
}
```

The project-linked query returned these successful spans for that exact
`operation_Id` at `2026-09-10T02:53:44Z`:

| Span | ID | Parent ID |
| --- | --- | --- |
| `POST /ask` | `16e5babf5388bb63` | `bd3a4ddca4ad0a724bebf413a9750abe` |
| `invoke_agent boring-aks-agent` | `f5a19aaf15de1498` | `16e5babf5388bb63` |
| `chat gpt-4.1-mini` | `487739365f2b3dc0` | `f5a19aaf15de1498` |

All three carried `gen_ai.agent.id=boring-aks-agent-demo` and exported
`cloud_RoleInstance=boring-agent-76d7bf87fc-8l6zs`. The root carried the response's
`demo.release_id`; the model span recorded 30 input tokens and 10 output tokens.
The Insights query API encoded `success` as the string `"True"` in these rows.
Evidence consumers must recognize that encoding without treating `"False"` as
truthy. The root's exported parent value is shown as observed; the two native
spans have the expected request-to-agent-to-model parent chain.

An initial deployment exported these spans despite an auxiliary resource-envelope
warning. The exporter now receives the runtime's explicit tracer provider rather
than falling back to the global proxy. The final image above was rebuilt,
redeployed, and exercised with a new request; its logs no longer showed that warning.

The Foundry portal was also inspected under **Build > Agents > boring-aks-agent >
Traces** on September 10. Trace `bd3a4ddca4ad0a724bebf413a9750abe` was
`Completed`, with 30 input tokens and 10 output tokens. Opening it displayed
`POST /ask -> invoke_agent boring-aks-agent -> chat gpt-4.1-mini`.
The root's metadata showed the matching stable agent ID and release ID.
The trace-dialog screenshot was captured in the operator session; no tenant
URL, account identity, endpoint, or credentials are published here.

## AKS provisioning diagnosis

Three initial cluster attempts across two regions were removed after bounded
waits without usable control planes. Those waits were not service-returned
terminal failures. The subsequent IaC deployment precreated the bootstrap
identities and reconciled the cluster, but still did not create node resources.

The investigation initially focused on `ControlPlaneNotFound` and high-level
operation status. **The actionable error was already in saved node-RG activity
logs and was missed:** public-IP creation failed with
`SubscriptionNotRegisteredForFeature`, naming
`Microsoft.Network/AllowBringYourOwnPublicIpAddress`. The same failure was
confirmed in each earlier attempt's node RG. Region changes, identity changes,
and longer waits did not address this prerequisite.

Policy activity established the cause of the unexpected feature requirement:
an inherited management-group policy appended `FirstPartyUsage` IP tags to
public-IP requests. This was distinct from ordinary resource tags and was not
a customer-owned address or prefix requested by the IaC.

After explicit authorization, the feature reached `Registered` and the
`Microsoft.Network` provider refresh completed on September 10 at 02:30 UTC.
The existing IaC-backed cluster was retained; no replacement cluster or custom
IP prefix was created for this fix. The same reconciliation then created its
public IP, load balancer, network security group, and virtual network; the
public IP reported `Succeeded` with a `FirstPartyUsage` tag. The same ARM
deployment completed at 02:35 UTC, followed by Ready nodes and the live evidence
above. See the
[failed-child-write diagnostics and targeted remediation](infrastructure.md#public-ip-feature-gate-hidden-by-a-nonterminal-aks-operation).

The original empty attempts and node groups were removed. The IaC-backed cluster
and dedicated foundations remained running at the time of this record.

## Reproduce the correlation

Follow [deploy and demonstrate](deployment.md) against an approved deployment.
Agent execution stays on AKS; the operator performs only client requests,
registration, deployment, and telemetry queries. Require evidence for the same
request across client output, image/pod, project-linked telemetry, and Foundry.
Record failures and missing evidence explicitly. Evaluation remains deferred.

[node-rg]: https://learn.microsoft.com/en-us/azure/aks/faq#why-are-two-resource-groups-created-with-aks
