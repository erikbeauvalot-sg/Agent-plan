// Mini-graphe d'une investigation en cours (cartes de l'accueil) : l'agent principal en haut, un point par
// sous-agent dessous, coloré par état ; un agent actif respire (sauf mouvement réduit).
import type { LiveSummary } from "../api/types";
import { statusLabel } from "../lib/format";

const W = 132;
const H = 44;

export function MiniGraph({ live }: { live: LiveSummary }) {
  const lead = live.agents.find((a) => a.id === "lead");
  const subs = live.agents.filter((a) => a.id !== "lead");
  const gap = subs.length > 1 ? Math.min(18, (W - 16) / (subs.length - 1)) : 0;
  const x0 = W / 2 - (gap * (subs.length - 1)) / 2;
  const label =
    `${subs.length} sous-agent(s)` +
    (subs.length ? ` : ${subs.filter((a) => a.state === "running").length} en cours` : "") +
    (lead ? `, agent principal ${statusLabel(lead.state)}` : "");
  return (
    <svg className="mini-graph" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={label}>
      {subs.map((a, i) => (
        <line key={`l-${a.id}`} x1={W / 2} y1={10} x2={x0 + i * gap} y2={H - 9} />
      ))}
      {lead && <circle className="dot" data-state={lead.state} cx={W / 2} cy={10} r={5.5} />}
      {subs.map((a, i) => (
        <circle key={a.id} className="dot" data-state={a.state} cx={x0 + i * gap} cy={H - 9} r={4} />
      ))}
    </svg>
  );
}
