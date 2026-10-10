"""Page d'accueil : état des modèles et des sources, activité, statistiques et derniers résultats d'éval.

Les vérifications d'état n'appellent jamais un modèle payant : un fournisseur distant est « prêt » si sa
clé ou son point d'accès est configuré ; seul un serveur local (Ollama, vLLM) est interrogé (liste des
modèles)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import catalog
from .connectors.http import get_json
from .llm import model_profiles, select_profile

PROBE_TIMEOUT_S = 3
ENDED = ("completed", "partial", "stopped", "failed", "needs_clarification")


def _model_name(role_cfg: dict[str, Any]) -> str:
    return role_cfg.get("deployment") or role_cfg.get("model") or "?"


def provider_status(provider_cfg: dict[str, Any], models: set[str]) -> tuple[bool, str]:
    """Fournisseur utilisable pour ces modèles ? Retourne (prêt, détail)."""
    adapter = provider_cfg.get("adapter")
    if adapter == "openai_compatible" and provider_cfg.get("api_key_env"):
        env = provider_cfg["api_key_env"]
        return (True, "clé présente") if os.environ.get(env) else (False, f"{env} absente")
    if adapter == "openai_compatible":  # serveur local : on vérifie qu'il répond et qu'il a les modèles
        try:
            data = get_json(provider_cfg["base_url"], "/models", timeout=PROBE_TIMEOUT_S)
        except ValueError as e:
            return False, f"injoignable ({str(e)[:80]})"
        available = {m.get("id") for m in data.get("data", [])}
        missing = sorted(models - available)
        return (False, f"modèle absent : {', '.join(missing)}") if missing else (True, "répond")
    if adapter == "azure_openai":
        endpoint = os.path.expandvars(provider_cfg.get("endpoint", ""))
        if not endpoint or "$" in endpoint:
            return False, "AZURE_OPENAI_ENDPOINT absente"
        if provider_cfg.get("auth") == "api_key" and not os.environ.get("AZURE_OPENAI_API_KEY"):
            return False, "AZURE_OPENAI_API_KEY absente"
        return True, "point d'accès configuré"
    if adapter == "anthropic":
        return (True, "clé présente") if os.environ.get("ANTHROPIC_API_KEY") else (False, "ANTHROPIC_API_KEY absente")
    return False, f"adaptateur inconnu : {adapter}"


def models_status(models_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Un élément par profil : modèles par rôle, prêt ou non, et pourquoi."""
    names, default = model_profiles(models_cfg)
    out = []
    for name in names:
        roles = select_profile(models_cfg, name)[1]["roles"]
        by_provider: dict[str, set[str]] = {}
        for role_cfg in roles.values():
            by_provider.setdefault(role_cfg["provider"], set()).add(_model_name(role_cfg))
        checks = [provider_status(models_cfg["providers"][p], m) for p, m in by_provider.items()]
        out.append({"profile": name, "default": name == default,
                    "roles": {role: _model_name(cfg) for role, cfg in roles.items()},
                    "ok": all(ok for ok, _ in checks), "detail": " · ".join(d for _, d in checks)})
    return out


def sources_status() -> dict[str, Any]:
    """État des jeux de sources et alertes en cours (Alertmanager), quel que soit le réglage actif."""
    from .connectors.alertmanager import Alertmanager
    from .connectors.ssh import SshProbe

    with catalog.using_sources("demo,maison"):
        cards = catalog.load_catalog()
    demo = [c["id"] for c in cards.values() if catalog.source_set(c) == "demo"]
    items = [{"set": "demo", "name": "Démo", "ok": True, "detail": f"{len(demo)} sources factices"}]
    alerts: list[dict[str, Any]] = []
    for name, env in (("Prometheus", "PROMETHEUS_URL"), ("Alertmanager", "ALERTMANAGER_URL")):
        card = next((c for c in cards.values() if env in c.get("requires_env", [])), None)
        if card is None:
            items.append({"set": "maison", "name": name, "ok": False, "configured": False,
                          "detail": f"non configuré ({env})"})
            continue
        backend = card["backend"]
        try:
            if name == "Prometheus":
                up = get_json(backend["url"], "/api/v1/query", {"query": "up"}, backend.get("bearer_token_env"),
                              timeout=PROBE_TIMEOUT_S)["data"]["result"]
                n_up = sum(r["value"][1] == "1" for r in up)
                detail = f"{n_up}/{len(up)} cibles up"
            else:
                alerts = Alertmanager(card).alerts()
                detail = f"{len(alerts)} alerte(s) active(s)"
            items.append({"set": "maison", "name": name, "ok": True, "configured": True, "detail": detail})
        except (ValueError, KeyError) as e:
            items.append({"set": "maison", "name": name, "ok": False, "configured": True,
                          "detail": f"erreur : {str(e)[:100]}"})
    # SSH : machines déclarées seulement, sans connexion (une sonde par machine ralentirait l'accueil).
    ssh_card = next((c for c in cards.values() if c.get("kind") == "system"), None)
    if ssh_card is None:
        items.append({"set": "maison", "name": "SSH", "ok": False, "configured": False,
                      "detail": "non configuré (SSH_HOSTS)"})
    else:
        hosts = sorted(SshProbe(ssh_card).hosts)
        items.append({"set": "maison", "name": "SSH", "ok": bool(hosts), "configured": True,
                      "detail": f"{len(hosts)} machine(s) : {', '.join(hosts)}"})
    alerts.sort(key=lambda a: (a.get("severity") != "critical", a.get("starts_at") or ""))
    return {"sources": items, "alerts": [{k: a.get(k) for k in ("alertname", "host", "severity", "starts_at", "summary")}
                                         for a in alerts[:10]]}


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _duration(row: dict[str, Any]) -> float | None:
    start, end = _ts(row.get("started_at")), _ts(row.get("ended_at"))
    return (end - start).total_seconds() if start and end else None


