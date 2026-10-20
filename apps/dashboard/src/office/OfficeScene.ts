import Phaser from "phaser";
import type { CabinDef, OfficeMap, Selection, Task } from "@/lib/types";
import {
  TERMINAL,
  cabinForTaskState,
  deskSlots,
  getCabin,
  hireCount,
} from "./cabins";
import {
  Pt,
  deskToDeskPath,
  navigatePath,
  randomWalkableInCabin,
  stepPath,
} from "./pathing";
import { cabinAccent, ensureOfficeTextures } from "./sprites";
import { WallRect, buildWalls } from "./walls";

export type OfficeCallbacks = {
  onSelect: (sel: Selection) => void;
};

type IdlePhase = "desk" | "sofa" | "roam" | "chat";

type PersonEnt = {
  id: string;
  name: string;
  role: string;
  cabinId: string;
  permanent: boolean;
  seat: number;
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Image;
  nameTag: Phaser.GameObjects.Text;
  chatBubble: Phaser.GameObjects.Text | null;
  status: "idle" | "working" | "roaming" | "hired" | "sitting" | "chatting" | "called";
  taskId: string | null;
  target: { x: number; y: number };
  /** Corridor-aware waypoints to target */
  path: Pt[];
  phase: IdlePhase;
  phaseUntil: number;
  chatPartner: string | null;
  /** Stay seated until this time after finishing a stage */
  holdUntil: number;
  /** True once seated at desk with task delivered (or no transit needed) */
  workActive: boolean;
};

type DeskEnt = {
  cabinId: string;
  seat: number;
  x: number;
  y: number;
  desk: Phaser.GameObjects.Image;
  chair: Phaser.GameObjects.Image;
  occupied: boolean;
};

type SofaEnt = {
  id: string;
  cabinId: string;
  x: number;
  y: number;
  orient: "h" | "v";
  sprite: Phaser.GameObjects.Image;
  occupiedBy: string | null;
};

/** Token only exists while flowing desk → desk */
type TokenEnt = {
  taskId: string;
  container: Phaser.GameObjects.Container;
  label: Phaser.GameObjects.Text;
  path: Pt[];
};

type TaskBinding = {
  taskId: string;
  cabinId: string;
  seat: number;
  personId: string | null;
  state: string;
  /** ready = at desk (no visible token); transit = token en route */
  delivery: "ready" | "transit";
};

const HIRE_NAMES = [
  "Alex", "Sam", "Jordan", "Taylor", "Quinn", "Avery",
  "Reese", "Blake", "Drew", "Jamie", "Kai", "Noah",
];
const BODY_R = 11;
const CHAIR_N = 28;
const POST_TASK_SIT_MS = 60_000;
const TOKEN_SPEED = 0.45; // fast desk→desk
const WORK_WALK = 0.24; // called to desk
const IDLE_WALK = 0.055;
const CHAT_LINES = ["hey", "ship it?", "on it", "nice", "lol", "sync?", "ack", "👀", "brb", "ok"];

function chairOf(deskX: number, deskY: number) {
  return { x: deskX, y: deskY - CHAIR_N };
}

function shorten(s: string, n: number) {
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}

function atPoint(a: { x: number; y: number }, b: { x: number; y: number }, r = 6) {
  return Math.hypot(a.x - b.x, a.y - b.y) < r;
}

export class OfficeScene extends Phaser.Scene {
  private mapData!: OfficeMap;
  private callbacks!: OfficeCallbacks;
  private tasks = new Map<string, Task>();
  private people = new Map<string, PersonEnt>();
  private desks: DeskEnt[] = [];
  private sofas: SofaEnt[] = [];
  private tokens = new Map<string, TokenEnt>();
  private bindings = new Map<string, TaskBinding>();
  private walls: WallRect[] = [];
  private hireSeq = 0;
  private selectedKey: string | null = null;
  private leaving = new Set<string>();

  constructor() {
    super("OfficeScene");
  }

  init(data: { map: OfficeMap; callbacks: OfficeCallbacks }) {
    this.mapData = data.map;
    this.callbacks = data.callbacks;
  }

  create() {
    ensureOfficeTextures(this);
    this.cameras.main.setBackgroundColor("#0c1018");
    this.cameras.main.setRoundPixels(true);
    this.walls = buildWalls(this.mapData);
    this.drawHall();
    this.spawnPermanentStaff();
  }

