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
    assert bad["is_error"] and "risk est un seul mot" in bad["output"] and "risk_explanation" in bad["output"]


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
    summary = report["summary"]
    assert summary.pop("duration_s") >= 0
    assert summary == {"cases": 2, "passed": 1, "tokens": 0, "models_profile": None}
    failed = [c["check"] for c in report["results"][1]["checks"] if not c["ok"]]
    assert failed == ["mentionne « INC0098765 »", "ne mentionne pas « INC0097012 »"]
    assert (tmp_path / "results").glob("*.json")


def test_eval_alternatives_and_kinds(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DIAGAGENT_RUNS_DIR", str(tmp_path / "runs"))
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
defaults: {now: "2026-10-07T06:00:00Z"}
cases:
  - {id: latence, kind: simple, question: "Latence max ?", must_mention: [["3897", "3 898"]]}
  - {id: priorite, kind: simple, question: "Priorité ?", must_mention: [P2]}
  - {id: cause, kind: incident, question: "Pourquoi ?", must_mention: [CHG0034567]}
""")
    replies = {"Latence max ?": "Pic à 3 898 ms.", "Priorité ?": "P3", "Pourquoi ?": "CHG0034567"}

    def lead(request):
        return answer(replies[request.messages[0].content])

    report = asyncio.run(run_eval(cases, providers=lambda role: (ScriptedProvider([lead]), {}),
                                  out_dir=tmp_path / "results"))
    assert report["results"][0]["checks"][1] == {"check": "mentionne « 3897 » ou « 3 898 »", "ok": True}
    assert report["summary"]["kinds"] == {"simple": {"cases": 2, "passed": 1}, "incident": {"cases": 1, "passed": 1}}
    cli.print_eval(report)
    out = " ".join(capsys.readouterr().out.split())
    assert "questions simples 1/2 critère non atteint" in out and "incidents 1/1 critère atteint" in out
    only = asyncio.run(run_eval(cases, providers=lambda role: (ScriptedProvider([lead]), {}),
                                out_dir=tmp_path / "results", kind="incident"))
    assert [r["id"] for r in only["results"]] == ["cause"]


def test_eval_repeat_reports_pass_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    cases = tmp_path / "cases.yaml"
    cases.write_text("""
defaults: {now: "2026-10-07T06:00:00Z"}
cases:
  - id: alterne
    question: "Qui possède db-pay-02 ?"
    must_mention: ["Bases de données"]
""")
    lead = ScriptedProvider([answer(t) for t in ("C'est l'équipe Bases de données.", "Je ne sais pas.",
                                                 "Équipe Bases de données")])

    def providers(role):
        if role != "lead":
            raise KeyError(role)  # pas de classifieur : catégorie autre
        return lead, {}

    report = asyncio.run(run_eval(cases, providers=providers, out_dir=tmp_path / "results", repeat=3))
    assert report["summary"]["pass_rate"] == {"alterne": "2/3"} and report["summary"]["cases"] == 3
    assert [r["attempt"] for r in report["results"]] == [1, 2, 3]


def test_same_action_twice_is_recorded_once(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    again = {**ACTION, "title": ACTION["title"].upper() + "  ", "rationale": "reformulée"}
    lead = ScriptedProvider([tools(call("propose_action", ACTION), call("propose_action", again)),
                             answer("## Synthèse\nok")])
    log, status, _ = asyncio.run(cli.ask("Pourquoi ?", providers=by_role(lead=lead)))
    assert status == "completed"
    assert [a["id"] for a in json.loads((log.dir / "actions.json").read_text())] == ["A01"]
    assert "déjà enregistrée" in lead.requests[1].messages[-1].content


def test_actions_written_in_answer_must_be_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    text = "## Synthèse\nCHG0034567.\n## Actions proposées\n1) Revenir à max_connections = 500\n## Limites\naucune"
    lead = ScriptedProvider([answer(text), tools(call("propose_action", ACTION)), answer(text)])
    log, status, final = asyncio.run(cli.ask("Pourquoi ?", providers=by_role(lead=lead)))
    assert status == "completed" and final == text
    assert "aucune n'a été enregistrée" in lead.requests[1].messages[-1].content
    assert json.loads((log.dir / "actions.json").read_text())[0]["id"] == "A01"

    # Titre en gras et tableau (gpt-oss) : relance aussi.
    bold = ("**Synthèse**\nok\n\n**Actions proposées**\n| Titre | Cible |\n|---|---|\n"
            "| Régler SwapUsageHigh | Prometheus |\n\n**Limites**\naucune")
    lead = ScriptedProvider([answer(bold), tools(call("propose_action", ACTION)), answer(bold)])
    asyncio.run(cli.ask("Pourquoi ?", providers=by_role(lead=lead)))
    assert "aucune n'a été enregistrée" in lead.requests[1].messages[-1].content

    # Pas de relance quand la réponse ne décrit aucune action.
    lead = ScriptedProvider([answer("## Synthèse\nok\n## Actions proposées\nAucune.\n")])
    assert asyncio.run(cli.ask("Q", providers=by_role(lead=lead)))[1] == "completed" and len(lead.requests) == 1


def test_action_values_are_matched_without_case_or_accents():
    from diagagent.orchestrator import validate_action
    action = validate_action({**ACTION, "type": "Remediation", "risk": "Élevé"})
    assert (action["type"], action["risk"]) == ("remédiation", "élevé")


def test_answer_normalization_ignores_unicode_hyphens_and_spaces():
    from diagagent.evaluation import normalize
    assert "db-pay-02" in normalize("dépend de **db‑pay‑02**") and "rhel 9" in normalize("RHEL 9")
