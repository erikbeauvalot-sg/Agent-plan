"""Ligne de commande du POC : diagagent ask "question" | diagagent tools | diagagent check."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

from . import catalog, knowledge, learning, playbooks
from .evaluation import find_run, replay_run, run_eval
from .orchestrator import Investigation, ProviderFactory, usage_total
from .llm import LLMRequest, Message, make_provider
from .runlog import RunLog
from .tools import ToolHub


def _load(name: str) -> dict:
    return yaml.safe_load((catalog.home() / "config" / name).read_text(encoding="utf-8"))


def default_providers() -> ProviderFactory:
    models = _load("models.yaml")
    cache: dict[str, Any] = {}

    def providers(role: str):
        if role not in cache:
            cache[role] = make_provider(models, role)
        return cache[role]
    return providers


async def ask(question: str, providers: ProviderFactory | None = None, user: str | None = None,
              on_started: Callable[[RunLog, Investigation], None] | None = None,
              category: str | None = None) -> tuple[RunLog, str, str]:
    """Une investigation complète. on_started est appelé dès que l'investigation est pilotable
    (utilisé par la passerelle web pour l'arrêt). category impose la catégorie et saute le classifieur
    (correction de l'utilisateur, rejeu)."""
    poc = _load("poc.yaml")
    providers = providers or default_providers()
    lead, lead_cfg = providers("lead")
    log = RunLog(catalog.runs_dir(poc), question, user or getpass.getuser(),
                 {"models": {"lead": {"provider": lead.name,
                                      "model": lead_cfg.get("deployment") or lead_cfg.get("model")}},
                  "reference_time": catalog.now().isoformat()})
    async with ToolHub(poc["mcp_servers"]) as hub:
        investigation = Investigation(question, hub, log, providers, poc, category=category)
        if on_started:
            on_started(log, investigation)
        result = await investigation.run()
    log.manifest["subagents"] = {t: {"role": s.role, "status": s.status,
                                     "report_status": (s.report or {}).get("status")}
                                 for t, s in investigation.subagents.items()}
    log.finish(result.status, result.answer, usage_total(result, investigation.subagents, log.dir))
    return log, result.status, result.answer


async def list_tools() -> None:
    async with ToolHub(_load("poc.yaml")["mcp_servers"]) as hub:
        for spec in hub.specs.values():
            print(f"- {spec.name} : {spec.description.splitlines()[0] if spec.description else ''}")


def list_playbooks() -> None:
    from .orchestrator import load_roles

    roles = set(load_roles())
    for book in playbooks.load_playbooks(include=playbooks.STATUSES).values():
        playbooks.validate(book, roles=roles)
        print(f"- {book['id']:<18} v{book['version']} {book['status']:<8} {len(book['steps'])} étape(s) · {book['owner']}")


def run_learn(days: int, model: bool = True, replay: bool = True) -> None:
    from .orchestrator import load_roles

    models = _load("models.yaml")
    drafter = make_provider(models, "learner")[0] if model else None
    classifier = make_provider(models, "classifier")[0] if replay else None
    written = learning.learn(catalog.runs_dir(_load("poc.yaml")), days, drafter, classifier, set(load_roles()), log=print)
    pending = sum(p["status"] == "pending" for p in written)
    print(f"{len(written)} proposition(s), dont {pending} à valider par un Superviseur")


def manage_proposals(action: str, proposal_id: str | None, by: str | None, comment: str) -> None:
    from .orchestrator import load_roles

    if action == "list":
        for p in learning.list_proposals():
            replay = p.get("replay") or {}
            score = f"rejeu {replay['before']}→{replay['after']}/{replay['cases']}" if replay else "non rejouée"
            print(f"- {p['id']:<48} {p['status']:<9} {score} · {p['rationale']}")
        return
    if not proposal_id or not by:
        sys.exit("Indiquer l'identifiant de la proposition et --by <superviseur>")
    p = learning.decide(proposal_id, action == "accept", by, comment, roles=set(load_roles()))
    print(f"{p['id']} : {p['status']}" + (f" (version {p['applied_version']})" if p.get("applied_version") else ""))


def check_model() -> None:
    provider, role_cfg = make_provider(_load("models.yaml"), "lead")
    resp = provider.complete(LLMRequest(system="Réponds en un mot.", messages=[Message("user", "Bonjour ?")],
                                        max_tokens=200))
    print(f"OK : {provider.name} / {resp.model}, arrêt={resp.stop_reason}, réponse={resp.text!r}")


def print_eval(report: dict[str, Any]) -> bool:
    for r in report["results"]:
        mark = "OK  " if r["passed"] else "ÉCHEC"
        print(f"{mark} {r['id']:<22} {r['duration_s']:>6} s  {sum(r['usage'].values()):>7} tokens  {r['run_id']}")
        for c in r["checks"]:
            if not c["ok"]:
                print(f"       ✗ {c['check']}" + (f" ({c['detail']})" if "detail" in c else ""))
    s = report["summary"]
    categories = (f" · catégorie juste {s['categories']['correct']}/{s['categories']['cases']}"
                  if "categories" in s else "")
    print(f"\n{s['passed']}/{s['cases']} cas réussis{categories} · {s['tokens']} tokens · rapport : {report['path']}")
    return s["passed"] == s["cases"]


def print_replay(result: dict[str, Any]) -> bool:
    print(f"Rejeu de {result['original']} -> {result['replay']} : statut {result['status']} "
          f"(origine : {result['original_status']})")
    for d in result["differences"]:
        print(f"  ≠ {d['ref']} : {d['difference']}")
    if result["unused_responses"]:
        print(f"  Réponses enregistrées non utilisées : {result['unused_responses']}")
    same = not result["differences"] and not result["unused_responses"]
    print("Identique à l'investigation d'origine." if same else "Le rejeu diverge de l'origine.")
    return same


def serve(host: str, port: int) -> None:
    import uvicorn

    from .web.app import create_app
    from .web.auth import FileUserStore

    if not FileUserStore().path.exists():
        sys.exit("Aucun utilisateur : crée d'abord un compte avec "
                 "diagagent user add <login> --role administrateur")
    print(f"Interface : http://{host}:{port}", file=sys.stderr)
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


def add_user(login: str, roles: list[str], name: str | None) -> None:
    from .web.auth import AuthError, FileUserStore

    password = getpass.getpass("Mot de passe (12 caractères minimum) : ")
    if password != getpass.getpass("Confirmation : "):
        sys.exit("Les mots de passe diffèrent")
    try:
        user = FileUserStore().add(login, password, roles, name)
    except AuthError as e:
        sys.exit(str(e))
    print(f"Utilisateur {user.login} ({', '.join(user.roles)}) créé dans auth/users.yaml")


def load_dotenv(path: Path) -> None:
    """Charge les lignes `CLE=valeur` d'un fichier .env sans écraser les variables déjà définies.
    Les serveurs MCP héritent de l'environnement : PROMETHEUS_URL ou ALERTMANAGER_URL peuvent y figurer."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="diagagent", description="POC de l'agent de diagnostic")
    parser.add_argument("--home", help="Racine du POC (catalog/, config/, runs/) ; défaut : dossier courant")
    parser.add_argument("--now", help="Heure de référence ISO 8601 (rejouer un scénario)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ask = sub.add_parser("ask", help="Poser une question à l'agent principal")
    p_ask.add_argument("question")
    p_ask.add_argument("--category", help="Imposer la catégorie (sans classifieur)")
    p_books = sub.add_parser("playbooks", help="Vérifier et lister les playbooks")
    p_books.add_argument("--rollback", metavar="ID", help="Revenir à la version précédente d'un playbook")
    p_learn = sub.add_parser("learn", help="Agent d'apprentissage : écrit des propositions dans playbooks/proposals/")
    p_learn.add_argument("--days", type=int, default=7, help="Période analysée (jours)")
    p_learn.add_argument("--no-model", action="store_true", help="Propositions mécaniques seulement")
    p_learn.add_argument("--no-replay", action="store_true", help="Ne pas rejouer la catégorisation")
    p_prop = sub.add_parser("proposals", help="Lister, accepter ou rejeter les propositions")
    p_prop.add_argument("action", nargs="?", choices=["list", "accept", "reject"], default="list")
    p_prop.add_argument("id", nargs="?")
    p_prop.add_argument("--by", help="Superviseur qui décide")
    p_prop.add_argument("--comment", default="")
    p_case = sub.add_parser("case", help="Créer un cas dans knowledge/ à partir d'une investigation confirmée")
    p_case.add_argument("action", choices=["add"])
    p_case.add_argument("run_id")
    p_case.add_argument("--cause", required=True)
    p_case.add_argument("--resolution", default="")
    sub.add_parser("tools", help="Lister les outils exposés par les serveurs MCP")
    sub.add_parser("check", help="Vérifier la connexion au modèle")
    p_eval = sub.add_parser("eval", help="Jouer un jeu d'évaluation avec le modèle configuré")
    p_eval.add_argument("--cases", default="eval/cases.yaml")
    p_eval.add_argument("--only", action="append", help="Identifiant de cas (répétable)")
    p_replay = sub.add_parser("replay", help="Rejouer une investigation sans appeler le modèle")
    p_replay.add_argument("run_id")
    p_serve = sub.add_parser("serve", help="Lancer l'interface web")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_user = sub.add_parser("user", help="Gérer la table d'utilisateurs (auth/users.yaml)")
    p_user.add_argument("action", choices=["add"])
    p_user.add_argument("login")
    p_user.add_argument("--role", action="append", required=True, choices=["lecteur", "operateur", "superviseur", "administrateur", "auditeur"])
    p_user.add_argument("--name", help="Nom affiché")
    args = parser.parse_args(argv)
    if args.home:
        os.environ["DIAGAGENT_HOME"] = str(Path(args.home).resolve())
    if args.now:
        os.environ["DIAGAGENT_NOW"] = args.now
    load_dotenv(catalog.home() / ".env")

    if args.cmd == "tools":
        asyncio.run(list_tools())
    elif args.cmd == "check":
        check_model()
    elif args.cmd == "eval":
        sys.exit(0 if print_eval(asyncio.run(run_eval(catalog.home() / args.cases, only=args.only))) else 1)
    elif args.cmd == "replay":
        sys.exit(0 if print_replay(asyncio.run(replay_run(args.run_id))) else 1)
    elif args.cmd == "serve":
        serve(args.host, args.port)
    elif args.cmd == "playbooks":
        if args.rollback:
            book = playbooks.rollback(args.rollback)
            print(f"{book['id']} revenu à la version {book['version']}")
        list_playbooks()
    elif args.cmd == "learn":
        run_learn(args.days, model=not args.no_model, replay=not args.no_replay)
    elif args.cmd == "proposals":
        manage_proposals(args.action, args.id, args.by, args.comment)
    elif args.cmd == "case":
        case = knowledge.create_case(find_run(args.run_id), getpass.getuser(), args.cause, args.resolution)
        print(f"Cas {case['id']} créé ({case['category']}) dans {knowledge.knowledge_dir()}")
    elif args.cmd == "user":
        add_user(args.login, args.role, args.name)
    else:
        log, status, answer = asyncio.run(ask(args.question, category=args.category))
        print(answer)
        print(f"\n---\nStatut : {status} · traces : {log.dir}", file=sys.stderr)
        print(json.dumps(log.manifest.get("usage", {})), file=sys.stderr)


if __name__ == "__main__":
    main()
