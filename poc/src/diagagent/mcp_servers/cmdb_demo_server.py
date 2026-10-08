"""mcp-cmdb (démo) : CI, dépendances et propriétaires, depuis la source cmdb du catalogue."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
from diagagent.mcp_servers.common import read_only_tool

server = MCPServer("mcp-cmdb", instructions="CMDB en lecture seule.")


def _find(id_or_hostname: str) -> dict[str, Any]:
    key = id_or_hostname.strip().lower()
    for ci in catalog.rows("cmdb"):
        if key in (ci["ci_id"].lower(), ci["hostname"].lower()):
            return ci
    raise ValueError(f"CI introuvable : {id_or_hostname}")


@read_only_tool(server)
def get_ci(id_or_hostname: str) -> dict[str, Any]:
    """Fiche CMDB d'un CI, par identifiant (CIxxxxxxx) ou nom d'hôte."""
    return _find(id_or_hostname)


@read_only_tool(server)
def get_dependencies(ci: str, depth: int = 1) -> dict[str, Any]:
    """Dépendances d'un CI (ce dont il dépend) et CI qui dépendent de lui, jusqu'à `depth` niveaux."""
    root = _find(ci)
    by_id = {c["ci_id"]: c for c in catalog.rows("cmdb")}
    depends_on, frontier = [], [root["ci_id"]]
    for level in range(1, max(1, min(depth, 3)) + 1):
        nxt = []
        for cid in frontier:
            for dep in by_id[cid]["depends_on"]:
                depends_on.append({"level": level, "ci_id": dep, "hostname": by_id[dep]["hostname"],
                                   "type": by_id[dep]["type"]})
                nxt.append(dep)
        frontier = nxt
    used_by = [{"ci_id": c["ci_id"], "hostname": c["hostname"], "type": c["type"]}
               for c in by_id.values() if root["ci_id"] in c["depends_on"]]
    return {"ci": root["ci_id"], "hostname": root["hostname"], "depends_on": depends_on, "used_by": used_by}


@read_only_tool(server)
def get_owners(ci: str) -> dict[str, Any]:
    """Équipe propriétaire d'un CI."""
    c = _find(ci)
    return {"ci": c["ci_id"], "hostname": c["hostname"], "owner_team": c["owner_team"]}


if __name__ == "__main__":
    server.run()
