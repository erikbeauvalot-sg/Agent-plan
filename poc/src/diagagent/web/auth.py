"""Authentification par table d'utilisateurs interne (auth/users.yaml) et rôles.

Mots de passe hachés en Argon2id, verrouillage après 5 échecs, jeton de session signé (HMAC)
dans un cookie HttpOnly. L'interface AuthProvider permettra de brancher l'annuaire (OIDC) plus tard.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from diagagent import catalog

from . import passwords

ROLES = ("lecteur", "operateur", "superviseur", "administrateur", "auditeur")
MIN_PASSWORD = passwords.MIN_PASSWORD
ACTIVATION_HOURS = 24  # validité d'un lien d'activation ou de réinitialisation
MAX_FAILURES = 5
LOCK_MINUTES = 15
SESSION_IDLE_S = 15 * 60
SESSION_MAX_S = 8 * 3600

# Matrice des rôles du document d'architecture (section « Authentification et rôles »).
#   view_shared    lire une investigation partagée (tous les rôles)
#   view_own/all   lire ses investigations / toutes, avec graphe et chronologie en direct
#   details_*      prompts, transcripts et appels d'outils (le Lecteur ne les voit pas)
#   stop_*         arrêt propre d'un sous-agent ou d'une investigation ; kill : arrêt immédiat ; les
#                  mêmes droits envoient une consigne à l'agent principal et relancent un sous-agent
#   adjust_budget  relever ou baisser le budget d'un agent en cours (Superviseur, Administrateur)
#   share_own      partager ses investigations avec les Lecteurs
#   review         valider ou rejeter une action proposée, une évolution de catégorie ou de playbook
#   view_costs, view_access_log, view_indicators, manage_users
#   view_config     lire la configuration et son historique
#   edit_platform   catalogue, modèles, paramètres, rôles de sous-agents (Administrateur)
#   edit_diagnostic playbooks, prompts, jeu d'évaluation (Superviseur)
_OWN = {"view_shared", "ask", "view_own", "details_own", "stop_own", "share_own"}
_ALL = {"view_all", "details_all", "stop_all", "kill", "share_all", "adjust_budget"}
PERMISSIONS = {
    "lecteur": {"view_shared"},
    "operateur": _OWN,
    "superviseur": _OWN | _ALL | {"review", "view_indicators", "view_costs", "view_config", "edit_diagnostic"},
    "administrateur": _OWN | _ALL | {"manage_users", "view_indicators", "view_costs", "view_access_log",
                                     "view_config", "edit_platform"},
    "auditeur": {"view_shared", "view_all", "details_all", "view_costs", "view_access_log", "view_indicators",
                 "view_config"},
}

_hasher = PasswordHasher()


def _digest(token: str) -> str:
    """Empreinte d'un jeton d'activation : le jeton lui-même n'est jamais écrit sur disque."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class User:
    id: str
    login: str
    display_name: str
    roles: list[str]

    def can(self, permission: str) -> bool:
        return any(permission in PERMISSIONS.get(r, set()) for r in self.roles)

    def public(self) -> dict[str, Any]:
        perms = sorted(set().union(*(PERMISSIONS.get(r, set()) for r in self.roles)))
        return {"id": self.id, "login": self.login, "display_name": self.display_name,
                "roles": self.roles, "permissions": perms}


class AuthProvider(Protocol):
    def authenticate(self, login: str, password: str) -> User | None: ...

    def get(self, user_id: str) -> User | None: ...


class AuthError(Exception):
    pass


