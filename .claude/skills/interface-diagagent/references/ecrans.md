# Écrans

L'application est une page unique (`static/index.html`) avec trois vues routées par le fragment d'URL :
`#` accueil, `#<run_id>` investigation (adresse partageable), `#admin` administration ; plus l'écran de
connexion, le tiroir de détail d'un agent et, à ajouter, la palette de commandes.

## Inventaire à préserver

Toute refonte garde ces fonctions (vérifier chacune à la fin d'un lot qui touche l'écran concerné) :

**Connexion** : identifiant et mot de passe, message d'erreur, redirection vers l'adresse demandée
(`next`), verrouillage après 5 échecs (message du serveur), formulaire qui fonctionne aussi sans
JavaScript (`POST /login`).

**Barre du haut** : nom de l'application, heure de référence figée quand le serveur tourne avec `--now`,
utilisateur et rôles, lien Administration (selon droits), déconnexion.

**Accueil** :
- Question, choix du **modèle** (profils, option indisponible grisée avec sa raison, dernier choix
  retenu par le navigateur), des **données** (démo, maison, les deux) et de la **catégorie** (automatique
  ou imposée) ; aide qui rappelle les modèles par rôle ; mode **relance** (bandeau « Relance de … »,
  annulation).
- Investigations **en cours** ; **dernières investigations** avec recherche, filtre par catégorie,
  « Afficher plus » ; pour chacune : question, état, date, auteur, catégorie, modèle, durée, tokens.
- **État** des modèles et des sources (vérification relançable), **chiffres du jour**, **alertes en
  cours** avec « Investiguer » qui préremplit la question, **dernières évaluations** par modèle.
- **Statistiques** sur 1, 7 ou 30 jours (évaluations incluses ou non) : par catégorie, par agent, par
  modèle.

**Investigation** :
- Question, date, auteur, identifiant, lien vers l'investigation d'origine d'une relance, heure de
  référence ; modèles par rôle et tokens comptés en direct.
- **Catégorie** : libellé, confiance, playbook, décision ; **Corriger** (enregistrer, ou relancer avec
  cette catégorie).
- État, **Partager**, **Relancer…**, **Arrêter l'investigation**.
- **Graphe** : agent principal et sous-agents, état, objectif, outils utilisés sur budget, durée, tokens,
  modèle, jauge de budget, signaux (bloqué depuis 120 s, boucle, 3 erreurs d'outil d'affilée, budget à
  80 %, erreur du modèle). Clic sur un nœud : tiroir de l'agent.
- **Chronologie** : une ligne par agent, segments modèle, outil et erreur ; clic : tiroir sur l'appel.
- **Actions proposées** (« jamais exécutées par l'agent ») avec type, risque, justification, retour
  arrière, preuves, et décision de validation pour le Superviseur.
- **Réponse** en Markdown avec preuves cliquables ; **avis** (utile, partiel, faux ; cause réelle ;
  « enregistrer comme cas confirmé ») ; **précision** quand l'agent en demande une (« Préciser et
  relancer ») ; **plan d'investigation** repliable.

**Tiroir d'un agent** : modèle et tokens, prompt reçu (ou prompt système), rapport, appels d'outils
(entrée, sortie, durée, erreur ; ouverture directe sur l'appel cité), réponses du modèle, **Arrêter cet
agent** ; message adapté quand le rôle ne voit pas le détail.

**Administration** (selon droits) : actions à valider, indicateurs par catégorie, propositions
d'évolution des catégories et playbooks (accepter, rejeter, avec commentaire), coûts (tokens par jour,
utilisateur, modèle), journal d'accès (200 dernières entrées).

## Ce que voit chaque rôle

L'API applique déjà les droits ; l'écran **masque** ce qui n'est pas permis (au lieu d'afficher un
bouton qui échouera) et dit pourquoi une information manque quand c'est utile. Les permissions
arrivent dans `/api/me` (`me.permissions`) et, pour une investigation, dans `can_details`, `can_stop`,
`can_share`.

| Rôle | Poser | Voir | Détail (prompts, appels) | Arrêter | Valider | Administration |
| --- | --- | --- | --- | --- | --- | --- |
| Lecteur | non | investigations partagées | non | non | non | non |
| Opérateur | oui | les siennes | les siennes | les siennes | non | non |
| Superviseur | oui | toutes | toutes | toutes, et arrêt immédiat | oui | indicateurs, coûts |
| Administrateur | oui | toutes | toutes | toutes, et arrêt immédiat | non | indicateurs, coûts, journal, utilisateurs |
| Auditeur | non | toutes | toutes | non | non | indicateurs, coûts, journal |

Un Lecteur n'a pas de zone de question : son accueil devient une liste des investigations partagées.
L'**arrêt immédiat** (`POST /api/runs/{id}/agents/lead/stop?kill=true`, permission `kill`) existe dans
l'API mais pas encore à l'écran : l'ajouter comme option secondaire du bouton d'arrêt, avec
confirmation explicite.

