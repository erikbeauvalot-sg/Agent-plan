// Administration, selon les droits : actions à valider, indicateurs, propositions d'évolution, configuration,
// comptes, coûts, journal d'accès.
import { useCallback, useEffect, useState } from "react";
import { api, post } from "../api/client";
import type { AccessEntry, Action, Costs, Indicators, Me, Proposal } from "../api/types";
import { ActionCard } from "../components/ActionCard";
import { SortTable, type Column } from "../components/SortTable";
import { TabPanel, Tabs, type Tab } from "../components/Tabs";
import { fmtDate, fmtDuration, pct } from "../lib/format";
import { stored } from "../lib/storage";
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
  const openProposals = (proposals ?? []).filter((p) => p.status === "proposed").length;

  // Onglets selon les droits ; le dernier ouvert est retenu par le navigateur.
  const tabs: Tab[] = [
    ...(can("review") ? [{ id: "actions", label: "À valider", badge: actions ? pending.length : null }] : []),
    ...(can("review") || can("view_indicators")
      ? [{ id: "proposals", label: "Propositions", badge: proposals ? openProposals : null }]
      : []),
    ...(can("view_indicators") ? [{ id: "indicators", label: "Indicateurs" }] : []),
    ...(can("view_config") ? [{ id: "config", label: "Configuration" }] : []),
    ...(can("manage_users") ? [{ id: "users", label: "Comptes" }] : []),
    ...(can("view_costs") ? [{ id: "costs", label: "Coûts" }] : []),
    ...(can("view_access_log") ? [{ id: "log", label: "Journal" }] : []),
  ];
  const [chosen, setChosen] = useState(() => stored.get("admin-tab") ?? "");
  const tab = tabs.some((t) => t.id === chosen) ? chosen : (tabs[0]?.id ?? "");
  const choose = (id: string) => {
    setChosen(id);
    stored.set("admin-tab", id);
  };
  const show = (id: string) => tab === id;

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
      {!tabs.length && <p className="muted">Aucune fonction d'administration pour ton rôle.</p>}
      <Tabs tabs={tabs} active={tab} onChange={choose} label="Sections de l'administration" idPrefix="admin" />
      <TabPanel idPrefix="admin" id={tab}>
        <AdminPanels
          show={show}
          can={can}
          actions={actions}
          actionsError={actionsError}
          loadActions={loadActions}
          pending={pending}
          indicators={indicators}
          indicatorsError={indicatorsError}
          proposals={proposals}
          proposalsError={proposalsError}
          loadProposals={loadProposals}
          costs={costs}
          costsError={costsError}
          log={log}
          logError={logError}
        />
      </TabPanel>
    </>
  );
}

interface PanelsProps {
  show: (id: string) => boolean;
  can: (p: string) => boolean;
  actions: Action[] | null;
  actionsError: string | null;
  loadActions: () => void;
  pending: Action[];
  indicators: Indicators | null;
  indicatorsError: string | null;
  proposals: Proposal[] | null;
  proposalsError: string | null;
  loadProposals: () => void;
  costs: Costs | null;
  costsError: string | null;
  log: AccessEntry[] | null;
  logError: string | null;
}

type CostRow = Costs["rows"][number];
type CategoryRow = Indicators["categories"][number];

const CATEGORY_COLUMNS: Column<CategoryRow>[] = [
  { key: "category", label: "Catégorie", value: (c) => c.category },
  { key: "runs", label: "Demandes", num: true, value: (c) => c.runs },
  { key: "share", label: "Part", num: true, value: (c) => c.share, render: (c) => pct(c.share) },
  {
    key: "corrected",
    label: "Corrigées",
    num: true,
    value: (c) => c.corrected_share,
    render: (c) => pct(c.corrected_share),
  },
  {
    key: "useful",
    label: "Diagnostics justes",
    num: true,
    value: (c) => c.useful_share,
    render: (c) => (
      <>
        {pct(c.useful_share)} <span className="faint">({c.feedback} avis)</span>
      </>
    ),
  },
  {
    key: "duration",
    label: "Durée moy.",
    num: true,
    value: (c) => c.avg_duration_s,
    render: (c) => fmtDuration(c.avg_duration_s),
  },
  { key: "tools", label: "Appels d'outils moy.", num: true, value: (c) => c.avg_tool_calls },
];

const COST_COLUMNS: Column<CostRow>[] = [
  { key: "day", label: "Jour", value: (r) => r.day },
  { key: "user", label: "Utilisateur", value: (r) => r.user },
  { key: "model", label: "Modèle", value: (r) => r.model },
  { key: "runs", label: "Investigations", num: true, value: (r) => r.runs },
  { key: "in", label: "Tokens entrée", num: true, value: (r) => r.input_tokens, render: (r) => n(r.input_tokens) },
  { key: "out", label: "Tokens sortie", num: true, value: (r) => r.output_tokens, render: (r) => n(r.output_tokens) },
];

const LOG_COLUMNS: Column<AccessEntry>[] = [
  { key: "ts", label: "Date", value: (e) => e.ts, render: (e) => <span className="num">{fmtDate(e.ts)}</span> },
  { key: "user", label: "Utilisateur", value: (e) => e.user ?? "" },
  { key: "action", label: "Action", value: (e) => e.action },
  {
    key: "detail",
    label: "Détail",
    value: (e) => {
      const { ts: _ts, user: _user, action: _action, ...rest } = e;
      void [_ts, _user, _action];
      return JSON.stringify(rest);
    },
    render: (e) => {
      const { ts: _ts, user: _user, action: _action, ...rest } = e;
      void [_ts, _user, _action];
      return <span className="mono wrap">{JSON.stringify(rest)}</span>;
    },
  },
];

function AdminPanels(p: PanelsProps) {
  const { show, can, actions, actionsError, loadActions, pending, indicators, indicatorsError } = p;
  const { proposals, proposalsError, loadProposals, costs, costsError, log, logError } = p;
  return (
    <>
      {show("actions") && (
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

      {show("indicators") && (
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
              <SortTable
                rows={indicators.categories}
                columns={CATEGORY_COLUMNS}
                rowKey={(c) => c.category}
                initial={{ key: "runs", dir: -1 }}
                caption="Indicateurs par catégorie"
              />
            </>
          )}
        </Section>
      )}

      {show("proposals") && (
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

      {show("config") && (
        <Section title="Configuration" extra="validée avant écriture, versionnée, tracée dans le journal">
          <ConfigEditor />
        </Section>
      )}

      {show("users") && (
        <Section title="Comptes" extra="les mots de passe ne sont jamais affichés">
          <Users />
        </Section>
      )}

      {show("costs") && (
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
              <SortTable
                rows={costs.rows}
                columns={COST_COLUMNS}
                rowKey={(r) => `${r.day}-${r.user}-${r.model}`}
                initial={{ key: "day", dir: -1 }}
                caption="Coûts par jour, utilisateur et modèle"
              />
            </>
          )}
        </Section>
      )}

      {show("log") && (
        <Section title="Journal d'accès" extra="200 dernières entrées">
          {!log ? (
            <Loading error={logError} />
          ) : (
            <SortTable
              rows={log}
              columns={LOG_COLUMNS}
              rowKey={(e, i) => `${e.ts}-${i}`}
              initial={{ key: "ts", dir: -1 }}
              caption="Journal d'accès"
            />
          )}
        </Section>
      )}
    </>
  );
}