class FileUserStore:
    """Table d'utilisateurs dans un fichier YAML, lisible par la seule passerelle."""

    def __init__(self, path: Path | None = None):
        self.path = path or catalog.home() / "auth" / "users.yaml"
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": []}
        return yaml.safe_load(self.path.read_text(encoding="utf-8")) or {"users": []}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    @staticmethod
    def _user(entry: dict[str, Any]) -> User:
        return User(entry["id"], entry["login"], entry.get("display_name", entry["login"]), entry["roles"])

    @staticmethod
    def check_password(password: str, login: str, display_name: str | None = None) -> None:
        reasons = passwords.problems(password, login, display_name or "")
        if reasons:
            raise AuthError("Mot de passe refusé : " + " ; ".join(reasons))

    def add(self, login: str, password: str | None, roles: list[str], display_name: str | None = None) -> User:
        """Compte actif avec mot de passe (ligne de commande), ou en attente d'activation sans mot de
        passe (interface : l'utilisateur le choisit par le lien d'activation, voir invite)."""
        if password is not None:
            self.check_password(password, login, display_name)
        unknown = [r for r in roles if r not in ROLES]
        if unknown or not roles:
            raise AuthError(f"Rôle inconnu : {unknown or roles} ; rôles : {', '.join(ROLES)}")
        with self._lock:
            data = self._read()
            if any(u["login"] == login for u in data["users"]):
                raise AuthError(f"L'utilisateur {login} existe déjà")
            entry = {"id": f"u-{len(data['users']) + 1:04d}", "login": login,
                     "display_name": display_name or login, "roles": roles,
                     "password_hash": _hasher.hash(password) if password is not None else None,
                     "status": "active" if password is not None else "pending",
                     "failed_logins": 0, "locked_until": None, "created_at": date.today().isoformat()}
            data["users"].append(entry)
            self._write(data)
        return self._user(entry)

    def invite(self, user_id: str) -> tuple[str, str]:
        """Lien d'activation à usage unique, valable ACTIVATION_HOURS : nouveau compte, ou mot de passe
        oublié. Seule l'empreinte du jeton est gardée ; un nouveau lien annule le précédent. Rend le jeton
        et sa date d'expiration."""
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(hours=ACTIVATION_HOURS)).isoformat()
        with self._lock:
            data = self._read()
            entry = next((u for u in data["users"] if u["id"] == user_id), None)
            if entry is None:
                raise AuthError(f"Utilisateur inconnu : {user_id}")
            if entry.get("status") == "disabled":
                raise AuthError("Compte désactivé : réactive-le avant d'envoyer un lien")
            entry["activation"] = {"token_sha256": _digest(token), "expires_at": expires}
            self._write(data)
        return token, expires

    def activation(self, token: str) -> dict[str, Any] | None:
        """Compte visé par un lien encore valable (pour afficher l'identifiant sur l'écran d'activation)."""
        entry = self._by_token(self._read(), token)
        return {"login": entry["login"], "display_name": entry.get("display_name"),
                "expires_at": entry["activation"]["expires_at"]} if entry else None

    def activate(self, token: str, password: str) -> User:
        with self._lock:
            data = self._read()
            entry = self._by_token(data, token)
            if entry is None:
                raise AuthError("Lien d'activation inconnu, déjà utilisé ou expiré : demande un nouveau lien")
            self.check_password(password, entry["login"], entry.get("display_name"))
            entry.update(password_hash=_hasher.hash(password), status="active", failed_logins=0, locked_until=None)
            entry.pop("activation", None)
            self._write(data)
        return self._user(entry)

    @staticmethod
    def _by_token(data: dict[str, Any], token: str) -> dict[str, Any] | None:
        digest = _digest(token)
        now = datetime.now(timezone.utc)
        for u in data["users"]:
            act = u.get("activation") or {}
            if act.get("token_sha256") and hmac.compare_digest(act["token_sha256"], digest) \
                    and datetime.fromisoformat(act["expires_at"]) > now and u.get("status") != "disabled":
                return u
        return None

    def locked_minutes(self, login: str) -> int | None:
        """Minutes de verrouillage restantes après trop d'échecs, ou None."""
        entry = next((u for u in self._read()["users"] if u["login"] == login), None)
        until = entry.get("locked_until") if entry else None
        if not until:
            return None
        left = (datetime.fromisoformat(until) - datetime.now(timezone.utc)).total_seconds()
        return max(1, round(left / 60)) if left > 0 else None

    def authenticate(self, login: str, password: str) -> User | None:
        with self._lock:
            data = self._read()
            entry = next((u for u in data["users"] if u["login"] == login), None)
            if entry is None:
                _hasher.hash(password)  # même coût qu'un vrai essai
                return None
            now = datetime.now(timezone.utc)
            if entry.get("status") != "active":
                return None
            if entry.get("locked_until") and datetime.fromisoformat(entry["locked_until"]) > now:
                return None
            try:
                _hasher.verify(entry["password_hash"], password)
            except (VerifyMismatchError, VerificationError):
                entry["failed_logins"] = entry.get("failed_logins", 0) + 1
                if entry["failed_logins"] >= MAX_FAILURES:
                    entry["locked_until"] = (now + timedelta(minutes=LOCK_MINUTES)).isoformat()
                    entry["failed_logins"] = 0
                self._write(data)
                return None
            if entry.get("failed_logins") or entry.get("locked_until"):
                entry["failed_logins"], entry["locked_until"] = 0, None
                self._write(data)
            return self._user(entry)

    def accounts(self) -> list[dict[str, Any]]:
        """Comptes sans leur empreinte de mot de passe, qui ne quitte jamais la passerelle."""
        keep = ("id", "login", "display_name", "roles", "status", "locked_until", "created_at")
        return [{**{k: u.get(k) for k in keep},
                 "activation_expires_at": (u.get("activation") or {}).get("expires_at")}
                for u in self._read()["users"]]

    def update(self, user_id: str, roles: list[str] | None = None, status: str | None = None,
               password: str | None = None, display_name: str | None = None) -> dict[str, Any]:
        if roles is not None and (not roles or any(r not in ROLES for r in roles)):
            raise AuthError(f"Rôles invalides : {roles} ; rôles : {', '.join(ROLES)}")
        if status not in (None, "active", "disabled"):
            raise AuthError("status vaut active ou disabled")
        with self._lock:
            data = self._read()
            entry = next((u for u in data["users"] if u["id"] == user_id), None)
            if entry is None:
                raise AuthError(f"Utilisateur inconnu : {user_id}")
            if password is not None:
                self.check_password(password, entry["login"], display_name or entry.get("display_name"))
            if status == "active" and entry.get("status") == "pending" and password is None:
                raise AuthError("Compte en attente d'activation : l'utilisateur choisit son mot de passe par le lien")
            after = {**entry, **({"roles": roles} if roles is not None else {}),
                     **({"status": status} if status is not None else {})}
            # Jamais sans administrateur actif : personne ne pourrait plus gérer les comptes.
            if not any("administrateur" in u["roles"] and u.get("status") == "active"
                       for u in [after if u["id"] == user_id else u for u in data["users"]]):
                raise AuthError("Il doit rester au moins un administrateur actif")
            entry.update(after)
            if display_name is not None:
                entry["display_name"] = display_name
            if password is not None:
                entry.update(password_hash=_hasher.hash(password), failed_logins=0, locked_until=None)
            self._write(data)
        return next(u for u in self.accounts() if u["id"] == user_id)

    def get(self, user_id: str) -> User | None:
        entry = next((u for u in self._read()["users"] if u["id"] == user_id and u.get("status") == "active"), None)
        return self._user(entry) if entry else None


