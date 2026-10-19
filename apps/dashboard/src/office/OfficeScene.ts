import Phaser from "phaser";
import type { OfficeMap, Task } from "@/lib/types";

export type OfficeCallbacks = {
  onSelectTask: (task: Task | null) => void;
};

type AgentSprite = {
  taskId: string;
  container: Phaser.GameObjects.Container;
  body: Phaser.GameObjects.Rectangle;
  bubble: Phaser.GameObjects.Text;
  target: { x: number; y: number };
};

const STATE_ZONE: Record<string, string> = {
  planned: "planner",
  ready: "implementer",
  test_authoring: "test_author",
  coding: "implementer",
  testing: "test_author",
  reviewing: "reviewer",
  integrating: "integrating",
  merged: "exit",
  blocked_human: "planner",
  failed: "exit",
  parked: "exit",
  stopped: "exit",
};

export class OfficeScene extends Phaser.Scene {
  private mapData!: OfficeMap;
  private agents = new Map<string, AgentSprite>();
  private tasks = new Map<string, Task>();
  private callbacks!: OfficeCallbacks;
  private selectedId: string | null = null;

  constructor() {
    super("OfficeScene");
  }

  init(data: { map: OfficeMap; callbacks: OfficeCallbacks }) {
    this.mapData = data.map;
    this.callbacks = data.callbacks;
  }

  create() {
    const { width, height, zones, roles } = this.mapData;
    this.cameras.main.setBackgroundColor("#1a2332");

    // Floor grid
    const g = this.add.graphics();
    g.lineStyle(1, 0x2a3a4f, 0.5);
    for (let x = 0; x <= width; x += 32) g.lineBetween(x, 0, x, height);
    for (let y = 0; y <= height; y += 32) g.lineBetween(0, y, width, y);

    // Desks / zones
    for (const [key, zone] of Object.entries(zones)) {
      const color = Phaser.Display.Color.HexStringToColor(
        roles[key]?.color || "#5c6b7a"
      ).color;
      const desk = this.add.rectangle(zone.x, zone.y, 72, 48, color, 0.35);
      desk.setStrokeStyle(2, color, 0.9);
      this.add
        .text(zone.x, zone.y - 40, zone.label, {
          fontFamily: "monospace",
          fontSize: "11px",
          color: "#c8d4e0",
        })
        .setOrigin(0.5);
    }

    this.add
      .text(16, height - 24, "BUILDSHIFT OFFICE", {
        fontFamily: "monospace",
        fontSize: "14px",
        color: "#8ab4f8",
      })
      .setOrigin(0, 0.5);
  }

  syncTasks(tasks: Task[]) {
    const live = new Set<string>();
    for (const task of tasks) {
      if (["merged", "failed", "parked", "stopped"].includes(task.state)) {
        // keep briefly then remove
        if (this.agents.has(task.id)) {
          const ag = this.agents.get(task.id)!;
          const exit = this.mapData.zones.exit || { x: 860, y: 400 };
          ag.target = { x: exit.x, y: exit.y };
          this.tasks.set(task.id, task);
          live.add(task.id);
          // schedule cleanup
          this.time.delayedCall(2500, () => this.removeAgent(task.id));
        }
        continue;
      }
      live.add(task.id);
      this.tasks.set(task.id, task);
      this.upsertAgent(task);
    }
    for (const id of [...this.agents.keys()]) {
      if (!live.has(id) && !["merged", "failed", "parked", "stopped"].includes(this.tasks.get(id)?.state || "")) {
        this.removeAgent(id);
      }
    }
  }

  flashEvent(kind: string, taskId?: string | null) {
    if (!taskId) return;
    const ag = this.agents.get(taskId);
    if (!ag) return;
    this.tweens.add({
      targets: ag.body,
      scaleX: 1.25,
      scaleY: 1.25,
      yoyo: true,
      duration: 180,
    });
    if (kind.includes("hitl") || kind.includes("blocked")) {
      ag.bubble.setText("?");
      ag.bubble.setVisible(true);
    }
  }

  private upsertAgent(task: Task) {
    const role = task.stage || task.role || "implementer";
    const zoneKey = STATE_ZONE[task.state] || role;
    const zone = this.mapData.zones[zoneKey] || this.mapData.zones.implementer;
    const colorHex = this.mapData.roles[role]?.color || this.mapData.roles.implementer?.color || "#f0a202";
    const color = Phaser.Display.Color.HexStringToColor(colorHex).color;

    let ag = this.agents.get(task.id);
    if (!ag) {
      const body = this.add.rectangle(0, 0, 18, 22, color);
      body.setStrokeStyle(2, 0xffffff, 0.5);
      const label = this.add
        .text(0, 18, task.title.slice(0, 10), {
          fontFamily: "monospace",
          fontSize: "9px",
          color: "#e8eef5",
        })
        .setOrigin(0.5, 0);
      const bubble = this.add
        .text(0, -22, "!", {
          fontFamily: "monospace",
          fontSize: "14px",
          color: "#ffb020",
          backgroundColor: "#1a2332",
        })
        .setOrigin(0.5)
        .setVisible(task.state === "blocked_human");
      const container = this.add.container(zone.x, zone.y + 30, [body, label, bubble]);
      container.setSize(24, 40);
      container.setInteractive({ useHandCursor: true });
      container.on("pointerdown", () => {
        this.selectedId = task.id;
        this.callbacks.onSelectTask(this.tasks.get(task.id) || task);
      });
      ag = { taskId: task.id, container, body, bubble, target: { x: zone.x, y: zone.y + 30 } };
      this.agents.set(task.id, ag);
    }

    ag.target = {
      x: zone.x + (Math.random() * 20 - 10),
      y: zone.y + 28 + (Math.random() * 10 - 5),
    };
    ag.bubble.setVisible(task.state === "blocked_human");
    ag.bubble.setText(task.state === "blocked_human" ? "?" : "!");
    if (this.selectedId === task.id) {
      ag.body.setStrokeStyle(3, 0xffffff, 1);
    } else {
      ag.body.setStrokeStyle(2, 0xffffff, 0.5);
    }
  }

  private removeAgent(id: string) {
    const ag = this.agents.get(id);
    if (!ag) return;
    ag.container.destroy(true);
    this.agents.delete(id);
    this.tasks.delete(id);
    if (this.selectedId === id) {
      this.selectedId = null;
      this.callbacks.onSelectTask(null);
    }
  }

  update(_t: number, dt: number) {
    const speed = 0.08 * dt;
    for (const ag of this.agents.values()) {
      const dx = ag.target.x - ag.container.x;
      const dy = ag.target.y - ag.container.y;
      const dist = Math.hypot(dx, dy);
      if (dist > 1) {
        ag.container.x += (dx / dist) * Math.min(speed, dist);
        ag.container.y += (dy / dist) * Math.min(speed, dist);
      }
    }
  }
}
