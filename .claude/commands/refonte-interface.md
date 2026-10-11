---
description: Refonte de l'interface web de l'agent de diagnostic, un lot à la fois (argument : lot du plan, 0a à 7)
argument-hint: "[numéro du lot]"
---

Tu travailles sur la refonte de l'interface web de l'agent de diagnostic (`poc/src/diagagent/web/`).
Utilise le skill `interface-diagagent` : lis `SKILL.md` puis les références utiles au lot avant d'écrire
du code.

Objectif d'Erik : une interface hyper moderne et innovante, avec un effet « whoua » quand on l'utilise,
et une expérience irréprochable, simple et intuitive. L'effet vient du direct (agents qui travaillent
sous nos yeux, preuves reliées à la réponse), pas de la décoration.

Lot demandé : **$ARGUMENTS** (si rien n'est indiqué, propose le prochain lot non fait d'après
`docs/poc-suivi.md` et l'état du code, et attends ma confirmation).

## Lots

Le découpage fait foi dans [`docs/plan-interface.md`](../../docs/plan-interface.md) (décisions du
11 octobre 2026 : TypeScript, React et React Flow, bundle versionné, thème qui suit le système) :

- **0a** base TypeScript et React, connexion et accueil (nouvelle interface sur `/nouvelle`) ;
- **0b** investigation, tiroir, administration, puis bascule sur `/` ;
- **1** coquille, accueil et historique filtrable ;
- **2** investigation en direct et signaux calculés par l'orchestrateur ;
- **3** réponse au fil de l'eau et décision ;
- **4** tiroir, administration, connexion, comptes par lien d'activation ;
- **5** piloter les agents en cours (consigne, relance d'un sous-agent, budget) ;
- **6** question de suivi ;
- **7** finitions.

Lire la section du lot dans le plan avant de commencer. Tant que le lot 0a n'a pas mis à jour
`references/technique.md`, ses contraintes « sans build, sans framework » sont remplacées par les
décisions du plan ; « rien chargé d'Internet à l'exécution » reste vrai (dépendances empaquetées).

## Façon de travailler

1. Lis le code concerné et résume en quelques lignes ce qui existe, ce qui change pour l'utilisateur et
   les fichiers touchés. Signale tout conflit avec le skill avant de coder.
2. Implémente le lot en entier, tous les états compris (chargement, vide, erreur, partiel, droits).
3. Lance `diagagent --now 2026-10-07T06:00:00Z serve`, fais les captures (1440, 1024, 390 px ; sombre
   et clair ; mouvement réduit) et **regarde-les** ; corrige ce qui ne va pas avant de continuer.
4. Passe `references/checklist-qualite.md` et `cd poc && python -m pytest -q`.
5. Crée une branche `poc/interface-lot-<n>`, commite, et ouvre une PR **en brouillon** (la CI fusionne
   seule les PR non brouillon dont les tests passent) avec : avant / après en langage simple, captures,
   points de la checklist vérifiés, ce qui reste pour les lots suivants. Mets à jour
   `docs/poc-suivi.md`.

Ne change pas le comportement de l'API ni les droits par rôle sans me le demander. Si un choix de design
important n'est pas couvert par le skill, propose deux options avec ta recommandation au lieu de
trancher seul.
