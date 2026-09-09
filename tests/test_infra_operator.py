import argparse
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra import deploy, runtime


def values():
    return {
        "accountName": "demo-foundry",
        "registryName": "demoregistry",
        "applicationInsightsName": "demo-insights",
        "workloadIdentityName": "demo-workload",
        "controlPlaneIdentityName": "demo-control",
        "kubeletIdentityName": "demo-kubelet",
        "clusterName": "demo-aks",
        "nodeResourceGroupName": "demo-nodes",
    }


def test_runtime_renders_in_memory_without_modifying_sources():
    before = {p: p.read_bytes() for p in runtime.DEPLOY.glob("*.yaml")}
    docs = runtime.manifests(
        values(),
        "demoregistry.azurecr.io",
        "client-id",
        "demoregistry.azurecr.io/boring-agent@sha256:" + "a" * 64,
        "b" * 40,
        "boring-aks-agent",
        "stable-agent-id",
        "t" * 32,
        "private-connection",
    )
    by_kind = {doc["kind"]: doc for doc in docs}
    assert by_kind["Service"]["spec"]["type"] == "ClusterIP"
    config = by_kind["ConfigMap"]["data"]
    assert config["AZURE_OPENAI_ENDPOINT"] == "https://demo-foundry.openai.azure.com/"
    assert config["OTEL_AGENT_ID"] == "stable-agent-id"
    assert config["RELEASE_ID"] == "b" * 40
    assert "AGENT_API_TOKEN" not in config
    secret = by_kind["Secret"]
    assert "annotations" not in secret["metadata"]
    assert base64.b64decode(secret["data"]["AGENT_API_TOKEN"]) == b"t" * 32
    assert base64.b64decode(secret["data"]["APPLICATIONINSIGHTS_CONNECTION_STRING"]) == (
        b"private-connection"
    )
    assert all(p.read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize(
    "image,release,token",
    [
        ("other.azurecr.io/agent@sha256:" + "a" * 64, "b" * 40, "t" * 32),
        ("demoregistry.azurecr.io/agent:latest", "b" * 40, "t" * 32),
        ("demoregistry.azurecr.io/agent@sha256:" + "0" * 64, "b" * 40, "t" * 32),
        ("demoregistry.azurecr.io/agent@sha256:" + "a" * 64, "short", "t" * 32),
        ("demoregistry.azurecr.io/agent@sha256:" + "a" * 64, "b" * 40, "short"),
    ],
)
def test_runtime_rejects_nonreproducible_or_unsafe_inputs(image, release, token):
    with pytest.raises(ValueError):
        runtime.manifests(
            values(),
            "demoregistry.azurecr.io",
            "client-id",
            image,
            release,
            "agent",
            "id",
            token,
            "connection",
        )


def test_secrets_go_only_to_stdin_and_errors_are_redacted(monkeypatch):
    calls = []

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout="secret echo", stderr="secret echo")

    monkeypatch.setattr(runtime.shutil, "which", lambda _: "kubectl")
    monkeypatch.setattr(runtime.subprocess, "run", execute)
    with pytest.raises(RuntimeError, match="raw output suppressed") as error:
        runtime.kubectl("demo", "apply", "-f", "-", payload="secret-input")
    assert "secret" not in str(error.value)
    assert calls[0][1]["input"] == "secret-input"
    assert "secret-input" not in calls[0][0]
    with pytest.raises(RuntimeError) as error:
        deploy.az("resource", "show")
    assert "secret echo" not in str(error.value)


def test_exclusive_groups_and_distinct_identities_are_required():
    bad = values() | {"kubeletIdentityName": "DEMO-CONTROL"}
    with pytest.raises(ValueError, match="distinct"):
        deploy.check_names("foundation", bad, "demo")
    with pytest.raises(ValueError, match="separate"):
        deploy.check_names("cluster", values(), "DEMO-NODES")


def test_example_placeholders_are_not_deployable():
    path = Path(__file__).resolve().parents[1] / "infra" / "foundation.parameters.example.json"
    with pytest.raises(ValueError, match="Replace every"):
        deploy.parameters(path)


@pytest.mark.parametrize(
    "key",
    [
        "-----BEGIN OPENSSH PRIVATE KEY-----\nprivate material",
        "ssh-rsa AAAA\nextra line",
        "ssh-ed25519 AAAA demo",
    ],
)
def test_ssh_parameter_rejects_private_or_unsupported_key_material(key):
    with pytest.raises(ValueError, match="single-line ssh-rsa PUBLIC key") as error:
        deploy.check_names("cluster", values() | {"sshPublicKey": key}, "demo")
    assert key not in str(error.value)


