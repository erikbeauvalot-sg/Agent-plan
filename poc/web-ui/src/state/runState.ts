// Réduction des événements d'une investigation (events.jsonl, flux SSE) en un état d'agents.
// Fonction pure : le même état se reconstruit à partir des seuls événements, en direct comme au rejeu
// (document d'architecture, « Modèle d'événement »). Reprend la logique de l'interface actuelle (app.js).
import type { RunEvent } from "../api/types";

export type SegmentKind = "llm" | "tool" | "err";

export interface Segment {
  kind: SegmentKind;
  start: number;
  end: number;
  label: string;
  ref?: string;
}

export interface Usage {
  tokensIn: number;
  tokensOut: number;
  tokensReasoning: number;
  tokens: number;
}

export interface AgentState extends Usage {
  id: string;
  parent: string | null;
  role: string;
  objective: string;
  status: string;
  start: number;
  end: number | null;
  last: number;
  segments: Segment[];
  open: Record<string, number>;
  toolCalls: number;
  maxTools: number | null;
  errorStreak: number;
  repeats: Record<string, number>;
  maxRepeat: number;
  modelError: string | null;
  llm: string | null;
  report: string | null;
}

export interface RunState {
  agents: Record<string, AgentState>;
  order: string[];
  firstTs: number | null;
  lastTs: number | null;
  lastSeq: number;
  classifier: Usage | null;
  /** Événements qui demandent de relire la synthèse (catégorie, action proposée…). */
  summaryVersion: number;
}

export const emptyRun = (): RunState => ({
  agents: {},
  order: [],
  firstTs: null,
  lastTs: null,
  lastSeq: 0,
  classifier: null,
  summaryVersion: 0,
});

const noUsage = (): Usage => ({
  tokensIn: 0,
  tokensOut: 0,
  tokensReasoning: 0,
  tokens: 0,
});

function addUsage(target: Usage, usage: unknown): Usage {
  const u = (usage ?? {}) as {
    input_tokens?: number;
    output_tokens?: number;
    reasoning_tokens?: number;
  };
  const tokensIn = target.tokensIn + (u.input_tokens ?? 0);
  const tokensOut = target.tokensOut + (u.output_tokens ?? 0);
  return {
    tokensIn,
    tokensOut,
    tokensReasoning: target.tokensReasoning + (u.reasoning_tokens ?? 0),
    tokens: tokensIn + tokensOut,
  };
}

function newAgent(e: RunEvent, ts: number): AgentState {
  return {
    id: e.agent_id,
    parent: e.parent_id,
    role: e.agent_id === "lead" ? "principal" : (e.agent_id.split("-")[1] ?? e.agent_id),
    objective: "",
    status: "running",
    start: ts,
    end: null,
    last: ts,
    segments: [],
    open: {},
    toolCalls: 0,
    maxTools: null,
    errorStreak: 0,
    repeats: {},
    maxRepeat: 0,
    modelError: null,
    llm: null,
    report: null,
    ...noUsage(),
  };
}

const str = (v: unknown): string => (typeof v === "string" ? v : v === undefined || v === null ? "" : String(v));

