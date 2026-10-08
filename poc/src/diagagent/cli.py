"""Ligne de commande du POC : diagagent ask "question" | diagagent tools | diagagent check."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

import yaml

from . import catalog
from .agent import Budget, run_agent
from .llm import LLMRequest, Message, make_provider
from .runlog import RunLog
from .tools import ToolHub


def _load(name: str) -> dict:
    return yaml.safe_load((catalog.home() / "config" / name).read_text(encoding="utf-8"))


def lead_system_prompt() -> str:
    template = (catalog.home() / "prompts" / "lead.md").read_text(encoding="utf-8")
    return template.format(now=catalog.now().strftime("%Y-%m-%dT%H:%M:%SZ"), catalog=catalog.catalog_summary())


async def ask(question: str, provider=None, role_cfg: dict | None = None) -> tuple[RunLog, str, str]:
    poc = _load("poc.yaml")
    if provider is None:
        provider, role_cfg = make_provider(_load("models.yaml"), "lead")
    role_cfg = role_cfg or {}
    log = RunLog(catalog.home() / poc.get("runs_dir", "runs"), question, getpass.getuser(),
                 {"models": {"lead": {"provider": provider.name,
                                      "model": role_cfg.get("deployment") or role_cfg.get("model")}},
                  "reference_time": catalog.now().isoformat()})
    async with ToolHub(poc["mcp_servers"]) as hub:
        result = await run_agent(agent_id="lead", provider=provider, system=lead_system_prompt(),
                                 user_message=question, tools=hub.tools_for(None), hub=hub, log=log,
                                 budget=Budget(**poc.get("budgets", {}).get("lead", {})),
                                 reasoning=role_cfg.get("reasoning"))
    log.finish(result.status, result.answer, result.usage)
    return log, result.status, result.answer


async def list_tools() -> None:
    async with ToolHub(_load("poc.yaml")["mcp_servers"]) as hub:
        for spec in hub.specs.values():
            print(f"- {spec.name} : {spec.description.splitlines()[0] if spec.description else ''}")


def check_model() -> None:
    provider, role_cfg = make_provider(_load("models.yaml"), "lead")
    resp = provider.complete(LLMRequest(system="Réponds en un mot.", messages=[Message("user", "Bonjour ?")],
                                        max_tokens=200))
    print(f"OK : {provider.name} / {resp.model}, arrêt={resp.stop_reason}, réponse={resp.text!r}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="diagagent", description="POC de l'agent de diagnostic")
    parser.add_argument("--home", help="Racine du POC (catalog/, config/, runs/) ; défaut : dossier courant")
    parser.add_argument("--now", help="Heure de référence ISO 8601 (rejouer un scénario)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ask = sub.add_parser("ask", help="Poser une question à l'agent principal")
    p_ask.add_argument("question")
    sub.add_parser("tools", help="Lister les outils exposés par les serveurs MCP")
    sub.add_parser("check", help="Vérifier la connexion au modèle")
    args = parser.parse_args(argv)
    if args.home:
        os.environ["DIAGAGENT_HOME"] = str(Path(args.home).resolve())
    if args.now:
        os.environ["DIAGAGENT_NOW"] = args.now

    if args.cmd == "tools":
        asyncio.run(list_tools())
    elif args.cmd == "check":
        check_model()
    else:
        log, status, answer = asyncio.run(ask(args.question))
        print(answer)
        print(f"\n---\nStatut : {status} · traces : {log.dir}", file=sys.stderr)
        print(json.dumps(log.manifest.get("usage", {})), file=sys.stderr)


if __name__ == "__main__":
    main()
