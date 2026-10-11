import asyncio
import json

import yaml

from conftest import POC
from diagagent.tools import ToolHub

SERVERS = yaml.safe_load((POC / "config" / "poc.yaml").read_text())["mcp_servers"]


async def _with_hub(fn):
    async with ToolHub(SERVERS) as hub:
        return await fn(hub)


def test_hub_exposes_tools_of_every_server():
    names = asyncio.run(_with_hub(lambda hub: asyncio.sleep(0, result=set(hub.specs))))
    assert {"list_sources", "search", "get_dependencies", "query_metric"} <= names


def test_metric_break_is_detected():
    async def run(hub):
        return await hub.call("query_metric", {"host": "srv-pay-01", "metric": "http.latency_p95",
                                               "time_from": "2026-10-06T18:00:00Z"})
    res = asyncio.run(_with_hub(run))
    data = json.loads(res.content)
    assert not res.is_error
    assert data["breaks"][0]["at"].startswith("2026-10-06T22:1")


def test_tool_errors_are_returned_not_raised():
    async def run(hub):
        return await hub.call("get_ci", {"id_or_hostname": "inconnu-99"})
    res = asyncio.run(_with_hub(run))
    assert res.is_error and "introuvable" in res.content


def test_resolve_entity_by_business_alias():
    async def run(hub):
        return await hub.call("resolve_entity", {"name": "service paiement"})
    data = json.loads(asyncio.run(_with_hub(run)).content)
    assert {c["hostname"] for c in data["cis"]} == {"srv-pay-01", "db-pay-02"}


def test_resolve_entity_global_scope():
    # « SI » n'est pas un service introuvable : c'est tout le système d'information.
    from diagagent.mcp_servers.catalog_server import resolve_entity
    for name in ("SI", "le système d'information", "la prod", "Systeme d’information"):
        data = resolve_entity(name)
        assert data["found"] and data["scope"] == "global", name
        assert "état global" in data["guidance"].lower() and data["meaning"]
        assert {s["code"] for s in data["services"]} >= {"PAY", "CMD"} and not data["ambiguous"]
    other = resolve_entity("srv-pay-01")
    assert "scope" not in other and other["found"]
