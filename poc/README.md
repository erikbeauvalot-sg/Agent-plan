# POC de l'agent de diagnostic

Mise en œuvre progressive de l'[architecture](../docs/architecture-agent-diagnostic.md), sur des sources
de démonstration. Avancement : [suivi du POC](../docs/poc-suivi.md).

## Ce que contient le POC

| Brique | Où | Rôle |
| --- | --- | --- |
| Couche LLM agnostique | `src/diagagent/llm/` | Format pivot, adaptateurs `azure_openai`, `openai_compatible` (Ollama, vLLM) et `scripted` (tests) |
| Catalogue | `catalog/` | Une fiche YAML par source, glossaire, relations entre sources |
| Serveurs MCP | `src/diagagent/mcp_servers/` | `mcp-catalog`, `mcp-elk`, `mcp-cmdb`, `mcp-metrics`, `mcp-alerts`, `mcp-system` (SSH), en lecture seule |
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

`config/models.yaml` déclare des **profils** (un modèle par rôle d'agent) et le profil par défaut
(`default: ollama`). Le profil se choisit à chaque investigation, sans toucher au fichier :

```bash
diagagent --models openai ask "…"     # ou eval, check ; DIAGAGENT_MODELS=openai fait de même
```

Dans l'interface web, un sélecteur sous la question propose les profils ; une relance (catégorie
corrigée, précision) garde le profil de l'investigation d'origine. Le profil est noté dans le manifest
(`models_profile`) et dans les résultats d'éval.

**Modèle local (profil `ollama`, défaut)** : Ollama sur `localhost:11434` avec `gpt-oss:20b` (ou vLLM,
en changeant `base_url`).

**Azure OpenAI (profil `azure`)**

```bash
export AZURE_OPENAI_ENDPOINT=https://<ressource>.openai.azure.com
az login                    # authentification Entra ID (DefaultAzureCredential)
diagagent --models azure check   # un appel court pour vérifier l'accès au déploiement gpt-5.6-luna
```

Le nom du déploiement se règle dans le profil (`deployment`). Pour une clé d'API à la place
d'Entra ID : `auth: api_key` et la variable `AZURE_OPENAI_API_KEY`.

**OpenAI (profil `openai`, POC à la maison)** : avec `OPENAI_API_KEY` dans `poc/.env`. Le profil utilise
`gpt-4.1-mini` (agent principal) et `gpt-4.1-nano` (sous-agents, classifieur) : sans raisonnement, ils
consomment bien moins de tokens que `gpt-5.4-mini`/`nano`. Ne pas indiquer `reasoning` pour ces modèles.

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

Dans `config/models.yaml`, décommenter le profil `claude` (`provider: claude, model: claude-opus-5-5`),
puis lancer `diagagent --models claude check`.
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

