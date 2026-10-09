"""Agent d'apprentissage : propose des évolutions de catégories et de playbooks, jamais ne les applique
seul (document d'architecture, « Évolution des catégories : apprentissage »).

1. collect : investigations de la période, corrections de catégorie, avis sur les diagnostics, cas
   confirmés, correspondances des catégories en observation.
2. propose : propositions mécaniques (exemples tirés des corrections, activation d'une catégorie en
   observation assez sollicitée) et, si un modèle est fourni, propositions rédigées par le modèle
   (nouvelle catégorie, hypothèses, description).
3. replay : chaque proposition est rejouée sur les demandes de référence (cas du jeu d'évaluation avec
   une catégorie, demandes confirmées) ; elle n'est présentée que si la justesse de catégorisation ne
   baisse pas. La justesse des diagnostics n'est pas rejouée dans le POC (coût d'une investigation
   complète par demande).
4. decide : un Superviseur accepte ou rejette ; la décision est tracée et le playbook précédent gardé.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from . import catalog, knowledge, playbooks
from .llm import LLMProvider, LLMRequest, Message
from .runlog import _append, _ts

ACTIVATE_AFTER = 3  # correspondances observées avant de proposer l'activation d'une catégorie draft
STATUSES = ("pending", "discarded", "accepted", "rejected")


def proposals_dir() -> Path:
    return playbooks.playbooks_dir() / "proposals"


# 1. Collecte

def collect(runs_dir: Path, days: int = 7) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    index = knowledge._read_jsonl(runs_dir / "index.jsonl")
    runs = []
    for r in index:
        if datetime.fromisoformat(r["started_at"].replace("Z", "+00:00")) < since:
            continue
        manifest_path = runs_dir / r["path"] / "manifest.json"
        category = json.loads(manifest_path.read_text(encoding="utf-8")).get("category") or {} \
            if manifest_path.exists() else {}
        runs.append({"run_id": r["run_id"], "question": r["question"], "category": category.get("id"),
                     "confidence": category.get("confidence"), "draft_match": category.get("draft_match")})
    ids = {r["run_id"] for r in runs}
    corrections = [c for c in knowledge.category_corrections(runs_dir).values() if c["run_id"] in ids]
    feedback = [f for f in knowledge.diagnostic_feedback(runs_dir).values() if f["run_id"] in ids]
    return {
        "since": since.isoformat(), "runs": runs, "corrections": corrections, "feedback": feedback,
        "unclassified": [r for r in runs if r["category"] == playbooks.FALLBACK or r["confidence"] == "low"],
        "cases": knowledge.cases(),
        "draft_matches": _count(r["draft_match"] for r in runs if r["draft_match"]),
    }


def _count(items: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


# 2. Propositions

def mechanical_proposals(signals: dict[str, Any], books: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    by_target: dict[str, list[dict[str, Any]]] = {}
    for c in signals["corrections"]:
        if c["to"] in books and c["question"] not in (books[c["to"]].get("examples") or []):
            by_target.setdefault(c["to"], []).append(c)
    for target, items in by_target.items():
        froms = ", ".join(sorted({i["from"] or "?" for i in items}))
        out.append({
            "kind": "add_examples", "target": target,
            "rationale": f"{len(items)} demande(s) classée(s) {froms} corrigée(s) en {target} par les utilisateurs.",
            "evidence": [i["run_id"] for i in items],
            "change": {"examples": list(dict.fromkeys(i["question"] for i in items))[:5]}})
    for draft, n in signals["draft_matches"].items():
        if draft in books and books[draft]["status"] == "draft" and n >= ACTIVATE_AFTER:
            out.append({"kind": "activate", "target": draft,
                        "rationale": f"La catégorie en observation {draft} aurait capté {n} demande(s).",
                        "evidence": [r["run_id"] for r in signals["runs"] if r["draft_match"] == draft],
                        "change": {}})
    return out


LEARNER_SYSTEM = """Tu améliores les catégories et les playbooks d'un agent de diagnostic de production.
Tu proposes, un humain valide. Ne propose que ce que les données justifient, avec leurs identifiants.

