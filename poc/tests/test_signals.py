"""Signaux d'exécution calculés par l'orchestrateur et écrits dans la trace."""

import json

import pytest

from diagagent.runlog import RunLog
from diagagent.signals import SignalMonitor, Thresholds


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def run(tmp_path):
    log = RunLog(tmp_path, "question", "alice")
    clock = Clock()
    log.monitor = SignalMonitor(log.event, Thresholds(), clock)

    def signals():
        lines = (log.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        return [(e["agent_id"], e["type"], e["data"].get("kind")) for e in map(json.loads, lines)
                if e["type"].startswith("signal_")]
    return log, clock, signals


def call(log, agent, ref, args=None, error=False, duration=0.1, parent="lead"):
    log.event(agent, "tool_call_started", {"tool": "search", "ref": ref, "arguments": args or {"source": "logs"}},
              parent)
    log.event(agent, "tool_call_ended", {"tool": "search", "ref": ref, "is_error": error, "duration_s": duration},
              parent)


def test_loop_errors_and_budget(run):
    log, _, signals = run
    log.event("T01-logs-a", "agent_started", {"model": "m", "max_tool_calls": 4}, "lead")
    for i in range(3):
        call(log, "T01-logs-a", f"r{i}", error=True)
    assert signals() == [("T01-logs-a", "signal_raised", "loop"), ("T01-logs-a", "signal_raised", "errors")]
    call(log, "T01-logs-a", "r3", args={"source": "metrics"})  # succès : les erreurs cessent
    assert signals()[-2:] == [("T01-logs-a", "signal_cleared", "errors"), ("T01-logs-a", "signal_raised", "budget")]
    log.event("T01-logs-a", "agent_ended", {"status": "completed"}, "lead")
    assert {s for s in signals()[-2:]} == {("T01-logs-a", "signal_cleared", "loop"),
                                           ("T01-logs-a", "signal_cleared", "budget")}


def test_stuck_and_slow_source_need_time(run):
    log, clock, signals = run
    log.event("lead", "agent_started", {"model": "m"})
    log.event("T01-metrics-a", "agent_started", {"model": "m"}, "lead")
    log.event("T01-metrics-a", "tool_call_started", {"tool": "query_metrics", "ref": "x",
                                                     "arguments": {"source": "prometheus"}}, "lead")
    clock.t = 11
    log.monitor.tick()
    assert signals() == [("T01-metrics-a", "signal_raised", "slow:x")]
    clock.t = 125
    log.monitor.tick()
    # Le sous-agent est bloqué ; l'agent principal, qui l'attend, ne l'est pas tant qu'un agent a bougé
    # depuis moins de 120 s : ici aucun n'a bougé, les deux sont signalés.
    assert ("T01-metrics-a", "signal_raised", "stuck") in signals()
    log.event("T01-metrics-a", "tool_call_ended", {"tool": "query_metrics", "ref": "x", "duration_s": 125}, "lead")
    assert signals()[-1] == ("T01-metrics-a", "signal_cleared", "stuck")
    assert signals().count(("T01-metrics-a", "signal_raised", "slow:x")) == 1


def test_lead_waiting_on_working_subagents_is_not_stuck(run):
    log, clock, signals = run
    log.event("lead", "agent_started", {"model": "m"})
    clock.t = 130
    log.event("T01-logs-a", "agent_started", {"model": "m"}, "lead")
    log.monitor.tick()
    assert signals() == []


def test_model_refusal_quota_and_fallback(run):
    log, _, signals = run
    log.event("lead", "agent_started", {"model": "gpt-4.1-mini"})
    log.event("lead", "llm_call_ended", {"model": "gpt-4.1-mini-2025-04-14", "stop_reason": "end"})
    assert signals() == []
    log.event("lead", "llm_call_ended", {"error": "retryable", "message": "Error 429: rate limit"})
    log.event("lead", "llm_call_ended", {"model": "gpt-4.1-mini", "stop_reason": "end"})
    log.event("lead", "llm_call_ended", {"model": "claude-fallback", "stop_reason": "end"})
    assert signals() == [("lead", "signal_raised", "model"), ("lead", "signal_cleared", "model"),
                         ("lead", "signal_raised", "model")]
    events = [json.loads(x) for x in (log.dir / "events.jsonl").read_text().splitlines()]
    texts = [e["data"]["text"] for e in events if e["type"] == "signal_raised"]
    assert "quota" in texts[0] and "bascule de secours" in texts[1]


def test_thresholds_come_from_config():
    t = Thresholds.from_config({"stuck_s": 60, "slow_tool_s": 5, "inconnu": 1})
    assert (t.stuck_s, t.slow_tool_s, t.loop_repeats) == (60, 5, 3)
