"""Configuration modifiable depuis l'interface (document d'architecture, « Configuration depuis
l'interface ») : fiches du catalogue, modèles, paramètres, rôles de sous-agents, playbooks, prompts et
jeu d'évaluation.

Chaque enregistrement est validé par les mêmes règles que celles de l'orchestrateur avant d'être écrit,
refusé si le fichier a changé depuis la version lue, écrit de façon atomique, et versionné dans
config-history/ avec son auteur et son commentaire. Les comptes ne passent pas par ici (formulaire
dédié) ; le code, les secrets, runs/ et audit/ ne sont pas modifiables.
"""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import string
import tempfile
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import catalog, playbooks
from .agent import Budget
from .llm import model_profiles, select_profile

# (motif, type, permission, création autorisée)
EDITABLE = [
    ("catalog/sources/*.yaml", "source", "edit_platform", True),
    ("catalog/glossary.yaml", "yaml", "edit_platform", False),
    ("catalog/relations.yaml", "yaml", "edit_platform", False),
    ("config/models.yaml", "models", "edit_platform", False),
    ("config/poc.yaml", "poc", "edit_platform", False),
    ("agents/*.yaml", "agent", "edit_platform", True),
    ("playbooks/*.yaml", "playbook", "edit_diagnostic", True),
    ("prompts/*.md", "prompt", "edit_diagnostic", False),
    ("eval/cases*.yaml", "eval", "edit_diagnostic", True),
]
GROUPS = {"source": "Catalogue", "yaml": "Catalogue", "models": "Plateforme", "poc": "Plateforme",
          "agent": "Rôles de sous-agents", "playbook": "Playbooks", "prompt": "Prompts", "eval": "Évaluation"}
# Variables de chaque prompt, remplies par l'orchestrateur (str.format).
PROMPT_FIELDS = {"lead.md": {"now", "catalog", "roles", "max_subagents", "playbook"},
                 "subagent.md": {"role", "role_system", "now"}}
ADAPTERS = {"azure_openai", "openai_compatible", "anthropic"}
NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ConfigError(ValueError):
    pass


class ConflictError(ConfigError):
    pass


def history_dir() -> Path:
    return Path(os.environ.get("DIAGAGENT_CONFIG_HISTORY_DIR") or catalog.home() / "config-history")


def version_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _resolve(rel: str) -> Path:
    # Les playbooks peuvent vivre ailleurs (DIAGAGENT_PLAYBOOKS_DIR), comme pour l'orchestrateur.
    if rel.startswith("playbooks/"):
        return playbooks.playbooks_dir() / rel.split("/", 1)[1]
    return catalog.home() / rel


def rule_of(rel: str) -> tuple[str, str, bool]:
    """Type, permission et création autorisée d'un chemin ; ConfigError s'il n'est pas modifiable."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ".." in parts or not NAME.match(parts[-1]):
        raise ConfigError(f"Chemin refusé : {rel}")
    for pattern, kind, permission, creatable in EDITABLE:
        if fnmatch.fnmatchcase(rel, pattern) and rel.count("/") == pattern.count("/"):
            return kind, permission, creatable
    raise ConfigError(f"{rel} n'est pas un fichier de configuration modifiable")


def list_files() -> list[dict[str, Any]]:
    out = []
    for pattern, kind, permission, creatable in EDITABLE:
        folder, _, glob = pattern.rpartition("/")
        base = _resolve(f"{folder}/x").parent
        for path in sorted(base.glob(glob)):
            rel = f"{folder}/{path.name}"
            out.append({"path": rel, "kind": kind, "group": GROUPS[kind], "permission": permission,
                        "size": path.stat().st_size,
                        "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
    return out


def creatable() -> list[dict[str, str]]:
    """Dossiers où l'on peut créer un fichier, avec le motif de nom attendu."""
    return [{"pattern": p, "kind": k, "group": GROUPS[k], "permission": perm}
            for p, k, perm, c in EDITABLE if c]


def read(rel: str) -> dict[str, Any]:
    kind, permission, _ = rule_of(rel)
    path = _resolve(rel)
    if not path.exists():
        raise FileNotFoundError(rel)
    text = path.read_text(encoding="utf-8")
    return {"path": rel, "kind": kind, "permission": permission, "content": text, "version": version_of(text)}


# Validation : les mêmes règles que l'orchestrateur, avant toute écriture

def _yaml(text: str) -> Any:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML invalide : {e}") from e
    if not isinstance(data, (dict, list)):
        raise ConfigError("Le fichier doit contenir un objet YAML (clés et valeurs)")
    return data


