// Tiroir d'un agent, en onglets : résumé (objectif, modèle, jauges, rapport, relance), appels d'outils (ouverture
// sur l'appel cité), échanges avec le modèle, prompt. Agent précédent ou suivant par les flèches de l'en-tête ou
// les touches [ et ] ; Échap ferme ; le focus revient sur l'élément d'origine.
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { AgentDetail } from "../../api/types";
import { ChevronLeft, ChevronRight, Square } from "../../components/icons";
import { Markdown } from "../../components/Markdown";
import { StateBadge } from "../../components/StateBadge";
import { TabPanel, Tabs } from "../../components/Tabs";
import { fmtDate, fmtTokens } from "../../lib/format";
import type { AgentState } from "../../state/runState";
import { BudgetControl, RestartPanel } from "./Pilot";

interface Props {
  runId: string;
  agentId: string;
  focusRef?: string;
  agent: AgentState | undefined;
  /** Ordre des agents, pour passer au précédent ou au suivant. */
  order: string[];
  canDetails: boolean;
  canStop: boolean;
  /** Ajuster le budget (Superviseur, Administrateur) d'un agent en cours. */
  canBudget: boolean;
  onStop: (agentId: string) => void;
  onRestarted: (taskId: string) => void;
  onNavigate: (agentId: string) => void;
  onClose: () => void;
}

const n = (v: number) => v.toLocaleString("fr-FR");
const typing = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

