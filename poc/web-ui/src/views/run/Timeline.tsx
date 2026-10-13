// Chronologie : une ligne par agent, segments modèle, outil et erreur sur un axe commun ; les appels encore
// ouverts (attente d'un outil, d'un sous-agent) s'étirent en direct, une source lente est marquée. Le survol
// d'une ligne éclaire le nœud du graphe, et inversement ; un clic ouvre le tiroir de l'agent (sur l'appel
// d'outil quand on clique un segment d'outil).
import { describeCall } from "../../lib/activity";
import type { RunState } from "../../state/runState";

interface Props {
  run: RunState;
  now: number;
  ended: boolean;
  onOpen: (agentId: string, ref?: string) => void;
  liveSince: number | null;
  hover: string | null;
  onHover: (agentId: string | null) => void;
}

const secs = (ms: number) => (ms / 1000).toFixed(1).replace(".", ",");

export function Timeline({ run, now, ended, onOpen, liveSince, hover, onHover }: Props) {
  if (run.firstTs === null) return <p className="muted">Aucun événement pour l'instant.</p>;
  const t0 = run.firstTs;
  const end = ended ? (run.lastTs ?? now) : now;
  const span = Math.max(1, end - t0);
  const left = (t: number) => `${(100 * (t - t0)) / span}%`;
  const width = (a: number, b: number) => `${Math.max(0.3, (100 * (b - a)) / span)}%`;
  return (
    <div className="timeline" onMouseLeave={() => onHover(null)}>
      {run.order.map((id) => {
        const a = run.agents[id]!;
        const running = a.status === "running" || a.status === "stopping";
        const llmOpen = running && a.open.llm !== undefined && !a.segments.some((s) => s.start === a.open.llm);
        return (
          <div
            className="tl-row"
            key={id}
            data-born={liveSince !== null && a.start >= liveSince ? "" : undefined}
            data-hover={hover === id ? "" : undefined}
            onMouseEnter={() => onHover(id)}
          >
            <button type="button" className="tl-label link" onClick={() => onOpen(id)}>
              {id === "lead" ? "principal" : id}
            </button>
            <span className="tl-track">
              <span className="tl-life" style={{ left: left(a.start), width: width(a.start, a.end ?? end) }} />
              {a.segments.map((s, i) => {
                const slow = !!s.ref && a.slowRefs.includes(s.ref);
                const label = `${s.label} · ${secs(s.end - s.start)} s${slow ? " · source lente" : ""}`;
                return (
                  <button
                    type="button"
                    key={i}
                    className={`tl-seg ${s.kind}${s.label === "wait_subagents" ? " wait" : ""}${slow ? " slow" : ""}`}
                    style={{ left: left(s.start), width: width(s.start, s.end) }}
                    title={label}
                    aria-label={label}
                    onClick={() => onOpen(id, s.ref)}
                  />
                );
              })}
              {llmOpen && (
                <span
                  className="tl-seg llm pending"
                  style={{ left: left(a.open.llm!), width: width(a.open.llm!, end) }}
                  title={`modèle en cours · ${secs(end - a.open.llm!)} s`}
                />
              )}
              {running &&
                Object.entries(a.calls).map(([ref, c]) => {
                  const slow = a.slowRefs.includes(ref);
                  const label = `${describeCall(c.tool, c.args)} · en cours depuis ${secs(end - c.start)} s${slow ? " · source lente" : ""}`;
                  return (
                    <button
                      type="button"
                      key={ref}
                      className={`tl-seg tool pending${c.tool === "wait_subagents" ? " wait" : ""}${slow ? " slow" : ""}`}
                      style={{ left: left(c.start), width: width(c.start, end) }}
                      title={label}
                      aria-label={label}
                      onClick={() => onOpen(id, ref)}
                    />
                  );
                })}
            </span>
          </div>
        );
      })}
      <p className="legend faint">
        <span className="tl-key llm" /> modèle <span className="tl-key tool" /> outil <span className="tl-key wait" />{" "}
        attente des sous-agents <span className="tl-key err" /> erreur <span className="tl-key slow" /> source lente
      </p>
    </div>
  );
}
