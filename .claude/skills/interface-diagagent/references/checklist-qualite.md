# Checklist qualité

À passer avant de déclarer une tâche d'interface terminée. Dans la description de la PR, indiquer ce
qui a été vérifié et joindre ou décrire les captures regardées.

## Compréhension en 5 secondes

- [ ] Sur chaque écran touché, on sait en 5 secondes où l'on est, ce qui se passe et quoi faire ensuite.
- [ ] Une seule action principale visible par zone ; les actions secondaires sont plus discrètes.
- [ ] Les libellés sont des mots du métier (investigation, agent principal, sous-agent, source, preuve),
      sans identifiant technique non traduit.
- [ ] Les nombres ont leur unité et le bon format (`12 400 tokens`, `6 s`, `08/10/2026 06:11`).

## États

- [ ] Chargement : squelette ou progression au-delà de 400 ms, jamais d'écran blanc.
- [ ] Vide : message utile et prochaine action (exemples de questions, lien).
- [ ] Erreur : cause nommée (quelle source, quel appel), conséquence, action possible ; jamais
      d'`alert()` ni de pile d'appels brute.
- [ ] En direct, terminé, partiel, arrêté, échec, à préciser : chacun a couleur, icône et libellé.
- [ ] Droits : un rôle sans permission ne voit pas de bouton inutilisable ; une information masquée
      est signalée quand c'est utile (« détail réservé à l'auteur et aux superviseurs »).
- [ ] Coupure du flux : « Reconnexion… », reprise sans doublon ni perte.

## Interaction

- [ ] Retour visuel en moins de 100 ms sur chaque clic (état appuyé, désactivation pendant l'envoi).
- [ ] Les actions destructrices ou coûteuses (arrêt, relance, validation) confirment leur portée ;
      les autres ne demandent pas de confirmation.
- [ ] Aucune perte de saisie : une question en cours de frappe survit à un changement de vue.
- [ ] Les choix de l'utilisateur déjà faits sont repris (modèle, données, relance préremplie).

## Accessibilité (WCAG 2.2 AA)

- [ ] Contraste ≥ 4,5:1 pour le texte, ≥ 3:1 pour icônes, bordures de champs et focus, dans les deux
      thèmes.
- [ ] Tout est faisable au clavier, dans un ordre logique ; focus visible (anneau de 2 px en
      `--accent`) et jamais masqué par la barre collante.
- [ ] Tiroir, palette et confirmations : focus piégé tant qu'ils sont ouverts, `Échap` ferme, le focus
      revient sur l'élément d'origine.
- [ ] Cibles cliquables ≥ 24 × 24 px.
- [ ] Rôles et noms accessibles : boutons-icônes avec `aria-label`, graphe avec une alternative textuelle
      (liste des agents et de leur état), ligne de statut en `aria-live="polite"`.
- [ ] Rien ne repose sur la seule couleur ; aucun contenu ne clignote plus de 3 fois par seconde.
- [ ] `prefers-reduced-motion` respecté ; zoom à 200 % utilisable.

## Responsive

- [ ] 1440, 1024 et 390 px : pas de défilement horizontal de la page, pas de texte coupé sans moyen de
      le lire (infobulle ou retour à la ligne).
- [ ] Sur mobile, l'arrêt d'une investigation et la réponse restent accessibles sans chercher.

## Performances

- [ ] Pas de saute de mise en page à l'arrivée des événements (emplacements réservés, chiffres
      tabulaires).
- [ ] Fluide avec une grosse investigation (20 agents, 2 000 événements) ; ouverture d'une
      investigation terminée sans animation de rattrapage.
- [ ] Animations limitées à `transform`, `opacity`, `stroke-dashoffset` ; pause quand l'onglet est caché.
- [ ] Polices en woff2 auto-hébergées, `font-display: swap` ; pas de ressource externe (vérifier
      l'onglet Réseau).

## Code

- [ ] Tout texte externe échappé ; pas de HTML venant du modèle.
- [ ] Jetons CSS utilisés partout (aucune couleur ou durée en dur hors de `tokens.css`).
- [ ] Composants réutilisés plutôt que dupliqués ; pas de code mort laissé de l'ancienne version.
- [ ] `python -m pytest -q` passe ; nouveaux fichiers statiques bien empaquetés et servis.
- [ ] `poc/README.md` (section Interface web) et captures de `docs/images/` à jour si le comportement
      ou l'aspect a changé.

## L'effet « whoua », honnêtement

- [ ] Les trois moments signature sont soignés jusqu'au détail (timing, alignements, fin d'animation).
- [ ] Ailleurs, rien ne bouge sans raison.
- [ ] Montré à quelqu'un qui découvre l'outil : il comprend ce que font les agents sans explication.
