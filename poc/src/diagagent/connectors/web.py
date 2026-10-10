"""Recherche web et lecture de pages derrière mcp-web : problèmes connus, documentation, réglages.

WEB_SEARCH choisit le moteur : « duckduckgo » (sans clé) ou l'URL d'une instance SearXNG (API JSON).
Deux garde-fous : une requête ne contient ni adresse IP ni nom interne (SSH_HOSTS, WEB_SEARCH_DENY),
et une page n'est lue que sur une adresse publique, redirections comprises (pas d'accès au réseau local).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

# Navigateur courant : plusieurs forums (Cloudflare) refusent un client inconnu.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0 Safari/537.36")
TIMEOUT_S = 15
MAX_BYTES = 2_000_000
MAX_PAGE_CHARS = 8000
IPV4 = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
DDG_URL = "https://html.duckduckgo.com/html/"


def denied_words() -> set[str]:
    names = os.environ.get("SSH_HOSTS", "").split(",") + os.environ.get("WEB_SEARCH_DENY", "").split(",")
    return {n.partition("=")[0].strip().lower() for n in names if n.strip()}


def check_query(query: str) -> str:
    query = " ".join(query.split())
    if not query:
        raise ValueError("Requête vide")
    if IPV4.search(query):
        raise ValueError("La requête contient une adresse IP : cherche le logiciel et le symptôme, pas la machine")
    words = set(re.findall(r"[\w.-]+", query.lower()))
    leaked = sorted(words & denied_words())
    if leaked:
        raise ValueError(f"La requête contient un nom interne ({', '.join(leaked)}) : cherche le logiciel, "
                         "sa version et le symptôme, sans nom de machine")
    return query


def _open(req: urllib.request.Request, opener: urllib.request.OpenerDirector | None = None) -> tuple[str, str]:
    try:
        with (opener or urllib.request.build_opener()).open(req, timeout=TIMEOUT_S) as resp:
            ctype = resp.headers.get("Content-Type", "")
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read(MAX_BYTES).decode(charset, "replace"), ctype
    except urllib.error.HTTPError as e:
        raise ValueError(f"{req.full_url} a répondu {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ValueError(f"{req.full_url} injoignable : {getattr(e, 'reason', e)}") from e


def search(query: str, max_results: int = 8) -> list[dict[str, str]]:
    query = check_query(query)
    engine = os.environ.get("WEB_SEARCH", "duckduckgo").strip()
    if engine.startswith(("http://", "https://")):
        url = engine.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
        body, _ = _open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}))
        results = [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                   for r in json.loads(body).get("results", [])]
    elif engine == "duckduckgo":
        url = os.environ.get("DIAGAGENT_DDG_URL", DDG_URL)
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"q": query}).encode(),
                                     headers={"User-Agent": USER_AGENT})
        body, _ = _open(req)
        results = DuckDuckGoResults.parse(body)
    else:
        raise ValueError(f"WEB_SEARCH inconnu : {engine} (duckduckgo ou URL SearXNG)")
    return [r for r in results if r["url"].startswith(("http://", "https://"))][:max(1, min(max_results, 10))]


class DuckDuckGoResults(HTMLParser):
    """Page de résultats html.duckduckgo.com : liens result__a, extraits result__snippet, sans annonces."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._field: str | None = None

    @classmethod
    def parse(cls, body: str) -> list[dict[str, str]]:
        p = cls()
        p.feed(body)
        return [{k: " ".join(v.split()) for k, v in r.items()} for r in p.results
                if "duckduckgo.com" not in urllib.parse.urlparse(r["url"]).netloc]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            href = a.get("href") or ""
            target = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
            self.results.append({"title": "", "url": target, "snippet": ""})
            self._field = "title"
        elif tag in ("a", "div") and "result__snippet" in classes and self.results:
            self._field = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "div"):
            self._field = None

    def handle_data(self, data: str) -> None:
        if self._field and self.results:
            self.results[-1][self._field] += data  # espaces normalisés dans parse()


def check_public_url(url: str) -> None:
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"URL refusée : {url} (http ou https seulement)")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except socket.gaierror as e:
        raise ValueError(f"{parts.hostname} ne se résout pas") from e
    for address in addresses:
        if not ipaddress.ip_address(address.split("%")[0]).is_global:
            raise ValueError(f"URL refusée : {parts.hostname} est une adresse privée ou locale ({address})")


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str) -> dict[str, Any]:
    check_public_url(url)
    opener = urllib.request.build_opener(_PublicRedirects())
    body, ctype = _open(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), opener)
    if "html" in ctype or not ctype:
        title, text = page_text(body)
    elif ctype.startswith("text/"):
        title, text = "", " ".join(body.split())
    else:
        raise ValueError(f"Contenu non textuel : {ctype}")
    return {"url": url, "title": title, "text": text[:MAX_PAGE_CHARS], "truncated": len(text) > MAX_PAGE_CHARS}


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "form", "aside"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "pre", "tr", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        elif not self._skip:
            self.parts.append(data)


def page_text(body: str) -> tuple[str, str]:
    """Titre et texte lisible d'une page HTML (sans scripts, menus ni pieds de page). Les lignes de moins
    de quatre mots (liens de menu, pseudos, compteurs) sont écartées, sauf les dates des messages."""
    p = _Text()
    p.feed(body)
    lines = (" ".join(line.split()) for line in "".join(p.parts).splitlines())
    return p.title, "\n".join(line for line in lines if len(line.split()) >= 4 or DATE.search(line))
