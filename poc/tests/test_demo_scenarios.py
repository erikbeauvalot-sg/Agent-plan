"""Incidents passés de démonstration : rejoués à leur heure de référence, les sources ne montrent ni la
suite ni la résolution, et chaque preuve attendue par le jeu d'évaluation y est visible."""

import json
import re
import sys
from datetime import datetime, timedelta

import yaml

from conftest import POC
from diagagent import catalog
from diagagent.connectors.metrics import DemoMetrics

sys.path.insert(0, str(POC / "demo_data"))
from scenarios import SCENARIOS  # noqa: E402

CASES = [c for c in yaml.safe_load((POC / "eval" / "cases.yaml").read_text(encoding="utf-8"))["cases"]
         if c.get("kind") == "incident" and "now" in c]


def _at(monkeypatch, now):
    monkeypatch.setenv("DIAGAGENT_NOW", now)


def test_as_of_hides_the_future():
    card = {"time_field": "opened_at",
            "as_of": [{"field": "resolved_at", "before": {"state": "In Progress"}, "hide": ["resolution"]}]}
    docs = ({"n": 1, "opened_at": "2026-10-07T05:00:00Z", "state": "Resolved", "resolved_at": "2026-10-07T09:00:00Z",
             "resolution": "purge"},
            {"n": 2, "opened_at": "2026-10-07T07:00:00Z", "state": "New"},
            {"n": 3, "opened_at": "2026-10-06T05:00:00Z", "state": "Resolved", "resolved_at": "2026-10-06T09:00:00Z",
             "resolution": "purge"})
    assert catalog.as_of(card, docs) == (
        {"n": 1, "opened_at": "2026-10-07T05:00:00Z", "state": "In Progress"}, docs[2])
    assert catalog.as_of({}, docs) == docs


def test_every_incident_scenario_has_a_case():
    numbers = {s["incident"]["number"] for s in SCENARIOS}
    asked = {n for c in CASES for n in re.findall(r"INC\d{7}", c["question"])}
    assert asked <= numbers
    assert len(CASES) == len(SCENARIOS) == 17


def test_incident_replayed_at_its_reference_time(monkeypatch):
    s = next(s for s in SCENARIOS if s["incident"]["number"] == "INC0099104")
    _at(monkeypatch, "2026-09-18T10:45:00Z")
    ticket = catalog.search("incidents", filters={"number": "INC0099104"}, time_from="2026-09-18T00:00:00Z")["hits"]
    assert ticket[0]["state"] == "In Progress" and "resolution" not in ticket[0] and "resolved_at" not in ticket[0]
    alerts = catalog.search("events", filters={"host": "dns-01"}, time_from="2026-09-18T00:00:00Z")["hits"]
    assert [a["status"] for a in alerts] == ["open"] and "closed_at" not in alerts[0]
    end = datetime.fromisoformat("2026-09-19T00:00:00+00:00")
    points = DemoMetrics(catalog.get_source("metrics-demo")).series("dns-01", "dns.queries_per_s",
                                                                     end - timedelta(days=2), end, 300)
    assert points and points[-1][0] <= catalog.now()
    # Plus tard, le ticket est résolu et sa résolution visible.
    _at(monkeypatch, "2026-09-19T10:00:00Z")
    ticket = catalog.search("incidents", filters={"number": "INC0099104"}, time_from="2026-09-18T00:00:00Z")["hits"]
    assert ticket[0]["state"] == "Resolved" and ticket[0]["resolution"] == s["incident"]["resolution"]


def test_expected_evidence_is_visible_at_reference_time(monkeypatch):
    """Chaque identifiant attendu (CHG, host, adresse, port) existe dans les données visibles à l'heure de
    référence du cas : le cas peut être résolu, et la résolution du ticket ne le résout pas à sa place."""
    for case in CASES:
        _at(monkeypatch, case["now"])
        visible = json.dumps([catalog.rows(s) for s in ("incidents", "changes", "events", "logs-applicatifs", "cmdb")],
                             ensure_ascii=False).lower()
        for expected in case["must_mention"]:
            options = expected if isinstance(expected, list) else [expected]
            identifiers = [o for o in options if re.search(r"\d|-", str(o))]
            if identifiers:
                assert any(str(o).lower() in visible for o in identifiers), (case["id"], expected)
        number = re.findall(r"INC\d{7}", case["question"])
        if number:
            ticket = next(t for t in catalog.rows("incidents") if t["number"] == number[0])
            assert ticket["state"] == "In Progress" and "resolution" not in ticket, case["id"]
