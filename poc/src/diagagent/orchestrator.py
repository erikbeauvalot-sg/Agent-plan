"""Orchestration multi-agents : l'agent principal écrit un plan, lance des sous-agents spécialisés
avec un prompt généré, attend leurs rapports structurés et consolide.

Règles (document d'architecture, section Orchestration) : profondeur 1, sous-agents en parallèle
avec un plafond, budget par sous-agent, contexte isolé (le sous-agent ne voit que son prompt).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from . import catalog
from .agent import AgentResult, Budget, CancelToken, LocalTool, LocalToolError, run_agent
from .llm import LLMProvider, ToolSpec
from .runlog import RunLog
from .tools import ToolHub

ProviderFactory = Callable[[str], tuple[LLMProvider, dict[str, Any]]]

REPORT_STATUSES = ("completed", "partial", "failed")
CONFIDENCES = ("low", "medium", "high")

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(REPORT_STATUSES)},
        "summary": {"type": "string", "description": "Ce qui a été trouvé, en une ou deux phrases"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"},
                                 "description": "query_ref des appels d'outils qui prouvent le fait"},
                    "timestamp_range": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": list(CONFIDENCES)},
                },
                "required": ["fact", "evidence", "confidence"],
            },
        },
        "gaps": {"type": "array", "items": {"type": "string"},
                 "description": "Ce qui n'a pas pu être vérifié et pourquoi"},
        "suggested_followups": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "summary", "findings"],
}


ACTION_TYPES = ("diagnostic complémentaire", "remédiation", "contournement", "ouverture de ticket")
RISKS = ("faible", "moyen", "élevé")

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Action en une phrase, à l'infinitif"},
        "target": {"type": "string", "description": "Host, CI ou service visé"},
        "type": {"type": "string", "enum": list(ACTION_TYPES)},
        "rationale": {"type": "string", "description": "Pourquoi cette action, d'après les faits"},
        "evidence": {"type": "array", "items": {"type": "string"},
                     "description": "query_ref des appels qui justifient l'action"},
        "risk": {"type": "string", "enum": list(RISKS)},
        "risk_explanation": {"type": "string"},
        "procedure": {"type": "string", "description": "Étapes manuelles ou référence de runbook"},
        "rollback": {"type": "string", "description": "Comment revenir en arrière"},
        "requires_change": {"type": "boolean", "description": "Passe par la gestion des changements"},
    },
    "required": ["title", "target", "type", "rationale", "evidence", "risk", "procedure", "rollback",
                 "requires_change"],
}


def validate_action(action: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in ACTION_SCHEMA["required"] if action.get(k) in (None, "", [])]
    if missing:
        raise LocalToolError(f"Champs manquants : {', '.join(missing)}")
    if action["type"] not in ACTION_TYPES:
        raise LocalToolError(f"type doit valoir : {', '.join(ACTION_TYPES)}")
    if action["risk"] not in RISKS:
        raise LocalToolError(f"risk doit valoir : {', '.join(RISKS)}")
    if not isinstance(action["evidence"], list):
        raise LocalToolError("evidence doit être une liste de query_ref")
    return {k: action[k] for k in ACTION_SCHEMA["properties"] if k in action}


@dataclass
class Role:
    name: str
    description: str
    servers: list[str]
    system: str
    budget: Budget


@dataclass
class SubAgent:
    task_id: str
    role: str
    objective: str
    cancel: CancelToken = field(default_factory=CancelToken)
    task: asyncio.Task[AgentResult] | None = None
    report: dict[str, Any] | None = None
    status: str = "running"


def load_roles() -> dict[str, Role]:
    roles = {}
    for path in sorted((catalog.home() / "agents").glob("*.yaml")):
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
        roles[cfg["role"]] = Role(cfg["role"], " ".join(cfg["description"].split()), cfg["servers"],
                                  cfg["system"], Budget(**cfg.get("budget", {})))
    return roles


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validation du rapport de sous-agent ; une erreur revient au sous-agent pour correction."""
    if report.get("status") not in REPORT_STATUSES:
        raise LocalToolError(f"status doit valoir {', '.join(REPORT_STATUSES)}")
    if not isinstance(report.get("summary"), str) or not report["summary"].strip():
        raise LocalToolError("summary manquant")
    findings = report.get("findings")
    if not isinstance(findings, list):
        raise LocalToolError("findings doit être une liste")
    for i, f in enumerate(findings):
        if not isinstance(f, dict) or not f.get("fact"):
            raise LocalToolError(f"findings[{i}].fact manquant")
        if not isinstance(f.get("evidence"), list) or not f["evidence"]:
            raise LocalToolError(f"findings[{i}].evidence doit citer au moins un query_ref")
        if f.get("confidence") not in CONFIDENCES:
            raise LocalToolError(f"findings[{i}].confidence doit valoir {', '.join(CONFIDENCES)}")
    report.setdefault("gaps", [])
    report.setdefault("suggested_followups", [])
    return report


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")[:40] or "x"


