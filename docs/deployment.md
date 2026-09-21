# Deploy and verify

Deploy the private workload, send an authenticated model request, and locate
that same request in Foundry. Agent execution stays on AKS; the operator performs
only client requests, registration, deployment, and telemetry queries.

The [verification guide](evidence.md) defines the evidence required for one
request and deployment.

## Approval boundary

Before cloud writes, agree on the subscription/tenant, region, resource ownership,
cluster sizing, model deployment, spending limit, expiration, and cleanup scope.
Include AKS's [managed node resource group][node-rg], registry/build charges,
model calls, and telemetry ingestion. Budget alerts are not a hard spending cap.
An unanswered approval request is not approval.

Either approve dedicated resources or explicitly approve reuse of named existing
ones. Do not change unrelated projects, registries, identity grants, or telemetry
connections. Use the [staged Bicep infrastructure workflow](infrastructure.md)
to create or reconcile the dedicated foundations, preauthorize separate
control-plane/kubelet identities, and deploy AKS. Its private parameter files
also drive the runtime deployment helper. The manual steps below explain the
same wiring and evidence requirements. Follow the
[AKS Workload Identity guide][identity] for a Linux/amd64
cluster with OIDC and Workload Identity enabled, an ACR, and a dedicated
user-assigned managed identity.

Plan for the [documented system-pool minimum][system-pool]: at least two nodes,
each with at least four vCPUs and 4 GB memory. The single application replica
does not imply a single-node cluster. Check subscription-specific SKU restrictions
and regional/family quota before approval; a listed SKU is not a capacity guarantee.

The Foundry project must have an [Application Insights resource connected][external].
Export to that exact resource. Path A needs no inbound connection from Foundry to
AKS, no public application endpoint, and no APIM.

## 1. Prepare an isolated operator context

The examples use PowerShell, Azure CLI, kubectl, and Python 3.12 with uv.
Replace placeholders with approved values. Stop after any failed native command;
PowerShell does not automatically terminate on every nonzero exit code.

```powershell
$Subscription = '<approved-subscription-id>'
$Tenant = '<approved-tenant-id>'
$AksResourceGroup = '<approved-aks-resource-group>'
$AksName = '<approved-cluster>'
$Context = 'boring-agent-approved'
$Namespace = 'boring-agent'
$Kubeconfig = Join-Path ([IO.Path]::GetTempPath()) ("boring-agent-" + [guid]::NewGuid() + ".kubeconfig")
$Rendered = '<private-directory-outside-the-repository>'

az login --tenant $Tenant
az account show --subscription $Subscription --query '{id:id,tenantId:tenantId,name:name}'
$Cluster = az aks show --subscription $Subscription -g $AksResourceGroup -n $AksName -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $Cluster.provisioningState -ne 'Succeeded' -or -not $Cluster.identityProfile.kubeletidentity.objectId) {
    throw 'AKS is not ready: require Succeeded and a kubelet identity before deployment'
}
az aks get-credentials --subscription $Subscription -g $AksResourceGroup -n $AksName --file $Kubeconfig --context $Context
```

Do not treat a successful CLI wait exit code or an accepted ARM write as proof
of readiness. After credential retrieval, the platform operator must also
confirm that the Kubernetes API responds and the intended nodes are Ready.

Use non-admin credentials and restrict the kubeconfig file to the operator.
Every kubectl command below explicitly identifies its context and namespace.
Operators need scoped read access and `create` on `pods/portforward`, not
cluster-admin. Have the platform owner establish namespace/RBAC as needed.

Copy the five `deploy` manifests into `$Rendered`. Keep tenant-specific rendered
values and secrets out of source control. The namespace enforces restricted Pod
Security; the pod runs as UID/GID 10001 with no capabilities, a read-only root,
writable `/tmp`, resource limits, and health probes. It uses a single replica
with `Recreate`, accepting rollout downtime. The [downward API][downward] supplies
pod identity. ClusterIP does not isolate the service from other cluster workloads;
use a controlled cluster and keep the bearer-token requirement.

## 2. Wire Workload Identity and model access

Only an approved identity/RBAC administrator should execute these writes:

```powershell
$IdentityResourceGroup = '<approved-identity-resource-group>'
$IdentityName = '<dedicated-managed-identity>'
$ModelResourceId = '<approved-Azure-OpenAI-account-resource-id>'
$Issuer = az aks show --subscription $Subscription -g $AksResourceGroup -n $AksName --query oidcIssuerProfile.issuerUrl -o tsv
$ClientId = az identity show --subscription $Subscription -g $IdentityResourceGroup -n $IdentityName --query clientId -o tsv
$PrincipalId = az identity show --subscription $Subscription -g $IdentityResourceGroup -n $IdentityName --query principalId -o tsv

az identity federated-credential create --subscription $Subscription -g $IdentityResourceGroup --identity-name $IdentityName --name boring-agent-aks --issuer $Issuer --subject 'system:serviceaccount:boring-agent:boring-agent' --audiences 'api://AzureADTokenExchange'
az role assignment create --subscription $Subscription --assignee-object-id $PrincipalId --assignee-principal-type ServicePrincipal --role 'Cognitive Services OpenAI User' --scope $ModelResourceId
```

