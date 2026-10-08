"""Génère les données factices du POC (scénario : lenteurs du service Paiement la nuit du 6 octobre).

Scénario :
- 21:45Z  change CHG0034567 sur db-pay-02 : max_connections passe de 500 à 200.
- 22:10Z  srv-pay-01 commence à saturer son pool de connexions ; latence p95 en hausse.
- 22:12Z  alerte de latence sur srv-pay-01 ; 22:15Z alerte connexions sur db-pay-02.
- 22:25Z  incident INC0098765 ouvert par le support.

Usage : python demo_data/generate.py  (réécrit les fichiers .json/.jsonl de ce dossier)
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
START = datetime(2026, 10, 5, 22, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)
INCIDENT_START = datetime(2026, 10, 6, 22, 10, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def write(name: str, rows: list[dict]) -> None:
    path = HERE / name
    if name.endswith(".jsonl"):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    else:
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmdb() -> list[dict]:
    return [
        {"ci_id": "CI0012345", "hostname": "srv-pay-01", "type": "serveur applicatif", "service": "PAY",
         "application": "paiement-api", "environment": "prod", "os": "RHEL 9",
         "owner_team": "équipe Paiement", "depends_on": ["CI0012400", "CI0011000"]},
        {"ci_id": "CI0012400", "hostname": "db-pay-02", "type": "base de données", "service": "PAY",
         "application": "postgresql-paiement", "environment": "prod", "os": "RHEL 9",
         "owner_team": "équipe Bases de données", "depends_on": []},
        {"ci_id": "CI0011000", "hostname": "lb-front-01", "type": "répartiteur de charge", "service": "FRONT",
         "application": "haproxy-front", "environment": "prod", "os": "RHEL 9",
         "owner_team": "équipe Réseau", "depends_on": []},
        {"ci_id": "CI0013001", "hostname": "srv-web-03", "type": "serveur web", "service": "WEB",
         "application": "portail-client", "environment": "prod", "os": "RHEL 9",
         "owner_team": "équipe Portail", "depends_on": ["CI0011000", "CI0012345"]},
    ]


def incidents() -> list[dict]:
    return [
        {"number": "INC0098765", "priority": "P2", "state": "In Progress",
         "opened_at": "2026-10-06T22:25:00Z", "affected_ci": {"hostname": "srv-pay-01", "id": "CI0012345"},
         "business_service": "PAY", "short_description": "Lenteurs sur les paiements par carte",
         "assignment_group": "équipe Paiement", "caller_email": "support.n1@example.com"},
        {"number": "INC0097012", "priority": "P3", "state": "Closed",
         "opened_at": "2026-09-12T08:02:00Z", "affected_ci": {"hostname": "srv-pay-01", "id": "CI0012345"},
         "business_service": "PAY", "short_description": "Système de fichiers /var plein",
         "assignment_group": "équipe Système", "caller_email": "supervision@example.com",
         "resolution": "Purge des journaux applicatifs et rotation corrigée"},
        {"number": "INC0098701", "priority": "P4", "state": "New",
         "opened_at": "2026-10-06T14:40:00Z", "affected_ci": {"hostname": "srv-web-03", "id": "CI0013001"},
         "business_service": "WEB", "short_description": "Coquille dans la page d'accueil du portail",
         "assignment_group": "équipe Portail", "caller_email": "metier@example.com"},
    ]


def changes() -> list[dict]:
    return [
        {"number": "CHG0034567", "state": "Implemented", "risk": "Low",
         "start": "2026-10-06T21:45:00Z", "end": "2026-10-06T21:55:00Z",
         "ci": {"hostname": "db-pay-02", "id": "CI0012400"}, "service": "PAY",
         "short_description": "Tuning mémoire PostgreSQL : max_connections 500 -> 200",
         "implementer": "équipe Bases de données"},
        {"number": "CHG0034550", "state": "Implemented", "risk": "Low",
         "start": "2026-10-06T10:00:00Z", "end": "2026-10-06T10:20:00Z",
         "ci": {"hostname": "srv-web-03", "id": "CI0013001"}, "service": "WEB",
         "short_description": "Mise à jour du certificat TLS du portail",
         "implementer": "équipe Portail"},
    ]


def events() -> list[dict]:
    return [
        {"@timestamp": "2026-10-06T22:12:00Z", "host": "srv-pay-01", "severity": "major",
         "check": "http.latency_p95", "message": "Latence p95 > 2000 ms (valeur 3450 ms)", "status": "open"},
        {"@timestamp": "2026-10-06T22:15:00Z", "host": "db-pay-02", "severity": "major",
         "check": "db.connections_pct", "message": "Connexions actives à 100 % de max_connections (200/200)",
         "status": "open"},
        {"@timestamp": "2026-10-06T03:00:00Z", "host": "srv-web-03", "severity": "minor",
         "check": "disk.used_pct", "message": "Disque /data à 82 %", "status": "closed"},
    ]


def logs() -> list[dict]:
    rnd = random.Random(42)
    rows: list[dict] = []
    t = START
    while t < END:
        rows.append({"@timestamp": iso(t), "host": "srv-pay-01", "level": "INFO", "service": "PAY",
                     "logger": "paiement.api", "message": f"POST /v1/payments 201 {rnd.randint(80, 160)} ms"})
        rows.append({"@timestamp": iso(t + timedelta(minutes=7)), "host": "srv-web-03", "level": "INFO",
                     "service": "WEB", "logger": "portail.http", "message": "GET / 200"})
        t += timedelta(minutes=15)
    t = INCIDENT_START
    while t < END:
        for _ in range(rnd.randint(3, 6)):
            ts = t + timedelta(seconds=rnd.randint(0, 299))
            rows.append({"@timestamp": iso(ts), "host": "srv-pay-01", "level": "ERROR", "service": "PAY",
                         "logger": "paiement.db",
                         "message": "HikariPool-1 - Connection is not available, request timed out after 30000ms "
                                    "(connection pool exhausted, db-pay-02:5432)"})
        rows.append({"@timestamp": iso(t + timedelta(seconds=rnd.randint(0, 299))), "host": "db-pay-02",
                     "level": "FATAL", "service": "PAY", "logger": "postgresql",
                     "message": "sorry, too many clients already"})
        rows.append({"@timestamp": iso(t + timedelta(seconds=30)), "host": "srv-pay-01", "level": "WARN",
                     "service": "PAY", "logger": "paiement.api",
                     "message": f"POST /v1/payments 504 {rnd.randint(28000, 31000)} ms"})
        t += timedelta(minutes=5)
    rows.append({"@timestamp": "2026-10-06T21:50:12Z", "host": "db-pay-02", "level": "LOG", "service": "PAY",
                 "logger": "postgresql",
                 "message": "received SIGHUP, reloading configuration files; parameter \"max_connections\" "
                            "changed to \"200\""})
    rows.sort(key=lambda r: r["@timestamp"])
    return rows


def metrics() -> list[dict]:
    """Une ligne par point : {ts, host, metric, value}, pas de 5 min."""
    rnd = random.Random(7)
    rows: list[dict] = []
    t = START
    while t < END:
        hour = t.hour + t.minute / 60
        daily = 0.5 + 0.5 * math.sin((hour - 8) / 24 * 2 * math.pi)
        degraded = t >= INCIDENT_START
        values = {
            ("srv-pay-01", "cpu.usage"): 25 + 20 * daily + rnd.uniform(-3, 3) + (10 if degraded else 0),
            ("srv-pay-01", "mem.used_pct"): 61 + rnd.uniform(-2, 2),
            ("srv-pay-01", "http.latency_p95"): (3000 + rnd.uniform(0, 900)) if degraded
            else 140 + 60 * daily + rnd.uniform(-15, 15),
            ("db-pay-02", "cpu.usage"): 30 + 15 * daily + rnd.uniform(-3, 3),
            ("db-pay-02", "db.connections"): 200 if degraded
            else (180 + rnd.randint(-10, 10) if t >= datetime(2026, 10, 6, 21, 50, tzinfo=timezone.utc)
                  else 240 + 60 * daily + rnd.randint(-15, 15)),
            ("db-pay-02", "db.max_connections"): 200
            if t >= datetime(2026, 10, 6, 21, 50, tzinfo=timezone.utc) else 500,
            ("srv-web-03", "cpu.usage"): 15 + 10 * daily + rnd.uniform(-2, 2),
        }
        for (host, metric), v in values.items():
            rows.append({"ts": iso(t), "host": host, "metric": metric, "value": round(v, 1)})
        t += timedelta(minutes=5)
    return rows


if __name__ == "__main__":
    write("cmdb.json", cmdb())
    write("incidents.json", incidents())
    write("changes.json", changes())
    write("events.json", events())
    write("logs.jsonl", logs())
    write("metrics.jsonl", metrics())
    print("Données de démonstration régénérées dans", HERE)
