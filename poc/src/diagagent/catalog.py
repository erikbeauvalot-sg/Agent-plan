"""Catalogue déclaratif des sources (dossier catalog/) et accès aux données du POC."""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAX_HITS = 200
MAX_FIELD_CHARS = 500


def home() -> Path:
    """Racine du POC (contient catalog/, demo_data/, config/, runs/)."""
    return Path(os.environ.get("DIAGAGENT_HOME", Path.cwd())).resolve()


def now() -> datetime:
    """Heure de référence ; DIAGAGENT_NOW la fige pour rejouer le scénario de démonstration."""
    fixed = os.environ.get("DIAGAGENT_NOW")
    return parse_time(fixed) if fixed else datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def time_window(time_from: str | None, time_to: str | None) -> tuple[datetime, datetime]:
    """Période obligatoire : par défaut les 24 heures précédant l'heure de référence."""
    end = parse_time(time_to) if time_to else now()
    start = parse_time(time_from) if time_from else end - timedelta(hours=24)
    if start >= end:
        raise ValueError(f"Période vide : {time_from} >= {time_to}")
    return start, end


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, dict[str, Any]]:
    sources = {}
    for path in sorted((home() / "catalog" / "sources").glob("*.yaml")):
        card = yaml.safe_load(path.read_text(encoding="utf-8"))
        sources[card["id"]] = card
    return sources


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict[str, Any]:
    path = home() / "catalog" / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def get_source(source_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    if source_id not in catalog:
        raise KeyError(f"Source inconnue : {source_id}. Sources disponibles : {', '.join(catalog)}")
    return catalog[source_id]


def catalog_summary() -> str:
    """Résumé court (id + description) injecté dans le prompt système de l'agent."""
    lines = []
    for card in load_catalog().values():
        desc = " ".join(card["description"].split())
        lines.append(f"- {card['id']} ({card.get('kind', 'documents')}) : {desc}")
    return "\n".join(lines)


@lru_cache(maxsize=None)
def _load_rows(path: str) -> tuple[dict[str, Any], ...]:
    full = home() / path
    text = full.read_text(encoding="utf-8")
    if full.suffix == ".jsonl":
        return tuple(json.loads(line) for line in text.splitlines() if line.strip())
    return tuple(json.loads(text))


def rows(source_id: str) -> tuple[dict[str, Any], ...]:
    backend = get_source(source_id)["backend"]
    if backend["type"] != "file":
        raise NotImplementedError(f"Backend {backend['type']} pas encore disponible dans le POC")
    return _load_rows(backend["path"])


def field_value(doc: dict[str, Any], dotted: str) -> Any:
    value: Any = doc
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _clean(doc: dict[str, Any], exclude: list[str]) -> dict[str, Any]:
    """Masquage côté serveur et troncature des champs longs."""
    out = {}
    for k, v in doc.items():
        if k in exclude:
            continue
        if isinstance(v, str) and len(v) > MAX_FIELD_CHARS:
            v = v[:MAX_FIELD_CHARS] + "…"
        out[k] = v
    return out


def _matches(doc: dict[str, Any], filters: dict[str, Any] | None, text: str | None) -> bool:
    for key, expected in (filters or {}).items():
        actual = field_value(doc, key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif isinstance(actual, list):
            if expected not in actual:
                return False
        elif str(actual).lower() != str(expected).lower():
            return False
    if text and text.lower() not in json.dumps(doc, ensure_ascii=False).lower():
        return False
    return True


def search(source_id: str, filters: dict[str, Any] | None = None, text: str | None = None,
           time_from: str | None = None, time_to: str | None = None, size: int = 50) -> dict[str, Any]:
    card = get_source(source_id)
    limits = card.get("limits", {})
    size = max(1, min(size, limits.get("max_hits", DEFAULT_MAX_HITS)))
    time_field = card.get("time_field")
    hits = [d for d in rows(source_id) if _matches(d, filters, text)]
    window = None
    if time_field:
        start, end = time_window(time_from, time_to)
        window = [start.isoformat(), end.isoformat()]
        hits = [d for d in hits
                if (t := field_value(d, time_field)) and start <= parse_time(t) < end]
        hits.sort(key=lambda d: field_value(d, time_field), reverse=True)
    exclude = limits.get("exclude_fields", [])
    return {
        "source": source_id,
        "time_range": window,
        "total": len(hits),
        "returned": min(size, len(hits)),
        "truncated": len(hits) > size,
        "hits": [_clean(d, exclude) for d in hits[:size]],
    }


def aggregate(source_id: str, field: str, filters: dict[str, Any] | None = None,
              time_from: str | None = None, time_to: str | None = None, top: int = 10) -> dict[str, Any]:
    card = get_source(source_id)
    time_field = card.get("time_field")
    docs = [d for d in rows(source_id) if _matches(d, filters, None)]
    window = None
    if time_field:
        start, end = time_window(time_from, time_to)
        window = [start.isoformat(), end.isoformat()]
        docs = [d for d in docs if (t := field_value(d, time_field)) and start <= parse_time(t) < end]
    counts = Counter(str(field_value(d, field)) for d in docs)
    buckets = [{"value": v, "count": c} for v, c in counts.most_common(top)]
    if time_field:
        for b in buckets:
            times = sorted(field_value(d, time_field) for d in docs if str(field_value(d, field)) == b["value"])
            b["first_seen"], b["last_seen"] = times[0], times[-1]
    return {"source": source_id, "field": field, "time_range": window, "total": len(docs), "buckets": buckets}