Put the **client ID** in the rendered service-account annotation. The role grant
uses the **principal ID**. Preserve the issuer's trailing slash. The required
`azure.workload.identity/use: "true"` pod label enables the webhook's projected
federation token, independent of the disabled automatic Kubernetes API token.
The app uses `DefaultAzureCredential` and the
`https://cognitiveservices.azure.com/.default` scope. See [federation][identity]
and [model RBAC][model-rbac]. Never add a model API key to bypass failed identity.

Separately grant the AKS **kubelet identity** registry pull access: `AcrPull` for
non-ABAC registries, or appropriate repository-reader access for ABAC registries.
Follow [AKS/ACR integration][acr]; do not attach an unrelated shared registry.

## 3. Build and pin an immutable release

Require a clean, committed source tree. Choose one approved build path:

```powershell
git --no-pager status --porcelain
$Release = git rev-parse HEAD
$AcrName = '<approved-registry>'
$LoginServer = az acr show --subscription $Subscription -n $AcrName --query loginServer -o tsv
$ImageTag = "${LoginServer}/boring-agent:${Release}"

# Local build, with a running Docker daemon:
az acr login --subscription $Subscription -n $AcrName
docker build --platform linux/amd64 --label "org.opencontainers.image.revision=$Release" -t $ImageTag .
docker push $ImageTag

# OR an approved billable ACR build, without local Docker:
az acr build --subscription $Subscription -r $AcrName --platform linux/amd64 --image "boring-agent:${Release}" .
```

Review `.dockerignore` before uploading context. The image installs the committed
`uv.lock`, excludes administrative registration dependencies, and runs Python
3.12. See [ACR builds][acr-build].

```powershell
$Digest = az acr repository show --subscription $Subscription -n $AcrName --image "boring-agent:${Release}" --query digest -o tsv
if ($LASTEXITCODE -ne 0 -or $Digest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'No verified image digest' }
$PinnedImage = "${LoginServer}/boring-agent@${Digest}"
```

Set the rendered Deployment image to `$PinnedImage` and ConfigMap `RELEASE_ID`
to `$Release`. Replace all remaining `REPLACE_` values using the settings in
[configuration reference](configuration.md). Never deploy the all-zero sentinel digest or a mutable
tag. Record the commit, build ID, and digest. For an OCI index, retain the mapping
to the platform manifest digest shown by the running container.

## 4. Deliver secrets and deploy

Supply a cryptographically random caller token of at least 32 characters and
the connection string from the project's connected Application Insights.
The manifests reference `boring-agent-secrets`; they intentionally contain no
Secret or secret values.

One delivery option uses private, operator-only UTF-8 files without BOM or
trailing newline. Never put secret literals in command arguments or shell history:

```powershell
$TokenFile = '<private-token-file>'
$InsightsFile = '<private-connection-string-file>'
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace apply -f (Join-Path $Rendered 'namespace.yaml')
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace create secret generic boring-agent-secrets --from-file="AGENT_API_TOKEN=$TokenFile" --from-file="APPLICATIONINSIGHTS_CONNECTION_STRING=$InsightsFile"
```

This is a first-use Secret creation; use the approved rotation process if it
already exists. Remove delivery files promptly and restrict Secret RBAC.
Base64 is not encryption. Do not dump secrets or run `kubectl diff` against them.

```powershell
$Unresolved = Get-ChildItem $Rendered -Filter '*.yaml' | Select-String -Pattern 'REPLACE_|sha256:0{64}'
if ($Unresolved) { throw 'Unresolved deployment placeholders' }
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace apply --dry-run=server -f $Rendered
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace apply -f $Rendered
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace rollout status deployment/boring-agent --timeout=300s
```

For each release, update the image and matching ConfigMap together.
Secret/ConfigMap environment changes alone do not restart pods: explicitly
`rollout restart deployment/boring-agent` with the same context flags when needed.
For rollback, restore the prior digest **and** its matching settings; `rollout
undo` alone does not restore mutable ConfigMaps or Secrets.

## 5. Prove an authenticated AKS model request

In one terminal, keep this [loopback-only port-forward][forward] attached:

```powershell
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace port-forward --address 127.0.0.1 service/boring-agent 8000:8000
```

In another terminal, first confirm an unauthenticated request returns **401**:

```powershell
curl.exe -i -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' --data-raw '{"prompt":"Reply with a short greeting."}'
```

Then securely load the caller token into the CLI's environment:

```powershell
$SecureToken = Read-Host 'Demo bearer token' -AsSecureString
try {
    $env:AGENT_API_TOKEN = [System.Net.NetworkCredential]::new('', $SecureToken).Password
    $Reply = uv run --locked aks-agent --prompt 'Reply with a short greeting.' | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Agent request failed' }
    $Reply
    if ($Reply.trace_id -notmatch '^[0-9a-f]{32}$') { throw 'Missing trace identity' }
} finally {
    Remove-Item Env:AGENT_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Variable SecureToken -ErrorAction SilentlyContinue
}
```