class Sessions:
    """Jeton signé : identifiant, début de session, dernière activité. Renouvelé à chaque requête."""

    def __init__(self, secret: bytes | None = None):
        env = os.environ.get("DIAGAGENT_SESSION_SECRET")
        self.secret = secret or (env.encode() if env else secrets.token_bytes(32))

    def _sign(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.secret, payload, hashlib.sha256).digest()).decode()

    def issue(self, user_id: str, started: float | None = None) -> str:
        now = time.time()
        payload = base64.urlsafe_b64encode(json.dumps(
            {"u": user_id, "s": started or now, "a": now}).encode())
        return payload.decode() + "." + self._sign(payload)

    def verify(self, token: str | None) -> tuple[str, float] | None:
        if not token or "." not in token:
            return None
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload.encode())):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload))
        now = time.time()
        if now - data["a"] > SESSION_IDLE_S or now - data["s"] > SESSION_MAX_S:
            return None
        return data["u"], data["s"]


def audit(user: User | None, action: str, detail: dict[str, Any] | None = None, source: str | None = None) -> None:
    """Journal d'accès en ajout seul : audit/AAAA/MM/JJ.jsonl."""
    now = datetime.now(timezone.utc)
    root = Path(os.environ.get("DIAGAGENT_AUDIT_DIR") or catalog.home() / "audit")
    path = root / now.strftime("%Y/%m") / f"{now:%d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now.isoformat(), "user": user.login if user else None, "action": action,
                            "source": source, **(detail or {})}, ensure_ascii=False) + "\n")
