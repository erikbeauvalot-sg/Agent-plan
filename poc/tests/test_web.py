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
    script = {"_profiles": []}  # profils de modèles demandés, dans l'ordre des lancements

    def providers(profile=None):
        script["_profiles"].append(profile)
        factory = lambda role: (script[role], {})  # noqa: E731
        factory.profile = profile or "ollama"
        return factory
    app = create_app(providers=providers, users=store, sessions=Sessions(b"k" * 32))
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


def test_login_form_post_redirects(env):
    app, _ = env
    c = client(app)
    form = {"login": "alice", "password": PWD, "next": "20261010T065057Z-2996"}
    ok = c.post("/login", data=form, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/#20261010T065057Z-2996"
    assert c.get("/api/me").json()["login"] == "alice"
    # Une page visée invalide est ignorée ; un échec revient au formulaire sans session.
    other = client(app)
    bad = other.post("/login", data={"login": "alice", "password": "mauvais", "next": "javascript:x"}, follow_redirects=False)
    assert bad.status_code == 303 and bad.headers["location"] == "/?echec=1"
    assert other.get("/api/me").status_code == 401
    # Un formulaire envoyé depuis un autre site est refusé.
    assert client(app).post("/login", data=form, headers={"Origin": "https://ailleurs.example"},
                            follow_redirects=False).status_code == 403


def test_login_roles_and_csrf(env):
    app, _ = env
    c = client(app)
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/login", json={"login": "alice", "password": "mauvais-mot-de-passe"}).status_code == 401
    me = c.post("/api/login", json={"login": "alice", "password": PWD}).json()
    assert me["roles"] == ["operateur"] and "stop_all" not in me["permissions"]
    cookie = c.cookies.get("diagagent_session")
    assert cookie and c.get("/api/me").json()["login"] == "alice"
    assert c.get("/api/me").json()["reference_time"] == "2026-10-07T06:00:00Z"  # heure figée des tests
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


def test_models_profile_chosen_per_request(env):
    app, script = env
    alice = client(app, "alice")
    choices = alice.get("/api/models").json()
    assert choices["default"] == "ollama" and {"ollama", "openai"} <= set(choices["profiles"])
    assert alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?", "models": "inconnu"},
                      headers=H).status_code == 400

    script["lead"] = ScriptedProvider([answer("## Synthèse\nok"), answer("## Synthèse\nok")])
    first = alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?", "models": "openai"}, headers=H)
    assert wait_status(alice, first.json()["run_id"])["manifest"]["models_profile"] == "openai"
    second = alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?"}, headers=H)
    manifest = wait_status(alice, second.json()["run_id"])["manifest"]
    assert manifest["models_profile"] == "ollama" and manifest["sources"] == ["demo"]
    assert script["_profiles"] == ["openai", None]
    # Sans PROMETHEUS_URL ni ALERTMANAGER_URL, les choix « maison » restent listés mais indisponibles.
    sources = alice.get("/api/sources").json()
    assert sources["default"] == "demo"
    assert {c["value"]: c["available"] for c in sources["choices"]} == {"demo,maison": False, "demo": True, "maison": False}
    assert alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?", "sources": "maison"},
                      headers=H).status_code == 400

    # Accueil : la liste porte le profil, les statistiques comptent les deux investigations d'alice.
    runs = alice.get("/api/runs").json()
    assert [r["label"] for r in runs] == ["ollama", "openai"] and all(r["duration_s"] is not None for r in runs)
    home = alice.get("/api/home?days=7").json()
    assert home["activity"]["period"]["runs"] == 2
    assert {m["name"] for m in home["activity"]["models"]} == {"ollama", "openai"}
    assert home["activity"]["agents"][0]["name"] == "principal"
    # bob ne voit pas les investigations d'alice, ni dans la liste ni dans les statistiques.
    assert client(app, "bob").get("/api/home").json()["activity"]["period"]["runs"] == 0


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


