"""Catégorisation des demandes et playbooks (document d'architecture, sections « Catégorisation des
demandes » et « Playbooks »).

Une catégorie = un fichier playbooks/<categorie>.yaml. Le classifieur est un appel au modèle séparé,
avant l'agent principal : il reçoit la description et les exemples de chaque catégorie active et rend
une sortie structurée. La décision (playbook appliqué, deux playbooks combinés, question de précision,
`autre`) est mécanique et tracée ; le playbook retenu est injecté dans le prompt de l'agent principal.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import catalog
from .llm import LLMProvider, LLMRequest, Message

STATUSES = ("active", "draft", "retired")
CONFIDENCES = ("low", "medium", "high")
FALLBACK = "autre"
# Une entité indispensable peut être donnée sous une autre forme : un host nommé désigne le composant
# en cause (« la latence de srv-pay-01 »), comme le ferait un service.
ENTITY_ALIASES = {"service": ("host", "ci")}
GENERIC_NAMES = {"site", "site web", "site internet", "application", "appli", "app", "application web",
                 "service", "serveur", "outil", "logiciel", "système", "plateforme", "réseau", "base",
                 "base de données", "appli web", "programme"}
REQUIRED_KEYS = ("id", "version", "status", "description", "steps", "stop_when", "output", "owner")


class PlaybookError(ValueError):
    pass


def playbooks_dir() -> Path:
    return Path(os.environ.get("DIAGAGENT_PLAYBOOKS_DIR") or catalog.home() / "playbooks")


def load_playbooks(include: tuple[str, ...] = ("active",)) -> dict[str, dict[str, Any]]:
    """Playbooks par id, dans l'ordre des fichiers ; `include` filtre sur le statut."""
    books = {}
    for path in sorted(playbooks_dir().glob("*.yaml")):
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
        if not (playbooks_dir() / f"{target}.yaml").exists():
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
    draft_match: str | None = None

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
  Une question factuelle à réponse courte (priorité, statut ou résolution d'un ticket, heure d'une
  alerte, valeur d'une métrique, propriétaire) est information, même si elle cite un numéro INC ou une
  alerte : analyser, expliquer ou chercher une cause, c'est une autre catégorie.
- alternative : une deuxième catégorie seulement si elle est presque aussi plausible.
- entities : seulement les entités écrites dans la demande, sans rien deviner.
- missing : les entités indispensables de la catégorie (liste « indispensable » ci-dessus) que la
  demande ne permet pas d'identifier. « mon site » sans dire lequel : service manquant.
"""


def classifier_prompt(books: dict[str, dict[str, Any]], similar: list[dict[str, Any]] | None = None) -> str:
    lines = []
    for b in books.values():
        draft = " (catégorie en observation)" if b["status"] == "draft" else ""
        lines.append(f"## {b['id']}{draft}\n{' '.join(b['description'].split())}")
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
    """Une catégorie `draft` (en observation) n'est jamais appliquée : elle est notée dans draft_match
    et la demande suit la deuxième catégorie si elle est active, sinon `autre`."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise PlaybookError("pas d'objet JSON dans la réponse du classifieur")
    data = lenient_json(match.group(0))
    active = {k for k, b in books.items() if b["status"] == "active"}
    category, alternative = _known(data.get("category"), books), _known(data.get("alternative"), books)
    draft_match = None
    if category in books and category not in active:
        draft_match = category
        category = alternative if alternative in active else FALLBACK
        alternative = None
    if category not in active:
        category = FALLBACK
    if alternative not in active or alternative == category:
        alternative = None
    confidence = data.get("confidence") if data.get("confidence") in CONFIDENCES else "low"
    entities = {k: str(v) for k, v in (data.get("entities") or {}).items() if v not in (None, "", [])}
    required = books[category].get("required_entities") or {}
    # « Mon site web » n'identifie rien : l'entité est écartée, et manquante si la catégorie l'exige.
    vague = [k for k, v in entities.items() if is_vague(v)]
    for k in vague:
        del entities[k]

    def present(m: str) -> bool:
        return m in entities or any(a in entities for a in ENTITY_ALIASES.get(m, ()))

    missing = [m for m in dict.fromkeys([*(data.get("missing") or []), *vague]) if m in required and not present(m)]
    return Classification(category, confidence, alternative, entities, missing,
                          [str(c) for c in data.get("choices") or []][:6], str(data.get("reason") or ""),
                          draft_match=draft_match)


def lenient_json(text: str) -> dict[str, Any]:
    """Objet JSON du classifieur, même un peu abîmé : gpt-oss écrit \\' dans une chaîne, ou oublie le
    guillemet qui ferme la dernière (« …non précisé.} »). Les champs utiles sont alors relevés un à un ;
    seule une réponse sans catégorie reste illisible."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as first:
        try:
            return json.loads(text.replace("\\'", "'"))
        except json.JSONDecodeError:
            pass
        data: dict[str, Any] = {}
        for key in ("category", "confidence", "alternative", "reason"):
            if m := re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)', text):
                data[key] = m.group(1)
        for key, pattern in (("entities", r"\{[^{}]*\}"), ("missing", r"\[[^\[\]]*\]"), ("choices", r"\[[^\[\]]*\]")):
            if m := re.search(rf'"{key}"\s*:\s*({pattern})', text):
                try:
                    data[key] = json.loads(m.group(1).replace("\\'", "'"))
                except json.JSONDecodeError:
                    pass
        if "category" not in data:
            raise first
        return data


def is_vague(value: str) -> bool:
    """Nom générique, sans rien qui désigne un objet précis : « mon site web », « l'application »."""
    words = re.sub(r"\b(?:mon|ma|mes|notre|nos|votre|vos|le|la|les|l'|un|une|des|ce|cet|cette)\s*", " ",
                   value.strip().lower().replace("’", "'"))
    return " ".join(words.split()) in GENERIC_NAMES


def _known(value: Any, books: dict[str, dict[str, Any]]) -> Any:
    """Rapproche un identifiant presque exact (« analysis-evenement ») de la catégorie existante : une
    coquille du modèle ne doit pas envoyer la demande dans `autre`."""
    if not isinstance(value, str) or value in books:
        return value
    close = difflib.get_close_matches(value.strip().lower(), list(books), n=1, cutoff=0.85)
    return close[0] if close else value


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


IDENTIFIERS = {"ticket": r"\bINC\d{7}\b", "change": r"\bCHG\d{7}\b"}
ALERT_CATEGORY = "analyse-evenement"


def named_alert(question: str, alert_names: set[str] | frozenset[str]) -> str | None:
    """Nom d'alerte connue écrit tel quel dans la demande (le plus long si plusieurs se recouvrent)."""
    return next((n for n in sorted(alert_names, key=len, reverse=True)
                 if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", question)), None)


def alert_fallback(c: Classification, question: str, alert_names: set[str] | frozenset[str],
                   books: dict[str, dict[str, Any]]) -> Classification:
    """Une demande classée `autre` qui nomme une alerte connue est une analyse d'événement."""
    alert = named_alert(question, alert_names)
    if c.category != FALLBACK or not alert or books.get(ALERT_CATEGORY, {}).get("status") != "active":
        return c
    return Classification(ALERT_CATEGORY, "low", entities={**c.entities, "ticket": alert},
                          reason=f"alerte {alert} nommée dans la demande ; le classifieur proposait {FALLBACK}",
                          error=c.error)


def complete_entities(c: Classification, question: str, alert_names: set[str] | frozenset[str] = frozenset()
                      ) -> list[str]:
    """Entités indispensables écrites dans la demande mais que le classifieur a déclarées manquantes :
    numéro INC ou CHG, nom d'une alerte connue (ticket). Rend les entités complétées."""
    found = {k: m.group(0) for k, pattern in IDENTIFIERS.items() if (m := re.search(pattern, question))}
    alert = named_alert(question, alert_names)
    if alert and "ticket" not in found:
        found["ticket"] = alert
    completed = [m for m in c.missing if m in found]
    for m in completed:
        c.entities[m] = found[m]
    c.missing = [m for m in c.missing if m not in found]
    return completed


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


# Évolution des playbooks (propositions validées par un Superviseur)

CHANGE_KINDS = ("add_examples", "add_hypotheses", "update_description", "new_category", "activate")


def apply_change(book: dict[str, Any] | None, kind: str, change: dict[str, Any]) -> dict[str, Any]:
    """Nouvelle version d'un playbook après une proposition ; ne touche pas au disque."""
    if kind not in CHANGE_KINDS:
        raise PlaybookError(f"kind doit valoir {', '.join(CHANGE_KINDS)}")
    if kind == "new_category":
        new = dict(change["playbook"])
        new.update(version=1, status="draft")
        return new
    if book is None:
        raise PlaybookError("playbook cible inconnu")
    new = json.loads(json.dumps(book))
    new["version"] = book["version"] + 1
    if kind == "add_examples":
        new["examples"] = list(dict.fromkeys([*(book.get("examples") or []), *change["examples"]]))
    elif kind == "add_hypotheses":
        known = {h["id"] for h in book.get("hypotheses") or []}
        new["hypotheses"] = [*(book.get("hypotheses") or []),
                             *[h for h in change["hypotheses"] if h["id"] not in known]]
    elif kind == "update_description":
        new["description"] = change["description"]
    elif kind == "activate":
        new["status"] = "active"
    return new


def save_playbook(book: dict[str, Any], roles: set[str] | None = None) -> Path:
    """Écrit un playbook validé ; la version précédente est gardée dans history/ pour le retour arrière."""
    validate(book, roles=roles)
    path = playbooks_dir() / f"{book['id']}.yaml"
    if path.exists():
        old = yaml.safe_load(path.read_text(encoding="utf-8"))
        backup = playbooks_dir() / "history" / f"{old['id']}-v{old['version']}.yaml"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(yaml.safe_dump(book, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    return path


def rollback(book_id: str) -> dict[str, Any]:
    """Revient à la version précédente gardée dans history/ (la version retirée y reste aussi)."""
    history = sorted((playbooks_dir() / "history").glob(f"{book_id}-v*.yaml"),
                     key=lambda p: int(p.stem.rsplit("-v", 1)[1]))
    path = playbooks_dir() / f"{book_id}.yaml"
    current = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    previous = [p for p in history if current is None or int(p.stem.rsplit("-v", 1)[1]) < current["version"]]
    if not previous:
        raise PlaybookError(f"Aucune version antérieure de {book_id} dans history/")
    if current is not None:
        retired = playbooks_dir() / "history" / f"{book_id}-v{current['version']}.yaml"
        retired.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(previous[-1].read_text(encoding="utf-8"), encoding="utf-8")
    return yaml.safe_load(path.read_text(encoding="utf-8"))
