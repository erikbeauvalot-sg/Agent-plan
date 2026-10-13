// Tiroir d'un agent : modèle et tokens, prompt reçu, rapport, appels d'outils (ouverture sur l'appel cité),
// réponses du modèle, arrêt de cet agent. Échap ferme ; le focus revient sur l'élément d'origine.
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { AgentDetail } from "../../api/types";
import { Square } from "../../components/icons";
import { Markdown } from "../../components/Markdown";
import { StateBadge } from "../../components/StateBadge";
import { fmtDate } from "../../lib/format";
import type { AgentState } from "../../state/runState";
import { BudgetControl, RestartPanel } from "./Pilot";

interface Props {
  runId: string;
  agentId: string;
  focusRef?: string;
  agent: AgentState | undefined;
  canDetails: boolean;
  canStop: boolean;
  /** Ajuster le budget (Superviseur, Administrateur) d'un agent en cours. */
  canBudget: boolean;
  onStop: (agentId: string) => void;
  onRestarted: (taskId: string) => void;
  onClose: () => void;
}

const n = (v: number) => v.toLocaleString("fr-FR");

export function AgentDrawer({
  runId,
  agentId,
  focusRef,
  agent,
  canDetails,
  canStop,
  canBudget,
  onStop,
  onRestarted,
  onClose,
}: Props) {
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const origin = useRef<Element | null>(document.activeElement);

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
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      (previous as HTMLElement | null)?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    if (detail && focusRef) document.getElementById(`call-${focusRef}`)?.scrollIntoView({ block: "center" });
  }, [detail, focusRef]);

  const prompt = detail?.prompt || detail?.system_prompt;
  return (
    <aside className="drawer" role="dialog" aria-modal="false" aria-labelledby="drawer-title">
      <header className="drawer-head">
        <div>
          <h2 id="drawer-title">{agentId === "lead" ? "Agent principal" : agentId}</h2>
          {agent && <StateBadge state={agent.status} />}
        </div>
        <div className="drawer-tools">
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
      <div className="drawer-body">
        {agent && (
          <p className="muted hint">
            {agent.objective && <>{agent.objective} · </>}
            {agent.llm && <>{agent.llm} · </>}
            {n(agent.tokensIn)} tokens en entrée, {n(agent.tokensOut)} en sortie
            {agent.tokensReasoning ? `, dont ${n(agent.tokensReasoning)} de raisonnement` : ""}
            {agent.restartOf && <> · relance de {agent.restartOf}</>}
          </p>
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
        {!canDetails ? (
          <p className="muted">
            Prompts, échanges avec le modèle et appels d'outils ne sont pas visibles pour ton rôle.
          </p>
        ) : error ? (
          <p className="error">{error}</p>
        ) : !detail ? (
          <div aria-busy="true" className="stack">
            <div className="skeleton" />
            <div className="skeleton" />
          </div>
        ) : (
          <>
            {prompt && (
              <section>
                <h3>{detail.prompt ? "Prompt reçu" : "Prompt système"}</h3>
                <Markdown text={prompt} />
              </section>
            )}
            {detail.report !== null && detail.report !== undefined && (
              <section>
                <h3>Rapport</h3>
                <pre>{JSON.stringify(detail.report, null, 2)}</pre>
              </section>
            )}
            <section>
              <h3>Appels d'outils ({detail.calls.length})</h3>
              {detail.calls.length ? (
                detail.calls.map((c) => (
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
              )}
            </section>
            <section>
              <h3>Réponses du modèle ({detail.responses.length})</h3>
              {detail.responses.map((r, i) => (
                <div key={i} className="call">
                  <p className="faint hint">
                    {fmtDate(r.ts)} · {r.stop_reason}
                    {r.tool_calls.length ? ` · ${r.tool_calls.join(", ")}` : ""}
                  </p>
                  {r.text && <Markdown text={r.text} />}
                </div>
              ))}
            </section>
          </>
        )}
      </div>
    </aside>
  );
}
