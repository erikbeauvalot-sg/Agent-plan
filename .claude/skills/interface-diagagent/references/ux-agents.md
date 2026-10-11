# Montrer le travail des agents

Une interface d'agents réussie rend visibles trois choses : **ce que l'agent fait maintenant**, **ce
qu'il a trouvé et sur quelles preuves**, **ce que l'humain peut faire** (arrêter, corriger, juger). Les
patterns ci-dessous viennent des pratiques publiées en 2026 sur les interfaces d'IA agentique
(transparence, contrôle, responsabilité), adaptés à l'agent de diagnostic.

## Des événements à l'écran

L'état affiché est reconstruit **uniquement** à partir du flux `GET /api/runs/{id}/events` (SSE,
événement `agent` par ligne de `events.jsonl`, puis `end`). La fonction `apply()` de `app.js` réduit les
événements en état d'agents ; la conserver comme source de vérité et brancher le rendu dessus.

| Événement | Ce que l'écran montre |
| --- | --- |
| `classification_started` / `request_classified` | Ligne de statut « Je classe la demande… », puis la catégorie apparaît avec sa confiance ; en mode `clarify`, la demande de précision prend le premier plan |
| `agent_spawned` | Naissance du nœud (lien tracé puis nœud), objectif en sous-titre |
| `agent_started` | Modèle de l'agent, budget d'outils |
| `llm_call_started` / `llm_call_ended` | Segment « modèle » dans la chronologie ; ligne d'activité « réfléchit… » ; tokens qui défilent |
| `tool_call_started` / `tool_call_ended` | Ligne d'activité en clair (voir plus bas), segment « outil », impulsion sur le lien, jauge de budget ; erreur en rouge |
| `stop_requested` | État « arrêt demandé » immédiat sur l'agent (ou tous les agents en cours) |
| `report_submitted` | Icône de rapport sur le nœud (complet ou partiel) |
| `action_proposed` | Une carte d'action apparaît dans la section Actions, avec un compteur dans l'en-tête |
| `agent_ended` | Icône d'état finale, halo éteint |
| `category_changed` | Catégorie mise à jour avec une brève mise en évidence |
| `run_failed` | Bandeau d'échec qui nomme la cause et propose « Relancer… » |
| `end` | Révélation de la réponse (voir `direction-visuelle.md`) |

Le serveur rejoue tout le fichier à la connexion : ouvrir une investigation terminée reconstruit l'état
**sans animation** (pas de naissances en cascade de 30 agents) ; les animations ne jouent que pour les
événements reçus en direct après le rattrapage. Le flux reprend avec `Last-Event-ID` après une coupure :
afficher « Reconnexion… » dans la ligne de statut, jamais une page d'erreur.

## Patterns à appliquer

### Ligne de statut vivante

Sous le titre de l'investigation, une phrase qui dit ce qui se passe **maintenant**, construite avec la
formule **verbe d'action + objet précis + limite éventuelle** :

- « T03 interroge Prometheus : latence p95 de srv-pay-01 sur 24 h »
- « T02 cherche les erreurs dans les logs de srv-pay-01 depuis 21:00 »
- « L'agent principal rédige la synthèse à partir de 5 rapports »
- « 3 sous-agents en cours · 2 terminés · 41 appels d'outils · 12 400 tokens »

Traduire les noms d'outils MCP en verbes (`search` → « cherche dans les logs », `query_metric` →
« interroge les métriques », `get_ci` → « lit la fiche CMDB », `list_alerts` → « lit les alertes »,
`web_search` → « cherche sur le web »…) dans une table unique de `app.js`, avec
repli lisible pour un outil inconnu (« appelle l'outil search_x »). Région `aria-live="polite"`,
mise à jour au plus toutes les 2 s pour ne pas saturer les lecteurs d'écran.

### Fil d'activité

Journal lisible des événements marquants, le plus récent en haut, regroupé par agent quand plusieurs
événements se suivent ; horodatage relatif (« il y a 12 s ») avec l'heure exacte au survol. Il remplace
la lecture du JSON pour 90 % des besoins ; le JSON reste dans le tiroir de l'agent (« Voir les
journaux » : divulgation progressive).

### Signaux d'alerte sur les agents

