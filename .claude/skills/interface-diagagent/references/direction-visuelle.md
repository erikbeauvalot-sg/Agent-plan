# Direction visuelle

## L'intention : une salle de contrôle, pas un site vitrine

L'interface évoque une **salle de contrôle calme** : fond sombre profond et légèrement bleuté, surfaces
étagées par la lumière plutôt que par les ombres, une seule couleur d'accent « signal », des couleurs
d'état franches réservées aux états. Le calme général rend les changements visibles : quand un agent
démarre, échoue ou termine, on le voit immédiatement parce que rien d'autre ne bouge.

Références de ton (à étudier, pas à copier) : Linear (densité, hiérarchie, couleurs générées en LCH),
Vercel et Raycast (palette de commandes, précision typographique), Grafana et Honeycomb (lisibilité des
données temporelles), les vues « trace » des outils d'observabilité (chronologies en cascade).

Le thème sombre est le thème principal (astreintes de nuit, écrans de supervision) ; le thème clair est
un vrai thème, aussi soigné, choisi par `prefers-color-scheme` et forçable par l'utilisateur (bouton
dans la barre du haut, choix retenu en `localStorage`).

## Couleurs : jetons en OKLCH

Toutes les couleurs sont des variables CSS en `oklch()`, déclarées une fois dans une couche `tokens`.
OKLCH donne une luminosité perçue homogène : deux couleurs d'état de même `L` paraissent aussi claires,
ce qui garde l'équilibre du graphe. Dériver les variantes (survol, fond teinté, bordure) avec
`color-mix(in oklch, …)` plutôt que de multiplier les variables.