Réponds uniquement par un objet JSON : {"proposals": [ ... ]}, chaque proposition étant l'une de :
- {"kind": "new_category", "target": "<id-en-minuscules>", "rationale": "...", "evidence": ["<run_id>"],
   "change": {"playbook": {"id": "<id>", "description": "...", "examples": ["..."],
     "required_entities": {}, "hypotheses": [{"id": "...", "signal": "..."}],
     "steps": [{"name": "...", "parallel": [{"role": "<rôle>", "objective": "..."}]}],
     "stop_when": ["..."], "requalify": {}, "output": ["synthese"], "owner": "..."}}}
  quand plusieurs demandes semblables restent classées autre ou avec une confiance faible ;
- {"kind": "add_hypotheses", "target": "<catégorie>", "rationale": "...", "evidence": ["<id de cas>"],
   "change": {"hypotheses": [{"id": "...", "signal": "..."}]}}
  quand des cas confirmés montrent une cause qui n'est pas parmi les hypothèses du playbook ;
- {"kind": "update_description", "target": "<catégorie>", "rationale": "...", "evidence": ["<run_id>"],
   "change": {"description": "..."}}
  quand des corrections montrent une confusion récurrente entre deux catégories.
Rôles de sous-agents disponibles : {roles}. Si rien n'est justifié : {"proposals": []}.
"""


def model_proposals(provider: LLMProvider, signals: dict[str, Any], books: dict[str, dict[str, Any]],
                    roles: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Propositions rédigées par le modèle, validées mécaniquement ; rend aussi les rejets motivés."""
    summary = {
        "categories": {k: {"status": b["status"], "description": " ".join(b["description"].split()),
                           "hypotheses": [h["id"] for h in b.get("hypotheses") or []]} for k, b in books.items()},
        "non_classees": [{"run_id": r["run_id"], "question": r["question"]} for r in signals["unclassified"]],
        "corrections": [{k: c[k] for k in ("run_id", "question", "from", "to")} for c in signals["corrections"]],
        "cas_confirmes": [{k: c.get(k) for k in ("id", "category", "cause")} for c in signals["cases"]],
        "avis_faux": [{k: f.get(k) for k in ("run_id", "question", "category", "cause")}
                      for f in signals["feedback"] if f["verdict"] == "faux"],
    }
    request = LLMRequest(system=LEARNER_SYSTEM.replace("{roles}", ", ".join(sorted(roles))),
                         messages=[Message("user", json.dumps(summary, ensure_ascii=False, indent=1))],
                         max_tokens=6000)
    response = provider.complete(request)
    match = re.search(r"\{.*\}", response.text or "", re.S)
    if not match:
        return [], ["réponse du modèle sans JSON"]
    try:
        raw = json.loads(match.group(0)).get("proposals") or []
    except json.JSONDecodeError as e:
        return [], [f"JSON illisible : {e}"]
    kept, dropped = [], []
    for p in raw:
        try:
            kept.append(_check_proposal(p, books, roles))
        except (playbooks.PlaybookError, KeyError, TypeError, ValueError) as e:
            dropped.append(f"{p.get('kind')}/{p.get('target')} : {e}")
    return kept, dropped


