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
