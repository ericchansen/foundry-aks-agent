import argparse
import os
import time
from collections.abc import Iterable

from foundry_aks_agent.app import Answer
from foundry_aks_agent.client import ask, endpoint

PROMPTS = (
    "In one sentence, explain the difference between latency and throughput.",
    "Give three reasons an organization might monitor model token usage.",
    "Rewrite this fictional message in a clearer, neutral tone: "
    "'The system is slow and nobody knows why.'",
    "Summarize this synthetic incident note in two bullets: "
    "A deployment completed at 09:00. Response time increased at 09:05. "
    "No requests failed, and latency returned to normal at 09:12.",
    "State what additional information you would request before answering: 'Should we change it?'",
)
REQUEST_INTERVAL_SECONDS = 65


def generate_traffic(url: str, token: str, prompts: Iterable[str] = PROMPTS) -> list[Answer]:
    replies = []
    for index, prompt in enumerate(prompts):
        if index:
            print(f"\nWaiting {REQUEST_INTERVAL_SECONDS} seconds for model request quota.")
            time.sleep(REQUEST_INTERVAL_SECONDS)
        reply = ask(url, prompt, token)
        replies.append(reply)
        print(f"\nPrompt: {prompt}")
        print(reply.model_dump_json(indent=2))
    return replies


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic traffic for the external AKS agent."
    )
    parser.add_argument("--url", type=endpoint, default="http://127.0.0.1:8000")
    args = parser.parse_args()
    generate_traffic(args.url, os.environ["AGENT_API_TOKEN"])


if __name__ == "__main__":
    main()
