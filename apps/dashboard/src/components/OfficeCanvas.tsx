"use client";

import { useEffect, useRef } from "react";
import type { EventRow, OfficeAgentActivity, OfficeMap, Selection, Task } from "@/lib/types";

type Props = {
  map: OfficeMap;
  tasks: Task[];
  activity: OfficeAgentActivity[];
  lastEvent: EventRow | null;
  selection: Selection;
  onSelect: (sel: Selection) => void;
};

type SceneApi = {
  syncTasks: (t: Task[]) => void;
  syncRoleActivity: (a: OfficeAgentActivity[]) => void;
  flashEvent: (k: string, id?: string | null) => void;
  clearSelection: () => void;
};

export function OfficeCanvas({
  map,
  tasks,
  activity,
  lastEvent,
  selection,
  onSelect,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const gameRef = useRef<Phaser.Game | null>(null);
  const sceneRef = useRef<SceneApi | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    let destroyed = false;
    (async () => {
      const Phaser = (await import("phaser")).default;
      const { OfficeScene } = await import("@/office/OfficeScene");
      if (destroyed || !hostRef.current || gameRef.current) return;

      const scene = new OfficeScene();
      const game = new Phaser.Game({
        type: Phaser.WEBGL,
        parent: hostRef.current,
        width: map.width,
        height: map.height,
        backgroundColor: "#121820",
        scene: [scene],
        render: {
          pixelArt: true,
          antialias: false,
          roundPixels: true,
        },
        scale: {
          mode: Phaser.Scale.FIT,
          autoCenter: Phaser.Scale.CENTER_BOTH,
        },
        audio: { noAudio: true },
      });
      game.scene.start("OfficeScene", {
        map,
        callbacks: {
          onSelect: (sel: Selection) => onSelectRef.current(sel),
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
    sceneRef.current?.syncRoleActivity(activity);
  }, [activity]);

  useEffect(() => {
    if (!lastEvent) return;
    sceneRef.current?.flashEvent(lastEvent.kind, lastEvent.task_id);
  }, [lastEvent]);

  useEffect(() => {
    if (selection === null) sceneRef.current?.clearSelection();
  }, [selection]);

  return <div ref={hostRef} className="office-canvas" />;
}
