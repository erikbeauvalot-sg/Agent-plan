"""Catalogue déclaratif des sources (dossier catalog/) et accès aux données du POC."""

from __future__ import annotations

import json
import os
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import yaml

DEFAULT_MAX_HITS = 200
MAX_FIELD_CHARS = 500


def home() -> Path:
    """Racine du POC (contient catalog/, demo_data/, config/, runs/)."""
    return Path(os.environ.get("DIAGAGENT_HOME", Path.cwd())).resolve()


def runs_dir(poc_cfg: dict[str, Any]) -> Path:
    """Dossier des traces : DIAGAGENT_RUNS_DIR, sinon runs_dir de config/poc.yaml relatif à la racine."""
    return Path(os.environ.get("DIAGAGENT_RUNS_DIR") or home() / poc_cfg.get("runs_dir", "runs"))


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


SOURCE_SETS = ("demo", "maison")
# Jeux de sources d'une investigation, choisis par requête (interface web, ask) ; sinon DIAGAGENT_SOURCES.
_sources: ContextVar[frozenset[str] | None] = ContextVar("diagagent_sources", default=None)


def parse_sources(value: str | list[str] | None) -> frozenset[str]:
    """« demo », « maison », « demo,maison » (ou une liste) ; un nom inconnu lève ValueError."""
    names = value.split(",") if isinstance(value, str) else list(value or [])
    found = frozenset(n.strip() for n in names if n.strip())
    unknown = found - set(SOURCE_SETS)
    if unknown or not found:
        raise ValueError(f"Jeu de sources inconnu : {value} (possibles : demo, maison, demo,maison)")
    return found


def active_sources() -> frozenset[str]:
    """Jeux de sources actifs : celui de l'investigation en cours, sinon DIAGAGENT_SOURCES, sinon les deux.
    DIAGAGENT_DEMO=0 (ancien réglage) vaut « maison »."""
    chosen = _sources.get()
    if chosen is not None:
        return chosen
    if os.environ.get("DIAGAGENT_SOURCES"):
        return parse_sources(os.environ["DIAGAGENT_SOURCES"])
    return frozenset({"maison"}) if os.environ.get("DIAGAGENT_DEMO") == "0" else frozenset(SOURCE_SETS)


@contextmanager
def using_sources(value: str | list[str] | None) -> Iterator[frozenset[str]]:
    """Fixe les jeux de sources pour une investigation (tâche asyncio comprise) ; None garde le réglage."""
    token = _sources.set(parse_sources(value) if value else active_sources())
    try:
        yield _sources.get()  # type: ignore[misc]
    finally:
        _sources.reset(token)


def source_set(entry: dict[str, Any]) -> str | None:
    """Jeu d'une fiche ou d'un serveur : « demo » (demo: true), « maison » (source réelle, requires_env),
    None pour l'infrastructure commune (catalogue, routage des métriques)."""
    if entry.get("demo"):
        return "demo"
    return "maison" if entry.get("requires_env") else None


def enabled(entry: dict[str, Any]) -> bool:
    """Une fiche ou un serveur est actif si son jeu de sources est actif et si ses variables
    d'environnement (`requires_env`) sont définies."""
    kind = source_set(entry)
    if kind and kind not in active_sources():
        return False
    return all(os.environ.get(var) for var in entry.get("requires_env", []))


def configured_sources() -> list[str]:
    """Jeux de sources utilisables : « demo » toujours, « maison » si une source réelle est configurée."""
    cards = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in (home() / "catalog" / "sources").glob("*.yaml")]
    real = any(source_set(c) == "maison" and all(os.environ.get(v) for v in c["requires_env"]) for c in cards)
    return ["demo", "maison"] if real else ["demo"]


def load_catalog() -> dict[str, dict[str, Any]]:
    return _load_catalog(active_sources())