def _check_proposal(p: dict[str, Any], books: dict[str, dict[str, Any]], roles: set[str]) -> dict[str, Any]:
    kind, target = p["kind"], p["target"]
    if kind not in ("new_category", "add_hypotheses", "update_description"):
        raise ValueError(f"kind non autorisé pour le modèle : {kind}")
    if kind == "new_category":
        if target in books or not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", target):
            raise ValueError("id de catégorie déjà pris ou invalide")
        book = {**p["change"]["playbook"], "id": target, "version": 1, "status": "draft"}
        playbooks.validate(book, roles=roles)
    elif target not in books:
        raise ValueError("catégorie cible inconnue")
    elif kind == "add_hypotheses":
        if not all(h.get("id") and h.get("signal") for h in p["change"]["hypotheses"]):
            raise ValueError("chaque hypothèse a un id et un signal")
    elif not str(p["change"].get("description", "")).strip():
        raise ValueError("description vide")
    return {"kind": kind, "target": target, "rationale": str(p.get("rationale", "")),
            "evidence": [str(e) for e in p.get("evidence") or []], "change": p["change"]}


# 3. Rejeu sur les demandes de référence

def reference_requests(runs_dir: Path, cases_path: Path | None = None) -> list[dict[str, Any]]:
    cases_path = cases_path or catalog.home() / "eval" / "cases.yaml"
    refs = []
    if cases_path.exists():
        spec = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
        for c in spec.get("cases", []):
            if "category" in c:
                expected = c["category"] if isinstance(c["category"], list) else [c["category"]]
                refs.append({"question": c["question"], "expected": expected, "source": f"eval:{c['id']}"})
    for r in knowledge.confirmed_requests(runs_dir):
        refs.append({"question": r["question"], "expected": [r["category"]], "source": "confirmée"})
    return refs


def classification_score(provider: LLMProvider, books: dict[str, dict[str, Any]],
                         refs: list[dict[str, Any]]) -> dict[str, Any]:
    details = []
    for ref in refs:
        c, _ = playbooks.classify(provider, ref["question"], books)
        details.append({"question": ref["question"], "expected": ref["expected"], "got": c.category,
                        "draft_match": c.draft_match, "ok": c.category in ref["expected"]})
    return {"cases": len(details), "correct": sum(d["ok"] for d in details), "details": details}


def books_after(books: dict[str, dict[str, Any]], proposal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    after = dict(books)
    after[proposal["target"]] = playbooks.apply_change(books.get(proposal["target"]), proposal["kind"],
                                                        proposal["change"])
    return after


# Écriture et décision

def write_proposal(p: dict[str, Any]) -> Path:
    pdir = proposals_dir()
    pdir.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now(timezone.utc):%Y-%m-%d}-{p['kind']}-{p['target']}"
    path, n = pdir / f"{stem}.yaml", 2
    while path.exists():
        path, n = pdir / f"{stem}-{n}.yaml", n + 1
    p = {"id": path.stem, **p}
    path.write_text(yaml.safe_dump(p, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    return path


def list_proposals() -> list[dict[str, Any]]:
    if not proposals_dir().exists():
        return []
    return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(proposals_dir().glob("*.yaml"))]


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["kind"], a["target"], a["change"]) == (b["kind"], b["target"], b["change"])


def learn(runs_dir: Path, days: int = 7, drafter: LLMProvider | None = None,
          classifier: LLMProvider | None = None, roles: set[str] | None = None,
          log: Callable[[str], None] = lambda _: None) -> list[dict[str, Any]]:
    """Un passage de l'agent d'apprentissage ; rend les propositions écrites."""
    books = playbooks.load_playbooks(include=("active", "draft"))
    signals = collect(runs_dir, days)
    log(f"{len(signals['runs'])} investigation(s), {len(signals['corrections'])} correction(s), "
        f"{len(signals['feedback'])} avis, {len(signals['cases'])} cas, {len(signals['unclassified'])} non classée(s)")
    candidates = mechanical_proposals(signals, books)
    if drafter is not None:
        drafted, dropped = model_proposals(drafter, signals, books, roles or set())
        candidates += drafted
        for d in dropped:
            log(f"proposition du modèle écartée : {d}")
    existing = [p for p in list_proposals() if p["status"] in ("pending", "accepted")]
    candidates = [c for c in candidates if not any(_same(c, e) for e in existing)]
    written = []
    refs = reference_requests(runs_dir) if classifier is not None and candidates else []
    before = classification_score(classifier, books, refs) if refs else None
    for c in candidates:
        proposal = {"created_at": _ts(), "status": "pending", **c, "replay": None, "decision": None}
        if before is not None:
            after = classification_score(classifier, books_after(books, c), refs)
            ok = after["correct"] >= before["correct"]
            proposal["replay"] = {"cases": before["cases"], "before": before["correct"], "after": after["correct"],
                                  "ok": ok, "details": after["details"]}
            if not ok:
                proposal["status"] = "discarded"
        path = write_proposal(proposal)
        log(f"{proposal['status']:<9} {path.name}")
        written.append(yaml.safe_load(path.read_text(encoding="utf-8")))
    return written


