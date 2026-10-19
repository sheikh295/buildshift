import Phaser from "phaser";
import type { AgentInfo, CabinDef, OfficeMap, Selection, Task } from "@/lib/types";
import {
  TERMINAL,
  activeTasksInCabin,
  cabinForTaskState,
  deskSlots,
  getCabin,
  hireCount,
  tokenLane,
} from "./cabins";
import { cabinAccent, ensureOfficeTextures } from "./sprites";
import {
  WallRect,
  buildWalls,
  moveCollide,
  randomWalkablePoint,
} from "./walls";

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
  status: "idle" | "working" | "roaming" | "hired" | "sitting" | "chatting";
  taskId: string | null;
  target: { x: number; y: number };
  phase: IdlePhase;
  phaseUntil: number;
  chatPartner: string | null;
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
  x: number;
  y: number;
  orient: "h" | "v";
  sprite: Phaser.GameObjects.Image;
  occupiedBy: string | null;
};

type TokenEnt = {
  taskId: string;
  container: Phaser.GameObjects.Container;
  label: Phaser.GameObjects.Text;
  target: { x: number; y: number };
  cabinId: string;
  exiting: boolean;
};

const HIRE_NAMES = [
  "Alex", "Sam", "Jordan", "Taylor", "Quinn", "Avery",
  "Reese", "Blake", "Drew", "Jamie", "Kai", "Noah",
];
const BODY_R = 11;
const CHAIR_N = 28; // chair sits north of desk
const CHAT_LINES = ["hey", "ship it?", "on it", "nice", "lol", "sync?", "ack", "👀", "brb", "ok"];

function chairOf(deskX: number, deskY: number) {
  return { x: deskX, y: deskY - CHAIR_N };
}

