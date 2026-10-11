// Chiffres du jour, dernières évaluations par modèle, statistiques sur 1, 7 ou 30 jours.
import type { HomeResponse, StatRow } from "../../api/types";
import { fmtDate, fmtDuration, fmtTokens, pct } from "../../lib/format";

function Rate({ rate }: { rate: number | null }) {
  if (rate === null || rate === undefined) return <>–</>;
  const level = rate >= 0.8 ? "high" : rate >= 0.5 ? "mid" : "low";
  return (
    <span className="rate">
      <span className="gauge" data-level={level} aria-hidden="true">
        <span style={{ transform: `scaleX(${rate})` }} />
      </span>
      <span className="num">{pct(rate)}</span>
    </span>
  );
}

export function TodayCard({ data, withEval }: { data: HomeResponse | null; withEval: boolean }) {
  const t = data?.activity.today;
  const byModel = t
    ? Object.entries(t.by_model)
        .map(([m, n]) => `${m} ${n}`)
        .join(" · ")
    : "";
  return (
    <section className="card" aria-labelledby="today-title">
      <h2 id="today-title">Aujourd'hui</h2>
      {!t ? (
        <div className="skeleton" aria-busy="true" />
      ) : (
        <>
          <div className="kpis">
            <div>
              <strong>{t.runs}</strong>
              <span>investigation(s)</span>
            </div>
            <div>
              <strong>{pct(t.success_rate)}</strong>
              <span>terminées avec succès</span>
            </div>
            <div>
              <strong>{fmtTokens(t.tokens)}</strong>
              <span>tokens</span>
            </div>
            <div>
              <strong>{fmtDuration(t.avg_duration_s) || "–"}</strong>
              <span>durée moyenne</span>
            </div>
          </div>
          {byModel && <p className="muted hint">{byModel}</p>}
          {!withEval && <p className="faint hint">hors évaluations</p>}
        </>
      )}
    </section>
  );
}

export function EvalsCard({ data }: { data: HomeResponse | null }) {
  const evals = data?.evals ?? [];
  return (
    <section className="card" aria-labelledby="evals-title">
      <h2 id="evals-title">Dernières évaluations</h2>
      {!data ? (
        <div className="skeleton" aria-busy="true" />
      ) : evals.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Modèles</th>
                <th className="num">Réussis</th>
                <th className="num">Durée</th>
                <th className="num">Tokens</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {evals.map((e) => (
                <tr key={e.file} title={`${e.cases_file} · ${e.file}`}>
                  <td>{e.label}</td>
                  <td className="num">
                    {e.passed}/{e.cases}
                    {e.repeat > 1 && <span className="faint"> (×{e.repeat})</span>}
                  </td>
                  <td className="num">{fmtDuration(e.duration_s)}</td>
                  <td className="num">{fmtTokens(e.tokens)}</td>
                  <td className="num">{fmtDate(e.date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">
          Aucun rapport. Lancer <code>diagagent --models &lt;profil&gt; eval</code>.
        </p>
      )}
    </section>
  );
}

function StatTable({
  rows,
  first,
  duration = false,
  tokens = false,
}: {
  rows: StatRow[];
  first: string;
  duration?: boolean;
  tokens?: boolean;
}) {
  if (!rows.length) return <p className="muted">Aucune investigation sur la période.</p>;
  // Réussite = terminée ; partiel = partielle, arrêtée ou précision demandée ; échec = en échec.
  const partial = (r: StatRow) =>
    (r.statuses.partial ?? 0) + (r.statuses.stopped ?? 0) + (r.statuses.needs_clarification ?? 0);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{first}</th>
            <th className="num">Total</th>
            <th>Réussite</th>
            <th className="num" title="partielles, arrêtées ou en attente de précision">
              Part.
            </th>
            <th className="num" title="échecs">
              Éch.
            </th>
            {duration && <th className="num">Durée</th>}
            {tokens && <th className="num">Tokens</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <td>{r.name === "?" ? <span className="faint">sans catégorie</span> : r.name}</td>
              <td className="num">{r.runs}</td>
              <td>
                <Rate rate={r.success_rate} />
              </td>
              <td className="num">{partial(r)}</td>
              <td className="num">{r.statuses.failed ?? 0}</td>
              {duration && <td className="num">{fmtDuration(r.avg_duration_s)}</td>}
              {tokens && <td className="num">{fmtTokens(r.tokens)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface StatsProps {
  data: HomeResponse | null;
  days: number;
  withEval: boolean;
  onDays: (d: number) => void;
  onWithEval: (v: boolean) => void;
}

export function StatsCard({ data, days, withEval, onDays, onWithEval }: StatsProps) {
  const p = data?.activity.period;
  return (
    <section className="card" aria-labelledby="stats-title">
      <div className="card-head">
        <h2 id="stats-title">Statistiques</h2>
        <div className="filters">
          <select aria-label="Période" value={days} onChange={(e) => onDays(Number(e.target.value))}>
            <option value={1}>aujourd'hui</option>
            <option value={7}>7 jours</option>
            <option value={30}>30 jours</option>
          </select>
          <label className="check">
            <input type="checkbox" checked={withEval} onChange={(e) => onWithEval(e.target.checked)} /> inclure les
            évaluations
          </label>
        </div>
      </div>
      {!data || !p ? (
        <div className="skeleton" aria-busy="true" />
      ) : (
        <>
          <p className="muted">
            {p.runs} investigation(s) terminée(s) · {pct(p.success_rate)} avec succès · {fmtTokens(p.tokens)} tokens
            {withEval ? "" : " · hors évaluations"}
          </p>
          <div className="stats-grid">
            <div>
              <h3>Par catégorie</h3>
              <StatTable rows={data.activity.categories} first="Catégorie" duration />
            </div>
            <div>
              <h3>Par agent</h3>
              <StatTable rows={data.activity.agents} first="Agent" />
            </div>
            <div>
              <h3>Par modèle</h3>
              <StatTable rows={data.activity.models} first="Modèles" duration tokens />
            </div>
          </div>
        </>
      )}
    </section>
  );
}