  syncTasks(tasks: Task[]) {
    this.tasks = new Map(tasks.map((t) => [t.id, t]));
    this.syncHiring(tasks);
    this.syncBindings(tasks);
  }

  flashEvent(_kind: string, _taskId?: string | null) {
    /* tokens flash on create */
  }

  // ——— Drawing ———

  private drawHall() {
    const { width, height, hall, cabins } = this.mapData;
    const g = this.add.graphics().setDepth(2);
    const t = hall.wallThickness || 16;

    g.fillStyle(0x0c1018, 1);
    g.fillRect(0, 0, width, height);

    const { x: hx, y: hy, w: hw, h: hh, radius: r = 20 } = hall;
    g.fillStyle(0xa89880, 1);
    g.fillRoundedRect(hx, hy, hw, hh, r);
    g.fillStyle(0xb8a890, 1);
    g.fillRoundedRect(hx + t, hy + t, hw - t * 2, hh - t * 2, Math.max(4, r - 8));
    g.lineStyle(1, 0x968870, 0.4);
    for (let y = hy + t + 8; y < hy + hh - t; y += 20) {
      g.lineBetween(hx + t + 4, y, hx + hw - t - 4, y);
    }

    g.fillStyle(0x2a3344, 1);
    g.fillRect(hx, hy, hw, t);
    g.fillRect(hx, hy + hh - t, hw, t);
    g.fillRect(hx, hy, t, hh);
    g.fillRect(hx + hw - t, hy, t, hh);
    g.lineStyle(2, 0x1a2230, 1);
    g.strokeRoundedRect(hx, hy, hw, hh, r);

    this.add
      .text(width / 2, 24, "BUILDSHIFT  ·  OPERATIONS HALL", {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "14px",
        color: "#9ec1ff",
        resolution: 2,
      })
      .setOrigin(0.5)
      .setDepth(50);

    const midY = hy + hh / 2;
    const gap = hall.corridorGap || 52;
    for (const w of this.walls) {
      if (w.h > t * 2 && w.w <= t + 4) {
        g.fillStyle(0x343f52, 1);
        g.fillRect(w.x, w.y, w.w, w.h);
        g.fillStyle(0x1e2838, 1);
        g.fillRect(w.x, w.y, 3, w.h);
        g.fillRect(w.x + w.w - 3, w.y, 3, w.h);
      }
    }
    for (let i = 0; i < cabins.length - 1; i++) {
      const left = cabins[i];
      const right = cabins[i + 1];
      const cx = (left.x + left.w + right.x) / 2;
      g.fillStyle(0x5b9cff, 0.55);
      g.fillRect(cx - t / 2 - 2, midY - gap / 2 - 3, t + 4, 4);
      g.fillRect(cx - t / 2 - 2, midY + gap / 2 - 1, t + 4, 4);
    }

    for (const cabin of cabins) {
      const accent = cabinAccent(cabin.accent);
      const wash = this.add.graphics().setDepth(3);
      wash.fillStyle(accent, 0.08);
      wash.fillRect(cabin.x + 8, hy + t + 28, cabin.w - 16, hh - t * 2 - 40);

      this.add
        .text(cabin.x + cabin.w / 2, hy + t + 14, cabin.label, {
          fontFamily: "IBM Plex Mono, monospace",
          fontSize: "12px",
          color: "#1a2332",
          backgroundColor: "#ffffff99",
          padding: { x: 6, y: 2 },
          resolution: 2,
        })
        .setOrigin(0.5)
        .setDepth(8);

      this.placeFurniture(cabin);
      this.placeDecor(cabin);
      this.placeDoor(cabin);
    }

    this.add
      .text(width / 2, height - 18, "corridor paths · lit screens only while working · 60s sit after handoff", {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "11px",
        color: "#6b7c90",
        resolution: 2,
      })
      .setOrigin(0.5)
      .setDepth(50);
  }

  private placeDoor(cabin: CabinDef) {
    if (!cabin.door) return;
    this.add.image(cabin.door.x, cabin.door.y, "door_gate").setDepth(8);
    this.add
      .text(cabin.door.x, cabin.door.y + 22, "GATE", {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "9px",
        color: "#5b9cff",
        resolution: 2,
      })
      .setOrigin(0.5, 0)
      .setDepth(8);
  }

