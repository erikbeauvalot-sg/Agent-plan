// Chronologie : une ligne par agent, segments modèle, outil et erreur sur un axe commun ; un clic ouvre le
// tiroir de l'agent (sur l'appel d'outil quand on clique un segment d'outil).
import type { RunState } from "../../state/runState";

interface Props {
  run: RunState;
  now: number;
  ended: boolean;
  onOpen: (agentId: string, ref?: string) => void;
}

export function Timeline({ run, now, ended, onOpen }: Props) {
  if (run.firstTs === null) return <p className="muted">Aucun événement pour l'instant.</p>;
  const t0 = run.firstTs;
  const end = ended ? (run.lastTs ?? now) : now;
  const span = Math.max(1, end - t0);
  const left = (t: number) => `${(100 * (t - t0)) / span}%`;
  const width = (a: number, b: number) => `${Math.max(0.3, (100 * (b - a)) / span)}%`;
  return (
    <div className="timeline">
      {run.order.map((id) => {
        const a = run.agents[id]!;
        const llmOpen =
          a.status === "running" && a.open.llm !== undefined && !a.segments.some((s) => s.start === a.open.llm);
        return (
          <div className="tl-row" key={id}>
            <button type="button" className="tl-label link" onClick={() => onOpen(id)}>
              {id === "lead" ? "principal" : id}
            </button>
            <span className="tl-track">
              <span className="tl-life" style={{ left: left(a.start), width: width(a.start, a.end ?? end) }} />
              {a.segments.map((s, i) => (
                <button
                  type="button"
                  key={i}
                  className={`tl-seg ${s.kind}`}
                  style={{ left: left(s.start), width: width(s.start, s.end) }}
                  title={`${s.label} · ${((s.end - s.start) / 1000).toFixed(1).replace(".", ",")} s`}
                  aria-label={`${s.label}, ${((s.end - s.start) / 1000).toFixed(1)} s`}
                  onClick={() => onOpen(id, s.ref)}
                />
              ))}
              {llmOpen && (
                <span
                  className="tl-seg llm pending"
                  style={{ left: left(a.open.llm!), width: width(a.open.llm!, end) }}
                />
              )}
            </span>
          </div>
        );
      })}
      <p className="legend faint">
        <span className="tl-key llm" /> modèle <span className="tl-key tool" /> outil <span className="tl-key err" />{" "}
        erreur
      </p>
    </div>
  );
}
