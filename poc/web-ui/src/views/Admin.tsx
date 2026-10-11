// Administration, selon les droits : actions à valider, indicateurs, propositions d'évolution, configuration,
// comptes, coûts, journal d'accès.
import { useCallback, useEffect, useState } from "react";
import { api, post } from "../api/client";
import type { AccessEntry, Action, Costs, Indicators, Me, Proposal } from "../api/types";
import { ActionCard } from "../components/ActionCard";
import { fmtDate, fmtDuration, pct } from "../lib/format";
import { ConfigEditor } from "./admin/ConfigEditor";
import { Users } from "./admin/Users";

const KINDS: Record<string, string> = {
  add_examples: "ajout d'exemples",
  add_hypotheses: "ajout d'hypothèses",
  update_description: "nouvelle description",
  new_category: "nouvelle catégorie (en observation)",
  activate: "activation d'une catégorie",
};
const n = (v: number) => v.toLocaleString("fr-FR");

function useLoad<T>(enabled: boolean, path: string): [T | null, string | null, () => void] {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    if (!enabled) return;
    api<T>(path)
      .then((d) => (setData(d), setError(null)))
      .catch((e: Error) => setError(e.message));
  }, [enabled, path]);
  useEffect(() => {
    load();
  }, [load]);
  return [data, error, load];
}

