"""Page d'accueil : état des modèles et des sources, statistiques, derniers résultats d'éval."""

import json
from datetime import datetime, timezone

from diagagent import dashboard

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def row(run_id, started, status, category="diagnostic", profile="ollama", subagents=(), user="alice", seconds=60):
    end = started.replace(second=0) if seconds is None else datetime.fromtimestamp(started.timestamp() + seconds, timezone.utc)
    return {"run_id": run_id, "path": run_id, "user": user, "status": status, "category": category,
            "started_at": started.isoformat(), "ended_at": end.isoformat(), "models_profile": profile,
            "usage": {"input_tokens": 100, "output_tokens": 10, "reasoning_tokens": 0},
            "subagents": [{"role": r, "status": s} for r, s in subagents]}


def test_activity_by_category_model_and_agent():
    rows = [
        row("a", NOW.replace(hour=9), "completed", subagents=[("metrics", "completed"), ("logs", "failed")]),
        row("b", NOW.replace(hour=10), "failed", profile="openai", subagents=[("metrics", "completed")]),
        row("c", NOW.replace(day=8), "partial", category="information", seconds=30),
        row("d", NOW.replace(day=1), "completed"),          # hors période (7 jours)
        row("e", NOW.replace(hour=11), "completed", user="eval"),  # évaluation exclue par défaut
    ]
    a = dashboard.activity(rows, lambda r: {}, NOW, days=7)
    assert a["today"]["runs"] == 2 and a["today"]["success_rate"] == 0.5
    assert a["today"]["by_model"] == {"ollama": 1, "openai": 1}
    assert a["period"]["runs"] == 3 and a["period"]["tokens"] == 330
    cats = {c["name"]: c for c in a["categories"]}
    assert cats["diagnostic"]["runs"] == 2 and cats["information"]["statuses"] == {"partial": 1}
    agents = {x["name"]: x for x in a["agents"]}
    assert a["agents"][0]["name"] == "principal" and agents["principal"]["runs"] == 3
    assert agents["metrics"]["success_rate"] == 1.0 and agents["logs"]["failure_rate"] == 1.0
    assert dashboard.activity(rows, lambda r: {}, NOW, include_eval=True)["period"]["runs"] == 4


def test_old_index_rows_are_completed_from_the_manifest():
    old = {k: v for k, v in row("a", NOW, "completed").items() if k not in ("models_profile", "subagents")}
    manifest = {"models": {"lead": {"model": "gpt-oss:20b"}}, "subagents": {"T01": {"role": "logs", "status": "completed"}}}
    a = dashboard.activity([old], lambda r: manifest, NOW)
    assert [m["name"] for m in a["models"]] == ["gpt-oss:20b"]
    assert {x["name"] for x in a["agents"]} == {"principal", "logs"}


def test_last_evals_one_per_profile(tmp_path):
    def report(stamp, profile, passed):
        (tmp_path / f"{stamp}.json").write_text(json.dumps({
            "date": f"2026-10-10T{stamp[9:11]}:00:00+00:00", "cases_file": "/x/eval/cases.yaml",
            "summary": {"cases": 9, "passed": passed, "tokens": 1000, "duration_s": 60.0, "models_profile": profile},
            "results": [{"run_id": "r1", "duration_s": 60.0}]}))
    report("20261010T080000Z", "ollama", 5)
    report("20261010T090000Z", "openai", 6)
    report("20261010T100000Z", "ollama", 7)
    report("20261010T070000Z", None, 4)  # rapport antérieur aux profils : modèle relu dans l'investigation
    evals = dashboard.last_evals(tmp_path, lambda run_id: {"models": {"lead": {"model": "gpt-oss:20b"}}})
    assert [(e["label"], e["passed"]) for e in evals] == [("ollama", 7), ("openai", 6), ("gpt-oss:20b", 4)]


