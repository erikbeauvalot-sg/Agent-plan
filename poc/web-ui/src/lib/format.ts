// Formats d'affichage : dates fr-FR sur 24 h, durées, tokens, pourcentages, libellés d'état.
import type { RunStatus } from "../api/types";

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

export function fmtDuration(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "";
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")}`;
  return `${(s / 3600).toFixed(1).replace(".", ",")} h`;
}

export function fmtTokens(n: number | null | undefined): string {
  const v = n ?? 0;
  if (v >= 1000) return `${(v / 1000).toFixed(v >= 100000 ? 0 : 1).replace(".", ",")} k`;
  return String(v);
}

export function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "–" : `${Math.round(x * 100)} %`;
}

export const STATUS_LABEL: Record<RunStatus, string> = {
  running: "en cours",
  stopping: "arrêt demandé",
  completed: "terminée",
  partial: "partielle",
  stopped: "arrêtée",
  failed: "en échec",
  needs_clarification: "précision demandée",
};

export function statusLabel(s: string): string {
  return STATUS_LABEL[s as RunStatus] ?? s;
}

export const ENDED: RunStatus[] = ["completed", "partial", "stopped", "failed"];

/** Heure UTC (HH:MM) d'une date ISO : l'heure de référence est donnée en UTC par le serveur. */
export function fmtUtc(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(11, 16);
}
