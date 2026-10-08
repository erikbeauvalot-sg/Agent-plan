import asyncio
import json

from diagagent import cli
from diagagent.evaluation import replay_run, run_eval
from diagagent.llm import LLMResponse
from diagagent.llm.scripted import ScriptedProvider
from test_agent import _load_with_runs
from test_orchestrator import REPORT, answer, by_role, call, tools

ACTION = {"title": "Revenir à max_connections = 500 sur db-pay-02", "target": "db-pay-02 (CI0012400)",
          "type": "remédiation", "rationale": "Saturation depuis CHG0034567",
          "evidence": ["lead/calls/0001.json"], "risk": "faible", "procedure": "ALTER SYSTEM …; reload",
          "rollback": "Remettre 200", "requires_change": True}


def scenario():
    lead = ScriptedProvider([
        tools(call("search", {"source": "changes", "time_from": "2026-10-06T00:00:00Z"})),
        tools(call("spawn_subagent", {"role": "logs", "entity": "srv-pay-01", "objective": "Erreurs",
                                      "period": "2026-10-06T21:00Z"})),
        tools(call("wait_subagents", {})),
        tools(call("propose_action", {**ACTION, "risk": "nul"}, "bad"), call("propose_action", ACTION, "ok")),
        answer("## Synthèse\nCHG0034567 a réduit max_connections sur db-pay-02."),
    ])
    logs = ScriptedProvider([
        tools(call("aggregate", {"source": "logs-applicatifs", "field": "message",
                                 "filters": {"host": "srv-pay-01", "level": "ERROR"}, "time_from": "2026-10-06T21:00:00Z"})),
        tools(call("submit_report", REPORT)),
    ])
    return by_role(lead=lead, logs=logs)


def test_actions_are_recorded_never_executed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    log, status, _ = asyncio.run(cli.ask("Pourquoi ?", providers=scenario()))
    actions = json.loads((log.dir / "actions.json").read_text())
    assert status == "completed"
    assert [a["id"] for a in actions] == ["A01"] and actions[0]["status"] == "proposed"
    assert actions[0]["requires_change"] is True
    bad = json.loads((log.dir / "lead" / "calls" / "0004.json").read_text())
    assert bad["is_error"] and "risk doit valoir" in bad["output"]


def test_replay_matches_and_detects_divergence(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGAGENT_RUNS_DIR", str(tmp_path / "runs"))
    log, _, _ = asyncio.run(cli.ask("Pourquoi ?", providers=scenario()))
    result = asyncio.run(replay_run(log.run_id))
    assert result["status"] == "completed" and result["differences"] == [] and result["unused_responses"] == {}
    replayed = tmp_path / "runs" / result["replay"][:4] / result["replay"][4:6] / result["replay"][6:8] / result["replay"]
    assert json.loads((replayed / "actions.json").read_text())[0]["title"] == ACTION["title"]
    # Une source qui a changé depuis l'investigation d'origine apparaît comme une différence.
    call_file = log.dir / "subagents" / "T01-logs-srv-pay-01" / "calls" / "0001.json"
    data = json.loads(call_file.read_text())
    data["output"]["total"] = 0
    call_file.write_text(json.dumps(data))
    diffs = asyncio.run(replay_run(log.run_id))["differences"]
    assert diffs == [{"ref": "subagents/T01-logs-srv-pay-01/calls/0001.json", "tool": "aggregate",
                      "difference": "résultat différent"}]


def test_eval_checks_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGAGENT_RUNS_DIR", str(tmp_path / "runs"))
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
defaults: {now: "2026-10-07T06:00:00Z"}
cases:
  - id: proprietaire
    question: "Qui possède db-pay-02 ?"
    must_mention: ["équipe Bases de données"]
    max_subagents: 0
  - id: rate
    question: "Incidents ouverts ?"
    must_mention: [INC0098765]
    must_not_mention: [INC0097012]
""")

    def lead(request):
        q = request.messages[0].content
        return answer("C'est l'équipe Bases de données." if "possède" in q else "INC0097012 seulement")

    report = asyncio.run(run_eval(cases, providers=lambda role: (ScriptedProvider([lead]), {}),
                                  out_dir=tmp_path / "results"))
    assert report["summary"] == {"cases": 2, "passed": 1, "tokens": 0}
    failed = [c["check"] for c in report["results"][1]["checks"] if not c["ok"]]
    assert failed == ["mentionne « INC0098765 »", "ne mentionne pas « INC0097012 »"]
    assert (tmp_path / "results").glob("*.json")
