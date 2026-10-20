"use client";

import { useEffect, useState } from "react";
import { orch } from "@/lib/api";
import type {
  CtoChatMessage,
  EodDigest,
  HitlTree,
  Project,
  ProjectDetail,
  RuntimeSettings,
  Selection,
  Sprint,
  SprintDetail,
  Task,
  UsageReport,
} from "@/lib/types";

type Panel =
  | "projects"
  | "inbox"
  | "plan"
  | "board"
  | "eod"
  | "usage"
  | "control"
  | "cto"
  | null;

function formatGoals(goals: unknown): string {
  if (!goals) return "";
  if (typeof goals === "string") return goals;
  if (Array.isArray(goals)) {
    return goals
      .map((g) => {
        if (typeof g === "string") return g;
        if (g && typeof g === "object" && "text" in g) return String((g as { text: unknown }).text);
        return JSON.stringify(g);
      })
      .filter(Boolean)
      .join("\n");
  }
  return String(goals);
}

function TaskBody({ task }: { task: Task }) {
  const criteria = (task.acceptance_criteria || "").trim();
  const paths = task.owned_paths || [];
  return (
    <>
      {criteria ? (
        <>
          <dt>What / criteria</dt>
          <dd className="body-text">{criteria}</dd>
        </>
      ) : (
        <>
          <dt>What / criteria</dt>
          <dd className="muted">No acceptance criteria on this task.</dd>
        </>
      )}
      {paths.length > 0 && (
        <>
          <dt>Owned paths</dt>
          <dd>
            <code>{paths.join(", ")}</code>
          </dd>
        </>
      )}
    </>
  );
}

const PROJECT_KEY = "bs-selected-project";

type Props = {
  tasks: Task[];
  selection: Selection;
  onCloseInspector: () => void;
  onRefresh: () => void;
};

function useSelectedProject() {
  const [projectId, setProjectId] = useState(() => {
    if (typeof window === "undefined") return "";
    return sessionStorage.getItem(PROJECT_KEY) || "";
  });
  const select = (id: string) => {
    setProjectId(id);
    sessionStorage.setItem(PROJECT_KEY, id);
  };
  return [projectId, select] as const;
}

