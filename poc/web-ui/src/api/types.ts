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
