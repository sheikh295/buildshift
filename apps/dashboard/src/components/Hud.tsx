"use client";

import { useEffect, useState } from "react";
import { orch } from "@/lib/api";
import type { EodDigest, HumanItem, Plan, RuntimeSettings, Task } from "@/lib/types";

type Panel = "inbox" | "board" | "plan" | "eod" | "control" | null;

type Props = {
  tasks: Task[];
  selected: Task | null;
  onCloseInspector: () => void;
  onRefresh: () => void;
};

export function Hud({ tasks, selected, onCloseInspector, onRefresh }: Props) {
  const [panel, setPanel] = useState<Panel>(null);

  return (
    <>
      <nav className="hud-bar">
        <span className="brand">Buildshift</span>
        {(
          [
            ["inbox", "Inbox"],
            ["board", "Board"],
            ["plan", "Plan"],
            ["eod", "EOD"],
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

      {selected && (
        <aside className="inspector">
          <header>
            <strong>Agent</strong>
            <button type="button" onClick={onCloseInspector}>
              ×
            </button>
          </header>
          <h3>{selected.title}</h3>
          <dl>
            <dt>State</dt>
            <dd>{selected.state}</dd>
            <dt>Role / stage</dt>
            <dd>
              {selected.role} / {selected.stage || "—"}
            </dd>
            <dt>Spend</dt>
            <dd>
              {selected.spent_usd} / {selected.budget_usd} USD
            </dd>
            <dt>PR</dt>
            <dd>
              {selected.pr_url ? (
                <a href={selected.pr_url} target="_blank" rel="noreferrer">
                  open
                </a>
              ) : (
                "—"
              )}
            </dd>
            {selected.error && (
              <>
                <dt>Error</dt>
                <dd>{selected.error}</dd>
              </>
            )}
          </dl>
        </aside>
      )}

      {panel && (
        <div className="drawer">
          <header>
            <strong>{panel.toUpperCase()}</strong>
            <button type="button" onClick={() => setPanel(null)}>
              ×
            </button>
          </header>
          {panel === "inbox" && <InboxPanel onChange={onRefresh} />}
          {panel === "board" && <BoardPanel tasks={tasks} />}
          {panel === "plan" && <PlanPanel onChange={onRefresh} />}
          {panel === "eod" && <EodPanel />}
          {panel === "control" && <ControlPanel onChange={onRefresh} />}
        </div>
      )}
    </>
  );
}

function InboxPanel({ onChange }: { onChange: () => void }) {
  const [items, setItems] = useState<HumanItem[]>([]);
  const [reply, setReply] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");

  const load = () =>
    orch
      .hitl("open")
      .then(setItems)
      .catch((e) => setErr(String(e)));

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="panel-body">
      {err && <p className="err">{err}</p>}
      {items.length === 0 && <p className="muted">No open HITL items.</p>}
      {items.map((item) => (
        <div key={item.id} className="card-row">
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
}

function BoardPanel({ tasks }: { tasks: Task[] }) {
  const byState = tasks.reduce<Record<string, Task[]>>((acc, t) => {
    (acc[t.state] ||= []).push(t);
    return acc;
  }, {});
  const order = [
    "ready",
    "test_authoring",
    "coding",
    "reviewing",
    "integrating",
    "blocked_human",
    "merged",
    "parked",
    "failed",
  ];
  return (
    <div className="panel-body board">
      {order.map((state) => (
        <section key={state}>
          <h4>
            {state} ({byState[state]?.length || 0})
          </h4>
          <ul>
            {(byState[state] || []).map((t) => (
              <li key={t.id}>
                {t.title} <span className="muted">{t.role}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function PlanPanel({ onChange }: { onChange: () => void }) {
  const [products, setProducts] = useState<{ id: string; slug: string; title: string }[]>([]);
  const [productId, setProductId] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [markdown, setMarkdown] = useState("");
  const [sourceName, setSourceName] = useState("uploaded.md");
  const [busy, setBusy] = useState(false);

  const loadProducts = async (preferId?: string) => {
    const p = await orch.products();
    setProducts(p);
    const next = preferId || productId || p[0]?.id || "";
    if (next && p.some((x) => x.id === next)) setProductId(next);
    else if (p[0]) setProductId(p[0].id);
    return p;
  };

  useEffect(() => {
    loadProducts().catch((e) => setErr(String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onPickFile(file: File | null) {
    if (!file) return;
    setSourceName(file.name);
    setMarkdown(await file.text());
    setErr("");
  }

  async function indexAndKickoff() {
    if (!markdown.trim()) {
      setErr("Paste or upload a markdown PRD first.");
      return;
    }
    setBusy(true);
    setErr("");
    setMsg("Indexing PRD…");
    try {
      const indexed = await orch.indexPrd(markdown, sourceName || "uploaded.md");
      const first = indexed.products[0];
      await loadProducts(first?.id);
      if (first) {
        setMsg(`Indexed ${indexed.products.length} product(s). Kicking off ${first.slug}…`);
        const ko = await orch.kickoff(first.id);
        setProductId(first.id);
        setMsg(
          `Indexed + kickoff ${ko.slug}: ${ko.requirements} reqs, ${ko.human_items} HITL stub(s). Ready to propose.`
        );
      } else {
        setMsg("Indexed, but no products returned.");
      }
      onChange();
    } catch (e) {
      setErr(String(e));
      setMsg("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel-body">
      <fieldset>
        <legend>Upload PRD</legend>
        <p className="muted">Markdown file or paste. Indexes products, then kickoff on the first.</p>
        <label>
          File
          <input
            type="file"
            accept=".md,.markdown,text/markdown,text/plain"
            onChange={(e) => onPickFile(e.target.files?.[0] || null)}
          />
        </label>
        <label>
          Source name
          <input value={sourceName} onChange={(e) => setSourceName(e.target.value)} />
        </label>
        <label>
          Markdown
          <textarea
            rows={8}
            placeholder="# Product Title&#10;&#10;## Requirements&#10;…"
            value={markdown}
            onChange={(e) => setMarkdown(e.target.value)}
          />
        </label>
        <button type="button" disabled={busy || !markdown.trim()} onClick={indexAndKickoff}>
          {busy ? "Working…" : "Index & kickoff"}
        </button>
      </fieldset>

      <label>
        Product
        <select value={productId} onChange={(e) => setProductId(e.target.value)}>
          {products.length === 0 && <option value="">No products yet — upload a PRD</option>}
          {products.map((p) => (
            <option key={p.id} value={p.id}>
              {p.slug} — {p.title}
            </option>
          ))}
        </select>
      </label>
      <div className="row">
        <button
          type="button"
          disabled={!productId || busy}
          onClick={async () => {
            setBusy(true);
            setErr("");
            setMsg("Proposing…");
            try {
              const p = await orch.proposePlan(productId, 3);
              setPlan(p);
              setMsg(`Draft plan ${p.id}`);
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Propose
        </button>
        <button
          type="button"
          disabled={!plan || plan.status === "approved" || busy}
          onClick={async () => {
            if (!plan) return;
            setBusy(true);
            setErr("");
            try {
              const r = await orch.approvePlan(plan.id);
              setMsg(`Approved → ${r.task_ids.length} tasks`);
              onChange();
            } catch (e) {
              setErr(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Approve
        </button>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <p className="muted">{msg}</p>}
      {plan && (
        <pre className="code">{JSON.stringify({ status: plan.status, tickets: plan.tickets, diff: plan.diff }, null, 2)}</pre>
      )}
    </div>
  );
}

function EodPanel() {
  const [digest, setDigest] = useState<EodDigest | null>(null);
  useEffect(() => {
    orch.eod().then(setDigest);
  }, []);
  if (!digest) return <p className="panel-body muted">Loading…</p>;
  const text = [
    `EOD ${digest.day}`,
    `merged=${digest.merged} reviewing=${digest.reviewing} blocked=${digest.blocked_human}`,
    `parked=${digest.parked} failed=${digest.failed} spend=$${digest.spend_usd}`,
    `open_hitl=${digest.open_hitl}`,
    ...digest.risks.map((r) => `risk: ${r}`),
  ].join("\n");
  return (
    <div className="panel-body">
      <button type="button" onClick={() => navigator.clipboard.writeText(text)}>
        Copy digest
      </button>
      <pre className="code">{text}</pre>
      <h4>Counts</h4>
      <ul>
        {Object.entries(digest.counts_by_state).map(([k, v]) => (
          <li key={k}>
            {k}: {v}
          </li>
        ))}
      </ul>
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
        <select
          value={s.harness}
          onChange={(e) => setS({ ...s, harness: e.target.value })}
        >
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
        <textarea
          rows={8}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
        />
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