export function Hud({ tasks, selection, onCloseInspector, onRefresh }: Props) {
  const [panel, setPanel] = useState<Panel>(null);
  const [projectId, setProjectId] = useSelectedProject();

  return (
    <>
      <nav className="hud-bar">
        <span className="brand">Buildshift</span>
        {(
          [
            ["projects", "Projects"],
            ["inbox", "Inbox"],
            ["plan", "Plan"],
            ["board", "Board"],
            ["eod", "EOD"],
            ["usage", "Usage"],
            ["control", "Control"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            className={panel === id ? "active" : ""}
            type="button"
            onClick={() => setPanel(panel === id ? null : id)}
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          className="ghost"
          onClick={async () => {
            await fetch("/api/auth/logout", { method: "POST" });
            window.location.href = "/login";
          }}
        >
          Logout
        </button>
      </nav>

      {selection?.kind === "task" && (
        <aside className="inspector">
          <header>
            <strong>Task</strong>
            <button type="button" onClick={onCloseInspector}>
              ×
            </button>
          </header>
          <h3>{selection.task.title}</h3>
          <dl>
            <dt>State</dt>
            <dd>{selection.task.state}</dd>
            <dt>Role / stage</dt>
            <dd>
              {selection.task.role} / {selection.task.stage || "—"}
            </dd>
            <dt>Spend</dt>
            <dd>
              {selection.task.spent_usd} / {selection.task.budget_usd} USD
            </dd>
            <dt>Sprint / epic</dt>
            <dd>
              {selection.task.sprint_id?.slice(0, 8) || "—"} / {selection.task.parent_epic || "—"}
            </dd>
            <TaskBody task={selection.task} />
            <dt>Branch</dt>
            <dd>{selection.task.branch || "—"}</dd>
            <dt>PR</dt>
            <dd>
              {selection.task.pr_url ? (
                <a href={selection.task.pr_url} target="_blank" rel="noreferrer">
                  open
                </a>
              ) : (
                "—"
              )}
            </dd>
            {selection.task.error && (
              <>
                <dt>Error</dt>
                <dd>{selection.task.error}</dd>
              </>
            )}
          </dl>
        </aside>
      )}

      {selection?.kind === "agent" && (
        <aside className="inspector">
          <header>
            <strong>Session</strong>
            <button type="button" onClick={onCloseInspector}>
              ×
            </button>
          </header>
          <h3>{selection.agent.name}</h3>
          <dl>
            <dt>Role</dt>
            <dd>{selection.agent.role}</dd>
            <dt>Cabin</dt>
            <dd>{selection.agent.cabinId}</dd>
            <dt>Status</dt>
            <dd>{selection.agent.status}</dd>
            <dt>Staff</dt>
            <dd>{selection.agent.permanent ? "permanent" : "hired"}</dd>
            <dt>Working on</dt>
            <dd>{selection.agent.taskTitle || "— idle / roaming —"}</dd>
          </dl>
          {(selection.agent.role === "planner" ||
            selection.agent.name === "CTO" ||
            selection.agent.cabinId === "planner") && (
            <div className="inspector-actions">
              <button type="button" onClick={() => setPanel("cto")}>
                Chat with CTO
              </button>
            </div>
          )}
          {selection.task && (
            <>
              <h3 className="sub">Linked task</h3>
              <dl>
                <dt>Title</dt>
                <dd>{selection.task.title}</dd>
                <dt>State</dt>
                <dd>{selection.task.state}</dd>
                <TaskBody task={selection.task} />
                <dt>Spend</dt>
                <dd>
                  {selection.task.spent_usd} / {selection.task.budget_usd}
                </dd>
              </dl>
            </>
          )}
        </aside>
      )}

      {panel && (
        <div className="drawer">
          <header>
            <strong>{panel === "cto" ? "CTO CHAT" : panel.toUpperCase()}</strong>
            <button type="button" onClick={() => setPanel(null)}>
              ×
            </button>
          </header>
          {panel === "projects" && (
            <ProjectsPanel projectId={projectId} onSelect={setProjectId} onChange={onRefresh} />
          )}
          {panel === "inbox" && <InboxPanel onChange={onRefresh} />}
          {panel === "plan" && (
            <PlanPanel projectId={projectId} onSelect={setProjectId} onChange={onRefresh} />
          )}
          {panel === "board" && (
            <BoardPanel projectId={projectId} onSelect={setProjectId} tasks={tasks} />
          )}
          {panel === "eod" && <EodPanel projectId={projectId} onSelect={setProjectId} />}
          {panel === "usage" && <UsagePanel projectId={projectId} onSelect={setProjectId} />}
          {panel === "control" && <ControlPanel onChange={onRefresh} />}
          {panel === "cto" && (
            <CtoChatPanel projectId={projectId} onSelect={setProjectId} onChange={onRefresh} />
          )}
        </div>
      )}
    </>
  );
}

function CtoChatPanel({
  projectId,
  onSelect,
  onChange,
}: {
  projectId: string;
  onSelect: (id: string) => void;
  onChange: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [history, setHistory] = useState<CtoChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [applied, setApplied] = useState("");

  const load = async (id: string) => {
    if (!id) {
      setHistory([]);
      return;
    }
    setHistory(await orch.ctoChatHistory(id));
  };

  useEffect(() => {
    orch.projects().then(setProjects).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    load(projectId).catch((e) => setErr(String(e)));
  }, [projectId]);

  return (
    <div className="panel-body cto-chat">
      <p className="muted">
        You are the Boss. Talk to your CTO about this project — priorities, tickets, sprints,
        blockers, or new work to schedule.
      </p>
      <ProjectSelect projectId={projectId} onSelect={onSelect} projects={projects} />
      <div className="row">
        <button
          type="button"
          className="ghost"
          disabled={!projectId || busy || history.length === 0}
          onClick={async () => {
            if (!projectId) return;
            setBusy(true);
            setErr("");
            try {
              await orch.ctoChatClear(projectId);
              setHistory([]);
              setApplied("");
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Clear chat
        </button>
      </div>

      <div className="chat-log">
        {history.length === 0 && (
          <p className="muted">No messages yet. Pick a project and ask the CTO anything.</p>
        )}
        {history.map((m) => (
          <div key={m.id} className={`chat-bubble ${m.role === "user" ? "you" : "cto"}`}>
            <div className="chat-who">{m.role === "user" ? "You (Boss)" : "CTO"}</div>
            <div className="body-text">{m.content}</div>
            {!!(m.actions && m.actions.length) && (
              <p className="muted">Applied: {JSON.stringify(m.actions)}</p>
            )}
          </div>
        ))}
      </div>

      <label>
        Message
        <textarea
          rows={3}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. What's left in the current sprint? Add a ticket to fix the login redirect."
          disabled={!projectId || busy}
        />
      </label>
      <button
        type="button"
        disabled={!projectId || !draft.trim() || busy}
        onClick={async () => {
          if (!projectId) return;
          setBusy(true);
          setErr("");
          setApplied("");
          try {
            const r = await orch.ctoChat(projectId, draft.trim());
            setDraft("");
            setHistory(r.history);
            if (r.applied_actions?.length) {
              setApplied(`CTO applied ${r.applied_actions.length} change(s)`);
              onChange();
            }
          } catch (e) {
            setErr(String(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "CTO thinking…" : "Send"}
      </button>
      {err && <p className="err">{err}</p>}
      {applied && <p className="muted">{applied}</p>}
    </div>
  );
}

function ProjectSelect({
  projectId,
  onSelect,
  projects,
}: {
  projectId: string;
  onSelect: (id: string) => void;
  projects: Project[];
}) {
  return (
    <label>
      Project
      <select value={projectId} onChange={(e) => onSelect(e.target.value)}>
        <option value="">Select project…</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.title}
          </option>
        ))}
      </select>
    </label>
  );
}

function ProjectsPanel({
  projectId,
  onSelect,
  onChange,
}: {
  projectId: string;
  onSelect: (id: string) => void;
  onChange: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [title, setTitle] = useState("");
  const [markdown, setMarkdown] = useState("");
  const [sourceName, setSourceName] = useState("prd.md");
  const [repoUrl, setRepoUrl] = useState("");
  const [repoBranch, setRepoBranch] = useState("main");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async (prefer?: string) => {
    const list = await orch.projects();
    setProjects(list);
    const id = prefer || projectId || list[0]?.id || "";
    if (id) {
      onSelect(id);
      const d = await orch.project(id);
      setDetail(d);
      setRepoUrl(d.project.repo_url || "");
      setRepoBranch(d.project.repo_branch || "main");
    } else setDetail(null);
  };

  useEffect(() => {
    load().catch((e) => setErr(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!projectId) return;
    orch
      .project(projectId)
      .then((d) => {
        setDetail(d);
        setRepoUrl(d.project.repo_url || "");
        setRepoBranch(d.project.repo_branch || "main");
      })
      .catch((e) => setErr(String(e)));
  }, [projectId]);

  return (
    <div className="panel-body">
      <fieldset>
        <legend>New project</legend>
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="My product" />
        </label>
        <button
          type="button"
          disabled={!title.trim() || busy}
          onClick={async () => {
            setBusy(true);
            setErr("");
            try {
              const p = await orch.createProject(title.trim());
              setTitle("");
              setMsg(`Created ${p.title}`);
              await load(p.id);
              onChange();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Create
        </button>
      </fieldset>

      <ProjectSelect projectId={projectId} onSelect={onSelect} projects={projects} />

      {detail && (
        <>
          <p className="muted">
            {detail.modules.length} modules · {detail.sprint_count} sprints · {detail.open_hitl} open
            HITL · PRD {detail.project.has_prd ? "uploaded" : "missing"} · repo{" "}
            {detail.project.has_repo ? "connected" : "not set"}
          </p>
          <fieldset>
            <legend>Git repository</legend>
            <p className="muted">
              Workers clone this remote into a local mirror under{" "}
              <code>data/repos/{detail.project.slug}</code>, then each task gets an isolated
              checkout. Use a GitHub URL or an absolute path to a local git repo.
            </p>
            <label>
              Clone URL / path
              <input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/org/app.git or /path/to/repo"
              />
            </label>
            <label>
              Base branch
              <input value={repoBranch} onChange={(e) => setRepoBranch(e.target.value)} />
            </label>
            {detail.project.repo_path && (
              <p className="muted">
                Mirror: <code>{detail.project.repo_path}</code>
                {detail.project.repo_synced_at
                  ? ` · synced ${new Date(detail.project.repo_synced_at).toLocaleString()}`
                  : ""}
              </p>
            )}
            <div className="row">
              <button
                type="button"
                disabled={!projectId || !repoUrl.trim() || busy}
                onClick={async () => {
                  setBusy(true);
                  setErr("");
                  try {
                    const p = await orch.connectRepo(
                      projectId,
                      repoUrl.trim(),
                      repoBranch.trim() || "main",
                      true
                    );
                    setMsg(`Repo connected · ${p.repo_path || "ok"}`);
                    setDetail(await orch.project(projectId));
                    onChange();
                  } catch (e) {
                    setErr(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Connect &amp; sync
              </button>
              <button
                type="button"
                disabled={!projectId || !detail.project.has_repo || busy}
                onClick={async () => {
                  setBusy(true);
                  setErr("");
                  try {
                    const p = await orch.syncRepo(projectId);
                    setMsg(`Synced · ${p.repo_path || "ok"}`);
                    setDetail(await orch.project(projectId));
                    onChange();
                  } catch (e) {
                    setErr(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Sync now
              </button>
            </div>
          </fieldset>
          {detail.modules.length > 0 && (
            <ul className="tree">
              {detail.modules.map((m) => (
                <li key={m.id}>
                  <span className="tag">{m.status}</span> {m.title}
                </li>
              ))}
            </ul>
          )}
          <fieldset>
            <legend>PRD</legend>
            <label>
              File
              <input
                type="file"
                accept=".md,.markdown,text/markdown,text/plain"
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  setSourceName(f.name);
                  setMarkdown(await f.text());
                }}
              />
            </label>
            <label>
              Markdown
              <textarea
                rows={7}
                value={markdown}
                onChange={(e) => setMarkdown(e.target.value)}
                placeholder="## Module&#10;1. Requirement…"
              />
            </label>
            <div className="row">
              <button
                type="button"
                disabled={!projectId || !markdown.trim() || busy}
                onClick={async () => {
                  setBusy(true);
                  setErr("");
                  try {
                    const r = await orch.uploadPrd(projectId, markdown, sourceName);
                    setMsg(`Indexed ${r.modules} module(s)`);
                    setDetail(await orch.project(projectId));
                    onChange();
                  } catch (e) {
                    setErr(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Upload / replace PRD
              </button>
              <button
                type="button"
                disabled={!projectId || busy}
                onClick={async () => {
                  setBusy(true);
                  setErr("");
                  try {
                    const r = await orch.reindexPrd(projectId);
                    setMsg(`Reindexed ${r.modules} module(s)`);
                    setDetail(await orch.project(projectId));
                    onChange();
                  } catch (e) {
                    setErr(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Reindex
              </button>
            </div>
          </fieldset>
        </>
      )}
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
    </div>
  );
}

function InboxPanel({ onChange }: { onChange: () => void }) {
  const [tree, setTree] = useState<HitlTree | null>(null);
  const [openProj, setOpenProj] = useState<Record<string, boolean>>({});
  const [openSprint, setOpenSprint] = useState<Record<string, boolean>>({});
  const [reply, setReply] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");

  const load = () =>
    orch
      .hitlTree("open")
      .then(setTree)
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
  }, []);

  if (!tree) return <p className="panel-body muted">Loading…</p>;

  return (
    <div className="panel-body">
      {err && <p className="err">{err}</p>}
      {tree.projects.length === 0 && <p className="muted">No open HITL items.</p>}
      {tree.projects.map((proj) => {
        const pk = proj.project_id || "none";
        return (
          <div key={pk} className="tree-node">
            <button
              type="button"
              className="tree-toggle"
              onClick={() => setOpenProj({ ...openProj, [pk]: !openProj[pk] })}
            >
              {openProj[pk] ? "▼" : "▶"} {proj.project_title}{" "}
              <span className="tag">{proj.count}</span>
            </button>
            {openProj[pk] &&
              proj.sprints.map((sp) => {
                const sk = `${pk}:${sp.sprint_id || "none"}`;
                return (
                  <div key={sk} className="tree-node nest">
                    <button
                      type="button"
                      className="tree-toggle"
                      onClick={() => setOpenSprint({ ...openSprint, [sk]: !openSprint[sk] })}
                    >
                      {openSprint[sk] ? "▼" : "▶"} {sp.sprint_label}{" "}
                      <span className="tag">{sp.count}</span>
                    </button>
                    {openSprint[sk] &&
                      sp.items.map((item) => (
                        <div key={item.id} className="card-row nest">
                          <div>
                            <span className="tag">{item.kind}</span> {item.summary}
                          </div>
                          <textarea
                            rows={2}
                            placeholder="Reply…"
                            value={reply[item.id] || ""}
                            onChange={(e) => setReply({ ...reply, [item.id]: e.target.value })}
                          />
                          <button
                            type="button"
                            onClick={async () => {
                              await orch.replyHitl(item.id, reply[item.id] || "ack");
                              await load();
                              onChange();
                            }}
                          >
                            Reply & unblock
                          </button>
                        </div>
                      ))}
                  </div>
                );
              })}
          </div>
        );
      })}
    </div>
  );
}

function PlanPanel({
  projectId,
  onSelect,
  onChange,
}: {
  projectId: string;
  onSelect: (id: string) => void;
  onChange: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [detail, setDetail] = useState<SprintDetail | null>(null);
  const [hours, setHours] = useState(6);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    orch.projects().then(setProjects).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!projectId) {
      setSprints([]);
      setDetail(null);
      return;
    }
    orch
      .sprints(projectId)
      .then((list) => {
        setSprints(list);
        if (list[0]) orch.sprint(list[0].id).then(setDetail);
        else setDetail(null);
      })
      .catch((e) => setErr(String(e)));
  }, [projectId]);

  return (
    <div className="panel-body">
      <ProjectSelect projectId={projectId} onSelect={onSelect} projects={projects} />
      <p className="muted">
        <strong>Propose</strong> builds a sprint (tasks stay planned).{" "}
        <strong>Kick off</strong> starts that sprint — tasks become ready for workers. Hours = planning
        ceiling (1–40); short remaining work finishes early (not padded).
      </p>
      <label>
        Sprint size (hours)
        <input
          type="number"
          min={1}
          max={40}
          step={1}
          value={hours}
          onChange={(e) => setHours(Math.min(40, Math.max(1, Number(e.target.value) || 1)))}
        />
      </label>
      <div className="row">
        <button
          type="button"
          disabled={!projectId || busy}
          onClick={async () => {
            setBusy(true);
            setErr("");
            try {
              const sp = await orch.proposeSprint(projectId, hours);
              setMsg(`Proposed sprint ${sp.id.slice(0, 8)} · ~${sp.estimated_hours}h of ≤${hours}h`);
              const list = await orch.sprints(projectId);
              setSprints(list);
              setDetail(await orch.sprint(sp.id));
              onChange();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Propose sprint
        </button>
        <button
          type="button"
          disabled={
            !detail ||
            (detail.sprint.status !== "planned" && detail.sprint.status !== "draft") ||
            busy
          }
          title="Start workers on this proposed sprint"
          onClick={async () => {
            if (!detail) return;
            setBusy(true);
            setErr("");
            try {
              const r = await orch.kickoffSprint(detail.sprint.id);
              setMsg(`Kicked off · ${r.task_count} tasks ready for agents`);
              setDetail(await orch.sprint(detail.sprint.id));
              setSprints(await orch.sprints(projectId));
              onChange();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Kick off sprint
        </button>
      </div>
      <div className="row">
        <button
          type="button"
          disabled={!detail || detail.sprint.status !== "active" || busy}
          onClick={async () => {
            if (!detail) return;
            setBusy(true);
            setErr("");
            try {
              const r = await orch.pauseSprint(detail.sprint.id);
              setMsg(r.message);
              setDetail(await orch.sprint(detail.sprint.id));
              setSprints(await orch.sprints(projectId));
              onChange();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Pause sprint
        </button>
        <button
          type="button"
          disabled={
            !detail ||
            (detail.sprint.status !== "paused" && detail.sprint.status !== "pausing") ||
            busy
          }
          onClick={async () => {
            if (!detail) return;
            setBusy(true);
            setErr("");
            try {
              const r = await orch.resumeSprint(detail.sprint.id);
              setMsg(`Resumed · ${r.task_count} tasks ready`);
              setDetail(await orch.sprint(detail.sprint.id));
              setSprints(await orch.sprints(projectId));
              onChange();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Resume sprint
        </button>
      </div>

      <label>
        History
        <select
          value={detail?.sprint.id || ""}
          onChange={async (e) => {
            if (!e.target.value) return;
            setDetail(await orch.sprint(e.target.value));
          }}
        >
          {sprints.length === 0 && <option value="">No sprints yet</option>}
          {sprints.map((s) => (
            <option key={s.id} value={s.id}>
              {s.status} · ≤{s.capacity_hours}h · ~{s.estimated_hours}h · {s.created_at?.slice(0, 10)}
            </option>
          ))}
        </select>
      </label>

      {detail && (
        <div className="tree">
          <p>
            <span className="tag">{detail.sprint.status}</span> est {detail.sprint.estimated_hours}h /
            ceiling {detail.sprint.capacity_hours}h · ${detail.sprint.estimated_spend_usd}
          </p>
          {formatGoals(detail.sprint.goals) && (
            <div className="card-row">
              <h4>Sprint goals</h4>
              <pre className="body-text">{formatGoals(detail.sprint.goals)}</pre>
            </div>
          )}
          {detail.epics.map((block) => (
            <div key={block.epic.id} className="tree-node">
              <strong>{block.epic.title}</strong>
              {block.epic.summary ? (
                <p className="body-text muted">{block.epic.summary}</p>
              ) : null}
              <ul>
                {block.tasks.map((t) => (
                  <li key={t.id}>
                    <span className="tag">{t.state}</span> {t.title}
                    {t.acceptance_criteria ? (
                      <div className="body-text muted">{t.acceptance_criteria}</div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
    </div>
  );
}

function BoardPanel({
  projectId,
  onSelect,
  tasks,
}: {
  projectId: string;
  onSelect: (id: string) => void;
  tasks: Task[];
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [detail, setDetail] = useState<SprintDetail | null>(null);
  const [taskFocus, setTaskFocus] = useState<Task | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    orch.projects().then(setProjects).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!projectId) {
      setSprints([]);
      setDetail(null);
      return;
    }
    orch
      .sprints(projectId)
      .then(async (list) => {
        setSprints(list);
        if (list[0]) setDetail(await orch.sprint(list[0].id));
        else setDetail(null);
      })
      .catch((e) => setErr(String(e)));
  }, [projectId]);

  const scoped = projectId ? tasks.filter((t) => t.project_id === projectId) : tasks;

  return (
    <div className="panel-body">
      <ProjectSelect projectId={projectId} onSelect={onSelect} projects={projects} />
      {err && <p className="err">{err}</p>}
      <label>
        Sprint
        <select
          value={detail?.sprint.id || ""}
          onChange={async (e) => {
            if (!e.target.value) return;
            setDetail(await orch.sprint(e.target.value));
            setTaskFocus(null);
          }}
        >
          {sprints.length === 0 && <option value="">No sprints</option>}
          {sprints.map((s) => (
            <option key={s.id} value={s.id}>
              {s.status} · ≤{s.capacity_hours}h · {s.created_at?.slice(0, 10)}
            </option>
          ))}
        </select>
      </label>

      {detail ? (
        <div className="tree">
          {formatGoals(detail.sprint.goals) && (
            <div className="card-row">
              <h4>Sprint goals</h4>
              <pre className="body-text">{formatGoals(detail.sprint.goals)}</pre>
            </div>
          )}
          {detail.epics.map((block) => (
            <div key={block.epic.id} className="tree-node">
              <strong>
                Epic · {block.epic.title} <span className="tag">{block.epic.status}</span>
              </strong>
              {block.epic.summary ? (
                <p className="body-text">{block.epic.summary}</p>
              ) : null}
              <ul>
                {block.tasks.map((t) => {
                  const live = scoped.find((x) => x.id === t.id) || t;
                  return (
                    <li key={t.id}>
                      <button type="button" className="linkish" onClick={() => setTaskFocus(live)}>
                        <span className="tag">{live.state}</span> {live.title}
                      </button>
                      {live.acceptance_criteria ? (
                        <div className="body-text muted">{live.acceptance_criteria}</div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">Select a project with sprints to see hierarchy.</p>
      )}

      {taskFocus && (
        <div className="card-row">
          <h4>{taskFocus.title}</h4>
          <dl>
            <dt>State</dt>
            <dd>{taskFocus.state}</dd>
            <dt>Role / stage</dt>
            <dd>
              {taskFocus.role} / {taskFocus.stage || "—"}
            </dd>
            <TaskBody task={taskFocus} />
            <dt>Spend</dt>
            <dd>
              {taskFocus.spent_usd} / {taskFocus.budget_usd}
            </dd>
            <dt>Branch</dt>
            <dd>{taskFocus.branch || "—"}</dd>
            {taskFocus.error && (
              <>
                <dt>Error</dt>
                <dd>{taskFocus.error}</dd>
              </>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}

function EodPanel({
  projectId,
  onSelect,
}: {
  projectId: string;
  onSelect: (id: string) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10));
  const [digest, setDigest] = useState<EodDigest | null>(null);
  const [taskFocus, setTaskFocus] = useState<Task | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    orch.projects().then(setProjects).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    orch
      .eod(day, projectId || undefined)
      .then(setDigest)
      .catch((e) => setErr(String(e)));
  }, [day, projectId]);

  return (
    <div className="panel-body">
      <ProjectSelect projectId={projectId} onSelect={onSelect} projects={projects} />
      <label>
        Day
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      </label>
      {err && <p className="err">{err}</p>}
      {!digest && <p className="muted">Loading…</p>}
      {digest && (
        <>
          <pre className="code">
            {[
              `EOD ${digest.day}`,
              `merged=${digest.merged} reviewing=${digest.reviewing} blocked=${digest.blocked_human}`,
              `parked=${digest.parked} failed=${digest.failed} spend=$${digest.spend_usd}`,
              `open_hitl=${digest.open_hitl}`,
              ...digest.risks.map((r) => `risk: ${r}`),
            ].join("\n")}
          </pre>
          <h4>Agents</h4>
          <ul>
            {(digest.agents || []).map((a) => (
              <li key={a.role}>
                {a.role}: {a.runs} runs · {Math.round(a.duration_sec / 60)}m · ${a.cost_usd.toFixed(2)}
              </li>
            ))}
            {(digest.agents || []).length === 0 && <li className="muted">No sessions this day</li>}
          </ul>
          <h4>Sessions</h4>
          <ul>
            {(digest.sessions || []).slice(0, 30).map((s) => (
              <li key={s.run_id}>
                {s.role} · {s.task_title} · {s.status} · ${s.cost_usd} ·{" "}
                {s.duration_sec != null ? `${Math.round(s.duration_sec)}s` : "—"}
              </li>
            ))}
          </ul>
          <h4>Hierarchy</h4>
          {(digest.hierarchy || []).map((h) => (
            <div key={h.sprint.id} className="tree-node">
              <strong>
                Sprint {h.sprint.status} · ≤{h.sprint.capacity_hours}h
              </strong>
              {h.epics.map((b) => (
                <div key={b.epic.id} className="nest">
                  <div>{b.epic.title}</div>
                  <ul>
                    {b.tasks.map((t) => (
                      <li key={t.id}>
                        <button type="button" className="linkish" onClick={() => setTaskFocus(t)}>
                          <span className="tag">{t.state}</span> {t.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          ))}
          {taskFocus && (
            <div className="card-row">
              <h4>{taskFocus.title}</h4>
              <p>
                {taskFocus.state} · {taskFocus.role} · ${taskFocus.spent_usd}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function UsagePanel({
  projectId,
  onSelect,
}: {
  projectId: string;
  onSelect: (id: string) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sprints, setSprints] = useState<Sprint[]>([]);
  const [sprintId, setSprintId] = useState("");
  const [from, setFrom] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  });
  const [to, setTo] = useState(() => new Date().toISOString().slice(0, 10));
  const [groupBy, setGroupBy] = useState("day");
  const [report, setReport] = useState<UsageReport | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    orch.projects().then(setProjects).catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    if (!projectId) {
      setSprints([]);
      setSprintId("");
      return;
    }
    orch.sprints(projectId).then(setSprints).catch((e) => setErr(String(e)));
  }, [projectId]);

  useEffect(() => {
    orch
      .usage({
        from,
        to,
        project_id: projectId || undefined,
        sprint_id: sprintId || undefined,
        group_by: groupBy,
      })
      .then(setReport)
      .catch((e) => setErr(String(e)));
  }, [from, to, projectId, sprintId, groupBy]);

  return (
    <div className="panel-body">
      <ProjectSelect projectId={projectId} onSelect={onSelect} projects={projects} />
      <label>
        Sprint
        <select value={sprintId} onChange={(e) => setSprintId(e.target.value)}>
          <option value="">All sprints</option>
          {sprints.map((s) => (
            <option key={s.id} value={s.id}>
              {s.status} · {s.created_at?.slice(0, 10)}
            </option>
          ))}
        </select>
      </label>
      <div className="row">
        <label>
          From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
      </div>
      <label>
        Group by
        <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
          <option value="day">Day</option>
          <option value="project">Project</option>
          <option value="sprint">Sprint</option>
          <option value="epic">Epic</option>
          <option value="task">Task</option>
          <option value="run">Session / run</option>
          <option value="role">Agent / role</option>
          <option value="model">Model</option>
        </select>
      </label>
      {err && <p className="err">{err}</p>}
      {report && (
        <>
          <p>
            Total ${report.total_cost_usd.toFixed(4)} · tokens in {report.total_tokens_in} / out{" "}
            {report.total_tokens_out}
          </p>
          <h4>By model</h4>
          <ul>
            {Object.entries(report.model_totals).map(([m, c]) => (
              <li key={m}>
                {m}: ${c.toFixed(4)}
              </li>
            ))}
            {Object.keys(report.model_totals).length === 0 && (
              <li className="muted">No model spend recorded yet</li>
            )}
          </ul>
          <h4>Buckets</h4>
          <ul>
            {report.buckets.map((b) => (
              <li key={b.key}>
                <strong>{b.label}</strong> · ${b.cost_usd.toFixed(4)} · {b.run_count} runs · tok{" "}
                {b.tokens_in}/{b.tokens_out}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function ControlPanel({ onChange }: { onChange: () => void }) {
  const [s, setS] = useState<RuntimeSettings | null>(null);
  const [raw, setRaw] = useState("");
  const [msg, setMsg] = useState("");

  const load = () =>
    orch.settings().then((data) => {
      setS(data);
      setRaw(JSON.stringify(data, null, 2));
    });

  useEffect(() => {
    load();
  }, []);

  if (!s) return <p className="panel-body muted">Loading settings…</p>;

  const roles = s.roles || {};
  const limits = s.limits || {};

  return (
    <div className="panel-body control">
      <p className="muted">Control plane — changes apply without redeploy. Env holds secrets only.</p>
      <label>
        Harness
        <select value={s.harness} onChange={(e) => setS({ ...s, harness: e.target.value })}>
          <option value="mock">mock</option>
          <option value="claude">claude</option>
        </select>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={s.kill_switch}
          onChange={(e) => setS({ ...s, kill_switch: e.target.checked })}
        />
        Kill switch
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={s.multi_role_pipeline}
          onChange={(e) => setS({ ...s, multi_role_pipeline: e.target.checked })}
        />
        Multi-role pipeline
      </label>
      <fieldset>
        <legend>Limits</legend>
        {(
          [
            ["task_budget_usd", "Task budget USD"],
            ["daily_budget_usd", "Daily budget USD"],
            ["max_parallel_workers", "Max parallel workers"],
            ["max_attempts_per_tier", "Max attempts / tier"],
          ] as const
        ).map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              type="number"
              step="any"
              value={limits[key] ?? ""}
              onChange={(e) =>
                setS({
                  ...s,
                  limits: { ...limits, [key]: Number(e.target.value) },
                })
              }
            />
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Role → model</legend>
        {Object.entries(roles).map(([role, entry]) => (
          <label key={role}>
            {role}
            <input
              value={entry?.model || ""}
              onChange={(e) =>
                setS({
                  ...s,
                  roles: { ...roles, [role]: { ...entry, model: e.target.value } },
                })
              }
            />
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Proving</legend>
        <label>
          Repo URL
          <input
            value={s.proving_repo_url}
            onChange={(e) => setS({ ...s, proving_repo_url: e.target.value })}
          />
        </label>
        <label>
          Branch
          <input
            value={s.proving_repo_branch}
            onChange={(e) => setS({ ...s, proving_repo_branch: e.target.value })}
          />
        </label>
      </fieldset>
      <div className="row">
        <button
          type="button"
          onClick={async () => {
            const saved = await orch.putSettings({
              harness: s.harness,
              kill_switch: s.kill_switch,
              multi_role_pipeline: s.multi_role_pipeline,
              limits: s.limits,
              roles: s.roles,
              proving_repo_url: s.proving_repo_url,
              proving_repo_branch: s.proving_repo_branch,
              poll_interval_sec: s.poll_interval_sec,
            });
            setS(saved);
            setRaw(JSON.stringify(saved, null, 2));
            setMsg("Saved.");
            onChange();
          }}
        >
          Save
        </button>
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(raw);
            setMsg("Copied JSON.");
          }}
        >
          Export JSON
        </button>
      </div>
      <label>
        Import JSON
        <textarea rows={8} value={raw} onChange={(e) => setRaw(e.target.value)} />
      </label>
      <button
        type="button"
        onClick={async () => {
          const patch = JSON.parse(raw) as Partial<RuntimeSettings>;
          const saved = await orch.putSettings(patch);
          setS(saved);
          setRaw(JSON.stringify(saved, null, 2));
          setMsg("Imported.");
          onChange();
        }}
      >
        Apply import
      </button>
      {msg && <p className="muted">{msg}</p>}
    </div>
  );
}
