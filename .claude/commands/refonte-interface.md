---
description: Refonte de l'interface web de l'agent de diagnostic, un lot à la fois (argument : numéro du lot, 0 à 5)
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

0. **Fondations** : jetons CSS (thèmes sombre et clair, bascule), polices et sprite d'icônes
   auto-hébergés, découpage en modules ES et couches CSS, empaquetage `web/static/**/*`, rendu par clé
   du graphe (fin du `innerHTML` à chaque image), outil de démonstration en direct sans modèle, script
   de captures Playwright. L'aspect peut encore être proche de l'actuel ; rien ne régresse.
1. **Coquille et accueil** : barre du haut, palette de commandes `Ctrl+K`, question en héros avec puces
   d'options et suggestions (alertes, exemples), investigations en cours avec mini-graphe vivant,
   historique, état des sources, alertes, chiffres du jour, statistiques repliées, état vide.
2. **Investigation en direct** : ligne de statut vivante, graphe vivant (naissance des agents,
   respiration, impulsions sur les liens, jauges, signaux), fil d'activité, chronologie en cascade
   synchronisée avec le graphe, arrêt d'un agent et de l'investigation avec confirmation de portée
   (arrêt immédiat pour qui a `kill`), transition de vue accueil → investigation.
3. **Réponse et décision** : révélation de la réponse, puces de preuves reliées au graphe et au tiroir,
   confiance, actions proposées (risque, retour arrière, copier, validation Superviseur), catégorie
   corrigeable en popover, avis, précision, plan, relance.
4. **Tiroir, administration, connexion** : tiroir à onglets avec navigation entre agents, écran
   d'administration à onglets et tableaux triables (dont l'éditeur de configuration et les comptes), écran
   de connexion.
5. **Finitions** : passe complète de la checklist qualité sur tous les écrans, accessibilité (axe-core),
   performances avec une grosse investigation, cohérence des textes, captures pour `docs/images/` et
   mise à jour de `poc/README.md`.

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
