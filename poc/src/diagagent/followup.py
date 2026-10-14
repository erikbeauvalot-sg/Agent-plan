"""Question de suivi (document d'architecture, « Conversation ») : une nouvelle investigation liée à la
précédente (`follow_up_of`). L'agent principal reçoit la question d'origine, sa synthèse et les rapports
des sous-agents, plafonnés en taille ; la trace de l'investigation d'origine n'est jamais modifiée."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_ANSWER_CHARS = 6_000
MAX_REPORTS_CHARS = 6_000
MAX_CHAIN = 3  # questions précédentes rappelées quand le suivi porte sur un suivi


def run_dir(runs_dir: Path, run_id: str) -> Path:
    return runs_dir / run_id[0:4] / run_id[4:6] / run_id[6:8] / run_id


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _cut(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n[… tronqué]"


def chain(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    """Investigations du fil, de la plus ancienne à celle-ci (manifests), en remontant follow_up_of."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = run_id
    while current and current not in seen and len(out) < 20:
        seen.add(current)
        manifest = run_dir(runs_dir, current) / "manifest.json"
        if not manifest.exists():
            break
        data = json.loads(manifest.read_text(encoding="utf-8"))
        out.append(data)
        current = data.get("follow_up_of")
    return list(reversed(out))


def context(runs_dir: Path, run_id: str) -> dict[str, str]:
    """Contexte d'une question de suivi : `lead` pour l'agent principal (question, synthèse, rapports),
    `previous` (la question d'origine) pour aider le classifieur à comprendre une question elliptique."""
    path = run_dir(runs_dir, run_id)
    manifest = json.loads(_read(path / "manifest.json") or "{}")
    if not manifest:
        raise ValueError(f"Investigation d'origine inconnue : {run_id}")
    earlier = [m["question"] for m in chain(runs_dir, run_id)[:-1]][-MAX_CHAIN:]
    reports, used = [], 0
    for report in sorted((path / "subagents").glob("*/report.json")):
        data = json.loads(report.read_text(encoding="utf-8"))
        facts = "; ".join(str(f.get("fact", f)) if isinstance(f, dict) else str(f) for f in data.get("findings") or [])
        line = f"- {report.parent.name} ({data.get('status')}) : {data.get('summary', '')}" + (
            f" Faits : {facts}" if facts else "")
        if used + len(line) > MAX_REPORTS_CHARS:
            reports.append(f"- [{len(list((path / 'subagents').glob('*/report.json'))) - len(reports)} rapport(s) "
                           f"non repris faute de place : voir {run_id}]")
            break
        reports.append(line)
        used += len(line)
    parts = [f"# Contexte : question de suivi de l'investigation {run_id}"]
    if earlier:
        parts.append("Questions précédentes du fil : " + " → ".join(f"« {q} »" for q in earlier))
    parts += [f"Question d'origine ({manifest.get('started_at', '')[:16]}, {manifest.get('status')}) : "
              f"« {manifest['question']} »",
              "## Synthèse rendue", _cut(_read(path / "analysis.md"), MAX_ANSWER_CHARS) or "(aucune synthèse)"]
    if reports:
        parts += ["## Rapports des sous-agents", "\n".join(reports)]
    parts.append("Appuie-toi sur ce contexte sans le refaire : ne réinterroge les sources que pour ce que la "
                 "nouvelle question demande, ou pour vérifier un point douteux. Les preuves de l'investigation "
                 "d'origine ne sont pas citables ici (query_ref d'une autre trace) : cite-les par leur contenu.")
    return {"lead": "\n\n".join(parts), "previous": manifest["question"]}
