// Action proposée par l'agent, jamais exécutée : risque, justification, preuves, procédure et retour arrière,
// décision d'un Superviseur (valider ou rejeter, avec commentaire).
import { useState } from "react";
import { post } from "../api/client";
import type { Action } from "../api/types";
import { Check, Copy } from "./icons";
import { Evidence, Markdown, type OnEvidence, type OnEvidenceHover } from "./Markdown";

const STATUS: Record<string, string> = {
  proposed: "à valider",
  validated: "validée, non exécutée",
  rejected: "rejetée",
};

/** Une preuve est en principe un query_ref ; certains modèles écrivent un objet ({fact, task_id}…) : on en
 * garde un texte lisible plutôt que de faire échouer l'affichage. */
export function evidenceText(e: unknown): string {
  if (typeof e === "string") return e;
  if (e && typeof e === "object") {
    const o = e as Record<string, unknown>;
    const ref = o.query_ref ?? o.ref ?? o.evidence;
    if (typeof ref === "string") return ref;
    return [o.task_id, o.fact].filter((x) => typeof x === "string").join(" : ") || JSON.stringify(e);
  }
  return String(e);
}

interface Props {
  action: Action;
  runId: string;
  reviewable: boolean;
  onDecided: () => void;
  onEvidence?: OnEvidence;
  onEvidenceHover?: OnEvidenceHover;
  showRunLink?: boolean;
}

export function ActionCard({
  action: a,
  runId,
  reviewable,
  onDecided,
  onEvidence,
  onEvidenceHover,
  showRunLink,
}: Props) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Procédure et retour arrière copiés ensemble, pour un ticket de changement ou une main courante.
  const copy = async () => {
    const text = `${a.id} · ${a.title}\nCible : ${a.target}\nRisque : ${a.risk}\n\nProcédure\n${a.procedure}\n\nRetour arrière\n${a.rollback}\n`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Copie impossible : le navigateur refuse l'accès au presse-papiers.");
    }
  };
  const decide = async (accept: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await post(`/api/runs/${runId}/actions/${a.id}/decision`, { accept, comment });
      onDecided();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="action-card" data-risk={a.risk}>
      <header>
        <strong>
          {a.id} · {a.title}
        </strong>
        <span className="action-tags">
          <span className="never-run">jamais exécutée par l'agent</span>
          <span className="risk" data-risk={a.risk}>
            risque {a.risk}
          </span>
        </span>
      </header>
      {showRunLink && a.question && (
        <p className="muted">
          <a href={`#${runId}`}>{a.question}</a>
        </p>
      )}
      <p className="muted hint">
        {STATUS[a.status] ?? a.status}
        {a.decision && ` · par ${a.decision.by}${a.decision.comment ? ` : ${a.decision.comment}` : ""}`} · {a.type} ·{" "}
        {a.target}
        {a.requires_change ? " · passe par un changement" : ""}
      </p>
      <Markdown text={a.rationale} onEvidence={onEvidence} onEvidenceHover={onEvidenceHover} />
      {!!a.evidence?.length && (
        <p className="refs">
          {a.evidence
            .map(evidenceText)
            .map((r, i) =>
              /\/calls\/\d{4}\.json/.test(r) ? (
                <Evidence
                  key={i}
                  refPath={r.match(/(?:lead|subagents\/[^/\s]+)\/calls\/\d{4}\.json/)?.[0] ?? r}
                  onEvidence={onEvidence}
                  onHover={onEvidenceHover}
                />
              ) : (
                <code key={i}>{r}</code>
              ),
            )}
        </p>
      )}
      <details>
        <summary>Procédure et retour arrière</summary>
        <button type="button" className="btn ghost copy" onClick={copy}>
          {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
          {copied ? "Copiée" : "Copier la procédure"}
        </button>
        <Markdown text={a.procedure} />
        <h3>Retour arrière</h3>
        <Markdown text={a.rollback} />
        {a.risk_explanation && <p className="muted">{a.risk_explanation}</p>}
      </details>
      {reviewable && a.status === "proposed" && (
        <div className="decide">
          <input
            placeholder="Commentaire (facultatif)"
            aria-label="Commentaire de la décision"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <button type="button" className="btn primary" disabled={busy} onClick={() => decide(true)}>
            Valider
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => decide(false)}>
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