  private placeDecor(cabin: CabinDef) {
    if (cabin.id === "developers") {
      this.add.image(505, 350, "rug").setDepth(4).setScale(2.4, 3.5).setAlpha(0.55);
    } else if (cabin.id === "qa") {
      this.add.image(880, 350, "rug").setDepth(4).setScale(1.7, 3.3).setAlpha(0.5);
    } else if (cabin.id === "planner") {
      this.add.image(150, 350, "rug").setDepth(4).setScale(1.35, 2.9).setAlpha(0.45);
    } else if (cabin.id === "integrate") {
      this.add.image(1130, 350, "rug").setDepth(4).setScale(1.25, 2.8).setAlpha(0.45);
    }
    for (const p of [
      { x: cabin.x + 28, y: cabin.y + 70 },
      { x: cabin.x + cabin.w - 28, y: cabin.y + 70 },
      { x: cabin.x + 28, y: cabin.y + cabin.h - 50 },
      { x: cabin.x + cabin.w - 28, y: cabin.y + cabin.h - 50 },
    ]) {
      this.add.image(p.x, p.y, "plant").setDepth(6).setScale(1.15);
    }
  }

  private placeFurniture(cabin: CabinDef) {
    for (const s of cabin.sofas || []) {
      const key = s.orient === "v" ? "sofa_v" : "sofa_h";
      const sprite = this.add.image(s.x, s.y, key).setDepth(6).setInteractive({ useHandCursor: true });
      sprite.on("pointerdown", (ptr: Phaser.Input.Pointer) => {
        ptr.event.stopPropagation();
        const sitter = this.sofas.find((x) => x.id === s.id)?.occupiedBy;
        if (sitter) this.selectPerson(sitter);
      });
      this.sofas.push({
        id: s.id,
        cabinId: cabin.id,
        x: s.x,
        y: s.y,
        orient: s.orient,
        sprite,
        occupiedBy: null,
      });
    }

    for (const slot of deskSlots(cabin)) {
      const chair = chairOf(slot.x, slot.y);
      const deskImg = this.add
        .image(slot.x, slot.y, "desk_empty")
        .setDepth(7)
        .setInteractive({ useHandCursor: true });
      const chairImg = this.add.image(chair.x, chair.y, "chair").setDepth(6).setAlpha(0.6);
      deskImg.on("pointerdown", (ptr: Phaser.Input.Pointer) => {
        ptr.event.stopPropagation();
        this.selectDesk(cabin, slot.seat);
      });
      this.desks.push({
        cabinId: cabin.id,
        seat: slot.seat,
        x: slot.x,
        y: slot.y,
        desk: deskImg,
        chair: chairImg,
        occupied: false,
      });
    }
  }

  // ——— People ———

  private spawnPermanentStaff() {
    for (const cabin of this.mapData.cabins || []) {
      const slots = deskSlots(cabin);
      for (const p of cabin.permanent) {
        const slot = slots.find((s) => s.seat === p.seat) || slots[0];
        const chair = chairOf(slot.x, slot.y);
        this.spawnPerson({
          id: p.id,
          name: p.name,
          role: p.role,
          cabinId: cabin.id,
          permanent: true,
          seat: p.seat,
          x: chair.x,
          y: chair.y,
        });
        this.setDeskVisual(cabin.id, p.seat, { occupied: true, working: false });
        const person = this.people.get(p.id);
        if (person) this.applyPose(person, "sit");
      }
    }
  }

  private spawnPerson(opts: {
    id: string;
    name: string;
    role: string;
    cabinId: string;
    permanent: boolean;
    seat: number;
    x: number;
    y: number;
  }) {
    if (this.people.has(opts.id)) return;
    const tex = this.textures.exists(`person_${opts.role}`)
      ? `person_${opts.role}`
      : "person_implementer";
    const sprite = this.add.image(0, 0, tex).setOrigin(0.5, 1);
    const nameTag = this.add
      .text(0, 4, opts.name, {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "9px",
        color: "#1a2332",
        backgroundColor: "#ffffffcc",
        padding: { x: 3, y: 1 },
        resolution: 2,
      })
      .setOrigin(0.5, 0);

    const container = this.add.container(opts.x, opts.y, [sprite, nameTag]).setDepth(30);
    container.setSize(26, 38);
    container.setInteractive({
      useHandCursor: true,
      hitArea: new Phaser.Geom.Rectangle(-13, -36, 26, 38),
      hitAreaCallback: Phaser.Geom.Rectangle.Contains,
    });
    container.on("pointerdown", (ptr: Phaser.Input.Pointer) => {
      ptr.event.stopPropagation();
      this.selectPerson(opts.id);
    });

    this.people.set(opts.id, {
      id: opts.id,
      name: opts.name,
      role: opts.role,
      cabinId: opts.cabinId,
      permanent: opts.permanent,
      seat: opts.seat,
      container,
      sprite,
      nameTag,
      chatBubble: null,
      status: "idle",
      taskId: null,
      target: { x: opts.x, y: opts.y },
      path: [],
      phase: "desk",
      phaseUntil: this.time.now + 6000 + Math.random() * 5000,
      chatPartner: null,
      holdUntil: 0,
      workActive: false,
    });
  }

