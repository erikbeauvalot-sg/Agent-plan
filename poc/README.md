# POC de l'agent de diagnostic

Mise en œuvre progressive de l'[architecture](../docs/architecture-agent-diagnostic.md), sur des sources
de démonstration. Avancement : [suivi du POC](../docs/poc-suivi.md).

## Ce que contient le POC

| Brique | Où | Rôle |
| --- | --- | --- |
| Couche LLM agnostique | `src/diagagent/llm/` | Format pivot, adaptateurs `azure_openai`, `openai_compatible` (Ollama, vLLM) et `scripted` (tests) |
| Catalogue | `catalog/` | Une fiche YAML par source, glossaire, relations entre sources |
| Serveurs MCP | `src/diagagent/mcp_servers/` | `mcp-catalog`, `mcp-elk`, `mcp-cmdb`, `mcp-metrics`, en lecture seule |
| Catégorisation et playbooks | `src/diagagent/playbooks.py`, `playbooks/<catégorie>.yaml` | Classifieur, décision (playbook, combinaison, précision), stratégie de collecte par catégorie |
| Base de cas et apprentissage | `src/diagagent/knowledge.py`, `src/diagagent/learning.py` | Avis sur les diagnostics, cas confirmés, propositions d'évolution rejouées et validées par un Superviseur, indicateurs |
| Agent principal | `src/diagagent/agent.py`, `prompts/lead.md` | Boucle d'agent, budget, jeton d'annulation |
| Sous-agents | `src/diagagent/orchestrator.py`, `agents/<rôle>.yaml`, `prompts/subagent.md` | Plan, lancement en parallèle, rapports structurés, arrêt |
| Interface web | `src/diagagent/web/` | Passerelle FastAPI (connexion, rôles, flux temps réel, arrêt) et écran de suivi |
| Évaluation | `src/diagagent/evaluation.py`, `eval/`, `llm/replay.py` | Jeu de cas, contrôles automatiques, rejeu sans modèle |
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
python -m pytest            # tests sans réseau ni modèle
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

**Claude (POC à la maison)**

Réservé au POC sur tes propres sources : en production, les données ne partent pas chez un
fournisseur de modèle externe et l'agent reste sur Azure OpenAI.

```bash
pip install -e '.[claude]'
export ANTHROPIC_API_KEY=sk-ant-...   # clé créée sur platform.claude.com (ou `ant auth login`)
```

La clé peut aussi aller dans `poc/.env` (`ANTHROPIC_API_KEY=sk-ant-...`), ignoré par git : la commande
`diagagent` charge ce fichier au démarrage sans écraser une variable déjà exportée. PROMETHEUS_URL
et ALERTMANAGER_URL peuvent y figurer aussi.

