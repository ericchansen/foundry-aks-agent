"""Apply the existing private runtime manifests without writing or printing secrets."""

import argparse
import base64
import getpass
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from infra.deploy import az, check_names, parameters

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def kubectl(context: str, *args: str, payload: str | None = None) -> str:
    executable = shutil.which("kubectl")
    if executable is None:
        raise RuntimeError("kubectl is required.")
    result = subprocess.run(
        [executable, "--context", context, *args],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        # Validation/admission failures can repeat the secret-containing request.
        raise RuntimeError(f"kubectl failed ({result.returncode}); raw output suppressed.")
    return result.stdout


def manifests(
    foundation: dict,
    login_server: str,
    client_id: str,
    image: str,
    release_id: str,
    agent_name: str,
    agent_id: str,
    token: str,
    connection_string: str,
) -> list[dict]:
    if not re.fullmatch(r"[0-9a-f]{40}", release_id):
        raise ValueError("release-id must be the full lowercase source commit SHA.")
    match = re.fullmatch(re.escape(login_server) + r"/[\w./-]+@sha256:([0-9a-f]{64})", image)
    if match is None or match[1] == "0" * 64:
        raise ValueError("Use a non-placeholder digest-pinned image from the dedicated ACR.")
    if len(token) < 32 or not connection_string.strip():
        raise ValueError("A token of at least 32 characters and telemetry connection are required.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", agent_name) or not agent_id.strip():
        raise ValueError("A valid agent name and stable telemetry agent ID are required.")
    docs = {
        path.stem: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in DEPLOY.glob("*.yaml")
    }
    docs["serviceaccount"]["metadata"]["annotations"]["azure.workload.identity/client-id"] = (
        client_id
    )
    docs["configmap"]["data"].update(
        AZURE_OPENAI_ENDPOINT=f"https://{foundation['accountName']}.openai.azure.com/",
        AZURE_OPENAI_DEPLOYMENT=foundation.get("modelDeploymentName", "gpt-4.1-mini"),
        RELEASE_ID=release_id,
        AGENT_NAME=agent_name,
        OTEL_AGENT_ID=agent_id,
    )
    docs["deployment"]["spec"]["template"]["spec"]["containers"][0]["image"] = image
    # Change this nonsecret annotation on each release. For token/config-only
    # changes, main() explicitly restarts the workload after applying everything.
    docs["deployment"]["spec"]["template"]["metadata"].setdefault("annotations", {})[
        "foundry-aks-agent/release"
    ] = release_id
    # data (rather than stringData) supports server-side apply. No last-applied
    # annotation is created, and the serialized object is only sent over stdin.
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "boring-agent-secrets", "namespace": "boring-agent"},
        "type": "Opaque",
        "data": {
            key: base64.b64encode(value.encode()).decode()
            for key, value in {
                "AGENT_API_TOKEN": token,
                "APPLICATIONINSIGHTS_CONNECTION_STRING": connection_string,
            }.items()
        },
    }
    return [
        docs["namespace"],
        docs["serviceaccount"],
        docs["configmap"],
        secret,
        docs["deployment"],
        docs["service"],
    ]


def run(args):
    foundation = parameters(args.foundation_parameters)
    cluster = parameters(args.cluster_parameters)
    check_names("foundation", foundation, args.resource_group)
    check_names("cluster", cluster, args.resource_group)
    for key in ("workloadIdentityName", "controlPlaneIdentityName", "kubeletIdentityName"):
        if foundation[key] != cluster[key]:
            raise ValueError(f"Foundation and cluster disagree on {key}.")
    scope = ["--subscription", args.subscription, "--resource-group", args.resource_group]
    cluster_info = az(
        "aks",
        "show",
        *scope,
        "--name",
        cluster["clusterName"],
        "--query",
        "{fqdn:fqdn,state:provisioningState}",
    )
    if cluster_info["state"] != "Succeeded":
        raise RuntimeError("AKS must reach Succeeded before applying the runtime.")
    context = json.loads(kubectl(args.context, "config", "view", "--minify", "--output", "json"))
    kube_cluster = context["clusters"][0]["cluster"]
    server = urlsplit(kube_cluster["server"])
    if (
        server.scheme != "https"
        or server.hostname != cluster_info["fqdn"]
        or server.username
        or server.password
        or kube_cluster.get("insecure-skip-tls-verify", False)
    ):
        raise ValueError("Explicit kubectl context does not point to the selected AKS cluster.")
    login_server = az(
        "acr", "show", *scope, "--name", foundation["registryName"], "--query", "loginServer"
    )
    client_id = az(
        "identity",
        "show",
        *scope,
        "--name",
        foundation["workloadIdentityName"],
        "--query",
        "clientId",
    )
    # ARM component read, captured in memory; never a CLI argument or output.
    connection_string = az(
        "resource",
        "show",
        *scope,
        "--resource-type",
        "Microsoft.Insights/components",
        "--name",
        foundation["applicationInsightsName"],
        "--api-version",
        "2020-02-02",
        "--query",
        "properties.ConnectionString",
    )
    token = os.environ.get("AGENT_API_TOKEN") or getpass.getpass(
        "Agent bearer token (>=32 chars): "
    )
    docs = manifests(
        foundation,
        login_server,
        client_id,
        args.image,
        args.release_id,
        args.agent_name,
        args.agent_id,
        token,
        connection_string,
    )
    for doc in docs:
        kubectl(
            args.context,
            "apply",
            "--server-side",
            "--field-manager",
            "foundry-aks-agent",
            "-f",
            "-",
            payload=json.dumps(doc),
        )
    kubectl(args.context, "-n", "boring-agent", "rollout", "restart", "deployment/boring-agent")
    kubectl(
        args.context,
        "-n",
        "boring-agent",
        "rollout",
        "status",
        "deployment/boring-agent",
        "--timeout=300s",
    )
    print("Private runtime applied and rollout completed. No secrets were written or printed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--foundation-parameters", required=True, type=Path)
    parser.add_argument("--cluster-parameters", required=True, type=Path)
    parser.add_argument("--context", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--agent-name", default="boring-aks-agent")
    parser.add_argument("--agent-id", default="boring-aks-agent-demo")
    args = parser.parse_args()
    try:
        run(args)
    except (RuntimeError, ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
