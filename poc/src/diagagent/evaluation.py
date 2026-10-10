"""Évaluation et rejeu.

- `run_eval` pose les questions d'un jeu de cas au modèle configuré et vérifie mécaniquement chaque
  réponse (mentions attendues, nombre de sous-agents, actions proposées, erreurs d'outil).
- `replay_run` rejoue une investigation passée avec les réponses enregistrées du modèle et compare
  les résultats d'outils : une différence signale un changement de comportement des sources ou des
  serveurs MCP, sans aucun appel au modèle.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import catalog
from .llm.replay import ReplayProvider
from .orchestrator import ProviderFactory, tokens


def _events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def check_case(case: dict[str, Any], status: str, answer: str, run_dir: Path) -> list[dict[str, Any]]:
    events = _events(run_dir)
    subagents = sum(1 for e in events if e["type"] == "agent_spawned")
    actions = sum(1 for e in events if e["type"] == "action_proposed")
    tool_errors = sum(1 for e in events if e["type"] == "tool_call_ended" and e["data"].get("is_error"))
    text = answer.lower()
    checks = [{"check": "status", "ok": status in case.get("status", ["completed"]), "detail": status}]
    if "category" in case:
        # Catégorie rendue par le classifieur, avant toute requalification par l'agent principal.
        expected = case["category"] if isinstance(case["category"], list) else [case["category"]]
        found = next((e["data"].get("id") for e in events if e["type"] == "request_classified"), None)
        checks.append({"check": f"catégorie {' ou '.join(expected)}", "ok": found in expected,
                       "detail": found, "kind": "category"})
    for s in case.get("must_mention", []):
        checks.append({"check": f"mentionne « {s} »", "ok": s.lower() in text})
    for s in case.get("must_not_mention", []):
        checks.append({"check": f"ne mentionne pas « {s} »", "ok": s.lower() not in text})
    if "min_subagents" in case:
        checks.append({"check": f"≥ {case['min_subagents']} sous-agents", "ok": subagents >= case["min_subagents"],
                       "detail": subagents})
    if "max_subagents" in case:
        checks.append({"check": f"≤ {case['max_subagents']} sous-agents", "ok": subagents <= case["max_subagents"],
                       "detail": subagents})
    if "min_actions" in case:
        checks.append({"check": f"≥ {case['min_actions']} action(s)", "ok": actions >= case["min_actions"],
                       "detail": actions})
    if "max_tool_errors" in case:
        checks.append({"check": f"≤ {case['max_tool_errors']} erreurs d'outil",
                       "ok": tool_errors <= case["max_tool_errors"], "detail": tool_errors})
    return checks


async def run_eval(cases_path: Path, providers: ProviderFactory | None = None,
                   only: list[str] | None = None, out_dir: Path | None = None, repeat: int = 1) -> dict[str, Any]:
    """repeat > 1 joue chaque cas plusieurs fois : avec un modèle local, un seul passage ne dit pas grand-chose
    (le même code a donné 7 puis 4 cas réussis sur 9). Le résumé donne alors un taux de réussite par cas."""
    from .cli import ask

    spec = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    defaults = spec.get("defaults", {})
    results = []
    saved = {k: os.environ.get(k) for k in ("DIAGAGENT_NOW",)}
    try:
        for case in spec["cases"]:
            if only and case["id"] not in only:
                continue
            case = {**defaults, **case}
            _set_env("DIAGAGENT_NOW", case.get("now"))
            # sources: du cas (demo, maison, demo,maison) ; l'ancien demo: false vaut « maison ».
            sources = case.get("sources") or ("maison" if case.get("demo") is False else None)
            catalog.load_catalog.cache_clear()
            for attempt in range(1, max(1, repeat) + 1):
                started = time.monotonic()
                log, status, answer = await ask(case["question"], providers=providers, user="eval", sources=sources)
                checks = check_case(case, status, answer, log.dir)
                results.append({"id": case["id"], "attempt": attempt, "question": case["question"],
                                "run_id": log.run_id, "passed": all(c["ok"] for c in checks), "checks": checks,
                                "duration_s": round(time.monotonic() - started, 1),
                                "usage": log.manifest.get("usage", {}),
                                "models_profile": log.manifest.get("models_profile")})
    finally:
        for k, v in saved.items():
            _set_env(k, v)
        catalog.load_catalog.cache_clear()
    summary = {"cases": len(results), "passed": sum(r["passed"] for r in results),
               "tokens": sum(tokens(r["usage"]) for r in results),
               "duration_s": round(sum(r["duration_s"] for r in results), 1),
               "models_profile": next((r["models_profile"] for r in results), None)}
    if repeat > 1:
        rates: dict[str, list[bool]] = {}
        for r in results:
            rates.setdefault(r["id"], []).append(r["passed"])
        summary["repeat"] = repeat
        summary["pass_rate"] = {k: f"{sum(v)}/{len(v)}" for k, v in rates.items()}
    category_checks = [c for r in results for c in r["checks"] if c.get("kind") == "category"]
    if category_checks:
        summary["categories"] = {"cases": len(category_checks), "correct": sum(c["ok"] for c in category_checks)}
    report = {"date": datetime.now(timezone.utc).isoformat(), "cases_file": str(cases_path),
              "summary": summary, "results": results}
    out = out_dir or catalog.home() / "eval" / "results"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / f"{stamp}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["path"] = str(out / f"{stamp}.json")
    return report


def _set_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


def find_run(run_id: str) -> Path:
    poc = yaml.safe_load((catalog.home() / "config" / "poc.yaml").read_text(encoding="utf-8"))
    path = catalog.runs_dir(poc) / run_id[0:4] / run_id[4:6] / run_id[6:8] / run_id
    if not (path / "manifest.json").exists():
        raise FileNotFoundError(f"Investigation introuvable : {run_id}")
    return path


def compare_calls(original: Path, replayed: Path) -> list[dict[str, Any]]:
    """Appels d'outils dont le résultat diffère entre l'investigation d'origine et son rejeu."""
    diffs = []
    for orig in sorted(original.glob("**/calls/*.json")):
        ref = orig.relative_to(original)
        new = replayed / ref
        if not new.exists():
            diffs.append({"ref": str(ref), "difference": "appel absent du rejeu"})
            continue
        a, b = json.loads(orig.read_text(encoding="utf-8")), json.loads(new.read_text(encoding="utf-8"))
        if a["input"] != b["input"]:
            diffs.append({"ref": str(ref), "difference": "entrée différente"})
        elif a["is_error"] != b["is_error"] or a["output"] != b["output"]:
            diffs.append({"ref": str(ref), "tool": a["tool"], "difference": "résultat différent"})
    return diffs


async def replay_run(run_id: str) -> dict[str, Any]:
    from .cli import ask

    original = find_run(run_id)
    manifest = json.loads((original / "manifest.json").read_text(encoding="utf-8"))
    provider = ReplayProvider(original)
    saved = os.environ.get("DIAGAGENT_NOW")
    os.environ["DIAGAGENT_NOW"] = manifest.get("reference_time") or manifest["started_at"]
    try:
        # La catégorie d'origine est imposée : le classifieur n'est pas rejoué, seules les décisions
        # de l'agent principal et des sous-agents le sont.
        log, status, _ = await ask(manifest["question"], providers=lambda role: (provider, {}), user="replay",
                                   category=(manifest.get("category") or {}).get("id"))
    finally:
        _set_env("DIAGAGENT_NOW", saved)
    return {"original": run_id, "replay": log.run_id, "status": status, "original_status": manifest["status"],
            "unused_responses": provider.remaining(), "differences": compare_calls(original, log.dir)}
