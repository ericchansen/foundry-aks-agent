"""Offline compiled ARM contracts. Enable with BICEP_TESTS=1 (required in CI)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def templates():
    if os.environ.get("BICEP_TESTS") != "1":
        pytest.skip("Set BICEP_TESTS=1 to run offline Bicep compilation contracts.")
    executable = shutil.which("az")
    assert executable, "Azure CLI + Bicep 0.45.15 are required for infrastructure validation"
    compiled = {}
    for stage in ("foundation", "cluster"):
        result = subprocess.run(
            [
                executable,
                "bicep",
                "build",
                "--file",
                str(ROOT / "infra" / f"{stage}.bicep"),
                "--stdout",
                "--only-show-errors",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        compiled[stage] = json.loads(result.stdout)
    return compiled


def resource(template, resource_type):
    matches = [r for r in template["resources"] if r["type"] == resource_type]
    assert len(matches) == 1
    return matches[0]


def test_every_direct_resource_is_in_deployment_rg(templates):
    for template in templates.values():
        assert "/deploymentTemplate.json#" in template["$schema"]
        for item in template["resources"]:
            assert "subscriptionId" not in item
            assert "resourceGroup" not in item
            assert item["type"] != "Microsoft.Resources/resourceGroups"
            if "scope" in item:
                assert item["type"] == "Microsoft.Authorization/roleAssignments"
                assert "resourceId(" in item["scope"]


def test_resource_tags_inherit_rg_lifecycle_tags_and_private_overrides(templates):
    for template in templates.values():
        assert template["parameters"]["tags"]["defaultValue"] == {}
        expression = template["variables"]["resourceTags"]
        assert "resourceGroup().tags" in expression
        assert "parameters('tags')" in expression
        assert "expiresOn" not in expression
        tagged = [item for item in template["resources"] if "tags" in item]
        assert tagged
        assert all(item["tags"] == "[variables('resourceTags')]" for item in tagged)


def test_foundry_model_and_connection_contract(templates):
    template = templates["foundation"]
    account = resource(template, "Microsoft.CognitiveServices/accounts")
    assert account["kind"] == "AIServices"
    assert account["sku"] == {"name": "S0"}
    assert account["identity"]["type"] == "SystemAssigned"
    assert account["properties"]["allowProjectManagement"] is True
    assert account["properties"]["disableLocalAuth"] is True
    models = [
        item
        for item in template["resources"]
        if item["type"] == "Microsoft.CognitiveServices/accounts/deployments"
    ]
    assert len(models) == 2
    runtime_model = next(item for item in models if "modelDeploymentName" in item["name"])
    evaluation_model = next(
        item for item in models if "evaluationModelDeploymentName" in item["name"]
    )
    assert runtime_model["properties"]["versionUpgradeOption"] == "NoAutoUpgrade"
    assert evaluation_model["properties"]["versionUpgradeOption"] == "NoAutoUpgrade"
    assert any("modelDeploymentName" in dependency for dependency in evaluation_model["dependsOn"])
    assert template["parameters"]["modelName"]["defaultValue"] == "gpt-4.1-mini"
    assert template["parameters"]["modelVersion"]["defaultValue"] == "2025-04-14"
    assert template["parameters"]["modelSku"]["defaultValue"] == "GlobalStandard"
    assert template["parameters"]["modelCapacity"]["defaultValue"] == 1
    assert template["parameters"]["evaluationModelName"]["defaultValue"] == "gpt-5-mini"
    assert template["parameters"]["evaluationModelVersion"]["defaultValue"] == "2025-08-07"
    assert template["parameters"]["evaluationModelSku"]["defaultValue"] == "GlobalStandard"
    assert template["parameters"]["evaluationModelCapacity"]["defaultValue"] == 10
    connection = resource(template, "Microsoft.CognitiveServices/accounts/projects/connections")
    assert connection["apiVersion"] == "2026-05-01"
    props = connection["properties"]
    assert props["authType"] == "ApiKey"
    assert props["category"] == "AppInsights"
    assert props["credentials"]["key"] == props["target"]
    assert ".ConnectionString" in props["target"]
    assert props["metadata"]["ApiType"] == "Azure"
    assert "Microsoft.Insights/components" in props["metadata"]["ResourceId"]


def test_telemetry_registry_and_no_sensitive_outputs(templates):
    template = templates["foundation"]
    registry = resource(template, "Microsoft.ContainerRegistry/registries")
    assert registry["sku"] == {"name": "Basic"}
    assert registry["properties"]["adminUserEnabled"] is False
    workspace = resource(template, "Microsoft.OperationalInsights/workspaces")
    assert workspace["properties"]["retentionInDays"] == 30
    assert workspace["properties"]["sku"]["name"] == "PerGB2018"
    insights = resource(template, "Microsoft.Insights/components")
    assert (
        "Microsoft.OperationalInsights/workspaces" in insights["properties"]["WorkspaceResourceId"]
    )
    assert set(template["outputs"]) == {
        "registryLoginServer",
        "workloadClientId",
        "openAIEndpoint",
        "projectEndpoint",
    }
    assert set(templates["cluster"]["outputs"]) == {"clusterId", "oidcIssuer", "nodeResourceGroup"}
    for compiled in templates.values():
        output = json.dumps(compiled["outputs"]).lower()
        assert all(
            word not in output for word in ("connectionstring", "listkeys", "token", "secret")
        )


def test_explicit_control_plane_and_kubelet_identities(templates):
    cluster = resource(templates["cluster"], "Microsoft.ContainerService/managedClusters")
    assert cluster["identity"]["type"] == "UserAssigned"
    assert "controlPlaneIdentityName" in next(iter(cluster["identity"]["userAssignedIdentities"]))
    kubelet = cluster["properties"]["identityProfile"]["kubeletidentity"]
    assert set(kubelet) == {"resourceId", "clientId", "objectId"}
    assert all("kubeletIdentityName" in value for value in kubelet.values())
    assert cluster["properties"]["nodeResourceGroup"] == "[parameters('nodeResourceGroupName')]"


def test_scoped_roles_and_no_broad_bootstrap_grants(templates):
    expected = [
        (
            "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd",
            "Microsoft.CognitiveServices/accounts",
            "workload",
            "modelUserAssignmentName",
        ),
        (
            "7f951dda-4ed3-4680-a7ca-43fe172d538d",
            "Microsoft.ContainerRegistry/registries",
            "kubelet",
            "acrPullAssignmentName",
        ),
        (
            "f1a07417-d97a-45cb-824c-7a7467783830",
            "Microsoft.ManagedIdentity/userAssignedIdentities",
            "controlPlane",
            "identityOperatorAssignmentName",
        ),
        (
            "53ca6127-db72-4b80-b1b0-d745d6d5456d",
            "Microsoft.CognitiveServices/accounts/projects",
            "operatorObjectId",
            "foundryUserAssignmentName",
        ),
        (
            "53ca6127-db72-4b80-b1b0-d745d6d5456d",
            "Microsoft.CognitiveServices/accounts",
            "Microsoft.CognitiveServices/accounts/projects",
            "projectFoundryUserAssignmentName",
        ),
        (
            "43d0d8ad-25c7-4714-9337-8ba259a9fe05",
            "Microsoft.Insights/components",
            "operatorObjectId",
            "operatorMonitoringReaderAssignmentName",
        ),
        (
            "dbc9c667-e97f-4491-aee6-90b9cf960190",
            "Microsoft.Insights/components",
            "operatorObjectId",
            "operatorPrivilegedMonitoringDataReaderAssignmentName",
        ),
        (
            "acdd72a7-3385-48ef-bd42-f606fba81ae7",
            "Microsoft.Insights/components",
            "Microsoft.CognitiveServices/accounts/projects",
            "projectInsightsReaderAssignmentName",
        ),
        (
            "43d0d8ad-25c7-4714-9337-8ba259a9fe05",
            "Microsoft.Insights/components",
            "Microsoft.CognitiveServices/accounts/projects",
            "projectMonitoringReaderAssignmentName",
        ),
        (
            "73c42c96-874c-492b-b04d-ab87d138a893",
            "Microsoft.Insights/components",
            "Microsoft.CognitiveServices/accounts/projects",
            "projectLogAnalyticsReaderAssignmentName",
        ),
        (
            "dbc9c667-e97f-4491-aee6-90b9cf960190",
            "Microsoft.Insights/components",
            "Microsoft.CognitiveServices/accounts/projects",
            "projectPrivilegedMonitoringDataReaderAssignmentName",
        ),
        (
            "b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b",
            "Microsoft.ContainerService/managedClusters",
            "operatorObjectId",
            "clusterAdminAssignmentName",
        ),
    ]
    assignments = [
        r
        for template in templates.values()
        for r in template["resources"]
        if r["type"] == "Microsoft.Authorization/roleAssignments"
    ]
    assert len(assignments) == len(expected)
    for role_id, scope, principal, assignment_name in expected:
        matches = [
            assignment
            for assignment in assignments
            if role_id in assignment["properties"]["roleDefinitionId"]
            and scope in assignment["scope"]
            and principal in assignment["properties"]["principalId"]
        ]
        assert len(matches) == 1
        assignment = matches[0]
        assert assignment_name in assignment["name"]
        if role_id == "f1a07417-d97a-45cb-824c-7a7467783830":
            assert "kubeletIdentityName" in assignment["scope"]


def test_aks_system_pool_network_and_auth(templates):
    template = templates["cluster"]
    cluster = resource(template, "Microsoft.ContainerService/managedClusters")
    props = cluster["properties"]
    assert cluster["sku"] == {"name": "Base", "tier": "Free"}
    assert template["parameters"]["kubernetesVersion"]["defaultValue"] == "1.34.10"
    (pool,) = props["agentPoolProfiles"]
    assert pool["count"] == 2
    assert pool["mode"] == "System"
    assert pool["osSKU"] == "Ubuntu"
    assert pool["enableAutoScaling"] is False
    assert props["disableLocalAccounts"] is True
    assert props["enableRBAC"] is True
    assert props["aadProfile"]["managed"] is True
    assert props["aadProfile"]["enableAzureRBAC"] is True
    assert props["oidcIssuerProfile"]["enabled"] is True
    assert props["securityProfile"]["workloadIdentity"]["enabled"] is True
    assert props["networkProfile"]["networkPlugin"] == "azure"
    assert props["networkProfile"]["networkPluginMode"] == "overlay"
    assert props["networkProfile"]["outboundType"] == "loadBalancer"


def test_optional_supplied_public_key_and_node_ssh_disable(templates):
    template = templates["cluster"]
    cluster = resource(template, "Microsoft.ContainerService/managedClusters")
    assert cluster["apiVersion"] == "2025-10-01"
    assert template["parameters"]["sshPublicKey"]["defaultValue"] == ""
    assert template["parameters"]["linuxAdminUsername"]["defaultValue"] == "azureuser"
    assert template["parameters"]["disableNodeSsh"]["defaultValue"] is False
    profile = cluster["properties"]["linuxProfile"]
    assert "sshPublicKey" in profile
    assert "linuxAdminUsername" in profile
    assert "keyData" in profile
    pool = cluster["properties"]["agentPoolProfiles"][0]
    assert "disableNodeSsh" in pool["securityProfile"]
    assert "'sshAccess', 'Disabled'" in pool["securityProfile"]
    assert "ssh" not in json.dumps(template["outputs"]).lower()


def test_federation_tracks_serving_service_account(templates):
    federation = resource(
        templates["cluster"],
        "Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials",
    )
    account = yaml.safe_load((ROOT / "deploy" / "serviceaccount.yaml").read_text())
    metadata = account["metadata"]
    assert federation["properties"]["subject"] == (
        f"system:serviceaccount:{metadata['namespace']}:{metadata['name']}"
    )
    assert federation["properties"]["audiences"] == ["api://AzureADTokenExchange"]
    assert ".oidcIssuerProfile.issuerURL" in federation["properties"]["issuer"]
    assert any("Microsoft.ContainerService/managedClusters" in d for d in federation["dependsOn"])


def test_examples_cover_required_parameters(templates):
    for stage, template in templates.items():
        path = ROOT / "infra" / f"{stage}.parameters.example.json"
        example = json.loads(path.read_text())["parameters"]
        required = {
            name
            for name, definition in template["parameters"].items()
            if "defaultValue" not in definition
        }
        assert required <= example.keys() <= template["parameters"].keys()
