"""Passerelle web : authentification, lancement des investigations, flux temps réel, arrêt d'agent.

Le front ne voit que ce qui est écrit dans runs/ : l'état affiché est reconstruit à partir de
events.jsonl, relu et poussé en Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from diagagent import catalog, knowledge, learning, playbooks
from diagagent.orchestrator import Investigation, ProviderFactory
from diagagent.runlog import RunLog, _append, _dump, _ts

from .auth import AuthProvider, FileUserStore, Sessions, User, audit

STATIC = Path(__file__).parent / "static"
COOKIE = "diagagent_session"
CSRF_HEADER = "x-diagagent"
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{4}$")
AGENT_ID = re.compile(r"^(lead|T\d{2}-[a-z]+-[a-z0-9.\-]+)$")
POLL_S = 0.4


@dataclass
class LiveRun:
    log: RunLog
    user: str
    investigation: Investigation | None = None
    task: asyncio.Task[Any] | None = None
    error: str | None = None


@dataclass
class RunManager:
    """Investigations en cours dans ce processus (pour l'arrêt) ; les terminées se relisent sur disque."""
    providers: Callable[[], ProviderFactory]
    live: dict[str, LiveRun] = field(default_factory=dict)

    async def start(self, question: str, user: User, category: str | None = None) -> str:
        from diagagent.cli import ask

        started: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        holder: dict[str, LiveRun] = {}

        def on_started(log: RunLog, inv: Investigation) -> None:
            run = holder.setdefault("run", LiveRun(log, user.login))
            run.investigation = inv
            self.live[log.run_id] = run
            if not started.done():
                started.set_result(log.run_id)

        async def go() -> None:
            try:
                await ask(question, providers=self.providers(), user=user.login, on_started=on_started,
                          category=category)
            except Exception as e:  # erreur de démarrage (modèle, serveurs MCP) : visible dans l'interface
                if not started.done():
                    started.set_exception(e)
                elif "run" in holder:
                    holder["run"].error = f"{type(e).__name__}: {e}"
                    holder["run"].log.event("lead", "run_failed", {"error": holder["run"].error})
                    holder["run"].log.finish("failed", f"Erreur : {holder['run'].error}", {})

        task = asyncio.create_task(go())
        run_id = await started
        self.live[run_id].task = task
        return run_id


class LoginBody(BaseModel):
    login: str
    password: str


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=4000)
    category: str | None = None


class CategoryBody(BaseModel):
    category: str


class FeedbackBody(BaseModel):
    verdict: str
    cause: str = Field(default="", max_length=2000)
    comment: str = Field(default="", max_length=2000)
    create_case: bool = False
    resolution: str = Field(default="", max_length=2000)


class ShareBody(BaseModel):
    shared: bool


class DecisionBody(BaseModel):
    accept: bool
    comment: str = Field(default="", max_length=2000)


def runs_dir() -> Path:
    import yaml

    poc = yaml.safe_load((catalog.home() / "config" / "poc.yaml").read_text(encoding="utf-8"))
    return catalog.runs_dir(poc)


