"""Passerelle web : connexion, rôles, lancement, flux d'événements, arrêt d'un sous-agent."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from diagagent.llm import LLMResponse, ToolCall
from diagagent.llm.scripted import ScriptedProvider
from diagagent.web.app import create_app
from diagagent.web.auth import FileUserStore, Sessions

PWD = "un-mot-de-passe-long"
H = {"X-Diagagent": "1"}


def tools(*calls):
    return LLMResponse("", [ToolCall(f"c{i}-{n}", n, a) for i, (n, a) in enumerate(calls)], "tool_call")


def answer(text):
    return LLMResponse(text, [], "end")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGAGENT_RUNS_DIR", str(tmp_path / "runs"))
    store = FileUserStore(tmp_path / "users.yaml")
    store.add("alice", PWD, ["operateur"])
    store.add("bob", PWD, ["operateur"])
    store.add("admin", PWD, ["administrateur"])
    script = {}
    app = create_app(providers=lambda: (lambda role: (script[role], {})), users=store, sessions=Sessions(b"k" * 32))
    monkeypatch.setenv("DIAGAGENT_AUDIT_DIR", str(tmp_path / "audit"))
    return app, script


def client(app, login=None):
    c = TestClient(app)
    c.__enter__()
    if login:
        assert c.post("/api/login", json={"login": login, "password": PWD}).status_code == 200
    return c


def wait_status(c, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = c.get(f"/api/runs/{run_id}").json()
        if data["manifest"]["status"] != "running":
            return data
        time.sleep(0.2)
    raise AssertionError("investigation non terminée")


def test_login_roles_and_csrf(env):
    app, _ = env
    c = client(app)
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/login", json={"login": "alice", "password": "mauvais-mot-de-passe"}).status_code == 401
    me = c.post("/api/login", json={"login": "alice", "password": PWD}).json()
    assert me["roles"] == ["operateur"] and "stop_all" not in me["permissions"]
    cookie = c.cookies.get("diagagent_session")
    assert cookie and c.get("/api/me").json()["login"] == "alice"
    # Sans l'en-tête anti-falsification, une commande est refusée.
    assert c.post("/api/runs", json={"question": "test"}).status_code == 403


def test_access_journal(env, tmp_path):
    app, _ = env
    client(app, "alice")
    lines = [json.loads(l) for f in (tmp_path / "audit").rglob("*.jsonl") for l in f.read_text().splitlines()]
    assert lines[-1]["user"] == "alice" and lines[-1]["action"] == "login"


def test_lockout_after_five_failures(env):
    app, _ = env
    c = client(app)
    for _ in range(5):
        c.post("/api/login", json={"login": "bob", "password": "faux-mot-de-passe"})
    assert c.post("/api/login", json={"login": "bob", "password": PWD}).status_code == 401


def test_ask_stream_and_visibility(env):
    app, script = env
    script["lead"] = ScriptedProvider([tools(("get_ci", {"id_or_hostname": "srv-pay-01"})),
                                       answer("## Synthèse\nCI0012345 [lead/calls/0001.json]")])
    alice = client(app, "alice")
    run_id = alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?"}, headers=H).json()["run_id"]
    data = wait_status(alice, run_id)
    assert data["manifest"]["status"] == "completed" and "CI0012345" in data["analysis"]
    assert data["manifest"]["user"] == "alice" and data["can_stop"] is False and data["actions"] == []

    body = alice.get(f"/api/runs/{run_id}/events").text
    events = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: {\"seq")]
    assert [e["type"] for e in events[:3]] == ["classification_started", "request_classified", "agent_started"]
    assert events[-1]["type"] == "agent_ended"
    assert "event: end" in body
    # Reprise après coupure : seulement les événements après Last-Event-ID.
    tail = alice.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(len(events) - 1)}).text
    assert tail.count("event: agent") == 1

    detail = alice.get(f"/api/runs/{run_id}/agents/lead").json()
    assert detail["calls"][0]["tool"] == "get_ci" and len(detail["responses"]) == 2
    assert [r["run_id"] for r in alice.get("/api/runs").json()] == [run_id]

    bob, admin = client(app, "bob"), client(app, "admin")
    assert bob.get(f"/api/runs/{run_id}").status_code == 404
    assert bob.get("/api/runs").json() == []
    assert admin.get(f"/api/runs/{run_id}").status_code == 200


def test_stop_subagent_from_the_interface(env):
    app, script = env
    go = threading.Event()

    def blocked(request):
        assert go.wait(20)
        return tools(("list_metrics", {"host": "srv-pay-01"}))

    script["lead"] = ScriptedProvider([
        tools(("spawn_subagent", {"role": "metrics", "entity": "srv-pay-01", "objective": "Métriques", "period": "24 h"})),
        tools(("wait_subagents", {})),
        answer("Synthèse partielle"),
    ])
    script["metrics"] = ScriptedProvider([blocked, tools(("submit_report", {
        "status": "partial", "summary": "arrêté", "findings": []}))])
    alice, bob = client(app, "alice"), client(app, "bob")
    run_id = alice.post("/api/runs", json={"question": "Lenteurs ?"}, headers=H).json()["run_id"]
    url = f"/api/runs/{run_id}/agents/T01-metrics-srv-pay-01/stop"
    deadline = time.time() + 20
    while alice.post(url, headers=H).status_code == 409:  # le sous-agent n'existe pas encore
        assert time.time() < deadline
        time.sleep(0.1)
    assert bob.post(url, headers=H).status_code == 404       # bob ne voit pas l'investigation d'alice
    assert alice.post(url + "?kill=true", headers=H).status_code == 403
    go.set()
    data = wait_status(alice, run_id)
    report = alice.get(f"/api/runs/{run_id}/agents/T01-metrics-srv-pay-01").json()["report"]
    assert report["status"] == "partial" and "Sous-agent arrêté avant la fin" in report["gaps"]
    assert data["manifest"]["status"] == "completed"
    body = alice.get(f"/api/runs/{run_id}/events").text
    stop = [json.loads(l[6:]) for l in body.splitlines() if '"stop_requested"' in l][0]
    assert stop["data"] == {"by": "alice", "scope": "agent"}


def test_category_is_shown_corrected_and_forced(env, tmp_path):
    app, script = env
    script["lead"] = ScriptedProvider([answer("## Synthèse\nok"), answer("## Synthèse\nok")])
    script["classifier"] = ScriptedProvider([LLMResponse(
        '{"category": "information", "confidence": "medium"}', [], "end")])
    alice, bob, admin = client(app, "alice"), client(app, "bob"), client(app, "admin")
    assert {c["id"] for c in alice.get("/api/categories").json()} >= {"information", "performance", "autre"}

    run_id = alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?"}, headers=H).json()["run_id"]
    data = wait_status(alice, run_id)
    assert data["manifest"]["category"]["id"] == "information"
    assert next(r for r in alice.get("/api/runs").json() if r["run_id"] == run_id)["category"] == "information"

    # Seuls l'auteur et un administrateur corrigent ; la correction est tracée pour l'apprentissage.
    assert bob.post(f"/api/runs/{run_id}/category", json={"category": "tendance"}, headers=H).status_code == 404
    assert alice.post(f"/api/runs/{run_id}/category", json={"category": "inconnue"}, headers=H).status_code == 400
    r = alice.post(f"/api/runs/{run_id}/category", json={"category": "tendance"}, headers=H)
    assert r.status_code == 200 and r.json()["category"]["correction"]["by"] == "alice"
    assert alice.get(f"/api/runs/{run_id}").json()["manifest"]["category"]["correction"]["category"] == "tendance"
    feedback = (tmp_path / "runs" / "feedback" / "categories.jsonl").read_text().splitlines()
    assert json.loads(feedback[-1])["from"] == "information" and json.loads(feedback[-1])["to"] == "tendance"
    assert admin.post(f"/api/runs/{run_id}/category", json={"category": "information"}, headers=H).status_code == 200

    # Relance avec une catégorie imposée : le classifieur n'est pas rappelé.
    run2 = alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?", "category": "tendance"},
                      headers=H).json()["run_id"]
    assert wait_status(alice, run2)["manifest"]["category"]["source"] == "user"
    assert len(script["classifier"].requests) == 1
