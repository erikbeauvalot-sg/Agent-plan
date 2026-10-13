// Réponse de l'investigation. Pendant que l'agent principal l'écrit : le texte diffusé (answer_delta), marqué
// « en cours d'écriture » ou « en cours de révision » si un contrôle l'a relancé. À la fin : la synthèse en
// premier, en grand, avec le niveau de confiance, puis les autres rubriques en cascade ; chaque preuve est une
// puce qui ouvre l'appel exact et, au survol, éclaire l'agent dans le graphe.
import { useEffect, useRef } from "react";
import { FOLDED, parseAnswer } from "../../lib/answer";
import { Markdown, type OnEvidence, type OnEvidenceHover } from "../../components/Markdown";
import type { Draft } from "../../state/runState";

const LEVEL: Record<string, string> = { faible: "low", moyenne: "mid", élevée: "high" };

const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

interface Props {
  analysis: string | null | undefined;
  draft: Draft | null;
  ended: boolean;
  /** La synthèse vient d'arriver en direct : on l'anime ; ouverte plus tard, elle s'affiche directement. */
  reveal: boolean;
  onEvidence: OnEvidence;
  onEvidenceHover: OnEvidenceHover;
}

export function Answer({ analysis, draft, ended, reveal, onEvidence, onEvidenceHover }: Props) {
  if (!analysis) {
    if (draft?.text.trim())
      return (
        <div className="answer-draft" aria-busy={!draft.done}>
          <p className="draft-state">
            <span className="pulse" aria-hidden="true" />
            {draft.revising
              ? "En cours de révision : un contrôle de l'orchestrateur a demandé de compléter la réponse"
              : draft.done
                ? "Réponse rédigée, enregistrement…"
                : "L'agent principal écrit la réponse…"}
          </p>
          <Markdown text={draft.text} onEvidence={onEvidence} onEvidenceHover={onEvidenceHover} className="answer" />
          {!draft.done && <span className="caret" aria-hidden="true" />}
        </div>
      );
    return (
      <p className="muted">
        {ended ? "Aucune synthèse enregistrée." : "La synthèse s'affichera ici, au fil de son écriture."}
      </p>
    );
  }

  return <Revealed analysis={analysis} reveal={reveal} onEvidence={onEvidence} onEvidenceHover={onEvidenceHover} />;
}

function Revealed({
  analysis,
  reveal,
  onEvidence,
  onEvidenceHover,
}: Pick<Props, "reveal" | "onEvidence" | "onEvidenceHover"> & { analysis: string }) {
  const ref = useRef<HTMLDivElement>(null);
  // Vue en direct : la synthèse passe en tête de page à la fin ; on l'amène sous les yeux.
  useEffect(() => {
    if (!reveal) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    ref.current?.closest("section")?.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
  }, [reveal]);
  const a = parseAnswer(analysis);
  return (
    <div className="answer-reveal" ref={ref} data-reveal={reveal ? "" : undefined}>
      <div className="answer-lead">
        {a.confidence && (
          <span className="confidence" data-level={LEVEL[a.confidence]}>
            Confiance {a.confidence}
          </span>
        )}
        <Markdown text={a.summary} onEvidence={onEvidence} onEvidenceHover={onEvidenceHover} className="answer" />
      </div>
      {a.sections.map((s, i) => {
        const body = (
          <Markdown text={s.body} onEvidence={onEvidence} onEvidenceHover={onEvidenceHover} className="answer" />
        );
        const folded = FOLDED.includes(fold(s.title).trim());
        return (
          <section key={`${s.title}-${i}`} className="answer-part" style={{ "--i": i + 1 } as React.CSSProperties}>
            {folded ? (
              <details>
                <summary>
                  <h3>{s.title}</h3>
                  <span className="faint">détail plus bas, dans les cartes d'actions</span>
                </summary>
                {body}
              </details>
            ) : (
              <>
                <h3>{s.title}</h3>
                {body}
              </>
            )}
          </section>
        );
      })}
    </div>
  );
}
