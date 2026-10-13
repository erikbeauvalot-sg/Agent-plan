// Contrats de la passerelle FastAPI (poc/src/diagagent/web/app.py) utilisés par l'interface.

export type RunStatus = "running" | "stopping" | "completed" | "partial" | "stopped" | "failed" | "needs_clarification";

export interface Me {
  id: string;
  login: string;
  display_name: string;
  roles: string[];
  permissions: string[];
  reference_time: string | null;
}

export interface Category {
  id: string;
  description: string;
  examples?: string[];
}

export interface Choice {
  value: string;
  label: string;
  available: boolean;
  reason?: string | null;
}

export interface SourcesResponse {
  choices: Choice[];
  default: string;
}

export interface ModelsResponse {
  profiles: string[];
  default: string;
}

export interface ModelState {
  profile: string;
  roles: Record<string, string>;
  ok: boolean;
  detail: string;
  default?: boolean;
}

export interface SourceState {
  name: string;
  ok: boolean;
  detail: string;
  configured?: boolean;
}

export interface Alert {
  alertname: string;
  host?: string | null;
  severity?: string | null;
  summary?: string | null;
  starts_at?: string | null;
}

export interface StatusResponse {
  models: ModelState[];
  sources: SourceState[];
  alerts: Alert[];
  default_models: string;
}

export interface RunRow {
  run_id: string;
  question: string;
  status: RunStatus;
  started_at: string;
  duration_s?: number | null;
  category?: string | null;
  label?: string | null;
  tokens?: number | null;
  user: string;
  live?: LiveSummary;
}

export type StatusCounts = Partial<Record<RunStatus, number>>;

export interface StatRow {
  name: string;
  runs: number;
  success_rate: number | null;
  statuses: StatusCounts;
  avg_duration_s?: number | null;
  tokens?: number;
}

export interface HomeResponse {
  activity: {
    today: {
      runs: number;
      success_rate: number | null;
      tokens: number;
      avg_duration_s: number | null;
      by_model: Record<string, number>;
    };
    period: { runs: number; success_rate: number | null; tokens: number };
    categories: StatRow[];
    agents: StatRow[];
    models: StatRow[];
  };
  evals: EvalRow[];
}

export interface EvalRow {
  label: string;
  passed: number;
  cases: number;
  repeat: number;
  duration_s: number | null;
  tokens: number;
  date: string;
  cases_file: string;
  file: string;
}

export interface RunCategory {
  id: string;
  source?: string;
  correction?: { category: string; by: string };
}

export interface Manifest {
  run_id: string;
  question: string;
  status: RunStatus;
  user: string;
  started_at: string;
  models_profile?: string | null;
  /** « orchestrator » : les signaux sont dans la trace (signal_raised), pas à recalculer. */
  signals?: string | null;
  sources?: string[] | null;
  category?: RunCategory | null;
}

export interface RunDetail {
  manifest: Manifest;
  can_stop: boolean;
  can_share: boolean;
  can_details: boolean;
}

export interface AskBody {
  question: string;
  models: string | null;
  sources: string | null;
  category: string | null;
  rerun_of: string | null;
}

// Une ligne de events.jsonl, telle que le flux SSE la transmet.
export interface RunEvent {
  seq: number;
  ts: string;
  run_id: string;
  agent_id: string;
  parent_id: string | null;
  type: string;
  data?: Record<string, unknown>;
}

// Investigation (GET /api/runs/{id})

export interface FullCategory extends RunCategory {
  confidence?: string;
  mode?: string;
  playbooks?: Record<string, number>;
  history?: { from: string; to?: string }[];
  error?: string;
}

export interface Feedback {
  by: string;
  verdict: string;
  cause?: string;
}

export interface FullManifest extends Manifest {
  reference_time?: string | null;
  rerun_of?: string | null;
  shared?: boolean;
  feedback?: Feedback | null;
  models?: Record<string, { provider: string; model: string }>;
  usage?: { input_tokens?: number; output_tokens?: number; reasoning_tokens?: number };
  category?: FullCategory | null;
}

export interface Action {
  id: string;
  status: "proposed" | "validated" | "rejected" | string;
  title: string;
  target: string;
  type: string;
  rationale: string;
  evidence?: unknown[];
  risk: string;
  risk_explanation?: string;
  procedure: string;
  rollback: string;
  requires_change?: boolean;
  decision?: { by: string; comment?: string } | null;
  run_id?: string;
  question?: string;
  user?: string;
}

export interface FullRun {
  manifest: FullManifest;
  plan: string | null;
  analysis: string | null;
  actions: Action[];
  can_details: boolean;
  can_share: boolean;
  can_stop: boolean;
}

export interface ToolCallDetail {
  ref: string;
  tool: string;
  input: unknown;
  is_error: boolean;
  duration_s: number;
  output: string;
}

export interface AgentDetail {
  agent_id: string;
  prompt: string | null;
  system_prompt: string | null;
  report: unknown;
  calls: ToolCallDetail[];
  responses: { ts: string; text: string; tool_calls: string[]; stop_reason: string }[];
}

// Administration

export interface Indicators {
  runs: number;
  autre_share: number | null;
  draft_matches: Record<string, number>;
  categories: {
    category: string;
    runs: number;
    share: number | null;
    corrected_share: number | null;
    useful_share: number | null;
    feedback: number;
    avg_duration_s: number;
    avg_tool_calls: number;
  }[];
}

export interface Proposal {
  id: string;
  kind: string;
  target: string;
  status: string;
  rationale: string;
  evidence?: unknown[];
  change: unknown;
  replay?: { before: number; after: number; cases: number; ok: boolean } | null;
  decision?: { by: string; comment?: string } | null;
}

export interface CostRow {
  day: string;
  user: string;
  model: string;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
}

export interface Costs {
  rows: CostRow[];
  total: { runs: number; input_tokens: number; output_tokens: number; reasoning_tokens: number };
}

export interface AccessEntry {
  ts: string;
  user: string | null;
  action: string;
  [key: string]: unknown;
}

export interface ConfigFile {
  path: string;
  kind: string;
  group: string;
  permission: string;
  editable: boolean;
  size?: number;
  modified?: string;
}

export interface ConfigList {
  files: ConfigFile[];
  creatable: { pattern: string; kind: string; group: string; permission: string }[];
}

export interface ConfigContent {
  path: string;
  kind: string;
  permission: string;
  content: string;
  version: string;
  editable: boolean;
}

export interface ConfigVersion {
  id: string;
  author: string | null;
  comment: string;
  version: string;
  previous: string | null;
}

export interface Account {
  id: string;
  login: string;
  display_name: string;
  roles: string[];
  status: string;
  locked_until: string | null;
  created_at: string;
  /** Compte en attente ou lien de nouveau mot de passe : fin de validité du lien en cours. */
  activation_expires_at?: string | null;
}

export interface ActivationLink {
  url: string;
  expires_at: string;
}

/** Investigation en cours vue de l'accueil : état de chaque agent et dernière activité. */
export interface LiveSummary {
  agents: { id: string; parent: string | null; state: string }[];
  activity: string;
  activity_at: string | null;
}

/** Valeurs proposées par les filtres de l'historique. */
export interface RunFacets {
  users: string[];
  categories: string[];
  statuses: string[];
  hosts: string[];
}
