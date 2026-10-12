// Investigations en cours (cartes avec mini-graphe vivant et ligne de statut) et historique filtrable
// (période, utilisateur, catégorie, statut, host, texte ; filtres en puces, gardés dans l'adresse).
import { useEffect, useState } from "react";
import type { Category, RunFacets, RunRow } from "../../api/types";
import { History, LoaderCircle, Search } from "../../components/icons";
import { MiniGraph } from "../../components/MiniGraph";
import { ChipSelect, useClosePopover } from "../../components/Popover";
import { StateBadge } from "../../components/StateBadge";
import { fmtDate, fmtDuration, fmtTokens, statusLabel } from "../../lib/format";
import { hasFilters, NO_FILTERS, PERIOD_LABEL, type HistoryFilters, type Period } from "../../lib/history";
import { runHref } from "../../lib/route";

function RunItem({ run, showUser, now }: { run: RunRow; showUser: boolean; now: number }) {
  const elapsed = run.status === "running" ? (now - Date.parse(run.started_at)) / 1000 : run.duration_s;
  return (
    <li>
      <a href={runHref(run.run_id)}>
        <span className="q">{run.question}</span>
        <span className="meta">
          <StateBadge state={run.status} />
          <span className="num">{fmtDate(run.started_at)}</span>
          {run.category && <span className="tag">{run.category}</span>}
          {run.label && run.label !== "?" && <span className="tag mono">{run.label}</span>}
          {elapsed !== null && elapsed !== undefined && <span className="num">{fmtDuration(elapsed)}</span>}
          {!!run.tokens && <span className="num">{fmtTokens(run.tokens)} tokens</span>}
          {showUser && <span>{run.user}</span>}
        </span>
      </a>
    </li>
  );
}

