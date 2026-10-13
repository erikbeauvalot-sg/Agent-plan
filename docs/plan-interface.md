# Interface web : plan d'amélioration (octobre 2026)

Ce plan confronte l'interface du POC (`poc/src/diagagent/web/`) à la section « Interface web » du
[document d'architecture](architecture-agent-diagnostic.md) et au skill
[`interface-diagagent`](../.claude/skills/interface-diagagent/SKILL.md). Il reprend les six lots de la
commande [`/refonte-interface`](../.claude/commands/refonte-interface.md), qui portent sur l'aspect et
l'expérience, et y ajoute ce que le document d'architecture demande et qui n'existe pas encore : piloter
les agents en cours, suivre la réponse au fil de l'eau, poser une question de suivi, signaux calculés
par l'orchestrateur, historique filtrable.

Chaque lot est une PR vers `main`, en brouillon pour être regardée avant la fusion (le lot 0 en compte
deux). Un lot se vérifie
avec les tests unitaires et des captures d'écran sur la démonstration ; les évaluations de scénario
(`diagagent eval`) ne sont pas lancées.

## Ce qui existe et ce qui manque

| Exigence du document d'architecture | Aujourd'hui | Lot |
| --- | --- | --- |
| Conversation : poser une question, catégorie affichée et corrigeable | Fait ; une question = une investigation | 1, 3 |
| Conversation : **fil de questions et réponses** (question de suivi sur la même investigation) | Absent : seulement « Préciser et relancer » et « Relancer… », qui repartent de zéro | 6 |
| Conversation : **réponse affichée au fil de l'eau** | Absent : la réponse apparaît en bloc à la fin | 3 |
| Faits cliquables vers leur preuve | Fait (références `[lead/calls/…]` qui ouvrent le tiroir) | 3 |
| Graphe d'investigation en direct, coloré par état | Fait, mais redessiné en entier à chaque événement (aucune animation possible) | 0b, 2 |
| Chronologie par agent (modèle, outils, attentes, erreurs) | Fait, sans attentes ni lien avec le graphe | 2 |
| Détail d'un agent : prompt, échanges, appels d'outils | Fait ; **jauges de budget** absentes du tiroir | 4 |
| Actions proposées, validation par un rôle habilité | Fait | 3 |
| Historique : recherche par **date, utilisateur, catégorie, host, statut** | Recherche texte et filtre catégorie seulement | 1 |
| Administration : catalogue, playbooks, propositions et rejeu, indicateurs, modèles, budgets, comptes, coûts | Fait, en une longue page | 4 |
| Administration : **rejouer le jeu d'évaluation** après une modification de playbook ou de prompt | Absent | 7 (facultatif) |
| Signaux bloqué, boucle, erreurs d'outil, budget | Calculés dans le navigateur | 2 |
| Signaux **modèle** (refus, quota, bascule) et **source lente** (> 10 s) | Absents | 2 |
| Signaux **calculés par l'orchestrateur** (`signal_raised` dans `events.jsonl`) | Absent : seul le navigateur les calcule, rien n'est tracé | 2 |
| Arrêter un sous-agent, arrêter l'investigation | Fait | 2 |
| **Arrêt immédiat** (Superviseur) | Dans l'API, absent de l'écran | 2 |
| **Relancer un sous-agent** (même prompt ou prompt corrigé) | Absent (API et écran) | 5 |
| **Envoyer une consigne** à l'agent principal en cours de route | Absent (API et écran) | 5 |
| **Ajuster un budget** en cours (Superviseur) | Absent (API et écran) | 5 |
| Flux SSE avec reprise au dernier événement | Fait (`Last-Event-ID`) | — |
| Création de compte par **lien d'activation** de 24 h, liste de mots de passe compromis | L'administrateur saisit le mot de passe | 4 |
| Front TypeScript (React), graphe React Flow, chronologie Gantt | JavaScript natif sans build | 0 |

## Décisions (11 octobre 2026)

1. **Front en TypeScript et React dès le POC**, graphe avec React Flow (`@xyflow/react`, licence MIT),
   comme le prévoit le document d'architecture. Les dépendances npm sont empaquetées dans le bundle :
   rien n'est chargé d'Internet à l'exécution, polices comprises.
2. **Bundle versionné** : le code compilé (`web/static/dist/`) est commité ; Node n'est nécessaire que
   pour modifier l'interface, et le POC s'installe toujours avec `pip install -e`. La CI vérifie que le
   bundle correspond aux sources (`tsc --noEmit`, build, `git diff --exit-code`).
3. **Thème** : suit le réglage du système (sombre ou clair), avec une bascule mémorisée.
4. **Question de suivi** : nouvelle investigation liée à la précédente, dont l'agent principal reçoit la
   question d'origine, la synthèse et les rapports en contexte ; les traces restent immuables.

## Lots

Les lots 0 à 4 et 7 reprennent la refonte prévue, sur la nouvelle base React ; les lots 5 et 6 ajoutent
les fonctions du document d'architecture qui demandent aussi du travail côté serveur. Ordre conseillé :
0a, 0b, 1, 2, 3, 5, 4, 6, 7.

### Lot 0a : base TypeScript et React, connexion et accueil

Pour l'utilisateur, l'aspect reste proche de l'actuel ; tout ce qui suit en dépend.

- Projet front dans `poc/web-ui/` : Vite, React, TypeScript strict, ESLint ; sortie dans
  `poc/src/diagagent/web/static/dist/` (versionnée) ; empaquetage `web/static/**/*` dans
  `pyproject.toml` ; serveur de développement Vite qui relaie `/api` vers FastAPI.
- Couches communes : client d'API typé (types générés ou écrits depuis les modèles FastAPI), gestion de
  la session et du 401, flux SSE avec reprise (`Last-Event-ID`), **réduction des événements en un état
  unique** (`reduce(state, event)`) testée avec Vitest, routage par fragment (`#`, `#<run_id>`,
  `#admin`), jetons CSS en `oklch()` (thèmes sombre et clair, bascule), polices et icônes
  auto-hébergées.
- Écrans portés à fonctions identiques : connexion (le formulaire `POST /login` sans JavaScript reste
  servi), barre du haut, accueil complet (question et options, relance, en cours, historique, état,
  alertes, chiffres du jour, évaluations, statistiques).
- Réalisé avec le lot 0b dans la PR #37, sans adresse de transition (demande du 11 octobre).
- CI : job Node (installation, `tsc --noEmit`, tests Vitest, build, bundle à jour) en plus des tests
  Python.
- Mise à jour du skill `interface-diagagent` (`references/technique.md` : outillage, structure,
  contraintes) et de la section « Interface web » de `poc/README.md` (comment développer l'interface).

### Lot 0b : investigation, tiroir, administration ; bascule

- Écrans portés à fonctions identiques : investigation (graphe React Flow, chronologie, catégorie,
  actions, réponse, avis, précision, plan, partage, relance, arrêt), tiroir d'agent, administration
  complète (dont l'éditeur de configuration et les comptes).
- Graphe et chronologie rendus depuis l'état réduit : un événement met à jour un nœud, pas tout le
  graphe, ce qui permet les animations du lot 2.
- Outil de démonstration en direct sans modèle (rejeu d'une trace avec son rythme d'origine) et script
  de captures Playwright (1440, 1024, 390 px ; sombre et clair ; mouvement réduit).
- Acceptation : chaque fonction de l'inventaire (`references/ecrans.md`) vérifiée sur la nouvelle
  interface ; la nouvelle interface passe sur `/`, l'ancienne est supprimée.

### Lot 1 : coquille, accueil et historique

- Barre du haut fine (marque, heure de référence figée, palette, thème, menu utilisateur) ; palette de
  commandes `Ctrl+K` (lancer, ouvrir une investigation, aller à l'administration, changer de thème).
- Question en héros, options en puces (modèle, données, catégorie), suggestions quand le champ est vide
  (alertes en cours, exemples, dernières questions) ; `Entrée` lance.
- Investigations en cours en cartes avec mini-graphe vivant et ligne de statut.
- **Historique filtrable** (document d'architecture) : période, utilisateur, catégorie, host, statut,
  recherche texte ; filtres en puces, combinables, gardés dans l'adresse. Côté API : paramètres de
  filtre sur `GET /api/runs` (aujourd'hui tout est filtré dans le navigateur sur 100 lignes).
- Colonne d'état : sources, alertes, chiffres du jour ; statistiques repliées.
- Accueil du Lecteur : investigations partagées seulement ; état vide du premier lancement.
- Réalisé dans la PR #39 : `GET /api/runs` filtre côté serveur (`since`, `until`, `user`, `category`,
  `status`, `host`, `q`, `offset`) et porte l'état des agents des investigations en cours (`live`) ;
  `GET /api/runs/facets` donne les valeurs des filtres. Reporté au lot 2 : le titre de l'investigation
  dans la barre du haut et la transition de vue de la question vers ce titre.

### Lot 2 : investigation en direct et signaux

- Ligne de statut vivante (« T03 interroge Prometheus : latence p95 de srv-pay-01 »), graphe vivant
  (naissance des agents, impulsion sur le lien à chaque appel, jauges), fil d'activité, chronologie en
  cascade synchronisée avec le graphe (survol croisé), attentes visibles dans la chronologie.
- **Signaux calculés par l'orchestrateur** : un moniteur côté serveur écrit `signal_raised` (et
  `signal_cleared`) dans `events.jsonl` selon les règles du document (bloqué 120 s, boucle 3 fois,
  3 erreurs d'outil, budget 80 %), avec des seuils réglables dans `config/poc.yaml`. Le navigateur les
  affiche au lieu de les recalculer ; ils restent dans la trace et dans le rejeu.
- **Nouveaux signaux** : *modèle* (refus, quota, bascule de secours, levés par la couche LLM) et
  *source lente* (appel d'outil au-delà de 10 s, badge sur l'appel avec la source en cause).
- Arrêt d'un agent et de l'investigation avec portée explicite ; **arrêt immédiat** pour qui a la
  permission `kill` (API existante), avec confirmation.
- Transition de vue accueil → investigation (View Transitions en amélioration progressive).
- Réalisé dans la PR #41 : moniteur `src/diagagent/signals.py` (seuils `signals` de `config/poc.yaml`),
  `manifest.signals = "orchestrator"` pour que le navigateur ne recalcule plus ; outil `tools/demo_live.py`
  (rejeu en direct sans modèle) ; titre de l'investigation dans la barre du haut (reporté du lot 1). Le
  signal de budget porte sur les appels d'outils : le POC n'a pas de budget de tokens par agent.

### Lot 3 : réponse au fil de l'eau et décision

- **Réponse au fil de l'eau** (document d'architecture) : la synthèse de l'agent principal s'affiche
  pendant qu'il l'écrit. Côté serveur : diffusion des morceaux de texte du dernier appel au modèle
  (`answer_delta`), pour les adaptateurs qui savent diffuser (OpenAI compatible, Azure, Claude) ; sinon
  affichage en bloc comme aujourd'hui. Les contrôles de la réponse finale (vagues, changements, faits)
  peuvent relancer l'agent : la réponse affichée est alors marquée « en cours de révision ».
- Révélation de la réponse (synthèse, cause probable, chronologie, limites) avec ses preuves en puces
  reliées au graphe et au tiroir ; niveau de confiance lisible.
- Actions proposées : risque, retour arrière, preuves, copie de la procédure, validation Superviseur ;
  « jamais exécutées par l'agent » toujours visible.
- Catégorie corrigeable en popover, avis, précision, plan, relance.

### Lot 4 : tiroir, administration, connexion, comptes

- Tiroir d'agent à onglets (résumé, appels d'outils, échanges, prompt), navigation entre agents,
  **jauges de budget** (appels d'outils et tokens sur leur plafond).
- Administration à onglets (À valider, Propositions, Indicateurs, Configuration, Comptes, Coûts,
  Journal), tableaux triables ; éditeur de configuration avec numéros de ligne et écart coloré.
- **Comptes par lien d'activation** (document d'architecture) : l'administrateur crée le compte, la
  passerelle produit un lien à usage unique valable 24 h où l'utilisateur choisit son mot de passe ;
  refus des mots de passe d'une liste de mots de passe compromis (fichier local, pas d'appel externe).
- Écran de connexion refait (affichage du mot de passe, message de verrouillage avec la durée).

### Lot 5 : piloter les agents en cours

Les trois commandes du document d'architecture qui manquent, côté serveur et à l'écran, chacune tracée
dans `events.jsonl` et dans le journal d'accès.

- **Envoyer une consigne** (Opérateur, sur ses investigations) : un champ sous la ligne de statut ;
  `POST /api/runs/{id}/instructions` ; l'orchestrateur ajoute le message au contexte de l'agent principal
  avant son prochain appel au modèle (comme les rappels `progress_check`) ; événement
  `instruction_received` dans le fil d'activité.
- **Relancer un sous-agent** (Opérateur) : depuis le tiroir d'un sous-agent terminé ou arrêté, avec son
  prompt d'origine ou un prompt modifié ; `POST /api/runs/{id}/agents/{agent}/restart` ; nouveau
  sous-agent rattaché au même agent principal, dont le rapport lui est remis.
- **Ajuster un budget** (Superviseur) : jauge cliquable dans le tiroir ;
  `POST /api/runs/{id}/agents/{agent}/budget` ; nouveau plafond pris en compte au prochain appel.
- Tests : unitaires de l'orchestrateur (consigne reçue au bon moment, budget relevé, relance rattachée)
  et de la passerelle (droits par rôle, journal).
- Réalisé dans la PR #43 : boîte de messages de l'agent principal (`inbox`, lue avant chaque appel au
  modèle), budget propre à chaque sous-agent et boucle de tours relue à chaque tour, permission
  `adjust_budget` ; consigne sous la ligne de statut, jauge et relance dans le tiroir. Corrigé au passage :
  un clic sur un nœud du graphe n'ouvrait plus le tiroir (glisser du fond qui capturait le pointeur, et
  recadrage à chaque survol).