  /** Set destination with corridor-aware waypoints so walls are never crossed. */
  private setNav(p: PersonEnt, dest: Pt) {
    p.target = { ...dest };
    p.path = navigatePath(
      this.mapData,
      { x: p.container.x, y: p.container.y },
      dest,
      this.walls,
      BODY_R
    );
  }

  private stepNav(p: PersonEnt, speed: number): boolean {
    const waypoints = p.path.length ? p.path : [p.target];
    const step = stepPath(p.container.x, p.container.y, waypoints, speed);
    p.container.x = step.x;
    p.container.y = step.y;
    p.path = step.path;
    return step.arrived && atPoint(p.container, p.target, 8);
  }

  private applyPose(p: PersonEnt, pose: "stand" | "sit" | "work") {
    const key =
      pose === "sit"
        ? `person_${p.role}_sit`
        : pose === "work"
          ? `person_${p.role}_work`
          : `person_${p.role}`;
    p.sprite.setTexture(this.textures.exists(key) ? key : `person_${p.role}`);
  }

  private clearChat(p: PersonEnt) {
    if (p.chatBubble) {
      p.chatBubble.destroy();
      p.chatBubble = null;
    }
    p.chatPartner = null;
  }

  private showChat(p: PersonEnt, line: string) {
    this.clearChat(p);
    p.chatBubble = this.add
      .text(0, -36, line, {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "10px",
        color: "#1a2332",
        backgroundColor: "#ffffff",
        padding: { x: 4, y: 2 },
        resolution: 2,
      })
      .setOrigin(0.5, 1);
    p.container.add(p.chatBubble);
  }

  private deskChairFor(p: PersonEnt): Pt | null {
    const cabin = getCabin(this.mapData, p.cabinId);
    if (!cabin) return null;
    const slot = deskSlots(cabin).find((s) => s.seat === p.seat);
    if (!slot) return null;
    return chairOf(slot.x, slot.y);
  }

  private deskPos(cabinId: string, seat: number): Pt | null {
    const cabin = getCabin(this.mapData, cabinId);
    if (!cabin) return null;
    const slot = deskSlots(cabin).find((s) => s.seat === seat);
    if (!slot) return null;
    return { x: slot.x, y: slot.y };
  }

  /** Chair presence vs lit monitor — screen only when actively working. */
  private setDeskVisual(
    cabinId: string,
    seat: number,
    opts: { occupied?: boolean; working?: boolean }
  ) {
    const d = this.desks.find((x) => x.cabinId === cabinId && x.seat === seat);
    if (!d) return;
    if (opts.occupied !== undefined) {
      d.occupied = opts.occupied;
      d.chair.setAlpha(opts.occupied ? 1 : 0.6);
    }
    if (opts.working !== undefined) {
      d.desk.setTexture(opts.working ? "desk" : "desk_empty");
    }
  }

  private cabinDoor(cabinId: string): Pt {
    const cabin = getCabin(this.mapData, cabinId);
    if (cabin?.door) return { ...cabin.door };
    const hall = this.mapData.hall;
    return { x: hall.x + hall.w / 2, y: hall.y + hall.h - 20 };
  }

  // ——— Hiring via gates ———

