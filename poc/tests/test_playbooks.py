import asyncio
import json

import pytest

from diagagent import cli, playbooks
from diagagent.llm import LLMResponse
from diagagent.llm.scripted import ScriptedProvider
from diagagent.orchestrator import load_roles
from test_agent import _load_with_runs
from test_orchestrator import answer, call, tools


def classifier(**out):
    return ScriptedProvider([LLMResponse(text="Voici :\n" + json.dumps(out), tool_calls=[], stop_reason="end")])


def with_classifier(lead, clf, **others):
    providers = {"lead": lead, "classifier": clf, **others}
    return lambda role: (providers[role], {})


def test_all_playbooks_are_valid_and_use_known_roles():
    books = playbooks.load_playbooks(include=playbooks.STATUSES)
    assert set(books) == {"information", "indisponibilite", "performance", "analyse-evenement",
                          "impact-change", "tendance", "autre"}
    roles = set(load_roles())
    for book in books.values():
        playbooks.validate(book, roles=roles)


def test_parse_classification_keeps_only_known_values():
    books = playbooks.load_playbooks()
    c = playbooks.parse_classification(json.dumps({
        "category": "inconnue", "confidence": "énorme", "alternative": "inconnue",
        "entities": {"host": "srv-pay-01", "service": ""}, "missing": ["service"]}), books)
    assert (c.category, c.confidence, c.alternative) == ("autre", "low", None)
    assert c.entities == {"host": "srv-pay-01"} and c.missing == []
    with pytest.raises(playbooks.PlaybookError):
        playbooks.parse_classification("pas de JSON", books)


@pytest.mark.parametrize("out, mode, categories", [
    ({"category": "performance", "confidence": "high"}, "playbook", ["performance"]),
    ({"category": "performance", "confidence": "medium", "alternative": "indisponibilite"},
     "combined", ["performance", "indisponibilite"]),
    ({"category": "performance", "confidence": "high", "alternative": "indisponibilite"}, "playbook", ["performance"]),
    ({"category": "indisponibilite", "confidence": "high", "missing": ["service"]}, "clarify", ["indisponibilite"]),
    ({"category": "autre", "confidence": "low"}, "generic", ["autre"]),
])
def test_decision(out, mode, categories):
    books = playbooks.load_playbooks()
    decision = playbooks.decide(playbooks.parse_classification(json.dumps(out), books), books)
    assert (decision.mode, decision.categories) == (mode, categories)


