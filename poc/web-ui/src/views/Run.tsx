// Investigation : voir les agents travailler en direct, comprendre la réponse et ses preuves, décider.
import { useCallback, useEffect, useState } from "react";
import { api, post } from "../api/client";
import type { Category, FullRun, Me } from "../api/types";
import { ActionCard } from "../components/ActionCard";
import { useConfirm } from "../components/Confirm";
import { evidenceAgent, Markdown } from "../components/Markdown";
import { StateBadge } from "../components/StateBadge";
import { setCurrentRun } from "../lib/currentRun";
import { ENDED, fmtDate } from "../lib/format";
import { liveUsage } from "../state/runState";
import { useRunStream } from "../state/useRunStream";
import { AgentDrawer } from "./run/AgentDrawer";
import { AgentGraph } from "./run/AgentGraph";
import { Answer } from "./run/Answer";
import { ActivityFeed, StatusLine } from "./run/LiveActivity";
import { InstructionBox } from "./run/Pilot";
import { CategoryBar, FeedbackForm, PrecisionForm } from "./run/RunPanels";
import { Timeline } from "./run/Timeline";

const n = (v: number | undefined) => (v ?? 0).toLocaleString("fr-FR");
const ROLE: Record<string, string> = { lead: "principal", classifier: "classifieur" };