  private syncHiring(tasks: Task[]) {
    for (const cabin of this.mapData.cabins || []) {
      if (!cabin.maxHire || !cabin.door) continue;
      const needed = hireCount(cabin, tasks);
      const hired = [...this.people.values()].filter(
        (p) => p.cabinId === cabin.id && !p.permanent && !this.leaving.has(p.id)
      );
      const slots = deskSlots(cabin);

      while (hired.length < needed) {
        const seat = this.nextFreeHireSeat(cabin, hired);
        if (seat < 0) break;
        const slot = slots.find((s) => s.seat === seat) || slots[0];
        // Match hire role to pending work that lacks a person
        const unbound = tasks.filter((t) => {
          if (TERMINAL.has(t.state)) return false;
          if (!(cabin.hireStates || []).includes(t.state)) return false;
          const b = this.bindings.get(t.id);
          return !b || b.cabinId !== cabin.id || !b.personId;
        });
        const sample = unbound[0];
        const role =
          cabin.id === "qa"
            ? sample?.state === "reviewing"
              ? "reviewer"
              : "test_author"
            : "implementer";
        const id = `hire-${cabin.id}-${this.hireSeq++}`;
        const name = HIRE_NAMES[this.hireSeq % HIRE_NAMES.length];
        const door = this.cabinDoor(cabin.id);
        this.spawnPerson({
          id,
          name,
          role,
          cabinId: cabin.id,
          permanent: false,
          seat,
          x: door.x,
          y: door.y,
        });
        const person = this.people.get(id)!;
        person.status = "hired";
        this.setNav(person, chairOf(slot.x, slot.y));
        person.phase = "desk";
        person.phaseUntil = this.time.now + 8000;
        this.setDeskVisual(cabin.id, seat, { occupied: true, working: false });
        hired.push(person);
      }

      const liveHired = [...this.people.values()].filter(
        (p) => p.cabinId === cabin.id && !p.permanent && !this.leaving.has(p.id)
      );
      if (liveHired.length > needed) {
        const extra = [...liveHired]
          .reverse()
          .find((h) => !h.taskId && this.time.now >= h.holdUntil);
        if (extra) {
          this.leaving.add(extra.id);
          this.clearSofaIf(extra.id);
          this.clearChat(extra);
          this.setDeskVisual(cabin.id, extra.seat, { occupied: false, working: false });
          extra.taskId = null;
          extra.workActive = false;
          extra.status = "roaming";
          this.setNav(extra, this.cabinDoor(cabin.id));
          this.applyPose(extra, "stand");
          this.time.delayedCall(900, () => {
            this.removePerson(extra.id);
            this.leaving.delete(extra.id);
          });
        }
      }
    }
  }

  private nextFreeHireSeat(cabin: CabinDef, hired: PersonEnt[]): number {
    const taken = new Set([
      ...cabin.permanent.map((p) => p.seat),
      ...hired.map((h) => h.seat),
    ]);
    for (const d of deskSlots(cabin)) {
      if (!taken.has(d.seat)) return d.seat;
    }
    return -1;
  }

  // ——— Task bindings + desk→desk tokens ———

  private syncBindings(tasks: Task[]) {
    const active = tasks.filter((t) => !TERMINAL.has(t.state));
    const activeIds = new Set(active.map((t) => t.id));

    // Release finished tasks
    for (const [tid, bind] of [...this.bindings.entries()]) {
      if (activeIds.has(tid)) continue;
      this.releaseBinding(bind);
      this.bindings.delete(tid);
      this.removeToken(tid);
    }

    // Group by target cabin
    const byCabin = new Map<string, Task[]>();
    for (const task of active) {
      const cabinId = cabinForTaskState(task.state);
      if (!byCabin.has(cabinId)) byCabin.set(cabinId, []);
      byCabin.get(cabinId)!.push(task);
    }

    for (const [cabinId, list] of byCabin) {
      const cabin = getCabin(this.mapData, cabinId);
      if (!cabin) continue;

      // Prefer stable person assignment
      for (const task of list) {
        const prev = this.bindings.get(task.id);
        const sameCabin = prev && prev.cabinId === cabinId;

        let person: PersonEnt | undefined;
        if (sameCabin && prev.personId) {
          person = this.people.get(prev.personId);
        }
        if (!person || person.cabinId !== cabinId || this.leaving.has(person.id)) {
          person = this.pickFreePerson(cabinId, list, task.id);
        }
        if (!person) continue;

        const newDesk = this.deskPos(cabinId, person.seat);
        if (!newDesk) continue;

        if (prev && prev.cabinId !== cabinId) {
          // Stage handoff: token from previous desk → new desk
          const oldDesk = this.deskPos(prev.cabinId, prev.seat);
          if (oldDesk) {
            this.startTransit(task, oldDesk, newDesk);
            this.releasePersonHold(prev.personId);
          }
          this.bindings.set(task.id, {
            taskId: task.id,
            cabinId,
            seat: person.seat,
            personId: person.id,
            state: task.state,
            delivery: "transit",
          });
          this.callPersonToWork(person, task.id);
        } else if (!prev) {
          // First appearance — no floating token; work when seated
          this.bindings.set(task.id, {
            taskId: task.id,
            cabinId,
            seat: person.seat,
            personId: person.id,
            state: task.state,
            delivery: "ready",
          });
          this.callPersonToWork(person, task.id);
          this.tryActivateWork(person);
        } else {
          // Same cabin — keep assignment; only re-call if unbound or idle
          prev.state = task.state;
          prev.personId = person.id;
          prev.seat = person.seat;
          if (person.taskId !== task.id || (person.status !== "called" && !person.workActive)) {
            this.callPersonToWork(person, task.id);
            this.tryActivateWork(person);
          }
        }
      }
    }
  }

