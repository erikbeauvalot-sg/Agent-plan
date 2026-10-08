# Suivi du POC

Chaque étape est livrée par une pull request sur ce dépôt, testée en CI (GitHub Actions) et
utilisable seule. Ce fichier est mis à jour à chaque PR.

| Étape | Contenu | État |
| --- | --- | --- |
| 1. Socle | Couche LLM agnostique (Azure OpenAI, compatible OpenAI), catalogue, 4 serveurs MCP de démonstration, agent principal seul, traces en fichiers, ligne de commande, tests | Fait (PR #1) |
| 2. Sous-agents | `write_plan`, `spawn_subagent`, `wait_subagents`, `submit_report` ; rôles host, logs, metrics, events, changes, generic ; rapports structurés validés ; parallélisme et budgets ; arrêt d'un sous-agent | En revue |
| 3. Interface web | Passerelle FastAPI, flux temps réel (SSE) sur `events.jsonl`, conversation, graphe d'investigation, chronologie, arrêt d'agent ; connexion par `auth/users.yaml` (Opérateur, Administrateur) | À faire |
| 4. Sources réelles | Connecteurs Prometheus (métriques, historique d'alertes) et Alertmanager (alertes, silences), fiches catalogue, mode sans démonstration | Fait pour Prometheus et Alertmanager (PR #2) |
| 5. Actions et évaluation | `propose_action` et `actions.json` ; jeu de questions de référence, adaptateur `replay`, comparaison de modèles | À faire |

## Critères de sortie

- Étape 1 : sur le scénario de démonstration, l'agent trouve le changement CHG0034567 comme cause
  probable, avec des preuves citées, et chaque appel est tracé dans `runs/`.
- Étape 2 : même résultat, obtenu par des sous-agents lancés en parallèle par l'agent principal.
- Étape 3 : on suit l'investigation dans le navigateur et on arrête un sous-agent sans arrêter les autres.

## Journal

- 2026-10-08 : étape 1 ouverte.
- 2026-10-08 : sources du POC connues (Prometheus et Alertmanager d'Erik) ; connecteurs ouverts en avance.
- 2026-10-08 : PR #1 et #2 fusionnées ; étape 2 ouverte.