class Investigation:
    def __init__(self, question: str, hub: ToolHub, log: RunLog, providers: ProviderFactory,
                 poc_cfg: dict[str, Any]):
        self.question = question
        self.hub = hub
        self.log = log
        self.providers = providers
        orch = poc_cfg.get("orchestration", {})
        self.max_subagents = orch.get("max_subagents", 12)
        self.semaphore = asyncio.Semaphore(orch.get("max_parallel", 6))
        self.lead_budget = Budget(**poc_cfg.get("budgets", {}).get("lead", {}))
        self.roles = {name: r for name, r in load_roles().items() if self._role_tools(r)}
        self.subagents: dict[str, SubAgent] = {}
        self.lead_cancel = CancelToken()

    # Pilotage (utilisé par l'interface web à l'étape 3)

    def stop_agent(self, agent_id: str, by: str | None = None) -> bool:
        """Arrêt propre : un sous-agent rend un rapport partiel ; "lead" arrête toute l'investigation,
        l'agent principal produisant une synthèse partielle."""
        if agent_id == "lead":
            self.log.event("lead", "stop_requested", {"by": by, "scope": "investigation"})
            for sub in self.subagents.values():
                if sub.status == "running":
                    sub.cancel.wrap_up()
            self.lead_cancel.wrap_up()
            return True
        sub = self.subagents.get(agent_id)
        if sub is None or sub.status != "running":
            return False
        self.log.event(agent_id, "stop_requested", {"by": by, "scope": "agent"}, parent_id="lead")
        sub.cancel.wrap_up()
        return True

    def kill(self, by: str | None = None) -> None:
        """Arrêt immédiat, sans synthèse (un agent surcharge une source)."""
        self.log.event("lead", "stop_requested", {"by": by, "scope": "kill"})
        self.lead_cancel.cancel()
        for sub in self.subagents.values():
            sub.cancel.cancel()

    def stop_all(self) -> None:
        self.kill()

    # Agent principal

    async def run(self) -> AgentResult:
        provider, role_cfg = self.providers("lead")
        result = await run_agent(
            agent_id="lead", provider=provider, system=self.lead_system_prompt(),
            user_message=self.question, tools=self.hub.tools_for(None), hub=self.hub, log=self.log,
            budget=self.lead_budget, reasoning=role_cfg.get("reasoning"), cancel=self.lead_cancel,
            local_tools=self._lead_tools())
        await self._close_pending()
        return result

    def lead_system_prompt(self) -> str:
        template = (catalog.home() / "prompts" / "lead.md").read_text(encoding="utf-8")
        roles = "\n".join(f"- {r.name} : {r.description}" for r in self.roles.values()) or "- (aucun)"
        return template.format(now=catalog.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                               catalog=catalog.catalog_summary(), roles=roles,
                               max_subagents=self.max_subagents)

    def _lead_tools(self) -> dict[str, LocalTool]:
        role_names = list(self.roles)
        return {
            "write_plan": LocalTool(ToolSpec(
                "write_plan",
                "Écrit ou remplace plan.md : hypothèses à tester, investigations prévues (rôle, source, "
                "critère de fin). À appeler avant de lancer des sous-agents.",
                {"type": "object", "properties": {"markdown": {"type": "string"}}, "required": ["markdown"]}),
                self._write_plan),
            "spawn_subagent": LocalTool(ToolSpec(
                "spawn_subagent",
                "Lance un sous-agent sur une investigation et rend immédiatement son task_id. Lance les "
                "investigations indépendantes dans la même réponse pour qu'elles tournent en parallèle, "
                "puis appelle wait_subagents.",
                {"type": "object", "properties": {
                    "role": {"type": "string", "enum": role_names},
                    "entity": {"type": "string", "description": "Entité principale (host, service), pour l'identifiant"},
                    "objective": {"type": "string", "description": "Objectif en une phrase"},
                    "period": {"type": "string", "description": "Période ISO 8601 et période de référence éventuelle"},
                    "entities": {"type": "string", "description": "Entités résolues (host, CI, service, labels)"},
                    "sources": {"type": "string", "description": "Sources ou outils suggérés"},
                    "end_criterion": {"type": "string", "description": "Quand s'arrêter"},
                }, "required": ["role", "entity", "objective", "period"]}),
                self._spawn),
            "wait_subagents": LocalTool(ToolSpec(
                "wait_subagents",
                "Attend la fin des sous-agents indiqués (tous les sous-agents en cours si la liste est vide) "
                "et rend leurs rapports.",
                {"type": "object", "properties": {"task_ids": {"type": "array", "items": {"type": "string"}}}}),
                self._wait),
            "propose_action": LocalTool(ToolSpec(
                "propose_action",
                "Enregistre une action proposée dans actions.json. L'action n'est jamais exécutée : elle est "
                "présentée à un humain avec sa justification et ses preuves. Une action par appel.",
                ACTION_SCHEMA), self._propose_action),
        }

    async def _propose_action(self, args: dict[str, Any]) -> str:
        action = validate_action(dict(args))
        path = self.log.dir / "actions.json"
        actions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        action = {"id": f"A{len(actions) + 1:02d}", "status": "proposed", **action}
        actions.append(action)
        path.write_text(json.dumps(actions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.log.event("lead", "action_proposed", {"id": action["id"], "title": action["title"],
                                                   "risk": action["risk"]})
        return json.dumps({"id": action["id"], "status": "proposed, non exécutée"}, ensure_ascii=False)

    async def _write_plan(self, args: dict[str, Any]) -> str:
        (self.log.dir / "plan.md").write_text(args["markdown"].rstrip() + "\n", encoding="utf-8")
        self.log.event("lead", "plan_written", {"chars": len(args["markdown"])})
        return "plan.md écrit"

    async def _spawn(self, args: dict[str, Any]) -> str:
        role = self.roles.get(args.get("role", ""))
        if role is None:
            raise LocalToolError(f"Rôle inconnu ou sans source disponible : {args.get('role')}. "
                                 f"Rôles disponibles : {', '.join(self.roles)}")
        if len(self.subagents) >= self.max_subagents:
            raise LocalToolError(f"Plafond de {self.max_subagents} sous-agents atteint pour cette question")
        task_id = f"T{len(self.subagents) + 1:02d}-{role.name}-{_slug(args['entity'])}"
        prompt = self._task_prompt(task_id, role, args)
        sub = SubAgent(task_id, role.name, args["objective"])
        self.subagents[task_id] = sub
        self.log.write_text(task_id, "prompt.md", prompt)
        self.log.event(task_id, "agent_spawned", {"role": role.name, "objective": args["objective"]},
                       parent_id="lead")
        sub.task = asyncio.create_task(self._run_subagent(sub, role, prompt))
        return json.dumps({"task_id": task_id, "status": "started"}, ensure_ascii=False)

    async def _wait(self, args: dict[str, Any]) -> str:
        ids = args.get("task_ids") or [t for t, s in self.subagents.items() if s.task and not s.task.done()]
        if not ids:
            ids = list(self.subagents)
        unknown = [t for t in ids if t not in self.subagents]
        if unknown:
            raise LocalToolError(f"task_id inconnu : {', '.join(unknown)}")
        await asyncio.gather(*(self.subagents[t].task for t in ids if self.subagents[t].task))
        return json.dumps([{"task_id": t, **(self.subagents[t].report or {})} for t in ids], ensure_ascii=False)

    async def _close_pending(self) -> None:
        """L'agent principal a fini sans attendre certains sous-agents : on les arrête proprement."""
        pending = [s for s in self.subagents.values() if s.task and not s.task.done()]
        for sub in pending:
            sub.cancel.cancel()
        await asyncio.gather(*(s.task for s in pending if s.task), return_exceptions=True)

    # Sous-agents

    def _role_tools(self, role: Role) -> list[ToolSpec]:
        """Outils du rôle ; un rôle n'est disponible que s'il a au moins une source hors catalogue."""
        tools = self.hub.tools_for(role.servers)
        catalog_only = {t.name for t in self.hub.tools_for(["mcp-catalog"])}
        return tools if any(t.name not in catalog_only for t in tools) else []

    def _task_prompt(self, task_id: str, role: Role, args: dict[str, Any]) -> str:
        lines = [f"# Tâche {task_id}", f"Objectif : {args['objective']}", f"Période : {args['period']}"]
        if args.get("entities"):
            lines.append(f"Entités : {args['entities']}")
        if args.get("sources"):
            lines.append(f"Sources suggérées : {args['sources']}")
        lines += ["", "# Critère de fin",
                  args.get("end_criterion") or f"Tu t'arrêtes quand l'objectif est atteint, ou après "
                                               f"{role.budget.max_tool_calls} appels d'outils."]
        return "\n".join(lines) + "\n"

    def _subagent_system(self, role: Role) -> str:
        template = (catalog.home() / "prompts" / "subagent.md").read_text(encoding="utf-8")
        return template.format(role=role.name, role_system=role.system.strip(),
                               now=catalog.now().strftime("%Y-%m-%dT%H:%M:%SZ"))

    async def _run_subagent(self, sub: SubAgent, role: Role, prompt: str) -> AgentResult:
        async with self.semaphore:
            submitted: dict[str, Any] = {}

            async def submit(args: dict[str, Any]) -> str:
                submitted.update(validate_report(dict(args)))
                return "Rapport reçu."

            local = {"submit_report": LocalTool(ToolSpec(
                "submit_report", "Rend le rapport structuré à l'agent principal et termine la tâche.",
                REPORT_SCHEMA), submit, terminal=True)}
            try:
                provider, role_cfg = self.providers(role.name)
                result = await run_agent(
                    agent_id=sub.task_id, provider=provider, system=self._subagent_system(role),
                    user_message=prompt, tools=self._role_tools(role), hub=self.hub, log=self.log,
                    budget=role.budget, reasoning=role_cfg.get("reasoning"), cancel=sub.cancel,
                    local_tools=local, final_tools=("submit_report",), parent_id="lead",
                    budget_message="Budget atteint : appelle submit_report maintenant avec status "
                                   "\"partial\" et ce que tu as trouvé.")
            except Exception as e:  # un sous-agent en échec n'interrompt pas l'investigation
                result = AgentResult(status="failed", answer=f"{type(e).__name__}: {e}")
            sub.status = result.status
            sub.report = submitted or {
                "status": "partial" if result.status in ("partial", "stopped", "completed") else "failed",
                "summary": result.answer or "Aucun rapport rendu.",
                "findings": [], "gaps": [f"Sous-agent terminé ({result.status}) sans rapport structuré"],
                "suggested_followups": [],
            }
            if result.status == "stopped":
                sub.report["status"] = "partial"
                sub.report.setdefault("gaps", []).append("Sous-agent arrêté avant la fin")
            self.log.write_text(sub.task_id, "report.json",
                                json.dumps(sub.report, ensure_ascii=False, indent=2) + "\n")
            self.log.event(sub.task_id, "report_submitted", {"status": sub.report["status"]}, parent_id="lead")
            return result


def usage_total(lead: AgentResult, subagents: dict[str, SubAgent], log_dir: Path) -> dict[str, int]:
    """Tokens cumulés de l'agent principal et des sous-agents, relus depuis les événements."""
    total = dict(lead.usage)
    events = log_dir / "events.jsonl"
    if events.exists():
        for line in events.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e["type"] == "agent_ended" and e["agent_id"] in subagents:
                for k, v in e["data"].get("usage", {}).items():
                    total[k] = total.get(k, 0) + v
    return total