  private pickFreePerson(cabinId: string, tasksInCabin: Task[], forTaskId: string): PersonEnt | undefined {
    const claimed = new Set(
      [...this.bindings.values()]
        .filter((b) => b.cabinId === cabinId && b.taskId !== forTaskId && b.personId)
        .map((b) => b.personId!)
    );
    const staff = [...this.people.values()]
      .filter((p) => p.cabinId === cabinId && !this.leaving.has(p.id))
      .sort((a, b) => Number(b.permanent) - Number(a.permanent) || a.seat - b.seat);

    // Prefer person already bound to this task
    const already = staff.find((p) => p.taskId === forTaskId);
    if (already) return already;

    return staff.find((p) => !claimed.has(p.id) && (!p.taskId || p.taskId === forTaskId));
  }

  private callPersonToWork(person: PersonEnt, taskId: string) {
    this.clearSofaIf(person.id);
    this.clearChat(person);
    person.taskId = taskId;
    person.workActive = false;
    person.status = "called";
    const chair = this.deskChairFor(person);
    if (chair) this.setNav(person, chair);
    this.setDeskVisual(person.cabinId, person.seat, { occupied: true, working: false });
    this.applyPose(person, "stand");
    // Pause idle AI while called/working
    person.phaseUntil = this.time.now + 999_999_999;
  }

  private releasePersonHold(personId: string | null) {
    if (!personId) return;
    const p = this.people.get(personId);
    if (!p) return;
    p.taskId = null;
    p.workActive = false;
    p.status = p.permanent ? "idle" : "hired";
    p.holdUntil = this.time.now + POST_TASK_SIT_MS;
    p.phase = "desk";
    p.phaseUntil = p.holdUntil;
    const chair = this.deskChairFor(p);
    if (chair) this.setNav(p, chair);
    this.setDeskVisual(p.cabinId, p.seat, { occupied: true, working: false });
    this.applyPose(p, "sit");
  }

  private releaseBinding(bind: TaskBinding) {
    this.releasePersonHold(bind.personId);
  }

  private startTransit(task: Task, from: Pt, to: Pt) {
    this.removeToken(task.id);
    const path = deskToDeskPath(this.mapData, from, to);
    const img = this.add.image(0, 0, "ticket");
    const label = this.add
      .text(0, 14, shorten(task.title, 14), {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "9px",
        color: "#1a2332",
        backgroundColor: "#f5f0e1",
        padding: { x: 2, y: 1 },
        resolution: 2,
      })
      .setOrigin(0.5, 0);
    const container = this.add.container(from.x, from.y, [img, label]).setDepth(40);
    container.setSize(28, 28);
    container.setInteractive({
      useHandCursor: true,
      hitArea: new Phaser.Geom.Rectangle(-14, -10, 28, 28),
      hitAreaCallback: Phaser.Geom.Rectangle.Contains,
    });
    container.on("pointerdown", (ptr: Phaser.Input.Pointer) => {
      ptr.event.stopPropagation();
      this.selectedKey = `task:${task.id}`;
      this.callbacks.onSelect({ kind: "task", task: this.tasks.get(task.id) || task });
    });
    this.tokens.set(task.id, {
      taskId: task.id,
      container,
      label,
      path: path.slice(1), // already at first point
    });
  }

  private removeToken(id: string) {
    const tok = this.tokens.get(id);
    if (!tok) return;
    tok.container.destroy(true);
    this.tokens.delete(id);
  }

  private onTokenArrived(taskId: string) {
    this.removeToken(taskId);
    const bind = this.bindings.get(taskId);
    if (!bind) return;
    bind.delivery = "ready";
    // Try activate work if person already seated
    if (bind.personId) {
      const p = this.people.get(bind.personId);
      if (p) this.tryActivateWork(p);
    }
  }

