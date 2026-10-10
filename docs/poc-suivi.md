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
| 6. Catégorisation et playbooks | Sept playbooks `playbooks/<categorie>.yaml` ; classifieur (appel au modèle séparé, sortie structurée) ; décision : playbook appliqué, deux playbooks combinés, question de précision, `autre` ; playbook injecté dans le prompt de l'agent principal ; outil `requalify` ; catégorie, confiance et version du playbook dans `manifest.json` et `index.jsonl` ; catégorie affichée et corrigeable dans l'interface, filtre de l'historique ; contrôle `category` dans `diagagent eval` | Fait (PR #9) |
| 7. Base de cas et apprentissage | Retours sur les diagnostics (utile, partiel, faux) ; base `knowledge/cases/` et `knowledge/index.jsonl` ; demandes proches données au classifieur et cas « déjà vu » à l'agent principal ; rôle Superviseur ; `diagagent learn` écrit des propositions dans `playbooks/proposals/`, rejouées sur le jeu d'évaluation ; validation dans l'interface ; catégories `draft` en observation ; indicateurs par catégorie | Fait (PR #10, fusionnée dans `main` par la PR #12) |
| 8. Rôles complets et revue des actions | Rôles Lecteur et Auditeur, matrice complète du document ; partage d'une investigation ; détail des agents réservé aux rôles autorisés ; arrêt immédiat pour Superviseur et Administrateur ; validation ou rejet des actions proposées par un Superviseur ; écran Administration : actions à valider, coûts en tokens, journal d'accès | Fait (PR #11, fusionnée dans `main` par la PR #12) |
| 9. Qualité des diagnostics | Chaîne de dépendances dans les playbooks (la cause est souvent sur la dépendance) ; relances limitées aux ratés consécutifs ; étapes du playbook lancées en vagues successives ; identifiants cités dans les rapports ; `diagagent eval --repeat` | Fait (PR #13, #14) |
| 10. Modèles et coûts | Modèle et tokens par rôle et par agent, tokens de raisonnement ; profils de modèles (`ollama` par défaut, `openai`, `azure`) choisis par requête, en ligne de commande ou dans l'interface | Fait (PR #15, #16, #17) |
| 11. Données maison | Jeux de sources `demo` et `maison` (Prometheus et Alertmanager d'Erik) choisis par investigation ; page d'accueil en tableau de bord ; connexion par formulaire | Fait (PR #18, #19) |
| 12. Diagnostic système | Swap, pression mémoire (PSI) et OOM dans les métriques, heure du pic (`max_at`) ; source SSH en lecture seule (`mcp-system`, sonde fixe `remote/diagagent-probe`) ; historique par conteneur (cAdvisor) et mises à jour de conteneurs comme changements | Fait (PR #20, #21, #24) |
| 13. Remédiation | Quatre pistes examinées après la cause : impact réel, problème connu, réglage de l'application, réglage du système ; règle d'alerte lue dans Prometheus (`alert_rule`) ; recherche web (`mcp-web`, DuckDuckGo ou SearXNG, garde-fous sur la requête et l'adresse) ; actions dédoublonnées, règle PromQL testée avant d'être proposée | Fait (PR #22, #24) |
| 14. Classifieur | Entité oubliée par le modèle complétée depuis la demande : numéro INC ou CHG, nom d'une alerte connue (Alertmanager, règles Prometheus) ; demande `autre` qui nomme une alerte connue classée `analyse-evenement` | Fait (PR #26) |
| 15. Vagues imposées | Réponse finale contrôlée : étapes du playbook dont aucun rôle spécialisé n'a été lancé, rappelées une fois à l'agent principal ; valeurs de `propose_action` reconnues sans casse ni accents | Fait (PR #27) |
| 16. Relancer une demande | Bouton « Relancer… » : nouvelle demande préremplie (question, modèle, données, catégorie), lancée après modification des options ; choix de la catégorie sur l'accueil ; lien `rerun_of` vers l'investigation d'origine | Fait (PR #28) |
| 17. Rappel précoce des vagues | Après 8 appels directs de l'agent principal sans sous-agent spécialisé (`early_wave_reminder`), rappel des étapes du playbook, une fois | Fait (PR #29) |
| CI | Merge automatique de toute PR non brouillon vers `main` dès que les tests passent | Fait (PR #23) |

## Reste à faire

- **Critères de sortie** : le document d'architecture demande 20 questions simples justes et une cause
  correcte sur une majorité de 20 incidents passés ; `eval/cases.yaml` ne compte que 9 cas, tous sur
  la démo. Agrandir le jeu, ajouter des cas maison, mesurer avec `--repeat`.
- **Contrôles des faits et des actions dans le code** : l'agent affirme encore des chiffres contraires aux
  mesures (« conteneurs au-delà de 1 Go » pour des pics de 323 et 539 Mo) et propose une limite incohérente
  avec ce qu'il écrit. À vérifier dans le code : limite mémoire jamais sous le pic mesuré, pas d'alerte qui
  existe déjà, règle PromQL qui rend des séries.
- **Industrialisation** (étape 4 du document d'architecture) : connecteur `mcp-elk` réel et Druid,
  branchement Azure OpenAI GPT-5.6 Luna et comparaison de modèles sur le jeu d'évaluation, annuaire
  d'entreprise (OIDC), quotas et coûts Azure, archivage. Elle attend les réponses aux points ouverts du
  document d'architecture et un accès à ELK et à Azure.

## Critères de sortie

- Étape 1 : sur le scénario de démonstration, l'agent trouve le changement CHG0034567 comme cause
  probable, avec des preuves citées, et chaque appel est tracé dans `runs/`.
- Étape 2 : même résultat, obtenu par des sous-agents lancés en parallèle par l'agent principal.
- Étape 3 : on suit l'investigation dans le navigateur et on arrête un sous-agent sans arrêter les autres.
- Étape 6 : chaque cas du jeu d'évaluation est classé dans la catégorie attendue ; la catégorie et le
  playbook appliqués apparaissent dans les traces et dans l'interface, où l'utilisateur peut corriger la
  catégorie ; une demande sans entité indispensable reçoit une question de précision.
- Étape 8 : chaque fonction de la matrice des rôles est vérifiée par un test ; une action validée
  par un Superviseur est tracée et n'est jamais exécutée.
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
- 2026-10-09 : PR #9 ouverte (étape 6, catégorie juste sur 9 cas sur 9 avec gpt-oss:20b en local) ; étape 7
  livrée par la PR #10, empilée sur la #9.
- 2026-10-09 : PR #8 complétée (opérateurs dans les filtres) ; étape 8 livrée par la PR #11, empilée sur la #10.
- 2026-10-09 : PR #8 et #9 fusionnées dans `main` ; les PR #10 et #11, fusionnées dans leurs branches
  de base, arrivent dans `main` par la PR #12, avec le signalement des documents hors période et la
  recherche texte qui ignore les champs masqués.
- 2026-10-10 : PR #13 et #14 fusionnées (qualité des diagnostics, tirée des traces ratées avec `gpt-oss:20b`).
- 2026-10-10 : PR #15 à #17 fusionnées (modèles, tokens, profils ; Ollama par défaut).
- 2026-10-10 : PR #18 et #19 fusionnées (données maison, page d'accueil, connexion).
- 2026-10-10 : PR #20 à #22 fusionnées, à partir de l'alerte SwapUsageHigh sur xdocker (swap, SSH,
  remédiation et recherche web).
- 2026-10-10 : PR #23 fusionnée : les PR suivantes se mergent seules après les tests ; PR #24
  fusionnée (conteneurs).
- 2026-10-10 : PR #25 fusionnée (suivi à jour) ; PR #26 ouverte (alerte nommée reconnue par le classifieur).
- 2026-10-10 : PR #26 fusionnée (classifieur, écriture atomique des traces) ; PR #27 ouverte (vagues du playbook rappelées à l'agent principal).
- 2026-10-10 : PR #27 fusionnée (vagues rappelées) ; PR #28 ouverte (relancer une demande avec d'autres options).
- 2026-10-10 : PR #28 fusionnée (relancer une demande) ; PR #29 ouverte (rappel précoce des vagues : 6 sous-agents spécialisés lancés, dont web, sur SwapUsageHigh).