def test_models_status_never_calls_a_paid_api(monkeypatch):
    calls = []

    def fake_get_json(base_url, path, *args, **kwargs):
        calls.append(base_url + path)
        return {"data": [{"id": "gpt-oss:20b"}]}
    monkeypatch.setattr(dashboard, "get_json", fake_get_json)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = {"default": "ollama", "providers": {
        "local": {"adapter": "openai_compatible", "base_url": "http://localhost:11434/v1"},
        "openai": {"adapter": "openai_compatible", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"}},
        "profiles": {"ollama": {"lead": {"provider": "local", "model": "gpt-oss:20b"}},
                     "openai": {"lead": {"provider": "openai", "model": "gpt-4.1-mini"}},
                     "gros": {"lead": {"provider": "local", "model": "qwen3:32b"}}}}
    status = {s["profile"]: s for s in dashboard.models_status(cfg)}
    assert status["ollama"]["ok"] and status["ollama"]["default"]
    assert not status["openai"]["ok"] and "OPENAI_API_KEY absente" in status["openai"]["detail"]
    assert not status["gros"]["ok"] and "qwen3:32b" in status["gros"]["detail"]
    assert all(c.startswith("http://localhost") for c in calls)  # seul le serveur local est interrogé


def test_history_filters_combine():
    r = {**row("a", NOW, "completed", category="diagnostic"), "question": "Pourquoi srv-pay-01 est lent ?"}
    hosts = lambda: ["srv-pay-01"]  # noqa: E731
    assert dashboard.run_matches(r, {}, hosts)
    assert dashboard.run_matches(r, {"since": "2026-10-10", "until": "2026-10-10T23:00", "user": "alice",
                                     "category": "diagnostic", "status": "partial,completed",
                                     "host": "PAY", "q": "LENT"}, hosts)
    for f in ({"since": "2026-10-11"}, {"until": "2026-10-09"}, {"user": "bob"}, {"category": "information"},
              {"status": "failed"}, {"host": "crm"}, {"q": "disque"}):
        assert not dashboard.run_matches(r, f, hosts), f


def test_hosts_of_an_investigation():
    manifest = {"category": {"entities": {"host": "srv-db-02"}},
                "subagents": {"T01-host-mq-01": {}, "T02-service-paiement": {}}}
    known = {"srv-pay-01", "mq-01", "srv-crm-01"}
    assert dashboard.hosts_of({"question": "srv-pay-01 et le reste ?"}, manifest, known) == \
        ["mq-01", "srv-db-02", "srv-pay-01"]


def test_live_summary_gives_agent_states_and_status_line():
    ev = lambda aid, kind, data=None, parent=None: {"agent_id": aid, "parent_id": parent, "type": kind,  # noqa: E731
                                                    "data": data or {}, "ts": "2026-10-10T12:00:00Z"}
    summary = dashboard.live_summary([
        ev("lead", "classification_started"), ev("lead", "agent_started"),
        ev("T01-metrics-srv-pay-01", "agent_spawned", {"objective": "latence"}, "lead"),
        ev("T01-metrics-srv-pay-01", "agent_started", parent="lead"),
        ev("T02-logs-srv-pay-01", "agent_spawned", {"objective": "erreurs"}, "lead"),
        ev("T02-logs-srv-pay-01", "agent_started", parent="lead"),
        ev("T02-logs-srv-pay-01", "agent_ended", {"status": "completed"}, "lead"),
        ev("T01-metrics-srv-pay-01", "tool_call_started", {"tool": "query_metrics",
                                                           "arguments": {"source": "prometheus"}}, "lead"),
        ev("T01-metrics-srv-pay-01", "tool_call_ended", {"tool": "query_metrics"}, "lead"),
    ])
    assert [(a["id"], a["parent"], a["state"]) for a in summary["agents"]] == [
        ("lead", None, "running"), ("T01-metrics-srv-pay-01", "lead", "running"),
        ("T02-logs-srv-pay-01", "lead", "completed")]
    assert summary["activity"] == "T01 appelle query_metrics (prometheus)"