function Section({ title, extra, children }: { title: string; extra?: string; children: React.ReactNode }) {
  const id = `admin-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section className="card" aria-labelledby={id}>
      <h2 id={id}>
        {title} {extra && <span className="faint">· {extra}</span>}
      </h2>
      {children}
    </section>
  );
}

const Loading = ({ error }: { error: string | null }) =>
  error ? <p className="error">{error}</p> : <div className="skeleton" aria-busy="true" />;

function ProposalCard({ p, canReview, onDecided }: { p: Proposal; canReview: boolean; onDecided: () => void }) {
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const r = p.replay;
  const replay = r
    ? `rejeu de la catégorisation : ${r.before} → ${r.after} / ${r.cases}${r.ok ? "" : " (dégradation, écartée)"}`
    : "non rejouée";
  const decide = async (accept: boolean) => {
    try {
      await post(`/api/proposals/${p.id}/decision`, { accept, comment });
      onDecided();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <article className="action-card">
      <header>
        <strong>
          {KINDS[p.kind] ?? p.kind} · {p.target}
        </strong>
        <span className="tag">{p.status}</span>
      </header>
      <p>{p.rationale}</p>
      <p className="muted hint">
        {replay}
        {p.decision && ` · ${p.status} par ${p.decision.by}${p.decision.comment ? ` : ${p.decision.comment}` : ""}`} ·
        preuves : {(p.evidence ?? []).join(", ") || "–"}
      </p>
      <details>
        <summary>Changement proposé</summary>
        <pre>{JSON.stringify(p.change, null, 2)}</pre>
      </details>
      {canReview && p.status === "pending" && (
        <div className="decide">
          <input
            placeholder="Commentaire (facultatif)"
            aria-label="Commentaire"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <button type="button" className="btn primary" onClick={() => decide(true)}>
            Accepter
          </button>
          <button type="button" className="btn" onClick={() => decide(false)}>
            Rejeter
          </button>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </article>
  );
}

export function Admin({ me }: { me: Me }) {
  const can = (p: string) => me.permissions.includes(p);
  const [actions, actionsError, loadActions] = useLoad<Action[]>(can("review"), "/api/actions");
  const [indicators, indicatorsError] = useLoad<Indicators>(can("view_indicators"), "/api/indicators");
  const [proposals, proposalsError, loadProposals] = useLoad<Proposal[]>(
    can("review") || can("view_indicators"),
    "/api/proposals",
  );
  const [costs, costsError] = useLoad<Costs>(can("view_costs"), "/api/costs");
  const [log, logError] = useLoad<AccessEntry[]>(can("view_access_log"), "/api/access-log");
  const pending = (actions ?? []).filter((a) => a.status === "proposed");

  return (
    <>
      <a href="#" className="back">
        ← Accueil
      </a>
      <header className="run-head">
        <div>
          <h1>Administration</h1>
          <p className="muted">
            Revue des actions, amélioration continue des catégories et des playbooks (<code>diagagent learn</code>),
            configuration, comptes, coûts et journal d'accès. Les validations sont réservées au Superviseur.
          </p>
        </div>
      </header>

      {can("review") && (
        <Section title="Actions proposées à valider" extra="jamais exécutées par l'agent">
          {!actions ? (
            <Loading error={actionsError} />
          ) : pending.length ? (
            <div className="actions">
              {pending.map((a) => (
                <ActionCard
                  key={`${a.run_id}-${a.id}`}
                  action={a}
                  runId={a.run_id!}
                  reviewable
                  onDecided={loadActions}
                  showRunLink
                />
              ))}
            </div>
          ) : (
            <p className="muted">Aucune action en attente.</p>
          )}
        </Section>
      )}

      {can("view_indicators") && (
        <Section title="Indicateurs par catégorie">
          {!indicators ? (
            <Loading error={indicatorsError} />
          ) : (
            <>
              <p className="muted">
                {indicators.runs} investigation(s) hors évaluation · classées autre : {pct(indicators.autre_share)}
                {Object.keys(indicators.draft_matches).length > 0 &&
                  ` · catégories en observation : ${Object.entries(indicators.draft_matches)
                    .map(([k, v]) => `${k} : ${v}`)
                    .join(", ")}`}
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Catégorie</th>
                      <th className="num">Demandes</th>
                      <th className="num">Part</th>
                      <th className="num">Corrigées</th>
                      <th>Diagnostics justes</th>
                      <th className="num">Durée moy.</th>
                      <th className="num">Appels d'outils moy.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {indicators.categories.map((c) => (
                      <tr key={c.category}>
                        <td>{c.category}</td>
                        <td className="num">{c.runs}</td>
                        <td className="num">{pct(c.share)}</td>
                        <td className="num">{pct(c.corrected_share)}</td>
                        <td>
                          {pct(c.useful_share)} <span className="faint">({c.feedback} avis)</span>
                        </td>
                        <td className="num">{fmtDuration(c.avg_duration_s)}</td>
                        <td className="num">{c.avg_tool_calls}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Section>
      )}

      {(can("review") || can("view_indicators")) && (
        <Section title="Propositions d'évolution des catégories et playbooks">
          {!proposals ? (
            <Loading error={proposalsError} />
          ) : proposals.length ? (
            <div className="actions">
              {proposals.map((p) => (
                <ProposalCard key={p.id} p={p} canReview={can("review")} onDecided={loadProposals} />
              ))}
            </div>
          ) : (
            <p className="muted">
              Aucune proposition. Lancer <code>diagagent learn</code> pour en produire.
            </p>
          )}
        </Section>
      )}

      {can("view_config") && (
        <Section title="Configuration" extra="validée avant écriture, versionnée, tracée dans le journal">
          <ConfigEditor />
        </Section>
      )}

      {can("manage_users") && (
        <Section title="Comptes" extra="les mots de passe ne sont jamais affichés">
          <Users />
        </Section>
      )}

      {can("view_costs") && (
        <Section title="Coûts" extra="tokens par jour, utilisateur et modèle">
          {!costs ? (
            <Loading error={costsError} />
          ) : (
            <>
              <p className="muted">
                Total : {costs.total.runs} investigation(s) · {n(costs.total.input_tokens)} tokens en entrée ·{" "}
                {n(costs.total.output_tokens)} en sortie
                {costs.total.reasoning_tokens ? `, dont ${n(costs.total.reasoning_tokens)} de raisonnement` : ""}
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Jour</th>
                      <th>Utilisateur</th>
                      <th>Modèle</th>
                      <th className="num">Investigations</th>
                      <th className="num">Tokens entrée</th>
                      <th className="num">Tokens sortie</th>
                    </tr>
                  </thead>
                  <tbody>
                    {costs.rows.map((r) => (
                      <tr key={`${r.day}-${r.user}-${r.model}`}>
                        <td className="num">{r.day}</td>
                        <td>{r.user}</td>
                        <td>{r.model}</td>
                        <td className="num">{r.runs}</td>
                        <td className="num">{n(r.input_tokens)}</td>
                        <td className="num">{n(r.output_tokens)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Section>
      )}

      {can("view_access_log") && (
        <Section title="Journal d'accès" extra="200 dernières entrées">
          {!log ? (
            <Loading error={logError} />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Utilisateur</th>
                    <th>Action</th>
                    <th>Détail</th>
                  </tr>
                </thead>
                <tbody>
                  {log.map((e, i) => {
                    const { ts, user, action, ...rest } = e;
                    return (
                      <tr key={i}>
                        <td className="num">{fmtDate(ts)}</td>
                        <td>{user ?? "–"}</td>
                        <td>{action}</td>
                        <td className="mono wrap">{JSON.stringify(rest)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}
    </>
  );
}