def _mapping(text: str) -> dict[str, Any]:
    data = _yaml(text)
    if not isinstance(data, dict):
        raise ConfigError("Le fichier doit contenir un objet YAML (clés et valeurs), pas une liste")
    return data


def _budget(cfg: Any, where: str) -> None:
    allowed = {f.name for f in fields(Budget)}
    if not isinstance(cfg, dict) or set(cfg) - allowed or not all(isinstance(v, int) and v > 0 for v in cfg.values()):
        raise ConfigError(f"{where} : budget invalide ; clés possibles {', '.join(sorted(allowed))}, entiers positifs")


def _check_source(text: str, stem: str) -> None:
    card = _mapping(text)
    missing = [k for k in ("id", "kind", "description", "backend") if not card.get(k)]
    if missing:
        raise ConfigError(f"Champs obligatoires manquants : {', '.join(missing)}")
    if card["id"] != stem:
        raise ConfigError(f"id {card['id']!r} différent du nom du fichier ({stem})")
    if not isinstance(card["backend"], dict) or not card["backend"].get("type"):
        raise ConfigError("backend doit être un objet avec un type (file, prometheus…)")
    for tr in card.get("as_of", []) or []:
        if not isinstance(tr, dict) or not tr.get("field"):
            raise ConfigError("Chaque entrée de as_of a un champ field")


def _check_models(text: str) -> None:
    cfg = _mapping(text)
    providers = cfg.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ConfigError("providers est obligatoire")
    for name, p in providers.items():
        if not isinstance(p, dict) or p.get("adapter") not in ADAPTERS:
            raise ConfigError(f"Fournisseur {name} : adapter parmi {', '.join(sorted(ADAPTERS))}")
    try:
        names, _ = model_profiles(cfg)
        for profile in names:
            _, selected = select_profile(cfg, profile)
            roles = selected.get("roles")
            if not isinstance(roles, dict) or "lead" not in roles:
                raise ConfigError(f"Profil {profile} : le rôle lead est obligatoire")
            for role, r in roles.items():
                if not isinstance(r, dict) or r.get("provider") not in providers:
                    raise ConfigError(f"Profil {profile}, rôle {role} : fournisseur inconnu {r.get('provider') if isinstance(r, dict) else r}")
                if not (r.get("model") or r.get("deployment")):
                    raise ConfigError(f"Profil {profile}, rôle {role} : model ou deployment obligatoire")
    except (KeyError, TypeError, ValueError) as e:
        if isinstance(e, ConfigError):
            raise
        raise ConfigError(f"Profils de modèles invalides : {e}") from e


def _check_poc(text: str) -> None:
    cfg = _mapping(text)
    for name, budget in (cfg.get("budgets") or {}).items():
        _budget(budget, f"budgets.{name}")
    orch = cfg.get("orchestration") or {}
    if not isinstance(orch, dict) or not all(isinstance(v, (int, float)) and v >= 0 for v in orch.values()):
        raise ConfigError("orchestration : des nombres positifs")


def _check_agent(text: str, stem: str) -> None:
    cfg = _mapping(text)
    missing = [k for k in ("role", "description", "servers", "system") if not cfg.get(k)]
    if missing:
        raise ConfigError(f"Champs obligatoires manquants : {', '.join(missing)}")
    if cfg["role"] != stem:
        raise ConfigError(f"role {cfg['role']!r} différent du nom du fichier ({stem})")
    if not isinstance(cfg["servers"], list) or not all(isinstance(s, str) for s in cfg["servers"]):
        raise ConfigError("servers est une liste de serveurs MCP (mcp-elk, mcp-metrics…)")
    if "budget" in cfg:
        _budget(cfg["budget"], "budget")


def _roles() -> set[str]:
    return {yaml.safe_load(p.read_text(encoding="utf-8"))["role"] for p in (catalog.home() / "agents").glob("*.yaml")}


def _check_playbook(text: str, stem: str) -> None:
    try:
        playbooks.validate(_mapping(text), stem, roles=_roles())
    except (KeyError, TypeError, AttributeError) as e:
        raise ConfigError(f"Playbook invalide : {e}") from e
    except playbooks.PlaybookError as e:
        raise ConfigError(str(e)) from e


