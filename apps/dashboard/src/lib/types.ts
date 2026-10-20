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
  attempts?: number;
  branch?: string | null;
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

export type CabinPermanent = {
  id: string;
  name: string;
  role: string;
  seat: number;
};

export type DeskPlacement = { seat: number; x: number; y: number };
export type SofaPlacement = { id: string; x: number; y: number; orient: "h" | "v" };

export type DoorPlacement = { x: number; y: number };

export type CabinDef = {
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  accent: string;
  permanent: CabinPermanent[];
  maxHire: number;
  hireRoles?: string[];
  hireStates?: string[];
  desks: DeskPlacement[];
  sofas?: SofaPlacement[];
  /** Hire/fire gate for dynamic cabins */
  door?: DoorPlacement;
  /** @deprecated grid fallback */
  deskRows?: number;
  deskCols?: number;
};

export type HallDef = {
  x: number;
  y: number;
  w: number;
  h: number;
  radius: number;
  corridorGap: number;
  wallThickness?: number;
};

export type OfficeMap = {
  id: string;
  width: number;
  height: number;
  tile: number;
  hall: HallDef;
  cabins: CabinDef[];
  roles: Record<string, { color: string; shirt?: string; skin?: string }>;
};

export type AgentInfo = {
  id: string;
  name: string;
  role: string;
  cabinId: string;
  status: "idle" | "working" | "roaming" | "hired" | "sitting" | "chatting" | "called";
  taskId?: string | null;
  taskTitle?: string | null;
  permanent: boolean;
};

export type Selection =
  | { kind: "task"; task: Task }
  | { kind: "agent"; agent: AgentInfo; task?: Task | null }
  | null;
