import os
import time
from datetime import UTC, datetime, timedelta

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

LOOKBACK = timedelta(hours=24)
INGESTION_PADDING_SECONDS = 600
POLL_TIMEOUT_SECONDS = 900
POLL_INTERVAL_SECONDS = 15
MAX_TRACES = 5
TERMINAL_STATUSES = {"completed", "failed", "canceled"}


def run_trace_evaluation(client, agent_name: str, deployment_name: str):
    evaluation = client.evals.create(
        name=f"{agent_name}-trace-eval",
        data_source_config={"type": "azure_ai_source", "scenario": "traces"},
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": "intent_resolution",
                "evaluator_name": "builtin.intent_resolution",
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{item.response}}",
                    "tool_definitions": "{{item.tool_definitions}}",
                },
                "initialization_parameters": {"deployment_name": deployment_name},
            }
        ],
    )
    now = datetime.now(tz=UTC)
    run = client.evals.runs.create(
        eval_id=evaluation.id,
        name=f"{agent_name}-trace-run",
        data_source={
            "type": "azure_ai_trace_data_source_preview",
            "trace_source": {
                "type": "agent_filter",
                "agent_name": agent_name,
                "start_time": int((now - LOOKBACK).timestamp()),
                "end_time": int(now.timestamp()) + INGESTION_PADDING_SECONDS,
                "max_traces": MAX_TRACES,
            },
        },
    )
    print(f"Created evaluation run {run.id}", flush=True)
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        run = client.evals.runs.retrieve(run_id=run.id, eval_id=evaluation.id)
        if run.status in TERMINAL_STATUSES:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Evaluation run {run.id} did not finish before timeout")
        print(f"Evaluation status: {run.status}", flush=True)
        time.sleep(POLL_INTERVAL_SECONDS)
    if run.status != "completed":
        raise RuntimeError(f"Evaluation run {run.id} finished with status {run.status}")
    return run


def print_results(run) -> None:
    counts = run.result_counts
    print(f"Evaluation run {run.id} completed")
    print(
        f"passed={getattr(counts, 'passed', 'n/a')} "
        f"failed={getattr(counts, 'failed', 'n/a')} "
        f"errored={getattr(counts, 'errored', 'n/a')}"
    )
    for result in run.per_testing_criteria_results or []:
        name = getattr(result, "testing_criteria", None) or getattr(result, "name", "?")
        print(
            f"{name}: passed={getattr(result, 'passed', 'n/a')} "
            f"failed={getattr(result, 'failed', 'n/a')}"
        )


def main() -> None:
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            credential=credential,
            allow_preview=True,
        ) as project,
    ):
        client = project.get_openai_client()
        try:
            run = run_trace_evaluation(
                client,
                os.environ.get("AGENT_NAME", "boring-aks-agent"),
                os.environ.get("FOUNDRY_MODEL_NAME", "gpt-5-mini"),
            )
            print_results(run)
        finally:
            client.close()


if __name__ == "__main__":
    main()
