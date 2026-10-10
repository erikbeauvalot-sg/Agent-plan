"""Backends de métriques derrière mcp-metrics : fichier de démonstration et Prometheus.

Chaque backend répond aux mêmes questions (hosts suivis, métriques d'un host, série d'une métrique)
avec des noms de métriques normalisés ; mcp-metrics choisit le backend qui suit le host.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from diagagent import catalog
from .http import get_json

Point = tuple[datetime, float]


class MetricBackend(Protocol):
    source_id: str

    def hosts(self) -> list[str]: ...

    def metrics(self, host: str) -> list[str]: ...

    def series(self, host: str, metric: str, start: datetime, end: datetime, step_s: int) -> list[Point]: ...


class DemoMetrics:
    def __init__(self, card: dict[str, Any]):
        self.source_id = card["id"]

    def hosts(self) -> list[str]:
        return sorted({r["host"] for r in catalog.rows(self.source_id)})

    def metrics(self, host: str) -> list[str]:
        return sorted({r["metric"] for r in catalog.rows(self.source_id) if r["host"] == host})

    def series(self, host: str, metric: str, start: datetime, end: datetime, step_s: int) -> list[Point]:
        points = [(catalog.parse_time(r["ts"]), r["value"]) for r in catalog.rows(self.source_id)
                  if r["host"] == host and r["metric"] == metric]
        return [(t, v) for t, v in points if start <= t < end]


class PrometheusMetrics:
    """Les métriques normalisées sont des modèles PromQL de la fiche catalogue (`metrics:`),
    où {sel} devient le sélecteur du host : instance="host" avec ou sans port."""

    def __init__(self, card: dict[str, Any]):
        self.source_id = card["id"]
        self.card = card
        self.url = card["backend"]["url"]
        self.token_env = card["backend"].get("bearer_token_env")
        self.host_label = card["backend"].get("host_label", "instance")

    def get(self, path: str, params: dict[str, Any]) -> Any:
        data = get_json(self.url, path, params, self.token_env)
        if data.get("status") != "success":
            raise ValueError(f"Prometheus : {data.get('errorType')} {data.get('error')}")
        return data["data"]

    def selector(self, host: str) -> str:
        # Le point est échappé pour la regex ; la barre oblique est doublée pour la chaîne PromQL.
        escaped = host.replace(".", r"\\.")
        return f'{self.host_label}=~"{escaped}(:[0-9]+)?"'

    def instant(self, promql: str) -> list[dict[str, Any]]:
        return self.get("/api/v1/query", {"query": promql, "time": catalog.now().timestamp()})["result"]

    def range(self, promql: str, start: datetime, end: datetime, step_s: int) -> list[dict[str, Any]]:
        data = self.get("/api/v1/query_range", {"query": promql, "start": start.timestamp(),
                                                 "end": end.timestamp(), "step": step_s})
        return data["result"]

    def hosts(self) -> list[str]:
        return sorted({host_of(r["metric"], self.host_label) for r in self.instant("up")} - {""})

    def targets(self) -> list[dict[str, Any]]:
        """Cibles de collecte : host, job, état (up = 1)."""
        return [{"host": host_of(r["metric"], self.host_label), "job": r["metric"].get("job"),
                 "up": r["value"][1] == "1"} for r in self.instant("up")]

    def metrics(self, host: str) -> list[str]:
        sel = self.selector(host)
        return [name for name, tpl in self.card.get("metrics", {}).items()
                if self.instant(tpl["promql"].format(sel=sel))]

    def series(self, host: str, metric: str, start: datetime, end: datetime, step_s: int) -> list[Point]:
        templates = self.card.get("metrics", {})
        if metric not in templates:
            raise ValueError(f"Métrique {metric} non décrite pour {self.source_id} ; "
                             f"disponibles : {', '.join(templates)}")
        result = self.range(templates[metric]["promql"].format(sel=self.selector(host)), start, end, step_s)
        if not result:
            return []
        return to_points(result[0]["values"])


def host_of(labels: dict[str, str], host_label: str = "instance") -> str:
    """Nom du host à partir des labels Prometheus : instance sans port, ou label host/hostname."""
    for key in (host_label, "host", "hostname", "instance"):
        if labels.get(key):
            return labels[key].rsplit(":", 1)[0] if ":" in labels[key] else labels[key]
    return ""


def to_points(values: list[list[Any]]) -> list[Point]:
    out = []
    for ts, v in values:
        try:
            out.append((datetime.fromtimestamp(float(ts), timezone.utc), float(v)))
        except ValueError:
            continue
    return out


def backends() -> list[MetricBackend]:
    out: list[MetricBackend] = []
    for card in catalog.sources_of_kind("metrics"):
        kind = card["backend"]["type"]
        if kind == "file":
            out.append(DemoMetrics(card))
        elif kind == "prometheus":
            out.append(PrometheusMetrics(card))
        else:
            raise NotImplementedError(f"Backend de métriques {kind} pas encore disponible")
    return out


def prometheus() -> PrometheusMetrics | None:
    return next((b for b in backends() if isinstance(b, PrometheusMetrics)), None)
