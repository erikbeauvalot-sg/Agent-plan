"""Catégorisation des demandes et playbooks (document d'architecture, sections « Catégorisation des
demandes » et « Playbooks »).

Une catégorie = un fichier playbooks/<categorie>.yaml. Le classifieur est un appel au modèle séparé,
avant l'agent principal : il reçoit la description et les exemples de chaque catégorie active et rend
une sortie structurée. La décision (playbook appliqué, deux playbooks combinés, question de précision,
`autre`) est mécanique et tracée ; le playbook retenu est injecté dans le prompt de l'agent principal.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import catalog
from .llm import LLMProvider, LLMRequest, Message

STATUSES = ("active", "draft", "retired")
CONFIDENCES = ("low", "medium", "high")
FALLBACK = "autre"
REQUIRED_KEYS = ("id", "version", "status", "description", "steps", "stop_when", "output", "owner")


class PlaybookError(ValueError):
    pass


def load_playbooks(include: tuple[str, ...] = ("active",)) -> dict[str, dict[str, Any]]:
    """Playbooks par id, dans l'ordre des fichiers ; `include` filtre sur le statut."""
    books = {}
    for path in sorted((catalog.home() / "playbooks").glob("*.yaml")):
        book = yaml.safe_load(path.read_text(encoding="utf-8"))
        validate(book, path.stem)
        if book["status"] in include:
            books[book["id"]] = book
    if FALLBACK not in books and "active" in include:
        raise PlaybookError(f"Le playbook {FALLBACK} est obligatoire et doit être actif")
    return books


def validate(book: dict[str, Any], stem: str | None = None, roles: set[str] | None = None) -> None:
    missing = [k for k in REQUIRED_KEYS if k not in book]
    if missing:
        raise PlaybookError(f"{stem or book.get('id')} : champs manquants {', '.join(missing)}")
    if stem and book["id"] != stem:
        raise PlaybookError(f"{stem}.yaml : id {book['id']!r} différent du nom du fichier")
    if book["status"] not in STATUSES:
        raise PlaybookError(f"{book['id']} : status doit valoir {', '.join(STATUSES)}")
    for step in book["steps"]:
        if "name" not in step or not (step.get("parallel") or step.get("direct")):
            raise PlaybookError(f"{book['id']} : chaque étape a un name et des investigations (parallel) "
                                f"ou une consigne (direct)")
        for inv in step.get("parallel", []):
            if not inv.get("role") or not inv.get("objective"):
                raise PlaybookError(f"{book['id']}/{step['name']} : role et objective obligatoires")
            if roles is not None and inv["role"] not in roles:
                raise PlaybookError(f"{book['id']}/{step['name']} : rôle inconnu {inv['role']}")
    for target in book.get("requalify") or {}:
        if not (catalog.home() / "playbooks" / f"{target}.yaml").exists():
            raise PlaybookError(f"{book['id']} : requalify vers une catégorie inconnue {target}")


# Classification

@dataclass
class Classification:
    category: str
    confidence: str
    alternative: str | None = None
    entities: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    choices: list[str] = field(default_factory=list)
    reason: str = ""
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", [], {})}


@dataclass
class Decision:
    """Ce que l'orchestrateur fait de la classification."""
    mode: str  # playbook | combined | clarify | generic
    categories: list[str]
    clarification: str | None = None


CLASSIFIER_SYSTEM = """Tu classes les demandes adressées à un agent de diagnostic de production.

# Catégories
{categories}

# Sortie
Réponds uniquement par un objet JSON, sans texte autour :
{{"category": "<id>", "confidence": "low|medium|high", "alternative": "<id ou null>",
  "entities": {{"host": "...", "service": "...", "ticket": "...", "change": "...", "period": "..."}},
  "missing": ["<entité indispensable absente de la demande>"],
  "choices": ["<valeurs possibles pour l'entité manquante, si tu en connais>"],
  "reason": "<une phrase>"}}

- category : la catégorie qui décrit le mieux la demande ; {fallback} si aucune ne convient.
- alternative : une deuxième catégorie seulement si elle est presque aussi plausible.
- entities : seulement les entités écrites dans la demande, sans rien deviner.
- missing : les entités indispensables de la catégorie (liste « indispensable » ci-dessus) que la
  demande ne permet pas d'identifier. « mon site » sans dire lequel : service manquant.
"""


def classifier_prompt(books: dict[str, dict[str, Any]], similar: list[dict[str, Any]] | None = None) -> str:
    lines = []
    for b in books.values():
        lines.append(f"## {b['id']}\n{' '.join(b['description'].split())}")
        if b.get("examples"):
            lines.append("Exemples : " + " ; ".join(f"« {e} »" for e in b["examples"]))
        if b.get("required_entities"):
            lines.append("Indispensable : " + ", ".join(b["required_entities"]))
    prompt = CLASSIFIER_SYSTEM.format(categories="\n".join(lines), fallback=FALLBACK)
    if similar:
        prompt += "\n# Demandes passées déjà bien classées\n" + "\n".join(
            f"- « {s['question']} » → {s['category']}" for s in similar)
    return prompt


