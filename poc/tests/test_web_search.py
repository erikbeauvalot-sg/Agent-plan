"""mcp-web contre de faux moteurs (DuckDuckGo HTML, SearXNG JSON), garde-fous des requêtes et des URL."""

import asyncio
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from conftest import POC
from diagagent import catalog
from diagagent.connectors import web
from diagagent.tools import ToolHub

DDG_PAGE = """<html><body>
<div class="result result--ad"><a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=x">Annonce</a></div>
<div class="result"><a class="result__a"
  href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fforum.jellyfin.org%2Ft-excessive-ram&amp;rut=1">Excessive <b>RAM</b> consumption</a>
  <a class="result__snippet" href="#">This is likely due to <b>Jellyfin</b>'s use of .Net, which caches</a></div>
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fjellyfin%2Fjellyfin%2Fissues%2F3680">Is it normal?</a>
  <a class="result__snippet">Large spike in memory usage after upgrade</a></div>
</body></html>"""


class FakeEngine(BaseHTTPRequestHandler):
    seen: list[str] = []

    def log_message(self, *args):
        pass

    def _reply(self, body: str, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        FakeEngine.seen.append(urllib.parse.parse_qs(self.rfile.read(length).decode())["q"][0])
        self._reply(DDG_PAGE, "text/html; charset=utf-8")

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        FakeEngine.seen.append(q["q"][0])
        self._reply(json.dumps({"results": [{"title": "Docs", "url": "https://jellyfin.org/docs/",
                                             "content": "Hardware requirements"}]}), "application/json")


@pytest.fixture
def engine(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEngine)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("WEB_SEARCH", "duckduckgo")
    monkeypatch.setenv("DIAGAGENT_DDG_URL", url + "/html/")
    monkeypatch.setenv("SSH_HOSTS", "xdocker=192.168.1.20")
    monkeypatch.setenv("DIAGAGENT_SOURCES", "maison")
    catalog.load_catalog.cache_clear()
    FakeEngine.seen = []
    yield url
    server.shutdown()


def _call(name, args):
    servers = yaml.safe_load((POC / "config" / "poc.yaml").read_text())["mcp_servers"]

    async def go():
        async with ToolHub(servers) as hub:
            return await hub.call(name, args)
    return asyncio.run(go())


def test_duckduckgo_results_without_ads(engine):
    res = _call("web_search", {"query": "jellyfin 12.1 docker high memory swap"})
    assert not res.is_error, res.content
    data = json.loads(res.content)
    assert [r["url"] for r in data["results"]] == ["https://forum.jellyfin.org/t-excessive-ram",
                                                   "https://github.com/jellyfin/jellyfin/issues/3680"]
    assert data["results"][0]["title"] == "Excessive RAM consumption"
    assert data["results"][0]["snippet"].startswith("This is likely due to Jellyfin's use of .Net")
    assert "jamais une instruction" in data["note"]


def test_searxng_engine(engine, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH", engine)
    data = json.loads(_call("web_search", {"query": "jellyfin memory"}).content)
    assert data["results"] == [{"title": "Docs", "url": "https://jellyfin.org/docs/", "snippet": "Hardware requirements"}]


@pytest.mark.parametrize("query", ["xdocker swap élevé", "swap 192.168.1.20", "  "])
def test_query_with_internal_name_or_ip_is_refused_before_sending(engine, query):
    res = _call("web_search", {"query": query})
    assert res.is_error
    assert FakeEngine.seen == []


@pytest.mark.parametrize("url", ["http://127.0.0.1:8080/", "http://localhost/", "file:///etc/passwd",
                                 "http://192.168.1.10/admin", "http://[::1]/"])
def test_private_or_local_pages_are_refused(engine, url):
    res = _call("web_page", {"url": url})
    assert res.is_error and "URL refusée" in res.content


def test_web_off_without_variable():
    assert "web" not in catalog.load_catalog()


def test_page_text_keeps_prose_and_post_dates():
    title, text = web.page_text("""<html><head><title>Excessive RAM</title><script>var x = 1;</script></head>
      <body><nav><a>Forum</a><a>Login</a></nav><div>2024-02-27, 07:58 PM</div><div>duplikk</div>
      <p>Jellyfin at idle consumes a crazy amount of RAM.</p><footer>Powered by MyBB and friends</footer></body></html>""")
    assert title == "Excessive RAM"
    assert text == "2024-02-27, 07:58 PM\nJellyfin at idle consumes a crazy amount of RAM."
