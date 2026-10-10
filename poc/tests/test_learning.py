import asyncio
import json
import shutil

import pytest
import yaml

from conftest import POC
from diagagent import cli, knowledge, learning, playbooks
from diagagent.llm import LLMResponse
from diagagent.llm.scripted import ScriptedProvider
from diagagent.orchestrator import load_roles
from test_agent import _load_with_runs
from test_orchestrator import answer
from test_playbooks import classifier, with_classifier


@pytest.fixture
def books_dir(tmp_path, monkeypatch):
    """Copie des playbooks : les tests qui acceptent une proposition ne touchent pas au dépôt."""
    target = tmp_path / "playbooks"
    shutil.copytree(POC / "playbooks", target, ignore=shutil.ignore_patterns("proposals", "history"))
    monkeypatch.setenv("DIAGAGENT_PLAYBOOKS_DIR", str(target))
    return target


def run(tmp_path, question, category, lead_text="## Synthèse\nmax_connections réduit par CHG0034567 [lead/calls/0001.json]",
        **clf):
    lead = ScriptedProvider([answer(lead_text)] * 2)  # relance des vagues du playbook, puis même réponse
    log, status, _ = asyncio.run(cli.ask(question, providers=with_classifier(
        lead, classifier(category=category, confidence="high", **clf))))
    return log, lead


def correct(tmp_path, log, to):
    manifest = json.loads((log.dir / "manifest.json").read_text())
    path = tmp_path / "runs" / "feedback" / "categories.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps({"run_id": log.run_id, "question": manifest["question"],
                            "from": manifest["category"]["id"], "to": to, "by": "alice", "at": "x"}) + "\n")


def always(category):
    """Classifieur qui répond toujours la même catégorie (rejeu)."""
    def step(_request):
        return LLMResponse(text=json.dumps({"category": category, "confidence": "high"}), tool_calls=[], stop_reason="end")
    return ScriptedProvider([step] * 50)


