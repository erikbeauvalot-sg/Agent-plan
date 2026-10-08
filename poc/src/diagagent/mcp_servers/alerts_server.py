"""mcp-alerts : alertes en cours et silences (Alertmanager), historique des alertes (série ALERTS de Prometheus)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
from diagagent.connectors import metrics as metrics_mod
from diagagent.connectors.alertmanager import Alertmanager
from diagagent.mcp_servers.common import read_only_tool

server = MCPServer("mcp-alerts", instructions="Alertes de supervision en lecture seule.")


def _alertmanager() -> Alertmanager:
    cards = catalog.sources_of_kind("alerts")
    if not cards:
        raise ValueError("Aucune source Alertmanager configurée (variable ALERTMANAGER_URL)")
    return Alertmanager(cards[0])


@read_only_tool(server)
def list_alerts(host: str | None = None, severity: str | None = None,
                include_silenced: bool = False) -> dict[str, Any]:
    """Alertes actives maintenant dans Alertmanager, filtrables par host et sévérité."""
    am = _alertmanager()
    alerts = [a for a in am.alerts(include_silenced)
              if (not host or a["host"] == host) and (not severity or a["severity"] == severity)]
    alerts.sort(key=lambda a: a["starts_at"] or "", reverse=True)
    return {"source": am.source_id, "total": len(alerts), "alerts": alerts[:100]}


@read_only_tool(server)
def list_silences() -> dict[str, Any]:
    """Silences actifs ou à venir : une alerte silencieuse peut cacher un symptôme."""
    am = _alertmanager()
    return {"source": am.source_id, "silences": am.silences()}


@read_only_tool(server)
def alert_history(host: str | None = None, alertname: str | None = None, time_from: str | None = None,
                  time_to: str | None = None) -> dict[str, Any]:
    """Alertes qui ont été en état firing sur la période (d'après la série ALERTS de Prometheus),
    avec leurs intervalles de déclenchement. Utile pour dater le début d'un symptôme.
    """
    prom = metrics_mod.prometheus()
    if prom is None:
        raise ValueError("Historique indisponible : aucune source Prometheus configurée (PROMETHEUS_URL)")
    start, end = catalog.time_window(time_from, time_to)
    if end - start > timedelta(days=7):
        raise ValueError("Période trop longue : 7 jours au maximum")
    matchers = ['alertstate="firing"']
    if alertname:
        matchers.append(f'alertname="{alertname}"')
    step = 60 if end - start <= timedelta(days=1) else 300
    result = prom.range("ALERTS{" + ",".join(matchers) + "}", start, end, step)
    out = []
    for r in result:
        labels = r["metric"]
        if host and metrics_mod.host_of(labels) != host:
            continue
        out.append({"alertname": labels.get("alertname"), "host": metrics_mod.host_of(labels),
                    "severity": labels.get("severity"),
                    "intervals": _intervals(metrics_mod.to_points(r["values"]), step)})
    out.sort(key=lambda a: a["intervals"][0]["from"] if a["intervals"] else "")
    return {"source": prom.source_id, "time_range": [start.isoformat(), end.isoformat()],
            "total": len(out), "alerts": out[:100]}


def _intervals(points: list[Any], step: int) -> list[dict[str, str]]:
    """Regroupe les points consécutifs (écart <= 2 pas) en intervalles de déclenchement."""
    intervals: list[dict[str, Any]] = []
    for t, _ in points:
        if intervals and (t - intervals[-1]["_last"]).total_seconds() <= 2 * step:
            intervals[-1]["_last"] = t
        else:
            intervals.append({"_first": t, "_last": t})
    return [{"from": i["_first"].isoformat(), "to": i["_last"].isoformat()} for i in intervals]


if __name__ == "__main__":
    server.run()
