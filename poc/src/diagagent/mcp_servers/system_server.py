"""mcp-system : état en direct d'une machine par SSH (mémoire, processus, conteneurs, OOM).

Lecture seule : chaque outil lance une sonde fixe de remote/diagagent-probe. Les réponses décrivent
l'état au moment de l'appel, pas à l'heure de référence de l'investigation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
from diagagent.connectors import ssh
from diagagent.mcp_servers.common import read_only_tool

server = MCPServer("mcp-system", instructions="État en direct des machines par SSH, en lecture seule.")
MAX_PROCESSES = 30
NOTE = "État en direct au moment de l'appel (observed_at), pas à l'heure de référence de l'investigation."


def _probe() -> ssh.SshProbe:
    cards = catalog.sources_of_kind("system")
    if not cards:
        raise ValueError("Aucune machine joignable en SSH (variable SSH_HOSTS)")
    return ssh.SshProbe(cards[0])


def _run(host: str, probe: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
    p = _probe()
    data = p.run(host, probe)
    head = {"host": host, "source": p.source_id,
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": NOTE}
    return head, data


@read_only_tool(server)
def list_ssh_hosts() -> dict[str, Any]:
    """Machines que l'on peut interroger en direct par SSH (mêmes noms que dans Prometheus)."""
    p = _probe()
    return {"source": p.source_id, "hosts": sorted(p.hosts)}


@read_only_tool(server)
def host_memory(host: str) -> dict[str, Any]:
    """Mémoire et swap d'une machine maintenant : RAM disponible, swap utilisé, pression mémoire (PSI,
    % du temps où des tâches attendent la mémoire), swappiness."""
    head, data = _run(host, "memory")
    m = ssh.meminfo(data.get("meminfo", []))
    uptime = data.get("uptime", ["0"])[0].split()[0]
    return {**head,
            "mem_total_mb": ssh.mb(m.get("MemTotal", 0)), "mem_available_mb": ssh.mb(m.get("MemAvailable", 0)),
            "anon_mb": ssh.mb(m.get("AnonPages", 0)), "cached_mb": ssh.mb(m.get("Cached", 0)),
            "swap_total_mb": ssh.mb(m.get("SwapTotal", 0)),
            "swap_used_mb": ssh.mb(m.get("SwapTotal", 0) - m.get("SwapFree", 0)),
            "swap_cached_mb": ssh.mb(m.get("SwapCached", 0)),
            "committed_mb": ssh.mb(m.get("Committed_AS", 0)),
            "pressure_pct": ssh.psi(data.get("psi", [])),
            "swappiness": int(data["swappiness"][0]) if data.get("swappiness") else None,
            "uptime_days": round(float(uptime) / 86400, 1)}


@read_only_tool(server)
def top_processes(host: str, sort_by: str = "rss", limit: int = 15) -> dict[str, Any]:
    """Processus qui occupent le plus de RAM (sort_by="rss") ou de swap (sort_by="swap"), avec leur
    conteneur Docker s'il y en a un. Le swap d'un processus est la part de sa mémoire envoyée en swap."""
    if sort_by not in ("rss", "swap"):
        raise ValueError("sort_by : rss ou swap")
    head, data = _run(host, "processes")
    swap = ssh.by_pid(data.get("swap", []))
    cgroups = ssh.by_pid(data.get("cgroup", []))
    names = ssh.container_names(data.get("docker", []))
    procs = []
    for line in data.get("ps", []):
        fields = line.split(None, 4)
        if len(fields) < 5 or not fields[0].isdigit():
            continue
        pid, user, rss, elapsed, args = fields
        if args.startswith("["):  # thread du noyau
            continue
        procs.append({"pid": int(pid), "user": user, "command": args[:200],
                      "rss_mb": ssh.mb(int(rss)),
                      "swap_mb": ssh.mb(int(swap.get(int(pid), "0 kB").split()[0])),
                      "running_h": round(int(elapsed) / 3600, 1),
                      "container": ssh.container_of(cgroups.get(int(pid), ""), names)})
    key = "rss_mb" if sort_by == "rss" else "swap_mb"
    procs.sort(key=lambda p: p[key], reverse=True)
    return {**head, "sort_by": sort_by, "processes_total": len(procs),
            "rss_total_mb": round(sum(p["rss_mb"] for p in procs), 1),
            "swap_total_mb": round(sum(p["swap_mb"] for p in procs), 1),
            "processes": procs[:max(1, min(limit, MAX_PROCESSES))]}


@read_only_tool(server)
def container_memory(host: str) -> dict[str, Any]:
    """Mémoire de chaque conteneur Docker d'après ses cgroups : utilisée maintenant, en swap, pic depuis
    le démarrage du conteneur (peak_mb, cache de fichiers compris : borne haute, pas un besoin de mémoire),
    limite éventuelle, image et version (pour chercher les problèmes connus de cette version)."""
    head, data = _run(host, "containers")
    info = ssh.containers(data.get("docker", []))
    out = []
    for line in data.get("cgroups", []):
        cid, current, swap_now, peak, limit = (line.split() + ["-"] * 5)[:5]
        meta = info.get(cid, {})
        out.append({"container": meta.get("name") or cid[:12], "id": cid[:12],
                    "image": meta.get("image"), "version": meta.get("version"),
                    "mem_mb": ssh.mb(int(current) / 1024),
                    "swap_mb": ssh.mb(int(swap_now) / 1024) if swap_now.isdigit() else None,
                    "peak_mb": ssh.mb(int(peak) / 1024) if peak.isdigit() else None,
                    "limit_mb": ssh.mb(int(limit) / 1024) if limit.isdigit() else None})
    out.sort(key=lambda c: c["mem_mb"], reverse=True)
    return {**head, "total": len(out), "containers": out}


@read_only_tool(server)
def oom_events(host: str) -> dict[str, Any]:
    """Messages du noyau des 7 derniers jours sur le manque de mémoire (OOM killer, processus tués)."""
    head, data = _run(host, "oom")
    lines = data.get("oom", [])
    return {**head, "total": len(lines), "events": [line[:300] for line in lines]}


if __name__ == "__main__":
    server.run()
