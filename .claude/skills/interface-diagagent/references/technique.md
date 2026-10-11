# Technique

## Contraintes fixes

- **Pas de build, pas de framework, pas de npm à l'exécution.** HTML, CSS et JavaScript natifs, servis
  tels quels par FastAPI depuis `poc/src/diagagent/web/static/`. Le POC s'installe avec `pip install -e`
  et doit le rester.
- **Aucune ressource chargée depuis Internet** (CDN, Google Fonts, icônes distantes, analytics) :
  l'agent tourne sur des réseaux fermés et ses données ne sortent pas. Toute bibliothèque tierce est
  copiée dans `static/vendor/<nom>-<version>/` avec sa licence, et seulement si elle évite beaucoup de
  code (justifier dans la PR). Le graphe et la chronologie se font en SVG et CSS, sans bibliothèque.
- **Navigateurs cibles** : versions récentes de Chrome, Edge, Firefox et Safari. Les fonctions récentes
  (View Transitions, `popover`, positionnement par ancre, `@starting-style`) s'utilisent en amélioration
  progressive : l'écran reste correct sans elles (`@supports`, test de `document.startViewTransition`).
- **Empaquetage** : `pyproject.toml` déclare `diagagent = ["web/static/*"]`, qui n'inclut **pas** les
  sous-dossiers. En créant `static/js/`, `static/fonts/`, `static/vendor/`…, passer à
  `["web/static/**/*"]` et vérifier qu'une installation non éditable sert bien les fichiers.

## Structure cible du front

```
static/
  index.html          # squelette des vues, gabarits <template>
  css/
    tokens.css        # @layer tokens : couleurs, typo, espacements, mouvement (thèmes clair et sombre)
    base.css          # @layer base : reset, typographie, focus, liens, formulaires
    components.css    # @layer components : bouton, puce, carte, nœud, tiroir, palette, toast…
    views.css         # @layer views : mise en page de chaque écran
  js/
    main.js           # démarrage, routage, raccourcis
    api.js            # fetch, erreurs, 401 → connexion
    state.js          # réduction des événements (apply), signaux
    live.js           # EventSource, reconnexion, rattrapage sans animation
    graph.js          # graphe SVG : nœuds, liens, impulsions
    timeline.js       # chronologie en cascade
    views/home.js, views/run.js, views/admin.js, views/login.js
    ui/palette.js, ui/drawer.js, ui/toast.js, ui/popover.js, ui/dialog.js
    format.js         # dates fr-FR, durées, tokens, libellés d'états et d'outils
    md.js             # rendu Markdown minimal et sûr
  fonts/              # woff2 auto-hébergés + licences
  icons.svg           # sprite d'icônes
```

Modules ES natifs (`<script type="module" src="/static/js/main.js">`), un fichier CSS par couche chargé
dans l'ordre ou importé avec `@import` en tête de `app.css`. Découper par étapes : on peut garder
`app.js` et `app.css` pendant la transition et migrer écran par écran.

## Rendu sans tout redessiner

Aujourd'hui `render()` remplace `innerHTML` du graphe à chaque image : aucune animation ni transition ne
peut survivre, et le focus clavier est perdu à chaque événement. Passer à un **rendu par clé** :

