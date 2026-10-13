// Zone d'édition de code avec numéros de ligne (marge synchronisée au défilement) ; la ligne citée par une
// erreur de validation (« line 12 » du message YAML) est marquée dans la marge.
import { useRef } from "react";

/** Numéro de ligne cité dans un message d'erreur YAML ou JSON (« line 12, column 3 »). */
export function errorLine(message: string | null | undefined): number | null {
  const m = message?.match(/\bline (\d+)/i) ?? message?.match(/\bligne (\d+)/i);
  return m ? Number(m[1]) : null;
}

interface Props {
  value: string;
  onChange: (v: string) => void;
  readOnly?: boolean;
  label: string;
  rows?: number;
  errorAt?: number | null;
}

export function CodeArea({ value, onChange, readOnly, label, rows = 26, errorAt }: Props) {
  const gutter = useRef<HTMLDivElement>(null);
  const count = Math.max(1, value.split("\n").length);
  return (
    <div className="code-area">
      <div className="code-gutter" ref={gutter} aria-hidden="true">
        {Array.from({ length: count }, (_, i) => (
          <span key={i} data-error={errorAt === i + 1 ? "" : undefined}>
            {i + 1}
          </span>
        ))}
      </div>
      <textarea
        className="code"
        spellCheck={false}
        rows={rows}
        wrap="off"
        aria-label={label}
        value={value}
        readOnly={readOnly}
        onChange={(e) => onChange(e.target.value)}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop;
        }}
      />
    </div>
  );
}