Valeurs de départ (à ajuster à l'œil, en gardant les contrastes) :

```css
@layer tokens {
  :root, :root[data-theme="dark"] {
    color-scheme: dark;
    --bg:        oklch(0.16 0.012 255);   /* fond de page */
    --surface-1: oklch(0.19 0.012 255);   /* cartes, panneaux */
    --surface-2: oklch(0.22 0.013 255);   /* survol, éléments imbriqués */
    --surface-3: oklch(0.26 0.014 255);   /* tiroir, palette, popovers */
    --line:      oklch(0.32 0.012 255 / 0.65);   /* filets de 1 px */
    --text:      oklch(0.96 0.005 255);
    --text-2:    oklch(0.78 0.010 255);   /* texte secondaire */
    --text-3:    oklch(0.64 0.012 255);   /* libellés discrets, ≥ 4,5:1 sur --bg à vérifier */
    --accent:    oklch(0.80 0.14 200);    /* cyan « signal » : focus, action principale, en cours */
    --accent-ink: oklch(0.18 0.02 255);   /* texte sur l'accent */
    --ok:      oklch(0.78 0.15 155);
    --warn:    oklch(0.83 0.15 80);
    --bad:     oklch(0.68 0.20 25);
    --stopped: oklch(0.66 0.02 255);
    --clarify: oklch(0.76 0.12 300);     /* demande de précision */
    --llm:     oklch(0.72 0.12 260);     /* segments « modèle » de la chronologie */
    --tool:    oklch(0.62 0.03 255);     /* segments « outil » */
  }
  :root[data-theme="light"] {
    color-scheme: light;
    --bg:        oklch(0.985 0.003 255);
    --surface-1: oklch(1 0 0);
    --surface-2: oklch(0.965 0.005 255);
    --surface-3: oklch(1 0 0);
    --line:      oklch(0.90 0.008 255);
    --text:      oklch(0.22 0.02 255);
    --text-2:    oklch(0.42 0.02 255);
    --text-3:    oklch(0.52 0.02 255);
    --accent:    oklch(0.55 0.13 215);
    --accent-ink: oklch(0.99 0 0);
    --ok: oklch(0.55 0.14 155);  --warn: oklch(0.62 0.15 70);  --bad: oklch(0.55 0.20 25);
    --stopped: oklch(0.55 0.02 255);  --clarify: oklch(0.52 0.15 300);
    --llm: oklch(0.58 0.14 260);  --tool: oklch(0.70 0.02 255);
  }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) { /* reprendre les valeurs du thème clair */ }
  }
}
```

Règles :

- **Un seul accent.** Il marque le focus, l'action principale de l'écran et l'état « en cours ». Jamais
  pour décorer.
- **Les couleurs d'état ne servent qu'aux états** (agent, investigation, alerte, risque d'une action).
  Fond teinté d'un état : `color-mix(in oklch, var(--bad) 14%, var(--surface-1))`.
- **Profondeur par la lumière** : chaque niveau de surface est un peu plus clair (sombre) ; filet de 1 px
  `--line` en guise de texture. Ombres seulement pour ce qui flotte (tiroir, palette, popover, toast).
- Vérifier les contrastes de chaque couple texte/fond (4,5:1 pour le texte, 3:1 pour les icônes,
  bordures de champs et anneaux de focus), dans les deux thèmes.

## Atmosphère

- Le **canevas du graphe** porte une trame de points très discrète
  (`radial-gradient(circle, var(--line) 1px, transparent 1px) 0 0 / 24px 24px`), comme un plan de
  travail. Nulle part ailleurs.
- Un **halo d'accent** très doux (opacité ≤ 8 %) derrière la zone active pendant une investigation en
  cours ; il s'éteint à la fin. C'est le seul dégradé « d'ambiance ».
- Pas de photos, pas d'illustrations, pas de mascotte. L'identité vient de la typographie, de la
  précision des alignements et du graphe.

## Typographie

Polices **auto-hébergées** dans `static/fonts/` (woff2, licence OFL, `font-display: swap`), jamais
Google Fonts : l'interface tourne sur des réseaux fermés.

- **Texte et titres : Geist** (ou IBM Plex Sans en alternative). Titres en graisse 600, approche
  légèrement resserrée (`letter-spacing: -0.01em` à partir de 20 px).
- **Données et identifiants : Geist Mono** (ou JetBrains Mono) pour les hôtes, numéros de changement,
  requêtes, chemins de preuves, durées. Les chiffres qui changent en direct utilisent
  `font-variant-numeric: tabular-nums` pour ne pas trembler.
- Repli : `system-ui, -apple-system, "Segoe UI", sans-serif` et `ui-monospace, monospace`.

Échelle (en `rem`, base 16 px) : 12 · 13 · 14 · 16 · 20 · 24 · 32. Les vues denses (listes, graphe,
chronologie, administration) sont en 13-14 px ; **la réponse de l'agent est un texte de lecture** :
16 px, interligne 1,6, largeur de ligne ≤ 72 caractères.

Les intertitres de cartes ne sont plus en petites capitales grises : un titre court en 14 px graisse
600, `--text`, éventuellement précédé d'une icône.

## Espacements, rayons, densité

- Grille de 4 px : 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 (variables `--space-1` à `--space-8`).
- Rayons : 6 px (contrôles), 10 px (cartes et nœuds), 999 px (pastilles d'état). Rien de plus rond.
- Lignes de liste et de tableau : 32 à 36 px de haut. Cibles cliquables ≥ 24 × 24 px, idéalement 32.
- Densité « outil d'expert » sur les vues de travail, aération plus généreuse sur l'accueil vide et la
  connexion (premier contact).

## Icônes

Un sprite SVG local `static/icons.svg` (sous-ensemble de Lucide, licence ISC, version notée en
commentaire), utilisé par `<svg><use href="/static/icons.svg#stop"/></svg>`. Trait de 1,5 px, taille 16
ou 20 px, `currentColor`. Pas d'emojis comme icônes. Une icône par état :

| État | Icône | Couleur |
| --- | --- | --- |
| En cours | cercle qui tourne (ou point pulsant) | `--accent` |
| Terminé | coche | `--ok` |
| Partiel | demi-cercle | `--warn` |
| Arrêt demandé / arrêté | carré | `--stopped` |
| Échec | croix dans un cercle | `--bad` |
| À préciser | point d'interrogation | `--clarify` |

## Mouvement

Jetons :

```css
--dur-1: 120ms;   /* survol, appui, bascule */
--dur-2: 200ms;   /* apparition d'un élément, popover */
--dur-3: 320ms;   /* transition de vue, tiroir */
--ease-out: cubic-bezier(.2, .8, .2, 1);
--ease-in-out: cubic-bezier(.65, 0, .35, 1);
```

- N'animer que `transform`, `opacity` et, pour les tracés SVG, `stroke-dashoffset`.
- Apparitions en cascade : décalage de 30 à 40 ms, 8 éléments au plus, puis tout le reste d'un coup.
- Respiration d'un agent en cours : halo qui pulse sur 1,6 s, très faible amplitude. Une seule chose
  « respire » par agent.
- `@media (prefers-reduced-motion: reduce)` : plus de respiration, de particules ni de cascade ; les
  changements d'état restent visibles par la couleur, l'icône et le texte.
- Mettre en pause les animations continues quand l'onglet est caché (`document.visibilityState`).

## Les moments signature (« whoua »)

Trois moments, travaillés jusqu'au détail. Tout le reste reste sobre pour qu'ils ressortent.

### 1. Le graphe d'agents vivant

- L'agent principal apparaît au centre haut ; à chaque `agent_spawned`, le sous-agent **naît** de lui :
  le lien se trace (`stroke-dashoffset` de 100 % à 0 en 320 ms), puis le nœud apparaît (échelle 0,96 → 1,
  opacité 0 → 1).
- Un agent en cours a un halo d'accent qui respire ; sa ligne d'activité (« interroge mcp-metrics… »)
  change à chaque appel d'outil.
- À chaque `tool_call_ended`, une **impulsion** (petit point lumineux) parcourt le lien du sous-agent
  vers l'agent principal : on voit littéralement l'information remonter. Une impulsion rouge pour une
  erreur d'outil.
- La jauge de budget se remplit en continu ; elle passe à l'orange à 80 %, au rouge au maximum.
- À la fin d'un agent, le halo s'éteint et l'icône d'état se pose (légère mise à l'échelle 1,1 → 1).
  À la fin de l'investigation, un balayage lumineux unique parcourt le graphe, puis tout se calme.

### 2. La barre de question et la palette de commandes

- Sur l'accueil, la question est **l'élément héros** : grande zone de saisie centrée, focus automatique,
  exemples de questions et alertes en cours proposées en suggestions cliquables sous le champ (fin de
  la page blanche).
- `Ctrl+K` / `⌘K` ouvre partout une **palette de commandes** (`<dialog>` natif) : poser une question,
  ouvrir une investigation récente, investiguer une alerte, relancer, aller à l'administration, changer
  de thème. Recherche floue, navigation aux flèches, raccourci affiché à droite de chaque commande.
- Les options (modèle, données, catégorie) sont des puces discrètes sous la question, pas des listes
  déroulantes alignées : on voit la valeur courante, un clic ouvre un popover de choix.

### 3. La révélation de la réponse, reliée aux preuves

- À la fin, la **synthèse** arrive en premier, en grand, avec la **cause probable** et un indicateur de
  confiance ; chronologie, actions et limites suivent en cascade.
- Chaque preuve citée (`[subagents/T03-…/calls/0002.json]`) devient une **puce de preuve** lisible
  (« T03 · métriques · appel 2 »). Au survol, le nœud de l'agent concerné s'illumine dans le graphe et
  son segment dans la chronologie ; au clic, le tiroir de l'agent s'ouvre sur l'appel exact.
- Les heures de la chronologie du diagnostic (21:50, 22:10…) sont alignées en colonne, en chiffres
  tabulaires, pour se lire d'un coup d'œil.

### Liant : les transitions de vue

Passer de l'accueil à une investigation utilise l'API View Transitions (même document,
`document.startViewTransition`) : la question tapée se transforme en titre de l'investigation
(`view-transition-name: question`). Amélioration progressive : sans prise en charge, le changement est
immédiat. Désactivé avec `prefers-reduced-motion`.
