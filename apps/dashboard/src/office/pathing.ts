import type { CabinDef, OfficeMap } from "@/lib/types";
import { WallRect, circleHitsWall } from "./walls";

export type Pt = { x: number; y: number };

/** Corridor midline Y (center of partition gaps). */
export function corridorY(map: OfficeMap): number {
  return map.hall.y + map.hall.h / 2;
}

export function partitionXs(map: OfficeMap): number[] {
  const xs: number[] = [];
  const cabins = map.cabins || [];
  for (let i = 0; i < cabins.length - 1; i++) {
    const left = cabins[i];
    const right = cabins[i + 1];
    xs.push((left.x + left.w + right.x) / 2);
  }
  return xs;
}

/** Sample along a segment; true if any sample hits a wall. */
export function lineHitsWall(
  from: Pt,
  to: Pt,
  walls: WallRect[],
  radius: number,
  samples = 16
): boolean {
  for (let i = 1; i <= samples; i++) {
    const t = i / samples;
    const x = from.x + (to.x - from.x) * t;
    const y = from.y + (to.y - from.y) * t;
    if (circleHitsWall(x, y, radius, walls)) return true;
  }
  return false;
}

/**
 * Wall-aware walk path. Direct if clear; otherwise via the corridor gap
 * (drop to corridor → travel → rise to destination).
 */
export function navigatePath(
  map: OfficeMap,
  from: Pt,
  to: Pt,
  walls: WallRect[],
  radius = 11
): Pt[] {
  const dist = Math.hypot(from.x - to.x, from.y - to.y);
  if (dist < 20) return [{ ...to }];

  if (!lineHitsWall(from, to, walls, radius)) {
    return [{ ...to }];
  }

  const cy = corridorY(map);
  const path: Pt[] = [];

  if (Math.abs(from.y - cy) > 10) {
    path.push({ x: from.x, y: cy });
  }
  if (Math.abs(from.x - to.x) > 10) {
    path.push({ x: to.x, y: cy });
  }
  path.push({ ...to });
  return path;
}

/** Desk → desk / token path via corridor. */
export function deskToDeskPath(map: OfficeMap, from: Pt, to: Pt): Pt[] {
  const cy = corridorY(map);
  if (Math.hypot(from.x - to.x, from.y - to.y) < 40) {
    return [{ ...to }];
  }
  return [
    { x: from.x, y: cy },
    { x: to.x, y: cy },
    { ...to },
  ];
}

/** Advance along a waypoint path; returns new position and remaining path. */
export function stepPath(
  x: number,
  y: number,
  path: Pt[],
  speed: number
): { x: number; y: number; path: Pt[]; arrived: boolean } {
  if (!path.length) return { x, y, path, arrived: true };
  const target = path[0];
  const dx = target.x - x;
  const dy = target.y - y;
  const dist = Math.hypot(dx, dy);
  if (dist <= speed || dist < 2) {
    const rest = path.slice(1);
    return {
      x: target.x,
      y: target.y,
      path: rest,
      arrived: rest.length === 0,
    };
  }
  return {
    x: x + (dx / dist) * speed,
    y: y + (dy / dist) * speed,
    path,
    arrived: false,
  };
}

/** Random walkable point inside a single cabin (no cross-partition roam). */
export function randomWalkableInCabin(
  cabin: CabinDef,
  walls: WallRect[],
  radius = 12
): Pt {
  const pad = 32;
  for (let i = 0; i < 40; i++) {
    const x = cabin.x + pad + Math.random() * Math.max(8, cabin.w - pad * 2);
    const y = cabin.y + pad + Math.random() * Math.max(8, cabin.h - pad * 2);
    if (!circleHitsWall(x, y, radius, walls)) return { x, y };
  }
  return { x: cabin.x + cabin.w / 2, y: cabin.y + cabin.h / 2 };
}
