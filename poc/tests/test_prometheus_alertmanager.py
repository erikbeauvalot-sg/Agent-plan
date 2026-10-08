"""Connecteurs Prometheus et Alertmanager contre un faux serveur HTTP, via les serveurs MCP réels."""

import asyncio
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from conftest import POC
from diagagent import catalog
from diagagent.tools import ToolHub

NOW = 1_791_352_800  # 2026-10-07T06:00:00Z
NODE = {"__name__": "up", "instance": "nas.maison:9100", "job": "node"}
SELF = {"__name__": "up", "instance": "localhost:9090", "job": "prometheus"}


class FakeMonitoring(BaseHTTPRequestHandler):
    queries: list[str] = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path.startswith("/api/v1/"):
            FakeMonitoring.queries.append(q["query"])
            body = {"status": "success", "data": self.prometheus(url.path, q)}
        elif url.path == "/api/v2/alerts":
            body = [{"labels": {"alertname": "DiskAlmostFull", "instance": "nas.maison:9100",
                                "severity": "warning"},
                     "annotations": {"summary": "Disque /data à 91 %"},
                     "startsAt": "2026-10-07T05:10:00Z", "status": {"state": "active"}}]
        elif url.path == "/api/v2/silences":
            body = [{"id": "s1", "status": {"state": "active"}, "matchers": [], "comment": "maintenance",
                     "startsAt": "2026-10-07T00:00:00Z", "endsAt": "2026-10-08T00:00:00Z"},
                    {"id": "s0", "status": {"state": "expired"}}]
        else:
            self.send_response(404)
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def prometheus(self, path, q):
        query = q["query"]
        if path == "/api/v1/query":
            if query == "up":
                return {"resultType": "vector", "result": [{"metric": NODE, "value": [NOW, "1"]},
                                                           {"metric": SELF, "value": [NOW, "1"]}]}
            known = "nas\\\\.maison" in query and "node_network" not in query
            return {"resultType": "vector", "result": [{"metric": {}, "value": [NOW, "1"]}] if known else []}
        start, end, step = float(q["start"]), float(q["end"]), float(q["step"])
        if query.startswith("ALERTS"):
            values = [[t, "1"] for t in range(int(end - 3000), int(end), int(step))]
            return {"resultType": "matrix", "result": [
                {"metric": {"alertname": "DiskAlmostFull", "instance": "nas.maison:9100",
                            "severity": "warning", "alertstate": "firing"}, "values": values}]}
        values, t = [], start
        while t <= end:
            values.append([t, "20" if t < end - 4 * 3600 else "85"])  # rupture 4 h avant la fin
            t += step
        return {"resultType": "matrix", "result": [{"metric": {"instance": "nas.maison:9100"}, "values": values}]}


@pytest.fixture
def home_monitoring(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeMonitoring)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("PROMETHEUS_URL", url)
    monkeypatch.setenv("ALERTMANAGER_URL", url)
    monkeypatch.setenv("DIAGAGENT_DEMO", "0")
    catalog.load_catalog.cache_clear()
    FakeMonitoring.queries = []
    yield
    server.shutdown()


def _run(fn):
    servers = yaml.safe_load((POC / "config" / "poc.yaml").read_text())["mcp_servers"]

    async def go():
        async with ToolHub(servers) as hub:
            return await fn(hub)
    return asyncio.run(go())


def _call(name, args):
    async def fn(hub):
        res = await hub.call(name, args)
        assert not res.is_error, res.content
        return json.loads(res.content)
    return _run(fn)


def test_home_mode_exposes_only_real_sources(home_monitoring):
    assert set(catalog.load_catalog()) == {"metrics-prometheus", "alerts-alertmanager"}
    names = _run(lambda hub: asyncio.sleep(0, result=set(hub.specs)))
    assert {"list_alerts", "alert_history", "promql", "list_hosts"} <= names
    assert "search" not in names and "get_ci" not in names


def test_hosts_and_metrics_from_prometheus(home_monitoring):
    hosts = _call("list_hosts", {})["metrics-prometheus"]
    assert {"host": "nas.maison", "job": "node", "up": True} in hosts
    metrics = [m["name"] for m in _call("list_metrics", {"host": "nas.maison"})["metrics"]]
    assert "cpu.usage" in metrics and "net.errors_s" not in metrics


def test_query_metric_builds_promql_and_detects_break(home_monitoring):
    data = _call("query_metric", {"host": "nas.maison", "metric": "cpu.usage"})
    assert data["source"] == "metrics-prometheus"
    assert data["summary"]["max"] == 85 and data["breaks"]
    sent = FakeMonitoring.queries[-1]
    assert 'node_cpu_seconds_total{mode="idle",instance=~"nas\\\\.maison(:[0-9]+)?"}' in sent


def test_alerts_silences_and_history(home_monitoring):
    alerts = _call("list_alerts", {"host": "nas.maison"})
    assert alerts["alerts"][0]["alertname"] == "DiskAlmostFull"
    assert [s["id"] for s in _call("list_silences", {})["silences"]] == ["s1"]
    history = _call("alert_history", {"host": "nas.maison"})
    assert len(history["alerts"][0]["intervals"]) == 1


def test_resolve_entity_finds_monitored_host_without_cmdb(home_monitoring):
    data = _call("resolve_entity", {"name": "nas"})
    assert data["found"] and data["cis"] == []
    assert {"source": "metrics-prometheus", "host": "nas.maison"} in data["monitored_hosts"]