### Lot 6 : question de suivi

- Sous la réponse, un champ « Poser une question de suivi » (Opérateur) : nouvelle investigation liée
  (`follow_up_of`), dont l'agent principal reçoit la question d'origine, la synthèse et les rapports des
  sous-agents ; la catégorie est reclassée sur la nouvelle question.
- À l'écran, les investigations liées forment un **fil de conversation** : questions et réponses les
  unes sous les autres, chacune avec son graphe repliable.
- Côté serveur : `follow_up_of` dans `POST /api/runs` et dans le manifest (comme `rerun_of`), contexte
  injecté dans le prompt de l'agent principal, plafonné en taille.

### Lot 7 : finitions

- Checklist qualité complète sur tous les écrans, accessibilité (axe-core), performances avec une grosse
  investigation (plus de 500 événements), cohérence des textes, captures pour `docs/images/`, section
  « Interface web » de `poc/README.md`.
- Facultatif : bouton **Rejouer le jeu d'évaluation** après une modification de playbook ou de prompt
  dans l'éditeur de configuration (document d'architecture), avec le résultat à côté du précédent.
  Lancé seulement à la demande, en tâche de fond.

## Mise à jour du document d'architecture

La cible technique (TypeScript, React, React Flow) ne change pas. À compléter au fil des lots : bundle
versionné et vérifié en CI (lot 0a), modèle d'événement (`signal_cleared` au lot 2, `answer_delta` au
lot 3, `instruction_received` au lot 5), routes des commandes sur les agents (lot 5) et question de
suivi (`follow_up_of`, lot 6).
