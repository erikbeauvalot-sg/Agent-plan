// Réduction des événements d'une investigation (events.jsonl, flux SSE) en un état d'agents.
// Fonction pure : le même état se reconstruit à partir des seuls événements, en direct comme au rejeu
// (document d'architecture, « Modèle d'événement »). Reprend la logique de l'interface actuelle (app.js).
import type { RunEvent } from "../api/types";
import { agentName, describeCall } from "../lib/activity";

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
  /** Appels d'outils en cours (ref → outil, paramètres, début) et ce que fait l'agent en ce moment. */
  calls: Record<string, { tool: string; args: unknown; start: number }>;
  current: string | null;
  /** Signaux écrits par l'orchestrateur (signal_raised / signal_cleared), par type. */
  serverSignals: Record<string, Signal>;
  slowRefs: string[];
}

/** Une ligne du fil d'activité. */
export interface FeedItem {
  seq: number;
  ts: number;
  agent: string;
  text: string;
  kind: "tool" | "agent" | "signal" | "run";
  bad?: boolean;
}

const FEED_MAX = 300;

export interface RunState {
  agents: Record<string, AgentState>;
  order: string[];
  firstTs: number | null;
  lastTs: number | null;
  lastSeq: number;
  classifier: Usage | null;
  /** Événements qui demandent de relire la synthèse (catégorie, action proposée…). */
  summaryVersion: number;
  /** Fil d'activité, du plus ancien au plus récent (les FEED_MAX derniers). */
  feed: FeedItem[];
  /** La trace contient des signaux de l'orchestrateur : le navigateur ne les recalcule pas. */
  serverSignals: boolean;
}

