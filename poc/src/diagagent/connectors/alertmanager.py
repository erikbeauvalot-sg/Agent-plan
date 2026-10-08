"""Connecteur Alertmanager : alertes en cours et silences (API v2)."""

from __future__ import annotations

from typing import Any

from .http import get_json
from .metrics import host_of


class Alertmanager:
    def __init__(self, card: dict[str, Any]):
        self.source_id = card["id"]
        self.url = card["backend"]["url"]
        self.token_env = card["backend"].get("bearer_token_env")

    def alerts(self, include_silenced: bool = False) -> list[dict[str, Any]]:
        raw = get_json(self.url, "/api/v2/alerts", {
            "active": "true", "silenced": str(include_silenced).lower(),
            "inhibited": str(include_silenced).lower()}, self.token_env)
        return [{
            "alertname": a["labels"].get("alertname"),
            "host": host_of(a["labels"]),
            "severity": a["labels"].get("severity"),
            "state": a.get("status", {}).get("state"),
            "starts_at": a.get("startsAt"),
            "summary": a.get("annotations", {}).get("summary") or a.get("annotations", {}).get("description"),
            "labels": a["labels"],
        } for a in raw]

    def silences(self) -> list[dict[str, Any]]:
        raw = get_json(self.url, "/api/v2/silences", None, self.token_env)
        return [{"id": s["id"], "state": s.get("status", {}).get("state"), "matchers": s.get("matchers"),
                 "starts_at": s.get("startsAt"), "ends_at": s.get("endsAt"), "comment": s.get("comment")}
                for s in raw if s.get("status", {}).get("state") != "expired"]
