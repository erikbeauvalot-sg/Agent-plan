// Markdown minimal et sûr : titres, listes, gras, code, blocs de code, preuves cliquables. Construit des
// éléments React (le texte est échappé par React) ; jamais de HTML venant du modèle.
import { Fragment, type ReactNode } from "react";

const EVIDENCE = /\[((?:lead|subagents\/[^\]/]+)\/calls\/\d{4}\.json)\]/;
const INLINE = /(\*\*.+?\*\*|`[^`]+`|\[(?:lead|subagents\/[^\]/]+)\/calls\/\d{4}\.json\])/g;

export type OnEvidence = (ref: string) => void;
/** Survol ou focus d'une preuve (null en sortie) : le graphe éclaire l'agent qui l'a produite. */
export type OnEvidenceHover = (ref: string | null) => void;

/** Agent qui a fait l'appel cité (lead ou T03-…). */
export const evidenceAgent = (ref: string): string => (ref.startsWith("lead") ? "lead" : (ref.split("/")[1] ?? "lead"));

/** « T03 · appel 2 » plutôt que le chemin du fichier. */
export function evidenceLabel(ref: string): string {
  const call = Number(ref.match(/(\d{4})\.json$/)?.[1] ?? 0);
  const agent = ref.startsWith("lead") ? "principal" : (ref.split("/")[1] ?? "").split("-")[0];
  return `${agent} · appel ${call}`;
}

export function Evidence({
  refPath,
  onEvidence,
  onHover,
}: {
  refPath: string;
  onEvidence?: OnEvidence;
  onHover?: OnEvidenceHover;
}) {
  if (!onEvidence) return <code title={refPath}>{evidenceLabel(refPath)}</code>;
  return (
    <button
      type="button"
      className="evidence"
      title={`Ouvrir la preuve ${refPath}`}
      onClick={() => onEvidence(refPath)}
      onMouseEnter={() => onHover?.(refPath)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => onHover?.(refPath)}
      onBlur={() => onHover?.(null)}
    >
      {evidenceLabel(refPath)}
    </button>
  );
}

function inline(text: string, onEvidence?: OnEvidence, onHover?: OnEvidenceHover): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    const ev = part.match(EVIDENCE);
    if (ev && ev[0] === part) return <Evidence key={i} refPath={ev[1]!} onEvidence={onEvidence} onHover={onHover} />;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function Markdown({
  text,
  onEvidence,
  onEvidenceHover,
  className,
}: {
  text: string | null | undefined;
  onEvidence?: OnEvidence;
  onEvidenceHover?: OnEvidenceHover;
  className?: string;
}) {
  const inline_ = (t: string) => inline(t, onEvidence, onEvidenceHover);
  const blocks: ReactNode[] = [];
  let list: ReactNode[] | null = null;
  let code: string[] | null = null;
  const flushList = () => {
    if (list) blocks.push(<ul key={`l${blocks.length}`}>{list}</ul>);
    list = null;
  };
  for (const raw of (text ?? "").split("\n")) {
    if (raw.startsWith("```")) {
      if (code) {
        blocks.push(<pre key={`c${blocks.length}`}>{code.join("\n")}</pre>);
        code = null;
      } else {
        flushList();
        code = [];
      }
      continue;
    }
    if (code) {
      code.push(raw);
      continue;
    }
    const item = raw.match(/^\s*[-*•]\s+(.*)/) ?? raw.match(/^\s*\d+\.\s+(.*)/);
    if (item) {
      (list ??= []).push(<li key={list.length}>{inline_(item[1]!)}</li>);
      continue;
    }
    flushList();
    const heading = raw.match(/^(#{1,4})\s+(.*)/);
    if (heading) blocks.push(<h3 key={`h${blocks.length}`}>{inline_(heading[2]!)}</h3>);
    else if (raw.trim()) blocks.push(<p key={`p${blocks.length}`}>{inline_(raw)}</p>);
  }
  flushList();
  if (code) blocks.push(<pre key={`c${blocks.length}`}>{(code as string[]).join("\n")}</pre>);
  return <div className={`md ${className ?? ""}`}>{blocks}</div>;
}