Le modèle oublie parfois une entité écrite dans la demande. Avant de poser une question de précision,
l'orchestrateur relit la demande : un numéro `INC` ou `CHG`, ou le nom exact d'une alerte connue
(en cours dans Alertmanager ou règle d'alerte de Prometheus), complète l'entité manquante (événement
`entities_completed`). Une demande classée `autre` qui nomme une alerte connue passe en
`analyse-evenement`, avec une confiance faible.

En cours de route, l'agent principal peut appeler `requalify` si les faits contredisent la catégorie ;
le changement est tracé (`category_changed` dans `events.jsonl`). La catégorie, sa confiance et la
version des playbooks appliqués sont dans `manifest.json` (clé `category`) et dans `runs/index.jsonl`.

Avant d'accepter la réponse finale, l'orchestrateur la contrôle et relance l'agent principal, une fois
par motif (événement `final_answer_rechecked`) :
- **vagues non lancées** : une étape du playbook prévoit des sous-agents et aucun de ses rôles n'a été
  lancé (`gpt-oss:20b` fait souvent tout lui-même, ou ne lance que `generic`). L'agent lance les
  étapes manquantes ou dit dans les Limites pourquoi il les saute. Le rôle `generic` et les rôles
  indisponibles ne comptent pas ; après `requalify`, c'est le nouveau playbook qui compte ;
- **actions non enregistrées** : la réponse décrit des actions sans avoir appelé `propose_action`.

```bash
diagagent playbooks                               # valide et liste les playbooks
diagagent ask --category performance "…"          # impose la catégorie, sans classifieur
```

Le classifieur utilise le rôle `classifier` du profil de modèles ; absent, il prend le modèle de
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
sous-agents se règle par la clé `subagent` du profil de modèles, ou par rôle.

## Interface web

```bash
diagagent user add erik --role administrateur --name Erik     # demande le mot de passe (12 caractères min.)
diagagent user add sophie --role superviseur --name Sophie    # valide les propositions d'évolution
diagagent serve                                               # http://127.0.0.1:8080
diagagent --now 2026-10-07T06:00:00Z serve                    # scénario de démonstration (voir ci-dessous)
```

Les recherches sans période portent sur les 24 h qui précèdent l'**heure de référence**. Lancé sans
`--now`, le serveur utilise l'heure réelle : les données de démonstration (nuit du 6 octobre 2026) sont
alors hors période, et l'agent doit élargir lui-même ses recherches. Pour jouer le scénario comme
`diagagent eval`, lancer le serveur avec `--now 2026-10-07T06:00:00Z` ; l'heure figée s'affiche dans la
barre du haut, et l'heure de référence de chaque investigation sous sa question.

- **Accueil** : la question avec le choix du **modèle** (profils de `config/models.yaml`) et des
  **données** (démo, maison ou les deux). Une option indisponible reste visible, grisée, avec la raison ;
  le navigateur retient le dernier choix, sinon le défaut du serveur (`DIAGAGENT_MODELS`,
  `DIAGAGENT_SOURCES` dans `.env`). Puis : investigations en cours et dernières investigations
  (recherche, filtre par catégorie, modèle, durée, tokens), **état** des modèles et des sources
  (Ollama interrogé, clés présentes, cibles Prometheus up, alertes ; aucun appel payant), chiffres du
  jour, dernier résultat d'éval par modèle, alertes Alertmanager en cours (« Investiguer » préremplit la
  question), et **statistiques** sur 1, 7 ou 30 jours : réussite par catégorie, par agent (principal et
  sous-agents par rôle) et par modèle, évaluations exclues sauf demande. Le détail d'une investigation
  s'ouvre au clic (`#<run_id>`, partageable) ; « ← Accueil » y revient. Le choix **catégorie**
  (automatique par défaut) impose un playbook sans passer par le classifieur.
- **Relancer…** (sur une investigation) : prépare une nouvelle demande sur l'accueil, préremplie avec la
  question, le modèle, les données et la catégorie imposée ou corrigée de l'investigation d'origine, **sans
  la lancer** : on change la question ou les options, puis « Lancer l'investigation ». La nouvelle
  investigation note `rerun_of` dans son manifest et affiche un lien vers l'originale ; les relances
  « Relancer avec cette catégorie » et « Préciser et relancer » le notent aussi.

Pour l'ouvrir depuis une autre machine du réseau : `diagagent serve --host 0.0.0.0`, et définir
`DIAGAGENT_SESSION_SECRET` pour que les sessions survivent à un redémarrage.

- **Conversation** : on pose la question sur l'accueil ; la réponse s'affiche à la fin, chaque preuve
  `[…/calls/NNNN.json]` est cliquable.
- **Graphe d'investigation** : agent principal et sous-agents, colorés par état, avec la jauge de
  budget et les signaux (bloqué depuis 120 s, boucle, 3 erreurs d'outil, budget à 80 %, erreur modèle).
- **Chronologie** : une ligne par agent, appels au modèle et aux outils.
- **Modèles et tokens** : sous la question, le fournisseur et le modèle de chaque rôle (principal,
  classifieur, sous-agents) et les tokens consommés, comptés en direct ; sur chaque nœud et dans le
  détail d'un agent, son modèle et ses tokens. Ils sont aussi dans `manifest.json` (`models`,
  `usage`, `usage_by_agent`).