def parse_classification(text: str, books: dict[str, dict[str, Any]]) -> Classification:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise PlaybookError("pas d'objet JSON dans la réponse du classifieur")
    data = json.loads(match.group(0))
    category = data.get("category")
    if category not in books:
        category = FALLBACK
    alternative = data.get("alternative")
    if alternative not in books or alternative == category:
        alternative = None
    confidence = data.get("confidence") if data.get("confidence") in CONFIDENCES else "low"
    entities = {k: str(v) for k, v in (data.get("entities") or {}).items() if v not in (None, "", [])}
    required = books[category].get("required_entities") or {}
    missing = [m for m in data.get("missing") or [] if m in required and m not in entities]
    return Classification(category, confidence, alternative, entities, missing,
                          [str(c) for c in data.get("choices") or []][:6], str(data.get("reason") or ""))


def classify(provider: LLMProvider, question: str, books: dict[str, dict[str, Any]],
             similar: list[dict[str, Any]] | None = None) -> tuple[Classification, Any]:
    """Un appel au modèle ; en cas d'échec, catégorie `autre` avec l'erreur notée. Rend aussi la
    réponse brute pour la trace."""
    request = LLMRequest(system=classifier_prompt(books, similar), messages=[Message("user", question)],
                         max_tokens=2000)
    try:
        response = provider.complete(request)
    except Exception as e:  # le classifieur ne doit jamais bloquer l'investigation
        return Classification(FALLBACK, "low", error=f"{type(e).__name__}: {e}"[:300]), None
    try:
        return parse_classification(response.text, books), response
    except (PlaybookError, json.JSONDecodeError) as e:
        return Classification(FALLBACK, "low", error=f"Réponse illisible : {e}"[:300]), response


def decide(c: Classification, books: dict[str, dict[str, Any]]) -> Decision:
    if c.missing:
        book = books[c.category]
        question = " ".join(book["required_entities"][m] for m in c.missing)
        return Decision("clarify", [c.category], question)
    if c.category == FALLBACK:
        return Decision("generic", [FALLBACK])
    if c.alternative and c.confidence != "high":
        return Decision("combined", [c.category, c.alternative])
    return Decision("playbook", [c.category])


# Rendu pour l'agent principal

def render(book: dict[str, Any], available_roles: set[str]) -> str:
    """Le playbook en Markdown, pour le prompt de l'agent principal. Une investigation dont le rôle
    n'est pas disponible (source absente) est marquée, pour que l'agent la saute en le disant."""
    lines = [f"### Playbook {book['id']} (version {book['version']})", " ".join(book["description"].split())]
    if book.get("hypotheses"):
        lines.append("Hypothèses à tester en priorité :")
        lines += [f"- {h['id']} : {h['signal']}" for h in book["hypotheses"]]
    lines.append("Étapes (les investigations d'une même étape sont lancées en parallèle) :")
    for i, step in enumerate(book["steps"], 1):
        lines.append(f"{i}. {step['name']}")
        if step.get("direct"):
            lines.append(f"   - {step['direct']}")
        for item in step.get("collect", []):
            lines.append(f"   - {item}")
        for inv in step.get("parallel", []):
            sources = f" (sources : {', '.join(inv['sources'])})" if inv.get("sources") else ""
            absent = "" if inv["role"] in available_roles else " — rôle indisponible ici, à sauter"
            lines.append(f"   - [{inv['role']}] {inv['objective']}{sources}{absent}")
    lines.append("Conclure quand : " + " ; ou ".join(book["stop_when"]))
    if book.get("requalify"):
        lines.append("Changer de catégorie (outil requalify) si : " + " ; ".join(
            f"{k} quand {v}" for k, v in book["requalify"].items()))
    lines.append("Rubriques attendues dans la réponse : " + ", ".join(book["output"]))
    return "\n".join(lines)


def lead_section(decision: Decision, c: Classification, books: dict[str, dict[str, Any]],
                 available_roles: set[str]) -> str:
    head = f"Catégorie : {', '.join(decision.categories)} (confiance {c.confidence})."
    if c.entities:
        head += " Entités repérées : " + ", ".join(f"{k} = {v}" for k, v in c.entities.items()) + "."
    if decision.mode == "combined":
        head += (" Deux catégories sont plausibles : commence par les étapes communes aux deux playbooks, "
                 "puis tranche avec les faits et appelle requalify pour retenir la bonne.")
    body = "\n\n".join(render(books[cat], available_roles) for cat in decision.categories)
    return f"{head}\n\n{body}"
