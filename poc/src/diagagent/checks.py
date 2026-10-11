"""Contrôles des faits et des actions dans le code : ce que le prompt demande à l'agent, vérifié sur les
mesures de l'investigation (appels d'outils tracés) et sur Prometheus.

- Une limite mémoire proposée n'est jamais sous le pic mesuré du conteneur, marge comprise.
- Une règle d'alerte proposée est acceptée par Prometheus, ses métriques ont des séries, et elle ne
  recopie pas une règle existante.
- La réponse finale n'affirme pas qu'un conteneur dépasse une taille que ses mesures n'atteignent pas.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

import yaml

UNITS_MB = {"k": 1 / 1024, "m": 1.0, "g": 1024.0, "t": 1024.0 * 1024}
NUM = r"(\d+(?:[.,]\d+)?|\bune?)"
UNIT = r"(ki?b?|mi?b?|gi?b?|ti?b?|ko|mo|go|to)\b"

# --memory=1g (pas --memory-swap), mem_limit: 1g, memory: 1G (compose), « limite … 1 Go ».
LIMIT_PATTERNS = [
    re.compile(r"--memory(?![-\w])[= ]+[\"']?" + NUM + r"\s*" + UNIT, re.I),
    re.compile(r"\bmem_limit\s*[:=]\s*[\"']?" + NUM + r"\s*" + UNIT, re.I),
    re.compile(r"(?<![-\w])memory\s*:\s*[\"']?" + NUM + r"\s*" + UNIT, re.I),
    re.compile(r"\blimit\w*\b[^.\n`]{0,60}?" + NUM + r"\s*" + UNIT, re.I),
]
CLAIM = re.compile(r"(dépass\w*|au[- ]delà d[eu']|plus d[e']|supérieur\w* à|exceed\w*|above|over|>)\s*"
                   r"(?:souvent\s+|parfois\s+|régulièrement\s+|largement\s+|~\s*)?" + NUM + r"\s*" + UNIT, re.I)
PROMQL_KEYWORDS = {"by", "without", "on", "ignoring", "group_left", "group_right", "bool", "and", "or",
                   "unless", "offset", "inf", "nan"}


class Prometheus(Protocol):
    def instant(self, promql: str) -> list[dict[str, Any]]: ...

    def get(self, path: str, params: dict[str, Any]) -> Any: ...


def to_mb(number: str, unit: str) -> float:
    value = 1.0 if number.lower() in ("un", "une") else float(number.replace(",", "."))
    return value * UNITS_MB[unit.lower()[0]]


def _fmt(mb: float) -> str:
    return f"{mb:.0f} Mo"


# Mesures

def measured_peaks(run_dir: Path) -> dict[str, dict[str, Any]]:
    """Pics mémoire mesurés par conteneur dans l'investigation, chacun avec sa preuve (query_ref) :
    - mb, ref : le plus haut de tout ce qui a été mesuré, cache de fichiers compris (peak_mb et mem_mb de
      container_memory sont lus dans le cgroup) ; borne haute pour juger une taille citée ;
    - working_set_mb, working_set_ref : maximum de container_metrics (container.mem_mb, mémoire de
      travail de cAdvisor), seule mesure valable pour une limite : le noyau libère le cache avant de
      tuer le conteneur."""
    peaks: dict[str, dict[str, Any]] = {}

    def keep(name: Any, mb: Any, ref: str, working_set: bool = False) -> None:
        if not isinstance(name, str) or not isinstance(mb, (int, float)):
            return
        peak = peaks.setdefault(name, {"mb": -1.0})
        if mb > peak["mb"]:
            peak.update(mb=float(mb), ref=ref)
        if working_set and mb > peak.get("working_set_mb", -1):
            peak.update(working_set_mb=float(mb), working_set_ref=ref)

    for path in sorted(run_dir.glob("**/calls/*.json")):
        try:
            call = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out, ref = call.get("output"), str(path.relative_to(run_dir))
        if not isinstance(out, dict):
            continue
        if call.get("tool") == "container_memory":
            for c in out.get("containers", []):
                keep(c.get("container"), max((v for v in (c.get("peak_mb"), c.get("mem_mb"))
                                              if isinstance(v, (int, float))), default=None), ref)
        elif call.get("tool") == "container_metrics" and out.get("metric", "container.mem_mb") == "container.mem_mb":
            for c in out.get("containers", []):
                keep(c.get("container"), (c.get("summary") or {}).get("max"), ref, working_set=True)
    return peaks


def _mentions(text: str, names: list[str]) -> list[tuple[int, str]]:
    found = []
    for name in names:
        found += [(m.start(), name) for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I)]
    return sorted(found)


# Limite mémoire

def memory_limits(text: str) -> list[tuple[int, float]]:
    """Limites mémoire écrites dans un texte : (position, Mo), une par endroit."""
    seen: dict[int, float] = {}
    for pattern in LIMIT_PATTERNS:
        for m in pattern.finditer(text):
            pos = m.start(1)
            if not any(abs(pos - p) < 3 for p in seen):
                seen[pos] = to_mb(m.group(1), m.group(2))
    return sorted(seen.items())


def check_memory_limit(action: dict[str, Any], peaks: dict[str, dict[str, Any]], margin: float) -> str | None:
    """Erreur si une limite mémoire de l'action est sous le pic de mémoire de travail du conteneur visé,
    marge comprise, ou si ce pic n'a pas été mesuré (peak_mb compte le cache de fichiers : un conteneur
    qui télécharge affiche des Go que le noyau libère sans rien tuer). Le conteneur visé est celui
    nommé sur la même ligne que la limite, sinon le dernier nommé avant."""
    text = "\n".join(str(action.get(k, "")) for k in ("title", "target", "procedure"))
    limits = memory_limits(text)
    if not limits:
        return None
    unmeasured = ("Cette action fixe une limite mémoire sans pic de mémoire de travail mesuré pour {}. "
                  "peak_mb et mem_mb de container_memory comptent le cache de fichiers, que le noyau libère "
                  "avant de tuer un conteneur : mesure le pic avec container_metrics (container.mem_mb, sur "
                  "7 jours), puis propose une limite au-dessus de ce pic, marge de "
                  f"{round((margin - 1) * 100)} % comprise.")
    mentions = _mentions(text, list(peaks))
    if not mentions:
        return unmeasured.format("le conteneur visé") if not peaks else None
    errors, missing = [], []
    for pos, limit in limits:
        line_start, line_end = text.rfind("\n", 0, pos) + 1, (text.find("\n", pos) + 1 or len(text) + 1) - 1
        before = [n for p, n in mentions if p < pos]
        targets = {n for p, n in mentions if line_start <= p < line_end} \
            or set(before[-1:]) or {n for _, n in mentions}
        for name in sorted(targets):
            peak = peaks[name]
            if "working_set_mb" not in peak:
                missing += [name] if name not in missing else []
            elif limit < peak["working_set_mb"] * margin and not any(
                    e.startswith(f"{name} : limite {_fmt(limit)},") for e in errors):
                errors.append(f"{name} : limite {_fmt(limit)}, pic de mémoire de travail "
                              f"{_fmt(peak['working_set_mb'])} [{peak['working_set_ref']}], "
                              f"minimum {_fmt(peak['working_set_mb'] * margin)}")
    if errors:
        return ("Limite mémoire sous le pic mesuré (marge de "
                f"{round((margin - 1) * 100)} % comprise) : {' ; '.join(errors)}. Le conteneur serait tué "
                "(OOM) à son prochain pic : propose une limite au-dessus du minimum, ou pas de limite.")
    return unmeasured.format(", ".join(missing)) if missing else None


# Règle d'alerte

def proposed_rules(procedure: str) -> list[dict[str, Any]]:
    """Règles d'alerte d'une procédure : blocs YAML (alert, expr, for), sinon lignes « expr: »."""
    blocks = re.findall(r"```[\w-]*\n(.*?)```", procedure, re.S) or [procedure]
    rules: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("expr"), (str, int, float)):
                rules.append({"alert": node.get("alert"), "expr": str(node["expr"]).strip()})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for block in blocks:
        try:
            walk(yaml.safe_load(block))
        except yaml.YAMLError:
            continue
    if not rules:
        alert = re.search(r"\balert\s*:\s*[\"']?([\w:]+)", procedure)
        rules += [{"alert": alert.group(1) if alert else None, "expr": m.group(1).strip().strip("`\"'")}
                  for m in re.finditer(r"\bexpr\s*:\s*(.+)", procedure)]
    return [r for r in rules if r["expr"]]


def proposed_rule(procedure: str) -> dict[str, Any] | None:
    """Règle proposée : la dernière de la procédure. Les modèles citent souvent la règle actuelle
    (« Current: expr: … ») avant la nouvelle ; elle ne doit pas être contrôlée comme une proposition."""
    rules = proposed_rules(procedure)
    if not rules:
        return None
    named = next((r["alert"] for r in reversed(rules) if r["alert"]), None)
    return {**rules[-1], "alert": rules[-1]["alert"] or named}


def metric_names(expr: str) -> list[str]:
    """Noms de métriques d'une expression PromQL (hors fonctions, labels, durées et mots-clés)."""
    bare = re.sub(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', "", expr)
    bare = re.sub(r"\{[^}]*\}|\[[^\]]*\]", " ", bare)
    bare = re.sub(r"\b(by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)", " ", bare)
    names = re.findall(r"(?<![\w.:])([a-zA-Z_:][\w:]*)(?![\w:])(?!\s*\()", bare)
    return list(dict.fromkeys(n for n in names if n.lower() not in PROMQL_KEYWORDS))


def _same(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def check_rule(rule: dict[str, Any], prom: Prometheus) -> str | None:
    """Erreur si Prometheus refuse l'expression, si une de ses métriques n'a aucune série, ou si la règle
    recopie une règle existante. Prometheus injoignable : ValueError (le contrôle est alors sauté)."""
    expr, alert = rule["expr"], rule.get("alert")
    try:
        prom.instant(expr)
    except ValueError as e:
        if "injoignable" in str(e):
            raise
        return f"Prometheus refuse l'expression {expr!r} : {str(e)[:300]}. Corrige-la et teste-la avec promql."
    empty = [m for m in metric_names(expr) if not prom.instant(f'count({{__name__="{m}"}})')]
    if empty:
        return (f"Métriques sans aucune série dans Prometheus : {', '.join(empty)} (expression {expr!r}). "
                "Une règle sur une métrique absente ne se déclenche jamais : utilise des métriques existantes, "
                "testées avec promql.")
    existing = [r for g in prom.get("/api/v1/rules", {"type": "alert"})["groups"] for r in g["rules"]]
    for r in existing:
        if _same(r.get("query", ""), expr):
            if alert in (None, r.get("name")):
                return (f"La règle {alert} proposée est identique à la règle actuelle ({expr!r}) : elle ne "
                        "change rien. Propose le réglage (seuil, durée for, expression) qui corrige le problème.")
            return (f"Cette expression existe déjà dans la règle {r.get('name')} : ne crée pas d'alerte en "
                    "double, propose de régler celle-ci.")
    return None


# Réponse finale

def unsupported_claims(text: str, peaks: dict[str, dict[str, Any]]) -> list[str]:
    """Phrases qui disent qu'un conteneur dépasse une taille que son pic mesuré n'atteint pas."""
    claims = []
    for line in re.split(r"(?<=[.!?])\s+|\n", text):
        names = sorted({n for _, n in _mentions(line, list(peaks))})
        if not names:
            continue
        for m in CLAIM.finditer(line):
            size = to_mb(m.group(2), m.group(3))
            below = [n for n in names if peaks[n]["mb"] < size]
            if below and len(below) == len(names):
                measured = ", ".join(f"{n} {_fmt(peaks[n]['mb'])} [{peaks[n]['ref']}]" for n in below)
                claims.append(f"« {line.strip()[:160]} » : pic mesuré {measured}, sous {_fmt(size)}")
    return claims
