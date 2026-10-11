---
name: interface-diagagent
description: Conception et développement de l'interface web de l'agent de diagnostic (poc/src/diagagent/web/). À utiliser pour toute modification de l'écran, du style, des interactions ou de l'expérience utilisateur de l'interface, y compris la refonte visuelle.
---

# Interface web de l'agent de diagnostic

Ce skill guide toute évolution de l'interface web du POC (`poc/src/diagagent/web/`). L'objectif d'Erik :
une interface **très moderne et innovante**, avec un **effet « whoua »** à l'usage, et une expérience
**irréprochable, simple et intuitive**. Les deux exigences ne s'opposent pas : l'effet « whoua » vient
d'une interface qui montre en direct, avec précision et élégance, ce que font les agents, pas de la
décoration.

Lire avant de coder, selon la tâche :

| Fichier | Quand le lire |
| --- | --- |
| [references/direction-visuelle.md](references/direction-visuelle.md) | Toute tâche qui touche au style : jetons de couleur, typographie, espacements, mouvement, moments « whoua » |
| [references/ecrans.md](references/ecrans.md) | Toute tâche sur un écran : connexion, accueil, investigation, détail d'agent, administration ; visibilité par rôle |
| [references/ux-agents.md](references/ux-agents.md) | Tout ce qui montre le travail des agents : graphe, chronologie, statut en direct, arrêt, réponse, preuves, actions |
| [references/technique.md](references/technique.md) | Toute modification de code : contraintes (sans build, sans CDN), structure, flux SSE, sécurité, performances, tests |
| [references/checklist-qualite.md](references/checklist-qualite.md) | Avant de déclarer une tâche finie : accessibilité, états, responsive, performances, captures |

## Le produit en une phrase

Un opérateur de production pose une question (« pourquoi le service Paiement est lent depuis hier
soir ? ») ; un agent principal classe la demande, lance des sous-agents en parallèle sur les sources
(logs, métriques, CMDB, alertes, changements), puis rend une synthèse avec preuves et propose des
actions **qu'il n'exécute jamais**. L'interface sert à poser la question, **voir les agents travailler
en direct**, les arrêter, corriger la catégorie, lire la réponse, vérifier les preuves et juger le
diagnostic.

Les utilisateurs sont des ingénieurs d'exploitation, souvent sous pression (incident en cours, astreinte
de nuit). Chaque seconde de compréhension gagnée compte plus qu'une animation.

## Principes non négociables

1. **La réponse d'abord, le détail à la demande.** Chaque écran répond d'abord à « où en est-on ? » et
   « que dois-je faire ? ». Le détail (prompts, appels d'outils, tokens) reste à un clic, jamais en
   premier plan (divulgation progressive).
2. **Le direct est le spectacle.** L'effet « whoua » se concentre sur trois moments signature
   (voir `direction-visuelle.md`) : le graphe d'agents vivant, la barre de question, la révélation de la
   réponse reliée aux preuves. Pas d'animation gratuite ailleurs.
3. **Le mouvement porte du sens.** Une animation montre un changement d'état réel (agent lancé, outil
   appelé, erreur, fin). Elle dure moins de 300 ms pour une interaction, n'anime que `transform` et
   `opacity`, et disparaît avec `prefers-reduced-motion: reduce`.
4. **Le contrôle reste humain.** Arrêter un agent ou l'investigation est toujours visible, à portée et
   sans ambiguïté sur sa portée (cet agent, ou toute l'investigation). Les actions proposées sont
   clairement marquées « jamais exécutées par l'agent ».
5. **La couleur n'est jamais seule.** Chaque état (en cours, terminé, partiel, arrêté, échec, à
   préciser) a une couleur **et** une icône ou une forme **et** un libellé.
6. **Rapide par construction.** Retour visuel en moins de 100 ms sur toute action ; tout ce qui dépasse
   400 ms affiche un squelette ou une progression ; aucune saute de mise en page quand les événements
   arrivent.
7. **Accessible.** WCAG 2.2 AA : contraste, focus visible et jamais masqué par la barre du haut, cibles
   de 24 × 24 px minimum, tout au clavier, régions `aria-live` pour le statut en direct.
8. **Sobre techniquement.** Pas de build, pas de framework, pas de CDN : HTML, CSS et JavaScript natifs
   servis par FastAPI. Les données de production restent dans l'entreprise, polices comprises.
9. **Rien ne régresse.** Toutes les fonctions actuelles restent disponibles (liste dans `ecrans.md`) et
   les droits par rôle sont respectés à l'écran comme dans l'API.
10. **Interface en français**, tutoiement (comme l'existant), dates `fr-FR` sur 24 h, heure de référence
    et fuseau toujours explicites.

## Méthode de travail

Pour toute tâche d'interface :

1. **Comprendre l'existant.** Lire les fichiers concernés de `poc/src/diagagent/web/` (`static/index.html`,
   `static/app.css`, `static/app.js`, `app.py` pour l'API) et les sections utiles des références. Repérer
   les fonctions et événements déjà gérés avant de réécrire quoi que ce soit.
2. **Annoncer le plan en quelques lignes** : écran visé, ce qui change pour l'utilisateur, fichiers
   touchés, moments signature concernés. Pour une refonte, découper en lots livrables séparément (une PR
   par lot, comme le reste du POC).
3. **Construire d'abord les fondations** (jetons, typographie, composants de base) avant les écrans, et
   réutiliser les composants plutôt que de dupliquer du CSS.
4. **Coder pour tous les états** : chargement, vide, erreur, partiel, en direct, terminé, arrêté, droits
   insuffisants. Un écran qui ne prévoit que le cas nominal n'est pas fini.
5. **Vérifier en vrai** : lancer `diagagent --now 2026-10-07T06:00:00Z serve`, ouvrir l'écran dans un
   navigateur, et faire des captures (largeurs 1440, 1024 et 390 px ; thème clair et sombre) ; voir
   `technique.md` pour lancer une investigation de démonstration et automatiser les captures.
6. **Passer la checklist** (`checklist-qualite.md`) et les tests (`cd poc && python -m pytest -q`).
7. **Mettre à jour la documentation** : section « Interface web » de `poc/README.md` si le comportement
   change, captures dans `docs/images/` si l'aspect change nettement.

## Ce qu'il faut éviter

- L'esthétique générique « générée par IA » : dégradé violet sur fond blanc, cartes identiques en grille,
  coins très arrondis partout, ombres floues, emojis comme icônes, Inter partout sans hiérarchie.
- Le glassmorphisme ou le flou en arrière-plan sur des zones de lecture : il nuit au contraste et coûte
  cher au rendu. Réservé, si besoin, à une surface flottante (palette de commandes).
- Les tableaux de bord « mur d'indicateurs » : chaque chiffre affiché doit aider à décider ou agir.
- Les spinners sans contexte : dire ce qui se passe (« T03 interroge Prometheus : latence p95 de
  srv-pay-01 »).
- Les modales bloquantes pour des informations : préférer le tiroir latéral, le popover, l'inline.
- Les messages d'erreur vagues : nommer la source en cause et la suite (« Alertmanager ne répond pas ;
  l'agent continue sans les alertes »).
- Le jargon interne à l'écran (`run_id`, `needs_clarification`, noms de fichiers JSON) sauf dans les
  vues de détail destinées aux experts, et toujours avec un libellé humain à côté.
- Toute dépendance chargée depuis Internet à l'exécution.