export const emptyRun = (): RunState => ({
  agents: {},
  order: [],
  firstTs: null,
  lastTs: null,
  lastSeq: 0,
  classifier: null,
  summaryVersion: 0,
  feed: [],
  serverSignals: false,
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
    calls: {},
    current: null,
    serverSignals: {},
    slowRefs: [],
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
  // Un signal n'est pas une activité de l'agent : il ne remet pas à zéro sa durée d'inactivité.
  const isSignal = e.type.startsWith("signal_");
  let a: AgentState = prev ? (isSignal ? { ...prev } : { ...prev, last: ts }) : newAgent(e, ts);
  const agents = { ...state.agents };
  const order = prev ? state.order : [...state.order, e.agent_id];
  let { classifier, summaryVersion, serverSignals } = state;
  const said: Omit<FeedItem, "seq" | "ts" | "agent">[] = [];
  const who = agentName(e.agent_id);

  switch (e.type) {
    case "agent_spawned":
      a = { ...a, objective: str(d.objective), parent: "lead" };
      said.push({ kind: "agent", text: `${who} lancé : ${str(d.objective)}` });
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
      a = { ...a, open: { ...a.open, llm: ts }, current: Object.keys(a.calls).length ? a.current : "réfléchit" };
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
      const current = describeCall(str(d.tool), d.arguments);
      a = {
        ...a,
        open: { ...a.open, [str(d.ref)]: ts },
        repeats: { ...a.repeats, [key]: count },
        maxRepeat: Math.max(a.maxRepeat, count),
        calls: { ...a.calls, [str(d.ref)]: { tool: str(d.tool), args: d.arguments, start: ts } },
        current,
      };
      said.push({ kind: "tool", text: `${who} ${current}` });
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
      const { [ref]: done, ...calls } = a.calls;
      const still = Object.values(calls).at(-1);
      a = {
        ...a,
        toolCalls: a.toolCalls + 1,
        errorStreak: d.is_error ? a.errorStreak + 1 : 0,
        segments: [...a.segments, seg],
        calls,
        current: still ? describeCall(still.tool, still.args) : a.current,
      };
      if (d.is_error && done) said.push({ kind: "tool", text: `${who} : erreur de ${str(d.tool)}`, bad: true });
      break;
    }
    case "stop_requested":
      said.push({
        kind: "run",
        text:
          d.scope === "agent"
            ? `Arrêt de ${who} demandé par ${str(d.by)}`
            : d.scope === "kill"
              ? `Arrêt immédiat demandé par ${str(d.by)}`
              : `Arrêt de l'investigation demandé par ${str(d.by)}`,
      });
      if (d.scope === "agent") a = { ...a, status: "stopping" };
      else {
        for (const [id, x] of Object.entries(agents))
          if (x.status === "running") agents[id] = { ...x, status: "stopping" };
        if (a.status === "running") a = { ...a, status: "stopping" };
      }
      break;
    case "report_submitted":
      a = { ...a, report: str(d.status) };
      said.push({ kind: "agent", text: `${who} a rendu son rapport (${statusText(str(d.status))})` });
      break;
    case "agent_ended":
      a = { ...a, status: str(d.status), end: ts, current: null, calls: {} };
      said.push({ kind: "agent", text: `${who} : ${statusText(str(d.status))}`, bad: d.status === "failed" });
      break;
    case "signal_raised": {
      const kind = str(d.kind);
      const signal: Signal = { key: kind, text: str(d.text) || kind, bad: d.level === "bad" };
      serverSignals = true;
      a = {
        ...a,
        serverSignals: { ...a.serverSignals, [kind]: signal },
        slowRefs: kind.startsWith("slow:") ? [...a.slowRefs, str(d.ref)] : a.slowRefs,
      };
      said.push({ kind: "signal", text: `${who} — ${signal.text}`, bad: signal.bad });
      break;
    }
    case "signal_cleared": {
      const { [str(d.kind)]: _gone, ...rest } = a.serverSignals;
      void _gone;
      a = { ...a, serverSignals: rest };
      break;
    }

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
      said.push({ kind: "run", text: d.mode === "clarify" ? "Précision demandée" : `Demande classée : ${str(d.id)}` });
      summaryVersion += 1;
      break;
    }
    case "action_proposed":
      said.push({ kind: "run", text: `Action proposée : ${str(d.title)}` });
      summaryVersion += 1;
      break;
    case "category_changed":
      said.push({ kind: "run", text: `Catégorie changée : ${str(d.from)} → ${str(d.to)}` });
      summaryVersion += 1;
      break;
    case "run_failed":
      a = { ...a, status: "failed", end: ts };
      break;
  }
  agents[e.agent_id] = a;
  const feed = said.length
    ? [...state.feed, ...said.map((x) => ({ ...x, seq: e.seq, ts, agent: e.agent_id }))].slice(-FEED_MAX)
    : state.feed;
  return {
    agents,
    order,
    firstTs: state.firstTs ?? ts,
    lastTs: isSignal ? (state.lastTs ?? ts) : ts,
    lastSeq: Math.max(state.lastSeq, e.seq ?? 0),
    classifier,
    summaryVersion,
    feed,
    serverSignals,
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
  key: string;
  text: string;
  bad?: boolean;
}

const statusText = (status: string): string =>
  ({ completed: "terminé", partial: "partiel", failed: "en échec", stopped: "arrêté" })[status] ?? status;

/** Signaux affichés sur un agent en cours. Une trace récente porte ceux de l'orchestrateur (fromServer) ;
 * une trace plus ancienne les fait recalculer ici avec les mêmes règles. */
export function signals(a: AgentState, now: number, fromServer = false): Signal[] {
  if (a.status !== "running" && a.status !== "stopping") return [];
  if (fromServer) {
    // La durée d'inactivité continue de compter après la levée du signal.
    const out = Object.values(a.serverSignals)
      .filter((x) => !x.key.startsWith("slow:"))
      .map((x) => (x.key === "stuck" ? { ...x, text: `bloqué ${Math.round((now - a.last) / 1000)} s` } : x));
    const slow = Object.keys(a.serverSignals).filter((k) => k.startsWith("slow:")).length;
    if (slow) out.push({ key: "slow", text: slow > 1 ? `${slow} sources lentes` : "source lente" });
    return out;
  }
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
