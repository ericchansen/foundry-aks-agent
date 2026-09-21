# Security & boundaries

This is a single-operator synthetic-data demo, not a production authorization
design. A shared caller token is not user identity or human delegation.

The Microsoft Foundry
[external-agent feature is in public preview](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent).
Microsoft provides the preview without a service-level agreement and does not
recommend it for production workloads. This repository uses registration, trace visibility, and one-off trace
evaluation from that feature.

## Network and identity

The [ClusterIP service](https://github.com/ericchansen/foundry-aks-agent/blob/main/deploy/service.yaml)
has no public application ingress. Operators reach it through a
[loopback-only port-forward](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/)
authorized by Kubernetes RBAC. Never publish the HTTP service directly.
The [CLI](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/client.py)
refuses remote plaintext HTTP and does not follow redirects.

ClusterIP does not isolate the service from other cluster workloads. Use a
controlled cluster and retain bearer authentication. Only the application is
private: the [infrastructure](infrastructure.md#ownership-and-stages) uses a
public, Entra/RBAC-protected AKS API and public Azure model/registry/telemetry
endpoints. No Private Link or private-cluster networking is implemented.

[AKS Workload Identity](https://learn.microsoft.com/en-us/azure/aks/workload-identity-overview)
supplies pod-to-Azure credentials. No model key is stored. Assign only the
required model-access role to the workload identity; the control-plane and
kubelet identities serve separate purposes.

## Secrets and workload hardening

Keep the caller token in a Kubernetes Secret. Rotate it by updating the Secret
and restarting the deployment, then update the client. Do not put it in
arguments, logs, screenshots, or shell transcripts.

The [deployment manifests](https://github.com/ericchansen/foundry-aks-agent/tree/main/deploy)
use a non-root pod, read-only root filesystem, dropped capabilities, writable
`/tmp`, resource limits, and health probes. The namespace enforces restricted
Pod Security. One replica and `Recreate` deliberately accept rollout downtime.
See the [operator workflow](infrastructure.md#apply-the-private-runtime).

## Telemetry content

[Pydantic instrumentation](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/runtime.py)
records prompt and response content so Foundry can display and evaluate the
synthetic interactions. Binary content remains disabled. Use only synthetic,
non-sensitive prompts: message content is retained in telemetry, and provider
exceptions may include service error details in framework spans.

[Tracing](https://github.com/ericchansen/foundry-aks-agent/blob/main/src/foundry_aks_agent/telemetry.py)
is fully sampled for this low-volume demo. Scoped enrichment sets `gen_ai.agent.id`
on spans created during an agent request without tagging unrelated work.
The native Pydantic run/model spans are retained; no duplicate `invoke_agent`
span is added. Azure Monitor export is asynchronous. The Foundry project
identity receives Foundry User on the Foundry account for judge-model inference
and only the Application Insights Reader, Monitoring Reader, Log Analytics
Reader, and protected-content reader roles required for tracing, evaluation,
and Insights.

## Approval and cleanup

Before cloud writes, agree on resource ownership, tenant/subscription, region,
sizing, model, spending controls, expiration, and cleanup scope. The
[approval boundary](deployment.md#approval-boundary) covers the separately
managed AKS node resource group, build costs, calls, and telemetry.

Remove only explicitly approved, demo-owned resources. Deleting the
[external registration](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent)
does not stop AKS execution or delete ingested spans. Follow the
[cleanup procedure](deployment.md#cleanup), including credential files,
port-forwards, token revocation, and retention requirements.
