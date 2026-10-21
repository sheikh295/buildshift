export type Task = {
  id: string;
  title: string;
  state: string;
  tier: string;
  role: string;
  stage?: string | null;
  acceptance_criteria?: string;
  owned_paths?: string[];
  spent_usd: number | string;
  budget_usd: number | string;
  pr_url?: string | null;
  error?: string | null;
  review_verdict?: string | null;
  attempts?: number;
  branch?: string | null;
  project_id?: string | null;
  sprint_id?: string | null;
  epic_id?: string | null;
  product_id?: string | null;
  parent_epic?: string | null;
  pause_notes?: string | null;
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
  project_id?: string | null;
  sprint_id?: string | null;
  product_id?: string | null;
  kind: string;
  summary: string;
  status: string;
  reply?: string | null;
  needed_by?: string | null;
};

export type HitlTreeItem = {
  id: string;
  kind: string;
  summary: string;
  status: string;
  task_id?: string | null;
  needed_by?: string | null;
  created_at: string;
};

export type HitlSprintNode = {
  sprint_id: string | null;
  sprint_label: string;
  count: number;
  items: HitlTreeItem[];
};

export type HitlProjectNode = {
  project_id: string | null;
  project_title: string;
  count: number;
  sprints: HitlSprintNode[];
};

export type HitlTree = { projects: HitlProjectNode[] };

export type Project = {
  id: string;
  slug: string;
  title: string;
  status: string;
  prd_path?: string | null;
  has_prd?: boolean;
  context_markdown?: string;
  index_status?: string;
  index_error?: string | null;
  indexed_at?: string | null;
  repo_url?: string | null;
  repo_branch?: string;
  repo_path?: string | null;
  repo_synced_at?: string | null;
  has_repo?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type PrdModule = {
  id: string;
  project_id?: string | null;
  slug: string;
  title: string;
  summary: string;
  build_order: number;
  status: string;
};

export type ProjectDetail = {
  project: Project;
  modules: PrdModule[];
  sprint_count: number;
  open_hitl: number;
  open_backlog?: number;
};

export type Sprint = {
  id: string;
  project_id: string;
  mode: string;
  status: string;
  capacity_hours: number | string;
  goals: unknown[];
  estimated_spend_usd: number | string;
  estimated_hours: number | string;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
};

export type Epic = {
  id: string;
  sprint_id: string;
  project_id: string;
  product_id?: string | null;
  title: string;
  summary?: string;
  status: string;
  sort_order: number;
};

export type CtoChatMessage = {
  id: string;
  project_id: string;
  role: "user" | "assistant" | string;
  content: string;
  actions?: unknown[];
  cost_usd?: number | string;
  created_at: string;
};

export type SprintDetail = {
  sprint: Sprint;
  epics: { epic: Epic; tasks: Task[] }[];
  ungrouped_tasks: Task[];
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

export type EodSession = {
  run_id: string;
  task_id: string;
  task_title: string;
  role: string;
  model?: string | null;
  status: string;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  started_at?: string | null;
  ended_at?: string | null;
  duration_sec?: number | null;
};

export type EodDigest = {
  day: string;
  project_id?: string | null;
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
  sessions?: EodSession[];
  agents?: { role: string; runs: number; cost_usd: number; duration_sec: number }[];
  hierarchy?: {
    sprint: Sprint;
    epics: { epic: Epic; tasks: Task[] }[];
  }[];
};

export type UsageBucket = {
  key: string;
  label: string;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  run_count: number;
  models: Record<string, number>;
};

export type UsageReport = {
  from_day?: string | null;
  to_day?: string | null;
  group_by: string;
  total_cost_usd: number;
  total_tokens_in: number;
  total_tokens_out: number;
  buckets: UsageBucket[];
  model_totals: Record<string, number>;
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
  door?: DoorPlacement;
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
