"""mcp-catalog : découverte des sources et résolution des entités."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
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
    """Résout un nom libre (host, CI, service, alias métier) en entités connues de la CMDB."""
    needle = name.strip().lower()
    services = catalog.load_yaml("glossary.yaml").get("services", {})
    matched_services = [code for code, s in services.items()
                        if needle == code.lower() or needle == s["name"].lower()
                        or any(needle == a.lower() or a.lower() in needle for a in s.get("aliases", []))]
    cis = [ci for ci in catalog.rows("cmdb")
           if needle in (ci["hostname"].lower(), ci["ci_id"].lower(), ci["application"].lower())
           or ci["service"] in matched_services]
    return {
        "query": name,
        "services": [{"code": c, "name": services[c]["name"]} for c in matched_services],
        "cis": [{"ci_id": c["ci_id"], "hostname": c["hostname"], "type": c["type"], "service": c["service"]}
                for c in cis],
        "ambiguous": len(cis) > 1 and not matched_services,
        "found": bool(cis or matched_services),
    }


if __name__ == "__main__":
    server.run()