def run_path(run_id: str) -> Path:
    if not RUN_ID.match(run_id):
        raise HTTPException(404, "Investigation inconnue")
    path = runs_dir() / run_id[0:4] / run_id[4:6] / run_id[6:8] / run_id
    if not (path / "manifest.json").exists():
        raise HTTPException(404, "Investigation inconnue")
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def read_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def create_app(providers: Callable[[], ProviderFactory] | None = None, users: AuthProvider | None = None,
               sessions: Sessions | None = None, secure_cookie: bool = False) -> FastAPI:
    if providers is None:
        from diagagent.cli import default_providers
        providers = default_providers
    users = users or FileUserStore()
    sessions = sessions or Sessions()
    manager = RunManager(providers)
    app = FastAPI(title="Agent de diagnostic (POC)", docs_url=None, redoc_url=None)
    app.state.manager = manager

    def set_cookie(response: Response, token: str) -> None:
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=secure_cookie, path="/")

    def current_user(request: Request, response: Response) -> User:
        verified = sessions.verify(request.cookies.get(COOKIE))
        user = users.get(verified[0]) if verified else None
        if user is None:
            raise HTTPException(401, "Session absente ou expirée")
        if request.method != "GET" and request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(403, "En-tête anti-falsification manquant")
        set_cookie(response, sessions.issue(user.id, verified[1]))  # renouvellement tant qu'actif
        return user

    def require(user: User, permission: str) -> None:
        if not user.can(permission):
            raise HTTPException(403, "Fonction non autorisée pour votre rôle")

    def can_view(user: User, manifest: dict[str, Any]) -> bool:
        return (user.can("view_all") or (user.can("view_own") and manifest.get("user") == user.login)
                or (user.can("view_shared") and bool(manifest.get("shared"))))

    def can_details(user: User, manifest: dict[str, Any]) -> bool:
        return user.can("details_all") or (user.can("details_own") and manifest.get("user") == user.login)

    def load_run(user: User, run_id: str) -> tuple[Path, dict[str, Any]]:
        path = run_path(run_id)
        manifest = read_json(path / "manifest.json")
        if not can_view(user, manifest):
            raise HTTPException(404, "Investigation inconnue")
        return path, manifest

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict[str, Any]:
        user = users.authenticate(body.login, body.password)
        source = request.client.host if request.client else None
        if user is None:
            audit(None, "login_failed", {"login": body.login}, source)
            raise HTTPException(401, "Identifiant ou mot de passe incorrect (compte verrouillé après 5 échecs)")
        audit(user, "login", source=source)
        set_cookie(response, sessions.issue(user.id))
        return user.public()

    @app.post("/api/logout")
    def logout(response: Response, user: User = Depends(current_user)) -> dict[str, str]:
        audit(user, "logout")
        response.delete_cookie(COOKIE, path="/")
        return {"status": "ok"}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)) -> dict[str, Any]:
        # Heure de référence figée (serve --now) : les questions portent sur cette date, pas sur maintenant.
        return {**user.public(), "reference_time": os.environ.get("DIAGAGENT_NOW")}

    @app.post("/api/runs")
    async def ask_question(body: AskBody, user: User = Depends(current_user)) -> dict[str, str]:
        require(user, "ask")
        if body.category and body.category not in playbooks.load_playbooks():
            raise HTTPException(400, f"Catégorie inconnue : {body.category}")
        try:
            run_id = await manager.start(body.question.strip(), user, body.category)
        except Exception as e:
            raise HTTPException(502, f"Impossible de démarrer l'investigation : {type(e).__name__}: {e}") from e
        audit(user, "ask", {"run_id": run_id, "category": body.category})
        return {"run_id": run_id}

    @app.get("/api/categories")
    def categories(user: User = Depends(current_user)) -> list[dict[str, Any]]:
        return [{"id": b["id"], "version": b["version"], "description": " ".join(b["description"].split())}
                for b in playbooks.load_playbooks().values()]

    @app.post("/api/runs/{run_id}/category")
    def correct_category(run_id: str, body: CategoryBody, user: User = Depends(current_user)) -> dict[str, Any]:
        """Correction de catégorie par l'utilisateur : tracée dans le manifest et dans
        runs/feedback/categories.jsonl, qui alimente l'apprentissage. L'investigation n'est pas relancée."""
        path, manifest = load_run(user, run_id)
        if not (user.can("stop_all") or manifest.get("user") == user.login):
            raise HTTPException(403, "Seul l'auteur de la question ou un administrateur peut corriger la catégorie")
        if body.category not in playbooks.load_playbooks():
            raise HTTPException(400, f"Catégorie inconnue : {body.category}")
        correction = {"category": body.category, "by": user.login, "at": _ts()}
        live = manager.live.get(run_id)
        if live and live.investigation and manifest.get("status") == "running":
            # L'investigation en cours tient le manifest en mémoire : on corrige sa catégorie à elle.
            category = live.investigation.category
            category["correction"] = correction
            live.log.update_manifest(category=category)
        else:
            category = {**(manifest.get("category") or {}), "correction": correction}
            manifest["category"] = category
            _dump(path / "manifest.json", manifest)
        _append(runs_dir() / "feedback" / "categories.jsonl", {
            "run_id": run_id, "question": manifest.get("question"), "from": category.get("id"),
            "to": body.category, "by": user.login, "at": correction["at"]})
        audit(user, "correct_category", {"run_id": run_id, "category": body.category})
        return {"category": category}

    @app.post("/api/runs/{run_id}/feedback")
    def feedback(run_id: str, body: FeedbackBody, user: User = Depends(current_user)) -> dict[str, Any]:
        """Avis sur le diagnostic ; avec une cause confirmée, l'investigation peut devenir un cas."""
        path, manifest = load_run(user, run_id)
        if not (user.can("stop_all") or manifest.get("user") == user.login):
            raise HTTPException(403, "Seul l'auteur de la question, un superviseur ou un administrateur donne un avis")
        if manifest.get("status") == "running":
            raise HTTPException(409, "Investigation en cours")
        try:
            result: dict[str, Any] = {"feedback": knowledge.record_feedback(
                path, runs_dir(), body.verdict, user.login, body.cause, body.comment)}
            if body.create_case:
                if body.verdict != "utile":
                    raise ValueError("Seul un diagnostic jugé utile devient un cas")
                result["case"] = knowledge.create_case(path, user.login, body.cause, body.resolution)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        audit(user, "feedback", {"run_id": run_id, "verdict": body.verdict, "case": body.create_case})
        return result

    @app.get("/api/indicators")
    def indicators(user: User = Depends(current_user)) -> dict[str, Any]:
        require(user, "view_indicators")
        return learning.indicators(runs_dir())

    @app.get("/api/proposals")
    def proposals(user: User = Depends(current_user)) -> list[dict[str, Any]]:
        if not (user.can("review") or user.can("view_indicators")):
            raise HTTPException(403, "Accès réservé aux superviseurs et administrateurs")
        return sorted(learning.list_proposals(), key=lambda p: (p["status"] != "pending", p["id"]))

    @app.post("/api/proposals/{proposal_id}/decision")
    def decide(proposal_id: str, body: DecisionBody, user: User = Depends(current_user)) -> dict[str, Any]:
        require(user, "review")
        from diagagent.orchestrator import load_roles

        try:
            p = learning.decide(proposal_id, body.accept, user.login, body.comment, roles=set(load_roles()))
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        audit(user, "proposal_decision", {"proposal": proposal_id, "status": p["status"]})
        return p

    @app.get("/api/runs")
    def list_runs(user: User = Depends(current_user)) -> list[dict[str, Any]]:
        index = runs_dir() / "index.jsonl"
        done = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()] if index.exists() else []
        finished = {r["run_id"] for r in done}
        running = [{"run_id": rid, "question": r.log.manifest["question"], "user": r.user,
                    "started_at": r.log.manifest["started_at"], "status": "running",
                    "category": (r.log.manifest.get("category") or {}).get("id")}
                   for rid, r in manager.live.items() if rid not in finished]
        shared = set()
        if not user.can("view_all"):  # les investigations partagées se lisent dans leur manifest
            shared = {r["run_id"] for r in done if (read_json(runs_dir() / r["path"] / "manifest.json") or {}).get("shared")}
        rows = [r for r in running + done if can_view(user, {**r, "shared": r["run_id"] in shared})]
        return sorted(rows, key=lambda r: r["started_at"], reverse=True)[:100]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
        path, manifest = load_run(user, run_id)
        return {"manifest": manifest, "plan": read_text(path / "plan.md"),
                "analysis": read_text(path / "analysis.md"), "actions": read_json(path / "actions.json") or [],
                "can_details": can_details(user, manifest),
                "can_share": user.can("share_all") or (user.can("share_own") and manifest.get("user") == user.login),
                "can_stop": manifest.get("status") == "running" and run_id in manager.live
                and (user.can("stop_all") or (user.can("stop_own") and manifest.get("user") == user.login))}

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, user: User = Depends(current_user)) -> StreamingResponse:
        path, _ = load_run(user, run_id)
        last = int(request.headers.get("last-event-id") or 0)

        async def stream() -> AsyncIterator[str]:
            sent = last
            idle = 0
            while True:
                lines = (path / "events.jsonl").read_text(encoding="utf-8").splitlines() \
                    if (path / "events.jsonl").exists() else []
                for line in lines[sent:]:
                    sent += 1
                    yield f"id: {sent}\nevent: agent\ndata: {line}\n\n"
                manifest = read_json(path / "manifest.json") or {}
                if manifest.get("status") != "running":
                    yield f"event: end\ndata: {json.dumps({'status': manifest.get('status')})}\n\n"
                    return
                if await request.is_disconnected():
                    return
                idle += 1
                if idle % 25 == 0:
                    yield ": ping\n\n"
                await asyncio.sleep(POLL_S)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/runs/{run_id}/agents/{agent_id}")
    def agent_detail(run_id: str, agent_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
        path, manifest = load_run(user, run_id)
        if not can_details(user, manifest):
            raise HTTPException(403, "Prompts, transcripts et appels d'outils non visibles pour votre rôle")
        if not AGENT_ID.match(agent_id):
            raise HTTPException(404, "Agent inconnu")
        adir = path / "lead" if agent_id == "lead" else path / "subagents" / agent_id
        if not adir.exists():
            raise HTTPException(404, "Agent inconnu")
        calls = []
        for f in sorted((adir / "calls").glob("*.json")) if (adir / "calls").exists() else []:
            c = read_json(f)
            out = json.dumps(c.get("output"), ensure_ascii=False)
            calls.append({"ref": str(f.relative_to(path)), "tool": c["tool"], "input": c["input"],
                          "is_error": c["is_error"], "duration_s": c["duration_s"],
                          "output": out[:4000] + ("…" if len(out) > 4000 else "")})
        transcript = []
        if (adir / "transcript.jsonl").exists():
            for line in (adir / "transcript.jsonl").read_text(encoding="utf-8").splitlines():
                e = json.loads(line)
                if e["direction"] == "response":
                    transcript.append({"ts": e["ts"], "text": e["content"]["text"][:2000],
                                       "tool_calls": [c["name"] for c in e["content"]["tool_calls"]],
                                       "usage": e.get("usage"), "stop_reason": e.get("stop_reason")})
        return {"agent_id": agent_id, "prompt": read_text(adir / "prompt.md"),
                "system_prompt": read_text(adir / "system_prompt.md"), "report": read_json(adir / "report.json"),
                "calls": calls, "responses": transcript}

    @app.post("/api/runs/{run_id}/agents/{agent_id}/stop")
    def stop(run_id: str, agent_id: str, kill: bool = False, user: User = Depends(current_user)) -> dict[str, Any]:
        path, manifest = load_run(user, run_id)
        own = manifest.get("user") == user.login
        if not (user.can("stop_all") or (user.can("stop_own") and own)):
            raise HTTPException(403, "Vous ne pouvez arrêter que vos propres investigations")
        if kill and not user.can("kill"):
            raise HTTPException(403, "Arrêt immédiat réservé au superviseur et à l'administrateur")
        live = manager.live.get(run_id)
        if live is None or live.investigation is None or manifest.get("status") != "running":
            raise HTTPException(409, "Investigation terminée")
        if kill:
            live.investigation.kill(by=user.login)
            ok = True
        else:
            ok = live.investigation.stop_agent(agent_id, by=user.login)
        if not ok:
            raise HTTPException(409, "Agent déjà terminé ou inconnu")
        audit(user, "stop", {"run_id": run_id, "agent_id": agent_id, "kill": kill})
        return {"status": "stopping"}

    @app.post("/api/runs/{run_id}/share")
    def share(run_id: str, body: ShareBody, user: User = Depends(current_user)) -> dict[str, Any]:
        """Partage avec les Lecteurs : l'investigation devient lisible par tout utilisateur connecté."""
        path, manifest = load_run(user, run_id)
        if not (user.can("share_all") or (user.can("share_own") and manifest.get("user") == user.login)):
            raise HTTPException(403, "Seul l'auteur, un superviseur ou un administrateur partage une investigation")
        if manifest.get("status") == "running" and run_id in manager.live:
            manager.live[run_id].log.update_manifest(shared=body.shared)
        else:
            manifest["shared"] = body.shared
            _dump(path / "manifest.json", manifest)
        audit(user, "share", {"run_id": run_id, "shared": body.shared})
        return {"shared": body.shared}

    # Revue des actions proposées : validées ou rejetées par un Superviseur, jamais exécutées par l'agent.

    @app.get("/api/actions")
    def pending_actions(user: User = Depends(current_user)) -> list[dict[str, Any]]:
        require(user, "review")
        index = runs_dir() / "index.jsonl"
        out = []
        for r in (json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()) if index.exists() else []:
            for a in read_json(runs_dir() / r["path"] / "actions.json") or []:
                out.append({**a, "run_id": r["run_id"], "question": r["question"], "user": r["user"]})
        return sorted(out, key=lambda a: (a["status"] != "proposed", a["run_id"]), reverse=False)

    @app.post("/api/runs/{run_id}/actions/{action_id}/decision")
    def decide_action(run_id: str, action_id: str, body: DecisionBody,
                      user: User = Depends(current_user)) -> dict[str, Any]:
        require(user, "review")
        path, manifest = load_run(user, run_id)
        if manifest.get("status") == "running":
            raise HTTPException(409, "Investigation en cours")
        actions = read_json(path / "actions.json") or []
        action = next((a for a in actions if a["id"] == action_id), None)
        if action is None:
            raise HTTPException(404, "Action inconnue")
        if action["status"] != "proposed":
            raise HTTPException(409, f"Action déjà {action['status']}")
        action["status"] = "validated" if body.accept else "rejected"
        action["decision"] = {"by": user.login, "at": _ts(), "comment": body.comment}
        _dump(path / "actions.json", actions)
        audit(user, "action_decision", {"run_id": run_id, "action_id": action_id, "status": action["status"]})
        return action

    # Coûts et journal d'accès

    @app.get("/api/costs")
    def costs(user: User = Depends(current_user)) -> dict[str, Any]:
        """Tokens consommés par jour, utilisateur et modèle (le POC n'a pas de notion d'équipe : un
        Superviseur voit tout). Le prix dépend du contrat du fournisseur : on compte des tokens."""
        require(user, "view_costs")
        index = runs_dir() / "index.jsonl"
        rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        for r in (json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()) if index.exists() else []:
            manifest = read_json(runs_dir() / r["path"] / "manifest.json") or {}
            lead = (manifest.get("models") or {}).get("lead") or {}
            key = (r["started_at"][:10], r.get("user") or "?", f"{lead.get('provider', '?')}/{lead.get('model', '?')}")
            row = rows.setdefault(key, {"day": key[0], "user": key[1], "model": key[2], "runs": 0,
                                        "input_tokens": 0, "output_tokens": 0})
            row["runs"] += 1
            for k in ("input_tokens", "output_tokens"):
                row[k] += (r.get("usage") or {}).get(k, 0)
        out = sorted(rows.values(), key=lambda x: (x["day"], x["user"]), reverse=True)
        return {"rows": out, "total": {k: sum(x[k] for x in out) for k in ("runs", "input_tokens", "output_tokens")}}

    @app.get("/api/access-log")
    def access_log(limit: int = 200, user: User = Depends(current_user)) -> list[dict[str, Any]]:
        require(user, "view_access_log")
        root = Path(os.environ.get("DIAGAGENT_AUDIT_DIR") or catalog.home() / "audit")
        out: list[dict[str, Any]] = []
        for f in sorted(root.glob("*/*/*.jsonl"), reverse=True) if root.exists() else []:
            out += [json.loads(line) for line in reversed(f.read_text(encoding="utf-8").splitlines())]
            if len(out) >= limit:
                break
        audit(user, "read_access_log", {})
        return out[:max(1, min(limit, 1000))]

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app
