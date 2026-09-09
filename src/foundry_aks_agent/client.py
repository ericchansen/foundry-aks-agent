import argparse
import os
from urllib.parse import urlsplit

import httpx

from foundry_aks_agent.app import Answer


def endpoint(value: str) -> str:
    parsed = urlsplit(value)
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
    ):
        raise argparse.ArgumentTypeError(
            "Use HTTPS, or HTTP on loopback through kubectl port-forward"
        )
    return value.rstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Call the authenticated AKS agent, not Foundry.")
    parser.add_argument("--url", type=endpoint, default="http://127.0.0.1:8000")
    parser.add_argument("--prompt", default="Reply with a short greeting.")
    args = parser.parse_args()
    token = os.environ["AGENT_API_TOKEN"]
    with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
        response = client.post(
            f"{args.url}/ask",
            headers={"Authorization": f"Bearer {token}"},
            json={"prompt": args.prompt},
        )
        response.raise_for_status()
        print(Answer.model_validate(response.json()).model_dump_json(indent=2))
