# POC de l'agent de diagnostic

Mise en œuvre progressive de l'[architecture](../docs/architecture-agent-diagnostic.md), sur des sources
de démonstration. Avancement : [suivi du POC](../docs/poc-suivi.md).

## Ce que contient l'étape 1

| Brique | Où | Rôle |
| --- | --- | --- |
| Couche LLM agnostique | `src/diagagent/llm/` | Format pivot, adaptateurs `azure_openai`, `openai_compatible` (Ollama, vLLM) et `scripted` (tests) |
| Catalogue | `catalog/` | Une fiche YAML par source, glossaire, relations entre sources |
| Serveurs MCP | `src/diagagent/mcp_servers/` | `mcp-catalog`, `mcp-elk`, `mcp-cmdb`, `mcp-metrics`, en lecture seule |
| Agent principal | `src/diagagent/agent.py`, `prompts/lead.md` | Boucle d'agent, budget, jeton d'annulation |
| Traces | `src/diagagent/runlog.py` → `runs/` | Manifest, transcript, appels d'outils, événements, analyse |
| Données de démo | `demo_data/` | Scénario : lenteurs du service Paiement la nuit du 6 octobre 2026 |

Les serveurs MCP de démonstration lisent les fichiers de `demo_data/`. Pour brancher une vraie source,
on change le `backend` de sa fiche catalogue et le connecteur correspondant ; l'agent ne change pas.

## Installation

Python 3.11 ou plus.

```bash
cd poc
python -m venv .venv && source .venv/bin/activate
pip install -e '.[azure,dev]'
python -m pytest            # 12 tests, sans réseau ni modèle
diagagent tools             # démarre les 4 serveurs MCP et liste leurs outils
```

## Brancher le modèle

**Azure OpenAI (défaut, `config/models.yaml`)**

```bash
export AZURE_OPENAI_ENDPOINT=https://<ressource>.openai.azure.com
az login                    # authentification Entra ID (DefaultAzureCredential)
diagagent check             # un appel court pour vérifier l'accès au déploiement gpt-5.6-luna
```

Le nom du déploiement se règle dans `config/models.yaml` (`deployment`). Pour une clé d'API à la place
d'Entra ID : `auth: api_key` et la variable `AZURE_OPENAI_API_KEY`.

**Modèle local** : décommenter la ligne `provider: local` de `config/models.yaml` (Ollama ou vLLM).

## Lancer une investigation

Le scénario de démonstration se joue à l'heure de référence du 7 octobre 2026, 06:00 UTC :

```bash
diagagent --now 2026-10-07T06:00:00Z ask "Pourquoi le service paiement est-il lent depuis hier soir ?"
diagagent --now 2026-10-07T06:00:00Z ask "Quels incidents sont ouverts sur srv-pay-01 ?"
```

La réponse s'affiche, et tout est tracé dans `runs/AAAA/MM/JJ/<id>/` :

```
manifest.json         question, utilisateur, modèle, statut, tokens
question.md / analysis.md
lead/system_prompt.md prompt système exact
lead/transcript.jsonl chaque requête et réponse du modèle
lead/calls/0001.json  chaque appel d'outil : entrée, sortie, durée, erreur
events.jsonl          journal horodaté (base du futur suivi temps réel)
```

`runs/index.jsonl` liste toutes les investigations.

## Régénérer les données de démonstration

```bash
python demo_data/generate.py
```