export function LiveRuns({ runs, showUser, now }: { runs: RunRow[]; showUser: boolean; now: number }) {
  if (!runs.length) return null;
  return (
    <section className="live-runs" aria-labelledby="live-title">
      <h2 id="live-title">
        <LoaderCircle size={15} className="spin" aria-hidden="true" />
        En cours <span className="faint num">{runs.length}</span>
      </h2>
      <ul aria-live="polite">
        {runs.map((r) => (
          <li key={r.run_id}>
            <a className="live-card" href={runHref(r.run_id)}>
              {r.live && <MiniGraph live={r.live} />}
              <span className="live-body">
                <span className="q">{r.question}</span>
                <span className="live-status">
                  <span className="pulse" aria-hidden="true" />
                  {r.live?.activity ?? "Démarrage"}
                </span>
                <span className="meta faint">
                  <span className="num">
                    depuis {fmtDuration(Math.max(0, (now - Date.parse(r.started_at)) / 1000))}
                  </span>
                  {r.category && <span className="tag">{r.category}</span>}
                  {showUser && <span>{r.user}</span>}
                </span>
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

const STATUSES = ["completed", "partial", "needs_clarification", "stopped", "failed", "running"];

function DatesForm({ filters, onChange }: { filters: HistoryFilters; onChange: (f: HistoryFilters) => void }) {
  const close = useClosePopover();
  const [since, setSince] = useState(filters.since);
  const [until, setUntil] = useState(filters.until);
  return (
    <form
      className="menu-form"
      onSubmit={(e) => {
        e.preventDefault();
        onChange({ ...filters, period: "dates", since, until });
        close();
      }}
    >
      <label>
        Du
        <input
          type="date"
          data-item=""
          value={since}
          max={until || undefined}
          onChange={(e) => setSince(e.target.value)}
        />
      </label>
      <label>
        Au
        <input
          type="date"
          data-item=""
          value={until}
          min={since || undefined}
          onChange={(e) => setUntil(e.target.value)}
        />
      </label>
      <button type="submit" className="btn" data-item="" disabled={!since && !until}>
        Appliquer
      </button>
    </form>
  );
}

const fmtDay = (d: string) => (d ? new Date(`${d}T12:00:00Z`).toLocaleDateString("fr-FR") : "…");

interface HistoryProps {
  runs: RunRow[] | null;
  error: string | null;
  more: boolean;
  onMore: () => void;
  filters: HistoryFilters;
  onFilters: (f: HistoryFilters) => void;
  facets: RunFacets | null;
  categories: Category[];
  showUser: boolean;
  me: string;
  now: number;
  title: string;
}

export function HistoryList({
  runs,
  error,
  more,
  onMore,
  filters,
  onFilters,
  facets,
  categories,
  showUser,
  me,
  now,
  title,
}: HistoryProps) {
  // La recherche texte part dans l'adresse et l'API après une courte pause de frappe.
  const [text, setText] = useState(filters.q);
  const [appliedQ, setAppliedQ] = useState(filters.q);
  if (filters.q !== appliedQ) {
    setAppliedQ(filters.q);
    setText(filters.q);
  }
  useEffect(() => {
    if (text === filters.q) return;
    const t = setTimeout(() => onFilters({ ...filters, q: text }), 300);
    return () => clearTimeout(t);
  }, [text, filters, onFilters]);

  const set = (patch: Partial<HistoryFilters>) => onFilters({ ...filters, ...patch });
  const periodDisplay =
    filters.period === "dates"
      ? `${fmtDay(filters.since)} → ${fmtDay(filters.until)}`
      : filters.period
        ? PERIOD_LABEL[filters.period]
        : "";
  const statusDisplay =
    filters.status.length > 2 ? `${filters.status.length} statuts` : filters.status.map(statusLabel).join(", ");
  const userOptions = (facets?.users ?? []).map((u) => ({ value: u, label: u === me ? `${u} (moi)` : u }));
  const categoryIds = [...new Set([...categories.map((c) => c.id), ...(facets?.categories ?? [])])];

  return (
    <section className="card" aria-labelledby="runs-title">
      <div className="card-head">
        <h2 id="runs-title">
          <History size={15} aria-hidden="true" />
          {title}
        </h2>
        <label className="search-field">
          <Search size={14} aria-hidden="true" />
          <input
            id="history-search"
            type="search"
            placeholder="Rechercher…"
            aria-label="Rechercher dans les questions"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
      </div>
      <div className="filter-chips" role="group" aria-label="Filtres de l'historique">
        <ChipSelect
          label="Période"
          display={periodDisplay}
          active={!!filters.period}
          onClear={() => set({ period: "", since: "", until: "" })}
          options={(["jour", "7j", "30j"] as Period[]).map((p) => ({ value: p, label: PERIOD_LABEL[p] }))}
          selected={[filters.period]}
          onSelect={(v) => set({ period: v as Period, since: "", until: "" })}
        >
          <DatesForm filters={filters} onChange={onFilters} />
        </ChipSelect>
        {showUser && userOptions.length > 0 && (
          <ChipSelect
            label="Utilisateur"
            display={filters.user}
            active={!!filters.user}
            onClear={() => set({ user: "" })}
            options={userOptions}
            selected={[filters.user]}
            onSelect={(v) => set({ user: v === filters.user ? "" : v })}
          />
        )}
        <ChipSelect
          label="Catégorie"
          display={filters.category}
          active={!!filters.category}
          onClear={() => set({ category: "" })}
          options={categoryIds.map((c) => ({ value: c, label: c }))}
          selected={[filters.category]}
          onSelect={(v) => set({ category: v === filters.category ? "" : v })}
        />
        <ChipSelect
          label="Statut"
          display={statusDisplay}
          multiple
          active={filters.status.length > 0}
          onClear={() => set({ status: [] })}
          options={STATUSES.map((s) => ({ value: s, label: statusLabel(s) }))}
          selected={filters.status}
          onSelect={(v) =>
            set({ status: filters.status.includes(v) ? filters.status.filter((s) => s !== v) : [...filters.status, v] })
          }
        />
        {(facets?.hosts.length ?? 0) > 0 && (
          <ChipSelect
            label="Host"
            display={filters.host}
            active={!!filters.host}
            onClear={() => set({ host: "" })}
            options={facets!.hosts.map((h) => ({ value: h, label: h }))}
            selected={[filters.host]}
            onSelect={(v) => set({ host: v === filters.host ? "" : v })}
          />
        )}
        {hasFilters(filters) && (
          <button
            type="button"
            className="link"
            onClick={() => {
              setText("");
              onFilters(NO_FILTERS);
            }}
          >
            Tout effacer
          </button>
        )}
      </div>
      {error ? (
        <p className="error" role="alert">
          L'historique n'a pas pu être chargé : {error}
        </p>
      ) : runs === null ? (
        <div aria-busy="true" className="skeleton-list">
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : runs.length ? (
        <ul className="runs">
          {runs.map((r) => (
            <RunItem key={r.run_id} run={r} showUser={showUser} now={now} />
          ))}
        </ul>
      ) : (
        <p className="muted empty">
          <Search size={14} aria-hidden="true" />{" "}
          {hasFilters(filters)
            ? "Aucune investigation ne correspond à ces filtres."
            : "Aucune investigation pour l'instant."}
        </p>
      )}
      {more && (
        <button type="button" className="link" onClick={onMore}>
          Afficher plus
        </button>
      )}
    </section>
  );
}
