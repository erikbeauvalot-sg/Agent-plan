"""mcp-elk (démo) : recherche et agrégation sur les sources documents et logs du catalogue.

Même contrat d'outils que le futur mcp-elk ; ici les données viennent des fichiers de demo_data/.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from diagagent import catalog
from diagagent.mcp_servers.common import read_only_tool

server = MCPServer("mcp-elk", instructions="Recherche en lecture seule dans les sources du catalogue.")


@read_only_tool(server)
def search(source: str, time_from: str | None = None, time_to: str | None = None,
           filters: dict[str, Any] | None = None, text: str | None = None, size: int = 50) -> dict[str, Any]:
    """Cherche des documents dans une source du catalogue.

    source : id de la source (voir list_sources). time_from / time_to : ISO 8601 UTC ; par défaut les
    24 h précédant l'heure de référence. filters : égalité exacte par champ (notation pointée, ex.
    {"affected_ci.hostname": "srv-pay-01"}) ; une liste vaut « l'une des valeurs ». text : sous-chaîne
    cherchée dans tout le document. size : nombre max de documents renvoyés (plafonné par la source).
    """
    return catalog.search(source, filters, text, time_from, time_to, size)


@read_only_tool(server)
def aggregate(source: str, field: str, time_from: str | None = None, time_to: str | None = None,
              filters: dict[str, Any] | None = None, top: int = 10) -> dict[str, Any]:
    """Compte les valeurs les plus fréquentes d'un champ (top N) avec première et dernière occurrence.

    Utile pour les logs : field="message" avec filters={"host": ..., "level": "ERROR"}.
    """
    return catalog.aggregate(source, field, filters, time_from, time_to, top)


if __name__ == "__main__":
    server.run()
