import Phaser from "phaser";

/** Generate crisp pixel textures once per game. */
export function ensureOfficeTextures(scene: Phaser.Scene) {
  if (scene.textures.exists("desk")) return;

  // Desk occupied (larger)
  const desk = scene.make.graphics({ x: 0, y: 0 }, false);
  desk.fillStyle(0x5c3a1e, 1);
  desk.fillRect(4, 22, 48, 16);
  desk.fillStyle(0x8b5a2b, 1);
  desk.fillRect(0, 14, 56, 14);
  desk.fillStyle(0xb07840, 1);
  desk.fillRect(0, 14, 56, 4);
  desk.fillStyle(0x2a2a2a, 1);
  desk.fillRect(10, 4, 22, 12);
  desk.fillStyle(0x1a1a1a, 1);
  desk.fillRect(12, 2, 18, 4);
  desk.fillStyle(0x5eb0ff, 1);
  desk.fillRect(13, 6, 16, 8);
  desk.fillStyle(0xffffff, 0.25);
  desk.fillRect(14, 7, 6, 3);
  desk.fillStyle(0x444444, 1);
  desk.fillRect(36, 8, 14, 6);
  desk.generateTexture("desk", 56, 40);
  desk.destroy();

  // Empty desk
  const empty = scene.make.graphics({ x: 0, y: 0 }, false);
  empty.fillStyle(0x4a3220, 1);
  empty.fillRect(4, 22, 48, 16);
  empty.fillStyle(0x6e4a2e, 1);
  empty.fillRect(0, 14, 56, 14);
  empty.fillStyle(0x8a6840, 1);
  empty.fillRect(0, 14, 56, 4);
  empty.fillStyle(0x3a3a3a, 1);
  empty.fillRect(10, 4, 22, 12);
  empty.fillStyle(0x2a2a2a, 1);
  empty.fillRect(12, 2, 18, 4);
  empty.fillStyle(0x666666, 0.55);
  empty.fillRect(13, 6, 16, 8);
  empty.fillStyle(0x555555, 1);
  empty.fillRect(36, 8, 14, 6);
  empty.generateTexture("desk_empty", 56, 40);
  empty.destroy();

  // Chair
  const chair = scene.make.graphics({ x: 0, y: 0 }, false);
  chair.fillStyle(0x2d3340, 1);
  chair.fillRect(6, 14, 20, 12);
  chair.fillStyle(0x4a5568, 1);
  chair.fillRect(6, 4, 20, 14);
  chair.fillStyle(0x3d4656, 1);
  chair.fillRect(4, 4, 4, 16);
  chair.fillStyle(0x1a1f28, 1);
  chair.fillRect(8, 26, 5, 6);
  chair.fillRect(19, 26, 5, 6);
  chair.generateTexture("chair", 32, 32);
  chair.destroy();

  // Sofa horizontal (large)
  const sofaH = scene.make.graphics({ x: 0, y: 0 }, false);
  sofaH.fillStyle(0x1e2838, 1);
  sofaH.fillRoundedRect(0, 12, 88, 32, 8);
  sofaH.fillStyle(0x3d5a80, 1);
  sofaH.fillRoundedRect(4, 4, 80, 28, 8);
  sofaH.fillStyle(0x2a4060, 1);
  sofaH.fillRoundedRect(8, 8, 28, 18, 5);
  sofaH.fillRoundedRect(44, 8, 28, 18, 5);
  sofaH.fillStyle(0x152030, 1);
  sofaH.fillRect(6, 38, 10, 8);
  sofaH.fillRect(72, 38, 10, 8);
  sofaH.generateTexture("sofa_h", 88, 48);
  sofaH.destroy();

  // Sofa vertical
  const sofaV = scene.make.graphics({ x: 0, y: 0 }, false);
  sofaV.fillStyle(0x1e2838, 1);
  sofaV.fillRoundedRect(12, 0, 32, 88, 8);
  sofaV.fillStyle(0x3d5a80, 1);
  sofaV.fillRoundedRect(4, 4, 28, 80, 8);
  sofaV.fillStyle(0x2a4060, 1);
  sofaV.fillRoundedRect(8, 8, 18, 28, 5);
  sofaV.fillRoundedRect(8, 44, 18, 28, 5);
  sofaV.fillStyle(0x152030, 1);
  sofaV.fillRect(38, 6, 8, 10);
  sofaV.fillRect(38, 72, 8, 10);
  sofaV.generateTexture("sofa_v", 48, 88);
  sofaV.destroy();

  // Plant pot (fill space)
  const plant = scene.make.graphics({ x: 0, y: 0 }, false);
  plant.fillStyle(0x8b4513, 1);
  plant.fillRect(8, 22, 16, 12);
  plant.fillStyle(0xa0522d, 1);
  plant.fillRect(6, 20, 20, 4);
  plant.fillStyle(0x2d6a4f, 1);
  plant.fillCircle(16, 14, 10);
  plant.fillStyle(0x40916c, 1);
  plant.fillCircle(10, 12, 6);
  plant.fillCircle(22, 12, 6);
  plant.generateTexture("plant", 32, 36);
  plant.destroy();

  // Floor rug
  const rug = scene.make.graphics({ x: 0, y: 0 }, false);
  rug.fillStyle(0x6b4f3a, 1);
  rug.fillRoundedRect(0, 0, 64, 40, 4);
  rug.fillStyle(0x8a6a4a, 1);
  rug.fillRoundedRect(4, 4, 56, 32, 3);
  rug.lineStyle(1, 0x5a4030, 0.6);
  rug.strokeRoundedRect(2, 2, 60, 36, 3);
  rug.generateTexture("rug", 64, 40);
  rug.destroy();

  // Task token
  const ticket = scene.make.graphics({ x: 0, y: 0 }, false);
  ticket.fillStyle(0xf5f0e1, 1);
  ticket.fillRect(0, 0, 24, 16);
  ticket.fillStyle(0xe8dcc8, 1);
  ticket.fillRect(0, 0, 24, 4);
  ticket.fillStyle(0x5b9cff, 1);
  ticket.fillRect(2, 6, 14, 2);
  ticket.fillStyle(0x888888, 1);
  ticket.fillRect(2, 10, 18, 1);
  ticket.fillRect(2, 13, 12, 1);
  ticket.generateTexture("ticket", 24, 16);
  ticket.destroy();

  const roleColors: Record<string, { shirt: number; skin: number; hair: number }> = {
    planner: { shirt: 0x2563eb, skin: 0xf0c9a0, hair: 0x3b2f2f },
    implementer: { shirt: 0xd97706, skin: 0xe8b896, hair: 0x1a1a1a },
    test_author: { shirt: 0x0d9488, skin: 0xf2d2b0, hair: 0x6b4423 },
    reviewer: { shirt: 0x7c3aed, skin: 0xe8c4a8, hair: 0x4a3728 },
    integrator: { shirt: 0x9333ea, skin: 0xf5d0b5, hair: 0x2c1810 },
  };

  for (const [role, c] of Object.entries(roleColors)) {
    drawPerson(scene, `person_${role}`, c.shirt, c.skin, c.hair, "stand");
    drawPerson(scene, `person_${role}_work`, c.shirt, c.skin, c.hair, "work");
    drawPerson(scene, `person_${role}_sit`, c.shirt, c.skin, c.hair, "sit");
  }
}

