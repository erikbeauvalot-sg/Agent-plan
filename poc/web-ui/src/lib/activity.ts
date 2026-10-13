// Ce que fait un agent, en une phrase lisible (ligne de statut, fil d'activité, nœud du graphe) :
// « T03 interroge les métriques : cpu.usage de srv-pay-01 ». Les noms d'outils restent dans le détail.

type Args = Record<string, unknown>;

const s = (v: unknown): string =>
  typeof v === "string" ? v : v === undefined || v === null ? "" : typeof v === "object" ? "" : String(v);

const SOURCE_LABEL: Record<string, string> = {
  logs: "les logs",
  metrics: "les métriques",
  events: "les alertes",
  incidents: "les incidents",
  changes: "les changements",
  cmdb: "la CMDB",
  prometheus: "Prometheus",
  alertmanager: "Alertmanager",
};

const source = (a: Args) => SOURCE_LABEL[s(a.source)] ?? (s(a.source) || "une source");

/** Filtres d'une recherche, en clair et sans accolades (host=srv-pay-01, level=error). */
function filters(a: Args): string {
  const f = a.filters;
  const parts: string[] = [];
  if (f && typeof f === "object")
    for (const [k, v] of Object.entries(f as Args)) {
      const value = Array.isArray(v) ? v.map(s).join("|") : s(v);
      if (value) parts.push(`${k}=${value}`);
    }
  if (s(a.text)) parts.push(`« ${s(a.text)} »`);
  return parts.slice(0, 3).join(", ");
}

const of = (what: string, a: Args, key = "host") => (s(a[key]) ? `${what} de ${s(a[key])}` : what);

const TOOLS: Record<string, (a: Args) => string> = {
  search: (a) => `cherche dans ${source(a)}${filters(a) ? ` : ${filters(a)}` : ""}`,
  aggregate: (a) => `compte dans ${source(a)} par ${s(a.field) || "champ"}${filters(a) ? ` (${filters(a)})` : ""}`,
  query_metric: (a) => `interroge les métriques : ${of(s(a.metric) || "série", a)}`,
  list_metrics: (a) => `liste les métriques${s(a.host) ? ` de ${s(a.host)}` : ""}`,
  promql: (a) => `interroge Prometheus : ${s(a.query)}`,
  container_metrics: (a) => `lit les métriques des conteneurs${s(a.host) ? ` de ${s(a.host)}` : ""}`,
  container_memory: (a) => `lit la mémoire des conteneurs${s(a.host) ? ` de ${s(a.host)}` : ""}`,
  container_changes: (a) => `cherche les changements de conteneurs${s(a.host) ? ` sur ${s(a.host)}` : ""}`,
  host_memory: (a) => `lit la mémoire${s(a.host) ? ` de ${s(a.host)}` : ""}`,
  oom_events: (a) => `cherche les processus tués faute de mémoire${s(a.host) ? ` sur ${s(a.host)}` : ""}`,
  top_processes: (a) => `liste les processus les plus gourmands${s(a.host) ? ` de ${s(a.host)}` : ""}`,
  list_alerts: (a) => `liste les alertes en cours${s(a.host) ? ` sur ${s(a.host)}` : ""}`,
  alert_history: (a) =>
    `lit l'historique des alertes${s(a.alertname) ? ` ${s(a.alertname)}` : ""}${s(a.host) ? ` sur ${s(a.host)}` : ""}`,
  alert_rule: (a) => `lit la règle d'alerte ${s(a.alertname)}`,
  list_silences: () => "liste les silences d'alertes",
  list_hosts: () => "vérifie les cibles de supervision",
  list_ssh_hosts: () => "liste les machines joignables en SSH",
  get_ci: (a) => `lit la fiche CMDB de ${s(a.id_or_hostname) || s(a.ci)}`,
  get_dependencies: (a) => `suit les dépendances de ${s(a.ci)}${s(a.depth) ? ` (profondeur ${s(a.depth)})` : ""}`,
  get_owners: (a) => `cherche les responsables de ${s(a.ci)}`,
  get_owner: (a) => `cherche le responsable de ${s(a.ci)}`,
  resolve_entity: (a) => `identifie « ${s(a.name)} »`,
  changes_around: (a) => `cherche les changements autour de ${s(a.entity)}${s(a.hours) ? ` (${s(a.hours)} h)` : ""}`,
  list_sources: () => "liste les sources disponibles",
  describe_source: (a) => `lit la description de la source ${s(a.id) || s(a.source)}`,
  web_search: (a) => `cherche sur le web : ${s(a.query)}`,
  web_page: (a) => `lit la page ${s(a.url)}`,
  spawn_subagent: (a) => `lance un sous-agent ${s(a.role)} : ${s(a.objective)}`,
  wait_subagents: (a) =>
    Array.isArray(a.task_ids) && a.task_ids.length
      ? `attend ${a.task_ids.length > 1 ? `les sous-agents ${a.task_ids.map((t) => s(t).split("-")[0]).join(", ")}` : `le sous-agent ${s(a.task_ids[0]).split("-")[0]}`}`
      : "attend ses sous-agents",
  submit_report: () => "rend son rapport",
  write_plan: () => "écrit le plan d'investigation",
  propose_action: (a) => `propose une action : ${s(a.title)}`,
  requalify: (a) => `change de catégorie : ${s(a.category)}`,
};

export const agentName = (id: string): string => (id === "lead" ? "Agent principal" : (id.split("-")[0] ?? id));

/** Description d'un appel d'outil, sans le nom de l'agent. */
export function describeCall(tool: string, args: unknown): string {
  const a = args && typeof args === "object" ? (args as Args) : {};
  const text = TOOLS[tool]?.(a) ?? `appelle ${tool}`;
  return text.length > 140 ? `${text.slice(0, 139)}…` : text;
}
