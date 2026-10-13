// Ligne de statut vivante (« T03 interroge les métriques : cpu.usage de srv-pay-01 ») et fil d'activité de
// l'investigation. La ligne visible change à chaque événement ; la région lue par les lecteurs d'écran est
// mise à jour au plus toutes les 5 s pour ne pas les noyer.
import { useEffect, useRef, useState } from "react";
import { TriangleAlert } from "../../components/icons";
import { agentName } from "../../lib/activity";
import type { RunState } from "../../state/runState";

/** Ce que fait l'agent actif le plus récent, et combien d'agents travaillent. */
export function statusLine(run: RunState): { text: string; active: number } | null {
  const running = run.order.map((id) => run.agents[id]!).filter((a) => a.status === "running");
  if (!running.length) return null;
  const busy = running.filter((a) => a.current).sort((a, b) => b.last - a.last)[0];
  const text = busy ? `${agentName(busy.id)} ${busy.current}` : "Démarrage de l'investigation";
  return { text, active: running.length };
}

export function StatusLine({ run, ended }: { run: RunState; ended: boolean }) {
  const line = ended ? null : statusLine(run);
  const text = line?.text ?? "";
  const latest = useRef(text);
  useEffect(() => {
    latest.current = text;
  }, [text]);
  const [spoken, setSpoken] = useState("");
  useEffect(() => {
    if (ended) return;
    const t = setInterval(() => setSpoken(latest.current), 5000);
    return () => clearInterval(t);
  }, [ended]);
  if (!line) return null;
  return (
    <div className="status-line">
      <span className="pulse" aria-hidden="true" />
      <span className="status-text" aria-hidden="true">
        {line.text}
      </span>
      <span className="faint num" aria-hidden="true">
        {line.active > 1 ? `${line.active} agents actifs` : "1 agent actif"}
      </span>
      <span className="visually-hidden" aria-live="polite">
        {spoken}
      </span>
    </div>
  );
}

const time = (ms: number) => new Date(ms).toLocaleTimeString("fr-FR", { hour12: false });

export function ActivityFeed({ run, onOpen }: { run: RunState; onOpen: (agentId: string) => void }) {
  const [all, setAll] = useState(false);
  if (!run.feed.length) return <p className="muted">Aucune activité pour l'instant.</p>;
  const items = [...run.feed].reverse().slice(0, all ? undefined : 40);
  return (
    <>
      <ol className="feed">
        {items.map((f, i) => (
          <li key={`${f.seq}-${i}`} data-kind={f.kind} data-bad={f.bad ? "" : undefined}>
            <span className="num faint">{time(f.ts)}</span>
            {f.kind === "signal" && <TriangleAlert size={13} aria-hidden="true" />}
            <span className="feed-text">
              {f.text.startsWith(agentName(f.agent)) ? (
                <>
                  <button type="button" className="link" onClick={() => onOpen(f.agent)}>
                    {agentName(f.agent)}
                  </button>
                  {f.text.slice(agentName(f.agent).length)}
                </>
              ) : (
                f.text
              )}
            </span>
          </li>
        ))}
      </ol>
      {run.feed.length > 40 && (
        <button type="button" className="link" onClick={() => setAll(!all)}>
          {all ? "Afficher moins" : `Afficher tout (${run.feed.length})`}
        </button>
      )}
    </>
  );
}
