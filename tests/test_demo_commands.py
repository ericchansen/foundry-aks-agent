from types import SimpleNamespace

import pytest

from foundry_aks_agent import evaluate, traffic
from foundry_aks_agent.app import Answer


def answer(trace_id: str) -> Answer:
    return Answer(
        answer="Synthetic answer",
        trace_id=trace_id,
        agent_id="boring-aks-agent-demo",
        release_id="release",
        pod_name="pod",
        pod_namespace="boring-agent",
    )


def test_generate_traffic_calls_every_prompt(monkeypatch, capsys):
    calls = []
    sleeps = []

    def fake_ask(url, prompt, token):
        calls.append((url, prompt, token))
        return answer(f"trace-{len(calls)}")

    monkeypatch.setattr(traffic, "ask", fake_ask)
    monkeypatch.setattr(traffic.time, "sleep", sleeps.append)
    replies = traffic.generate_traffic("http://127.0.0.1:8000", "token", ("one", "two"))
    assert [reply.trace_id for reply in replies] == ["trace-1", "trace-2"]
    assert calls == [
        ("http://127.0.0.1:8000", "one", "token"),
        ("http://127.0.0.1:8000", "two", "token"),
    ]
    assert sleeps == [traffic.REQUEST_INTERVAL_SECONDS]
    assert "Prompt: one" in capsys.readouterr().out


class FakeRuns:
    def __init__(self, status):
        self.status = status
        self.created = None

    def create(self, **kwargs):
        self.created = kwargs
        return SimpleNamespace(id="run")

    def retrieve(self, **kwargs):
        return SimpleNamespace(
            id="run",
            status=self.status,
            result_counts=SimpleNamespace(passed=1, failed=0, errored=0),
            per_testing_criteria_results=[],
        )


class FakeEvals:
    def __init__(self, status):
        self.runs = FakeRuns(status)
        self.created = None

    def create(self, **kwargs):
        self.created = kwargs
        return SimpleNamespace(id="evaluation")


def test_trace_evaluation_uses_agent_filter():
    evals = FakeEvals("completed")
    run = evaluate.run_trace_evaluation(
        SimpleNamespace(evals=evals), "boring-aks-agent", "gpt-4.1-mini"
    )
    assert run.status == "completed"
    assert evals.created["testing_criteria"][0]["evaluator_name"] == ("builtin.intent_resolution")
    trace_source = evals.runs.created["data_source"]["trace_source"]
    assert trace_source["agent_name"] == "boring-aks-agent"
    assert trace_source["max_traces"] == evaluate.MAX_TRACES


def test_trace_evaluation_fails_on_terminal_error():
    with pytest.raises(RuntimeError, match="status failed"):
        evaluate.run_trace_evaluation(
            SimpleNamespace(evals=FakeEvals("failed")),
            "boring-aks-agent",
            "gpt-4.1-mini",
        )


def test_trace_evaluation_times_out(monkeypatch):
    monkeypatch.setattr(evaluate, "POLL_TIMEOUT_SECONDS", 0)
    with pytest.raises(TimeoutError, match="did not finish"):
        evaluate.run_trace_evaluation(
            SimpleNamespace(evals=FakeEvals("running")),
            "boring-aks-agent",
            "gpt-4.1-mini",
        )
