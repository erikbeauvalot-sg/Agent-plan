// Investigations en cours et dernières investigations (recherche, filtre de catégorie, « Afficher plus »).
import { useState } from "react";
import type { Category, RunRow } from "../../api/types";
import { History, LoaderCircle, Search } from "../../components/icons";
import { StateBadge } from "../../components/StateBadge";
import { fmtDate, fmtDuration, fmtTokens } from "../../lib/format";
import { legacyRunHref } from "../../lib/route";

function RunItem({ run, showUser, now }: { run: RunRow; showUser: boolean; now: number }) {
  const elapsed = run.status === "running" ? (now - Date.parse(run.started_at)) / 1000 : run.duration_s;
  return (
    <li>
      <a href={legacyRunHref(run.run_id)}>
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

interface Props {
  runs: RunRow[] | null;
  error: string | null;
  categories: Category[];
  showUser: boolean;
  now: number;
}

export function LiveRuns({ runs, showUser, now }: Omit<Props, "error" | "categories">) {
  const live = (runs ?? []).filter((r) => r.status === "running");
  if (!live.length) return null;
  return (
    <section className="card" aria-labelledby="live-title">
      <h2 id="live-title">
        <LoaderCircle size={15} className="spin" aria-hidden="true" />
        En cours
      </h2>
      <ul className="runs" aria-live="polite">
        {live.map((r) => (
          <RunItem key={r.run_id} run={r} showUser={showUser} now={now} />
        ))}
      </ul>
    </section>
  );
}

export function RecentRuns({ runs, error, categories, showUser, now }: Props) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [shown, setShown] = useState(15);
  const needle = search.trim().toLowerCase();
  const done = (runs ?? []).filter(
    (r) =>
      r.status !== "running" &&
      (!category || r.category === category) &&
      (!needle || r.question.toLowerCase().includes(needle)),
  );

  return (
    <section className="card" aria-labelledby="runs-title">
      <div className="card-head">
        <h2 id="runs-title">
          <History size={15} aria-hidden="true" />
          Dernières investigations
        </h2>
        <div className="filters">
          <input
            type="search"
            placeholder="Rechercher…"
            aria-label="Rechercher une investigation"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select aria-label="Filtrer par catégorie" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Toutes catégories</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.id}
              </option>
            ))}
          </select>
        </div>
      </div>
      {error ? (
        <p className="error">{error}</p>
      ) : runs === null ? (
        <div aria-busy="true" style={{ display: "grid", gap: 10 }}>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : done.length ? (
        <ul className="runs">
          {done.slice(0, shown).map((r) => (
            <RunItem key={r.run_id} run={r} showUser={showUser} now={now} />
          ))}
        </ul>
      ) : (
        <p className="muted">
          <Search size={14} aria-hidden="true" />{" "}
          {needle || category ? "Aucune investigation ne correspond." : "Aucune investigation pour l'instant."}
        </p>
      )}
      {done.length > shown && (
        <button type="button" className="link" onClick={() => setShown((n) => n + 30)}>
          Afficher plus
        </button>
      )}
    </section>
  );
}
