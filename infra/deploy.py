"""Explicit, resumable RG-scoped ARM entrypoint. Never creates/deletes resource groups."""

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTIVE_STATES = {"accepted", "running", "creating", "updating", "deleting", "inprogress"}


def az(*args: str):
    executable = shutil.which("az")
    if executable is None:
        raise RuntimeError("Azure CLI is required.")
    result = subprocess.run(
        [executable, *args, "--only-show-errors", "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        # Do not echo ARM errors: a connection resource error can contain credentials.
        raise RuntimeError(
            f"Azure CLI failed ({result.returncode}). Inspect the operation securely in Azure; "
            "raw output is intentionally suppressed."
        )
    return json.loads(result.stdout) if result.stdout.strip() else None


def parameters(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    values = {key: entry["value"] for key, entry in document["parameters"].items()}
    if "REPLACE_WITH" in json.dumps(values):
        raise ValueError("Replace every example parameter before using this entrypoint.")
    return values


def check_names(stage: str, values: dict, resource_group: str):
    identity_names = [
        values[key]
        for key in ("workloadIdentityName", "controlPlaneIdentityName", "kubeletIdentityName")
    ]
    if len({name.lower() for name in identity_names}) != 3:
        raise ValueError("Workload, control-plane and kubelet identities must be distinct.")
    if stage == "cluster" and values["nodeResourceGroupName"].lower() == resource_group.lower():
        raise ValueError("The AKS-managed node resource group must be separate.")
    key = values.get("sshPublicKey", "")
    if key and (
        "PRIVATE KEY" in key
        or re.fullmatch(r"ssh-rsa [A-Za-z0-9+/]+={0,2}(?: [^\r\n]*)?", key) is None
    ):
        raise ValueError(
            "sshPublicKey must be a single-line ssh-rsa PUBLIC key, never a private key."
        )


def ensure_idle(stage: str, values: dict, scope: list[str], deployment: str):
    deployments = az("deployment", "group", "list", *scope)
    if any(
        item["name"] == deployment
        and item["properties"]["provisioningState"].lower() in ACTIVE_STATES
        for item in deployments
    ):
        raise RuntimeError("Deployment is still active. Use status; do not submit another PUT.")
    if stage != "cluster":
        return
    if values.get("disableNodeSsh", False):
        feature = az(
            "feature",
            "show",
            "--subscription",
            scope[1],
            "--namespace",
            "Microsoft.ContainerService",
            "--name",
            "DisableSSHPreview",
            "--query",
            "properties.state",
        )
        if feature != "Registered":
            raise RuntimeError(
                "disableNodeSsh requires DisableSSHPreview to be Registered. "
                "Feature/provider registration is an explicit operator action."
            )
    clusters = az(
        "resource",
        "list",
        *scope,
        "--resource-type",
        "Microsoft.ContainerService/managedClusters",
        "--name",
        values["clusterName"],
    )
    if clusters:
        state = az(
            "aks", "show", *scope, "--name", values["clusterName"], "--query", "provisioningState"
        )
        if state.lower() in ACTIVE_STATES:
            raise RuntimeError(
                "AKS is still active even if ARM timed out. Inspect it; do not retry."
            )
    elif az(
        "group",
        "exists",
        "--subscription",
        scope[1],
        "--name",
        values["nodeResourceGroupName"],
    ):
        raise RuntimeError("A new cluster requires an absent, dedicated AKS-managed node RG.")


def run(args):
    values = parameters(args.parameters)
    check_names(args.stage, values, args.resource_group)
    template = HERE / f"{args.stage}.bicep"
    scope = ["--subscription", args.subscription, "--resource-group", args.resource_group]
    deployment = f"foundry-aks-agent-{args.stage}"
    if args.action == "validate":
        # Offline: no login, ARM validation or Azure writes. Check parameters against
        # the actual compiled contract instead of accepting misspelled overrides.
        compiled = az("bicep", "build", "--file", str(template), "--stdout")
        definitions = compiled["parameters"]
        unknown = values.keys() - definitions.keys()
        missing = {
            key for key, definition in definitions.items() if "defaultValue" not in definition
        } - values.keys()
        if unknown or missing:
            raise ValueError(f"Unknown parameters: {sorted(unknown)}; missing: {sorted(missing)}")
        print(f"{args.stage}: Bicep compilation and parameter names validated (no Azure calls).")
        return
    if args.action == "status":
        state = az(
            "deployment",
            "group",
            "show",
            *scope,
            "--name",
            deployment,
            "--query",
            "properties.provisioningState",
        )
        print(f"{deployment}: {state}")
        if args.stage == "cluster":
            state = az(
                "aks",
                "show",
                *scope,
                "--name",
                values["clusterName"],
                "--query",
                "provisioningState",
            )
            print(f"AKS: {state}")
        return
    common = [
        *scope,
        "--name",
        deployment,
        "--template-file",
        str(template),
        "--parameters",
        f"@{args.parameters.resolve()}",
        "--mode",
        "Incremental",
        "--no-prompt",
        "true",
    ]
    if args.action == "plan":
        # FullResourcePayloads can expose the existing AppInsights connection.
        changes = az(
            "deployment",
            "group",
            "what-if",
            *common,
            "--result-format",
            "ResourceIdOnly",
            "--no-pretty-print",
        )
        for change in changes.get("changes", []):
            print(f"{change['changeType']}: {change['resourceId']}")
        return
    if args.confirm_resource_group != args.resource_group:
        raise ValueError("Deploy requires --confirm-resource-group matching the dedicated RG.")
    ensure_idle(args.stage, values, scope, deployment)
    az("deployment", "group", "create", *common, "--no-wait")
    print(f"Submitted {deployment}. Use status; a local timeout is not a terminal Azure failure.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "plan", "deploy", "status"])
    parser.add_argument("stage", choices=["foundation", "cluster"])
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--parameters", required=True, type=Path)
    parser.add_argument("--confirm-resource-group")
    args = parser.parse_args()
    try:
        run(args)
    except (RuntimeError, ValueError, KeyError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
