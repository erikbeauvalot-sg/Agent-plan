"""Client MCP de l'orchestrateur : lance les serveurs configurés et route les appels d'outils."""

from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import Client, StdioServerParameters

from .catalog import enabled, home
from .llm import ToolSpec


class ToolResult:
    def __init__(self, content: str, is_error: bool, server: str):
        self.content = content
        self.is_error = is_error
        self.server = server


class ToolHub:
    """Connexions aux serveurs MCP ; un nom d'outil appartient à un seul serveur."""

    def __init__(self, servers_cfg: dict[str, dict[str, Any]]):
        self._servers_cfg = servers_cfg
        self._stack = AsyncExitStack()
        self._clients: dict[str, Client] = {}
        self._owner: dict[str, str] = {}
        self.specs: dict[str, ToolSpec] = {}

    async def __aenter__(self) -> "ToolHub":
        env = {**os.environ, "DIAGAGENT_HOME": str(home())}
        for name, cfg in self._servers_cfg.items():
            if not enabled(cfg):
                continue
            params = StdioServerParameters(command=cfg.get("command", sys.executable),
                                           args=cfg.get("args", ["-m", cfg["module"]]), env=env)
            client = await self._stack.enter_async_context(Client(params))
            self._clients[name] = client
            for tool in (await client.list_tools()).tools:
                if tool.name in self._owner:
                    raise ValueError(f"Outil {tool.name} exposé par {self._owner[tool.name]} et {name}")
                self._owner[tool.name] = name
                schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
                self.specs[tool.name] = ToolSpec(tool.name, tool.description or "", schema)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.aclose()

    def tools_for(self, servers: list[str] | None) -> list[ToolSpec]:
        """Outils visibles par un rôle : ceux des serveurs autorisés (tous si None)."""
        return [s for n, s in self.specs.items() if servers is None or self._owner[n] in servers]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name not in self._owner:
            return ToolResult(f"Outil inconnu : {name}", True, "-")
        server = self._owner[name]
        try:
            result = await self._clients[server].call_tool(name, arguments)
        except Exception as e:  # erreur de transport : rendue au modèle comme erreur d'outil
            return ToolResult(f"{type(e).__name__}: {e}", True, server)
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            text = json.dumps(structured, ensure_ascii=False)
        else:
            text = "\n".join(getattr(c, "text", "") for c in getattr(result, "content", []) or [])
        return ToolResult(text, bool(getattr(result, "is_error", False)), server)
