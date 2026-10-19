"use client";

import { useEffect, useRef } from "react";
import type { EventRow, OfficeMap, Task } from "@/lib/types";

type Props = {
  map: OfficeMap;
  tasks: Task[];
  lastEvent: EventRow | null;
  onSelectTask: (task: Task | null) => void;
};

export function OfficeCanvas({ map, tasks, lastEvent, onSelectTask }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const gameRef = useRef<Phaser.Game | null>(null);
  const sceneRef = useRef<{ syncTasks: (t: Task[]) => void; flashEvent: (k: string, id?: string | null) => void } | null>(null);
  const onSelectRef = useRef(onSelectTask);
  onSelectRef.current = onSelectTask;

  useEffect(() => {
    let destroyed = false;
    (async () => {
      const Phaser = (await import("phaser")).default;
      const { OfficeScene } = await import("@/office/OfficeScene");
      if (destroyed || !hostRef.current || gameRef.current) return;

      const scene = new OfficeScene();
      const game = new Phaser.Game({
        type: Phaser.AUTO,
        parent: hostRef.current,
        width: map.width,
        height: map.height,
        backgroundColor: "#1a2332",
        scene: [scene],
        scale: {
          mode: Phaser.Scale.FIT,
          autoCenter: Phaser.Scale.CENTER_BOTH,
        },
      });
      game.scene.start("OfficeScene", {
        map,
        callbacks: {
          onSelectTask: (t: Task | null) => onSelectRef.current(t),
        },
      });
      gameRef.current = game;
      sceneRef.current = scene;
    })();

    return () => {
      destroyed = true;
      gameRef.current?.destroy(true);
      gameRef.current = null;
      sceneRef.current = null;
    };
  }, [map]);

  useEffect(() => {
    sceneRef.current?.syncTasks(tasks);
  }, [tasks]);

  useEffect(() => {
    if (!lastEvent) return;
    sceneRef.current?.flashEvent(lastEvent.kind, lastEvent.task_id);
  }, [lastEvent]);

  return <div ref={hostRef} className="office-canvas" />;
}
