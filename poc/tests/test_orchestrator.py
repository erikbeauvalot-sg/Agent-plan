import asyncio
import json

import pytest
import yaml

from conftest import POC
from diagagent import cli
from diagagent.llm import LLMResponse, ToolCall
from diagagent.llm.scripted import ScriptedProvider
from diagagent.agent import LocalToolError
from diagagent.orchestrator import Investigation
from diagagent.runlog import RunLog
from diagagent.tools import ToolHub
from test_agent import _load_with_runs


def call(name, args, cid=None):
    return ToolCall(cid or f"{name}-{len(json.dumps(args))}", name, args)


def tools(*calls, text=""):
    return LLMResponse(text=text, tool_calls=list(calls), stop_reason="tool_call")


def answer(text):
    return LLMResponse(text=text, tool_calls=[], stop_reason="end")


REPORT = {"status": "completed", "summary": "Pool de connexions saturé",
          "findings": [{"fact": "Erreurs connection pool exhausted dès 22:10",
                        "evidence": ["subagents/T02-logs-srv-pay-01/calls/0001.json"], "confidence": "high"}]}


def by_role(**providers):
    return lambda role: (providers[role], {})


def test_lead_plans_spawns_in_parallel_and_consolidates(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    seen_reports = {}

    def final(request):
        seen_reports["wait"] = request.messages[-1].content
        return answer("## Synthèse\nCHG0034567 [subagents/T02-logs-srv-pay-01/calls/0001.json]")

    lead = ScriptedProvider([
        tools(call("write_plan", {"markdown": "# Plan\n- T01 host\n- T02 logs"}),
              call("spawn_subagent", {"role": "host", "entity": "srv-pay-01", "objective": "Fiche du CI",
                                      "period": "2026-10-06T21:00Z à 2026-10-07T06:00Z"}),
              call("spawn_subagent", {"role": "logs", "entity": "srv-pay-01", "objective": "Erreurs",
                                      "period": "2026-10-06T21:00Z à 2026-10-07T06:00Z",
                                      "entities": "host = srv-pay-01"})),
        tools(call("wait_subagents", {})),
        final,
    ])
    host = ScriptedProvider([
        tools(call("get_ci", {"id_or_hostname": "srv-pay-01"})),
        tools(call("submit_report", {**REPORT, "summary": "srv-pay-01 dépend de db-pay-02",
                                     "findings": [{"fact": "Dépend de CI0012400",
                                                   "evidence": ["subagents/T01-host-srv-pay-01/calls/0001.json"],
                                                   "confidence": "high"}]})),
    ])
    logs = ScriptedProvider([
        tools(call("aggregate", {"source": "logs-applicatifs", "field": "message",
                                 "filters": {"host": "srv-pay-01", "level": "ERROR"},
                                 "time_from": "2026-10-06T21:00:00Z"})),
        tools(call("submit_report", {"status": "completed", "summary": "x", "findings": [{"fact": "sans preuve"}]})),
        tools(call("submit_report", REPORT)),
    ])
    log, status, text = asyncio.run(cli.ask("Pourquoi srv-pay-01 est lent ?",
                                            providers=by_role(lead=lead, host=host, logs=logs)))

    assert status == "completed" and "CHG0034567" in text
    d = log.dir
    assert (d / "plan.md").read_text().startswith("# Plan")
    # Les sous-agents ne voient que leur prompt et leurs outils, pas spawn_subagent.
    logs_req = logs.requests[0]
    assert logs_req.messages[0].content.startswith("# Tâche T02-logs-srv-pay-01")
    assert {t.name for t in logs_req.tools} == {"list_sources", "describe_source", "resolve_entity",
                                                "search", "aggregate", "submit_report"}
    assert 'sous-agent "logs"' in logs_req.system
    # Un rapport invalide revient en erreur au sous-agent, qui corrige.
    assert "ERREUR D'OUTIL" in logs.requests[2].messages[-1].content
    report = json.loads((d / "subagents" / "T02-logs-srv-pay-01" / "report.json").read_text())
    assert report["summary"] == "Pool de connexions saturé" and report["gaps"] == []
    assert (d / "subagents" / "T01-host-srv-pay-01" / "calls" / "0001.json").exists()
    # L'agent principal reçoit les deux rapports.
    reports = json.loads(seen_reports["wait"].split("\n", 1)[1])
    assert [r["task_id"] for r in reports] == ["T01-host-srv-pay-01", "T02-logs-srv-pay-01"]
    events = [json.loads(line) for line in (d / "events.jsonl").read_text().splitlines()]
    spawned = [e for e in events if e["type"] == "agent_spawned"]
    assert len(spawned) == 2 and all(e["parent_id"] == "lead" for e in spawned)
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["subagents"]["T01-host-srv-pay-01"]["report_status"] == "completed"


def test_subagent_out_of_budget_without_report_gives_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    lead = ScriptedProvider([
        tools(call("spawn_subagent", {"role": "changes", "entity": "db-pay-02", "objective": "Changements",
                                      "period": "24 h"}),
              call("spawn_subagent", {"role": "inexistant", "entity": "x", "objective": "x", "period": "x"})),
        tools(call("wait_subagents", {"task_ids": ["T01-changes-db-pay-02"]})),
        lambda req: answer(req.messages[-1].content),
    ])
    changes = ScriptedProvider([tools(call("search", {"source": "changes"}))] * 8
                               + [answer("Je n'ai pas fini.")])
    _, _, text = asyncio.run(cli.ask("Q", providers=by_role(lead=lead, changes=changes)))
    assert '"status": "partial"' in text and "Je n'ai pas fini." in text
    # Seul submit_report reste proposé quand le budget est atteint ; le rôle inconnu est refusé.
    assert [t.name for t in changes.requests[-1].tools] == ["submit_report"]
    assert "Rôle inconnu" in lead.requests[1].messages[-1].content


def test_stop_agent_ends_subagent_with_partial_report(tmp_path):
    servers = yaml.safe_load((POC / "config" / "poc.yaml").read_text())["mcp_servers"]

    async def go():
        async with ToolHub(servers) as hub:
            log = RunLog(tmp_path, "Q", "test")
            holder = {}

            def stop_then_continue(request):
                holder["inv"].stop_agent("T01-metrics-srv-pay-01")
                return tools(call("list_metrics", {"host": "srv-pay-01"}))

            lead = ScriptedProvider([
                tools(call("spawn_subagent", {"role": "metrics", "entity": "srv-pay-01", "objective": "o",
                                              "period": "p"})),
                tools(call("wait_subagents", {})),
                answer("fin"),
            ])
            metrics = ScriptedProvider([stop_then_continue, tools(call("submit_report", {
                "status": "partial", "summary": "Arrêté après list_metrics",
                "findings": [{"fact": "f", "evidence": ["subagents/T01-metrics-srv-pay-01/calls/0001.json"],
                              "confidence": "low"}]}))])
            inv = Investigation("Q", hub, log, by_role(lead=lead, metrics=metrics),
                                {"budgets": {}, "orchestration": {}})
            holder["inv"] = inv
            await inv.run()
            return inv

    inv = asyncio.run(go())
    sub = inv.subagents["T01-metrics-srv-pay-01"]
    assert sub.status == "stopped"
    assert sub.report["status"] == "partial" and "Sous-agent arrêté avant la fin" in sub.report["gaps"]


def test_roles_without_sources_are_hidden(tmp_path):
    servers = yaml.safe_load((POC / "config" / "poc.yaml").read_text())["mcp_servers"]

    async def go():
        async with ToolHub(servers) as hub:
            inv = Investigation("Q", hub, RunLog(tmp_path, "Q", "t"), by_role(), {})
            return set(inv.roles), inv.lead_system_prompt()

    roles, prompt = asyncio.run(go())
    # Démo sans ALERTMANAGER_URL : events garde la source events d'ELK ; tous les rôles sont là.
    assert roles == {"host", "logs", "metrics", "events", "changes", "generic"}
    assert "- logs : Erreurs et anomalies" in prompt


def test_report_evidence_is_normalized():
    from diagagent.orchestrator import validate_report

    report = validate_report({"status": "completed", "summary": "ok", "findings": [
        {"fact": "a", "evidence": "subagents/T01-x/calls/0001.json", "confidence": "high"},
        {"fact": "b", "evidence": [{"query_ref": "[subagents/T01-x/calls/0002.json]"}, "lead/calls/0001.json"],
         "confidence": "low"}]})
    assert [f["evidence"] for f in report["findings"]] == [
        ["subagents/T01-x/calls/0001.json"], ["subagents/T01-x/calls/0002.json", "lead/calls/0001.json"]]
    with pytest.raises(LocalToolError):
        validate_report({"status": "completed", "summary": "ok",
                         "findings": [{"fact": "a", "evidence": [{}], "confidence": "high"}]})


def test_manifest_is_never_read_half_written(tmp_path):
    """L'interface relit manifest.json pendant les mises à jour : jamais de fichier vide ou tronqué."""
    import threading

    from diagagent.runlog import RunLog
    log = RunLog(tmp_path / "runs", "Q", "alice")
    stop, errors = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                json.loads((log.dir / "manifest.json").read_text(encoding="utf-8"))
            except ValueError as e:
                errors.append(e)

    t = threading.Thread(target=reader)
    t.start()
    for i in range(300):
        log.update_manifest(step=i, padding="x" * 20000)
    stop.set()
    t.join()
    assert errors == [] and json.loads((log.dir / "manifest.json").read_text())["step"] == 299
    assert [p.name for p in log.dir.iterdir() if p.name.endswith(".tmp")] == []