@lru_cache(maxsize=8)
def _load_catalog(active: frozenset[str]) -> dict[str, dict[str, Any]]:
    """active ne sert qu'à la clé du cache : enabled() relit les jeux actifs."""
    sources = {}
    for path in sorted((home() / "catalog" / "sources").glob("*.yaml")):
        card = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not enabled(card):
            continue
        backend = card.get("backend", {})
        if isinstance(backend.get("url"), str):
            backend["url"] = api_base_url(os.path.expandvars(backend["url"]))
        sources[card["id"]] = card
    return sources


load_catalog.cache_clear = _load_catalog.cache_clear  # type: ignore[attr-defined]

UI_PAGES = ("/query", "/graph", "/alerts", "/targets", "/status")


def api_base_url(url: str) -> str:
    """URL de base de l'API à partir d'une URL copiée depuis l'interface web
    (http://h:9090/query ou http://h:9093/#/alerts -> http://h:9090, http://h:9093)."""
    url = url.split("#", 1)[0].rstrip("/")
    for page in UI_PAGES:
        if url.endswith(page):
            url = url[: -len(page)]
    return url.rstrip("/")


def sources_of_kind(kind: str) -> list[dict[str, Any]]:
    return [c for c in load_catalog().values() if c.get("kind") == kind]


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


def _field_paths(doc: dict[str, Any], prefix: str = "") -> set[str]:
    paths = set()
    for k, v in doc.items():
        paths.add(prefix + k)
        if isinstance(v, dict):
            paths |= _field_paths(v, f"{prefix}{k}.")
    return paths


def _check_filters(source_id: str, filters: dict[str, Any] | None) -> None:
    """Refuse aussi une valeur de filtre qui n'est ni une valeur simple ni une liste : un opérateur
    ({"$nin": [...]}, {"gte": ...}) serait comparé comme du texte et ne trouverait rien, sans erreur."""
    _check_fields(source_id, list(filters or {}))
    for field in filters or {}:
        if any(isinstance(field_value(d, field), dict) for d in rows(source_id)):
            # {"ci": "CI0012400"} comparait l'objet {"hostname": ..., "id": ...} à un texte : 0 résultat, lu
            # « aucun changement sur db-pay-02 ».
            subs = sorted({f"{field}.{k}" for d in rows(source_id)
                           if isinstance(v := field_value(d, field), dict) for k in v})
            raise ValueError(f"Le champ {field} est un objet : filtre sur un de ses sous-champs ({', '.join(subs)}).")
    for field, value in (filters or {}).items():
        values = value if isinstance(value, list) else [value]
        if all(isinstance(v, (str, int, float, bool)) for v in values):
            continue
        known = sorted({str(v) for d in rows(source_id) if (v := field_value(d, field)) is not None
                        and not isinstance(v, (dict, list))})
        hint = f" Valeurs présentes pour {field} : {', '.join(known)}." if 0 < len(known) <= 20 else ""
        raise ValueError(f"Filtre {field} non pris en charge : {json.dumps(value, ensure_ascii=False)}. "
                         f"Un filtre est une égalité exacte (valeur simple) ou une liste de valeurs acceptées ; "
                         f"pas d'opérateur. Pour exclure des valeurs, liste celles que tu acceptes.{hint}")


def _unknown_values(source_id: str, filters: dict[str, Any] | None) -> dict[str, dict[str, list[str]]]:
    """Valeurs de filtre absentes de la source, pour les champs à peu de valeurs (états, priorités…) :
    {"state": {"absentes": [...], "présentes": [...]}}. Un état deviné (« Ouvert ») ne trouvait rien, sans erreur."""
    out = {}
    for field, value in (filters or {}).items():
        present = {str(v) for d in rows(source_id) if (v := field_value(d, field)) is not None
                   and not isinstance(v, (dict, list))}
        if not present or len(present) > 20:
            continue
        wanted = value if isinstance(value, list) else [value]
        lowered = {p.lower() for p in present}
        missing = [str(w) for w in wanted if str(w).lower() not in lowered]
        if missing:
            out[field] = {"absentes": missing, "présentes": sorted(present)}
    return out


