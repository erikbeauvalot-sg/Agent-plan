"""mcp-metrics (démo) : séries temporelles résumées, sans envoyer de séries brutes au modèle."""

from __future__ import annotations

from datetime import timedelta
from statistics import mean
from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
from diagagent.mcp_servers.common import read_only_tool

server = MCPServer("mcp-metrics", instructions="Métriques en lecture seule, réponses résumées.")
SOURCE = "metrics-demo"
MAX_POINTS = 48


@read_only_tool(server)
def list_metrics(host: str) -> dict[str, Any]:
    """Métriques disponibles pour un host, avec leur description."""
    names = sorted({r["metric"] for r in catalog.rows(SOURCE) if r["host"] == host})
    if not names:
        raise ValueError(f"Aucune métrique pour {host} ; hosts couverts : "
                         f"{catalog.get_source(SOURCE).get('coverage', {}).get('hosts')}")
    glossary = catalog.load_yaml("glossary.yaml").get("metrics", {})
    return {"host": host, "source": SOURCE, "metrics": [{"name": n, "desc": glossary.get(n, "")} for n in names]}


@read_only_tool(server)
def query_metric(host: str, metric: str, time_from: str | None = None, time_to: str | None = None,
                 step_minutes: int = 30) -> dict[str, Any]:
    """Résumé d'une métrique sur une période : min, max, moyenne, ruptures détectées et série sous-échantillonnée.

    time_from / time_to : ISO 8601 UTC, par défaut les 24 h précédant l'heure de référence.
    step_minutes : pas de la série renvoyée (moyenne par pas), au moins 5.
    """
    start, end = catalog.time_window(time_from, time_to)
    points = [(catalog.parse_time(r["ts"]), r["value"]) for r in catalog.rows(SOURCE)
              if r["host"] == host and r["metric"] == metric]
    points = [(t, v) for t, v in points if start <= t < end]
    if not points:
        raise ValueError(f"Pas de point pour {host}/{metric} sur la période")
    step = max(5, step_minutes)
    while (end - start).total_seconds() / 60 / step > MAX_POINTS:
        step *= 2
    buckets: dict[int, list[float]] = {}
    for t, v in points:
        buckets.setdefault(int((t - start).total_seconds() // (step * 60)), []).append(v)
    series = [{"ts": (start + timedelta(minutes=i * step)).isoformat(), "value": round(mean(vs), 1)}
              for i, vs in sorted(buckets.items())]
    return {"host": host, "metric": metric, "source": SOURCE,
            "time_range": [start.isoformat(), end.isoformat()], "step_minutes": step,
            "summary": {"min": min(v for _, v in points), "max": max(v for _, v in points),
                        "mean": round(mean(v for _, v in points), 1), "points": len(points)},
            "breaks": _breaks(points), "series": series}


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