- un élément DOM (ou un groupe SVG) par agent, créé une fois (`data-agent`), puis **mis à jour** champ
  par champ (classe d'état, texte, largeur de jauge via `transform: scaleX()`, badges) ;
- regrouper les mises à jour dans `requestAnimationFrame` (déjà fait par `scheduleRender`) ;
- ne recalculer la disposition du graphe que quand un agent naît ou disparaît ;
- tenir 60 images/s avec 20 agents et 2 000 événements : pas de lecture de mise en page (`offsetWidth`,
  `getBoundingClientRect`) entre deux écritures, pas d'ombres animées, `contain: layout paint` sur les
  nœuds et les lignes de chronologie.

Disposition du graphe : agent principal en haut, sous-agents en rangées centrées dessous (comme
aujourd'hui), liens en courbes de Bézier SVG du bas du parent au haut de l'enfant. Les impulsions sont
de petits cercles SVG animés le long du chemin (`getPointAtLength` calculé une fois, ou
`offset-path` en CSS), retirés à la fin de l'animation, limités à 3 simultanées par lien.

## Flux temps réel

- `EventSource('/api/runs/{id}/events')` ; événements nommés `agent` (une ligne de `events.jsonl`) et
  `end` ; reprise native avec `Last-Event-ID`.
- Distinguer **rattrapage** et **direct** : tant que les événements reçus ont un horodatage antérieur
  à l'ouverture de la page de plus de quelques secondes, appliquer sans animation.
- Fermer le flux en quittant la vue (`closeStream()` existe) ; un seul flux ouvert à la fois.
- Les données de synthèse (`GET /api/runs/{id}`) se rechargent avec un délai de regroupement (déjà
  `scheduleSummary`, 300 ms).

## Sécurité

- **Tout texte venant du modèle, des sources ou des utilisateurs est échappé** (`esc()`), y compris
  dans les attributs. Le rendu Markdown (`md()`) échappe d'abord, puis n'introduit que des balises
  connues ; garder ce principe, ne jamais insérer de HTML produit par le modèle.
- Préférer `textContent` et la création d'éléments à `innerHTML` pour les nouveaux composants.
- Les requêtes passent par `api()` qui envoie l'en-tête `X-Diagagent` (protection CSRF côté serveur) ;
  ne pas contourner.
- Pas de données sensibles dans `localStorage` : seulement des préférences (thème, dernier modèle,
  dernières données, onglets).
- Les droits sont vérifiés par le serveur ; l'écran masque, il ne protège pas.

## Lancer et voir l'interface

```bash
cd poc && source .venv/bin/activate
diagagent user add erik --role administrateur --name Erik   # une fois
diagagent --now 2026-10-07T06:00:00Z serve                  # http://127.0.0.1:8080
```

Une investigation réelle demande un modèle (profil `ollama` local par défaut, ou `openai`, `azure`).
Pour travailler l'aspect **en direct sans modèle**, créer si besoin (lot de fondations) un petit outil
de démonstration, par exemple `diagagent demo-live <run_id>` ou `poc/tools/demo_live.py`, qui recopie
une investigation existante de `runs/` dans une nouvelle, en réécrivant `events.jsonl` ligne par ligne
au rythme des horodatages d'origine (accéléré ou ralenti), le manifest restant `running` jusqu'à la
fin. Pour obtenir une première investigation sans modèle payant : `diagagent replay <run_id>` sur une
investigation enregistrée, ou les jeux d'évaluation avec l'adaptateur `scripted` des tests.

## Captures automatiques

Pour vérifier un écran, utiliser Playwright (Python : `pip install playwright` ; navigateur Chromium
déjà présent ou `playwright install chromium`) dans un script de développement, hors des dépendances du
POC, par exemple `poc/tools/ui_snapshots.py` :

- se connecter, ouvrir l'accueil, une investigation terminée, une investigation en cours (démo en
  direct), le tiroir d'un agent, l'administration ;
- capturer en 1440 × 900, 1024 × 768 et 390 × 844, thème sombre et clair (`color_scheme`), et une fois
  avec `reduced_motion="reduce"` ;
- enregistrer dans un dossier ignoré par git (`poc/.snapshots/`), puis **regarder les images** avant de
  conclure. Les captures retenues pour la documentation vont dans `docs/images/`.

Contrôle d'accessibilité automatique en complément : axe-core injecté par le script de capture depuis
un fichier local (jamais en production), zéro violation « serious » ou « critical ».

## Tests

- `cd poc && python -m pytest -q` doit passer (la CI le lance sur chaque PR et fusionne
  automatiquement une PR non brouillon dont les tests passent : ouvrir en **brouillon** un lot qui doit
  être relu).
- Les tests de `tests/test_web.py` couvrent l'API (connexion, rôles, flux, arrêt, catégorie, avis).
  Ajouter un test si l'interface demande un nouveau point d'API ou un nouveau champ ; ne rien changer
  aux contrats existants sans mettre à jour les tests.
- Ajouter un test simple qui vérifie que chaque fichier référencé par `index.html` est servi (200),
  pour attraper un oubli d'empaquetage.