- **Détail d'un agent** (clic sur un nœud) : prompt reçu, rapport, chaque appel d'outil, réponses du modèle,
  bouton d'arrêt.
- **Arrêt** : un sous-agent arrêté rend un rapport partiel et l'agent principal continue ;
  « Arrêter l'investigation » demande à l'agent principal une synthèse partielle.

Les cinq rôles du document d'architecture :

| Rôle | Ce qu'il peut faire |
| --- | --- |
| `lecteur` | Lire les investigations partagées, avec graphe et chronologie, sans prompts ni appels d'outils |
| `operateur` | Poser des questions ; voir en détail, arrêter, partager, corriger et noter les siennes |
| `superviseur` | Comme l'opérateur, sur toutes les investigations ; arrêt immédiat ; valider ou rejeter les actions proposées et les évolutions de playbooks ; indicateurs et coûts |
| `administrateur` | Tout voir et tout arrêter ; gérer les utilisateurs ; indicateurs, coûts et journal d'accès ; ne valide pas |
| `auditeur` | Tout lire, prompts et journal d'accès compris, sans rien piloter |

Une investigation partagée (bouton **Partager**) devient lisible par tout utilisateur connecté, mais
seuls son auteur et les rôles qui voient tout en ont le détail. L'écran **Administration** regroupe,
selon le rôle : les actions à valider, les indicateurs par catégorie, les propositions d'évolution, les
coûts (tokens par jour, utilisateur et modèle ; le POC n'a pas de notion d'équipe, un Superviseur voit
tout) et le journal d'accès. Comptes dans `auth/users.yaml` (mots de passe en Argon2id, verrouillage
15 min après 5 échecs) ; journal d'accès dans `audit/`.

![Investigation en cours](../docs/images/poc-interface-en-cours.png)

## Actions proposées

L'agent principal enregistre chaque action qu'il recommande avec `propose_action` : type (diagnostic
complémentaire, remédiation, contournement, ouverture de ticket), cible, justification et preuves,
risque, procédure, retour arrière, passage ou non par la gestion des changements. Elles sont écrites
dans `actions.json` et affichées dans l'interface ; aucun outil ne permet de les exécuter.

Un Superviseur valide ou rejette chaque action, depuis l'investigation ou depuis la liste des actions
en attente de l'écran Administration. La décision (qui, quand, commentaire) est écrite dans
`actions.json` et dans le journal d'accès. Une action validée reste non exécutée : l'exécution avec
validation humaine fera l'objet d'un document séparé.

## Évaluation et rejeu

```bash
diagagent eval                                   # joue eval/cases.yaml avec le modèle configuré
diagagent eval --only diag-paiement              # un seul cas
diagagent eval --repeat 3                        # chaque cas 3 fois : taux de réussite par cas
diagagent replay 20261008T061159Z-5f31           # rejoue une investigation sans appeler le modèle
```

`eval` pose chaque question du jeu de cas et vérifie la réponse : catégorie rendue par le classifieur,
mentions attendues ou interdites, nombre de sous-agents, actions proposées, erreurs d'outil. Le résumé
donne aussi la justesse de catégorisation. Le rapport va dans `eval/results/`.
`eval/cases.yaml` porte sur le scénario de démonstration ; `eval/cases-maison.example.yaml` sert de
modèle pour des questions sur tes propres sources. `diagagent --models <profil> eval` compare les
modèles sur les mêmes questions ; le rapport donne la durée totale et le profil utilisé. Avec un modèle local, les résultats varient
d'un passage à l'autre (le même code a donné 7 puis 4 cas réussis sur 9 avec `gpt-oss:20b`) : comparer
avec `--repeat` plutôt que sur un seul passage.

`replay` refait passer les décisions enregistrées du modèle dans les outils actuels et signale chaque
appel d'outil dont le résultat a changé : utile après une modification d'un serveur MCP ou du catalogue. La
catégorie d'origine est imposée : le classifieur n'est pas rejoué.