def _check_prompt(text: str, name: str) -> None:
    allowed = PROMPT_FIELDS.get(name, set())
    try:
        used = {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}
    except ValueError as e:
        raise ConfigError(f"Accolade non fermée : {e} (une accolade littérale s'écrit {{{{ ou }}}})") from e
    unknown = sorted(used - allowed)
    if unknown:
        raise ConfigError(f"Variables inconnues : {', '.join('{' + u + '}' for u in unknown)} ; disponibles : "
                          f"{', '.join('{' + a + '}' for a in sorted(allowed))} (accolade littérale : {{{{ }}}})")


def _check_eval(text: str) -> None:
    spec = _mapping(text)
    cases = spec.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ConfigError("cases est une liste de cas")
    seen = set()
    for i, case in enumerate(cases):
        if not isinstance(case, dict) or not case.get("id") or not case.get("question"):
            raise ConfigError(f"cases[{i}] : id et question obligatoires")
        if case["id"] in seen:
            raise ConfigError(f"Identifiant de cas en double : {case['id']}")
        seen.add(case["id"])
        if case.get("kind") not in (None, "simple", "incident"):
            raise ConfigError(f"{case['id']} : kind vaut simple ou incident")
        for key in ("must_mention", "must_not_mention"):
            if key in case and not isinstance(case[key], list):
                raise ConfigError(f"{case['id']} : {key} est une liste")


def validate(rel: str, text: str) -> None:
    kind, _, _ = rule_of(rel)
    name = rel.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    checks = {"source": lambda: _check_source(text, stem), "yaml": lambda: _yaml(text),
              "models": lambda: _check_models(text), "poc": lambda: _check_poc(text),
              "agent": lambda: _check_agent(text, stem), "playbook": lambda: _check_playbook(text, stem),
              "prompt": lambda: _check_prompt(text, name), "eval": lambda: _check_eval(text)}
    checks[kind]()


# Enregistrement et historique

def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _keep(rel: str, text: str, meta: dict[str, Any]) -> None:
    folder = history_dir() / rel
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    (folder / f"{stamp}.txt").write_text(text, encoding="utf-8")
    (folder / f"{stamp}.json").write_text(json.dumps({"id": stamp, **meta}, ensure_ascii=False, indent=2),
                                          encoding="utf-8")


def save(rel: str, text: str, base_version: str | None, author: str, comment: str) -> dict[str, Any]:
    """Valide puis écrit. base_version : empreinte de la version lue (None pour un nouveau fichier) ;
    ConflictError si le fichier a changé depuis. La version d'origine d'un fichier est gardée au premier
    enregistrement, pour pouvoir y revenir."""
    kind, _, can_create = rule_of(rel)
    if not comment.strip():
        raise ConfigError("Un commentaire est obligatoire : il explique le changement dans l'historique")
    path = _resolve(rel)
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current is None and not can_create:
        raise ConfigError(f"{rel} n'existe pas et ne peut pas être créé ici")
    if current is not None and base_version != version_of(current):
        raise ConflictError(f"{rel} a été modifié depuis votre lecture (version {version_of(current)}) : "
                            "rechargez-le et reportez vos changements")
    if current is None and base_version is not None:
        raise ConflictError(f"{rel} a été supprimé depuis votre lecture")
    if current == text:
        raise ConfigError("Aucun changement")
    validate(rel, text)
    if current is not None and not any((history_dir() / rel).glob("*.json")):
        _keep(rel, current, {"author": None, "comment": "Version d'origine, avant la première modification",
                             "version": version_of(current), "previous": None})
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                                     suffix=".tmp", delete=False) as tmp:
        tmp.write(text)
    os.replace(tmp.name, path)
    meta = {"author": author, "comment": comment.strip(), "version": version_of(text),
            "previous": version_of(current) if current is not None else None}
    _keep(rel, text, meta)
    # Les fiches et les données sont mises en cache : la prochaine investigation relit la nouvelle version.
    catalog.load_catalog.cache_clear()
    catalog.load_yaml.cache_clear()
    catalog._load_rows.cache_clear()
    return {"path": rel, "kind": kind, **meta}


def history(rel: str) -> list[dict[str, Any]]:
    rule_of(rel)
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((history_dir() / rel).glob("*.json"), reverse=True)]


def version_text(rel: str, version_id: str) -> str:
    rule_of(rel)
    if not re.fullmatch(r"\d{8}T\d{12}Z", version_id):
        raise ConfigError(f"Version inconnue : {version_id}")
    path = history_dir() / rel / f"{version_id}.txt"
    if not path.exists():
        raise FileNotFoundError(f"{rel}@{version_id}")
    return path.read_text(encoding="utf-8")


def diff(old: str, new: str, old_label: str = "avant", new_label: str = "après") -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                        old_label, new_label))