def test_playbook_guides_the_lead_and_is_traced(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    lead = ScriptedProvider([answer("## Synthèse\nCHG0034567")])
    clf = classifier(category="performance", confidence="high", entities={"service": "paiement"})
    log, status, _ = asyncio.run(cli.ask("Pourquoi le service paiement est-il lent ?",
                                         providers=with_classifier(lead, clf)))
    assert status == "completed"
    # Le classifieur voit les catégories et leurs exemples ; l'agent principal reçoit le playbook.
    assert "## indisponibilite" in clf.requests[0].system and "Le stockage est lent" in clf.requests[0].system
    system = lead.requests[0].system
    version = playbooks.load_playbooks()["performance"]["version"]
    assert f"### Playbook performance (version {version})" in system and "[changes]" in system
    assert "Entités repérées : service = paiement" in system
    manifest = json.loads((log.dir / "manifest.json").read_text())
    assert manifest["category"] == {"id": "performance", "confidence": "high", "source": "classifier",
                                    "mode": "playbook", "playbooks": {"performance": version},
                                    "entities": {"service": "paiement"}}
    index = json.loads((tmp_path / "runs" / "index.jsonl").read_text().splitlines()[-1])
    assert index["category"] == "performance"


def test_missing_entity_asks_for_a_precision_without_running_the_lead(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    lead = ScriptedProvider([])
    clf = classifier(category="indisponibilite", confidence="high", missing=["service"],
                     choices=["Paiement", "Extranet"])
    log, status, text = asyncio.run(cli.ask("Mon site ne fonctionne pas", providers=with_classifier(lead, clf)))
    assert status == "needs_clarification" and lead.requests == []
    assert "De quel site ou application parles-tu ?" in text and "- Extranet" in text


def test_lead_can_requalify_the_request(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    seen = {}

    def final(request):
        seen["playbook"] = request.messages[-1].content
        return answer("## Synthèse\nLenteur extrême, pas une panne.")

    lead = ScriptedProvider([
        tools(call("requalify", {"category": "inconnue", "reason": "x"}, "bad"),
              call("requalify", {"category": "performance", "reason": "le service répond en 4 s"}, "ok")),
        final,
    ])
    clf = classifier(category="indisponibilite", confidence="high", entities={"service": "paiement"})
    log, _, _ = asyncio.run(cli.ask("Paiement est en panne", providers=with_classifier(lead, clf)))
    assert "### Playbook performance" in seen["playbook"]
    manifest = json.loads((log.dir / "manifest.json").read_text())
    assert manifest["category"]["id"] == "performance" and manifest["category"]["source"] == "requalify"
    assert manifest["category"]["history"] == [{"from": "indisponibilite", "reason": "le service répond en 4 s"}]
    events = [json.loads(line) for line in (log.dir / "events.jsonl").read_text().splitlines()]
    assert [e["data"]["to"] for e in events if e["type"] == "category_changed"] == ["performance"]


def test_forced_category_skips_the_classifier(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    lead = ScriptedProvider([answer("ok")])
    clf = ScriptedProvider([])
    log, _, _ = asyncio.run(cli.ask("Q", providers=with_classifier(lead, clf), category="tendance"))
    assert clf.requests == [] and "### Playbook tendance" in lead.requests[0].system
    assert json.loads((log.dir / "manifest.json").read_text())["category"]["source"] == "user"


def test_unreadable_classifier_answer_falls_back_to_generic(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    lead = ScriptedProvider([answer("ok")])
    clf = ScriptedProvider([LLMResponse(text="je ne sais pas", tool_calls=[], stop_reason="end")])
    log, status, _ = asyncio.run(cli.ask("Q", providers=with_classifier(lead, clf)))
    category = json.loads((log.dir / "manifest.json").read_text())["category"]
    assert status == "completed" and category["id"] == "autre" and "illisible" in category["error"]
    assert (log.dir / "lead" / "classification_response.txt").read_text() == "je ne sais pas"


def test_near_miss_category_id_is_matched():
    books = playbooks.load_playbooks()
    c = playbooks.parse_classification('{"category": "analysis-evenement", "confidence": "high", '
                                       '"alternative": "Performance"}', books)
    assert (c.category, c.alternative) == ("analyse-evenement", "performance")
    assert playbooks.parse_classification('{"category": "meteo", "confidence": "high"}', books).category == "autre"


def test_models_and_tokens_are_recorded_per_role_and_agent(tmp_path, monkeypatch):
    from diagagent.llm import Usage

    monkeypatch.setattr(cli, "_load", _load_with_runs(tmp_path))
    clf = ScriptedProvider([LLMResponse(text='{"category": "information", "confidence": "high"}', tool_calls=[],
                                        stop_reason="end", usage=Usage(100, 10), model="nano-1")])
    lead = ScriptedProvider([LLMResponse(text="## Synthèse\nok", tool_calls=[], stop_reason="end",
                                         usage=Usage(1000, 50), model="mini-1")])
    providers = {"lead": (lead, {"model": "mini"}), "classifier": (clf, {"model": "nano"})}
    log, _, _ = asyncio.run(cli.ask("Qui est srv-pay-01 ?", providers=lambda role: providers[role]))
    m = json.loads((log.dir / "manifest.json").read_text())
    assert m["models"]["lead"] == {"provider": "scripted", "model": "mini"}
    assert m["models"]["classifier"] == {"provider": "scripted", "model": "nano"}
    assert m["usage_by_agent"] == {
        "classifier": {"input_tokens": 100, "output_tokens": 10, "reasoning_tokens": 0, "calls": 1, "model": "nano-1"},
        "lead": {"input_tokens": 1000, "output_tokens": 50, "reasoning_tokens": 0, "calls": 1, "model": "mini-1"}}
    assert m["usage"] == {"input_tokens": 1100, "output_tokens": 60, "reasoning_tokens": 0}
