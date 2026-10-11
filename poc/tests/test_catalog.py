import pytest

from diagagent import catalog


def test_catalog_summary_lists_all_sources():
    summary = catalog.catalog_summary()
    for source in ["incidents", "changes", "events", "logs-applicatifs", "cmdb", "metrics-demo"]:
        assert f"- {source} " in summary


def test_search_filters_period_and_masks_fields():
    res = catalog.search("incidents", filters={"affected_ci.hostname": "srv-pay-01"},
                         time_from="2026-10-01T00:00:00Z")
    assert [h["number"] for h in res["hits"]] == ["INC0098765"]
    assert "caller_email" not in res["hits"][0]


def test_search_default_period_is_last_24h():
    res = catalog.search("changes")
    assert {h["number"] for h in res["hits"]} == {"CHG0034567", "CHG0034550"}
    assert res["time_range"][1].startswith("2026-10-07T06:00")


def test_search_size_is_capped_by_source_limits():
    res = catalog.search("logs-applicatifs", size=10_000)
    assert res["returned"] == 100 and res["truncated"]


def test_aggregate_finds_dominant_error():
    res = catalog.aggregate("logs-applicatifs", "message", filters={"host": "srv-pay-01", "level": "ERROR"})
    top = res["buckets"][0]
    assert "connection pool exhausted" in top["value"]
    assert top["first_seen"].startswith("2026-10-06T22:1")


def test_api_base_url_accepts_urls_copied_from_the_web_ui():
    assert catalog.api_base_url("http://192.168.1.15:9090/query") == "http://192.168.1.15:9090"
    assert catalog.api_base_url("http://192.168.1.15:9093/#/alerts") == "http://192.168.1.15:9093"
    assert catalog.api_base_url("https://h/prometheus/") == "https://h/prometheus"


def test_search_rejects_unknown_filter_field():
    # affected_ci.hostname existe dans incidents, pas dans changes (ci.hostname) : sans contrôle,
    # la recherche renvoyait 0 résultat et le modèle concluait qu'aucun changement n'avait eu lieu.
    with pytest.raises(ValueError, match=r"affected_ci\.hostname.*ci\.hostname"):
        catalog.search("changes", filters={"affected_ci.hostname": "db-pay-02"})
    res = catalog.search("changes", filters={"ci.hostname": "db-pay-02"})
    assert [h["number"] for h in res["hits"]] == ["CHG0034567"]


def test_unknown_fields_list_excludes_masked_fields():
    with pytest.raises(ValueError) as exc:
        catalog.search("incidents", filters={"host": "srv-pay-01"})
    assert "caller_email" not in str(exc.value)


def test_aggregate_rejects_unknown_field():
    with pytest.raises(ValueError, match="msg"):
        catalog.aggregate("logs-applicatifs", "msg")


def test_search_rejects_operator_filters_and_lists_values():
    # {"$nin": [...]} était comparé comme du texte : 0 incident ouvert, sans erreur.
    with pytest.raises(ValueError, match=r"pas d'opérateur.*Valeurs présentes pour state : .*In Progress"):
        catalog.search("incidents", filters={"affected_ci.hostname": "srv-pay-01",
                                             "state": {"$nin": ["Resolved", "Closed"]}})
    with pytest.raises(ValueError, match="non pris en charge"):
        catalog.aggregate("incidents", "state", filters={"priority": [{"gte": 2}]})
    res = catalog.search("incidents", filters={"affected_ci.hostname": "srv-pay-01", "state": ["New", "In Progress"]},
                         time_from="2026-10-01T00:00:00Z")
    assert [h["number"] for h in res["hits"]] == ["INC0098765"]


def test_empty_search_reports_matches_outside_the_time_range():
    # Heure de référence 2 jours après l'ouverture : la période par défaut (24 h) ne contient pas le ticket.
    res = catalog.search("incidents", filters={"number": "INC0098765"}, time_from="2026-10-08T00:00:00Z",
                         time_to="2026-10-09T00:00:00Z")
    assert res["total"] == 0
    assert res["outside_time_range"] == {"total": 1, "first": "2026-10-06T22:25:00Z", "last": "2026-10-06T22:25:00Z"}
    assert "élargis time_from" in res["note"]
    assert "outside_time_range" not in catalog.search("incidents", filters={"number": "INC0000000"})


def test_masked_fields_cannot_be_confirmed_by_search():
    # caller_email est masqué : ni filtre, ni recherche texte, ni agrégation ne doivent en confirmer une valeur.
    email = "support.n1@example.com"
    assert catalog.search("incidents", text=email, time_from="2026-09-01T00:00:00Z")["total"] == 0
    assert "outside_time_range" not in catalog.search("incidents", text=email)
    with pytest.raises(ValueError, match="caller_email"):
        catalog.search("incidents", filters={"caller_email": email})
    with pytest.raises(ValueError, match="caller_email"):
        catalog.aggregate("incidents", "caller_email")


def test_filter_values_absent_from_the_source_are_reported():
    # « Ouvert », « Assigned » n'existent pas dans incidents.state : 0 résultat se lisait « aucun incident ouvert ».
    res = catalog.search("incidents", filters={"affected_ci.hostname": "srv-pay-01",
                                               "state": ["Ouvert", "New", "Assigned"]})
    assert res["unknown_values"] == {"state": {"absentes": ["Ouvert", "Assigned"],
                                               "présentes": ["Closed", "In Progress", "New", "Resolved"]}}
    assert "absente(s) du champ state" in res["note"]
    assert "unknown_values" not in catalog.search("incidents", filters={"state": "in progress"},
                                                   time_from="2026-10-01T00:00:00Z")


def test_filter_on_an_object_field_names_its_subfields():
    with pytest.raises(ValueError, match=r"ci est un objet.*ci\.hostname, ci\.id"):
        catalog.search("changes", filters={"ci": ["CI0012345", "CI0012400"]})
    res = catalog.search("changes", filters={"ci.id": ["CI0012345", "CI0012400"]}, time_from="2026-10-05T00:00:00Z")
    assert "CHG0034567" in [h["number"] for h in res["hits"]]


def test_filters_ignore_case_and_text_fields_match_words():
    # Recherches réelles de gpt-4.1-mini qui revenaient vides.
    assert catalog.search("events", filters={"severity": ["MAJOR", "MINOR"], "status": "open"})["total"] == 2
    hits = catalog.search("events", filters={"host": "srv-pay-01", "message": "latence"})["hits"]
    assert [h["@timestamp"] for h in hits] == ["2026-10-06T22:12:00Z"]


def test_search_window_includes_its_end(monkeypatch):
    # Change lancé à l'heure exacte où la recherche s'arrête (début du symptôme) : il doit sortir.
    monkeypatch.setenv("DIAGAGENT_NOW", "2026-09-29T15:30:00Z")
    hits = catalog.search("changes", filters={"ci.hostname": "srv-api-02"},
                          time_from="2026-09-27T14:30:00Z", time_to="2026-09-29T14:30:00Z")["hits"]
    assert [h["number"] for h in hits] == ["CHG0034320"]


def test_empty_search_says_which_filter_removes_the_results():
    # Recherche réelle de gpt-4.1-mini : severity devinée, l'alerte de latence est major.
    res = catalog.search("events", filters={"host": "srv-pay-01", "check": "http.latency_p95", "severity": "critical"})
    assert res["total"] == 0 and res["without_filter"] == {"severity": 1}
    assert "1 sans le filtre severity" in res["note"]
