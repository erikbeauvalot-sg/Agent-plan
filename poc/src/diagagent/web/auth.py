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

ROLES = ("operateur", "superviseur", "administrateur")
MIN_PASSWORD = 12
MAX_FAILURES = 5
LOCK_MINUTES = 15
SESSION_IDLE_S = 15 * 60
SESSION_MAX_S = 8 * 3600

# Fonctions autorisées par rôle (matrice du document d'architecture). Seul le Superviseur valide les
# évolutions de catégories et de playbooks (review) ; l'Administrateur voit les indicateurs sans valider.
PERMISSIONS = {
    "operateur": {"ask", "view_own", "stop_own"},
    "superviseur": {"ask", "view_own", "stop_own", "view_all", "stop_all", "review", "view_indicators"},
    "administrateur": {"ask", "view_own", "stop_own", "view_all", "stop_all", "manage_users", "view_indicators"},
}

_hasher = PasswordHasher()


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

    def add(self, login: str, password: str, roles: list[str], display_name: str | None = None) -> User:
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"Mot de passe trop court : {MIN_PASSWORD} caractères minimum")
        unknown = [r for r in roles if r not in ROLES]
        if unknown or not roles:
            raise AuthError(f"Rôle inconnu : {unknown or roles} ; rôles : {', '.join(ROLES)}")
        with self._lock:
            data = self._read()
            if any(u["login"] == login for u in data["users"]):
                raise AuthError(f"L'utilisateur {login} existe déjà")
            entry = {"id": f"u-{len(data['users']) + 1:04d}", "login": login,
                     "display_name": display_name or login, "roles": roles,
                     "password_hash": _hasher.hash(password), "status": "active",
                     "failed_logins": 0, "locked_until": None, "created_at": date.today().isoformat()}
            data["users"].append(entry)
            self._write(data)
        return self._user(entry)

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
