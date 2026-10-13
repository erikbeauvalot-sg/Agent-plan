// Graphe d'investigation : agent principal en haut, sous-agents en rangées dessous (React Flow). Un nœud par
// agent, mis à jour par clé ; en direct, un agent qui naît apparaît en fondu et chaque appel d'outil envoie
// une impulsion le long de son lien. Une liste textuelle équivalente sert aux lecteurs d'écran.
import {
  Background,
  BaseEdge,
  type Edge,
  type EdgeProps,
  getBezierPath,
  Handle,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import { memo, useEffect, useState } from "react";
import { StateBadge } from "../../components/StateBadge";
import { fmtDuration, fmtTokens, statusLabel } from "../../lib/format";
import { type AgentState, type RunState, signals } from "../../state/runState";

const NODE_W = 248;
const GAP_X = 24;
const ROW_H = 190;
/** Sous-agents par rangée selon la largeur : 4 sur grand écran, 3 sur tablette, 2 sur téléphone. */
function perRowFor(width: number): number {
  return width < 640 ? 2 : width < 1100 ? 3 : 4;
}

function useViewportWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

type AgentNodeData = { agent: AgentState; now: number; fromServer: boolean; born: boolean; hover: boolean };

const AgentNode = memo(function AgentNode({ data }: NodeProps<Node<AgentNodeData>>) {
  const { agent: a, now, fromServer, born, hover } = data;
  const sigs = signals(a, now, fromServer);
  const working = a.status === "running" && a.current;
  const ratio = a.maxTools ? Math.min(1, a.toolCalls / a.maxTools) : 0;
  const level = ratio >= 1 ? "max" : ratio > 0.8 ? "hi" : "ok";
  const duration = ((a.end ?? now) - a.start) / 1000;
  return (
    <div
      className="agent-node"
      data-status={a.status}
      data-signal={sigs.some((s) => s.bad) ? "bad" : sigs.length ? "warn" : ""}
      data-born={born ? "" : undefined}
      data-hover={hover ? "" : undefined}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="agent-head">
        <span className="agent-name">{a.id === "lead" ? "Agent principal" : a.id}</span>
        <StateBadge state={a.status} />
      </div>
      {a.objective && <p className="agent-obj">{a.objective}</p>}
      {working && (
        <p className="agent-now">
          <span className="pulse" aria-hidden="true" />
          {a.current}
        </p>
      )}
      <p className="agent-stats num">
        {a.toolCalls}
        {a.maxTools ? `/${a.maxTools}` : ""} outils · {fmtDuration(duration) || "0 s"} · {fmtTokens(a.tokens)} tokens
      </p>
      {a.llm && <p className="agent-llm mono">{a.llm}</p>}
      <span
        className="gauge wide"
        data-level={level === "max" ? "low" : level === "hi" ? "mid" : "high"}
        aria-hidden="true"
      >
        <span style={{ transform: `scaleX(${ratio})` }} />
      </span>
      {sigs.length > 0 && (
        <span className="badges">
          {sigs.map((s) => (
            <span key={s.key} className={`badge ${s.bad ? "bad" : ""}`}>
              {s.text}
            </span>
          ))}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
});

const nodeTypes = { agent: AgentNode };

const REDUCED = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

type PulseData = { pulses: number; animate: boolean };

/** Impulsions le long du lien : une par appel d'outil de l'agent enfant, 3 au plus à la fois. */
function Pulses({ path, count }: { path: string; count: number }) {
  const [seen, setSeen] = useState(count);
  const [active, setActive] = useState<number[]>([]);
  if (count !== seen) {
    setSeen(count);
    if (count > seen) setActive((a) => [...a, count].slice(-3));
  }
  useEffect(() => {
    if (!active.length) return;
    const t = setTimeout(() => setActive((a) => a.slice(1)), 900);
    return () => clearTimeout(t);
  }, [active]);
  return (
    <>
      {active.map((k) => (
        <circle key={k} r={3.5} className="edge-pulse">
          <animateMotion
            dur="0.8s"
            path={path}
            begin="indefinite"
            fill="freeze"
            ref={(el) => {
              (el as SVGAnimationElement | null)?.beginElement();
            }}
          />
        </circle>
      ))}
    </>
  );
}

const PulseEdge = memo(function PulseEdge(props: EdgeProps<Edge<PulseData>>) {
  const [path] = getBezierPath(props);
  return (
    <>
      <BaseEdge id={props.id} path={path} />
      {props.data?.animate && !REDUCED && <Pulses path={path} count={props.data.pulses} />}
    </>
  );
});

const edgeTypes = { pulse: PulseEdge };

/** Recadre le graphe quand un agent naît (ou que la largeur change le nombre de nœuds par rangée). */
function FitOnGrowth({ count, perRow }: { count: number; perRow: number }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      void fitView({ padding: 0.08, maxZoom: 1, minZoom: 0.3, duration: REDUCED ? 0 : 200 });
    });
    return () => cancelAnimationFrame(frame);
  }, [count, perRow, fitView]);
  return null;
}