  private tryActivateWork(p: PersonEnt) {
    if (!p.taskId) return;
    const bind = this.bindings.get(p.taskId);
    if (!bind || bind.delivery !== "ready") return;
    const chair = this.deskChairFor(p);
    if (!chair || !atPoint(p.container, chair, 8)) return;
    p.workActive = true;
    p.status = "working";
    this.applyPose(p, "work");
    this.setDeskVisual(p.cabinId, p.seat, { occupied: true, working: true });
  }

  private removePerson(id: string) {
    this.clearSofaIf(id);
    const p = this.people.get(id);
    if (!p) return;
    this.clearChat(p);
    p.container.destroy(true);
    this.people.delete(id);
  }

  private clearSofaIf(personId: string) {
    for (const s of this.sofas) {
      if (s.occupiedBy === personId) s.occupiedBy = null;
    }
  }

  // ——— Selection ———

  private selectPerson(id: string) {
    const p = this.people.get(id);
    if (!p) return;
    this.selectedKey = `agent:${id}`;
    const task = p.taskId ? this.tasks.get(p.taskId) : null;
    const bind = p.taskId ? this.bindings.get(p.taskId) : null;
    this.callbacks.onSelect({
      kind: "agent",
      agent: {
        id: p.id,
        name: p.name,
        role: p.role,
        cabinId: p.cabinId,
        status: p.workActive
          ? "working"
          : p.status === "called"
            ? "called"
            : p.status,
        taskId: p.taskId,
        taskTitle: task
          ? `${task.title}${bind?.delivery === "transit" ? " (in transit…)" : !p.workActive && p.taskId ? " (walking to desk…)" : ""}`
          : null,
        permanent: p.permanent,
      },
      task: task || null,
    });
    for (const person of this.people.values()) {
      person.sprite.setScale(person.id === id ? 1.12 : 1);
    }
  }

  private selectDesk(cabin: CabinDef, seat: number) {
    const person = [...this.people.values()].find((p) => p.cabinId === cabin.id && p.seat === seat);
    if (person) {
      this.selectPerson(person.id);
      return;
    }
    this.callbacks.onSelect({
      kind: "agent",
      agent: {
        id: `desk-${cabin.id}-${seat}`,
        name: `Empty desk · ${cabin.label}`,
        role: cabin.id,
        cabinId: cabin.id,
        status: "idle",
        permanent: false,
      },
      task: null,
    });
  }

  // ——— Idle AI (respects holdUntil) ———