def decide(proposal_id: str, accept: bool, by: str, comment: str = "",
           roles: set[str] | None = None) -> dict[str, Any]:
    path = proposals_dir() / f"{proposal_id}.yaml"
    if not re.fullmatch(r"[\w.-]+", proposal_id) or not path.exists():
        raise KeyError(f"Proposition inconnue : {proposal_id}")
    p = yaml.safe_load(path.read_text(encoding="utf-8"))
    if p["status"] != "pending":
        raise ValueError(f"Proposition déjà {p['status']}")
    if accept:
        books = playbooks.load_playbooks(include=playbooks.STATUSES)
        new = playbooks.apply_change(books.get(p["target"]), p["kind"], p["change"])
        playbooks.save_playbook(new, roles=roles)
        p["applied_version"] = new["version"]
    p["status"] = "accepted" if accept else "rejected"
    p["decision"] = {"by": by, "at": _ts(), "comment": comment}
    path.write_text(yaml.safe_dump(p, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    _append(proposals_dir() / "decisions.jsonl", {"proposal": proposal_id, "status": p["status"],
                                                  "target": p["target"], "kind": p["kind"], **p["decision"]})
    return p


# Indicateurs par catégorie (écran Administration)

def indicators(runs_dir: Path) -> dict[str, Any]:
    index = [r for r in knowledge._read_jsonl(runs_dir / "index.jsonl") if r.get("user") not in ("eval", "replay")]
    corrections = knowledge.category_corrections(runs_dir)
    feedback = knowledge.diagnostic_feedback(runs_dir)
    total = len(index)
    rows: dict[str, dict[str, Any]] = {}
    for r in index:
        cat = r.get("category") or "?"
        row = rows.setdefault(cat, {"category": cat, "runs": 0, "corrected": 0, "feedback": 0, "useful": 0,
                                    "duration_s": 0.0, "tool_calls": 0})
        row["runs"] += 1
        row["corrected"] += r["run_id"] in corrections
        if r["run_id"] in feedback:
            row["feedback"] += 1
            row["useful"] += feedback[r["run_id"]]["verdict"] == "utile"
        if r.get("ended_at"):
            started = datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))
            ended = datetime.fromisoformat(r["ended_at"].replace("Z", "+00:00"))
            row["duration_s"] += (ended - started).total_seconds()
        row["tool_calls"] += r.get("tool_calls") or 0
    out = []
    for row in sorted(rows.values(), key=lambda x: -x["runs"]):
        n = row["runs"]
        out.append({"category": row["category"], "runs": n, "share": round(n / total, 3) if total else 0,
                    "corrected_share": round(row["corrected"] / n, 3),
                    "useful_share": round(row["useful"] / row["feedback"], 3) if row["feedback"] else None,
                    "feedback": row["feedback"], "avg_duration_s": round(row["duration_s"] / n, 1),
                    "avg_tool_calls": round(row["tool_calls"] / n, 1)})
    autre = rows.get(playbooks.FALLBACK, {}).get("runs", 0)
    return {"runs": total, "autre_share": round(autre / total, 3) if total else 0, "categories": out,
            "draft_matches": _count(r["draft_match"] for r in index if r.get("draft_match"))}
