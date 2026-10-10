"""Sonde SSH en lecture seule derrière mcp-system : état en direct d'une machine Linux.

Seul le script remote/diagagent-probe s'exécute, avec un nom de sonde pris dans PROBES ; le modèle ne
choisit que le host, qui doit figurer dans SSH_HOSTS. Le script part sur l'entrée standard
(`sh -s -- <sonde>`) : rien à installer sur la machine. Avec une clé à commande forcée
(command="/usr/local/bin/diagagent-probe"), la machine ignore ce script et exécute le sien.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any

from diagagent import catalog

PROBES = ("memory", "processes", "containers", "oom")
TIMEOUT_S = 20
# Pas de saisie interactive, clé d'hôte déjà connue, aucune redirection.
SSH_OPTIONS = ["-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes",
               "-o", "ClearAllForwardings=yes"]
CONTAINER_ID = re.compile(r"docker[-/]([0-9a-f]{64})")


class SshProbe:
    def __init__(self, card: dict[str, Any]):
        self.source_id = card["id"]
        backend = card.get("backend", {})
        self.user = os.environ.get(backend.get("user_env", ""), "") or None
        self.key = os.environ.get(backend.get("key_env", ""), "") or None
        # SSH_HOSTS : « xdocker,pdocker » ou « xdocker=192.168.1.20 » quand le nom ne se résout pas.
        self.hosts: dict[str, str] = {}
        for item in os.environ.get(backend.get("hosts_env", "SSH_HOSTS"), "").split(","):
            name, _, address = item.strip().partition("=")
            if name:
                self.hosts[name] = address or name

    def run(self, host: str, probe: str) -> dict[str, list[str]]:
        """Lance une sonde et rend ses sections (`### nom`) ligne par ligne."""
        if probe not in PROBES:
            raise ValueError(f"Sonde inconnue : {probe}")
        if host not in self.hosts:
            raise ValueError(f"{host} n'est pas joignable en SSH ; hosts autorisés (SSH_HOSTS) : "
                             f"{', '.join(self.hosts) or 'aucun'}")
        cmd = [os.environ.get("DIAGAGENT_SSH_COMMAND", "ssh"), *SSH_OPTIONS]
        if self.key:
            cmd += ["-i", self.key]
        if self.user:
            cmd += ["-l", self.user]
        cmd += [self.hosts[host], "sh", "-s", "--", probe]
        script = (catalog.home() / "remote" / "diagagent-probe").read_text(encoding="utf-8")
        try:
            done = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise ValueError(f"SSH vers {host} : pas de réponse en {TIMEOUT_S} s") from e
        if done.returncode != 0:
            raise ValueError(f"SSH vers {host} : code {done.returncode}, {done.stderr.strip()[:300]}")
        return sections(done.stdout)


def sections(output: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for line in output.splitlines():
        if line.startswith("### "):
            current = out.setdefault(line[4:].strip(), [])
        elif current is not None and line.strip():
            current.append(line)
    return out


def mb(kb: float) -> float:
    return round(kb / 1024, 1)


def meminfo(lines: list[str]) -> dict[str, int]:
    """Lignes de /proc/meminfo -> valeurs en kB."""
    out = {}
    for line in lines:
        key, _, value = line.partition(":")
        if value.split():
            out[key] = int(value.split()[0])
    return out


def psi(lines: list[str]) -> dict[str, dict[str, float]]:
    """/proc/pressure/memory : « some avg10=0.00 avg60=0.00 avg300=0.00 total=… » (en % du temps)."""
    out = {}
    for line in lines:
        kind, *fields = line.split()
        out[kind] = {k: float(v) for k, v in (f.split("=") for f in fields) if k.startswith("avg")}
    return out


def by_pid(lines: list[str]) -> dict[int, str]:
    """« /proc/123/status:VmSwap: 12 kB » ou « /proc/123/cgroup:0::/… » -> {123: reste de la ligne}."""
    out = {}
    for line in lines:
        path, _, rest = line.partition(":")
        parts = path.split("/")
        if len(parts) > 2 and parts[2].isdigit():
            out[int(parts[2])] = rest.partition(":")[2].strip()
    return out


def container_names(lines: list[str]) -> dict[str, str]:
    return {cid: info["name"] for cid, info in containers(lines).items()}


def containers(lines: list[str]) -> dict[str, dict[str, str | None]]:
    """« <id> /<nom> <image> <version> » (docker inspect) -> {id: nom, image, version}. La version vient du
    label org.opencontainers.image.version : un tag latest ne dit pas quelle version tourne."""
    out: dict[str, dict[str, str | None]] = {}
    for line in lines:
        fields = line.split()
        if len(fields) >= 2:
            version = fields[3] if len(fields) > 3 and fields[3] != "<no value>" else None
            out[fields[0]] = {"name": fields[1].lstrip("/"), "image": fields[2] if len(fields) > 2 else None,
                              "version": version}
    return out


def container_of(cgroup_path: str, names: dict[str, str]) -> str | None:
    match = CONTAINER_ID.search(cgroup_path)
    return (names.get(match.group(1)) or match.group(1)[:12]) if match else None