def test_feedback_case_and_supervisor_review(env, tmp_path, monkeypatch):
    import shutil
    import yaml as _yaml
    from conftest import POC
    from diagagent import learning

    books = tmp_path / "playbooks"
    shutil.copytree(POC / "playbooks", books, ignore=shutil.ignore_patterns("proposals", "history"))
    monkeypatch.setenv("DIAGAGENT_PLAYBOOKS_DIR", str(books))
    app, script = env
    from diagagent.web.auth import FileUserStore
    FileUserStore(tmp_path / "users.yaml").add("sophie", PWD, ["superviseur"])
    script["lead"] = ScriptedProvider([answer("## Synthèse\nCHG0034567 [lead/calls/0001.json]")])
    script["classifier"] = ScriptedProvider([LLMResponse('{"category": "information", "confidence": "high"}', [], "end")])
    alice, bob, admin, sophie = (client(app, n) for n in ("alice", "bob", "admin", "sophie"))
    run_id = alice.post("/api/runs", json={"question": "Le stockage NAS-02 rame"}, headers=H).json()["run_id"]
    wait_status(alice, run_id)

    # Avis : réservé à l'auteur (ou superviseur, administrateur) ; un cas exige un avis utile et une cause.
    body = {"verdict": "utile", "cause": "max_connections réduit", "create_case": True}
    assert bob.post(f"/api/runs/{run_id}/feedback", json=body, headers=H).status_code == 404
    assert alice.post(f"/api/runs/{run_id}/feedback", json={**body, "verdict": "faux"}, headers=H).status_code == 400
    r = alice.post(f"/api/runs/{run_id}/feedback", json=body, headers=H)
    assert r.status_code == 200 and r.json()["case"]["cause"] == "max_connections réduit"
    assert alice.get(f"/api/runs/{run_id}").json()["manifest"]["feedback"]["verdict"] == "utile"
    assert (tmp_path / "knowledge" / "cases" / f"{run_id}.yaml").exists()

    # Indicateurs : superviseur et administrateur ; pas l'opérateur.
    assert alice.get("/api/indicators").status_code == 403
    assert admin.get("/api/indicators").json()["runs"] == 1
    assert sophie.get("/api/indicators").status_code == 200

    alice.post(f"/api/runs/{run_id}/category", json={"category": "performance"}, headers=H)
    from diagagent.orchestrator import load_roles
    proposal = learning.learn(tmp_path / "runs", roles=set(load_roles()))[0]
    assert alice.get("/api/proposals").status_code == 403
    assert admin.get("/api/proposals").json()[0]["id"] == proposal["id"]
    # Seul le Superviseur valide (matrice des rôles : l'Administrateur ne valide pas).
    url = f"/api/proposals/{proposal['id']}/decision"
    assert admin.post(url, json={"accept": True}, headers=H).status_code == 403
    r = sophie.post(url, json={"accept": True, "comment": "ok"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert sophie.post(url, json={"accept": False}, headers=H).status_code == 409
    assert "Le stockage NAS-02 rame" in _yaml.safe_load((books / "performance.yaml").read_text())["examples"]


def test_role_matrix_sharing_action_review_costs_and_access_log(env, tmp_path):
    from test_actions_eval import ACTION

    app, script = env
    store = FileUserStore(tmp_path / "users.yaml")
    for login, role in (("lea", "lecteur"), ("sophie", "superviseur"), ("audrey", "auditeur")):
        store.add(login, PWD, [role])
    script["lead"] = ScriptedProvider([
        tools(("propose_action", ACTION)),
        answer("## Synthèse\nRevenir à max_connections = 500 [lead/calls/0001.json]")])
    alice, bob, admin, lea, sophie, audrey = (client(app, n) for n in ("alice", "bob", "admin", "lea", "sophie", "audrey"))
    run_id = alice.post("/api/runs", json={"question": "Pourquoi paiement est lent ?"}, headers=H).json()["run_id"]
    wait_status(alice, run_id)

    # Lecteur et Auditeur ne posent pas de question.
    for c in (lea, audrey):
        assert c.post("/api/runs", json={"question": "Une question"}, headers=H).status_code == 403

    # Partage : le Lecteur ne voit que les investigations partagées, sans prompts ni appels d'outils.
    assert lea.get(f"/api/runs/{run_id}").status_code == 404 and lea.get("/api/runs").json() == []
    assert bob.post(f"/api/runs/{run_id}/share", json={"shared": True}, headers=H).status_code == 404
    assert alice.post(f"/api/runs/{run_id}/share", json={"shared": True}, headers=H).json() == {"shared": True}
    assert [r["run_id"] for r in lea.get("/api/runs").json()] == [run_id]
    data = lea.get(f"/api/runs/{run_id}").json()
    assert data["can_details"] is False and data["can_share"] is False and "max_connections" in data["analysis"]
    assert lea.get(f"/api/runs/{run_id}/agents/lead").status_code == 403
    assert "event: end" in lea.get(f"/api/runs/{run_id}/events").text  # graphe et chronologie
    assert bob.get(f"/api/runs/{run_id}").json()["can_details"] is False  # partagée : lisible, sans détails
    # L'Auditeur lit tout, prompts compris, sans rien piloter.
    assert audrey.get(f"/api/runs/{run_id}/agents/lead").status_code == 200
    assert audrey.post(f"/api/runs/{run_id}/category", json={"category": "tendance"}, headers=H).status_code == 403

    # Revue des actions : Superviseur seulement ; l'action validée n'est jamais exécutée.
    assert admin.get("/api/actions").status_code == 403 and alice.get("/api/actions").status_code == 403
    pending = sophie.get("/api/actions").json()
    assert [(a["id"], a["status"], a["run_id"]) for a in pending] == [("A01", "proposed", run_id)]
    url = f"/api/runs/{run_id}/actions/A01/decision"
    assert admin.post(url, json={"accept": True}, headers=H).status_code == 403
    r = sophie.post(url, json={"accept": True, "comment": "à planifier"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "validated" and r.json()["decision"]["by"] == "sophie"
    assert sophie.post(url, json={"accept": False}, headers=H).status_code == 409
    assert alice.get(f"/api/runs/{run_id}").json()["actions"][0]["status"] == "validated"

    # Coûts : Superviseur, Administrateur, Auditeur ; journal d'accès : Administrateur et Auditeur.
    assert alice.get("/api/costs").status_code == 403 and lea.get("/api/costs").status_code == 403
    costs = admin.get("/api/costs").json()
    assert costs["total"]["runs"] == 1 and costs["rows"][0]["user"] == "alice"
    assert sophie.get("/api/costs").status_code == 200 and audrey.get("/api/costs").status_code == 200
    assert sophie.get("/api/access-log").status_code == 403
    log = audrey.get("/api/access-log").json()
    assert {"share", "action_decision"} <= {e["action"] for e in log}


def test_rerun_keeps_a_link_to_the_original_run(env):
    app, script = env
    alice = client(app, "alice")
    script["lead"] = ScriptedProvider([answer("## Synthèse\nok"), answer("## Synthèse\nok")])
    first = alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?"}, headers=H).json()["run_id"]
    wait_status(alice, first)
    # Relance avec d'autres options : nouvelle investigation, liée à l'originale.
    second = alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?", "category": "information",
                                           "models": "openai", "rerun_of": first}, headers=H).json()["run_id"]
    manifest = wait_status(alice, second)["manifest"]
    assert second != first and manifest["rerun_of"] == first
    assert manifest["models_profile"] == "openai" and manifest["category"]["source"] == "user"
    assert "rerun_of" not in wait_status(alice, first)["manifest"]
    for bad in ("20990101T000000Z-0000", "../../etc"):
        assert alice.post("/api/runs", json={"question": "Qui est srv-pay-01 ?", "rerun_of": bad},
                          headers=H).status_code == 400
