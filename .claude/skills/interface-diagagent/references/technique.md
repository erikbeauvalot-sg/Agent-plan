# Technique

## Contraintes fixes

Décisions du 11 octobre 2026 ([plan](../../../../docs/plan-interface.md)) : TypeScript et React, React Flow
pour le graphe, bundle versionné.

- **TypeScript strict et React**, compilés par Vite dans `poc/src/diagagent/web/static/dist/`, **versionné**
  : FastAPI le sert tel quel et le POC s'installe toujours avec `pip install -e`, sans Node. Node n'est
  nécessaire que pour modifier l'interface. Après toute modification de `poc/web-ui/src/`, lancer
  `npm run build` et commiter le bundle avec les sources ; la CI le vérifie (`git diff --exit-code`).
- **Aucune ressource chargée depuis Internet à l'exécution** (CDN, Google Fonts, icônes distantes,
  analytics) : l'agent tourne sur des réseaux fermés. Les dépendances npm (React, React Flow, Lucide,
  polices Geist en `@fontsource-variable`) sont empaquetées dans le bundle, leurs licences copiées dans
  `web-ui/public/licenses/`. Ajouter une dépendance seulement si elle évite beaucoup de code (justifier
  dans la PR) et noter sa licence.
- **Navigateurs cibles** : versions récentes de Chrome, Edge, Firefox et Safari. Les fonctions récentes
  (View Transitions, `popover`, positionnement par ancre, `@starting-style`) s'utilisent en amélioration
  progressive : l'écran reste correct sans elles (`@supports`, test de `document.startViewTransition`).
- **Empaquetage** : `pyproject.toml` déclare `diagagent = ["web/static/**/*"]` (sous-dossiers compris).
- **Transition (lots 0a et 0b)** : la nouvelle interface est servie sur `/nouvelle`, l'actuelle
  (`static/index.html`, `app.js`, `app.css`) reste sur `/` jusqu'à la bascule du lot 0b ; les liens vers des
  vues pas encore portées ouvrent l'interface actuelle (`legacyRunHref`, `legacyAdminHref` dans
  `lib/route.ts`).

## Structure du front

```
poc/web-ui/
  package.json          # npm run dev | build | check (typecheck, lint, test) | format
  vite.config.ts        # base /static/dist/, sortie versionnée, noms de fichiers fixes, proxy /api en dev
  public/licenses/      # licences des polices et bibliothèques empaquetées
  src/
    main.tsx            # polices, styles, thème, montage
    App.tsx             # session (/api/me), routage par fragment, vues
    api/client.ts       # fetch, en-tête X-Diagagent, erreurs, 401 → connexion
    api/types.ts        # contrats de la passerelle
    state/runState.ts   # réduction des événements (reduce), signaux, tokens en direct ; testée (Vitest)
    lib/                # format (dates fr-FR, durées, tokens), route, theme, storage
    components/         # TopBar, StateBadge, icons (Lucide)…
    views/              # Login, Home et home/* ; Run, Admin au lot 0b
    styles/             # tokens.css, base.css, components.css, views.css (@layer)
```

Développer : `diagagent --now 2026-10-07T06:00:00Z serve` dans un terminal, `cd poc/web-ui && npm run dev`
dans un autre (Vite relaie `/api` et `/login` vers le port 8080), puis ouvrir l'adresse donnée par Vite.
Le formatage suit `.prettierrc` (120 colonnes) ; `npm run check` doit passer avant un commit.

## Rendu sans tout redessiner

L'interface actuelle remplace `innerHTML` du graphe à chaque image : aucune animation ne survit et le focus
clavier est perdu. Dans la nouvelle, l'état vient de `reduce()` (un nouvel objet par événement, l'ancien
jamais modifié) et React met à jour par clé :

- un nœud React Flow par agent (`id` = `agent_id`), dont seules les données changent (état, texte, jauge
  via `transform: scaleX()`, badges) ; composants de nœud mémorisés (`memo`) ;
- regrouper les événements reçus dans une même image (`requestAnimationFrame`) avant de mettre à jour
  l'état, pour ne pas rendre 50 fois par seconde pendant un rattrapage ;
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

- **Tout texte venant du modèle, des sources ou des utilisateurs passe par React** (texte des éléments,
  attributs), qui l'échappe. Jamais de `dangerouslySetInnerHTML` sur du contenu produit par le modèle :
  le rendu Markdown construit des éléments React à partir d'un petit sous-ensemble connu (titres, listes,
  gras, code, preuves), comme `md()` de l'interface actuelle.
- Les requêtes passent par `api()` / `post()` de `api/client.ts`, qui envoient l'en-tête `X-Diagagent`
  (protection CSRF côté serveur) ; ne pas contourner.
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

`poc/tools/ui_snapshots.py` (Playwright, hors des dépendances du POC) capture la connexion et l'accueil ;
l'étendre aux nouvelles vues au fil des lots :

```bash
uv run --with playwright playwright install chromium        # une fois (cache utilisateur, hors dépôt)
uv run --with playwright python tools/ui_snapshots.py --base http://127.0.0.1:8080 --login … --password …
```

Pour ne pas toucher aux vrais comptes, lancer le serveur sur une copie de la configuration
(`DIAGAGENT_HOME`) avec un compte de test. Objectif à tenir :

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