export class OfficeScene extends Phaser.Scene {
  private mapData!: OfficeMap;
  private callbacks!: OfficeCallbacks;
  private tasks = new Map<string, Task>();
  private people = new Map<string, PersonEnt>();
  private desks: DeskEnt[] = [];
  private sofas: SofaEnt[] = [];
  private tokens = new Map<string, TokenEnt>();
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
    this.assignWork(tasks);
    this.syncTokens(tasks);
  }

  flashEvent(kind: string, taskId?: string | null) {
    if (!taskId) return;
    const tok = this.tokens.get(taskId);
    if (tok) {
      this.tweens.add({
        targets: tok.container,
        scaleX: 1.2,
        scaleY: 1.2,
        yoyo: true,
        duration: 160,
      });
    }
  }

  private drawHall() {
    const { width, height, hall, cabins } = this.mapData;
    const g = this.add.graphics().setDepth(2);
    const t = hall.wallThickness || 16;

    g.fillStyle(0x0c1018, 1);
    g.fillRect(0, 0, width, height);

    const { x: hx, y: hy, w: hw, h: hh, radius: r = 20 } = hall;

    // Floor
    g.fillStyle(0xa89880, 1);
    g.fillRoundedRect(hx, hy, hw, hh, r);
    g.fillStyle(0xb8a890, 1);
    g.fillRoundedRect(hx + t, hy + t, hw - t * 2, hh - t * 2, Math.max(4, r - 8));
    g.lineStyle(1, 0x968870, 0.4);
    for (let y = hy + t + 8; y < hy + hh - t; y += 20) {
      g.lineBetween(hx + t + 4, y, hx + hw - t - 4, y);
    }

    // Thick outer walls
    g.fillStyle(0x2a3344, 1);
    g.fillRect(hx, hy, hw, t);
    g.fillRect(hx, hy + hh - t, hw, t);
    g.fillRect(hx, hy, t, hh);
    g.fillRect(hx + hw - t, hy, t, hh);
    g.lineStyle(2, 0x1a2230, 1);
    g.strokeRoundedRect(hx, hy, hw, hh, r);
    g.lineStyle(1, 0x5b9cff, 0.25);
    g.strokeRoundedRect(hx + 2, hy + 2, hw - 4, hh - 4, r - 2);

    this.add
      .text(width / 2, 24, "BUILDSHIFT  ·  OPERATIONS HALL", {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "14px",
        color: "#9ec1ff",
        resolution: 2,
      })
      .setOrigin(0.5)
      .setDepth(50);

    // Thick division walls (from wall rects after outer)
    const midY = hy + hh / 2;
    const gap = hall.corridorGap || 52;
    for (const w of this.walls) {
      // skip outer walls for redraw detail — draw all partition-like vertical thick walls
      if (w.h > t * 2 && w.w <= t + 4) {
        g.fillStyle(0x343f52, 1);
        g.fillRect(w.x, w.y, w.w, w.h);
        g.fillStyle(0x1e2838, 1);
        g.fillRect(w.x, w.y, 3, w.h);
        g.fillRect(w.x + w.w - 3, w.y, 3, w.h);
        // baseboard
        g.fillStyle(0x4a5568, 0.5);
        g.fillRect(w.x - 2, w.y + w.h - 4, w.w + 4, 4);
      }
    }

    // Doorway jambs at corridor
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
      // Zone carpet panel
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
    }

    this.add
      .text(width / 2, height - 18, "thick walls · short corridor · desks stay empty until hired", {
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: "11px",
        color: "#6b7c90",
        resolution: 2,
      })
      .setOrigin(0.5)
      .setDepth(50);
  }

  private placeDecor(cabin: CabinDef) {
    // Rugs under desk clusters
    if (cabin.id === "developers") {
      this.add.image(505, 350, "rug").setDepth(4).setScale(2.4, 3.5).setAlpha(0.55);
    } else if (cabin.id === "qa") {
      this.add.image(880, 350, "rug").setDepth(4).setScale(1.7, 3.3).setAlpha(0.5);
    } else if (cabin.id === "planner") {
      this.add.image(150, 350, "rug").setDepth(4).setScale(1.35, 2.9).setAlpha(0.45);
    } else if (cabin.id === "integrate") {
      this.add.image(1130, 350, "rug").setDepth(4).setScale(1.25, 2.8).setAlpha(0.45);
    }

    // Plants in corners of each zone
    const plants = [
      { x: cabin.x + 28, y: cabin.y + 70 },
      { x: cabin.x + cabin.w - 28, y: cabin.y + 70 },
      { x: cabin.x + 28, y: cabin.y + cabin.h - 50 },
      { x: cabin.x + cabin.w - 28, y: cabin.y + cabin.h - 50 },
    ];
    for (const p of plants) {
      this.add.image(p.x, p.y, "plant").setDepth(6).setScale(1.15);
    }
  }

  private placeFurniture(cabin: CabinDef) {
    for (const s of cabin.sofas || []) {
      const key = s.orient === "v" ? "sofa_v" : "sofa_h";
      const sprite = this.add
        .image(s.x, s.y, key)
        .setDepth(6)
        .setInteractive({ useHandCursor: true });
      sprite.on("pointerdown", (ptr: Phaser.Input.Pointer) => {
        ptr.event.stopPropagation();
        const sitter = this.sofas.find((x) => x.id === s.id)?.occupiedBy;
        if (sitter) this.selectPerson(sitter);
      });
      this.sofas.push({
        id: s.id,
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
      // Chair on the north (top) side of the desk
      const chairImg = this.add
        .image(chair.x, chair.y, "chair")
        .setDepth(6)
        .setAlpha(0.6);

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
        this.setDeskOccupied(cabin.id, p.seat, true);
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
      phase: "desk",
      phaseUntil: this.time.now + 6000 + Math.random() * 5000,
      chatPartner: null,
    });
  }

  private applyPose(p: PersonEnt, pose: "stand" | "sit" | "work") {
    const key =
      pose === "sit"
        ? `person_${p.role}_sit`
        : pose === "work"
          ? `person_${p.role}_work`
          : `person_${p.role}`;
    const fallback = `person_${p.role}`;
    p.sprite.setTexture(this.textures.exists(key) ? key : fallback);
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

  private deskChairFor(p: PersonEnt): { x: number; y: number } | null {
    const cabin = getCabin(this.mapData, p.cabinId);
    if (!cabin) return null;
    const slot = deskSlots(cabin).find((s) => s.seat === p.seat);
    if (!slot) return null;
    return chairOf(slot.x, slot.y);
  }

  private setDeskOccupied(cabinId: string, seat: number, occupied: boolean) {
    const d = this.desks.find((x) => x.cabinId === cabinId && x.seat === seat);
    if (!d) return;
    d.occupied = occupied;
    d.desk.setTexture(occupied ? "desk" : "desk_empty");
    d.chair.setAlpha(occupied ? 1 : 0.6);
  }

  private syncHiring(tasks: Task[]) {
    for (const cabin of this.mapData.cabins || []) {
      if (!cabin.maxHire) continue;
      const needed = hireCount(cabin, tasks);
      const hired = [...this.people.values()].filter(
        (p) => p.cabinId === cabin.id && !p.permanent && !this.leaving.has(p.id)
      );
      const slots = deskSlots(cabin);

      while (hired.length < needed) {
        const seat = this.nextFreeHireSeat(cabin, hired);
        if (seat < 0) break;
        const slot = slots.find((s) => s.seat === seat) || slots[0];
        const role =
          cabin.id === "qa"
            ? tasks.some((t) => t.state === "reviewing")
              ? "reviewer"
              : "test_author"
            : "implementer";
        const id = `hire-${cabin.id}-${this.hireSeq++}`;
        const name = HIRE_NAMES[this.hireSeq % HIRE_NAMES.length];
        const door = {
          x: this.mapData.hall.x + this.mapData.hall.w / 2,
          y: this.mapData.hall.y + this.mapData.hall.h / 2,
        };
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
        const chair = chairOf(slot.x, slot.y);
        person.target = chair;
        person.phase = "desk";
        person.phaseUntil = this.time.now + 7000 + Math.random() * 4000;
        this.setDeskOccupied(cabin.id, seat, true);
        hired.push(person);
      }

      const liveHired = [...this.people.values()].filter(
        (p) => p.cabinId === cabin.id && !p.permanent && !this.leaving.has(p.id)
      );
      if (liveHired.length > needed) {
        const extra = [...liveHired].reverse().find((h) => !h.taskId);
        if (extra) {
          this.leaving.add(extra.id);
          this.clearSofaIf(extra.id);
          this.setDeskOccupied(cabin.id, extra.seat, false);
          extra.taskId = null;
          extra.status = "roaming";
          const hall = this.mapData.hall;
          extra.target = {
            x: hall.x + hall.w / 2,
            y: hall.y + hall.h - (hall.wallThickness || 16) - 8,
          };
          this.time.delayedCall(1200, () => {
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

  private assignWork(tasks: Task[]) {
    for (const p of this.people.values()) {
      if (p.status === "working") {
        p.status = p.permanent ? "idle" : "hired";
        p.taskId = null;
      }
    }

    for (const cabin of this.mapData.cabins || []) {
      const cabinTasks = activeTasksInCabin(cabin, tasks);
      const staff = [...this.people.values()]
        .filter((p) => p.cabinId === cabin.id && !this.leaving.has(p.id))
        .sort((a, b) => Number(b.permanent) - Number(a.permanent) || a.seat - b.seat);

      for (let i = 0; i < cabinTasks.length && i < staff.length; i++) {
        const person = staff[i];
        const task = cabinTasks[i];
        this.clearSofaIf(person.id);
        this.clearChat(person);
        person.taskId = task.id;
        person.status = "working";
        const slots = deskSlots(cabin);
        const slot = slots.find((s) => s.seat === person.seat) || slots[0];
        person.target = chairOf(slot.x, slot.y);
        this.setDeskOccupied(cabin.id, person.seat, true);
        this.applyPose(person, "work");
      }
    }
  }

  private syncTokens(tasks: Task[]) {
    const live = new Set<string>();
    const byCabin = new Map<string, Task[]>();
    for (const task of tasks) {
      if (TERMINAL.has(task.state) && !this.tokens.has(task.id)) continue;
      const cabinId = cabinForTaskState(task.state);
      if (!byCabin.has(cabinId)) byCabin.set(cabinId, []);
      if (!TERMINAL.has(task.state)) {
        byCabin.get(cabinId)!.push(task);
        live.add(task.id);
      } else if (this.tokens.has(task.id)) {
        live.add(task.id);
      }
    }

    for (const [cabinId, list] of byCabin) {
      const cabin = getCabin(this.mapData, cabinId);
      if (!cabin) continue;
      list.forEach((task, idx) => this.upsertToken(task, cabinId, tokenLane(cabin, idx, list.length)));
    }

    for (const task of tasks) {
      if (!TERMINAL.has(task.state)) continue;
      const tok = this.tokens.get(task.id);
      if (!tok || tok.exiting) continue;
      tok.exiting = true;
      const hall = this.mapData.hall;
      tok.target = { x: hall.x + hall.w - 48, y: hall.y + hall.h / 2 };
      this.time.delayedCall(1400, () => this.removeToken(task.id));
    }

    for (const id of [...this.tokens.keys()]) {
      if (!live.has(id) && !this.tokens.get(id)?.exiting) this.removeToken(id);
    }
  }

  private upsertToken(task: Task, cabinId: string, pos: { x: number; y: number }) {
    let tok = this.tokens.get(task.id);
    if (!tok) {
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
      const ring = this.add.circle(0, 0, 14, 0x000000, 0);
      const container = this.add.container(pos.x, pos.y, [ring, img, label]).setDepth(40);
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
        this.refreshSelectionStyles();
      });
      this.tweens.add({
        targets: img,
        y: -3,
        duration: 800 + Math.random() * 400,
        yoyo: true,
        repeat: -1,
        ease: "Sine.easeInOut",
      });
      tok = { taskId: task.id, container, label, target: pos, cabinId, exiting: false };
      this.tokens.set(task.id, tok);
    }
    tok.cabinId = cabinId;
    tok.target = pos;
    tok.label.setText(shorten(task.title, 14));
    const blocked = task.state === "blocked_human";
    const sel = this.selectedKey === `task:${task.id}`;
    (tok.container.list[0] as Phaser.GameObjects.Arc).setStrokeStyle(
      blocked || sel ? 2 : 0,
      blocked ? 0xffb020 : 0x5b9cff,
      blocked || sel ? 1 : 0
    );
  }

  private removeToken(id: string) {
    const tok = this.tokens.get(id);
    if (!tok) return;
    this.tweens.killTweensOf(tok.container);
    tok.container.destroy(true);
    this.tokens.delete(id);
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

  private selectPerson(id: string) {
    const p = this.people.get(id);
    if (!p) return;
    this.selectedKey = `agent:${id}`;
    const task = p.taskId ? this.tasks.get(p.taskId) : null;
    this.callbacks.onSelect({
      kind: "agent",
      agent: {
        id: p.id,
        name: p.name,
        role: p.role,
        cabinId: p.cabinId,
        status: p.status,
        taskId: p.taskId,
        taskTitle: task?.title || null,
        permanent: p.permanent,
      },
      task: task || null,
    });
    this.refreshSelectionStyles();
  }

  private selectDesk(cabin: CabinDef, seat: number) {
    const person = [...this.people.values()].find((p) => p.cabinId === cabin.id && p.seat === seat);
    if (person) {
      this.selectPerson(person.id);
      return;
    }
    this.selectedKey = `desk:${cabin.id}:${seat}`;
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
    this.refreshSelectionStyles();
  }

  private refreshSelectionStyles() {
    for (const tok of this.tokens.values()) {
      const sel = this.selectedKey === `task:${tok.taskId}`;
      (tok.container.list[0] as Phaser.GameObjects.Arc).setStrokeStyle(sel ? 2 : 0, 0x5b9cff, sel ? 1 : 0);
    }
    for (const p of this.people.values()) {
      p.sprite.setScale(this.selectedKey === `agent:${p.id}` ? 1.12 : 1);
    }
  }

  /** Balanced idle: desk sit ↔ brief roam/chat ↔ sofa — not stuck sitting or endlessly walking. */
  private advanceIdlePhase(p: PersonEnt, now: number) {
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
      if (r < 0.5) next = "desk";
      else if (r < 0.8) next = "roam";
      else next = "chat";
    } else if (from === "roam") {
      if (r < 0.55) next = "desk";
      else if (r < 0.8) next = "sofa";
      else next = "chat";
    } else {
      // after chat
      next = r < 0.65 ? "desk" : "roam";
    }

    p.phase = next;

    if (next === "desk") {
      const chair = this.deskChairFor(p);
      if (chair) p.target = chair;
      p.status = p.permanent ? "idle" : "hired";
      this.setDeskOccupied(p.cabinId, p.seat, true);
      p.phaseUntil = now + 7000 + Math.random() * 5000; // 7–12s at desk
    } else if (next === "sofa") {
      const free = this.sofas.filter((s) => !s.occupiedBy);
      if (!free.length) {
        p.phase = "desk";
        this.advanceIdlePhase(p, now);
        return;
      }
      const sofa = free[Math.floor(Math.random() * free.length)];
      sofa.occupiedBy = p.id;
      p.target = {
        x: sofa.orient === "v" ? sofa.x + 8 : sofa.x,
        y: sofa.orient === "v" ? sofa.y : sofa.y - 4,
      };
      p.status = "sitting";
      p.phaseUntil = now + 6000 + Math.random() * 4000; // 6–10s on sofa
    } else if (next === "chat") {
      const partner = this.findChatPartner(p);
      if (!partner) {
        p.phase = "roam";
        p.target = randomWalkablePoint(this.mapData, this.walls, BODY_R);
        p.status = "roaming";
        this.applyPose(p, "stand");
        p.phaseUntil = now + 4000 + Math.random() * 3000;
        return;
      }
      const mid = {
        x: (p.container.x + partner.container.x) / 2,
        y: (p.container.y + partner.container.y) / 2,
      };
      // slight offset so they face each other
      p.target = { x: mid.x - 14, y: mid.y };
      partner.target = { x: mid.x + 14, y: mid.y };
      p.status = "chatting";
      partner.status = "chatting";
      p.chatPartner = partner.id;
      partner.chatPartner = p.id;
      partner.phase = "chat";
      partner.phaseUntil = now + 3500 + Math.random() * 2000;
      p.phaseUntil = partner.phaseUntil;
      this.applyPose(p, "stand");
      this.applyPose(partner, "stand");
      this.clearSofaIf(partner.id);
      this.showChat(p, CHAT_LINES[Math.floor(Math.random() * CHAT_LINES.length)]);
      this.showChat(partner, CHAT_LINES[Math.floor(Math.random() * CHAT_LINES.length)]);
    } else {
      // roam — short stroll
      p.target = randomWalkablePoint(this.mapData, this.walls, BODY_R);
      p.status = "roaming";
      this.applyPose(p, "stand");
      p.phaseUntil = now + 4000 + Math.random() * 3000; // 4–7s
    }
  }

  private findChatPartner(p: PersonEnt): PersonEnt | null {
    const candidates = [...this.people.values()].filter(
      (o) =>
        o.id !== p.id &&
        !this.leaving.has(o.id) &&
        o.status !== "working" &&
        o.status !== "chatting" &&
        !o.taskId
    );
    if (!candidates.length) return null;
    candidates.sort(
      (a, b) =>
        Math.hypot(a.container.x - p.container.x, a.container.y - p.container.y) -
        Math.hypot(b.container.x - p.container.x, b.container.y - p.container.y)
    );
    return candidates[0];
  }

  update(_t: number, dt: number) {
    const now = this.time.now;
    for (const p of this.people.values()) {
      if (p.status === "working") {
        // Snap pose once arrived at chair
        const atChair =
          Math.hypot(p.container.x - p.target.x, p.container.y - p.target.y) < 4;
        if (atChair) this.applyPose(p, "work");
      } else if (!this.leaving.has(p.id) && now > p.phaseUntil) {
        this.advanceIdlePhase(p, now);
      }

      // Apply sit pose when arrived at seat/sofa
      if (
        (p.status === "sitting" || p.status === "idle" || p.status === "hired") &&
        Math.hypot(p.container.x - p.target.x, p.container.y - p.target.y) < 5
      ) {
        this.applyPose(p, "sit");
      } else if (p.status === "roaming" || p.status === "chatting" || this.leaving.has(p.id)) {
        if (Math.hypot(p.container.x - p.target.x, p.container.y - p.target.y) > 8) {
          this.applyPose(p, "stand");
        }
      }

      const speed =
        (p.status === "roaming" || p.status === "chatting" || this.leaving.has(p.id)
          ? 0.055
          : 0.07) * dt;
      const next = moveCollide(
        p.container.x,
        p.container.y,
        p.target.x,
        p.target.y,
        speed,
        BODY_R,
        this.walls
      );
      p.container.x = next.x;
      p.container.y = next.y;
    }

    for (const tok of this.tokens.values()) {
      const dx = tok.target.x - tok.container.x;
      tok.container.x += Math.sign(dx) * Math.min(Math.abs(dx), 0.09 * dt);
      const dy = tok.target.y - tok.container.y;
      if (Math.abs(dy) > 12) {
        tok.container.y += Math.sign(dy) * Math.min(Math.abs(dy), 0.06 * dt);
      }
    }
  }
}

function shorten(s: string, n: number) {
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}
