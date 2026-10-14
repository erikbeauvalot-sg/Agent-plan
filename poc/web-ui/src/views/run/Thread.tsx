// Fil de conversation : les questions précédentes et leur synthèse au-dessus de l'investigation affichée,
// chacune avec son graphe repliable ; sous la réponse, les questions de suivi déjà posées et le champ pour
// en poser une nouvelle (nouvelle investigation liée, qui reprend ce contexte).
import { useState } from "react";
import { post } from "../../api/client";
import type { RunStatus, ThreadTurn } from "../../api/types";
import { MessageSquare, Send } from "../../components/icons";
import { Markdown } from "../../components/Markdown";
import { StateBadge } from "../../components/StateBadge";
import { fmtDate } from "../../lib/format";
import { parseAnswer } from "../../lib/answer";
import { runHref } from "../../lib/route";
import { useRunStream } from "../../state/useRunStream";
import { AgentGraph } from "./AgentGraph";

/** Graphe d'une investigation précédente, chargé seulement quand on déplie. */
function TurnGraph({ runId }: { runId: string }) {
  const { state } = useRunStream(runId, () => {});
  return (
    <AgentGraph
      run={state}
      now={state.lastTs ?? 0}
      fromServer
      liveSince={null}
      hover={null}
      onHover={() => {}}
      onOpen={() => {
        location.hash = runId;
      }}
    />
  );
}

function Turn({ turn }: { turn: ThreadTurn }) {
  const [graph, setGraph] = useState(false);
  const summary = turn.analysis ? parseAnswer(turn.analysis).summary : "";
  return (
    <li className="turn">
      <p className="turn-q">
        <MessageSquare size={14} aria-hidden="true" />
        <a href={runHref(turn.run_id)}>{turn.question}</a>
        <StateBadge state={turn.status as RunStatus} />
        <span className="faint num">
          {fmtDate(turn.started_at)} · {turn.user}
        </span>
      </p>
      {summary ? <Markdown text={summary} className="turn-a" /> : <p className="muted">Pas de synthèse enregistrée.</p>}
      <details onToggle={(e) => setGraph((e.currentTarget as HTMLDetailsElement).open)}>
        <summary>Graphe d'investigation</summary>
        {graph && <TurnGraph runId={turn.run_id} />}
      </details>
    </li>
  );
}

export function ThreadEarlier({ turns }: { turns: ThreadTurn[] }) {
  if (!turns.length) return null;
  return (
    <section className="thread" aria-label="Questions précédentes de la conversation">
      <ol>
        {turns.map((t) => (
          <Turn key={t.run_id} turn={t} />
        ))}
      </ol>
    </section>
  );
}

interface FollowUpProps {
  runId: string;
  later: ThreadTurn[];
  canAsk: boolean;
  ended: boolean;
  models: string | null;
  sources: string | null;
}

export function FollowUp({ runId, later, canAsk, ended, models, sources }: FollowUpProps) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ask = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!question.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await post<{ run_id: string }>("/api/runs", {
        question: question.trim(),
        follow_up_of: runId,
        models,
        sources,
        category: null,
        rerun_of: null,
      });
      location.hash = run_id;
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };
  if (!later.length && !(canAsk && ended)) return null;
  return (
    <section className="follow-up" aria-labelledby="follow-up-title">
      <h3 id="follow-up-title">Suite de la conversation</h3>
      {later.length > 0 && (
        <ul className="later">
          {later.map((t) => (
            <li key={t.run_id}>
              <MessageSquare size={13} aria-hidden="true" />
              <a href={runHref(t.run_id)}>{t.question}</a> <StateBadge state={t.status as RunStatus} />
            </li>
          ))}
        </ul>
      )}
      {canAsk && ended && (
        <form onSubmit={ask}>
          <textarea
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void ask();
              }
            }}
            placeholder="Poser une question de suivi : « et sur db-pay-02 ? », « quelle action en premier ? »…"
            aria-label="Question de suivi"
          />
          <button type="submit" className="btn primary" disabled={busy || !question.trim()}>
            <Send size={14} aria-hidden="true" />
            {busy ? "Lancement…" : "Poser la question de suivi"}
          </button>
          <p className="faint hint">
            Nouvelle investigation liée à celle-ci : l'agent principal reçoit la question, la synthèse et les rapports
            des sous-agents, et ne réinterroge les sources que pour ce qui manque.
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
