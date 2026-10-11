"""Configuration modifiable depuis l'interface : validation, conflit, historique, droits et journal."""

import json
import shutil

import pytest
import yaml

from conftest import POC
from diagagent import catalog, config_files
from diagagent.web.auth import FileUserStore, Sessions
from test_web import PWD, client, H

from diagagent.web.app import create_app


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Copie de la configuration : les tests n'écrivent jamais dans les vrais fichiers."""
    root = tmp_path / "home"
    for d in ("catalog", "config", "agents", "playbooks", "prompts", "eval", "demo_data"):
        shutil.copytree(POC / d, root / d, ignore=shutil.ignore_patterns("results", "history", "proposals"))
    monkeypatch.setenv("DIAGAGENT_HOME", str(root))
    monkeypatch.delenv("DIAGAGENT_PLAYBOOKS_DIR", raising=False)
    monkeypatch.setenv("DIAGAGENT_CONFIG_HISTORY_DIR", str(tmp_path / "history"))
    monkeypatch.setenv("DIAGAGENT_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("DIAGAGENT_RUNS_DIR", str(tmp_path / "runs"))
    catalog.load_catalog.cache_clear()
    return root


def test_only_configuration_files_are_editable(home):
    assert config_files.rule_of("playbooks/performance.yaml")[:2] == ("playbook", "edit_diagnostic")
    assert config_files.rule_of("catalog/sources/cmdb.yaml")[:2] == ("source", "edit_platform")
    for path in ("auth/users.yaml", "../.env", "src/diagagent/agent.py", "playbooks/history/x.yaml",
                 "runs/index.jsonl", "/etc/passwd", "catalog/sources/../../auth/users.yaml"):
        with pytest.raises(config_files.ConfigError):
            config_files.rule_of(path)
    paths = {f["path"] for f in config_files.list_files()}
    assert {"config/models.yaml", "prompts/lead.md", "agents/system.yaml", "eval/cases.yaml"} <= paths


def test_every_current_file_is_valid(home):
    for f in config_files.list_files():
        config_files.validate(f["path"], config_files.read(f["path"])["content"])


@pytest.mark.parametrize("path, change, message", [
    ("playbooks/performance.yaml", lambda t: t.replace("status: active", "status: oui"), "status doit valoir"),
    ("playbooks/performance.yaml", lambda t: t.replace("role: metrics", "role: inconnu", 1), "rôle inconnu"),
    ("catalog/sources/cmdb.yaml", lambda t: t.replace("id: cmdb", "id: autre"), "différent du nom"),
    ("config/models.yaml", lambda t: t.replace("provider: local", "provider: nulle-part", 1), "fournisseur inconnu"),
    ("config/poc.yaml", lambda t: t.replace("max_parallel: 6", "max_parallel: beaucoup"), "orchestration"),
    ("agents/host.yaml", lambda t: t + "\nbudget: {max_tool_calls: -1}\n", "budget invalide"),
    ("prompts/subagent.md", lambda t: t + "\n{inconnue}\n", "Variables inconnues"),
    ("prompts/lead.md", lambda t: t + "\n{ouverte\n", "Accolade"),
    ("eval/cases.yaml", lambda t: t + "\n  - {id: diag-paiement, question: double}\n", "en double"),
    ("catalog/glossary.yaml", lambda t: "clé: [non fermée", "YAML invalide"),
])
def test_invalid_content_is_refused_and_nothing_written(home, path, change, message):
    before = config_files.read(path)
    with pytest.raises(config_files.ConfigError, match=message):
        config_files.save(path, change(before["content"]), before["version"], "admin", "test")
    assert config_files.read(path)["content"] == before["content"]
    assert config_files.history(path) == []


def test_save_keeps_history_and_detects_conflicts(home):
    path = "config/poc.yaml"
    original = config_files.read(path)
    edited = original["content"].replace("max_parallel: 6", "max_parallel: 4")
    with pytest.raises(config_files.ConfigError, match="commentaire est obligatoire"):
        config_files.save(path, edited, original["version"], "admin", "  ")
    saved = config_files.save(path, edited, original["version"], "admin", "Moins de parallélisme")
    assert saved["previous"] == original["version"] and saved["version"] == config_files.version_of(edited)
    assert yaml.safe_load((home / path).read_text())["orchestration"]["max_parallel"] == 4
    # Un second éditeur parti de la même version ne l'écrase pas.
    with pytest.raises(config_files.ConflictError, match="modifié depuis votre lecture"):
        config_files.save(path, original["content"] + "\n# autre\n", original["version"], "admin2", "x")
    history = config_files.history(path)
    assert [(h["author"], h["comment"]) for h in history] == [
        ("admin", "Moins de parallélisme"), (None, "Version d'origine, avant la première modification")]
    # Revenir en arrière : enregistrer l'ancienne version, tracé comme le reste.
    first = config_files.version_text(path, history[-1]["id"])
    assert first == original["content"]
    assert "-  max_parallel: 6" in config_files.diff(edited, first) or "+  max_parallel: 6" in config_files.diff(edited, first)
    config_files.save(path, first, saved["version"], "admin", "Retour à l'origine")
    assert config_files.read(path)["content"] == original["content"]


def test_new_playbook_and_source_take_effect(home):
    book = yaml.safe_load((home / "playbooks" / "tendance.yaml").read_text())
    book.update(id="securite", status="draft")
    config_files.save("playbooks/securite.yaml", yaml.safe_dump(book, allow_unicode=True), None, "sup", "Nouvelle catégorie")
    assert (home / "playbooks" / "securite.yaml").exists()
    with pytest.raises(config_files.ConfigError, match="ne peut pas être créé"):
        config_files.save("prompts/autre.md", "x", None, "sup", "x")
    card = (home / "catalog/sources/cmdb.yaml").read_text().replace("id: cmdb", "id: cmdb-bis")
    catalog.get_source("cmdb")  # met le catalogue en cache
    config_files.save("catalog/sources/cmdb-bis.yaml", card, None, "admin", "Seconde CMDB")
    assert "cmdb-bis" in catalog.load_catalog()


@pytest.fixture
def app(home, tmp_path):
    store = FileUserStore(tmp_path / "users.yaml")
    store.add("admin", PWD, ["administrateur"])
    store.add("sup", PWD, ["superviseur"])
    store.add("op", PWD, ["operateur"])
    store.add("audit", PWD, ["auditeur"])
    return create_app(providers=lambda profile=None: None, users=store, sessions=Sessions(b"k" * 32))


def test_config_rights_follow_the_role_matrix(app, home, tmp_path):
    admin, sup, op, aud = (client(app, u) for u in ("admin", "sup", "op", "audit"))
    assert op.get("/api/config").status_code == 403
    files = {f["path"]: f["editable"] for f in aud.get("/api/config").json()["files"]}
    assert files["playbooks/performance.yaml"] is False and files["config/models.yaml"] is False
    sup_files = {f["path"]: f["editable"] for f in sup.get("/api/config").json()["files"]}
    assert sup_files["playbooks/performance.yaml"] and not sup_files["config/models.yaml"]

    f = sup.get("/api/config/file", params={"path": "prompts/lead.md"}).json()
    body = {"path": "prompts/lead.md", "content": f["content"] + "\n- Réponds en français.\n",
            "version": f["version"], "comment": "Langue"}
    assert admin.post("/api/config/file", json=body, headers=H).status_code == 403  # séparation des tâches
    assert aud.post("/api/config/file", json=body, headers=H).status_code == 403
    ok = sup.post("/api/config/file", json=body, headers=H)
    assert ok.status_code == 200
    assert sup.post("/api/config/file", json=body, headers=H).status_code == 409  # version périmée
    bad = sup.post("/api/config/validate", json={**body, "content": "{x}"}, headers=H).json()
    assert bad["ok"] is False and "Variables inconnues" in bad["error"]

    history = aud.get("/api/config/history", params={"path": "prompts/lead.md"}).json()
    assert history[0]["author"] == "sup"
    v = aud.get("/api/config/version", params={"path": "prompts/lead.md", "id": history[-1]["id"]}).json()
    assert "+- Réponds en français." in v["diff"]
    assert aud.get("/api/config/file", params={"path": "auth/users.yaml"}).status_code == 400
    entries = [json.loads(line) for p in (tmp_path / "audit").glob("*/*/*.jsonl") for line in p.read_text().splitlines()]
    changed = [e for e in entries if e["action"] == "config_changed"]
    assert changed == [{**changed[0], "user": "sup", "path": "prompts/lead.md", "comment": "Langue",
                        "after": ok.json()["version"]}]


def test_accounts_are_managed_without_exposing_passwords(app, tmp_path):
    admin, sup = client(app, "admin"), client(app, "sup")
    assert sup.get("/api/users").status_code == 403
    accounts = admin.get("/api/users").json()
    assert {a["login"] for a in accounts} == {"admin", "sup", "op", "audit"}
    assert all("password_hash" not in a for a in accounts)
    created = admin.post("/api/users", json={"login": "nouveau", "roles": ["lecteur"], "password": PWD}, headers=H).json()
    assert created["roles"] == ["lecteur"] and "password_hash" not in created
    assert admin.post("/api/users", json={"login": "court", "roles": ["lecteur"], "password": "x"}, headers=H).status_code == 422
    uid = created["id"]
    assert admin.post(f"/api/users/{uid}", json={"roles": ["operateur"]}, headers=H).json()["roles"] == ["operateur"]
    assert admin.post(f"/api/users/{uid}", json={"status": "disabled"}, headers=H).json()["status"] == "disabled"
    assert client(app).post("/api/login", json={"login": "nouveau", "password": PWD}).status_code == 401
    admin.post(f"/api/users/{uid}", json={"status": "active", "password": "un-autre-mot-de-passe"}, headers=H)
    assert client(app).post("/api/login", json={"login": "nouveau", "password": "un-autre-mot-de-passe"}).status_code == 200
    # Le dernier administrateur actif ne peut pas être retiré.
    admin_id = next(a["id"] for a in accounts if a["login"] == "admin")
    refused = admin.post(f"/api/users/{admin_id}", json={"roles": ["operateur"]}, headers=H)
    assert refused.status_code == 422 and "administrateur actif" in refused.json()["detail"]
    log = [json.loads(line) for p in (tmp_path / "audit").glob("*/*/*.jsonl") for line in p.read_text().splitlines()]
    assert all("password" not in json.dumps({k: v for k, v in e.items() if k != "password_reset"}).replace(
        "password_reset", "") for e in log)
    assert [e["action"] for e in log if e["action"].startswith("user_")][:2] == ["user_created", "user_updated"]
