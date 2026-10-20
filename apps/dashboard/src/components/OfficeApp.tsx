"use client";

import { useCallback, useEffect, useState } from "react";
import { orch } from "@/lib/api";
import type { EventRow, OfficeMap, Selection, Task } from "@/lib/types";
import { OfficeCanvas } from "./OfficeCanvas";
import { Hud } from "./Hud";

type Props = { map: OfficeMap };

export function OfficeApp({ map }: Props) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const [lastEvent, setLastEvent] = useState<EventRow | null>(null);
  const [eventExpanded, setEventExpanded] = useState(() => {
    if (typeof window === "undefined") return false;
    return sessionStorage.getItem("bs-event-toast-expanded") === "1";
  });
  const [error, setError] = useState("");

  const toggleEventToast = useCallback(() => {
    setEventExpanded((prev) => {
      const next = !prev;
      sessionStorage.setItem("bs-event-toast-expanded", next ? "1" : "0");
      return next;
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const list = await orch.tasks(200);
      setTasks(list);
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3500);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;

    (async () => {
      let since = 0;
      try {
        const hist = await orch.events(0);
        if (hist.length) {
          since = hist[hist.length - 1].id;
          setLastEvent(hist[hist.length - 1]);
        }
      } catch {
        /* ignore */
      }
      if (cancelled) return;
      es = new EventSource(`/api/events/stream?since=${since}`);
      es.onmessage = (ev) => {
        try {
          const row = JSON.parse(ev.data) as EventRow;
          setLastEvent(row);
          if (
            row.kind.startsWith("task.") ||
            row.kind.startsWith("hitl.") ||
            row.kind.startsWith("control.")
          ) {
            refresh();
          }
        } catch {
          /* ignore */
        }
      };
    })();

    return () => {
      cancelled = true;
      es?.close();
    };
  }, [refresh]);

  return (
    <div className="office-root">
      <Hud
        tasks={tasks}
        selection={selection}
        onCloseInspector={() => setSelection(null)}
        onRefresh={refresh}
      />
      <OfficeCanvas
        map={map}
        tasks={tasks}
        lastEvent={lastEvent}
        onSelect={setSelection}
      />
      {error && <div className="toast err">{error}</div>}
      {lastEvent && (
        <button
          type="button"
          className={`toast event ${eventExpanded ? "expanded" : "collapsed"}`}
          onClick={toggleEventToast}
          title={eventExpanded ? "Collapse event" : "Expand event"}
        >
          {eventExpanded ? (
            <>
              #{lastEvent.id} {lastEvent.kind}
              {lastEvent.summary ? ` — ${lastEvent.summary}` : ""}
            </>
          ) : (
            <>
              #{lastEvent.id} {lastEvent.kind}
              {lastEvent.summary ? ` — ${lastEvent.summary.slice(0, 48)}${lastEvent.summary.length > 48 ? "…" : ""}` : ""}
            </>
          )}
        </button>
      )}
    </div>
  );
}
