// Piloter les agents en cours : consigne à l'agent principal (sous la ligne de statut), budget d'un agent
// (Superviseur, depuis le tiroir), relance d'un sous-agent terminé ou arrêté avec son prompt d'origine ou
// corrigé. Chaque commande est tracée par le serveur (events.jsonl, journal d'accès).
import { useState } from "react";
import { post } from "../../api/client";
import { RefreshCw, Send } from "../../components/icons";
import type { AgentState } from "../../state/runState";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function InstructionBox({ runId }: { runId: string }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setNote(null);
    try {
      await post(`/api/runs/${runId}/instructions`, { text: text.trim() });
      setText("");
      setNote({ ok: true, text: "Consigne envoyée : l'agent principal la lira avant son prochain appel au modèle." });
    } catch (err) {
      setNote({ ok: false, text: message(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="instruction" onSubmit={send}>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={2000}
        placeholder="Une consigne pour l'agent principal : « regarde aussi db-pay-02 », « ignore les logs d'hier »…"
        aria-label="Consigne pour l'agent principal"
      />
      <button type="submit" className="btn" disabled={busy || !text.trim()}>
        <Send size={14} aria-hidden="true" />
        Envoyer
      </button>
      {note && (
        <p className={note.ok ? "muted hint" : "error"} role={note.ok ? "status" : "alert"}>
          {note.text}
        </p>
      )}
    </form>
  );
}

/** Jauge du budget d'appels d'outils ; un Superviseur la relève (+5, +10) ou fixe un plafond. */
export function BudgetControl({ runId, agent, canAdjust }: { runId: string; agent: AgentState; canAdjust: boolean }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const max = agent.maxTools;
  const ratio = max ? Math.min(1, agent.toolCalls / max) : 0;
  const level = ratio >= 1 ? "low" : ratio > 0.8 ? "mid" : "high";
  const running = agent.status === "running";
  const set = async (next: number) => {
    setError(null);
    try {
      await post(`/api/runs/${runId}/agents/${agent.id}/budget`, { max_tool_calls: next });
      setValue("");
    } catch (e) {
      setError(message(e));
    }
  };
  if (!max) return null;
  return (
    <section className="budget">
      <h3>Budget</h3>
      <p className="num">
        {agent.toolCalls} / {max} appels d'outils
      </p>
      <span className="gauge wide" data-level={level} aria-hidden="true">
        <span style={{ transform: `scaleX(${ratio})` }} />
      </span>
      {canAdjust && running && (
        <form
          className="budget-form"
          onSubmit={(e) => {
            e.preventDefault();
            const n = Number(value);
            if (Number.isInteger(n) && n >= 1) void set(n);
          }}
        >
          <button type="button" className="btn" onClick={() => set(max + 5)}>
            +5
          </button>
          <button type="button" className="btn" onClick={() => set(max + 10)}>
            +10
          </button>
          <input
            type="number"
            min={1}
            max={200}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="plafond"
            aria-label="Nouveau plafond d'appels d'outils"
          />
          <button type="submit" className="btn" disabled={!value}>
            Fixer
          </button>
          <span className="faint hint">pris en compte au prochain tour de l'agent</span>
        </form>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** Relance d'un sous-agent terminé ou arrêté : même prompt, ou prompt corrigé à la main. */
export function RestartPanel({
  runId,
  agentId,
  prompt,
  onRestarted,
}: {
  runId: string;
  agentId: string;
  prompt: string | null | undefined;
  onRestarted: (taskId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(prompt ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const restart = async () => {
    setBusy(true);
    setError(null);
    try {
      const changed = text.trim() && text.trim() !== (prompt ?? "").trim();
      const { task_id } = await post<{ task_id: string }>(`/api/runs/${runId}/agents/${agentId}/restart`, {
        prompt: changed ? text : null,
      });
      onRestarted(task_id);
    } catch (e) {
      setError(message(e));
      setBusy(false);
    }
  };
  if (!open)
    return (
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        <RefreshCw size={14} aria-hidden="true" />
        Relancer ce sous-agent…
      </button>
    );
  return (
    <section className="restart">
      <h3>Relancer ce sous-agent</h3>
      <p className="muted hint">
        Un nouveau sous-agent reprend la tâche ; son rapport est remis à l'agent principal, qui continue.
      </p>
      <textarea
        rows={8}
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label="Prompt du sous-agent relancé"
        className="mono"
      />
      <div className="restart-actions">
        <button type="button" className="btn primary" disabled={busy} onClick={restart}>
          {text.trim() === (prompt ?? "").trim() ? "Relancer avec le même prompt" : "Relancer avec ce prompt"}
        </button>
        <button type="button" className="link" onClick={() => setOpen(false)}>
          Annuler
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
