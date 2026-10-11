"""Boucle d'agent écrite dans l'orchestrateur : chaque appel au modèle et chaque appel d'outil
passe ici, est tracé dans runs/ et soumis au budget avant exécution."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .llm import LLMError, LLMProvider, LLMRequest, LLMResponse, Message, ToolSpec
from .llm.base import to_jsonable
from .runlog import RunLog
from .tools import ToolHub

MAX_TOOL_RESULT_CHARS = 12_000
MAX_EMPTY_RETRIES = 2  # réponses vides consécutives relancées avant d'abandonner
MAX_FINAL_CHECKS = 5  # relances de la réponse finale (vagues, changements, faits des rapports, actions, tailles), une par motif
MALFORMED_TOOL_CALL = "error parsing tool call"  # erreur d'Ollama sur un appel d'outil illisible
TEXT_CALL_NUDGE = ("Tu as écrit un appel d'outil dans le texte de ta réponse au lieu de l'appeler. Appelle "
                   "l'outil, ou rends ta réponse finale en Markdown.")
EMPTY_NUDGE = ("Ta réponse est vide : ni texte, ni appel d'outil. Continue : appelle l'outil que tu avais "
               "prévu, ou rends ta réponse finale.")


@dataclass
class Budget:
    max_tool_calls: int = 20
    max_turns: int = 25


@dataclass
class AgentResult:
    status: str  # completed | partial | stopped | failed
    answer: str
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0,
                                                                   "reasoning_tokens": 0})
    tool_calls: int = 0


@dataclass
class LocalTool:
    """Outil interne à l'orchestrateur (pas MCP) : lancer un sous-agent, rendre un rapport…
    `terminal` : un appel réussi termine l'agent (submit_report)."""
    spec: ToolSpec
    handler: Callable[[dict[str, Any]], Awaitable[str]]
    terminal: bool = False


class LocalToolError(Exception):
    """Erreur rendue au modèle comme résultat d'outil en erreur."""


class CancelToken:
    """Jeton d'annulation vérifié avant chaque appel au modèle et chaque appel d'outil."""

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._wrap_up = asyncio.Event()

    def cancel(self) -> None:
        """Arrêt sans synthèse."""
        self._event.set()

    def wrap_up(self) -> None:
        """Arrêt propre : l'agent rend tout de suite une réponse partielle, sans nouvel appel d'outil."""
        self._wrap_up.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def wrapping_up(self) -> bool:
        return self._wrap_up.is_set()