export function Run({ me, runId }: { me: Me; runId: string }) {
  const [data, setData] = useState<FullRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [drawer, setDrawer] = useState<{ agentId: string; ref?: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmElement, confirm] = useConfirm();
  const [now, setNow] = useState(() => Date.now());
  const [openedAt] = useState(() => Date.now());
  const [hover, setHover] = useState<string | null>(null);
  // La synthèse n'est révélée en cascade que si on a vu l'investigation tourner.
  const [sawRunning, setSawRunning] = useState(false);
  const can = (p: string) => me.permissions.includes(p);

  const load = useCallback(
    () =>
      api<FullRun>(`/api/runs/${runId}`)
        .then((d) => (setData(d), setError(null)))
        .catch((e: Error) => setError(e.message)),
    [runId],
  );
  useEffect(() => {
    load();
    api<Category[]>("/api/categories")
      .then(setCategories)
      .catch(() => setCategories([]));
  }, [load]);

  const { state: run, status: stream } = useRunStream(runId, load);
  const ended = stream === "ended";

  // Titre court et état dans la barre du haut, le temps que la vue est affichée.
  const question = data?.manifest.question;
  const runStatus = data?.manifest.status;
  useEffect(() => {
    if (question && runStatus) setCurrentRun({ question, status: runStatus });
  }, [question, runStatus]);
  useEffect(() => () => setCurrentRun(null), []);

  // Catégorie, action proposée… : la synthèse se relit, regroupée sur 300 ms.
  useEffect(() => {
    if (!run.summaryVersion) return;
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
  }, [run.summaryVersion, load]);

  // Horloge des durées et des signaux tant que l'investigation tourne.
  useEffect(() => {
    if (ended) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [ended]);

  const openAgent = useCallback((agentId: string, ref?: string) => setDrawer({ agentId, ref }), []);
  const openEvidence = useCallback(
    (ref: string) => openAgent(ref.startsWith("lead") ? "lead" : (ref.split("/")[1] ?? "lead"), ref),
    [openAgent],
  );
  const closeDrawer = useCallback(() => setDrawer(null), []);

  if (error) return <p className="error card">{error}</p>;
  if (!data)
    return (
      <div className="card" aria-busy="true">
        <div className="skeleton" />
        <div className="skeleton" />
      </div>
    );

  const m = data.manifest;
  if (m.status === "running" && !sawRunning) setSawRunning(true);
  const isOwner = m.user === me.login;
  const fromServer = m.signals === "orchestrator" || run.serverSignals;
  // Animations seulement pour ce qui arrive en direct ; un rattrapage s'affiche sans mouvement.
  const liveSince = !ended && run.lastTs !== null && run.lastTs > openedAt - 5000 ? openedAt - 5000 : null;
  const clock = ended ? (run.lastTs ?? now) : Math.max(now, run.lastTs ?? 0);
  const usage =
    ended && m.usage
      ? m.usage
      : (() => {
          const u = liveUsage(run);
          return { input_tokens: u.tokensIn, output_tokens: u.tokensOut, reasoning_tokens: u.tokensReasoning };
        })();
  const total = (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0);
  const roles = Object.entries(m.models ?? {}).map(([r, x]) => `${ROLE[r] ?? r} ${x.provider} / ${x.model}`);
  const shifted = m.reference_time && Math.abs(Date.parse(m.reference_time) - Date.parse(m.started_at)) > 60_000;
  const sourcesLabel = (m.sources ?? []).map((s) => (s === "demo" ? "démo" : s)).join(" + ");

  const start = async (body: { question: string; category?: string | null }) => {
    const { run_id } = await post<{ run_id: string }>("/api/runs", {
      models: m.models_profile ?? null,
      sources: m.sources?.length ? m.sources.join(",") : null,
      rerun_of: m.run_id,
      category: null,
      ...body,
    });
    location.hash = run_id;
  };

  const kill = async () => {
    const ok = await confirm({
      title: "Arrêt immédiat de l'investigation ?",
      body: "Tous les agents sont coupés tout de suite, sans synthèse : à réserver à un agent qui surcharge une source. Pour garder une synthèse partielle, utilise plutôt « Arrêter l'investigation ».",
      confirm: "Couper immédiatement",
      danger: true,
    });
    if (!ok) return;
    setActionError(null);
    try {
      await post(`/api/runs/${runId}/agents/lead/stop?kill=true`);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const stop = async (agentId: string) => {
    const whole = agentId === "lead";
    const ok = await confirm({
      title: whole ? "Arrêter l'investigation ?" : `Arrêter l'agent ${agentId} ?`,
      body: whole
        ? "Tous les agents s'arrêtent ; l'agent principal rend une synthèse partielle, marquée comme telle."
        : "Cet agent rend un rapport partiel avec ce qu'il a déjà trouvé ; les autres continuent.",
      confirm: whole ? "Arrêter l'investigation" : "Arrêter cet agent",
      danger: true,
    });
    if (!ok) return;
    setActionError(null);
    try {
      await post(`/api/runs/${runId}/agents/${agentId}/stop`);
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const share = async () => {
    setActionError(null);
    try {
      await post(`/api/runs/${runId}/share`, { shared: !m.shared });
      load();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const answerCard = (
    <section className="card answer-card" aria-labelledby="answer-title">
      <h2 id="answer-title">Réponse</h2>
      <Answer
        analysis={data.analysis}
        draft={run.draft}
        ended={ended}
        reveal={sawRunning}
        onEvidence={openEvidence}
        onEvidenceHover={(ref) => setHover(ref ? evidenceAgent(ref) : null)}
      />
      <FeedbackForm manifest={m} canGive={isOwner || can("stop_all")} onSent={load} />
      {m.status === "needs_clarification" && can("ask") && (
        <PrecisionForm onRelaunch={(p) => start({ question: `${m.question}\nPrécision : ${p}` })} />
      )}
      {data.plan && (
        <details>
          <summary>Plan d'investigation</summary>
          <Markdown text={data.plan} />
        </details>
      )}
    </section>
  );

  return (
    <>
      <a href="#" className="back">
        ← Accueil
      </a>
      <header className="run-head">
        <div className="run-title">
          <h1>{m.question}</h1>
          <p className="muted hint">
            <span className="num">{fmtDate(m.started_at)}</span> · {m.user} · <span className="mono">{runId}</span>
            {sourcesLabel && ` · données ${sourcesLabel}`}
            {shifted && ` · heure de référence ${fmtDate(m.reference_time)}`}
            {m.rerun_of && (
              <>
                {" "}
                · relance de{" "}
                <a href={`#${m.rerun_of}`} className="mono">
                  {m.rerun_of}
                </a>
              </>
            )}
          </p>
          <p className="muted hint num">
            {roles.length ? `LLM : ${roles.join(" · ")} — ` : ""}
            {n(total)} tokens ({n(usage.input_tokens)} en entrée, {n(usage.output_tokens)} en sortie
            {usage.reasoning_tokens ? `, dont ${n(usage.reasoning_tokens)} de raisonnement` : ""})
          </p>
          <CategoryBar
            manifest={m}
            categories={categories}
            canCorrect={isOwner || can("stop_all")}
            canAsk={can("ask")}
            onChanged={load}
            onRerun={(category) => start({ question: m.question, category })}
          />
        </div>
        <div className="run-actions">
          {m.shared && <span className="tag">partagée</span>}
          <StateBadge state={m.status} />
          {stream === "reconnecting" && <span className="faint hint">Reconnexion…</span>}
          {data.can_share && (
            <button type="button" className="btn" onClick={share}>
              {m.shared ? "Ne plus partager" : "Partager"}
            </button>
          )}
          {can("ask") && (
            <a
              className="btn"
              href={`#relance/${runId}`}
              title="Nouvelle demande préremplie, à lancer après avoir changé les options"
            >
              Relancer…
            </a>
          )}
          {data.can_stop && (
            <button
              type="button"
              className="btn danger"
              onClick={() => stop("lead")}
              title="Tous les agents s'arrêtent ; l'agent principal rend une synthèse partielle"
            >
              Arrêter l'investigation
            </button>
          )}
          {data.can_stop && can("kill") && (
            <button
              type="button"
              className="btn ghost danger-text"
              onClick={kill}
              title="Coupure sans synthèse, quand un agent surcharge une source"
            >
              Arrêt immédiat
            </button>
          )}
        </div>
      </header>
      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}

      <StatusLine run={run} ended={ended} />
      {data.can_stop && !ended && <InstructionBox runId={runId} />}
      {data.analysis && answerCard}

      <section className="card" aria-labelledby="graph-title">
        <h2 id="graph-title">Graphe d'investigation</h2>
        <AgentGraph
          run={run}
          now={clock}
          onOpen={openAgent}
          fromServer={fromServer}
          liveSince={liveSince}
          hover={hover}
          onHover={setHover}
        />
      </section>

      <div className="run-grid">
        <section className="card" aria-labelledby="timeline-title">
          <h2 id="timeline-title">Chronologie</h2>
          <Timeline
            run={run}
            now={clock}
            ended={ended}
            onOpen={openAgent}
            liveSince={liveSince}
            hover={hover}
            onHover={setHover}
          />
        </section>
        <section className="card" aria-labelledby="feed-title">
          <h2 id="feed-title">Fil d'activité</h2>
          <ActivityFeed run={run} onOpen={openAgent} />
        </section>
      </div>

      {data.actions.length > 0 && (
        <section className="card" aria-labelledby="actions-title">
          <h2 id="actions-title">
            Actions proposées <span className="faint">· jamais exécutées par l'agent</span>
          </h2>
          <div className="actions">
            {data.actions.map((a) => (
              <ActionCard
                key={a.id}
                action={a}
                runId={runId}
                reviewable={ENDED.includes(m.status) && can("review")}
                onDecided={load}
                onEvidence={openEvidence}
                onEvidenceHover={(ref) => setHover(ref ? evidenceAgent(ref) : null)}
              />
            ))}
          </div>
        </section>
      )}

      {!data.analysis && answerCard}

      {drawer && (
        <AgentDrawer
          key={`${drawer.agentId}-${drawer.ref ?? ""}`}
          runId={runId}
          agentId={drawer.agentId}
          focusRef={drawer.ref}
          agent={run.agents[drawer.agentId]}
          canDetails={data.can_details}
          canStop={data.can_stop}
          canBudget={can("adjust_budget")}
          onStop={stop}
          onRestarted={(taskId) => setDrawer({ agentId: taskId })}
          onNavigate={(id) => setDrawer({ agentId: id })}
          order={run.order}
          onClose={closeDrawer}
        />
      )}
      {confirmElement}
    </>
  );
}
