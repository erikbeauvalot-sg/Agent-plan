# Suivi du POC

Chaque étape est livrée par une pull request sur ce dépôt, testée en CI (GitHub Actions) et
utilisable seule. Ce fichier est mis à jour à chaque PR.

| Étape | Contenu | État |
| --- | --- | --- |
| 1. Socle | Couche LLM agnostique (Azure OpenAI, compatible OpenAI), catalogue, 4 serveurs MCP de démonstration, agent principal seul, traces en fichiers, ligne de commande, tests | Fait (PR #1) |
| 2. Sous-agents | `write_plan`, `spawn_subagent`, `wait_subagents`, `submit_report` ; rôles host, logs, metrics, events, changes, generic ; rapports structurés validés ; parallélisme et budgets ; arrêt d'un sous-agent | Fait (PR #3) |
| 3. Interface web | Passerelle FastAPI, flux temps réel (SSE) sur `events.jsonl`, conversation, graphe d'investigation, chronologie, détail d'agent, signaux, arrêt d'agent ; connexion par `auth/users.yaml` (Opérateur, Administrateur), journal d'accès | Fait (PR #4) |
| 4. Sources réelles | Connecteurs Prometheus (métriques, historique d'alertes) et Alertmanager (alertes, silences), fiches catalogue, mode sans démonstration | Fait pour Prometheus et Alertmanager (PR #2) |
| 5. Actions et évaluation | `propose_action` et `actions.json` affichés dans l'interface ; jeu de cas `eval/cases.yaml` et `diagagent eval` ; adaptateur `replay` et `diagagent replay` | Fait (PR #5) |
| 6. Catégorisation et playbooks | Sept playbooks `playbooks/<categorie>.yaml` ; classifieur (appel au modèle séparé, sortie structurée) ; décision : playbook appliqué, deux playbooks combinés, question de précision, `autre` ; playbook injecté dans le prompt de l'agent principal ; outil `requalify` ; catégorie, confiance et version du playbook dans `manifest.json` et `index.jsonl` ; catégorie affichée et corrigeable dans l'interface, filtre de l'historique ; contrôle `category` dans `diagagent eval` | En cours |
| 7. Base de cas et apprentissage | Retours sur les diagnostics (utile, partiel, faux) ; base `knowledge/cases/` et `knowledge/index.jsonl` ; demandes proches données au classifieur et cas « déjà vu » à l'agent principal ; rôle Superviseur ; `diagagent learn` écrit des propositions dans `playbooks/proposals/`, rejouées sur le jeu d'évaluation ; validation dans l'interface ; catégories `draft` en observation ; indicateurs par catégorie | À faire |

## Critères de sortie

- Étape 1 : sur le scénario de démonstration, l'agent trouve le changement CHG0034567 comme cause
  probable, avec des preuves citées, et chaque appel est tracé dans `runs/`.
- Étape 2 : même résultat, obtenu par des sous-agents lancés en parallèle par l'agent principal.
- Étape 3 : on suit l'investigation dans le navigateur et on arrête un sous-agent sans arrêter les autres.
- Étape 6 : chaque cas du jeu d'évaluation est classé dans la catégorie attendue ; la catégorie et le
  playbook appliqués apparaissent dans les traces et dans l'interface, où l'utilisateur peut corriger la
  catégorie ; une demande sans entité indispensable reçoit une question de précision.
- Étape 7 : une investigation confirmée devient un cas réutilisé par la suivante ; une proposition
  d'évolution de playbook est rejouée sur le jeu d'évaluation puis acceptée ou rejetée par un Superviseur,
  et chaque décision est tracée.

## Journal

- 2026-10-08 : étape 1 ouverte.
- 2026-10-08 : sources du POC connues (Prometheus et Alertmanager d'Erik) ; connecteurs ouverts en avance.
- 2026-10-08 : PR #1 et #2 fusionnées ; étape 2 ouverte.
- 2026-10-08 : PR #3 fusionnée ; étape 3 ouverte (écran en JavaScript sans étape de build, React reporté à l'industrialisation).
- 2026-10-08 : PR #4 fusionnée ; étape 5 ouverte.
- 2026-10-08 : PR #5 fusionnée, les cinq étapes sont livrées ; adaptateur Claude ajouté pour le POC à la maison (PR #6).
- 2026-10-09 : document d'architecture mis à jour (catégorisation des demandes, playbooks, boucle
  d'apprentissage) ; étapes 6 et 7 ajoutées, étape 6 ouverte.