function layoutOf(children: string[], perRow: number): Record<string, { x: number; y: number }> {
  const width = Math.max(NODE_W, Math.min(children.length, perRow) * (NODE_W + GAP_X) - GAP_X);
  const pos: Record<string, { x: number; y: number }> = { lead: { x: width / 2 - NODE_W / 2, y: 0 } };
  children.forEach((id, i) => {
    const row = Math.floor(i / perRow);
    const inRow = Math.min(perRow, children.length - row * perRow);
    const rowWidth = inRow * (NODE_W + GAP_X) - GAP_X;
    pos[id] = { x: (width - rowWidth) / 2 + (i % perRow) * (NODE_W + GAP_X), y: (row + 1) * ROW_H };
  });
  return pos;
}

interface Props {
  run: RunState;
  now: number;
  onOpen: (agentId: string) => void;
  /** Signaux venus de l'orchestrateur (trace récente) plutôt que recalculés. */
  fromServer: boolean;
  /** Animations seulement en direct : un rattrapage (rejeu, page ouverte en cours) s'applique sans mouvement. */
  liveSince: number | null;
  hover: string | null;
  onHover: (agentId: string | null) => void;
}

export function AgentGraph({ run, now, onOpen, fromServer, liveSince, hover, onHover }: Props) {
  const children = run.order.filter((id) => id !== "lead");
  const viewport = useViewportWidth();
  const perRow = perRowFor(viewport);
  const rows = Math.ceil(children.length / perRow);
  // Sur un écran étroit le graphe est réduit pour tenir en largeur : sa hauteur suit, sans vide dessous.
  const contentWidth = Math.max(NODE_W, Math.min(children.length, perRow) * (NODE_W + GAP_X) - GAP_X) + 40;
  const scale = Math.max(0.3, Math.min(1, (viewport - 72) / contentWidth));
  const height = Math.max(180, Math.round((200 + rows * ROW_H) * scale));
  // La disposition ne dépend que de la liste des agents (calcul léger, mêmes positions à chaque rendu) :
  // un nœud ne bouge pas quand ses données changent.
  const layout = layoutOf(children, perRow);

  const nodes: Node<AgentNodeData>[] = run.order
    .filter((id) => layout[id])
    .map((id) => ({
      id,
      type: "agent",
      position: layout[id]!,
      data: {
        agent: run.agents[id]!,
        now,
        fromServer,
        born: liveSince !== null && run.agents[id]!.start >= liveSince,
        hover: hover === id,
      },
      draggable: false,
    }));
  const edges: Edge[] = (run.agents.lead ? children : []).map((id) => ({
    id: `lead-${id}`,
    source: "lead",
    target: id,
    type: "pulse",
    className: `edge-${run.agents[id]!.status}${hover === id ? " edge-hover" : ""}`,
    data: {
      pulses: run.agents[id]!.toolCalls + Object.keys(run.agents[id]!.calls).length,
      animate: liveSince !== null,
    },
  }));

  if (!run.agents.lead) return <p className="muted">En attente du premier événement…</p>;
  return (
    <>
      <div className="graph" style={{ height }} aria-hidden="true">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeClick={(_, n) => onOpen(n.id)}
          onNodeMouseEnter={(_, n) => onHover(n.id)}
          onNodeMouseLeave={() => onHover(null)}
          fitView
          fitViewOptions={{ padding: 0.08, maxZoom: 1, minZoom: 0.3 }}
          minZoom={0.3}
          nodesConnectable={false}
          nodesDraggable={false}
          elementsSelectable={false}
          zoomOnScroll={false}
          panOnScroll={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1} />
          <FitOnGrowth count={nodes.length} perRow={perRow} />
        </ReactFlow>
      </div>
      <ul className="agent-list visually-hidden-focusable" aria-label="Agents de l'investigation">
        {run.order.map((id) => {
          const a = run.agents[id]!;
          return (
            <li key={id}>
              <button type="button" className="link" onClick={() => onOpen(id)}>
                {id === "lead" ? "Agent principal" : id}
              </button>{" "}
              : {statusLabel(a.status)}, {a.toolCalls} appels d'outils{a.objective ? `, ${a.objective}` : ""}
            </li>
          );
        })}
      </ul>
    </>
  );
}