Les signaux existants (bloqué, boucle, erreurs d'outil, budget, erreur modèle) deviennent des badges
avec icône sur le nœud **et** une mention dans la ligne de statut quand ils apparaissent
(« T04 : 3 erreurs d'outil d'affilée sur Alertmanager »). Un agent en difficulté doit attirer l'œil sans
clignoter : bordure de couleur d'état et halo arrêté.

### Succès partiel et outil en cause

Quand une source échoue, dire laquelle et ce que l'agent fait sans elle (« Alertmanager ne répond pas ;
T04 continue sans les alertes »). Une investigation `partial` affiche ce qui a réussi agent par agent,
pas un unique bandeau d'échec. Les « Limites » de la réponse sont mises en évidence, pas cachées.

### Montrer ses preuves (« show work »)

- Chaque affirmation de la réponse qui cite une preuve a sa puce de preuve cliquable.
- La puce ouvre le tiroir de l'agent sur l'appel exact, entrée et sortie visibles.
- Une affirmation **sans preuve** n'est pas mise en avant comme un fait (style neutre).
- Le **plan d'investigation** reste accessible (repliable) : c'est l'aperçu d'intention de l'agent.

### Signal de confiance

La catégorie (confiance du classifieur) et la cause probable (confiance donnée par l'agent : faible,
moyenne, élevée) affichent un indicateur visuel simple (trois segments) et un mot. Pas de pourcentage
à deux décimales : il donne une fausse précision.

### Escalade : la demande de précision

Quand le classifieur ou l'agent demande une précision (`needs_clarification`), l'investigation
s'arrête et la question de l'agent devient l'élément principal de l'écran, avec le champ de réponse
focalisé et « Préciser et relancer ». Proposer les précisions probables en puces quand l'agent les
donne.

### Contrôle : arrêter

- Bouton **Arrêter l'investigation** toujours visible pendant le direct (collant en haut), libellé
  explicite, couleur `--bad` en contour (pas de fond plein rouge qui crie).
- **Arrêter cet agent** sur le nœud (au survol et au focus) et dans le tiroir.
- Confirmation dans un petit `<dialog>` (pas `confirm()`), qui dit la portée et la conséquence :
  « L'agent T03 rendra un rapport partiel ; l'investigation continue. » / « L'agent principal rédigera
  une synthèse avec ce qui a déjà été trouvé. » Pour les rôles qui ont `kill`, une case « Arrêt
  immédiat, sans synthèse » dans la même confirmation.
- Réponse immédiate : l'agent passe en « arrêt demandé » dès le clic (état optimiste), puis l'événement
  `agent_ended` confirme. En cas d'erreur de l'API, revenir à l'état précédent et l'expliquer dans un
  toast.

### Correction de la catégorie

Popover ancré sur la catégorie : liste des catégories avec leur description, la catégorie courante
cochée, deux actions claires : **Enregistrer** (corrige pour l'apprentissage, ne relance rien) et
**Relancer avec cette catégorie**. La correction apparaît dans l'en-tête (« corrigée par Erik »).

### Actions proposées

L'agent ne fait **jamais** l'action : l'écran le dit dans le titre de la section et sur chaque carte
(icône de main levée ou de cadenas, « à exécuter par un humain »). Chaque carte : titre de l'action,
type, **risque** (faible, moyen, élevé, en couleur d'état et en mot), justification, **retour arrière**,
preuves en puces, commande éventuelle en mono avec bouton copier. Pour le Superviseur : Valider /
Rejeter avec commentaire, et l'état de la décision ensuite.

### Avis sur le diagnostic

Trois gros boutons à bascule (Utile, Partiel, Faux) sous la réponse ; la cause réelle et « cas
confirmé » apparaissent seulement après le choix (« Partiel » ou « Faux » mettent la cause réelle en
avant). Confirmation discrète après l'envoi, sans recharger.

## Pas de cadran d'autonomie

Les guides de conception d'agents recommandent souvent un réglage d'autonomie (observer, proposer,
agir avec confirmation, agir seul). Ici l'agent est en **lecture seule par construction** : il observe
et propose, il n'agit jamais. Ne pas introduire de réglage qui laisserait croire le contraire.