export function AgentDrawer({
  runId,
  agentId,
  focusRef,
  agent,
  order,
  canDetails,
  canStop,
  canBudget,
  onStop,
  onRestarted,
  onNavigate,
  onClose,
}: Props) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState(focusRef ? "calls" : "summary");
  const closeRef = useRef<HTMLButtonElement>(null);
  const origin = useRef<Element | null>(document.activeElement);
  const index = order.indexOf(agentId);
  const prev = index > 0 ? order[index - 1] : undefined;
  const next = index >= 0 && index < order.length - 1 ? order[index + 1] : undefined;

  useEffect(() => {
    if (!canDetails) return;
    let cancelled = false;
    api<AgentDetail>(`/api/runs/${runId}/agents/${agentId}`)
      .then((d) => !cancelled && (setDetail(d), setError(null)))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [runId, agentId, canDetails]);

  useEffect(() => {
    const previous = origin.current;
    closeRef.current?.focus();
    return () => {
      (previous as HTMLElement | null)?.focus?.();
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (!typing(e.target) && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (e.key === "[" && prev) onNavigate(prev);
        if (e.key === "]" && next) onNavigate(next);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onNavigate, prev, next]);

  useEffect(() => {
    if (detail && focusRef && tab === "calls")
      document.getElementById(`call-${focusRef}`)?.scrollIntoView({ block: "center" });
  }, [detail, focusRef, tab]);

  const label = (id: string) => (id === "lead" ? "Agent principal" : id.split("-")[0]);
  const tabs = [
    { id: "summary", label: "Résumé" },
    ...(canDetails
      ? [
          { id: "calls", label: "Appels d'outils", badge: detail?.calls.length ?? null },
          { id: "exchanges", label: "Échanges", badge: detail?.responses.length ?? null },
          { id: "prompt", label: "Prompt" },
        ]
      : []),
  ];
  const prompt = detail?.prompt || detail?.system_prompt;
  const loading = !canDetails ? null : error ? (
    <p className="error">{error}</p>
  ) : !detail ? (
    <div aria-busy="true" className="stack">
      <div className="skeleton" />
      <div className="skeleton" />
    </div>
  ) : null;

  return (
    <aside className="drawer" role="dialog" aria-modal="false" aria-labelledby="drawer-title">
      <header className="drawer-head">
        <div>
          <h2 id="drawer-title">{agentId === "lead" ? "Agent principal" : agentId}</h2>
          {agent && <StateBadge state={agent.status} />}
        </div>
        <div className="drawer-tools">
          <span className="drawer-nav">
            <button
              type="button"
              className="btn ghost icon"
              disabled={!prev}
              onClick={() => prev && onNavigate(prev)}
              aria-label={prev ? `Agent précédent : ${label(prev)}` : "Pas d'agent précédent"}
              title="Agent précédent ([)"
            >
              <ChevronLeft size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="btn ghost icon"
              disabled={!next}
              onClick={() => next && onNavigate(next)}
              aria-label={next ? `Agent suivant : ${label(next)}` : "Pas d'agent suivant"}
              title="Agent suivant (])"
            >
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </span>
          {canStop && agent?.status === "running" && (
            <button type="button" className="btn danger" onClick={() => onStop(agentId)}>
              <Square size={14} aria-hidden="true" />
              Arrêter cet agent
            </button>
          )}
          <button
            ref={closeRef}
            type="button"
            className="btn ghost icon"
            onClick={onClose}
            aria-label="Fermer le détail"
          >
            ✕
          </button>
        </div>
      </header>
      <Tabs tabs={tabs} active={tab} onChange={setTab} label="Détail de l'agent" idPrefix="drawer" />
      <div className="drawer-body">
        <TabPanel idPrefix="drawer" id={tab}>
          {tab === "summary" && (
            <>
              {agent && (
                <dl className="agent-facts">
                  {agent.objective && (
                    <>
                      <dt>Objectif</dt>
                      <dd>{agent.objective}</dd>
                    </>
                  )}
                  {agent.llm && (
                    <>
                      <dt>Modèle</dt>
                      <dd className="mono">{agent.llm}</dd>
                    </>
                  )}
                  <dt>Tokens</dt>
                  <dd className="num">
                    {fmtTokens(agent.tokens)} : {n(agent.tokensIn)} en entrée, {n(agent.tokensOut)} en sortie
                    {agent.tokensReasoning ? `, dont ${n(agent.tokensReasoning)} de raisonnement` : ""}
                  </dd>
                  {agent.restartOf && (
                    <>
                      <dt>Relance de</dt>
                      <dd>
                        <button type="button" className="link mono" onClick={() => onNavigate(agent.restartOf!)}>
                          {agent.restartOf}
                        </button>
                      </dd>
                    </>
                  )}
                </dl>
              )}
              {agent && <BudgetControl runId={runId} agent={agent} canAdjust={canBudget && canStop} />}
              {agent && canStop && agentId !== "lead" && agent.status !== "running" && agent.status !== "stopping" && (
                <RestartPanel
                  key={detail?.prompt ?? ""}
                  runId={runId}
                  agentId={agentId}
                  prompt={detail?.prompt}
                  onRestarted={onRestarted}
                />
              )}
              {!canDetails && (
                <p className="muted">
                  Prompts, échanges avec le modèle et appels d'outils ne sont pas visibles pour ton rôle.
                </p>
              )}
              {loading}
              {detail?.report !== null && detail?.report !== undefined && (
                <section>
                  <h3>Rapport</h3>
                  <pre>{JSON.stringify(detail.report, null, 2)}</pre>
                </section>
              )}
            </>
          )}
          {tab === "calls" &&
            (loading ??
              (detail!.calls.length ? (
                detail!.calls.map((c) => (
                  <details
                    key={c.ref}
                    id={`call-${c.ref}`}
                    className={`call ${c.is_error ? "error" : ""}`}
                    open={c.ref === focusRef}
                  >
                    <summary>
                      <span>
                        {c.tool}
                        {c.is_error ? " · erreur" : ""}
                      </span>
                      <span className="faint num">
                        {String(c.duration_s).replace(".", ",")} s · {c.ref}
                      </span>
                    </summary>
                    <pre>{JSON.stringify(c.input, null, 2)}</pre>
                    <pre>{c.output}</pre>
                  </details>
                ))
              ) : (
                <p className="muted">Aucun appel.</p>
              )))}
          {tab === "exchanges" &&
            (loading ??
              (detail!.responses.length ? (
                detail!.responses.map((r, i) => (
                  <div key={i} className="call">
                    <p className="faint hint">
                      {fmtDate(r.ts)} · {r.stop_reason}
                      {r.tool_calls.length ? ` · ${r.tool_calls.join(", ")}` : ""}
                    </p>
                    {r.text && <Markdown text={r.text} />}
                  </div>
                ))
              ) : (
                <p className="muted">Aucun échange.</p>
              )))}
          {tab === "prompt" &&
            (loading ??
              (prompt ? (
                <section>
                  <h3>{detail!.prompt ? "Prompt reçu" : "Prompt système"}</h3>
                  <Markdown text={prompt} />
                </section>
              ) : (
                <p className="muted">Pas de prompt enregistré.</p>
              )))}
        </TabPanel>
      </div>
    </aside>
  );
}
