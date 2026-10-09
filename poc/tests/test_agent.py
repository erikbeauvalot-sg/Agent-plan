import asyncio
import json

from diagagent import cli
from diagagent.llm import LLMResponse, ToolCall
from diagagent.llm.scripted import ScriptedProvider


def _tool(*calls):
    return LLMResponse(text="", tool_calls=[ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(calls)],
                       stop_reason="tool_call")


def test_lead_agent_calls_tools_and_writes_traces(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    provider = ScriptedProvider([
        _tool(("get_ci", {"id_or_hostname": "srv-pay-01"}),
              ("search", {"source": "changes", "time_from": "2026-10-06T00:00:00Z"})),
        LLMResponse(text="## Synthèse\nChangement CHG0034567 [lead/calls/0002.json]", tool_calls=[],
                    stop_reason="end"),
    ])
    log, status, answer = asyncio.run(cli.ask("Pourquoi srv-pay-01 est lent ?", providers=only(provider)))

    assert status == "completed" and "CHG0034567" in answer
    # Le modèle reçoit le résultat d'outil avec sa référence de preuve.
    tool_msgs = [m for m in provider.requests[1].messages if m.role == "tool"]
    assert len(tool_msgs) == 2 and "query_ref: lead/calls/0001.json" in tool_msgs[0].content
    assert "CI0012345" in tool_msgs[0].content
    # Traces : manifest, transcript, appels, événements, index.
    d = log.dir
    assert json.loads((d / "manifest.json").read_text())["status"] == "completed"
    assert len((d / "lead" / "transcript.jsonl").read_text().splitlines()) == 4
    call = json.loads((d / "lead" / "calls" / "0002.json").read_text())
    assert call["tool"] == "search" and call["output"]["total"] == 2
    types = [json.loads(line)["type"] for line in (d / "events.jsonl").read_text().splitlines()]
    # La catégorisation précède l'agent principal ; sans classifieur, la stratégie générique.
    assert types[:3] == ["classification_started", "request_classified", "agent_started"]
    assert types[-1] == "agent_ended"
    assert json.loads((d / "manifest.json").read_text())["category"]["id"] == "autre"
    assert (tmp_path / "runs" / "index.jsonl").exists()
    assert "Date et heure de référence : 2026-10-07T06:00:00Z" in (d / "lead" / "system_prompt.md").read_text()


def test_budget_forces_a_partial_answer(tmp_path, monkeypatch):
    load = _load_with_runs(tmp_path, budget={"max_tool_calls": 1, "max_turns": 5})
    monkeypatch.setattr(cli, "_load", load)
    provider = ScriptedProvider([
        _tool(("list_sources", {})),
        LLMResponse(text="Réponse partielle", tool_calls=[], stop_reason="end"),
    ])
    _, status, answer = asyncio.run(cli.ask("Question", providers=only(provider)))
    assert status == "partial" and answer == "Réponse partielle"
    assert provider.requests[1].tools == []


def only(provider):
    """Le même fournisseur pour tous les agents ; pas de classifieur (catégorie autre)."""
    def providers(role):
        if role == "classifier":
            raise KeyError(role)
        return provider, {}
    return providers


def _load_with_runs(tmp_path, budget=None):
    original = cli._load

    def load(name):
        cfg = original(name)
        if name == "poc.yaml":
            cfg["runs_dir"] = str(tmp_path / "runs")
            if budget:
                cfg["budgets"] = {"lead": budget}
        return cfg
    return load