async def run_agent(*, agent_id: str, provider: LLMProvider, system: str, user_message: str,
                    tools: list[ToolSpec], hub: ToolHub, log: RunLog, budget: Budget,
                    reasoning: str | None = None, max_tokens: int = 4000,
                    cancel: CancelToken | None = None, local_tools: dict[str, LocalTool] | None = None,
                    final_tools: tuple[str, ...] = (), parent_id: str | None = None,
                    final_check: Callable[[str], str | None] | None = None,
                    progress_check: Callable[[list[str]], str | None] | None = None,
                    budget_message: str = "Budget d'appels d'outils atteint : rends maintenant ta réponse "
                                          "finale avec ce que tu as, en indiquant ce qui manque.") -> AgentResult:
    cancel = cancel or CancelToken()
    local_tools = local_tools or {}
    all_tools = tools + [t.spec for t in local_tools.values()]
    messages = [Message("user", user_message)]
    result = AgentResult(status="completed", answer="")
    empty_retries = 0
    final_checks = 0
    log.write_text(agent_id, "system_prompt.md", system)
    log.event(agent_id, "agent_started", {"provider": provider.name, "model": getattr(provider, "_model", None),
                                           "tools": [t.name for t in all_tools],
                                           "max_tool_calls": budget.max_tool_calls}, parent_id=parent_id)

    for turn in range(1, budget.max_turns + 1):
        if cancel.cancelled:
            result.status = "stopped"
            break
        wrapping_up = cancel.wrapping_up
        out_of_budget = wrapping_up or result.tool_calls >= budget.max_tool_calls or turn == budget.max_turns
        if wrapping_up:
            messages.append(Message("user", "Arrêt demandé par l'opérateur : " + budget_message))
        elif out_of_budget:
            messages.append(Message("user", budget_message))
        offered = [t for t in all_tools if t.name in final_tools] if out_of_budget else all_tools
        request = LLMRequest(system=system, messages=list(messages), tools=offered,
                             max_tokens=max_tokens, reasoning=reasoning)  # type: ignore[arg-type]
        response = await _complete(agent_id, provider, request, log)
        if response is None:
            result.status = "failed"
            result.answer = "L'appel au modèle a échoué ; voir events.jsonl."
            break
        result.usage["input_tokens"] += response.usage.input_tokens
        result.usage["output_tokens"] += response.usage.output_tokens
        result.usage["reasoning_tokens"] += response.usage.reasoning_tokens
        messages.append(Message("assistant", response.text, response.tool_calls, native=response.native))

        if response.stop_reason == "refusal":
            result.status = "failed"
            result.answer = "Le modèle a refusé de répondre (filtre de contenu)."
            break
        text_call = not response.tool_calls and _looks_like_tool_call(response.text, offered)
        if not response.tool_calls and (not response.text.strip() or text_call):
            # gpt-oss s'arrête parfois après avoir raisonné, sans texte ni appel d'outil, ou écrit l'appel
            # d'outil dans son texte : ni l'un ni l'autre ne doit passer pour une réponse finale.
            log.event(agent_id, "empty_response", {"retry": empty_retries + 1, "tool_call_as_text": text_call})
            if empty_retries < MAX_EMPTY_RETRIES and not cancel.cancelled:
                empty_retries += 1
                if not response.text.strip():
                    # Un message assistant vide renvoyé tel quel fait refuser toute la conversation par Ollama
                    # (« invalid message content type: <nil> ») : on ne le garde pas dans l'historique.
                    messages.pop()
                messages.append(Message("user", TEXT_CALL_NUDGE if text_call else EMPTY_NUDGE))
                continue
            result.status = "failed"
            result.answer = "Le modèle a rendu des réponses vides ; voir events.jsonl."
            break
        if not response.tool_calls and final_check and not out_of_budget and final_checks < MAX_FINAL_CHECKS:
            # Contrôle de la réponse finale : par exemple des actions décrites dans le texte sans avoir été
            # enregistrées avec propose_action. Le contrôle ne relance pas deux fois pour le même motif.
            final_checks += 1
            nudge = final_check(response.text)
            if nudge:
                log.event(agent_id, "final_answer_rechecked", {"reason": nudge[:200]})
                messages.append(Message("user", nudge))
                continue
        if not response.tool_calls:
            result.answer = response.text
            if out_of_budget:
                result.status = "stopped" if wrapping_up else "partial"
            break
        if cancel.cancelled:
            result.status = "stopped"
            break
        # La limite de relances porte sur les ratés consécutifs : un raté isolé, rattrapé, ne compte plus.
        empty_retries = 0
        refs = [log.reserve_call(agent_id) for _ in response.tool_calls]
        results = await asyncio.gather(*(_call_tool(agent_id, c, ref, hub, log, local_tools)
                                         for c, ref in zip(response.tool_calls, refs)))
        result.tool_calls += len(response.tool_calls)
        finished = False
        for call, (content, ok) in zip(response.tool_calls, results):
            messages.append(Message("tool", content, tool_call_id=call.id))
            if ok and call.name in local_tools and local_tools[call.name].terminal:
                finished = True
        if finished:
            result.answer = response.text
            if out_of_budget:
                result.status = "stopped" if wrapping_up else "partial"
            break
        if wrapping_up:
            result.status = "stopped"
            result.answer = result.answer or response.text
            break
        if progress_check and (reminder := progress_check([c.name for c in response.tool_calls])):
            # Rappel en cours de route (par exemple les vagues du playbook), avant que le budget ne s'épuise.
            log.event(agent_id, "progress_reminder", {"reason": reminder[:200]}, parent_id=parent_id)
            messages.append(Message("user", reminder))
    else:
        result.status = "partial"

    if result.status == "stopped" and not result.answer:
        result.answer = "Investigation arrêtée avant la fin."
    log.event(agent_id, "agent_ended", {"status": result.status, "tool_calls": result.tool_calls,
                                         "usage": result.usage}, parent_id=parent_id)
    return result