## Brancher Prometheus et Alertmanager

Deux variables suffisent, de préférence dans `poc/.env` :

```bash
PROMETHEUS_URL=http://192.168.1.15:9090
ALERTMANAGER_URL=http://192.168.1.15:9093
```

Les sources forment deux jeux : `demo` (données factices de `demo_data/`) et `maison` (Prometheus,
Alertmanager, actives seulement si leur variable est définie). Par défaut les deux sont actifs ; le
choix se fait par investigation, sans toucher à `.env` :

```bash
diagagent tools                                  # doit lister list_hosts, promql, list_alerts, alert_history…
diagagent ask "Pourquoi le NAS était-il lent cette nuit ?"           # démo + maison
diagagent --sources maison ask "Quelles machines sont suivies ?"     # seulement les sources réelles
diagagent --sources demo ask "…"                                     # seulement la démo
```

Dans l'interface web, le sélecteur « Données » (affiché dès qu'une source réelle est configurée)
propose les trois choix ; le manifest note les jeux utilisés (`sources`). Les tests `pytest` et le
banc `eval/cases.yaml` (`sources: demo`) n'utilisent que la démo, même si `PROMETHEUS_URL` est
définie : ils restent reproductibles. Les données de démo sont datées autour du 7 octobre 2026
(`--now`) : en mode mixte à l'heure réelle, elles sortent de la fenêtre par défaut de 24 h.

Sans `--now`, l'heure de référence est l'heure réelle. Ce que l'agent obtient :

| Outil | Source | Contenu |
| --- | --- | --- |
| `list_hosts` | Prometheus (`up`) | Machines suivies, job, cible joignable ou non |
| `list_metrics`, `query_metric` | Prometheus | Métriques normalisées (CPU, charge, mémoire, disque, réseau) résumées avec ruptures |
| `promql` | Prometheus | Requête libre, résumée par série |
| `list_alerts`, `list_silences` | Alertmanager | Alertes actives, silences en cours |
| `alert_history` | Prometheus (`ALERTS`) | Alertes passées et leurs intervalles de déclenchement |
| `container_metrics` | Prometheus (cAdvisor) | Mémoire, swap, CPU ou OOM par conteneur Docker, classés par pic, avec l'heure du pic |
| `container_changes` | Prometheus (cAdvisor) | Conteneurs démarrés, redémarrés ou mis à jour sur la période, version avant et après |
| `alert_rule` | Prometheus (règles) | Expression, seuil, durée et hosts en alerte d'une règle : l'alerte mesure-t-elle un impact ? |

Les métriques normalisées sont des modèles PromQL dans `catalog/sources/metrics-prometheus.yaml`,
écrits pour node_exporter ; on les adapte ou on en ajoute selon les exporters installés. Le nom de
host est le label `instance` sans le port (réglable par `host_label`). Un jeton facultatif se passe
par `PROMETHEUS_TOKEN` ou `ALERTMANAGER_TOKEN`.

## Interroger les machines en direct (SSH)

Prometheus dit quand la mémoire a manqué, pas quel processus l'a prise. `mcp-system` se connecte aux
machines en SSH, en lecture seule, et exécute une seule chose : le script `remote/diagagent-probe`,
avec une sonde fixe (`memory`, `processes`, `containers`, `oom`). Le modèle ne choisit que le host,
parmi ceux de `SSH_HOSTS` ; il n'écrit jamais de commande.

```bash
SSH_HOSTS=xdocker,pdocker            # mêmes noms que dans Prometheus ; xdocker=192.168.1.20 si besoin
SSH_USER=diagagent                   # facultatif, sinon ~/.ssh/config
SSH_KEY=~/.ssh/diagagent_ed25519     # facultatif
```

