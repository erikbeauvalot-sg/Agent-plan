"""Traçabilité en fichiers : un dossier par investigation sous runs/, sans base de données."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _dump(path: Path, data: Any) -> None:
    """Écriture atomique (fichier temporaire puis renommage) : l'interface web lit manifest.json
    pendant l'investigation et ne doit jamais tomber sur un fichier vidé en cours de réécriture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                                     suffix=".tmp", delete=False) as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(f.name, path)


def _append(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


class RunLog:
    def __init__(self, runs_dir: Path, question: str, user: str, extra: dict[str, Any] | None = None):
        started = datetime.now(timezone.utc)
        self.run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(2)
        self.runs_dir = runs_dir
        self.dir = runs_dir / started.strftime("%Y/%m/%d") / self.run_id
        self._seq = 0
        self._calls: dict[str, int] = {}
        self._lock = threading.Lock()
        self.monitor: Any = None  # SignalMonitor de l'investigation : lit chaque événement écrit
        self.manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION, "run_id": self.run_id, "question": question, "user": user,
            "started_at": _ts(), "status": "running", **(extra or {}),
        }
        _dump(self.dir / "manifest.json", self.manifest)
        (self.dir / "question.md").write_text(question + "\n", encoding="utf-8")

    def update_manifest(self, **fields: Any) -> None:
        self.manifest.update(fields)
        _dump(self.dir / "manifest.json", self.manifest)

    def agent_dir(self, agent_id: str) -> Path:
        return self.dir / "lead" if agent_id == "lead" else self.dir / "subagents" / agent_id

    def event(self, agent_id: str, type_: str, data: dict[str, Any] | None = None,
              parent_id: str | None = None) -> None:
        with self._lock:
            self._seq += 1
            _append(self.dir / "events.jsonl", {"seq": self._seq, "ts": _ts(), "run_id": self.run_id,
                                                "agent_id": agent_id, "parent_id": parent_id,
                                                "type": type_, "data": data or {}})
        if self.monitor is not None:
            self.monitor.observe(agent_id, type_, data or {}, parent_id)

    def write_text(self, agent_id: str, name: str, text: str) -> None:
        path = self.agent_dir(agent_id) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def transcript(self, agent_id: str, entry: dict[str, Any]) -> None:
        _append(self.agent_dir(agent_id) / "transcript.jsonl", {"ts": _ts(), "agent": agent_id, **entry})

    def reserve_call(self, agent_id: str) -> str:
        """Numérote un appel d'outil dans l'ordre où le modèle l'a demandé ; renvoie sa référence
        relative au dossier de l'investigation (calls/NNNN.json)."""
        with self._lock:
            n = self._calls[agent_id] = self._calls.get(agent_id, 0) + 1
        return str((self.agent_dir(agent_id) / "calls" / f"{n:04d}.json").relative_to(self.dir))

    def write_call(self, ref: str, record: dict[str, Any]) -> None:
        _dump(self.dir / ref, {"schema_version": SCHEMA_VERSION, **record})

    def finish(self, status: str, answer: str, usage: dict[str, int]) -> None:
        (self.dir / "analysis.md").write_text(answer + "\n", encoding="utf-8")
        self.manifest.update(status=status, ended_at=_ts(), usage=usage)
        _dump(self.dir / "manifest.json", self.manifest)
        _append(self.runs_dir / "index.jsonl", {
            "run_id": self.run_id, "path": str(self.dir.relative_to(self.runs_dir)),
            "started_at": self.manifest["started_at"], "ended_at": self.manifest["ended_at"],
            "user": self.manifest["user"], "question": self.manifest["question"],
            "category": (self.manifest.get("category") or {}).get("id"),
            "draft_match": (self.manifest.get("category") or {}).get("draft_match"), "status": status,
            "usage": usage, "tool_calls": sum(self._calls.values()),
            # Pour la page d'accueil : modèles, sources et issue de chaque sous-agent sans relire le manifest.
            "models_profile": self.manifest.get("models_profile"), "sources": self.manifest.get("sources"),
            "model": ((self.manifest.get("models") or {}).get("lead") or {}).get("model"),
            "subagents": [{"role": s.get("role"), "status": s.get("status")}
                          for s in (self.manifest.get("subagents") or {}).values()],
        })
