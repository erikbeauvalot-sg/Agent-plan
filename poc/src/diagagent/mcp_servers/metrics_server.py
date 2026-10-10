"""mcp-metrics : interface unique sur plusieurs outils de métriques (démonstration, Prometheus).

Réponses résumées (min, max, moyenne, ruptures, série sous-échantillonnée) : pas de séries brutes
envoyées au modèle.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import mean
from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
from diagagent.connectors import metrics as backends_mod
from diagagent.mcp_servers.common import read_only_tool

server = MCPServer("mcp-metrics", instructions="Métriques en lecture seule, réponses résumées.")
MAX_POINTS = 48
MAX_SERIES = 10
MAX_RANGE = timedelta(days=7)


def _backend_for(host: str) -> backends_mod.MetricBackend:
    """Premier outil qui suit le host, dans l'ordre du catalogue."""
    seen = {}
    for b in backends_mod.backends():
        hosts = b.hosts()
        seen[b.source_id] = hosts
        if host in hosts:
            return b
    raise ValueError(f"Aucun outil de métriques ne suit {host} ; hosts suivis : {seen}")


def _window(time_from: str | None, time_to: str | None) -> tuple[datetime, datetime]:
    start, end = catalog.time_window(time_from, time_to)
    if end - start > MAX_RANGE:
        raise ValueError("Période trop longue : 7 jours au maximum")
    return start, end


def _step_minutes(start: datetime, end: datetime, wanted: int) -> int:
    step = max(1, wanted)
    while (end - start).total_seconds() / 60 / step > MAX_POINTS:
        step *= 2
    return step


def _summarize(points: list[tuple[datetime, float]], start: datetime, step: int) -> dict[str, Any]:
    buckets: dict[int, list[float]] = {}
    for t, v in points:
        buckets.setdefault(int((t - start).total_seconds() // (step * 60)), []).append(v)
    values = [v for _, v in points]
    # La série moyennée lisse les pics courts : max_at date le maximum mesuré.
    peak_at, peak = max(points, key=lambda p: p[1])
    return {
        "summary": {"min": round(min(values), 2), "max": round(peak, 2), "max_at": peak_at.isoformat(),
                    "mean": round(mean(values), 2), "points": len(points)},
        "breaks": _breaks(points),
        "series": [{"ts": (start + timedelta(minutes=i * step)).isoformat(), "value": round(mean(vs), 2)}
                   for i, vs in sorted(buckets.items())],
    }


@read_only_tool(server)
def list_hosts() -> dict[str, Any]:
    """Hosts suivis par chaque outil de métriques (et, pour Prometheus, état des cibles de collecte)."""
    out: dict[str, Any] = {}
    for b in backends_mod.backends():
        if isinstance(b, backends_mod.PrometheusMetrics):
            out[b.source_id] = b.targets()
        else:
            out[b.source_id] = [{"host": h} for h in b.hosts()]
    return out


@read_only_tool(server)
def list_metrics(host: str) -> dict[str, Any]:
    """Métriques normalisées disponibles pour un host, avec leur description et l'outil qui les fournit."""
    b = _backend_for(host)
    glossary = catalog.load_yaml("glossary.yaml").get("metrics", {})
    return {"host": host, "source": b.source_id,
            "metrics": [{"name": n, "desc": glossary.get(n, "")} for n in b.metrics(host)]}


@read_only_tool(server)
def query_metric(host: str, metric: str, time_from: str | None = None, time_to: str | None = None,
                 step_minutes: int = 5) -> dict[str, Any]:
    """Résumé d'une métrique normalisée (voir list_metrics) sur une période : min, max, moyenne,
    ruptures détectées et série sous-échantillonnée (48 points au plus).

    time_from / time_to : ISO 8601 UTC, par défaut les 24 h précédant l'heure de référence ; 7 jours max.
    """
    start, end = _window(time_from, time_to)
    b = _backend_for(host)
    step = _step_minutes(start, end, step_minutes)
    points = b.series(host, metric, start, end, max(60, step * 60 // 4))
    if not points:
        raise ValueError(f"Pas de point pour {host}/{metric} sur la période")
    return {"host": host, "metric": metric, "source": b.source_id,
            "time_range": [start.isoformat(), end.isoformat()], "step_minutes": step,
            **_summarize(points, start, step)}


@read_only_tool(server)
def promql(query: str, time_from: str | None = None, time_to: str | None = None,
           step_minutes: int = 5) -> dict[str, Any]:
    """Requête PromQL libre sur Prometheus, résumée par série (10 séries au plus).

    À utiliser quand aucune métrique normalisée ne convient, par exemple
    rate(node_network_receive_errs_total{instance=~"nas.*"}[5m]).
    """
    prom = backends_mod.prometheus()
    if prom is None:
        raise ValueError("Aucune source Prometheus configurée (variable PROMETHEUS_URL)")
    start, end = _window(time_from, time_to)
    step = _step_minutes(start, end, step_minutes)
    result = prom.range(query, start, end, max(60, step * 60 // 4))
    series = []
    for r in result[:MAX_SERIES]:
        points = backends_mod.to_points(r["values"])
        if points:
            series.append({"labels": r["metric"], **_summarize(points, start, step)})
    return {"query": query, "source": prom.source_id, "time_range": [start.isoformat(), end.isoformat()],
            "step_minutes": step, "series_total": len(result), "truncated": len(result) > MAX_SERIES,
            "series": series}


def _breaks(points: list[tuple[Any, float]], window: int = 6, ratio: float = 0.5) -> list[dict[str, Any]]:
    """Ruptures : points où la moyenne des `window` points suivants s'écarte de plus de `ratio` de la
    moyenne des `window` précédents ; on garde le point le plus marqué de chaque zone."""
    scores = []
    for i in range(window, len(points) - window + 1):
        before = mean(v for _, v in points[i - window:i])
        after = mean(v for _, v in points[i:i + window])
        scores.append((abs(after - before) / (abs(before) or 1.0), i, before, after))
    found: list[dict[str, Any]] = []
    taken: list[int] = []
    for score, i, before, after in sorted(scores, reverse=True):
        if score <= ratio:
            break
        if any(abs(i - j) < window for j in taken):
            continue
        taken.append(i)
        found.append({"at": points[i][0].isoformat(), "before_mean": round(before, 1),
                      "after_mean": round(after, 1)})
    return sorted(found, key=lambda b: b["at"])

if __name__ == "__main__":
    server.run()