type Pose = "stand" | "work" | "sit";

function drawPerson(
  scene: Phaser.Scene,
  key: string,
  shirt: number,
  skin: number,
  hair: number,
  pose: Pose
) {
  const g = scene.make.graphics({ x: 0, y: 0 }, false);
  if (pose === "sit") {
    // Sitting: shorter legs tucked, body lower — clearly different from standing
    g.fillStyle(0x000000, 0.22);
    g.fillEllipse(12, 30, 18, 5);
    g.fillStyle(0x2d3748, 1);
    g.fillRect(5, 22, 7, 6);
    g.fillRect(14, 22, 7, 6);
    g.fillStyle(shirt, 1);
    g.fillRect(6, 12, 14, 12);
    g.fillStyle(skin, 1);
    g.fillRect(2, 14, 4, 7);
    g.fillRect(20, 14, 4, 7);
    g.fillStyle(skin, 1);
    g.fillRect(7, 2, 12, 11);
    g.fillStyle(hair, 1);
    g.fillRect(7, 0, 12, 5);
    g.fillRect(5, 2, 3, 5);
    g.fillRect(18, 2, 3, 4);
    g.fillStyle(0x1a1a1a, 1);
    g.fillRect(9, 7, 2, 2);
    g.fillRect(15, 7, 2, 2);
    g.generateTexture(key, 26, 32);
  } else {
    g.fillStyle(0x000000, 0.25);
    g.fillEllipse(12, 36, 16, 5);
    g.fillStyle(0x2d3748, 1);
    g.fillRect(7, 26, 5, 10);
    g.fillRect(14, 26, 5, 10);
    g.fillStyle(shirt, 1);
    g.fillRect(6, 14, 14, 13);
    g.fillStyle(skin, 1);
    if (pose === "work") {
      g.fillRect(2, 16, 4, 8);
      g.fillRect(20, 14, 4, 7);
    } else {
      g.fillRect(2, 16, 4, 10);
      g.fillRect(20, 16, 4, 10);
    }
    g.fillStyle(skin, 1);
    g.fillRect(7, 4, 12, 11);
    g.fillStyle(hair, 1);
    g.fillRect(7, 2, 12, 5);
    g.fillRect(5, 4, 3, 5);
    g.fillRect(18, 4, 3, 4);
    g.fillStyle(0x1a1a1a, 1);
    g.fillRect(9, 9, 2, 2);
    g.fillRect(15, 9, 2, 2);
    g.generateTexture(key, 26, 38);
  }
  g.destroy();
}

export function cabinAccent(hex: string): number {
  return Phaser.Display.Color.HexStringToColor(hex).color;
}
