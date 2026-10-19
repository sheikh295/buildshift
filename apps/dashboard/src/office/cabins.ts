import type { CabinDef, DeskPlacement, OfficeMap, SofaPlacement, Task } from "@/lib/types";

export const TERMINAL = new Set(["merged", "failed", "parked", "stopped"]);

export function cabinForTaskState(state: string): string {
  switch (state) {
    case "planned":
    case "blocked_human":
      return "planner";
    case "ready":
    case "coding":
      return "developers";
    case "test_authoring":
    case "testing":
    case "reviewing":
      return "qa";
    case "integrating":
    case "merged":
    case "failed":
    case "parked":
    case "stopped":
      return "integrate";
    default:
      return "developers";
  }
}

export function getCabin(map: OfficeMap, id: string): CabinDef | undefined {
  return map.cabins?.find((c) => c.id === id);
}

export function hireCount(cabin: CabinDef, tasks: Task[]): number {
  if (!cabin.maxHire) return 0;
  const states = new Set(cabin.hireStates || []);
  const n = tasks.filter((t) => !TERMINAL.has(t.state) && states.has(t.state)).length;
  return Math.min(cabin.maxHire, Math.max(0, n));
}

export function activeTasksInCabin(cabin: CabinDef, tasks: Task[]): Task[] {
  const states = new Set(cabin.hireStates || []);
  if (cabin.id === "planner") {
    return tasks.filter((t) => !TERMINAL.has(t.state) && ["planned", "blocked_human"].includes(t.state));
  }
  if (cabin.id === "integrate") {
    return tasks.filter((t) => t.state === "integrating");
  }
  return tasks.filter((t) => !TERMINAL.has(t.state) && states.has(t.state));
}

export type DeskSlot = DeskPlacement & { walkX: number; walkY: number };

export function deskSlots(cabin: CabinDef): DeskSlot[] {
  if (cabin.desks?.length) {
    return cabin.desks.map((d) => ({
      ...d,
      walkX: d.x + 22,
      walkY: d.y + 20,
    }));
  }
  // legacy grid fallback
  const cols = Math.max(1, cabin.deskCols || 1);
  const rows = Math.max(1, cabin.deskRows || 1);
  const marginX = 36;
  const marginY = 72;
  const cellW = (cabin.w - marginX * 2) / cols;
  const cellH = (cabin.h - marginY - 48) / rows;
  const slots: DeskSlot[] = [];
  let i = 0;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = cabin.x + marginX + cellW * c + cellW / 2;
      const y = cabin.y + marginY + cellH * r + cellH / 2;
      slots.push({ seat: i++, x, y, walkX: x + 18, walkY: y + 22 });
    }
  }
  return slots;
}

export function allSofas(map: OfficeMap): SofaPlacement[] {
  return (map.cabins || []).flatMap((c) => c.sofas || []);
}

export function tokenLane(cabin: CabinDef, slotIndex: number, total: number): { x: number; y: number } {
  const laneY = cabin.y + 42;
  const pad = 36;
  const usable = cabin.w - pad * 2;
  const spacing = Math.min(40, usable / Math.max(1, total));
  const start = cabin.x + pad + spacing / 2;
  return {
    x: start + slotIndex * spacing,
    y: laneY + (slotIndex % 2) * 12,
  };
}

/** @deprecated prefer randomWalkablePoint from walls.ts */
export function randomRoamPoint(map: OfficeMap): { x: number; y: number } {
  const hall = map.hall;
  const pad = (hall.wallThickness || 16) + 28;
  return {
    x: hall.x + pad + Math.random() * (hall.w - pad * 2),
    y: hall.y + pad + Math.random() * (hall.h - pad * 2),
  };
}
