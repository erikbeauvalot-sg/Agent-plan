"""mcp-catalog : découverte des sources et résolution des entités."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
from diagagent.connectors import metrics
from diagagent.mcp_servers.common import read_only_tool

server = MCPServer("mcp-catalog", instructions="Catalogue des sources de données de production.")


@read_only_tool(server)
def list_sources() -> list[dict[str, Any]]:
    """Liste les sources disponibles (id, type, description courte)."""
    return [{"id": c["id"], "kind": c.get("kind"), "description": " ".join(c["description"].split())}
            for c in catalog.load_catalog().values()]


@read_only_tool(server)
def describe_source(id: str) -> dict[str, Any]:
    """Fiche complète d'une source : champs, clés d'entité, champ de date, exemples, limites."""
    card = dict(catalog.get_source(id))
    card.pop("backend", None)
    card["relations"] = {entity: keys.get(id) for entity, keys in catalog.load_yaml("relations.yaml").items()
                         if keys.get(id)}
    return card


@read_only_tool(server)
def resolve_entity(name: str) -> dict[str, Any]:
    """Résout un nom libre (host, CI, service, alias métier) en entités connues : CMDB et hosts suivis
    par les outils de métriques. Une portée (« SI », « la prod ») rend scope = global et la consigne
    d'un état global : ce n'est pas un objet introuvable."""
    needle = name.strip().lower()
    services = catalog.load_yaml("glossary.yaml").get("services", {})
    if scope := catalog.scope_of(name):
        s = catalog.scopes()[scope]
        return {"query": name, "scope": scope, "meaning": s.get("meaning", s["name"]),
                "guidance": " ".join(str(s.get("guidance", "")).split()),
                "services": [{"code": c, "name": v["name"]} for c, v in services.items()],
                "cis": [], "monitored_hosts": [], "ambiguous": False, "found": True}
    matched_services = [code for code, s in services.items()
                        if needle == code.lower() or needle == s["name"].lower()
                        or any(needle == a.lower() or a.lower() in needle for a in s.get("aliases", []))]
    cmdb = catalog.rows("cmdb") if "cmdb" in catalog.load_catalog() else ()
    cis = [ci for ci in cmdb
           if needle in (ci["hostname"].lower(), ci["ci_id"].lower(), ci["application"].lower())
           or ci["service"] in matched_services]
    monitored = []
    for backend in metrics.backends():
        try:
            hosts = backend.hosts()
        except ValueError as e:
            monitored.append({"source": backend.source_id, "error": str(e)})
            continue
        monitored += [{"source": backend.source_id, "host": h} for h in hosts if needle in h.lower()]
    return {
        "query": name,
        "services": [{"code": c, "name": services[c]["name"]} for c in matched_services],
        "cis": [{"ci_id": c["ci_id"], "hostname": c["hostname"], "type": c["type"], "service": c["service"]}
                for c in cis],
        "monitored_hosts": monitored,
        "ambiguous": len(cis) > 1 and not matched_services,
        "found": bool(cis or matched_services or any("host" in m for m in monitored)),
    }


if __name__ == "__main__":
    server.run()