| Outil | Contenu |
| --- | --- |
| `list_ssh_hosts` | Machines joignables |
| `host_memory` | RAM disponible, swap, pression mémoire (PSI), swappiness |
| `top_processes` | Processus par RAM ou par swap, avec leur conteneur Docker |
| `container_memory` | Mémoire, swap, pic depuis le démarrage (`memory.peak`) et limite de chaque conteneur |
| `oom_events` | Messages OOM du noyau des 7 derniers jours |

Les réponses décrivent l'état au moment de l'appel (`observed_at`), pas à l'heure de référence :
le sous-agent `system` les croise avec les métriques pour un pic passé. Le rôle n'est proposé que
si `SSH_HOSTS` est définie ; les playbooks `analyse-evenement` et `performance` l'appellent.

Le script part sur l'entrée standard (`sh -s -- <sonde>`) : rien à installer, mais le compte SSH peut
alors tout faire. Pour que la clé ne permette que ces lectures, sur chaque machine :

```bash
useradd -r -m -s /bin/sh diagagent
install -m 755 diagagent-probe /usr/local/bin/diagagent-probe
# ~diagagent/.ssh/authorized_keys :
command="/usr/local/bin/diagagent-probe",restrict ssh-ed25519 AAAA... diagagent
```

La machine exécute alors son propre script, avec le dernier mot de la commande reçue comme nom de
sonde ; toute autre demande est refusée. Le compte n'a pas besoin de root : `/proc` donne le swap de
chaque processus. Pour les noms des conteneurs, l'ajouter au groupe `docker` (équivalent à root, mais la
commande forcée borne ce que la clé lance ; sans ce groupe, les identifiants
seuls) ; pour `oom_events`, au groupe `systemd-journal` ou `adm`. La clé d'hôte doit déjà être dans
`known_hosts` (`StrictHostKeyChecking=yes`) : se connecter une fois à la main.

## Recherche web et pistes de remédiation

Une cause trouvée ne suffit pas : « augmenter la RAM » n'aide personne. Une fois la cause établie,
l'agent principal examine quatre pistes et dit pour chacune ce qu'il retient ou écarte
(rubrique « Pistes de remédiation » de la réponse, étape `remediation` des playbooks
`analyse-evenement` et `performance`) :

1. **Impact réel** : le sous-agent `events` lit la règle de l'alerte (`alert_rule`) et la compare aux
   signes d'impact (pression mémoire, swap relu, erreurs, latence). Une alerte permanente sans impact
   est un faux positif : l'action proposée est de type `réglage de supervision`, avec la nouvelle règle.
2. **Problème connu** : le sous-agent `web` cherche le logiciel, sa version (`container_memory` lit le
   label `org.opencontainers.image.version` de l'image) et le symptôme sur les forums et issues.
3. **Réglage de l'application** : paramètre exact, valeur et endroit, d'après les sources.
4. **Réglage du système** : swappiness, taille du swap, limite mémoire du conteneur, RAM.

Une action donne le paramètre exact et sa valeur, et cite l'URL d'une source web. Une limite mémoire
n'est jamais sous le pic déjà mesuré, et une alerte existante se règle au lieu d'être recréée.

```bash
WEB_SEARCH=duckduckgo                 # sans clé ; ou l'URL d'une instance SearXNG (API JSON)
WEB_SEARCH_DENY=beauvalot,maison      # facultatif : mots jamais envoyés au moteur
```

| Outil | Contenu |
| --- | --- |
| `web_search` | Titre, URL et extrait des résultats (10 au plus, sans annonces) |
| `web_page` | Texte lisible d'une page publique (8000 caractères, sans menus ni scripts) |

Garde-fous : une requête qui contient une adresse IP, un nom de `SSH_HOSTS` ou un mot de
`WEB_SEARCH_DENY` est refusée avant l'envoi. `web_page` ne lit que des adresses publiques, redirections
comprises : pas d'accès au réseau local ni à `localhost`. Le contenu des pages est une donnée, jamais
une instruction. Réservé au POC à la maison : en production, les requêtes ne sortent pas sur internet.

## Régénérer les données de démonstration

```bash
python demo_data/generate.py
```
