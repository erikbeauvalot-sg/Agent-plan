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

    def _rows(self) -> list[dict[str, Any]]:
        """Points mesurés jusqu'à l'heure de référence : un incident passé rejoué ne voit pas la suite."""
        ref = catalog.now()
        return [r for r in catalog.rows(self.source_id) if catalog.parse_time(r["ts"]) <= ref]

    def hosts(self) -> list[str]:
        return sorted({r["host"] for r in self._rows()})

    def metrics(self, host: str) -> list[str]:
        return sorted({r["metric"] for r in self._rows() if r["host"] == host})

    def series(self, host: str, metric: str, start: datetime, end: datetime, step_s: int) -> list[Point]:
        points = [(catalog.parse_time(r["ts"]), r["value"]) for r in self._rows()
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

    def container_series(self, host: str, metric: str, start: datetime, end: datetime,
                         step_s: int) -> dict[str, list[Point]]:
        """Série par conteneur (label name, cAdvisor) d'une métrique de la section `containers:`."""
        templates = self.card.get("containers", {})
        if metric not in templates:
            raise ValueError(f"Métrique de conteneur {metric} non décrite ; disponibles : {', '.join(templates)}")
        result = self.range(templates[metric]["promql"].format(sel=self.selector(host)), start, end, step_s)
        return {r["metric"].get("name", "?"): to_points(r["values"]) for r in result}

    def container_starts(self, host: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Instances de conteneurs vues sur la période : nom, image, version, heure de démarrage."""
        promql = ("max by (name, id, image, container_label_org_opencontainers_image_version) "
                  f"(container_start_time_seconds{{name!=\"\",{self.selector(host)}}})")
        step = max(60, int((end - start).total_seconds() // 200))
        out = []
        for r in self.range(promql, start, end, step):
            points = to_points(r["values"])
            if points:
                labels = r["metric"]
                out.append({"name": labels.get("name"), "image": labels.get("image"),
                            "version": labels.get("container_label_org_opencontainers_image_version"),
                            "started_at": datetime.fromtimestamp(points[-1][1], timezone.utc)})
        return out


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
