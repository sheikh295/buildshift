import type {
  CtoChatMessage,
  EodDigest,
  EventRow,
  HitlTree,
  HumanItem,
  Plan,
  Project,
  ProjectDetail,
  RuntimeSettings,
  Sprint,
  SprintDetail,
  Task,
  UsageReport,
} from "./types";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/orch${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | undefined | null>) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const orch = {
  health: () => api<{ status: string; kill_switch: boolean; version: string }>("/health"),
  tasks: (limit = 100, opts?: { project_id?: string; sprint_id?: string }) =>
    api<Task[]>(
      `/tasks${qs({ limit, project_id: opts?.project_id, sprint_id: opts?.sprint_id })}`
    ),
  events: (since = 0) => api<EventRow[]>(`/events?since=${since}&limit=200`),
  hitl: (status = "open") => api<HumanItem[]>(`/hitl?status=${encodeURIComponent(status)}`),
  hitlTree: (status = "open") =>
    api<HitlTree>(`/hitl?status=${encodeURIComponent(status)}&group=tree`),
  replyHitl: (id: string, reply: string) =>
    api<HumanItem>(`/hitl/${id}/reply`, { method: "POST", body: JSON.stringify({ reply }) }),
  createHitl: (summary: string, kind = "question") =>
    api<HumanItem>("/hitl", {
      method: "POST",
      body: JSON.stringify({ summary, kind }),
    }),
  settings: () => api<RuntimeSettings>("/control/settings"),
  putSettings: (patch: Partial<RuntimeSettings>) =>
    api<RuntimeSettings>("/control/settings", { method: "PUT", body: JSON.stringify(patch) }),
  kill: (enabled: boolean) =>
    api<{ enabled: boolean }>("/control/kill", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  projects: () => api<Project[]>("/projects"),
  createProject: (title: string, slug?: string) =>
    api<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ title, slug: slug || null }),
    }),
  project: (id: string) => api<ProjectDetail>(`/projects/${id}`),
  connectRepo: (projectId: string, repoUrl: string, repoBranch = "main", sync = true) =>
    api<Project>(`/projects/${projectId}/repo`, {
      method: "PUT",
      body: JSON.stringify({ repo_url: repoUrl, repo_branch: repoBranch, sync }),
    }),
  syncRepo: (projectId: string) =>
    api<Project>(`/projects/${projectId}/repo/sync`, { method: "POST" }),
  uploadPrd: (projectId: string, markdown: string, sourceName = "uploaded.md") =>
    api<{ project_id: string; modules: number; module_ids: string[] }>(
      `/projects/${projectId}/prd`,
      { method: "POST", body: JSON.stringify({ markdown, source_name: sourceName }) }
    ),
  reindexPrd: (projectId: string) =>
    api<{ project_id: string; modules: number; module_ids: string[] }>(
      `/projects/${projectId}/reindex`,
      { method: "POST" }
    ),
  ctoChatHistory: (projectId: string) =>
    api<CtoChatMessage[]>(`/projects/${projectId}/cto/chat`),
  ctoChat: (projectId: string, message: string) =>
    api<{
      reply: CtoChatMessage;
      history: CtoChatMessage[];
      applied_actions: unknown[];
    }>(`/projects/${projectId}/cto/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  ctoChatClear: (projectId: string) =>
    api<void>(`/projects/${projectId}/cto/chat`, { method: "DELETE" }),
  sprints: (projectId: string) => api<Sprint[]>(`/projects/${projectId}/sprints`),
  proposeSprint: (projectId: string, capacityHours: number) =>
    api<Sprint>(`/projects/${projectId}/sprints/propose`, {
      method: "POST",
      body: JSON.stringify({ capacity_hours: capacityHours, mode: "hours" }),
    }),
  sprint: (id: string) => api<SprintDetail>(`/sprints/${id}`),
  kickoffSprint: (id: string) =>
    api<{ sprint_id: string; status: string; task_ids: string[]; task_count: number }>(
      `/sprints/${id}/kickoff`,
      { method: "POST" }
    ),
  pauseSprint: (id: string) =>
    api<{ sprint_id: string; status: string; inflight: number; message: string }>(
      `/sprints/${id}/pause`,
      { method: "POST" }
    ),
  resumeSprint: (id: string) =>
    api<{ sprint_id: string; status: string; task_ids: string[]; task_count: number }>(
      `/sprints/${id}/resume`,
      { method: "POST" }
    ),
  products: () =>
    api<{ id: string; slug: string; title: string; status?: string }[]>("/prd/products"),
  indexPrd: (markdown: string, sourceName = "uploaded.md") =>
    api<{ products: { id: string; slug: string; title: string; status?: string }[] }>(
      "/prd/index",
      {
        method: "POST",
        body: JSON.stringify({ markdown, source_name: sourceName }),
      }
    ),
  kickoff: (productId: string) =>
    api<{ product_id: string; slug: string; requirements: number; human_items: number }>(
      `/products/${productId}/kickoff`,
      { method: "POST" }
    ),
  proposePlan: (productId: string, maxTickets = 3) =>
    api<Plan>("/plans/propose", {
      method: "POST",
      body: JSON.stringify({ product_id: productId, max_tickets: maxTickets }),
    }),
  getPlan: (id: string) => api<Plan>(`/plans/${id}`),
  approvePlan: (id: string) =>
    api<{ plan_id: string; task_ids: string[]; status: string }>(`/plans/${id}/approve`, {
      method: "POST",
    }),
  eod: (day?: string, projectId?: string) =>
    api<EodDigest>(
      `/digest/eod${qs({ day, project_id: projectId })}`
    ),
  usage: (opts: {
    from?: string;
    to?: string;
    project_id?: string;
    sprint_id?: string;
    group_by?: string;
  }) =>
    api<UsageReport>(
      `/usage${qs({
        from: opts.from,
        to: opts.to,
        project_id: opts.project_id,
        sprint_id: opts.sprint_id,
        group_by: opts.group_by || "day",
      })}`
    ),
};