The actual request schema is `{"prompt":"..."}`; OpenAPI endpoints are disabled.
Use synthetic data only. The response must contain an answer, `trace_id`,
`agent_id`, `release_id`, `pod_name`, and `pod_namespace`.
Compare these with the workload:

```powershell
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace get deployment boring-agent -o jsonpath='{.spec.template.spec.containers[0].image}'
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace get configmap boring-agent-config -o jsonpath='{.data.RELEASE_ID}'
kubectl --kubeconfig $Kubeconfig --context $Context -n $Namespace get pods -l app.kubernetes.io/name=boring-agent -o 'custom-columns=NAME:.metadata.name,NAMESPACE:.metadata.namespace,IMAGE_ID:.status.containerStatuses[0].imageID,READY:.status.containerStatuses[0].ready'
```

HTTP health is not model authorization. Preserve the synthetic response,
timestamp, commit/digest, actual pod/image ID, and trace ID as demonstration
evidence outside the public repository. Do not enable HTTP debug logs or shell
transcripts around secrets. The shared bearer token is a single-operator demo
credential, not per-user authorization or human delegation.

## 6. Register and prove Foundry attribution

Use an approved administrative identity with project registration permissions
and Reader/Monitoring Reader on the connected Insights resource. Set the
administrative environment to match the runtime:

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = '<approved-project-endpoint>'
$env:AGENT_NAME = 'boring-aks-agent'
$env:OTEL_AGENT_ID = 'boring-aks-agent-demo'
uv run --locked --extra admin aks-agent-register
```

The tool uses `allow_preview=True`, creates metadata, and reads back
`ExternalAgentDefinition.otel_agent_id`. A matching existing record is reused;
a name belonging to another kind/identity is rejected without overwriting it.
It does not deploy or invoke anything. See [Path A and its preview limits][external].

Allow ingestion time, then query **the project's connected Application Insights
resource**. This is the Application Insights table schema:

```kusto
union withsource=TableName requests, dependencies
| where timestamp > ago(1h)
| where operation_Id == "<returned-32-hex-trace_id>"
| extend AgentId = tostring(customDimensions["gen_ai.agent.id"]),
         Operation = tostring(customDimensions["gen_ai.operation.name"]),
         Model = tostring(customDimensions["gen_ai.request.model"])
| project timestamp, TableName, operation_Id, id, operation_ParentId,
          name, AgentId, Operation, Model, success, duration,
          cloud_RoleName, cloud_RoleInstance, customDimensions
| order by timestamp asc
```

Require one native `invoke_agent` span and one native `chat` span in this trace,
connected by parent IDs, both tagged with the registered agent ID. The root
`POST /ask` carries `demo.release_id`; use that and the exported pod/resource
attributes to connect the trace to the response and deployment. Inspect actual
exported fields rather than assuming every resource attribute is copied verbatim.
For workspace queries, the corresponding tables are `AppRequests` and
`AppDependencies`, with `OperationId`, `ParentId`, and `Properties`.
See the [telemetry data model][data-model].

Open [Foundry](https://ai.azure.com), select the approved project, then the
external agent under **Agents**, and its **Traces** view. Locate the same trace
and agent/model spans; record a redacted screenshot or trace link. Client routing
must remain unchanged through the AKS service.

If KQL has spans but Foundry does not, check project linkage, viewer permissions,
registration identity, time range, and preview support. If neither has spans,
check exporter errors and allowed outbound connectivity. Do not substitute a
successful registration, healthy pod, unrelated trace, or generic Azure Monitor
visibility for this evidence. Evaluation and Path B are outside this repository.

## Cleanup

Stop port-forward with Ctrl+C. Remove the isolated kubeconfig and secret delivery
files. Revoke the demo token and remove only explicitly approved workload,
registration, federation, role grants, images, and infrastructure.
Delete a namespace only if it is exclusively demo-owned.

For dedicated approved cluster teardown, account for the managed node resource
group and residual disks/IPs. Never blindly delete either resource group or
shared project/model/Insights resources. Preserve telemetry according to its
owner's retention policy. [Deleting the external registration][external] does
not stop AKS execution or delete ingested spans.

[external]: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/register-external-agent
[identity]: https://learn.microsoft.com/en-us/azure/aks/workload-identity-deploy-cluster
[system-pool]: https://learn.microsoft.com/en-us/azure/aks/use-system-pools
[node-rg]: https://learn.microsoft.com/en-us/azure/aks/faq#why-are-two-resource-groups-created-with-aks
[model-rbac]: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/role-based-access-control
[acr]: https://learn.microsoft.com/en-us/azure/aks/cluster-container-registry-integration
[acr-build]: https://learn.microsoft.com/en-us/azure/container-registry/container-registry-tutorial-quick-task
[downward]: https://kubernetes.io/docs/concepts/workloads/pods/downward-api/
[forward]: https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/
[data-model]: https://learn.microsoft.com/en-us/azure/azure-monitor/app/data-model-complete
[operation-status]: https://learn.microsoft.com/en-us/rest/api/aks/operation-status-result/get