## Mise en page cible

### Coquille

- Barre du haut fine et collante : marque à gauche ; au centre, sur une investigation, son titre court
  et son état ; à droite, heure de référence (pastille ambre si figée), bouton de palette (`⌘K`),
  thème, avatar avec menu (rôles, déconnexion). La barre ne doit jamais masquer un élément qui a le
  focus (`scroll-padding-top` égal à sa hauteur).
- Largeur utile jusqu'à 1440 px, marges latérales de 16 px sur mobile.

### Accueil : « poser, suivre, reprendre »

1. **Héros** : la question en grand, centrée, focus automatique ; puces d'options dessous ; suggestions
   (alertes en cours, exemples, dernières questions) quand le champ est vide ; `Entrée` lance,
   `Maj+Entrée` passe à la ligne.
2. **En cours** : cartes larges pour les investigations actives, avec un mini-graphe vivant (points
   colorés par agent) et la ligne de statut courante. Un clic ouvre l'investigation.
3. **Deux colonnes** : à gauche l'historique (recherche, filtres en puces, lignes denses) ; à droite
   l'état des sources (une ligne par source, point d'état et détail au survol), les alertes, les
   chiffres du jour.
4. **Statistiques** dans une section repliable ou un onglet, pas en tête : elles servent au pilotage,
   pas à l'urgence.

État vide (premier lancement) : un message d'accueil, deux ou trois questions d'exemple cliquables, et
l'état des sources pour savoir si l'on peut commencer.

### Investigation : « voir, comprendre, décider »

Disposition sur grand écran (≥ 1200 px) :

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Question (titre)                      [état] [Partager] [Relancer] [■ Arrêter] │
│ catégorie · confiance · Corriger      modèles · tokens en direct · heure réf. │
│ ▸ Ligne de statut vivante : « T03 interroge Prometheus : latence p95… »        │
├───────────────────────────────────────────────┬──────────────────────────┤
│ Graphe d'agents (canevas)                      │ Fil d'activité            │
│                                               │ (événements lisibles,     │
│                                               │  le plus récent en haut)  │
├───────────────────────────────────────────────┴──────────────────────────┤
│ Chronologie (cascade synchronisée avec le graphe)                         │
├──────────────────────────────────────────────────────────────────────────┤
│ Réponse : synthèse · cause probable · chronologie · actions · limites     │
│ Avis · Précision · Plan                                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Pendant** l'investigation, graphe, fil d'activité et chronologie occupent l'écran ; la réponse est
  un emplacement discret (« La synthèse apparaîtra ici »).
- **À la fin**, la réponse remonte au premier plan (défilement doux jusqu'à elle si l'utilisateur
  n'a pas fait défiler entre-temps), le graphe se compacte.
- Survoler un nœud met en évidence sa ligne de chronologie et ses événements, et inversement.
- Sur tablette, le fil d'activité passe sous le graphe ; sur mobile, onglets « Agents · Chronologie ·
  Réponse », et le bouton d'arrêt reste accessible dans la barre du haut.

### Tiroir d'un agent

Panneau latéral droit (`<dialog>` non modal ou `aside` avec gestion du focus), largeur 560 px, fermeture
par `Échap` et par la croix ; onglets **Résumé** (objectif, état, rapport, modèle, tokens), **Appels
d'outils** (liste dense, chaque appel dépliable, entrée et sortie en mono avec coloration minimale,
bouton copier), **Échanges avec le modèle**, **Prompt**. Navigation d'un agent à l'autre sans fermer le
tiroir (`←` `→` ou `[` `]`).

### Administration

Onglets dans l'ordre de l'urgence : **À valider** (avec compteur), **Propositions**, **Indicateurs**,
**Coûts**, **Journal**. Tableaux denses, en-têtes collants, tri par colonne, chiffres alignés à droite en
chiffres tabulaires.

### Connexion

Carte centrée sur le fond de la salle de contrôle (trame de points, halo très discret) ; nom de
l'application, deux champs, un bouton. Affichage du mot de passe à la demande, gestionnaires de mots de
passe compatibles (`autocomplete`), message de verrouillage clair avec la durée.

## Raccourcis clavier

| Raccourci | Effet |
| --- | --- |
| `Ctrl+K` / `⌘K` | Palette de commandes |
| `/` | Aller au champ de question (accueil) ou à la recherche |
| `Entrée` / `Maj+Entrée` | Lancer / nouvelle ligne dans la question |
| `Échap` | Fermer le tiroir, le popover ou la palette |
| `g` puis `h` / `g` puis `a` | Accueil / Administration |
| `[` `]` | Agent précédent / suivant dans le tiroir |
| `?` | Aide des raccourcis |

Les raccourcis à une touche ne s'activent jamais quand le focus est dans un champ de saisie. Aucun
raccourci clavier pour arrêter un agent : l'arrêt passe toujours par un bouton.