def _tokens(row: dict[str, Any]) -> int:
    usage = row.get("usage") or {}
    return (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)


def _rate(ok: int, n: int) -> float | None:
    return round(ok / n, 3) if n else None


def enrich(row: dict[str, Any], manifest_of: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """Les lignes d'index antérieures n'ont ni profil ni sous-agents : on les relit dans le manifest."""
    if "subagents" in row:
        return row
    m = manifest_of(row) or {}
    return {**row, "models_profile": m.get("models_profile"), "sources": m.get("sources"),
            "model": ((m.get("models") or {}).get("lead") or {}).get("model"),
            "subagents": [{"role": s.get("role"), "status": s.get("status")} for s in (m.get("subagents") or {}).values()]}


def label(row: dict[str, Any]) -> str:
    """Profil de modèles, sinon nom du modèle principal (investigations antérieures aux profils)."""
    return row.get("models_profile") or row.get("model") or "?"


def activity(rows: Iterable[dict[str, Any]], manifest_of: Callable[[dict[str, Any]], dict[str, Any]],
             now: datetime, days: int = 7, include_eval: bool = False) -> dict[str, Any]:
    """Chiffres du jour et statistiques de la période : par catégorie, par profil de modèles, par agent.
    Une investigation réussit si elle se termine « completed » ; les évaluations sont exclues par défaut."""
    since, today = now - timedelta(days=days), now.date()
    period = [enrich(r, manifest_of) for r in rows
              if (include_eval or r.get("user") not in ("eval", "replay"))
              and r.get("status") in ENDED and (_ts(r.get("started_at")) or now) >= since]

    def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        durations = [d for d in map(_duration, items) if d is not None]
        statuses: dict[str, int] = {}
        for r in items:
            statuses[r["status"]] = statuses.get(r["status"], 0) + 1
        return {"runs": len(items), "statuses": statuses, "success_rate": _rate(statuses.get("completed", 0), len(items)),
                "avg_duration_s": round(sum(durations) / len(durations), 1) if durations else None,
                "tokens": sum(map(_tokens, items))}

    def grouped(key: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in period:
            groups.setdefault(key(r), []).append(r)
        return sorted(({"name": k, **summary(v)} for k, v in groups.items()), key=lambda x: -x["runs"])

    agents: dict[str, dict[str, int]] = {}
    for r in period:
        for role, status in [("principal", r["status"])] + [(s.get("role") or "?", s.get("status") or "?")
                                                              for s in r.get("subagents") or []]:
            row = agents.setdefault(role, {})
            row[status] = row.get(status, 0) + 1
    agent_rows = [{"name": role, "runs": sum(c.values()), "statuses": c,
                   "success_rate": _rate(c.get("completed", 0), sum(c.values())),
                   "failure_rate": _rate(c.get("failed", 0), sum(c.values()))}
                  for role, c in agents.items()]
    agent_rows.sort(key=lambda x: (x["name"] != "principal", -x["runs"]))
    today_rows = [r for r in period if (_ts(r["started_at"]) or now).date() == today]
    by_model: dict[str, int] = {}
    for r in today_rows:
        by_model[label(r)] = by_model.get(label(r), 0) + 1
    return {"days": days, "include_eval": include_eval,
            "today": {**summary(today_rows), "by_model": by_model},
            "period": summary(period), "categories": grouped(lambda r: r.get("category") or "?"),
            "models": grouped(label), "agents": agent_rows}


def last_evals(results_dir: Path, manifest_of_run: Callable[[str], dict[str, Any] | None], limit: int = 4) -> list[dict[str, Any]]:
    """Dernier rapport d'éval par profil de modèles (et par jeu de cas), du plus récent au plus ancien."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sorted(results_dir.glob("*.json"), reverse=True):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        s, results = report.get("summary") or {}, report.get("results") or []
        if not results:
            continue
        name = s.get("models_profile")
        if not name:  # rapport antérieur aux profils : modèle principal de la première investigation
            m = manifest_of_run(results[0]["run_id"]) or {}
            name = ((m.get("models") or {}).get("lead") or {}).get("model") or "?"
        cases = Path(report.get("cases_file") or "?").name
        if (name, cases) in seen:
            continue
        seen[(name, cases)] = {"label": name, "cases_file": cases, "date": report.get("date"), "passed": s.get("passed"),
                               "cases": s.get("cases"), "tokens": s.get("tokens"), "repeat": s.get("repeat", 1),
                               "duration_s": s.get("duration_s") or round(sum(r.get("duration_s") or 0 for r in results), 1),
                               "file": path.name}
        if len(seen) >= limit:
            break
    return list(seen.values())
