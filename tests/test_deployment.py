from pathlib import Path

import yaml

from foundry_aks_agent.config import Settings

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def manifests():
    return {
        path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in DEPLOY.glob("*.yaml")
    }


def test_manifests_wire_required_runtime_settings():
    docs = manifests()
    pod = docs["deployment"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    config = docs["configmap"]
    assert container["envFrom"] == [{"configMapRef": {"name": config["metadata"]["name"]}}]
    env = {entry["name"]: entry for entry in container["env"]}
    configured = set(config["data"]) | env.keys()
    required = {
        name.upper() for name, field in Settings.model_fields.items() if field.is_required()
    }
    assert required <= configured
    for name in ("AGENT_API_TOKEN", "APPLICATIONINSIGHTS_CONNECTION_STRING"):
        assert name not in config["data"]
        assert env[name]["valueFrom"]["secretKeyRef"] == {
            "name": "boring-agent-secrets",
            "key": name,
            "optional": False,
        }
    assert env["POD_NAME"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.name"
    assert env["POD_NAMESPACE"]["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace"


def test_private_service_selects_the_workload():
    docs = manifests()
    deployment, service = docs["deployment"], docs["service"]
    labels = deployment["spec"]["template"]["metadata"]["labels"]
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["selector"].items() <= labels.items()
    assert deployment["spec"]["selector"]["matchLabels"].items() <= labels.items()
    assert {doc["kind"] for doc in docs.values()} == {
        "Namespace",
        "ServiceAccount",
        "ConfigMap",
        "Deployment",
        "Service",
    }
    for doc in docs.values():
        if doc["kind"] != "Namespace":
            assert doc["metadata"]["namespace"] == docs["namespace"]["metadata"]["name"]


def test_workload_identity_and_hardening():
    docs = manifests()
    template = docs["deployment"]["spec"]["template"]
    pod = template["spec"]
    container = pod["containers"][0]
    sa = docs["serviceaccount"]
    assert template["metadata"]["labels"]["azure.workload.identity/use"] == "true"
    assert pod["serviceAccountName"] == sa["metadata"]["name"]
    assert "azure.workload.identity/client-id" in sa["metadata"]["annotations"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    assert container["volumeMounts"] == [{"name": "tmp", "mountPath": "/tmp"}]
    assert container["resources"]["requests"]
    assert container["resources"]["limits"]
    assert "@sha256:" in container["image"]
    assert docs["deployment"]["spec"]["replicas"] == 1
    assert "--no-access-log" in container["args"]
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert container[probe]["httpGet"] == {"path": "/healthz", "port": "http"}