  private advanceIdlePhase(p: PersonEnt, now: number) {
    if (p.taskId || this.leaving.has(p.id)) return;
    if (now < p.holdUntil) {
      // Forced sit after handoff
      const chair = this.deskChairFor(p);
      if (chair) this.setNav(p, chair);
      p.phase = "desk";
      p.phaseUntil = p.holdUntil;
      p.status = p.permanent ? "idle" : "hired";
      this.applyPose(p, "sit");
      this.setDeskVisual(p.cabinId, p.seat, { occupied: true, working: false });
      return;
    }

    this.clearSofaIf(p.id);
    this.clearChat(p);

    const from = p.phase;
    let next: IdlePhase = "desk";
    const r = Math.random();
    if (from === "desk") {
      if (r < 0.4) next = "roam";
      else if (r < 0.65) next = "sofa";
      else if (r < 0.85) next = "chat";
      else next = "desk";
    } else if (from === "sofa") {
      next = r < 0.5 ? "desk" : r < 0.8 ? "roam" : "chat";
    } else if (from === "roam") {
      next = r < 0.55 ? "desk" : r < 0.8 ? "sofa" : "chat";
    } else {
      next = r < 0.65 ? "desk" : "roam";
    }
    p.phase = next;

    const cabin = getCabin(this.mapData, p.cabinId);

    if (next === "desk") {
      const chair = this.deskChairFor(p);
      if (chair) this.setNav(p, chair);
      p.status = p.permanent ? "idle" : "hired";
      this.setDeskVisual(p.cabinId, p.seat, { occupied: true, working: false });
      p.phaseUntil = now + 7000 + Math.random() * 5000;
    } else if (next === "sofa") {
      const free = this.sofas.filter((s) => !s.occupiedBy && s.cabinId === p.cabinId);
      if (!free.length) {
        p.phase = "desk";
        this.advanceIdlePhase(p, now);
        return;
      }
      const sofa = free[Math.floor(Math.random() * free.length)];
      sofa.occupiedBy = p.id;
      this.setNav(p, {
        x: sofa.orient === "v" ? sofa.x + 8 : sofa.x,
        y: sofa.orient === "v" ? sofa.y : sofa.y - 4,
      });
      p.status = "sitting";
      p.phaseUntil = now + 6000 + Math.random() * 4000;
    } else if (next === "chat") {
      const partner = this.findChatPartner(p);
      if (!partner || !cabin) {
        p.phase = "roam";
        this.setNav(p, randomWalkableInCabin(cabin || this.mapData.cabins[0], this.walls, BODY_R));
        p.status = "roaming";
        this.applyPose(p, "stand");
        p.phaseUntil = now + 4000 + Math.random() * 3000;
        return;
      }
      // Meet near corridor midline in this cabin so path stays clear
      const cy = this.mapData.hall.y + this.mapData.hall.h / 2;
      const meetX = (p.container.x + partner.container.x) / 2;
      this.setNav(p, { x: meetX - 14, y: cy });
      this.setNav(partner, { x: meetX + 14, y: cy });
      p.status = partner.status = "chatting";
      p.chatPartner = partner.id;
      partner.chatPartner = p.id;
      partner.phase = "chat";
      partner.phaseUntil = p.phaseUntil = now + 3500 + Math.random() * 2000;
      this.applyPose(p, "stand");
      this.applyPose(partner, "stand");
      this.clearSofaIf(partner.id);
      this.showChat(p, CHAT_LINES[Math.floor(Math.random() * CHAT_LINES.length)]);
      this.showChat(partner, CHAT_LINES[Math.floor(Math.random() * CHAT_LINES.length)]);
    } else if (cabin) {
      this.setNav(p, randomWalkableInCabin(cabin, this.walls, BODY_R));
      p.status = "roaming";
      this.applyPose(p, "stand");
      p.phaseUntil = now + 4000 + Math.random() * 3000;
    }
  }

  private findChatPartner(p: PersonEnt): PersonEnt | null {
    const candidates = [...this.people.values()].filter(
      (o) =>
        o.id !== p.id &&
        o.cabinId === p.cabinId &&
        !this.leaving.has(o.id) &&
        !o.taskId &&
        this.time.now >= o.holdUntil &&
        o.status !== "working" &&
        o.status !== "called" &&
        o.status !== "chatting"
    );
    if (!candidates.length) return null;
    candidates.sort(
      (a, b) =>
        Math.hypot(a.container.x - p.container.x, a.container.y - p.container.y) -
        Math.hypot(b.container.x - p.container.x, b.container.y - p.container.y)
    );
    return candidates[0];
  }

  // ——— Frame update ———

  update(_t: number, dt: number) {
    const now = this.time.now;

    // Tokens follow corridor waypoints only (desk → corridor → desk)
    for (const [tid, tok] of [...this.tokens.entries()]) {
      const step = stepPath(tok.container.x, tok.container.y, tok.path, TOKEN_SPEED * dt);
      tok.container.x = step.x;
      tok.container.y = step.y;
      tok.path = step.path;
      if (step.arrived) this.onTokenArrived(tid);
    }

    for (const p of this.people.values()) {
      if (p.taskId && (p.status === "called" || p.status === "working")) {
        const arrived = this.stepNav(p, WORK_WALK * dt);
        if (arrived || atPoint(p.container, p.target, 8)) {
          this.tryActivateWork(p);
          if (!p.workActive) this.applyPose(p, "sit"); // waiting for token
        } else {
          this.applyPose(p, "stand");
        }
        continue;
      }

      if (!this.leaving.has(p.id) && now > p.phaseUntil) {
        this.advanceIdlePhase(p, now);
      }

      const arrived = atPoint(p.container, p.target, 8) && p.path.length === 0;
      if (
        (p.status === "sitting" || p.status === "idle" || p.status === "hired") &&
        arrived
      ) {
        this.applyPose(p, "sit");
      } else if (p.status === "roaming" || p.status === "chatting" || this.leaving.has(p.id)) {
        if (!arrived) this.applyPose(p, "stand");
      }

      const speed =
        (this.leaving.has(p.id)
          ? WORK_WALK
          : p.status === "roaming" || p.status === "chatting"
            ? IDLE_WALK
            : 0.07) * dt;
      this.stepNav(p, speed);
    }
  }
}
