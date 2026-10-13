"""Signaux d'exécution calculés par l'orchestrateur (document d'architecture, « Détection visuelle des
problèmes d'exécution ») : un agent bloqué, en boucle, en erreurs d'outil répétées, près de son budget, un
souci de modèle (refus, quota, bascule de secours), une source lente.

Le moniteur lit chaque événement écrit par RunLog et écrit à son tour `signal_raised` / `signal_cleared`
dans events.jsonl : les signaux restent dans la trace et au rejeu, l'interface les affiche sans les
recalculer. Les seuils se règlent dans config/poc.yaml (section `signals`)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

ENDED = ("agent_ended",)


@dataclass(frozen=True)
class Thresholds:
    stuck_s: float = 120          # aucun événement depuis
    loop_repeats: int = 3         # même outil, mêmes paramètres
    error_streak: int = 3         # erreurs d'outil consécutives
    budget_ratio: float = 0.8     # part du budget d'appels d'outils
    slow_tool_s: float = 10       # appel d'outil au-delà

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> Thresholds:
        cfg = cfg or {}
        known = {k: cfg[k] for k in cls.__dataclass_fields__ if k in cfg}
        return cls(**known)


@dataclass
class _Agent:
    parent: str | None
    last: float
    running: bool = True
    model: str | None = None
    tool_calls: int = 0
    max_tools: int | None = None
    streak: int = 0
    repeats: dict[str, int] = field(default_factory=dict)
    open_calls: dict[str, tuple[float, str, str | None]] = field(default_factory=dict)  # ref → (début, outil, source)
    raised: set[str] = field(default_factory=set)


Emit = Callable[[str, str, dict[str, Any], "str | None"], None]


def _quota(message: str) -> bool:
    m = message.lower()
    return any(w in m for w in ("429", "quota", "rate limit", "rate_limit", "too many requests"))


def _same_model(asked: str | None, got: str | None) -> bool:
    """Le modèle répondu est celui demandé, à une date de version près (gpt-4.1-mini → gpt-4.1-mini-2025-04-14)."""
    if not asked or not got:
        return True
    return got.startswith(asked) or asked.startswith(got)


class SignalMonitor:
    def __init__(self, emit: Emit, thresholds: Thresholds | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.emit = emit
        self.t = thresholds or Thresholds()
        self.clock = clock
        self.agents: dict[str, _Agent] = {}
        self._lock = threading.Lock()

    # Un signal levé est écrit une fois ; il est effacé quand la condition cesse (ou à la fin de l'agent).
    def _raise(self, agent_id: str, kind: str, text: str, level: str = "warn", **data: Any) -> None:
        a = self.agents[agent_id]
        if kind in a.raised:
            return
        a.raised.add(kind)
        self.emit(agent_id, "signal_raised", {"kind": kind, "level": level, "text": text, **data}, a.parent)

    def _clear(self, agent_id: str, kind: str) -> None:
        a = self.agents[agent_id]
        if kind in a.raised:
            a.raised.discard(kind)
            self.emit(agent_id, "signal_cleared", {"kind": kind}, a.parent)

    def observe(self, agent_id: str, type_: str, data: dict[str, Any], parent_id: str | None) -> None:
        if type_.startswith("signal_"):
            return
        with self._lock:
            now = self.clock()
            a = self.agents.get(agent_id)
            if a is None:
                a = self.agents[agent_id] = _Agent(parent=parent_id, last=now)
            a.last = now
            self._clear(agent_id, "stuck")
            if type_ == "agent_started":
                a.running, a.model = True, data.get("model")
                a.max_tools = data.get("max_tool_calls")
            elif type_ == "tool_call_started":
                key = f"{data.get('tool')}:{json.dumps(data.get('arguments'), sort_keys=True, ensure_ascii=False)}"
                a.repeats[key] = n = a.repeats.get(key, 0) + 1
                args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
                a.open_calls[str(data.get("ref"))] = (now, str(data.get("tool")), args.get("source"))
                if n >= self.t.loop_repeats:
                    self._raise(agent_id, "loop", f"boucle : {data.get('tool')} appelé {n} fois avec les mêmes "
                                "paramètres", tool=data.get("tool"), count=n)
            elif type_ == "tool_call_ended":
                ref = str(data.get("ref"))
                started, tool, source = a.open_calls.pop(ref, (now, str(data.get("tool")), None))
                a.tool_calls += 1
                duration = data.get("duration_s") or (now - started)
                if duration > self.t.slow_tool_s:
                    self._slow(agent_id, ref, tool, source, duration)
                a.streak = a.streak + 1 if data.get("is_error") else 0
                if a.streak >= self.t.error_streak:
                    self._raise(agent_id, "errors", f"{a.streak} erreurs d'outil de suite", "bad",
                                count=a.streak, tool=data.get("tool"), ref=ref)
                elif not data.get("is_error"):
                    self._clear(agent_id, "errors")
                if a.max_tools and a.tool_calls / a.max_tools > self.t.budget_ratio:
                    self._raise(agent_id, "budget", f"budget : {a.tool_calls}/{a.max_tools} appels d'outils",
                                "bad" if a.tool_calls >= a.max_tools else "warn",
                                used=a.tool_calls, max=a.max_tools)
            elif type_ == "llm_call_ended":
                self._model(agent_id, a, data)
            elif type_ in ENDED:
                a.running = False
                for kind in sorted(a.raised):
                    if not kind.startswith("slow:"):
                        self._clear(agent_id, kind)

    def _slow(self, agent_id: str, ref: str, tool: str, source: str | None, duration: float) -> None:
        where = f" ({source})" if source else ""
        self._raise(agent_id, f"slow:{ref}", f"source lente : {tool}{where} {duration:.0f} s", ref=ref, tool=tool,
                    source=source, duration_s=round(duration, 1))

    def _model(self, agent_id: str, a: _Agent, data: dict[str, Any]) -> None:
        if data.get("error"):
            message = str(data.get("message") or "")
            kind = data["error"]
            reason = ("refus du modèle (filtre de contenu)" if kind == "refusal"
                      else "quota ou limite de débit atteinte" if _quota(message)
                      else f"appel au modèle en échec ({kind})")
            self._raise(agent_id, "model", reason, "bad", reason=kind, message=message[:200])
            return
        if data.get("stop_reason") == "refusal":
            self._raise(agent_id, "model", "refus du modèle (filtre de contenu)", "bad", reason="refusal")
            return
        if not _same_model(a.model, data.get("model")):
            self._raise(agent_id, "model", f"bascule de secours : {data.get('model')} au lieu de {a.model}",
                        reason="fallback", model=data.get("model"))
            return
        self._clear(agent_id, "model")

    def tick(self) -> None:
        """Contrôles liés au temps (appelé régulièrement pendant l'investigation) : agent sans événement
        depuis stuck_s, appel d'outil encore ouvert au-delà de slow_tool_s. L'agent principal qui attend ses
        sous-agents n'est pas bloqué tant que l'un d'eux travaille."""
        with self._lock:
            now = self.clock()
            latest = max((x.last for x in self.agents.values()), default=now)
            for agent_id, a in self.agents.items():
                if not a.running:
                    continue
                last = max(a.last, latest) if agent_id == "lead" else a.last
                idle = now - last
                if idle > self.t.stuck_s:
                    self._raise(agent_id, "stuck", f"bloqué : aucun événement depuis {idle:.0f} s",
                                idle_s=round(idle))
                for ref, (started, tool, source) in list(a.open_calls.items()):
                    if now - started > self.t.slow_tool_s:
                        self._slow(agent_id, ref, tool, source, now - started)