Dans `config/models.yaml`, remplacer les deux lignes `lead` et `subagent` par les lignes Claude
commentées (`provider: claude, model: claude-opus-5-5`), puis lancer `diagagent check`.
`reasoning` règle l'effort de Claude (`low`, `medium`, `high`) ; la réflexion adaptative reste active.
Le fournisseur `claude` active aussi le cache de prompt (l'historique déjà envoyé est relu à moindre coût)
et `fallbacks: default`, qui relance sur un modèle de repli une requête refusée par un filtre de sûreté.

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
plan.md               plan d'investigation de l'agent principal
subagents/T01-host-srv-pay-01/
  prompt.md           prompt généré par l'agent principal
  transcript.jsonl, calls/…, report.json
events.jsonl          journal horodaté (base du futur suivi temps réel)
```

`runs/index.jsonl` liste toutes les investigations.

## Catégorisation et playbooks

Avant l'agent principal, un appel au modèle séparé (le classifieur) range la demande dans une des
catégories de `playbooks/` : `information`, `indisponibilite`, `performance`, `analyse-evenement`,
`impact-change`, `tendance` ou `autre`. Il reçoit la description et les exemples de chaque catégorie
active et rend la catégorie, sa confiance, une éventuelle deuxième catégorie, les entités repérées et
les entités indispensables qui manquent.

| Classification | Ce qui se passe |
| --- | --- |
| Une catégorie | Son playbook est injecté dans le prompt de l'agent principal comme plan de départ |
| Deux catégories plausibles (confiance moyenne ou faible) | Les deux playbooks sont injectés ; l'agent commence par les étapes communes puis tranche |
| Entité indispensable manquante (« mon site » sans dire lequel) | L'investigation s'arrête au statut `needs_clarification` avec la question à poser ; l'interface propose de préciser et relancer |
| Aucune catégorie, ou classifieur indisponible ou illisible | Catégorie `autre`, stratégie générique |

En cours de route, l'agent principal peut appeler `requalify` si les faits contredisent la catégorie ;
le changement est tracé (`category_changed` dans `events.jsonl`). La catégorie, sa confiance et la
version des playbooks appliqués sont dans `manifest.json` (clé `category`) et dans `runs/index.jsonl`.

```bash
diagagent playbooks                               # valide et liste les playbooks
diagagent ask --category performance "…"          # impose la catégorie, sans classifieur
```

Le classifieur utilise le rôle `classifier` de `config/models.yaml` ; absent, il prend le modèle de
`subagent`. Dans l'interface, la catégorie s'affiche sous la question ; l'auteur ou un administrateur
peut la corriger, ou relancer avec une autre catégorie. Chaque correction est ajoutée à
`runs/feedback/categories.jsonl`, qui servira à l'apprentissage (étape 7). L'historique se filtre par
catégorie.

## Base de cas et apprentissage

L'agent ne modifie jamais seul ses catégories ni ses playbooks : il propose, un Superviseur valide.

**Ce qui alimente l'apprentissage**

- Les corrections de catégorie faites dans l'interface (`runs/feedback/categories.jsonl`).
- L'avis sur chaque diagnostic, donné sous la réponse : utile, partiel ou faux, avec la cause réelle
  si on la connaît (`runs/feedback/diagnostics.jsonl`).
- Les cas confirmés : un diagnostic jugé utile, avec sa cause, peut être enregistré comme cas
  (case à cocher dans l'interface, ou `diagagent case add <run_id> --cause "…"`). Le cas va dans
  `knowledge/cases/<run_id>.yaml` et dans l'index `knowledge/index.jsonl`.

**Ce qui s'en sert tout de suite**

- Le classifieur reçoit les demandes passées les plus proches dont la catégorie est confirmée.
- L'agent principal reçoit les cas déjà vus proches de la demande (mots et entités en commun), à
  vérifier, jamais à recopier sans preuve.

**Agent d'apprentissage**

```bash
diagagent learn                     # analyse les 7 derniers jours, écrit playbooks/proposals/*.yaml
diagagent learn --no-model          # propositions mécaniques seulement
diagagent proposals                 # liste, avec le résultat du rejeu
diagagent proposals accept <id> --by sophie --comment "…"
diagagent playbooks --rollback performance   # revient à la version précédente (history/)
```

| Proposition | D'où elle vient |
| --- | --- |
| Ajout d'exemples à une catégorie | Corrections de catégorie (mécanique) |
| Activation d'une catégorie en observation | Au moins 3 demandes qu'elle aurait captées (mécanique) |
| Nouvelle catégorie, en observation (`draft`) | Demandes classées `autre` ou avec une confiance faible (modèle) |
| Ajout d'hypothèses à un playbook | Cas confirmés dont la cause n'est pas parmi les hypothèses (modèle) |
| Nouvelle description | Confusions récurrentes entre deux catégories (modèle) |

Chaque proposition est rejouée : le classifieur reclasse les demandes de référence (cas de
`eval/cases.yaml` avec une catégorie, demandes confirmées) avec les playbooks actuels puis avec la
proposition. Une proposition qui fait baisser la justesse est écartée (`discarded`). La justesse des
diagnostics n'est pas rejouée dans le POC, car il faudrait une investigation complète par demande.

Un Superviseur accepte ou rejette chaque proposition dans l'écran **Amélioration continue** de
l'interface. L'Administrateur y voit les indicateurs et les propositions, sans pouvoir valider. Une
proposition acceptée écrit la nouvelle version du playbook, garde l'ancienne dans
`playbooks/history/` et trace la décision dans `playbooks/proposals/decisions.jsonl`. Une nouvelle
catégorie démarre en `draft` : le classifieur la voit, mais une demande qui y correspond suit la
deuxième catégorie, ou `autre`. La correspondance est notée (`draft_match`) pour mesurer ce que la
catégorie aurait capté.

L'écran donne aussi, par catégorie : la part des demandes, la part classée `autre`, la part
corrigée, la part de diagnostics jugés justes, la durée et le nombre d'appels d'outils moyens.

## Sous-agents

Pour un diagnostic, l'agent principal écrit `plan.md`, lance un sous-agent par investigation
(`spawn_subagent`), en parallèle, puis attend leurs rapports (`wait_subagents`). Chaque rôle est décrit
dans `agents/<rôle>.yaml` : prompt, serveurs MCP autorisés, budget. Un rôle sans source disponible
n'est pas proposé (en mode maison, `logs` et `changes` disparaissent faute d'ELK). Le modèle des
sous-agents se règle par la clé `subagent` de `config/models.yaml`, ou par rôle.

## Interface web

```bash
diagagent user add erik --role administrateur --name Erik     # demande le mot de passe (12 caractères min.)
diagagent user add sophie --role superviseur --name Sophie    # valide les propositions d'évolution
diagagent serve                                               # http://127.0.0.1:8080
```

Pour l'ouvrir depuis une autre machine du réseau : `diagagent serve --host 0.0.0.0`, et définir
`DIAGAGENT_SESSION_SECRET` pour que les sessions survivent à un redémarrage.

- **Conversation** : on pose la question à gauche ; la réponse s'affiche à la fin, chaque preuve
  `[…/calls/NNNN.json]` est cliquable.
- **Graphe d'investigation** : agent principal et sous-agents, colorés par état, avec la jauge de
  budget et les signaux (bloqué depuis 120 s, boucle, 3 erreurs d'outil, budget à 80 %, erreur modèle).
- **Chronologie** : une ligne par agent, appels au modèle et aux outils.
- **Détail d'un agent** (clic sur un nœud) : prompt reçu, rapport, chaque appel d'outil, réponses du modèle,
  bouton d'arrêt.
- **Arrêt** : un sous-agent arrêté rend un rapport partiel et l'agent principal continue ;
  « Arrêter l'investigation » demande à l'agent principal une synthèse partielle.

Rôles du POC : `operateur` (pose des questions, voit et arrête les siennes) et `administrateur`
(voit et arrête tout, arrêt immédiat). Comptes dans `auth/users.yaml` (mots de passe en Argon2id,
verrouillage 15 min après 5 échecs) ; journal d'accès dans `audit/`.

![Investigation en cours](../docs/images/poc-interface-en-cours.png)

## Actions proposées

L'agent principal enregistre chaque action qu'il recommande avec `propose_action` : type (diagnostic
complémentaire, remédiation, contournement, ouverture de ticket), cible, justification et preuves,
risque, procédure, retour arrière, passage ou non par la gestion des changements. Elles sont écrites
dans `actions.json` et affichées dans l'interface ; aucun outil ne permet de les exécuter.

## Évaluation et rejeu

```bash
diagagent eval                                   # joue eval/cases.yaml avec le modèle configuré
diagagent eval --only diag-paiement              # un seul cas
diagagent replay 20261008T061159Z-5f31           # rejoue une investigation sans appeler le modèle
```

`eval` pose chaque question du jeu de cas et vérifie la réponse : catégorie rendue par le classifieur,
mentions attendues ou interdites, nombre de sous-agents, actions proposées, erreurs d'outil. Le résumé
donne aussi la justesse de catégorisation. Le rapport va dans `eval/results/`.
`eval/cases.yaml` porte sur le scénario de démonstration ; `eval/cases-maison.example.yaml` sert de
modèle pour des questions sur tes propres sources. Changer de modèle dans `config/models.yaml` puis
relancer `eval` permet de comparer les modèles sur les mêmes questions.

`replay` refait passer les décisions enregistrées du modèle dans les outils actuels et signale chaque
appel d'outil dont le résultat a changé : utile après une modification d'un serveur MCP ou du catalogue. La
catégorie d'origine est imposée : le classifieur n'est pas rejoué.

## Brancher Prometheus et Alertmanager

Deux variables suffisent ; les sources de démonstration se coupent avec `DIAGAGENT_DEMO=0` pour que
l'agent ne mélange pas données factices et réelles :

```bash
export PROMETHEUS_URL=http://192.168.1.15:9090
export ALERTMANAGER_URL=http://192.168.1.15:9093
export DIAGAGENT_DEMO=0
diagagent tools             # doit lister list_hosts, promql, list_alerts, alert_history…
diagagent ask "Quelles machines sont suivies et lesquelles ont une alerte en cours ?"
diagagent ask "Pourquoi le NAS était-il lent cette nuit ?"
```

Sans `--now`, l'heure de référence est l'heure réelle. Ce que l'agent obtient :

| Outil | Source | Contenu |
| --- | --- | --- |
| `list_hosts` | Prometheus (`up`) | Machines suivies, job, cible joignable ou non |
| `list_metrics`, `query_metric` | Prometheus | Métriques normalisées (CPU, charge, mémoire, disque, réseau) résumées avec ruptures |
| `promql` | Prometheus | Requête libre, résumée par série |
| `list_alerts`, `list_silences` | Alertmanager | Alertes actives, silences en cours |
| `alert_history` | Prometheus (`ALERTS`) | Alertes passées et leurs intervalles de déclenchement |

Les métriques normalisées sont des modèles PromQL dans `catalog/sources/metrics-prometheus.yaml`,
écrits pour node_exporter ; on les adapte ou on en ajoute selon les exporters installés. Le nom de
host est le label `instance` sans le port (réglable par `host_label`). Un jeton facultatif se passe
par `PROMETHEUS_TOKEN` ou `ALERTMANAGER_TOKEN`.

## Régénérer les données de démonstration

```bash
python demo_data/generate.py
```
