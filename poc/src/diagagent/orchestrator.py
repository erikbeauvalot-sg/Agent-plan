"""Orchestration multi-agents : l'agent principal écrit un plan, lance des sous-agents spécialisés
avec un prompt généré, attend leurs rapports structurés et consolide.

Règles (document d'architecture, section Orchestration) : profondeur 1, sous-agents en parallèle
avec un plafond, budget par sous-agent, contexte isolé (le sous-agent ne voit que son prompt).
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from . import catalog, knowledge, playbooks
from .connectors import alertmanager
from .agent import AgentResult, Budget, CancelToken, LocalTool, LocalToolError, run_agent
from .llm import LLMProvider, ToolSpec
from .llm.base import to_jsonable
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


ACTION_TYPES = ("diagnostic complémentaire", "remédiation", "contournement", "réglage de supervision",
                "ouverture de ticket")
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


def _choice(value: Any, allowed: tuple[str, ...]) -> Any:
    """Valeur autorisée écrite avec une autre casse ou sans accents (« Faible », « remediation »)."""
    if not isinstance(value, str):
        return value
    plain = unicodedata.normalize("NFKD", value.strip().lower()).encode("ascii", "ignore").decode()
    return next((a for a in allowed
                 if unicodedata.normalize("NFKD", a).encode("ascii", "ignore").decode() == plain), value)


def validate_action(action: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in ACTION_SCHEMA["required"] if action.get(k) in (None, "", [])]
    if missing:
        raise LocalToolError(f"Champs manquants : {', '.join(missing)}")
    action = {**action, "type": _choice(action["type"], ACTION_TYPES), "risk": _choice(action["risk"], RISKS)}
    if action["type"] not in ACTION_TYPES:
        raise LocalToolError(f"type doit valoir exactement l'une de ces valeurs : {', '.join(ACTION_TYPES)} "
                             f"(reçu : {str(action['type'])[:60]})")
    if action["risk"] not in RISKS:
        raise LocalToolError(f"risk est un seul mot parmi : {', '.join(RISKS)} ; mets l'explication du risque "
                             f"dans risk_explanation (reçu : {str(action['risk'])[:60]})")
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
        f["evidence"] = _normalize_evidence(f.get("evidence"))
        if not isinstance(f.get("evidence"), list) or not f["evidence"]:
            raise LocalToolError(f"findings[{i}].evidence doit citer au moins un query_ref")
        if f.get("confidence") not in CONFIDENCES:
            raise LocalToolError(f"findings[{i}].confidence doit valoir {', '.join(CONFIDENCES)}")
    report.setdefault("gaps", [])
    report.setdefault("suggested_followups", [])
    return report


def _normalize_evidence(evidence: Any) -> Any:
    """Les modèles rendent souvent une preuve seule en texte, ou des objets {"query_ref": ...} : on les
    ramène à une liste de query_ref plutôt que de refuser le rapport et de coûter un tour."""
    if isinstance(evidence, (str, dict)):
        evidence = [evidence]
    if not isinstance(evidence, list):
        return evidence
    out = []
    for e in evidence:
        if isinstance(e, dict):
            e = e.get("query_ref") or e.get("ref")
        if isinstance(e, str) and e.strip():
            out.append(e.strip().strip("[]"))
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")[:40] or "x"


class Investigation:
    def __init__(self, question: str, hub: ToolHub, log: RunLog, providers: ProviderFactory,
                 poc_cfg: dict[str, Any], category: str | None = None):
        self.question = question
        self.forced_category = category
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
        self.books: dict[str, dict[str, Any]] = {}
        self.category: dict[str, Any] = {}
        self.decision: playbooks.Decision | None = None
        self.rechecked: set[str] = set()  # motifs de relance de la réponse finale déjà utilisés

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
        decision, section = await self.categorize()
        self.decision = decision
        if decision.mode == "clarify":
            return AgentResult(status="needs_clarification", answer=self._clarification_text(decision))
        provider, role_cfg = self._provider("lead")
        result = await run_agent(
            agent_id="lead", provider=provider, system=self.lead_system_prompt(section),
            user_message=self.question, tools=self.hub.tools_for(None), hub=self.hub, log=self.log,
            budget=self.lead_budget, reasoning=role_cfg.get("reasoning"), cancel=self.lead_cancel,
            local_tools=self._lead_tools(), final_check=self._check_final_answer)
        await self._close_pending()
        return result

    def _provider(self, role: str) -> tuple[LLMProvider, dict[str, Any]]:
        """Fournisseur d'un rôle, noté dans le manifest (fournisseur et modèle par rôle d'agent)."""
        provider, cfg = self.providers(role)
        models = self.log.manifest.setdefault("models", {})
        if role not in models:
            models[role] = {"provider": provider.name,
                            "model": cfg.get("model") or cfg.get("deployment") or getattr(provider, "_model", None)}
            self.log.update_manifest(models=models)
        return provider, cfg

    def _check_final_answer(self, text: str) -> str | None:
        """Relance l'agent principal une fois par motif : vagues du playbook jamais lancées, puis actions
        décrites dans la réponse sans propose_action."""
        for motive, check in (("waves", self._missing_waves), ("actions", self._unrecorded_actions)):
            if motive not in self.rechecked and (nudge := check(text)):
                self.rechecked.add(motive)
                return nudge
        return None

    def _missing_waves(self, text: str) -> str | None:
        """Les petits modèles (gpt-oss:20b) font souvent tout eux-mêmes : les étapes du playbook qui
        prévoient des sous-agents ne sont alors jamais lancées. Une étape compte comme lancée si un de
        ses rôles spécialisés l'a été : generic, que le modèle lance pour tout, ne compte pas, et les
        rôles indisponibles sont ignorés."""
        if self.decision is None or self.category.get("mode") not in ("playbook", "combined"):
            return None
        if len(self.subagents) >= self.max_subagents:
            return None
        # Après requalify, seul le nouveau playbook compte.
        current = self.category.get("id")
        categories = self.decision.categories if current in self.decision.categories else [current]
        spawned = {s.role for s in self.subagents.values()}
        missing = []
        for cat in categories:
            for i, step in enumerate(self.books[cat]["steps"], 1):
                roles = [inv["role"] for inv in step.get("parallel", [])
                         if inv["role"] in self.roles and inv["role"] != "generic"]
                if roles and not spawned & set(roles):
                    missing.append(f"{i}. {step['name']} ({', '.join(dict.fromkeys(roles))})")
        if not missing:
            return None
        return ("Le playbook prévoit des vagues de sous-agents que tu n'as pas lancées : "
                + " ; ".join(missing) + ". Lance-les avec spawn_subagent, une étape à la fois (wait_subagents "
                "entre deux), en donnant à chaque sous-agent la période, les entités et ce que tu as déjà "
                "établi ; puis rends ta réponse finale complète. Si une étape est inutile ici, dis pourquoi "
                "dans les Limites au lieu de la lancer.")

    def _unrecorded_actions(self, text: str) -> str | None:
        """Les modèles décrivent souvent leurs actions dans la réponse sans appeler propose_action : elles
        n'arrivent alors pas dans actions.json et ne peuvent pas être revues par un Superviseur."""
        if (self.log.dir / "actions.json").exists():
            return None
        # Titre Markdown ou en gras (« **Actions proposées** »), puis liste ou tableau jusqu'au titre suivant.
        section = re.search(r"^(?:#+\s*|\*\*)Actions propos[ée]es(?:\*\*)?\s*\n(.*?)(?=\n(?:#+\s|\*\*\w)|\Z)",
                            text, re.S | re.I | re.M)
        if not section or not re.search(r"^\s*(?:[-*]|\d+[.)]|#+|\|(?!\s*-))\s*\S", section.group(1), re.M):
            return None
        return ("Ta réponse décrit des actions proposées, mais aucune n'a été enregistrée. Appelle "
                "propose_action pour chacune (une action par appel), puis rends ta réponse finale complète.")

    def lead_system_prompt(self, playbook: str = "") -> str:
        template = (catalog.home() / "prompts" / "lead.md").read_text(encoding="utf-8")
        roles = "\n".join(f"- {r.name} : {r.description}" for r in self.roles.values()) or "- (aucun)"
        return template.format(now=catalog.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                               catalog=catalog.catalog_summary(), roles=roles,
                               max_subagents=self.max_subagents,
                               playbook=playbook or "Aucun playbook : stratégie générique.")

    # Catégorisation (document d'architecture, « Catégorisation des demandes »)

    async def categorize(self) -> tuple[playbooks.Decision, str]:
        # Les catégories en observation (draft) sont proposées au classifieur mais jamais appliquées.
        classifier_usage: dict[str, Any] = {}
        self.books = playbooks.load_playbooks(include=("active", "draft"))
        active = {k: b for k, b in self.books.items() if b["status"] == "active"}
        if self.forced_category:
            if self.forced_category not in active:
                raise ValueError(f"Catégorie inconnue : {self.forced_category}")
            c = playbooks.Classification(self.forced_category, "high", reason="catégorie choisie par l'utilisateur")
            source = "user"
        else:
            self.log.event("lead", "classification_started", {})
            try:
                provider, _ = self._provider("classifier")
            except Exception as e:  # pas de classifieur configuré : stratégie générique
                provider, err = None, f"{type(e).__name__}: {e}"
            if provider is None:
                c = playbooks.Classification(playbooks.FALLBACK, "low", error=f"classifieur indisponible ({err})")
            else:
                similar = knowledge.similar_requests(self.question, self.log.runs_dir)
                c, raw = await asyncio.to_thread(playbooks.classify, provider, self.question, self.books, similar)
                if raw is not None:
                    classifier_usage = {"model": raw.model, "usage": to_jsonable(raw.usage)}
                if raw is not None:
                    self.log.write_text("lead", "classification_response.txt", raw.text or "")
            if c.missing or c.category == playbooks.FALLBACK:
                # Précision demandée alors que la demande nomme l'alerte (« l'alerte SwapUsageHigh »),
                # ou demande non classée : on cherche les alertes connues dans la question.
                names = await asyncio.to_thread(alertmanager.alert_names)
                c = playbooks.alert_fallback(c, self.question, names, self.books)
                completed = playbooks.complete_entities(c, self.question, names)
                if completed:
                    self.log.event("lead", "entities_completed", {m: c.entities[m] for m in completed})
            source = "classifier"
        decision = playbooks.decide(c, self.books)
        self._set_category(c, decision, source)
        self.log.event("lead", "request_classified", {**self.category, "mode": decision.mode, **classifier_usage})
        if decision.mode == "clarify":
            return decision, ""
        section = playbooks.lead_section(decision, c, self.books, set(self.roles))
        seen = knowledge.similar_cases(self.question, c.entities)
        if seen:
            self.log.event("lead", "similar_cases", {"cases": [x["id"] for x in seen]})
            section += "\n\n" + knowledge.render_cases(seen)
        return decision, section

    def _set_category(self, c: playbooks.Classification, decision: playbooks.Decision, source: str) -> None:
        self.category = {
            "id": decision.categories[0], "confidence": c.confidence, "source": source, "mode": decision.mode,
            "playbooks": {cat: self.books[cat]["version"] for cat in decision.categories},
            **{k: v for k, v in c.as_dict().items() if k not in ("category", "confidence")},
        }
        self.log.update_manifest(category=self.category)

    def _clarification_text(self, decision: playbooks.Decision) -> str:
        choices = self.category.get("choices") or []
        text = f"## Précision nécessaire\n{decision.clarification}"
        if choices:
            text += "\n" + "\n".join(f"- {c}" for c in choices)
        return text

    async def _requalify(self, args: dict[str, Any]) -> str:
        target = args.get("category", "")
        if target not in self.books or self.books[target]["status"] != "active":
            active = [k for k, b in self.books.items() if b["status"] == "active"]
            raise LocalToolError(f"Catégorie inconnue : {target}. Catégories : {', '.join(active)}")
        previous = self.category.get("id")
        if target == previous:
            raise LocalToolError(f"La demande est déjà dans la catégorie {target}")
        history = self.category.get("history", []) + [{"from": previous, "reason": args.get("reason", "")}]
        self.category.update(id=target, source="requalify", mode="playbook", history=history,
                             playbooks={target: self.books[target]["version"]})
        self.log.update_manifest(category=self.category)
        self.log.event("lead", "category_changed", {"from": previous, "to": target, "reason": args.get("reason", "")})
        return playbooks.render(self.books[target], set(self.roles))

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
            "requalify": LocalTool(ToolSpec(
                "requalify",
                "Change la catégorie de la demande quand les faits collectés contredisent la catégorie de "
                "départ (une « panne » qui s'avère être une lenteur extrême). Rend le nouveau playbook à suivre.",
                {"type": "object", "properties": {
                    "category": {"type": "string",
                                 "enum": [k for k, b in self.books.items() if b["status"] == "active"]},
                    "reason": {"type": "string", "description": "Faits qui justifient le changement"},
                }, "required": ["category", "reason"]}),
                self._requalify),
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
        # Les modèles rappellent souvent propose_action pour la même action (après un rappel du
        # contrôle final, ou en reformulant) : une seule entrée par titre et cible.
        key = (" ".join(action["title"].lower().split()), action["target"].lower())
        for known in actions:
            if (" ".join(known["title"].lower().split()), known["target"].lower()) == key:
                return json.dumps({"id": known["id"], "status": "déjà enregistrée, rien d'ajouté"},
                                  ensure_ascii=False)
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
                provider, role_cfg = self._provider(role.name)
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


