"""Adaptateur `replay` : rejoue les réponses du modèle enregistrées dans une investigation passée.

Sans appel réseau ni coût, il refait passer la même suite de décisions dans l'orchestrateur et les
outils actuels : un changement de serveur MCP, de catalogue ou d'orchestration se vérifie ainsi sur
de vraies investigations. Chaque agent est reconnu à son premier message (le prompt de tâche d'un
sous-agent commence par « # Tâche Tnn-… »).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from .base import Capabilities, LLMError, LLMRequest, LLMResponse, ToolCall, Usage

TASK = re.compile(r"^# Tâche (T\d{2}-\S+)")


def _load(transcript: Path) -> list[LLMResponse]:
    out = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["direction"] != "response":
            continue
        out.append(LLMResponse(
            text=e["content"]["text"],
            tool_calls=[ToolCall(c["id"], c["name"], c["arguments"]) for c in e["content"]["tool_calls"]],
            stop_reason=e["stop_reason"], usage=Usage(**(e.get("usage") or {})),
            model=f"replay:{e.get('model', '')}", request_id=e.get("request_id")))
    return out


class ReplayProvider:
    name = "replay"

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self._queues: dict[str, list[LLMResponse]] = {"lead": _load(run_dir / "lead" / "transcript.jsonl")}
        for sub in sorted((run_dir / "subagents").glob("*/transcript.jsonl")) if (run_dir / "subagents").exists() else []:
            self._queues[sub.parent.name] = _load(sub)
        self._lock = threading.Lock()

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def agent_of(self, request: LLMRequest) -> str:
        first = request.messages[0].content if request.messages else ""
        m = TASK.match(first)
        return m.group(1) if m else "lead"

    def complete(self, request: LLMRequest) -> LLMResponse:
        agent = self.agent_of(request)
        with self._lock:
            queue = self._queues.get(agent)
            if not queue:
                raise LLMError("fatal", f"Plus de réponse enregistrée pour {agent} : l'investigation "
                                        f"rejouée a divergé de l'originale")
            return queue.pop(0)

    def remaining(self) -> dict[str, int]:
        return {a: len(q) for a, q in self._queues.items() if q}
