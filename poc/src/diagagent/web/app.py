"""Passerelle web : authentification, lancement des investigations, flux temps réel, arrêt d'agent.

Le front ne voit que ce qui est écrit dans runs/ : l'état affiché est reconstruit à partir de
events.jsonl, relu et poussé en Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from diagagent import catalog, config_files, dashboard, followup, knowledge, learning, playbooks
from diagagent.llm import model_profiles
from diagagent.agent import LocalToolError
from diagagent.orchestrator import Investigation, ProviderFactory
from diagagent.runlog import RunLog, _append, _dump, _ts

from .auth import AuthError, AuthProvider, FileUserStore, Sessions, User, audit

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
    providers: Callable[[str | None], ProviderFactory]
    live: dict[str, LiveRun] = field(default_factory=dict)

    async def start(self, question: str, user: User, category: str | None = None,
                    models: str | None = None, sources: str | None = None, rerun_of: str | None = None,
                    follow_up_of: str | None = None) -> str:
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
                await ask(question, providers=self.providers(models), user=user.login, on_started=on_started,
                          category=category, sources=sources, rerun_of=rerun_of, follow_up_of=follow_up_of)
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
    models: str | None = None  # profil de config/models.yaml ; défaut : celui du fichier
    sources: str | None = None  # demo, maison ou demo,maison ; défaut : DIAGAGENT_SOURCES, sinon les deux
    rerun_of: str | None = None  # investigation relancée, que l'utilisateur peut voir
    follow_up_of: str | None = None  # question de suivi d'une investigation terminée, que l'utilisateur peut voir


class CategoryBody(BaseModel):
    category: str


class InstructionBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class RestartBody(BaseModel):
    prompt: str | None = Field(default=None, max_length=20_000)


class BudgetBody(BaseModel):
    max_tool_calls: int = Field(ge=1, le=200)


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


class ConfigBody(BaseModel):
    path: str = Field(max_length=200)
    content: str = Field(max_length=500_000)
    version: str | None = None  # empreinte de la version lue ; None pour un nouveau fichier
    comment: str = Field(default="", max_length=2000)


class NewUserBody(BaseModel):
    login: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str | None = Field(default=None, max_length=120)
    roles: list[str]
    # Sans mot de passe (cas normal depuis l'interface) : compte en attente et lien d'activation de 24 h.
    password: str | None = Field(default=None, max_length=200)


class ActivationBody(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(max_length=200)


class UserBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    roles: list[str] | None = None
    status: str | None = None
    password: str | None = Field(default=None, max_length=200)


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


def create_app(providers: Callable[[str | None], ProviderFactory] | None = None, users: AuthProvider | None = None,
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
            raise HTTPException(403, "Fonction non autorisée pour ton rôle")

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
            if (minutes := locked_minutes(body.login)) is not None:
                raise HTTPException(423, f"Compte verrouillé après 5 échecs : réessaie dans {minutes} min")
            raise HTTPException(401, "Identifiant ou mot de passe incorrect (compte verrouillé après 5 échecs)")
        audit(user, "login", source=source)
        set_cookie(response, sessions.issue(user.id))
        return user.public()

    @app.post("/login")
    async def login_form(request: Request) -> Response:
        """Connexion par un vrai envoi de formulaire puis redirection : la touche Entrée marche partout et les
        gestionnaires de mots de passe reconnaissent la connexion (proposition d'enregistrement immédiate,
        remplissage automatique ensuite). En cas d'échec, retour au formulaire avec ?echec=1."""
        origin = request.headers.get("origin")
        if origin and origin != "null" and urllib.parse.urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "Origine refusée")
        form = urllib.parse.parse_qs((await request.body()).decode("utf-8"))
        field = lambda name: (form.get(name) or [""])[0]  # noqa: E731
        target = field("next")
        anchor = f"#{target}" if target == "admin" or RUN_ID.match(target) else ""
        user = users.authenticate(field("login"), field("password"))
        source = request.client.host if request.client else None
        if user is None:
            audit(None, "login_failed", {"login": field("login")}, source)
            minutes = locked_minutes(field("login"))
            reason = f"verrou={minutes}" if minutes is not None else "echec=1"
            return RedirectResponse(f"/?{reason}{anchor}", status_code=303)
        audit(user, "login", source=source)
        response = RedirectResponse(f"/{anchor}", status_code=303)
        set_cookie(response, sessions.issue(user.id))
        return response

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
        if body.models and body.models not in model_choices()["profiles"]:
            raise HTTPException(400, f"Profil de modèles inconnu : {body.models}")
        if body.sources and body.sources not in [c["value"] for c in source_choices()["choices"] if c["available"]]:
            raise HTTPException(400, f"Jeu de sources inconnu ou non configuré : {body.sources}")
        if body.rerun_of:
            try:
                load_run(user, body.rerun_of)
            except HTTPException:
                raise HTTPException(400, f"Investigation d'origine inconnue : {body.rerun_of}") from None
        if body.follow_up_of:
            try:
                _, origin = load_run(user, body.follow_up_of)
            except HTTPException:
                raise HTTPException(400, f"Investigation d'origine inconnue : {body.follow_up_of}") from None
            if origin.get("status") == "running":
                raise HTTPException(409, "L'investigation d'origine tourne encore : envoie plutôt une consigne")
        try:
            run_id = await manager.start(body.question.strip(), user, body.category, body.models, body.sources,
                                         body.rerun_of, body.follow_up_of)
        except Exception as e:
            raise HTTPException(502, f"Impossible de démarrer l'investigation : {type(e).__name__}: {e}") from e
        audit(user, "ask", {"run_id": run_id, "category": body.category, "models": body.models,
                            "sources": body.sources, **({"rerun_of": body.rerun_of} if body.rerun_of else {}),
                            **({"follow_up_of": body.follow_up_of} if body.follow_up_of else {})})
        return {"run_id": run_id}

    def source_choices() -> dict[str, Any]:
        """Les trois choix sont toujours listés ; ceux qui demandent une source réelle sont indisponibles
        tant que PROMETHEUS_URL, ALERTMANAGER_URL, SSH_HOSTS ou WEB_SEARCH n'est pas définie. Défaut : DIAGAGENT_SOURCES."""
        home = "maison" in catalog.configured_sources()
        reason = None if home else "aucune source réelle configurée (PROMETHEUS_URL, ALERTMANAGER_URL, SSH_HOSTS, WEB_SEARCH)"
        choices = [{"value": "demo,maison", "label": "démo + maison", "available": home, "reason": reason},
                   {"value": "demo", "label": "démo", "available": True, "reason": None},
                   {"value": "maison", "label": "maison", "available": home, "reason": reason}]
        wanted = ",".join(sorted(catalog.active_sources()))
        default = wanted if any(c["value"] == wanted and c["available"] for c in choices) else "demo"
        return {"choices": choices, "default": default}

    @app.get("/api/sources")
    def sources(user: User = Depends(current_user)) -> dict[str, Any]:
        """Jeux de sources proposés au lancement d'une investigation."""
        return source_choices()

    def model_choices() -> dict[str, Any]:
        from diagagent.cli import _load

        names, default = model_profiles(_load("models.yaml"))
        return {"profiles": names, "default": os.environ.get("DIAGAGENT_MODELS") or default}

    @app.get("/api/models")
    def models(user: User = Depends(current_user)) -> dict[str, Any]:
        """Profils de modèles proposés au lancement d'une investigation (leur état : /api/status)."""
        return model_choices()

    status_cache: dict[str, Any] = {}

    @app.get("/api/status")
    async def status(refresh: bool = False, user: User = Depends(current_user)) -> dict[str, Any]:
        """État des profils de modèles et des sources, alertes en cours. Gardé 15 s : les vérifications
        interrogent Ollama, Prometheus et Alertmanager."""
        from diagagent.cli import _load

        now = time.monotonic()
        if refresh or not status_cache or now - status_cache["at"] > 15:
            models_cfg = _load("models.yaml")
            models_state, sources_state = await asyncio.gather(
                asyncio.to_thread(dashboard.models_status, models_cfg), asyncio.to_thread(dashboard.sources_status))
            status_cache.update(at=now, data={"models": models_state, **sources_state,
                                              "default_models": model_choices()["default"]})
        return status_cache["data"]

    @app.get("/api/home")
    def home(days: int = 7, include_eval: bool = False, user: User = Depends(current_user)) -> dict[str, Any]:
        """Activité du jour et statistiques de la période sur les investigations visibles par l'utilisateur,
        derniers résultats d'éval par profil de modèles."""
        days = max(1, min(days, 90))

        def manifest_of(row: dict[str, Any]) -> dict[str, Any]:
            return read_json(runs_dir() / row["path"] / "manifest.json") or {}

        def manifest_of_run(run_id: str) -> dict[str, Any] | None:
            try:
                return read_json(run_path(run_id) / "manifest.json")
            except HTTPException:
                return None
        # Heure réelle, pas l'heure de référence figée (serve --now) : les investigations sont datées réellement.
        now = datetime.now(timezone.utc)
        return {"activity": dashboard.activity(visible_runs(user), manifest_of, now, days, include_eval),
                "evals": dashboard.last_evals(catalog.home() / "eval" / "results", manifest_of_run)}

    @app.get("/api/categories")
    def categories(user: User = Depends(current_user)) -> list[dict[str, Any]]:
        return [{"id": b["id"], "version": b["version"], "description": " ".join(b["description"].split()),
                 "examples": list(b.get("examples") or [])}
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
    def list_runs(request: Request, limit: int = 100, offset: int = 0,
                  user: User = Depends(current_user)) -> list[dict[str, Any]]:
        """Investigations visibles, les plus récentes d'abord, avec modèles, durée et tokens. Filtres
        combinables en paramètres : since, until, user, category, status, host, q (voir run_matches).
        Une investigation en cours porte l'état de ses agents et sa ligne de statut (live)."""
        filters = {k: v for k in dashboard.RUN_FILTERS if (v := request.query_params.get(k))}
        rows = [r for r in visible_runs(user)
                if dashboard.run_matches(r, filters, lambda r=r: run_hosts(r))]
        out = []
        for r in rows[max(0, offset):max(0, offset) + max(1, min(limit, 1000))]:
            if r["status"] != "running":
                r = dashboard.enrich(r, manifest_of)
            elif (live := manager.live.get(r["run_id"])) is not None:
                r = {**r, "live": dashboard.live_summary(live_events(live.log.dir))}
            out.append({**r, "label": dashboard.label(r), "duration_s": dashboard._duration(r),
                        "tokens": dashboard._tokens(r)})
        return out

    @app.get("/api/runs/facets")
    def run_facets(user: User = Depends(current_user)) -> dict[str, Any]:
        """Valeurs proposées par les filtres de l'historique, d'après les investigations visibles."""
        rows = visible_runs(user)
        return {"users": sorted({r["user"] for r in rows}) if user.can("view_all") else [],
                "categories": sorted({r["category"] for r in rows if r.get("category")}),
                "statuses": sorted({r["status"] for r in rows}),
                "hosts": sorted({h for r in rows for h in run_hosts(r)})}

    def manifest_of(row: dict[str, Any]) -> dict[str, Any]:
        return read_json(runs_dir() / row["path"] / "manifest.json") or {}

    def live_events(path: Path) -> list[dict[str, Any]]:
        file = path / "events.jsonl"
        lines = file.read_text(encoding="utf-8").splitlines() if file.exists() else []
        return [json.loads(line) for line in lines if line.strip()]

    hosts_cache: dict[str, list[str]] = {}

    def run_hosts(row: dict[str, Any]) -> list[str]:
        """Hosts d'une investigation terminée, gardés en mémoire (une trace terminée ne change plus)."""
        if row["status"] == "running" or "path" not in row:
            live = manager.live.get(row["run_id"])
            manifest = live.log.manifest if live else {}
            return dashboard.hosts_of(row, manifest, known_hosts())
        if row["run_id"] not in hosts_cache:
            hosts_cache[row["run_id"]] = dashboard.hosts_of(row, manifest_of(row), known_hosts())
        return hosts_cache[row["run_id"]]

    def known_hosts() -> set[str]:
        try:
            return {str(c["hostname"]) for c in catalog.rows("cmdb") if c.get("hostname")}
        except Exception:  # CMDB absente du catalogue : seuls les hosts repérés par le classifieur comptent
            return set()

    def visible_runs(user: User) -> list[dict[str, Any]]:
        index = runs_dir() / "index.jsonl"
        done = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()] if index.exists() else []
        finished = {r["run_id"] for r in done}
        running = [{"run_id": rid, "question": r.log.manifest["question"], "user": r.user,
                    "started_at": r.log.manifest["started_at"], "status": "running",
                    "category": (r.log.manifest.get("category") or {}).get("id"),
                    "models_profile": r.log.manifest.get("models_profile"), "sources": r.log.manifest.get("sources"),
                    "follow_up_of": r.log.manifest.get("follow_up_of")}
                   for rid, r in manager.live.items() if rid not in finished]
        shared = set()
        if not user.can("view_all"):  # les investigations partagées se lisent dans leur manifest
            shared = {r["run_id"] for r in done if (read_json(runs_dir() / r["path"] / "manifest.json") or {}).get("shared")}
        rows = [r for r in running + done if can_view(user, {**r, "shared": r["run_id"] in shared})]
        return sorted(rows, key=lambda r: r["started_at"], reverse=True)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
        path, manifest = load_run(user, run_id)
        return {"manifest": manifest, "plan": read_text(path / "plan.md"),
                "analysis": read_text(path / "analysis.md"), "actions": read_json(path / "actions.json") or [],
                "can_details": can_details(user, manifest),
                "can_share": user.can("share_all") or (user.can("share_own") and manifest.get("user") == user.login),
                "can_stop": manifest.get("status") == "running" and run_id in manager.live
                and (user.can("stop_all") or (user.can("stop_own") and manifest.get("user") == user.login)),
                "thread": thread(user, run_id, manifest)}

    def thread(user: User, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        """Fil de conversation : questions précédentes avec leur synthèse (en remontant follow_up_of) et
        questions de suivi déjà posées, limités à ce que cet utilisateur peut voir."""
        earlier = []
        if manifest.get("follow_up_of"):
            for m in followup.chain(runs_dir(), manifest["follow_up_of"]):
                if not can_view(user, m):
                    earlier = []  # un maillon invisible coupe le fil : rien de ce qui précède n'est montré
                    continue
                earlier.append({"run_id": m["run_id"], "question": m["question"], "status": m.get("status"),
                                "started_at": m.get("started_at"), "user": m.get("user"),
                                "analysis": read_text(followup.run_dir(runs_dir(), m["run_id"]) / "analysis.md")})
        later = [{"run_id": r["run_id"], "question": r["question"], "status": r["status"],
                  "started_at": r["started_at"], "user": r["user"]}
                 for r in visible_runs(user) if r.get("follow_up_of") == run_id]
        return {"earlier": earlier, "later": sorted(later, key=lambda r: r["started_at"])}

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
            raise HTTPException(403, "Prompts, transcripts et appels d'outils non visibles pour ton rôle")
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
            raise HTTPException(403, "Tu ne peux arrêter que tes propres investigations")
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

    def pilot(user: User, run_id: str) -> Investigation:
        """Investigation en cours que cet utilisateur peut piloter (mêmes droits que l'arrêt)."""
        _, manifest = load_run(user, run_id)
        if not (user.can("stop_all") or (user.can("stop_own") and manifest.get("user") == user.login)):
            raise HTTPException(403, "Tu ne peux piloter que tes propres investigations")
        live = manager.live.get(run_id)
        if live is None or live.investigation is None or manifest.get("status") != "running":
            raise HTTPException(409, "Investigation terminée")
        return live.investigation

    @app.post("/api/runs/{run_id}/instructions")
    async def instruct(run_id: str, body: InstructionBody, user: User = Depends(current_user)) -> dict[str, Any]:
        """Consigne pour l'agent principal, remise avant son prochain appel au modèle."""
        if not pilot(user, run_id).instruct(body.text, by=user.login):
            raise HTTPException(409, "L'agent principal ne reçoit plus de consigne (classement ou synthèse finie)")
        audit(user, "instruction", {"run_id": run_id, "chars": len(body.text)})
        return {"status": "queued"}

    @app.post("/api/runs/{run_id}/agents/{agent_id}/restart")
    async def restart(run_id: str, agent_id: str, body: RestartBody,
                      user: User = Depends(current_user)) -> dict[str, Any]:
        """Relance d'un sous-agent terminé ou arrêté (prompt d'origine ou corrigé) ; asynchrone : la tâche
        est créée dans la boucle de l'investigation."""
        investigation = pilot(user, run_id)
        try:
            task_id = investigation.restart_subagent(agent_id, body.prompt, by=user.login)
        except LocalToolError as e:
            raise HTTPException(409, str(e)) from None
        audit(user, "restart_agent", {"run_id": run_id, "agent_id": agent_id, "new": task_id,
                                      "prompt_changed": bool(body.prompt)})
        return {"task_id": task_id}

    @app.post("/api/runs/{run_id}/agents/{agent_id}/budget")
    async def budget(run_id: str, agent_id: str, body: BudgetBody,
                     user: User = Depends(current_user)) -> dict[str, Any]:
        if not user.can("adjust_budget"):
            raise HTTPException(403, "Ajuster un budget est réservé au superviseur et à l'administrateur")
        if not pilot(user, run_id).set_budget(agent_id, body.max_tool_calls, by=user.login):
            raise HTTPException(409, "Agent terminé ou inconnu")
        audit(user, "budget", {"run_id": run_id, "agent_id": agent_id, "max_tool_calls": body.max_tool_calls})
        return {"max_tool_calls": body.max_tool_calls}

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
                                        "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0})
            row["runs"] += 1
            for k in ("input_tokens", "output_tokens", "reasoning_tokens"):
                row[k] += (r.get("usage") or {}).get(k, 0)
        out = sorted(rows.values(), key=lambda x: (x["day"], x["user"]), reverse=True)
        return {"rows": out, "total": {k: sum(x[k] for x in out) for k in ("runs", "input_tokens", "output_tokens", "reasoning_tokens")}}

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

    # Configuration depuis l'interface (document d'architecture, « Configuration depuis l'interface »)

    def config_rule(rel: str) -> tuple[str, str]:
        try:
            kind, permission, _ = config_files.rule_of(rel)
        except config_files.ConfigError as e:
            raise HTTPException(400, str(e)) from e
        return kind, permission

    @app.get("/api/config")
    def config_list(user: User = Depends(current_user)) -> dict[str, Any]:
        require(user, "view_config")
        return {"files": [{**f, "editable": user.can(f["permission"])} for f in config_files.list_files()],
                "creatable": [c for c in config_files.creatable() if user.can(c["permission"])]}

    @app.get("/api/config/file")
    def config_read(path: str, user: User = Depends(current_user)) -> dict[str, Any]:
        require(user, "view_config")
        _, permission = config_rule(path)
        try:
            f = config_files.read(path)
        except FileNotFoundError as e:
            raise HTTPException(404, f"Fichier inconnu : {path}") from e
        return {**f, "editable": user.can(permission)}

    @app.post("/api/config/validate")
    def config_validate(body: ConfigBody, user: User = Depends(current_user)) -> dict[str, Any]:
        _, permission = config_rule(body.path)
        require(user, permission)
        try:
            config_files.validate(body.path, body.content)
        except config_files.ConfigError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    @app.post("/api/config/file")
    def config_save(body: ConfigBody, user: User = Depends(current_user)) -> dict[str, Any]:
        _, permission = config_rule(body.path)
        require(user, permission)
        try:
            saved = config_files.save(body.path, body.content, body.version, user.login, body.comment)
        except config_files.ConflictError as e:
            raise HTTPException(409, str(e)) from e
        except config_files.ConfigError as e:
            raise HTTPException(422, str(e)) from e
        audit(user, "config_changed", {"path": body.path, "comment": saved["comment"],
                                       "before": saved["previous"], "after": saved["version"]})
        return saved

    @app.get("/api/config/history")
    def config_history(path: str, user: User = Depends(current_user)) -> list[dict[str, Any]]:
        require(user, "view_config")
        config_rule(path)
        return config_files.history(path)

    @app.get("/api/config/version")
    def config_version(path: str, id: str, user: User = Depends(current_user)) -> dict[str, Any]:
        """Une version de l'historique et son écart avec le fichier actuel."""
        require(user, "view_config")
        config_rule(path)
        try:
            old = config_files.version_text(path, id)
            current = config_files.read(path)["content"]
        except (FileNotFoundError, config_files.ConfigError) as e:
            raise HTTPException(404, str(e)) from e
        return {"path": path, "id": id, "content": old,
                "diff": config_files.diff(old, current, f"{path} ({id})", f"{path} (actuel)")}

    # Comptes : formulaire, jamais le fichier brut (les empreintes de mot de passe restent ici)

    def store() -> FileUserStore:
        if not isinstance(users, FileUserStore):
            raise HTTPException(501, "Les comptes sont gérés par l'annuaire d'entreprise")
        return users

    def locked_minutes(login: str) -> int | None:
        return users.locked_minutes(login) if isinstance(users, FileUserStore) else None

    @app.get("/api/users")
    def users_list(user: User = Depends(current_user)) -> list[dict[str, Any]]:
        require(user, "manage_users")
        return store().accounts()

    def activation_link(request: Request, token: str) -> str:
        return str(request.base_url).rstrip("/") + f"/#activation/{token}"

    @app.post("/api/users")
    def users_create(body: NewUserBody, request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
        """Création d'un compte. Sans mot de passe, le compte attend son activation et la réponse porte le
        lien à usage unique (24 h) à transmettre à l'utilisateur, qui y choisit son mot de passe."""
        require(user, "manage_users")
        try:
            created = store().add(body.login, body.password, body.roles, body.display_name)
            link = None
            if body.password is None:
                token, expires = store().invite(created.id)
                link = {"url": activation_link(request, token), "expires_at": expires}
        except AuthError as e:
            raise HTTPException(422, str(e)) from e
        audit(user, "user_created", {"login": created.login, "roles": created.roles, "activation_link": bool(link)})
        return {**next(u for u in store().accounts() if u["id"] == created.id), "activation": link}

    @app.post("/api/users/{user_id}/activation-link")
    def users_link(user_id: str, request: Request, user: User = Depends(current_user)) -> dict[str, Any]:
        """Nouveau lien (compte jamais activé, lien perdu ou mot de passe oublié) ; annule le précédent."""
        require(user, "manage_users")
        try:
            token, expires = store().invite(user_id)
        except AuthError as e:
            raise HTTPException(422, str(e)) from e
        login = next(u["login"] for u in store().accounts() if u["id"] == user_id)
        audit(user, "activation_link", {"login": login})
        return {"url": activation_link(request, token), "expires_at": expires}

    @app.get("/api/activation/{token}")
    def activation_info(token: str) -> dict[str, Any]:
        """Sans session : l'écran d'activation affiche l'identifiant visé et la fin de validité du lien."""
        info = store().activation(token)
        if info is None:
            raise HTTPException(404, "Lien d'activation inconnu, déjà utilisé ou expiré : demande un nouveau lien")
        return info

    @app.post("/api/activation")
    def activate(body: ActivationBody, request: Request, response: Response) -> dict[str, Any]:
        """Choix du mot de passe par le lien ; ouvre directement la session."""
        try:
            activated = store().activate(body.token, body.password)
        except AuthError as e:
            raise HTTPException(422, str(e)) from e
        audit(activated, "account_activated", source=request.client.host if request.client else None)
        set_cookie(response, sessions.issue(activated.id))
        return activated.public()

    @app.post("/api/users/{user_id}")
    def users_update(user_id: str, body: UserBody, user: User = Depends(current_user)) -> dict[str, Any]:
        require(user, "manage_users")
        try:
            updated = store().update(user_id, body.roles, body.status, body.password, body.display_name)
        except AuthError as e:
            raise HTTPException(422, str(e)) from e
        changes = [k for k in ("display_name", "roles", "status") if getattr(body, k) is not None]
        audit(user, "user_updated", {"login": updated["login"], "changes": changes,
                                     "roles": updated["roles"], "status": updated["status"],
                                     "password_reset": body.password is not None})
        return updated

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index() -> FileResponse:
        """Interface (TypeScript, React) : bundle versionné dans static/dist, construit par poc/web-ui ;
        aucun Node à l'exécution."""
        page = STATIC / "dist" / "index.html"
        if not page.exists():
            raise HTTPException(404, "Interface absente : cd poc/web-ui && npm ci && npm run build")
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    return app