def usage_by_agent(log_dir: Path) -> dict[str, dict[str, Any]]:
    """Tokens et modèle par agent, relus depuis les événements : chaque appel au modèle (llm_call_ended)
    et l'appel du classifieur (request_classified, compté sous « classifier »)."""
    out: dict[str, dict[str, Any]] = {}
    events = log_dir / "events.jsonl"
    for line in events.read_text(encoding="utf-8").splitlines() if events.exists() else []:
        e = json.loads(line)
        if e["type"] == "llm_call_ended" and e["data"].get("usage"):
            agent = e["agent_id"]
        elif e["type"] == "request_classified" and e["data"].get("usage"):
            agent = "classifier"
        else:
            continue
        row = out.setdefault(agent, {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
                                    "calls": 0, "model": None})
        row["calls"] += 1
        row["model"] = e["data"].get("model") or row["model"]
        for k in ("input_tokens", "output_tokens", "reasoning_tokens"):
            row[k] += e["data"]["usage"].get(k) or 0
    return out


def tokens(usage: dict[str, int]) -> int:
    """Tokens facturés : entrée et sortie ; le raisonnement est déjà compté dans la sortie."""
    return (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)


def usage_total(lead: AgentResult, subagents: dict[str, SubAgent], log_dir: Path) -> dict[str, int]:
    """Tokens cumulés de tous les appels au modèle (classifieur, agent principal, sous-agents)."""
    rows = usage_by_agent(log_dir).values()
    if not rows:
        return dict(lead.usage)
    return {k: sum(r[k] for r in rows) for k in ("input_tokens", "output_tokens", "reasoning_tokens")}
