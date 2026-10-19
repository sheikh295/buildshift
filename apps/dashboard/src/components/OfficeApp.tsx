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
  const [error, setError] = useState("");

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
        <div className="toast event">
          #{lastEvent.id} {lastEvent.kind}
          {lastEvent.summary ? ` — ${lastEvent.summary}` : ""}
        </div>
      )}
    </div>
  );
}