def test_ssh_parameter_accepts_optional_rsa_public_key():
    deploy.check_names("cluster", values() | {"sshPublicKey": ""}, "demo")
    deploy.check_names(
        "cluster",
        values() | {"sshPublicKey": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ== demo"},
        "demo",
    )


def test_ssh_disabling_requires_explicit_feature_registration(monkeypatch):
    answers = iter([[], "NotRegistered"])
    monkeypatch.setattr(deploy, "az", lambda *args: next(answers))
    with pytest.raises(RuntimeError, match="DisableSSHPreview to be Registered"):
        deploy.ensure_idle(
            "cluster",
            values() | {"disableNodeSsh": True},
            ["--subscription", "sub"],
            "demo",
        )


def test_active_arm_deployment_blocks_resubmission(monkeypatch):
    monkeypatch.setattr(
        deploy,
        "az",
        lambda *args: [{"name": "demo", "properties": {"provisioningState": "Running"}}],
    )
    with pytest.raises(RuntimeError, match="still active"):
        deploy.ensure_idle("cluster", values(), ["--subscription", "sub"], "demo")


def test_active_aks_blocks_retry_after_arm_failure(monkeypatch):
    responses = iter(
        [
            [{"name": "demo", "properties": {"provisioningState": "Failed"}}],
            [{"name": "demo-aks"}],
            "Creating",
        ]
    )
    monkeypatch.setattr(deploy, "az", lambda *args: next(responses))
    with pytest.raises(RuntimeError, match="AKS is still active"):
        deploy.ensure_idle("cluster", values(), ["--subscription", "sub"], "demo")


def test_existing_node_group_blocks_new_cluster(monkeypatch):
    responses = iter([[], [], True])
    monkeypatch.setattr(deploy, "az", lambda *args: next(responses))
    with pytest.raises(RuntimeError, match="absent"):
        deploy.ensure_idle("cluster", values(), ["--subscription", "sub"], "demo")


def test_deploy_requires_explicit_rg_confirmation(monkeypatch):
    monkeypatch.setattr(deploy, "parameters", lambda _: values())
    monkeypatch.setattr(deploy, "az", lambda *args: pytest.fail("No Azure call expected"))
    args = argparse.Namespace(
        stage="cluster",
        action="deploy",
        resource_group="demo",
        subscription="sub",
        parameters=Path("unused"),
        confirm_resource_group=None,
    )
    with pytest.raises(ValueError, match="confirm-resource-group"):
        deploy.run(args)


def test_plan_uses_resource_ids_only_and_machine_readable_output(monkeypatch, capsys):
    monkeypatch.setattr(deploy, "parameters", lambda _: values())
    calls = []

    def execute(*args):
        calls.append(args)
        return {"changes": [{"changeType": "Modify", "resourceId": "/demo/resource"}]}

    monkeypatch.setattr(deploy, "az", execute)
    deploy.run(
        argparse.Namespace(
            stage="foundation",
            action="plan",
            resource_group="demo",
            subscription="sub",
            parameters=Path("unused"),
        )
    )
    assert calls[0][:3] == ("deployment", "group", "what-if")
    assert calls[0][calls[0].index("--result-format") + 1] == "ResourceIdOnly"
    assert "--no-pretty-print" in calls[0]
    assert capsys.readouterr().out == "Modify: /demo/resource\n"


def test_runtime_applies_secret_over_stdin_then_restarts(monkeypatch, capsys):
    monkeypatch.setattr(runtime, "parameters", lambda _: values())
    answers = iter(
        [
            {"state": "Succeeded", "fqdn": "selected.example"},
            "demoregistry.azurecr.io",
            "client-id",
            "private-connection",
        ]
    )
    monkeypatch.setattr(runtime, "az", lambda *args: next(answers))
    monkeypatch.setenv("AGENT_API_TOKEN", "t" * 32)
    calls = []

    def kubectl(*args, **kwargs):
        calls.append((args, kwargs))
        return json.dumps({"clusters": [{"cluster": {"server": "https://selected.example"}}]})

    monkeypatch.setattr(runtime, "kubectl", kubectl)
    runtime.run(
        argparse.Namespace(
            foundation_parameters=Path("unused"),
            cluster_parameters=Path("unused"),
            resource_group="demo",
            subscription="sub",
            context="demo",
            image="demoregistry.azurecr.io/boring-agent@sha256:" + "a" * 64,
            release_id="b" * 40,
            agent_name="agent",
            agent_id="stable-id",
        )
    )
    applications = [(args, kwargs) for args, kwargs in calls if "apply" in args]
    assert len(applications) == 6
    assert all("--server-side" in args for args, _ in applications)
    assert all("--force-conflicts" not in args for args, _ in applications)
    assert any(json.loads(kwargs["payload"])["kind"] == "Secret" for _, kwargs in applications)
    assert "restart" in calls[-2][0]
    assert "status" in calls[-1][0]
    output = capsys.readouterr().out
    assert "private-connection" not in output
    assert "t" * 32 not in output


def test_runtime_rejects_wrong_kubectl_context_before_reading_secrets(monkeypatch):
    monkeypatch.setattr(runtime, "parameters", lambda _: values())
    monkeypatch.setattr(
        runtime, "az", lambda *args: {"state": "Succeeded", "fqdn": "selected.example"}
    )
    monkeypatch.setattr(
        runtime,
        "kubectl",
        lambda *args: json.dumps({"clusters": [{"cluster": {"server": "https://wrong.example"}}]}),
    )
    args = argparse.Namespace(
        foundation_parameters=Path("unused"),
        cluster_parameters=Path("unused"),
        resource_group="demo",
        subscription="sub",
        context="wrong",
    )
    with pytest.raises(ValueError, match="does not point"):
        runtime.run(args)
