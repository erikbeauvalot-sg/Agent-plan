# Interface web : recherche sur les styles et les points d'attention (octobre 2026)

Synthèse de la recherche qui a servi à écrire le skill Claude Code
[`interface-diagagent`](../.claude/skills/interface-diagagent/SKILL.md) et la commande
[`/refonte-interface`](../.claude/commands/refonte-interface.md).

## Ce que montre l'interface actuelle

L'interface du POC est complète sur le fond (question, graphe, chronologie, arrêt, catégorie, actions,
avis, administration, cinq rôles) mais visuellement neutre : cartes blanches identiques, intertitres en
petites capitales grises, couleurs d'état sans icône, graphe redessiné entièrement à chaque événement
(aucune animation possible), réponse rendue comme un texte brut en bas de page. Le potentiel « whoua »
est déjà là, dans les données : des agents qui travaillent en parallèle, en direct, avec des preuves.
Il n'est simplement pas mis en scène.

## Tendances de style retenues

| Tendance 2026 | Ce qu'on en retient |
| --- | --- |
| Minimalisme stratégique : chaque élément aide à comprendre ou agir | Base de tout le skill ; pas de « mur d'indicateurs » |
| Esthétique « outil d'expert » (Linear, Raycast, Vercel) : densité maîtrisée, surfaces étagées par la lumière, un seul accent | Direction « salle de contrôle calme », thème sombre principal, vrai thème clair |
| Couleurs générées en LCH / OKLCH (Linear) | Jetons en `oklch()`, variantes par `color-mix()` |
| Interfaces conversationnelles et « prompt-to-output » avec exemples à l'endroit de la saisie | Question en héros, suggestions (alertes en cours, exemples) |
| Canevas agentique : les étapes de l'agent sont visibles et inspectables | Graphe d'agents vivant, fil d'activité, chronologie synchronisée |
| Palette de commandes `⌘K` | Palette pour tout faire au clavier |
| Latence travaillée : certaines actions instantanées, d'autres rythmées | Retour < 100 ms, squelettes au-delà de 400 ms, révélation de la réponse rythmée |
| Verre dépoli (« liquid glass »), 3D, rétrofuturisme | **Écartés** pour les zones de travail : coût en contraste et en lisibilité ; au mieux sur la palette flottante |

## Points d'attention pour une interface d'agents efficace

Les guides publiés en 2026 (Smashing Magazine, notamment) convergent sur quelques patterns :

- **Statut en clair** : verbe + objet précis + limite (« T03 interroge Prometheus : latence p95 de
  srv-pay-01 »), plutôt qu'un indicateur de chargement muet.
- **Liste d'étapes dynamique** et **journal dépliable** (« voir les journaux ») : la transparence est
  disponible, pas imposée.
- **Succès partiel** et **outil en cause** : dire quelle source a échoué et ce que l'agent fait sans
  elle, au lieu d'un bandeau d'échec global.
- **Montrer ses preuves** : chaque conclusion mène à l'appel d'outil qui la fonde.
- **Signal de confiance** simple, sans fausse précision.
- **Escalade** : quand l'agent doute, il demande ; la question de l'agent devient l'élément principal.
- **Contrôle** : arrêt toujours visible, portée explicite, état optimiste immédiat.
- **Aperçu d'intention** : le plan d'investigation et les actions proposées, jamais exécutées.
- Le **cadran d'autonomie** recommandé par ces guides ne s'applique pas : l'agent est en lecture seule.

Côté exploitation (observabilité, astreinte) : réduire la charge cognitive, ne montrer que ce qui est
actionnable, mettre les anomalies en évidence visuellement, intégrer les aides (runbooks) au parcours.

## Socle technique et accessibilité

- **WCAG 2.2 AA** ajoute notamment : focus jamais entièrement masqué (barres collantes), cibles de
  24 × 24 px minimum, alternative au glisser-déposer, authentification sans test cognitif.
- Les **View Transitions** (même document) sont disponibles dans Chrome, Edge, Safari 18 et Firefox 144 :
  utilisables en amélioration progressive pour passer de l'accueil à une investigation.
- `popover`, `<dialog>`, positionnement par ancre, requêtes de conteneur et `color-mix()` permettent
  d'écrire palette, popovers et tiroir sans bibliothèque, ce qui respecte la contrainte « sans build,
  sans CDN » du POC.
- Le skill « frontend-design » publié par Anthropic met en garde contre l'esthétique générique des
  interfaces générées par IA (dégradés violets, polices par défaut, mises en page prévisibles) et
  recommande des choix typographiques et chromatiques assumés, et une animation orchestrée plutôt que
  dispersée.

## Ce que le skill impose en conséquence

1. Trois moments signature : graphe vivant, barre de question avec palette, réponse reliée aux preuves.
2. Le mouvement porte du sens et respecte `prefers-reduced-motion`.
3. Couleur, icône et libellé pour chaque état.
4. Rendu par clé du graphe (fin du redessin complet) pour permettre les animations.
5. Polices, icônes et bibliothèques auto-hébergées.
6. Une checklist qualité (états, accessibilité, responsive, performances) et des captures regardées
   avant chaque PR.
7. Une refonte en six lots, une PR en brouillon par lot.

## Sources

- [Designing For Agentic AI: Practical UX Patterns For Control, Consent, And Accountability](https://smashingmagazine.com/2026/02/designing-agentic-ai-practical-ux-patterns/) (Smashing Magazine, février 2026)
- [Practical Interface Patterns For AI Transparency (Part 2)](https://smashingmagazine.com/2026/05/practical-interface-patterns-ai-transparency/) (Smashing Magazine, mai 2026)
- [14 UI trends 2026 to keep an eye on](https://www.lazarev.agency/articles/ui-trends-2026) (Lazarev)
- [23 UI Design Trends in 2026](https://musemind.agency/blog/ui-design-trends) (Musemind)
- [How we redesigned the Linear UI](https://linear.app/now/how-we-redesigned-the-linear-ui) (Linear)
- [The Linear Aesthetic, Decoded: Tokens, Density, and Keyboard-First UX](https://www.buildmvpfast.com/blog/linear-aesthetic-tokens-density-keyboard-first-ux-2026)
- [Reducing the cognitive load associated with observability](https://thenewstack.io/reducing-the-cognitive-load-associated-with-observability/) (The New Stack)
- [What's new in WCAG 2.2](https://tetralogical.com/blog/2023/10/05/whats-new-wcag-2.2) (TetraLogical)
- [What's new in view transitions (2025 update)](https://developer.chrome.com/blog/view-transitions-in-2025) (Chrome for Developers)
- [May 2026 Baseline monthly digest](https://web.dev/blog/baseline-digest-may-2026) (web.dev)
- [Anthropic Skills Marketplace: The Anti AI-Slop UI Design Skill](https://medium.com/@porter.nicholas/anthropic-skills-marketplace-the-anti-ai-slop-ui-design-skill-a572d0cfef4f) (sur le skill frontend-design)
- [CMD+K search pattern](https://www.chameleon.io/patterns/cmd-k-search) (Chameleon)
