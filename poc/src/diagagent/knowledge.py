"""Base de cas diagnostiqués et retours des utilisateurs (document d'architecture, « Évolution des
catégories : apprentissage »).

Sans base de données : les retours vont dans runs/feedback/*.jsonl, chaque cas confirmé dans
knowledge/cases/<run_id>.yaml, et la recherche se fait sur knowledge/index.jsonl par recouvrement de mots
et d'entités. Les cas servent d'exemples au classifieur, de « déjà vu » à l'agent principal et de
statistiques pour ordonner les hypothèses d'un playbook.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from . import catalog
from .runlog import _append, _dump, _ts

VERDICTS = ("utile", "partiel", "faux")
STOPWORDS = set("""le la les un une des du de d l au aux et ou en sur sous dans par pour pas plus est sont
a ai as ont été etre être que qui quoi quel quelle quels quelles ce cet cette ces mon ma mes ton ta tes son sa
ses notre nos votre vos leur leurs il elle ils elles on je tu nous vous y ne se sa depuis hier soir matin
pourquoi comment combien donne moi infos information informations fait faits ete""".split())
REF = re.compile(r"\[((?:lead|subagents/[^\]/]+)/calls/\d{4}\.json)\]")


def knowledge_dir() -> Path:
    return Path(os.environ.get("DIAGAGENT_KNOWLEDGE_DIR") or catalog.home() / "knowledge")


def feedback_dir(runs_dir: Path) -> Path:
    return runs_dir / "feedback"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def keywords(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9][a-z0-9._-]{2,}", plain)
    return sorted({w for w in words if w not in STOPWORDS})


# Retours des utilisateurs

def record_feedback(run_dir: Path, runs_dir: Path, verdict: str, by: str, cause: str = "",
                    comment: str = "") -> dict[str, Any]:
    """Avis sur un diagnostic (utile, partiel, faux) et cause réelle si on la connaît."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict doit valoir {', '.join(VERDICTS)}")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    feedback = {"verdict": verdict, "cause": cause.strip(), "comment": comment.strip(), "by": by, "at": _ts()}
    manifest["feedback"] = feedback
    _dump(run_dir / "manifest.json", manifest)
    _append(feedback_dir(runs_dir) / "diagnostics.jsonl", {
        "run_id": manifest["run_id"], "question": manifest["question"],
        "category": effective_category(manifest), **feedback})
    return feedback


def effective_category(manifest: dict[str, Any]) -> str | None:
    """Catégorie retenue : la correction de l'utilisateur prime sur la classification."""
    c = manifest.get("category") or {}
    return (c.get("correction") or {}).get("category") or c.get("id")


def category_corrections(runs_dir: Path) -> dict[str, dict[str, Any]]:
    """Dernière correction de catégorie par investigation."""
    return {c["run_id"]: c for c in _read_jsonl(feedback_dir(runs_dir) / "categories.jsonl")}


def diagnostic_feedback(runs_dir: Path) -> dict[str, dict[str, Any]]:
    return {f["run_id"]: f for f in _read_jsonl(feedback_dir(runs_dir) / "diagnostics.jsonl")}


# Base de cas

def create_case(run_dir: Path, by: str, cause: str, resolution: str = "") -> dict[str, Any]:
    """Une investigation dont la cause est confirmée devient un cas réutilisable."""
    if not cause.strip():
        raise ValueError("La cause confirmée est obligatoire pour créer un cas")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    analysis = (run_dir / "analysis.md").read_text(encoding="utf-8") if (run_dir / "analysis.md").exists() else ""
    category = manifest.get("category") or {}
    case = {
        "id": manifest["run_id"], "created_at": _ts(), "confirmed_by": by,
        "symptom": manifest["question"], "category": effective_category(manifest),
        "entities": category.get("entities") or {}, "cause": cause.strip(), "resolution": resolution.strip(),
        "decisive_evidence": sorted(set(REF.findall(analysis)))[:10], "run": manifest["run_id"],
    }
    kdir = knowledge_dir()
    path = kdir / "cases" / f"{case['id']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(case, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _append(kdir / "index.jsonl", {
        "id": case["id"], "category": case["category"], "entities": case["entities"], "cause": case["cause"],
        "keywords": keywords(" ".join([case["symptom"], *case["entities"].values()])), "created_at": case["created_at"]})
    return case


def cases() -> list[dict[str, Any]]:
    """Index des cas ; un cas recréé pour la même investigation remplace le précédent."""
    return list({c["id"]: c for c in _read_jsonl(knowledge_dir() / "index.jsonl")}.values())


def _score(words: set[str], entities: set[str], other_words: set[str], other_entities: set[str]) -> int:
    return len(words & other_words) + 3 * len(entities & other_entities)


def similar_cases(question: str, entities: dict[str, str] | None = None, k: int = 3) -> list[dict[str, Any]]:
    words = set(keywords(question))
    ents = {v.lower() for v in (entities or {}).values()}
    scored = []
    for c in cases():
        score = _score(words, ents, set(c.get("keywords", [])), {v.lower() for v in c.get("entities", {}).values()})
        if score >= 2:
            scored.append((score, c))
    return [c for _, c in sorted(scored, key=lambda x: -x[0])[:k]]


def confirmed_requests(runs_dir: Path) -> list[dict[str, Any]]:
    """Demandes passées dont la catégorie est confirmée : corrigée par un utilisateur, ou dont le
    diagnostic a été jugé utile ou partiel sans correction."""
    out = {rid: {"question": c["question"], "category": c["to"]} for rid, c in category_corrections(runs_dir).items()}
    for rid, f in diagnostic_feedback(runs_dir).items():
        if rid not in out and f["verdict"] in ("utile", "partiel") and f.get("category"):
            out[rid] = {"question": f["question"], "category": f["category"]}
    return list(out.values())


def similar_requests(question: str, runs_dir: Path, k: int = 5) -> list[dict[str, Any]]:
    words = set(keywords(question))
    scored = [(len(words & set(keywords(r["question"]))), r) for r in confirmed_requests(runs_dir)]
    return [r for s, r in sorted(scored, key=lambda x: -x[0]) if s >= 1][:k]


def render_cases(found: list[dict[str, Any]]) -> str:
    if not found:
        return ""
    lines = ["Cas déjà vus, confirmés par un humain (à vérifier, jamais à recopier sans preuve) :"]
    for c in found:
        ents = ", ".join(f"{k} = {v}" for k, v in c.get("entities", {}).items())
        lines.append(f"- {c['id']} [{c.get('category')}] {ents} : cause {c['cause']}")
    return "\n".join(lines)