def _check_fields(source_id: str, fields: list[str]) -> None:
    """Refuse un champ absent de la source : un filtre sur un champ inconnu renverrait 0 résultat
    sans erreur, et le modèle conclurait à tort qu'il n'y a rien (ex. affected_ci.hostname sur changes)."""
    known = set().union(*(_field_paths(d) for d in rows(source_id)))
    known -= set(get_source(source_id).get("limits", {}).get("exclude_fields", []))
    unknown = [f for f in fields if f not in known]
    if unknown:
        raise ValueError(f"Champ(s) inconnu(s) dans la source {source_id} : {', '.join(unknown)}. "
                         f"Champs disponibles : {', '.join(sorted(known))}")


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


def _matches(doc: dict[str, Any], filters: dict[str, Any] | None, text: str | None,
             exclude: list[str] | None = None) -> bool:
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
    # La recherche texte ne porte pas sur les champs masqués : sinon un résultat non vide confirmerait
    # une valeur cachée (adresse de l'appelant, par exemple) sans jamais l'afficher.
    visible = {k: v for k, v in doc.items() if k not in (exclude or [])}
    if text and text.lower() not in json.dumps(visible, ensure_ascii=False).lower():
        return False
    return True


def search(source_id: str, filters: dict[str, Any] | None = None, text: str | None = None,
           time_from: str | None = None, time_to: str | None = None, size: int = 50) -> dict[str, Any]:
    card = get_source(source_id)
    limits = card.get("limits", {})
    size = max(1, min(size, limits.get("max_hits", DEFAULT_MAX_HITS)))
    time_field = card.get("time_field")
    _check_filters(source_id, filters)
    exclude = limits.get("exclude_fields", [])
    matching = [d for d in rows(source_id) if _matches(d, filters, text, exclude)]
    hits, window = matching, None
    if time_field:
        start, end = time_window(time_from, time_to)
        window = [start.isoformat(), end.isoformat()]
        hits = [d for d in matching
                if (t := field_value(d, time_field)) and start <= parse_time(t) < end]
        hits.sort(key=lambda d: field_value(d, time_field), reverse=True)
    result = {
        "source": source_id,
        "time_range": window,
        "total": len(hits),
        "returned": min(size, len(hits)),
        "truncated": len(hits) > size,
        "hits": [_clean(d, exclude) for d in hits[:size]],
    }
    unknown = _unknown_values(source_id, filters)
    if unknown:
        result["unknown_values"] = unknown
        result["note"] = " ".join(f"Valeur(s) {', '.join(v['absentes'])} absente(s) du champ {f}, qui contient : "
                                  f"{', '.join(v['présentes'])}." for f, v in unknown.items())
    outside = sorted(t for d in matching if (t := field_value(d, time_field))) if time_field and not hits else []
    if outside:
        # Sans cette note, « 0 dans la période par défaut » se lisait « n'existe pas » (un ticket cherché
        # par son numéro, ouvert plus de 24 h avant l'heure de référence).
        result["outside_time_range"] = {"total": len(outside), "first": outside[0], "last": outside[-1]}
        note = (f"Aucun document dans la période, mais {len(outside)} hors période ({time_field} du "
                f"{outside[0]} au {outside[-1]}) : élargis time_from / time_to pour les voir.")
        result["note"] = f"{result['note']} {note}" if result.get("note") else note
    return result


def aggregate(source_id: str, field: str, filters: dict[str, Any] | None = None,
              time_from: str | None = None, time_to: str | None = None, top: int = 10) -> dict[str, Any]:
    card = get_source(source_id)
    time_field = card.get("time_field")
    _check_fields(source_id, [field])
    _check_filters(source_id, filters)
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
