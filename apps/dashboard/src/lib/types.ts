export type Task = {
  id: string;
  title: string;
  state: string;
  tier: string;
  role: string;
  stage?: string | null;
  spent_usd: number | string;
  budget_usd: number | string;
  pr_url?: string | null;
  error?: string | null;
  review_verdict?: string | null;
};

export type EventRow = {
  id: number;
  ts: string;
  task_id?: string | null;
  role?: string | null;
  kind: string;
  status?: string | null;
  summary?: string | null;
  cost_usd: number | string;
  payload?: Record<string, unknown>;
};

export type HumanItem = {
  id: string;
  task_id?: string | null;
  kind: string;
  summary: string;
  status: string;
  reply?: string | null;
  needed_by?: string | null;
};

export type RuntimeSettings = {
  version: number;
  roles: Record<string, { tier?: string; model?: string; escalate_to?: string }>;
  limits: {
    task_budget_usd?: number;
    daily_budget_usd?: number;
    max_attempts_per_tier?: number;
    max_parallel_workers?: number;
  };
  harness: string;
  multi_role_pipeline: boolean;
  poll_interval_sec: number;
  proving_repo_url: string;
  proving_repo_branch: string;
  kill_switch: boolean;
  ui?: Record<string, unknown>;
  updated_at?: string | null;
};

export type Plan = {
  id: string;
  product_id?: string | null;
  status: string;
  goals: unknown[];
  tickets: unknown[];
  diff: Record<string, unknown>;
  estimated_spend_usd: number | string;
};

export type EodDigest = {
  day: string;
  counts_by_state: Record<string, number>;
  merged: number;
  reviewing: number;
  blocked_human: number;
  parked: number;
  failed: number;
  spend_usd: number;
  open_hitl: number;
  recent_events: EventRow[];
  risks: string[];
};

export type OfficeMap = {
  id: string;
  width: number;
  height: number;
  tile: number;
  zones: Record<string, { x: number; y: number; label: string }>;
  roles: Record<string, { color: string }>;
};
