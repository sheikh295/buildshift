import type { CabinDef, HallDef, OfficeMap } from "@/lib/types";

export type WallRect = { x: number; y: number; w: number; h: number };

/** Build solid wall rects: outer hall + thick division walls with a short corridor gap. */
export function buildWalls(map: OfficeMap): WallRect[] {
  const hall = map.hall;
  const t = hall.wallThickness || 16;
  const gap = hall.corridorGap || 52;
  const walls: WallRect[] = [];

  // Outer walls (inward from hall edge)
  walls.push({ x: hall.x, y: hall.y, w: hall.w, h: t }); // north
  walls.push({ x: hall.x, y: hall.y + hall.h - t, w: hall.w, h: t }); // south
  walls.push({ x: hall.x, y: hall.y, w: t, h: hall.h }); // west
  walls.push({ x: hall.x + hall.w - t, y: hall.y, w: t, h: hall.h }); // east

  const midY = hall.y + hall.h / 2;
  const gapTop = midY - gap / 2;
  const gapBot = midY + gap / 2;
  const cabins = map.cabins || [];

  for (let i = 0; i < cabins.length - 1; i++) {
    const left = cabins[i];
    const right = cabins[i + 1];
    const cx = (left.x + left.w + right.x) / 2;
    const wx = cx - t / 2;
    // Top segment
    walls.push({
      x: wx,
      y: hall.y + t,
      w: t,
      h: gapTop - (hall.y + t),
    });
    // Bottom segment
    walls.push({
      x: wx,
      y: gapBot,
      w: t,
      h: hall.y + hall.h - t - gapBot,
    });
  }

  return walls.filter((w) => w.w > 0 && w.h > 0);
}

export function circleHitsWall(
  cx: number,
  cy: number,
  radius: number,
  walls: WallRect[]
): boolean {
  for (const w of walls) {
    const nearestX = Math.max(w.x, Math.min(cx, w.x + w.w));
    const nearestY = Math.max(w.y, Math.min(cy, w.y + w.h));
    const dx = cx - nearestX;
    const dy = cy - nearestY;
    if (dx * dx + dy * dy < radius * radius) return true;
  }
  return false;
}

/** Move with axis-separated collision (slide along walls). */
export function moveCollide(
  x: number,
  y: number,
  tx: number,
  ty: number,
  speed: number,
  radius: number,
  walls: WallRect[]
): { x: number; y: number } {
  const dx = tx - x;
  const dy = ty - y;
  const dist = Math.hypot(dx, dy);
  if (dist <= 1) return { x, y };

  const step = Math.min(speed, dist);
  const nx = x + (dx / dist) * step;
  const ny = y + (dy / dist) * step;

  if (!circleHitsWall(nx, ny, radius, walls)) return { x: nx, y: ny };
  if (!circleHitsWall(nx, y, radius, walls)) return { x: nx, y };
  if (!circleHitsWall(x, ny, radius, walls)) return { x, y: ny };
  return { x, y };
}

export function randomWalkablePoint(map: OfficeMap, walls: WallRect[], radius = 12): { x: number; y: number } {
  const hall = map.hall;
  const pad = (hall.wallThickness || 16) + 24;
  for (let i = 0; i < 40; i++) {
    const x = hall.x + pad + Math.random() * (hall.w - pad * 2);
    const y = hall.y + pad + Math.random() * (hall.h - pad * 2);
    if (!circleHitsWall(x, y, radius, walls)) return { x, y };
  }
  // fallback: corridor center
  return { x: hall.x + hall.w / 2, y: hall.y + hall.h / 2 };
}

export function partitionCenters(cabins: CabinDef[], hall: HallDef): number[] {
  const xs: number[] = [];
  for (let i = 0; i < cabins.length - 1; i++) {
    const left = cabins[i];
    const right = cabins[i + 1];
    xs.push((left.x + left.w + right.x) / 2);
  }
  return xs;
}
