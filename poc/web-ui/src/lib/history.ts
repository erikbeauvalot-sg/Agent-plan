// Filtres de l'historique : gardés dans l'adresse (#?periode=7j&statut=completed,partial…) pour qu'une vue
// filtrée se partage et survive à un rechargement, traduits en paramètres de GET /api/runs.

export type Period = "" | "jour" | "7j" | "30j" | "dates";

export interface HistoryFilters {
  period: Period;
  since: string; // AAAA-MM-JJ, période « dates » seulement
  until: string;
  user: string;
  category: string;
  status: string[];
  host: string;
  q: string;
}

export const NO_FILTERS: HistoryFilters = {
  period: "",
  since: "",
  until: "",
  user: "",
  category: "",
  status: [],
  host: "",
  q: "",
};

export const PERIOD_LABEL: Record<Period, string> = {
  "": "toutes dates",
  jour: "aujourd'hui",
  "7j": "7 derniers jours",
  "30j": "30 derniers jours",
  dates: "entre deux dates",
};

const KEYS = {
  period: "periode",
  since: "du",
  until: "au",
  user: "utilisateur",
  category: "categorie",
  status: "statut",
  host: "host",
  q: "q",
} as const;

const PERIODS: Period[] = ["jour", "7j", "30j", "dates"];
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export function filtersFromHash(hash: string): HistoryFilters {
  const raw = hash.replace(/^#/, "");
  if (!raw.startsWith("?")) return NO_FILTERS;
  const p = new URLSearchParams(raw.slice(1));
  const period = p.get(KEYS.period) ?? "";
  const day = (k: string) => (DAY.test(p.get(k) ?? "") ? p.get(k)! : "");
  return {
    period: (PERIODS as string[]).includes(period) ? (period as Period) : "",
    since: day(KEYS.since),
    until: day(KEYS.until),
    user: p.get(KEYS.user) ?? "",
    category: p.get(KEYS.category) ?? "",
    status: (p.get(KEYS.status) ?? "").split(",").filter(Boolean),
    host: p.get(KEYS.host) ?? "",
    q: p.get(KEYS.q) ?? "",
  };
}

/** Fragment d'adresse de l'accueil avec ces filtres ; « # » seul sans filtre. */
export function filtersToHash(f: HistoryFilters): string {
  const p = new URLSearchParams();
  if (f.period) p.set(KEYS.period, f.period);
  if (f.period === "dates" && f.since) p.set(KEYS.since, f.since);
  if (f.period === "dates" && f.until) p.set(KEYS.until, f.until);
  if (f.user) p.set(KEYS.user, f.user);
  if (f.category) p.set(KEYS.category, f.category);
  if (f.status.length) p.set(KEYS.status, f.status.join(","));
  if (f.host.trim()) p.set(KEYS.host, f.host.trim());
  if (f.q.trim()) p.set(KEYS.q, f.q.trim());
  const s = p.toString().replace(/%2C/g, ",");
  return s ? `#?${s}` : "#";
}

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

/** Paramètres de GET /api/runs. Les périodes glissantes partent de l'heure réelle du poste : les traces
 * sont datées à l'heure réelle, même quand l'heure de référence des données est figée. */
export function apiQuery(f: HistoryFilters, now: Date = new Date()): URLSearchParams {
  const p = new URLSearchParams();
  const back = { jour: 0, "7j": 6, "30j": 29 } as Record<string, number>;
  if (f.period in back) p.set("since", isoDay(new Date(now.getTime() - (back[f.period] ?? 0) * 86_400_000)));
  if (f.period === "dates") {
    if (f.since) p.set("since", f.since);
    if (f.until) p.set("until", f.until);
  }
  if (f.user) p.set("user", f.user);
  if (f.category) p.set("category", f.category);
  if (f.status.length) p.set("status", f.status.join(","));
  if (f.host.trim()) p.set("host", f.host.trim());
  if (f.q.trim()) p.set("q", f.q.trim());
  return p;
}

export const hasFilters = (f: HistoryFilters): boolean => filtersToHash(f) !== "#";
