import type { EodDigest, EventRow, HumanItem, Plan, RuntimeSettings, Task } from "./types";

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

export const orch = {
  health: () => api<{ status: string; kill_switch: boolean; version: string }>("/health"),
  tasks: (limit = 100) => api<Task[]>(`/tasks?limit=${limit}`),
  events: (since = 0) => api<EventRow[]>(`/events?since=${since}&limit=200`),
  hitl: (status = "open") => api<HumanItem[]>(`/hitl?status=${encodeURIComponent(status)}`),
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
  eod: (day?: string) =>
    api<EodDigest>(day ? `/digest/eod?day=${encodeURIComponent(day)}` : "/digest/eod"),
};