def test_confirmed_case_is_reused_as_deja_vu(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    log, _ = run(tmp_path, "Pourquoi paiement est lent sur srv-pay-01 ?", "performance",
                 entities={"host": "srv-pay-01"})
    knowledge.record_feedback(log.dir, tmp_path / "runs", "utile", "alice", cause="max_connections 500 -> 200")
    case = knowledge.create_case(log.dir, "alice", "max_connections réduit à 200 par CHG0034567")
    assert case["category"] == "performance" and case["entities"] == {"host": "srv-pay-01"}
    assert case["decisive_evidence"] == ["lead/calls/0001.json"]
    assert (tmp_path / "knowledge" / "cases" / f"{log.run_id}.yaml").exists()

    # Nouvelle demande proche : le cas est donné à l'agent principal, et la demande confirmée au classifieur.
    log2, lead = run(tmp_path, "srv-pay-01 est lent ce matin", "performance", entities={"host": "srv-pay-01"})
    assert f"{log.run_id} [performance] host = srv-pay-01" in lead.requests[0].system
    events = [json.loads(line) for line in (log2.dir / "events.jsonl").read_text().splitlines()]
    assert any(e["type"] == "similar_cases" for e in events)


def test_confirmed_requests_are_given_to_the_classifier(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    log, _ = run(tmp_path, "Le stockage NAS-02 rame", "information")
    correct(tmp_path, log, "performance")
    clf = classifier(category="performance", confidence="high")
    asyncio.run(cli.ask("Le stockage NAS-03 rame", providers=with_classifier(ScriptedProvider([answer("ok")] * 2), clf)))
    assert "« Le stockage NAS-02 rame » → performance" in clf.requests[0].system


def test_draft_category_is_observed_not_applied(tmp_path, monkeypatch, books_dir):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    draft = yaml.safe_load((books_dir / "tendance.yaml").read_text())
    draft.update(id="capacite", status="draft", description="Prévision de capacité")
    (books_dir / "capacite.yaml").write_text(yaml.safe_dump(draft, allow_unicode=True))
    log, lead = run(tmp_path, "Aura-t-on assez de disque en décembre ?", "capacite", alternative="tendance")
    category = json.loads((log.dir / "manifest.json").read_text())["category"]
    assert category["id"] == "tendance" and category["draft_match"] == "capacite"
    assert "Playbook capacite" not in lead.requests[0].system
    assert json.loads((tmp_path / "runs" / "index.jsonl").read_text().splitlines()[-1])["draft_match"] == "capacite"


def test_learn_proposes_replays_and_a_supervisor_decides(tmp_path, monkeypatch, books_dir):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    runs_dir = tmp_path / "runs"
    v = yaml.safe_load((books_dir / "performance.yaml").read_text())["version"]
    log, _ = run(tmp_path, "Le stockage NAS-02 rame", "information")
    correct(tmp_path, log, "performance")

    written = learning.learn(runs_dir, classifier=always("information"), roles=set(load_roles()))
    assert [(p["kind"], p["target"], p["status"]) for p in written] == [("add_examples", "performance", "pending")]
    assert written[0]["change"] == {"examples": ["Le stockage NAS-02 rame"]}
    assert written[0]["evidence"] == [log.run_id]
    replay = written[0]["replay"]
    assert replay["cases"] >= 10 and replay["ok"] and replay["after"] == replay["before"]
    # Un second passage ne repropose pas la même chose.
    assert learning.learn(runs_dir, roles=set(load_roles())) == []

    accepted = learning.decide(written[0]["id"], True, "sophie", "ok", roles=set(load_roles()))
    assert accepted["status"] == "accepted" and accepted["applied_version"] == v + 1
    book = yaml.safe_load((books_dir / "performance.yaml").read_text())
    assert book["version"] == v + 1 and "Le stockage NAS-02 rame" in book["examples"]
    assert (books_dir / "history" / f"performance-v{v}.yaml").exists()
    decisions = (books_dir / "proposals" / "decisions.jsonl").read_text().splitlines()
    assert json.loads(decisions[-1])["by"] == "sophie"
    with pytest.raises(ValueError, match="déjà accepted"):
        learning.decide(written[0]["id"], False, "sophie")

    # Retour arrière : la version d'origine revient, la suivante reste dans history/.
    assert playbooks.rollback("performance")["version"] == v
    assert (books_dir / "history" / f"performance-v{v + 1}.yaml").exists()


def test_proposal_that_degrades_classification_is_discarded(tmp_path, monkeypatch, books_dir):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    log, _ = run(tmp_path, "Le stockage NAS-02 rame", "information")
    correct(tmp_path, log, "performance")

    def degrading(request):
        # Avec les playbooks actuels, tout est classé performance ; avec l'exemple proposé, plus rien.
        category = "autre" if "NAS-02 rame" in request.system else "performance"
        return LLMResponse(text=json.dumps({"category": category, "confidence": "high"}), tool_calls=[], stop_reason="end")

    written = learning.learn(tmp_path / "runs", classifier=ScriptedProvider([degrading] * 100), roles=set(load_roles()))
    assert written[0]["status"] == "discarded" and not written[0]["replay"]["ok"]
    assert written[0]["replay"]["after"] < written[0]["replay"]["before"]


def test_model_proposals_are_validated(tmp_path, monkeypatch, books_dir):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    run(tmp_path, "Aura-t-on assez de disque en décembre ?", "autre")
    new_book = {"id": "capacite", "description": "Prévision de capacité", "examples": ["assez de disque ?"],
                "steps": [{"name": "tendance", "parallel": [{"role": "metrics", "objective": "croissance"}]}],
                "stop_when": ["prévision faite"], "output": ["synthese"], "owner": "équipe capacité"}
    drafter = ScriptedProvider([LLMResponse(text=json.dumps({"proposals": [
        {"kind": "new_category", "target": "capacite", "rationale": "demandes récurrentes", "evidence": ["r1"],
         "change": {"playbook": new_book}},
        {"kind": "new_category", "target": "bad", "rationale": "x", "change": {"playbook": {"id": "bad"}}},
        {"kind": "add_hypotheses", "target": "inconnue", "rationale": "x", "change": {"hypotheses": []}},
    ]}), tool_calls=[], stop_reason="end")])
    notes = []
    written = learning.learn(tmp_path / "runs", drafter=drafter, roles=set(load_roles()), log=notes.append)
    assert [(p["kind"], p["target"]) for p in written] == [("new_category", "capacite")]
    assert sum("écartée" in n for n in notes) == 2
    assert "Aura-t-on assez de disque" in drafter.requests[0].messages[0].content

    learning.decide(written[0]["id"], True, "sophie", roles=set(load_roles()))
    created = yaml.safe_load((books_dir / "capacite.yaml").read_text())
    assert created["status"] == "draft" and created["version"] == 1
    assert "capacite" not in playbooks.load_playbooks() and "capacite" in playbooks.load_playbooks(("draft",))


def test_draft_with_enough_matches_gets_an_activation_proposal(tmp_path, monkeypatch, books_dir):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    draft = yaml.safe_load((books_dir / "tendance.yaml").read_text())
    draft.update(id="capacite", status="draft")
    (books_dir / "capacite.yaml").write_text(yaml.safe_dump(draft, allow_unicode=True))
    for i in range(learning.ACTIVATE_AFTER):
        run(tmp_path, f"Disque plein en décembre {i} ?", "capacite", alternative="tendance")
    written = learning.learn(tmp_path / "runs", roles=set(load_roles()))
    assert [(p["kind"], p["target"]) for p in written] == [("activate", "capacite")]
    learning.decide(written[0]["id"], True, "sophie", roles=set(load_roles()))
    assert "capacite" in playbooks.load_playbooks()


def test_indicators_by_category(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    log1, _ = run(tmp_path, "Q1 lente", "performance")
    log2, _ = run(tmp_path, "Q2", "autre")
    correct(tmp_path, log1, "indisponibilite")
    knowledge.record_feedback(log2.dir, tmp_path / "runs", "faux", "alice")
    ind = learning.indicators(tmp_path / "runs")
    assert ind["runs"] == 2 and ind["autre_share"] == 0.5
    rows = {r["category"]: r for r in ind["categories"]}
    assert rows["performance"]["corrected_share"] == 1.0
    assert rows["autre"]["useful_share"] == 0.0 and rows["autre"]["feedback"] == 1