async def _complete(agent_id: str, provider: LLMProvider, request: LLMRequest,
                    log: RunLog) -> LLMResponse | None:
    log.event(agent_id, "llm_call_started", {"messages": len(request.messages)})
    log.transcript(agent_id, {"direction": "request", "provider": provider.name,
                              "request": to_jsonable(request)})
    for attempt in range(3):
        started = time.monotonic()
        try:
            response = await asyncio.to_thread(provider.complete, request)
        except LLMError as e:
            log.event(agent_id, "llm_call_ended", {"error": e.kind, "message": str(e)[:500]})
            if MALFORMED_TOOL_CALL in str(e):
                # Le serveur n'a pas pu lire l'appel d'outil produit par le modèle : renvoyer la même requête
                # redonne souvent le même charabia. On rend une réponse vide, que la boucle relance avec une
                # consigne (comme une réponse vide du modèle).
                return LLMResponse(text="", tool_calls=[], stop_reason="end",
                                   provider_raw={"malformed_tool_call": str(e)[:500]})
            if e.kind == "retryable" and attempt < 2:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            return None
        duration = round(time.monotonic() - started, 3)
        log.transcript(agent_id, {
            "direction": "response", "model": response.model, "request_id": response.request_id,
            "usage": to_jsonable(response.usage), "stop_reason": response.stop_reason,
            "duration_s": duration, "content": {"text": response.text,
                                                "tool_calls": to_jsonable(response.tool_calls)},
            "provider_raw": response.provider_raw,
        })
        log.event(agent_id, "llm_call_ended", {"stop_reason": response.stop_reason, "duration_s": duration,
                                                "model": response.model, "usage": to_jsonable(response.usage)})
        return response
    return None


async def _call_tool(agent_id: str, call: Any, ref: str, hub: ToolHub, log: RunLog,
                     local_tools: dict[str, LocalTool]) -> tuple[str, bool]:
    """Exécute un appel (outil interne ou MCP), le trace et renvoie (contenu pour le modèle, succès)."""
    log.event(agent_id, "tool_call_started", {"tool": call.name, "ref": ref, "arguments": call.arguments})
    started = time.monotonic()
    if call.name in local_tools:
        server = "orchestrator"
        try:
            content, is_error = await local_tools[call.name].handler(call.arguments), False
        except (LocalToolError, KeyError, TypeError, ValueError) as e:
            content, is_error = f"{type(e).__name__}: {e}", True
    else:
        res = await hub.call(call.name, call.arguments)
        server, content, is_error = res.server, res.content, res.is_error
    duration = round(time.monotonic() - started, 3)
    log.write_call(ref, {"tool": call.name, "server": server, "input": call.arguments,
                         "output": _maybe_json(content), "is_error": is_error, "duration_s": duration})
    log.event(agent_id, "tool_call_ended", {"tool": call.name, "ref": ref, "is_error": is_error,
                                             "duration_s": duration})
    if len(content) > MAX_TOOL_RESULT_CHARS:
        content = content[:MAX_TOOL_RESULT_CHARS] + f"\n[… résultat tronqué, complet dans {ref}]"
    prefix = "ERREUR D'OUTIL : " if is_error else ""
    return f"[query_ref: {ref}]\n{prefix}{content}", not is_error


def _looks_like_tool_call(text: str, tools: list[ToolSpec]) -> bool:
    """Le texte n'est qu'un objet JSON qui contient les paramètres obligatoires d'un des outils offerts."""
    stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return False
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    for t in tools:
        required = set((t.parameters or {}).get("required", []))
        if required and required <= set(data):
            return True
    return False


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
