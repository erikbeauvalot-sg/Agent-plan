"""Règles des mots de passe choisis par les utilisateurs (document d'architecture, « Authentification ») :
12 caractères au moins, refus des mots de passe compromis et de ceux qui reprennent l'identifiant.

La liste des mots de passe compromis est locale, sans appel externe : une courte liste intégrée (mots de
passe très répandus de 12 caractères et plus), complétée par auth/compromised-passwords.txt s'il existe
(un mot de passe par ligne, par exemple une liste publique de mots de passe fuités, déposée par
l'administrateur)."""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

from diagagent import catalog

MIN_PASSWORD = 12

# Très répandus dans les listes de fuites, et assez longs pour passer la seule règle de longueur.
BUILTIN = """
123456789012 1234567890123 12345678901234 123456789123 1234567891011 111111111111 000000000000
123123123123 abcdefghijkl qwertyuiopas qwertyuiop12 qwertyuiop123 azertyuiop12 azertyuiop123
azertyuiopqs motdepasse12 motdepasse123 motdepasse1234 password1234 password12345 passwordpassword
passw0rd1234 Password1234 Password123! Motdepasse123! Azerty123456 Azertyuiop123 iloveyou1234
administrator administrateur admin1234567 adminadminadmin welcome12345 Bienvenue123 bienvenue1234
changeme1234 changemenow1 soleil123456 jetaime123456 football1234 1q2w3e4r5t6y 1qaz2wsx3edc
zaq12wsxcde3 qazwsxedcrfv letmein12345 trustno1trustno1 superman1234 starwars1234 dragon123456
monkey123456 sunshine1234 princess1234 abc123456789 a1b2c3d4e5f6 aaaaaaaaaaaa azerty123azerty
""".split()


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower().strip()


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> frozenset[str]:
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    return frozenset(_fold(line) for line in lines if line.strip() and not line.startswith("#"))


def compromised() -> frozenset[str]:
    extra = catalog.home() / "auth" / "compromised-passwords.txt"
    base = frozenset(_fold(p) for p in BUILTIN)
    return base | _load(str(extra), extra.stat().st_mtime) if extra.exists() else base


def problems(password: str, login: str = "", display_name: str = "") -> list[str]:
    """Raisons de refuser ce mot de passe (liste vide : accepté)."""
    out = []
    if len(password) < MIN_PASSWORD:
        out.append(f"{MIN_PASSWORD} caractères minimum")
    folded = _fold(password)
    if folded in compromised():
        out.append("ce mot de passe figure dans une liste de mots de passe compromis")
    names = [n for n in (_fold(login), *(_fold(w) for w in display_name.split())) if len(n) >= 3]
    if any(n in folded for n in names):
        out.append("il ne doit pas contenir ton identifiant ni ton nom")
    if len(set(folded)) <= 3:
        out.append("trop peu de caractères différents")
    return out