/** Applique un événement ; rend un nouvel état (l'ancien n'est jamais modifié). Un événement déjà vu est ignoré. */
export function reduce(state: RunState, e: RunEvent): RunState {
  if (e.seq && e.seq <= state.lastSeq) return state;
  const ts = Date.parse(e.ts);
  const d = e.data ?? {};
  const prev = state.agents[e.agent_id];
  let a: AgentState = prev ? { ...prev, last: ts } : newAgent(e, ts);
  const agents = { ...state.agents };
  const order = prev ? state.order : [...state.order, e.agent_id];
  let { classifier, summaryVersion } = state;

  switch (e.type) {
    case "agent_spawned":
      a = { ...a, objective: str(d.objective), parent: "lead" };
      break;
    case "agent_started":
      a = {
        ...a,
        maxTools: typeof d.max_tool_calls === "number" ? d.max_tool_calls : a.maxTools,
        start: Math.min(a.start, ts),
        llm: d.model ? `${str(d.provider)} / ${str(d.model)}` : a.llm,
      };
      break;
    case "llm_call_started":
      a = { ...a, open: { ...a.open, llm: ts } };
      break;
    case "llm_call_ended": {
      const error = d.error ? str(d.error) : null;
      const seg: Segment = {
        kind: error ? "err" : "llm",
        start: a.open.llm ?? ts,
        end: ts,
        label: error ? `modèle : ${error}` : `modèle ${str(d.model)}`.trim(),
      };
      a = {
        ...a,
        segments: [...a.segments, seg],
        modelError: error ?? a.modelError,
        ...addUsage(a, d.usage),
      };
      break;
    }
    case "tool_call_started": {
      const key = str(d.tool) + JSON.stringify(d.arguments ?? {});
      const count = (a.repeats[key] ?? 0) + 1;
      a = {
        ...a,
        open: { ...a.open, [str(d.ref)]: ts },
        repeats: { ...a.repeats, [key]: count },
        maxRepeat: Math.max(a.maxRepeat, count),
      };
      break;
    }
    case "tool_call_ended": {
      const ref = str(d.ref);
      const seg: Segment = {
        kind: d.is_error ? "err" : "tool",
        start: a.open[ref] ?? ts,
        end: ts,
        label: str(d.tool),
        ref,
      };
      a = {
        ...a,
        toolCalls: a.toolCalls + 1,
        errorStreak: d.is_error ? a.errorStreak + 1 : 0,
        segments: [...a.segments, seg],
      };
      break;
    }
    case "stop_requested":
      if (d.scope === "agent") a = { ...a, status: "stopping" };
      else {
        for (const [id, x] of Object.entries(agents))
          if (x.status === "running") agents[id] = { ...x, status: "stopping" };
        if (a.status === "running") a = { ...a, status: "stopping" };
      }
      break;
    case "report_submitted":
      a = { ...a, report: str(d.status) };
      break;
    case "agent_ended":
      a = { ...a, status: str(d.status), end: ts };
      break;
    case "classification_started":
      a = { ...a, open: { ...a.open, cls: ts } };
      break;
    case "request_classified": {
      // La classification apparaît comme un appel au modèle de l'agent principal ; une demande de
      // précision termine l'investigation sans lancer l'agent.
      if (a.open.cls !== undefined)
        a = {
          ...a,
          segments: [
            ...a.segments,
            {
              kind: "llm",
              start: a.open.cls,
              end: ts,
              label: `classification : ${str(d.id)}`,
            },
          ],
        };
      if (d.usage) classifier = addUsage(noUsage(), d.usage);
      if (d.mode === "clarify") a = { ...a, status: "needs_clarification", end: ts };
      summaryVersion += 1;
      break;
    }
    case "action_proposed":
    case "category_changed":
      summaryVersion += 1;
      break;
    case "run_failed":
      a = { ...a, status: "failed", end: ts };
      break;
  }
  agents[e.agent_id] = a;
  return {
    agents,
    order,
    firstTs: state.firstTs ?? ts,
    lastTs: ts,
    lastSeq: Math.max(state.lastSeq, e.seq ?? 0),
    classifier,
    summaryVersion,
  };
}

export const reduceAll = (events: RunEvent[], state: RunState = emptyRun()): RunState => events.reduce(reduce, state);

/** Seuils du document d'architecture (« Détection visuelle des problèmes d'exécution »). */
export const SIGNALS = {
  stuckSeconds: 120,
  loopRepeats: 3,
  errorStreak: 3,
  budgetRatio: 0.8,
};

export interface Signal {
  key: "stuck" | "loop" | "errors" | "budget" | "model";
  text: string;
  bad?: boolean;
}

export function signals(a: AgentState, now: number): Signal[] {
  if (a.status !== "running" && a.status !== "stopping") return [];
  const out: Signal[] = [];
  const idle = (now - a.last) / 1000;
  if (idle > SIGNALS.stuckSeconds) out.push({ key: "stuck", text: `bloqué ${Math.round(idle)} s` });
  if (a.maxRepeat >= SIGNALS.loopRepeats) out.push({ key: "loop", text: "boucle" });
  if (a.errorStreak >= SIGNALS.errorStreak) out.push({ key: "errors", text: `${a.errorStreak} erreurs`, bad: true });
  if (a.maxTools && a.toolCalls / a.maxTools > SIGNALS.budgetRatio) out.push({ key: "budget", text: "budget" });
  if (a.modelError) out.push({ key: "model", text: `modèle : ${a.modelError}`, bad: true });
  return out;
}

/** Tokens comptés en direct sur tous les agents et le classifieur. */
export function liveUsage(state: RunState): Usage {
  return [...Object.values(state.agents), state.classifier ?? noUsage()].reduce(
    (s, a) => ({
      tokensIn: s.tokensIn + a.tokensIn,
      tokensOut: s.tokensOut + a.tokensOut,
      tokensReasoning: s.tokensReasoning + a.tokensReasoning,
      tokens: s.tokens + a.tokens,
    }),
    noUsage(),
  );
}
