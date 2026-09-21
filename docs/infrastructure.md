# Infrastructure

This is **deployment code, not evidence of a successful live deployment**. It
supports the repository's existing bearer-authenticated agent, private
`ClusterIP` service, loopback port-forward, Workload Identity model calls, and
Path A **metadata-only** external-agent registration. No APIM, ingress
controller, public application service, additional agent tools, or evaluation
stack is created.

## Ownership and stages

All directly managed resources live in **one existing, demo-exclusive resource
group** in one subscription. Do not point these templates at shared resources.
Names are explicit; there is no tenant-wide discovery or Microsoft Graph lookup.

| Stage | Resources |
| --- | --- |
| `foundation.bicep` | AIServices S0 account and project, pinned model deployment, Basic ACR (admin disabled), three distinct user-assigned identities, 30-day PerGB2018 workspace, workspace-backed Application Insights, project's AppInsights connection, scoped RBAC prerequisites |
| `cluster.bicep` | AKS Free tier, two 4-vCPU system nodes by default, precreated control-plane and kubelet identities, Entra managed authentication/Azure RBAC, disabled local accounts, OIDC/Workload Identity, Azure CNI overlay, pod federation, operator bootstrap RBAC |

**AKS creates and owns a second, separately named node resource group. Do not
precreate it.** The [AKS FAQ](https://learn.microsoft.com/azure/aks/faq#can-i-provide-my-own-name-for-the-aks-node-resource-group)
explicitly excludes an existing resource group as the node resource group.
The [managed identity documentation](https://learn.microsoft.com/azure/aks/managed-identity-overview#summary-of-managed-identities)
documents AKS's control-plane Contributor permission on its node resource group.
We let AKS establish that permission. We do **not** grant Contributor/Network
Contributor on the demo RG or subscription, nor give the kubelet network rights.
This design has no bring-your-own VNet or other network resources outside the
AKS-managed group.

The [precreated kubelet prerequisite](https://learn.microsoft.com/azure/aks/managed-identity-overview#pre-created-kubelet-managed-identity)
is implemented **before** AKS creation: the control-plane UAI receives Managed
Identity Operator on the kubelet UAI. This is a distinct supported bootstrap
path, not a claim that changing identities cures an Azure provisioning incident.

The API server is public and Entra/RBAC protected, optionally restricted to
operator CIDRs. Only the **application** is private. ACR, model and telemetry
endpoints use public Azure endpoints; the AKS standard load balancer/public IP
is for **outbound** access, not an application ingress rule. Private Link,
private-cluster networking, Azure Monitor containers add-ons, and associated
extra costs are intentionally out of scope.

## Prerequisites and preflight

- Azure CLI, **Bicep 0.45.15**, Python 3.11–3.13, the locked project dependencies
  (`uv sync --locked --all-extras`), `kubectl` and `kubelogin`. The infrastructure
  entrypoint uses only Python's standard library; runtime rendering additionally
  uses the existing PyYAML development dependency.
- Log in to the intended Azure tenant. Provide a subscription ID/name and the
  operator's **Entra object ID**, not an application/client ID. For automation
  use `operatorPrincipalType: ServicePrincipal`; groups are also supported.
- The deploying principal needs resource creation/update and role-assignment
  permissions at the demo RG, and permission for AKS to create its managed RG
  (normally appropriate subscription-level bootstrap authority). Reader plus
  Foundry User alone is not sufficient. No deployment automation identity or
  subscription-wide role assignment is created by this code.
- Providers must already be registered: `Microsoft.ContainerService`,
  `Microsoft.Compute`, `Microsoft.Network`, `Microsoft.ManagedIdentity`,
  `Microsoft.ContainerRegistry`, `Microsoft.CognitiveServices`,
  `Microsoft.OperationalInsights`, `Microsoft.Insights`. Provider registration
  and quota requests are explicit operator actions, not script side effects.
- Confirm regional Kubernetes availability, VM restrictions **including zones**,
  regional total and VM-family vCPU quota, and model/SKU capacity. For example,
  these are read-only:

  ```powershell
  $sub = '<subscription-id-or-name>'
  $location = 'eastus2'
  az aks get-versions --subscription $sub --location $location --output table
  az vm list-skus --subscription $sub --location $location --size Standard_D4s_v6 --all --output json
  az vm list-usage --subscription $sub --location $location --output table
  az cognitiveservices usage list --subscription $sub --location $location --output table
  ```

  Defaults are East US 2 in the example parameter files, Kubernetes `1.34.10`,
  `Standard_D4s_v6`, and no explicit zones. Select an available compatible SKU
  and zone list locally; absence of a restriction does not guarantee capacity.
  Keep **two system nodes**, each at least 4 vCPUs/4 GiB, as required by
  [system pool guidance](https://learn.microsoft.com/azure/aks/use-system-pools).
  Reserve at least 8 vCPUs initially and **12 for the one-node upgrade surge**.
  Account for other consumption in both regional and family quota. If using a
  different SKU, retain AMD64 compatibility with the serving image/manifests.
  Check CIDRs do not overlap networks used by your environment.

## Local parameters and safe adoption

Run from the repository root. Keep real identifiers, kubeconfig and operator
state under the already ignored `.local/` directory:

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
Copy-Item infra/foundation.parameters.example.json .local/foundation.parameters.json
Copy-Item infra/cluster.parameters.example.json .local/cluster.parameters.json
$rg = '<dedicated-demo-rg>'
```

Edit these copies before proceeding:

- Every `REPLACE_WITH_*` value must be replaced. The account and registry names
  must satisfy their Azure naming/global-uniqueness constraints. Set the real
  **existing names** when adopting dedicated resources.
- Match all three identity names, location, operator object ID/type between
  files. The identities must be distinct. The node RG must differ from `$rg`.
  `cluster.bicep` references precreated identities only in `$rg`.
- Match the existing AppInsights **connection name**, model deployment name,
  model/version/SKU/capacity, workspace and component names. Defaults are
  `gpt-4.1-mini`, `2025-04-14`, `GlobalStandard`, capacity `1`.
- Account custom subdomain defaults to its account name; endpoints in this
  demo use Azure public cloud DNS. Do not adopt an account with a different
  immutable subdomain/location. The template intentionally disables account
  key authentication; model calls must use Entra Workload Identity.
- `apiServerAuthorizedIPRanges` accepts e.g. `["<operator-egress-ip>/32"]`.
  An empty list permits public API connectivity, **not unauthenticated access**.
  Account for a changing operator/VPN egress address before restricting it.
- Normal ARM incremental deployment **reconciles** named resources: it is not
  an `existing`/read-only adoption mode. Check current properties first; tags
  and declared properties converge to these templates. Do not use
  complete deployment mode. Do not run foundation/model reconciliation during
  a serving test unless an intentional update is acceptable.
- Taggable resources inherit the existing demo RG's tags, including lifecycle
  tags such as `expiresOn`, merged with durable demo labels. Optional `tags`
  objects in each private parameter file override individual values. The RG
  itself is never retagged by either template. Keep temporary dates, budgets
  and other deployment-specific values in private parameters, not durable
  examples or documentation.

### Optional supplied SSH public key and node SSH disabling

To eliminate reliance on AKS-side key generation for a fresh bootstrap, supply
`sshPublicKey` and optionally `linuxAdminUsername` (default `azureuser`) in the
private cluster parameter file. An empty public key omits `linuxProfile`; it
does **not** assert that server-side key generation or the SSH daemon is disabled.
This option removes a bootstrap dependency; it is **not** a confirmed diagnosis
of a `Creating` operation.

Generate a **new demo-scoped RSA key**, explicitly outside the repository in a
private session directory. Never use the operator's `~/.ssh` keys. For example:

```powershell
ssh-keygen -t rsa -b 3072 -f '<private-session-directory>/aks-bootstrap-rsa' -C foundry-aks-agent-bootstrap
```

Let `ssh-keygen` prompt for a passphrase; do not put it in command arguments.
Copy only the single-line `.pub` contents into the local `sshPublicKey` parameter.
Never put the private key in parameters, Bicep, outputs, logs, or the repository.
The scripts never generate keys, read a key path, or inspect `~/.ssh`; the
entrypoint rejects private-key/multiline/non-`ssh-rsa` values. Keep the public
key value unchanged on ordinary reruns, and protect/delete the scoped private
key according to the operator's retention policy.

Node-pool SSH disabling is supported by the selected **stable `2025-10-01` API**
as `agentPoolProfiles[].securityProfile.sshAccess = Disabled`, but the current
[AKS SSH guidance](https://learn.microsoft.com/azure/aks/manage-ssh-node-access)
still lists `DisableSSHPreview` registration as a prerequisite. Consequently,
`disableNodeSsh` defaults to `false` rather than adding an undeclared
subscription-level dependency.

Prefer `disableNodeSsh: true` once the operator has confirmed the feature is
available/registered and refreshed the ContainerService provider registration:

```powershell
az feature show --subscription $sub --namespace Microsoft.ContainerService `
  --name DisableSSHPreview --query properties.state --output tsv
```

Feature/provider registration, if necessary, is an explicit parent/operator
action, never a helper side effect. The deployment helper checks the feature
state before submission when this option is enabled. Supply the public key
**even with SSH disabled** to eliminate automatic key generation independently
of SSH service configuration. Disabling SSH prevents node SSH troubleshooting;
it does not disable managed Entra authentication, Azure RBAC, `kubectl`, or
loopback application port-forwarding. No SSH ingress rule, public node IP, VM
login role, or private-key output is added.

### Existing role assignments

Azure rejects a duplicate role assignment with a new name even if its principal,
scope and role match. Before first adoption, inspect the existing assignments
at each exact resource scope:

```powershell
az role assignment list --subscription $sub --scope '<full-resource-id>' `
  --fill-principal-name false --fill-role-definition-name false `
  --query '[].{name:name,principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}' `
  --output json
```

Add the matching assignment's **GUID name** as a JSON parameter override. Do not
pass the full assignment resource ID or a different principal's assignment.
Leave the override empty/absent only when no identical assignment exists.

| Parameter | Principal | Exact scope | Role ID |
| --- | --- | --- | --- |
| `modelUserAssignmentName` | Workload UAI | AIServices account | `5e0bd9bd-7b93-4f28-af87-19fc36ad61bd` |
| `acrPullAssignmentName` | Kubelet UAI | ACR | `7f951dda-4ed3-4680-a7ca-43fe172d538d` |
| `identityOperatorAssignmentName` | Control-plane UAI | Kubelet UAI | `f1a07417-d97a-45cb-824c-7a7467783830` |
| `foundryUserAssignmentName` | Operator | Foundry project | `53ca6127-db72-4b80-b1b0-d745d6d5456d` |
| `projectInsightsReaderAssignmentName` | Project system-assigned identity | Application Insights component | `acdd72a7-3385-48ef-bd42-f606fba81ae7` |
| `clusterAdminAssignmentName` (cluster file) | Operator | AKS | `b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b` |

New assignments use stable, deterministic GUIDs. If an identity is deleted and
recreated under the same name, its principal ID changes: remove the stale role
assignments deliberately before rerunning, or use new assignment GUID overrides.
Never broaden roles to address propagation delays.

## Validate, plan, submit, resume

The demo RG must already exist. For a **new** demo only, explicitly create that
one group after confirming the name is unused:

```powershell
az group create --subscription $sub --name $rg --location $location `
  --tags workload=foundry-aks-agent purpose=exclusive-demo --output none
```

The entrypoint never creates/deletes RGs, changes the active subscription,
registers providers, or requests quota. Offline compilation requires no login:

```powershell
python -m infra.deploy validate foundation --subscription $sub --resource-group $rg --parameters .local/foundation.parameters.json
python -m infra.deploy validate cluster --subscription $sub --resource-group $rg --parameters .local/cluster.parameters.json
python -m infra.deploy plan foundation --subscription $sub --resource-group $rg --parameters .local/foundation.parameters.json
python -m infra.deploy deploy foundation --subscription $sub --resource-group $rg --parameters .local/foundation.parameters.json --confirm-resource-group $rg
python -m infra.deploy status foundation --subscription $sub --resource-group $rg --parameters .local/foundation.parameters.json
```

`validate` compiles locally and checks required/unknown parameter names; ARM
performs semantic/type/availability checks during planning/deployment.
`plan` is Azure ARM what-if, **not provisioning**. It deliberately displays only
resource IDs/change types, not resolved property payloads: full what-if output
can reveal the AppInsights connection. Review declared nonsecret properties
separately in Bicep/current resource views. Do not enable CLI `--debug`, shell
transcription, or public artifact collection of deployment responses.

**Wait for foundation `Succeeded`**, verify the scoped identity assignments,
and allow for Entra/RBAC propagation before submitting the cluster stage:

[AKS identity guidance](https://learn.microsoft.com/azure/aks/user-assigned-managed-identity)
notes role propagation can take up to **60 minutes**. The separate stages let the
operator allow that propagation window without starting AKS prematurely. No
automatic sleep, retry, cancellation, or cluster creation follows foundation
completion; submit the cluster stage explicitly when ready.

```powershell
python -m infra.deploy plan cluster --subscription $sub --resource-group $rg --parameters .local/cluster.parameters.json
python -m infra.deploy deploy cluster --subscription $sub --resource-group $rg --parameters .local/cluster.parameters.json --confirm-resource-group $rg
python -m infra.deploy status cluster --subscription $sub --resource-group $rg --parameters .local/cluster.parameters.json
```

`deploy` submits with `--no-wait` using stable deployment names
`foundry-aks-agent-foundation` and `foundry-aks-agent-cluster`, and requires the
explicit RG confirmation. It blocks resubmission while that deployment, or the
named AKS cluster, is active. This is a single-operator workflow, not a
distributed lock. Use the same parameter files on reruns.

**A local deadline, CLI disconnect, ARM deployment failure, or
`ControlPlaneNotFound` does not establish that an AKS operation is terminal.**
Inspect both deployment and AKS `provisioningState`. Do not automatically retry,
delete/recreate, or launch alternative regions while a cluster is
`Creating`/`Updating`/`InProgress`. Preserve operation IDs and inspect detailed
errors securely in Azure. The helper suppresses raw CLI errors because those
can contain connection credentials. On terminal failure, resolve the cause
before resubmitting; a resubmission reconciles existing resources.

### Diagnose a public-IP feature gate

When an AKS operation remains `InProgress` and credential retrieval returns
`ControlPlaneNotFound`, inspect **failed events in the managed node RG**, not
only the cluster resource or a capped list of mixed read/write activity:

```powershell
$nodeRg = '<the-nodeResourceGroupName-parameter>'
az monitor activity-log list --subscription $sub --resource-group $nodeRg `
  --offset 6h --status Failed --max-events 100 `
  --query '[].{time:eventTimestamp,resourceId:resourceId,operation:operationName.value,message:properties.statusMessage}' `
  --output json
```

Review detailed errors privately; do not publish tenant identifiers or
unredacted request payloads. A capped query is not an exhaustive event count.
One relevant `Microsoft.Network/publicIPAddresses/write` error is:

```text
SubscriptionNotRegisteredForFeature
Microsoft.Network/AllowBringYourOwnPublicIpAddress
```

`Microsoft.Network` being `Registered` does **not** establish that this separate
feature is registered. The feature name also does not establish that the
template requests customer-owned IP space: an
[official Azure CLI test recording](https://github.com/Azure/azure-cli/blob/dev/src/azure-cli/azure/cli/command_modules/network/tests/latest/recordings/test_network_ag_root_cert.yaml)
shows the same error for a Standard public IP carrying a `FirstPartyUsage`
IP tag, without a supplied IP address or prefix.

An inherited policy that appends `FirstPartyUsage` IP tags can introduce this
feature prerequisite. Inspect successful
`Microsoft.Authorization/policies/append/action` events and their `fields` and
`policies` metadata. An empty RG-scoped policy-assignment listing does not rule
out a management-group assignment. Do not remove or exempt a governance policy
to bypass this prerequisite.

When the exact error is present, obtain authorization for the
**subscription-level** feature change before following Microsoft's
[documented registration sequence](https://github.com/Azure-Samples/chat-with-your-data-solution-accelerator/blob/main/docs/TroubleShootingSteps.md):

```powershell
az feature register --subscription $sub --namespace Microsoft.Network `
  --name AllowBringYourOwnPublicIpAddress --output none
if ($LASTEXITCODE -ne 0) { throw 'Feature registration request failed' }
$featureState = az feature show --subscription $sub --namespace Microsoft.Network `
  --name AllowBringYourOwnPublicIpAddress --query properties.state --output tsv
if ($LASTEXITCODE -ne 0 -or $featureState -ne 'Registered') {
    throw 'Feature is not Registered. Inspect its state; Pending may require approval.'
}
az provider register --subscription $sub --namespace Microsoft.Network --wait
if ($LASTEXITCODE -ne 0) { throw 'Network provider refresh failed' }
```

Some registrations require approval; a
[Microsoft Q&A answer for this exact feature](https://learn.microsoft.com/en-us/answers/a/1536598)
describes that requirement for internal subscriptions. Do not treat `Pending`
as success or create a custom IP prefix to work around the gate. This registration
addresses only the named feature prerequisite. The RG-scoped templates and
helpers do not apply it.

Verify the **existing** operation after registration. Require successful
public-IP writes, actual node resources, cluster readiness, and the
request/trace evidence. Registration alone does not establish deployment
completion. Do not submit a competing cluster update while reconciliation
remains active.

## Apply the private runtime

After cluster `Succeeded`, confirm two Ready nodes, OIDC issuer and federation,
then obtain **user** credentials (never `--admin`; local accounts are disabled).
The operator also needs permission to read cluster user credentials. The
deploying Contributor normally has that; a separate non-deploying operator
needs an appropriate AKS Cluster User role in addition to data-plane RBAC.

```powershell
$cluster = '<the-clusterName-parameter>'
$context = 'foundry-aks-agent-demo'
$env:KUBECONFIG = Join-Path (Get-Location) '.local/demo.kubeconfig'
az aks get-credentials --subscription $sub --resource-group $rg --name $cluster `
  --file $env:KUBECONFIG --context $context --format exec --overwrite-existing
kubelogin convert-kubeconfig --login azurecli
kubectl --context $context get nodes
```

Build/push the image from a clean, committed source tree with the existing locked
Dockerfile workflow, or reuse a verified image for that source commit.
The kubelet has AcrPull; the operator building/pushing needs separate ACR build
or push permissions. The infra scripts do not grant those or build/push images.

Use an ACR digest, not a mutable tag, and its corresponding full source commit
SHA. `runtime.py` verifies the registry host and refuses an all-zero digest.
It cannot prove the image's source provenance; retain build evidence separately.

Choose a strong random bearer token (at least 32 characters) in a password
manager, and reuse it for an ordinary rerun. The runtime helper securely prompts
if `AGENT_API_TOKEN` is unset; set it without command-line arguments if you also
need it for the client in the same shell:

```powershell
$token = Read-Host 'Paste the demo bearer token' -AsSecureString
$env:AGENT_API_TOKEN = [System.Net.NetworkCredential]::new('', $token).Password
Remove-Variable token
uv run --locked --all-extras python -m infra.runtime `
  --subscription $sub --resource-group $rg `
  --foundation-parameters .local/foundation.parameters.json `
  --cluster-parameters .local/cluster.parameters.json --context $context `
  --image '<registry>.azurecr.io/boring-agent@sha256:<verified-digest>' `
  --release-id '<40-character-source-commit-sha>' `
  --agent-name boring-aks-agent --agent-id boring-aks-agent-demo
```

The helper checks the explicit kubeconfig context's server against the selected
AKS FQDN **before reading secrets or writing Kubernetes resources**. It reads the
UAI client ID and Application Insights connection string through Azure CLI,
captures them in memory, and renders the existing `deploy/*.yaml` files without
modifying them. It applies the Secret over stdin with server-side apply (no
client-side last-applied annotation), then restarts/waits for the workload so
token/config-only updates also take effect. It prints neither the bearer token
nor connection string and writes neither to local files. This is not a Key Vault
design: Kubernetes stores a normal Secret; cluster admins can read it.

No `--force-conflicts` is used. If adopting manifests owned by another field
manager, deliberately reconcile ownership/conflicts rather than overriding
blindly. Partial applies are resumable. A rollout timeout requires inspection,
not automatically deleting the namespace. Reapply uses the supplied token;
token rotation is explicit and requires a client update.

In a separate terminal with the same dedicated kubeconfig:

```powershell
kubectl --context $context --namespace boring-agent port-forward `
  --address 127.0.0.1 service/boring-agent 8000:8000
```

Keep the existing authenticated client and never put the bearer token in
`curl --header`, command arguments, logs or screenshots. Health probes are
unauthenticated; a successful readiness probe alone does not prove real model
access.

## Path A registration and telemetry

The project connection uses
`Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01`,
`ApiKey`/`AppInsights`, with **both** `target` and `credentials.key` equal to the
component's connection string and `metadata.ApiType=Azure` /
`metadata.ResourceId=<component-id>`. No Bicep output exposes it.

Register using the existing admin extra/entrypoint after the operator's project
role has propagated:

```powershell
$env:FOUNDRY_PROJECT_ENDPOINT = 'https://<account>.services.ai.azure.com/api/projects/<project>'
$env:AGENT_NAME = 'boring-aks-agent'
$env:OTEL_AGENT_ID = 'boring-aks-agent-demo'
uv run --locked --all-extras aks-agent-register
```

Keep the registration's name/`otel_agent_id` identical to `runtime.py` arguments.
The stable ID maps to serving `gen_ai.agent.id` spans; the release ID changes
with each source/image release. Registration is metadata only, not routing,
hosting, an authenticated endpoint declaration, or proof of invocation. Verify
the project's `telemetry.get_application_insights_connection_string()` resolves
the same component **without printing the value**, make a real authenticated
model request, and query the connected Application Insights for the stable
agent ID and expected release. The operator owns these verification steps.

## Rerun and cleanup

- Rerun the appropriate stage with the same names/overrides only after its
  operation is terminal. No resources are deleted by incremental deployment.
  A new node RG name cannot be applied to an existing cluster.
- When bootstrap administration is no longer needed, explicitly remove the
  operator's AKS RBAC Cluster Admin assignment and, if no longer required, its
  project role. Set `grantOperatorClusterAdmin` / `grantOperatorFoundryUser` to
  `false` in local parameters to avoid re-adding them. **Setting these booleans
  alone does not revoke existing assignments.**
- Stop the loopback port-forward; clear `AGENT_API_TOKEN` from your shell with
  `Remove-Item Env:AGENT_API_TOKEN`, remove the demo kubeconfig, and remove any
  locally retained tokens using your credential manager.
- For full teardown, inventory the demo RG and the separately named node RG
  first. After deliberate operator confirmation, delete AKS and wait for AKS to
  delete its managed group; then delete the demo-exclusive RG. Check deletion
  status rather than assuming a timeout means completion. Never bulk-delete a
  shared RG or provider-created group belonging to another cluster.
- Foundry/account and monitoring soft-delete/retention behavior can retain
  data or reserve names after RG deletion. Handle purge/recovery deliberately
  if required; this entrypoint does not purge. Keep no production data here.

## Offline validation

CI installs Bicep **0.45.15** without Azure login and runs compiled-template
contracts with the normal locked tests. Locally, with Bicep already installed:

```powershell
$env:BICEP_TESTS = '1'
uv run --locked --all-extras pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Template tests assert resource-group containment, exact scoped roles, identity
wiring, two-node AKS/auth/network configuration, model pinning, federation
alignment with the existing ServiceAccount, the verified telemetry connection
schema and nonsecret outputs. Operator tests cover adoption guards, active
operation handling, source-preserving runtime rendering, context isolation and
secret redaction. Without `BICEP_TESTS=1`, compiled-template tests explicitly
skip; the remaining operator tests still run. These checks never provision Azure
resources and do not replace regional preflight or live deployment validation.
