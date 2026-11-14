// The world as a carved block on a walnut table, in three.js. It reads a run's world once and each
// frame after; it never changes a run. Town names are engine-made, so they may be painted into a
// texture; no agent text is drawn here.

import * as THREE from "./vendor/three.module.min.js";
import { OrbitControls } from "./vendor/OrbitControls.js";
import {
  INK, STYLE, STRATA, WATER_LEVEL, SEA_FLOOR, TABLE_LEVEL, STAGE_ORDER,
  centreHeight, cornerHeights, hash, hexRGB, mix, noise, seatLayout, tileRGB, tileXY,
} from "./world3d.js";

const TABLE_RGB = "#2b1e16";
const PAGE = "#1a120d";
const BRASS = "#c9a24a";
const MAX_PARTS = 6000;   // boxes, roofs and cones each; a 400-tick run uses well under this
const PULSE_MS = 900;
const TERRITORY_TINT = 0.24;

function srgb(rgb) {
  return new THREE.Color().setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace);
}

// A triangular prism one unit wide, deep and tall, its ridge along x: the roof of a house.
function prismGeometry() {
  const p = [-0.5, 0, -0.5, 0.5, 0, -0.5, 0.5, 0, 0.5, -0.5, 0, 0.5, -0.5, 1, 0, 0.5, 1, 0];
  const faces = [0, 1, 5, 0, 5, 4, 3, 4, 5, 3, 5, 2, 0, 4, 3, 1, 2, 5, 0, 3, 2, 0, 2, 1];
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(faces.flatMap((i) => p.slice(i * 3, i * 3 + 3)), 3));
  g.computeVertexNormals();
  return g;
}

// A wood-grain texture for the table, drawn from the tile hash.
function walnut() {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const g = canvas.getContext("2d");
  const base = hexRGB(TABLE_RGB);
  const image = g.createImageData(512, 512);
  for (let y = 0; y < 512; y++) {
    for (let x = 0; x < 512; x++) {
      const grain = Math.sin((x + noise(x / 60, y / 9, 31) * 40) * 0.18) * 0.5 + 0.5;
      const k = 0.78 + grain * 0.22 + (noise(x / 6, y / 140, 32) - 0.5) * 0.12;
      const i = (y * 512 + x) * 4;
      image.data[i] = base[0] * k;
      image.data[i + 1] = base[1] * k;
      image.data[i + 2] = base[2] * k;
      image.data[i + 3] = 255;
    }
  }
  g.putImageData(image, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(6, 6);
  return texture;
}

// A town's name card, painted once per town and kept.
function placard(name) {
  const canvas = document.createElement("canvas");
  const g = canvas.getContext("2d");
  const font = "500 44px 'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif";
  g.font = font;
  const width = Math.ceil(g.measureText(name).width) + 36;
  canvas.width = width;
  canvas.height = 68;
  g.font = font;
  g.fillStyle = "rgba(233,223,201,0.92)";
  g.fillRect(0, 0, width, 68);
  g.strokeStyle = "rgba(43,30,22,0.8)";
  g.lineWidth = 3;
  g.strokeRect(1.5, 1.5, width - 3, 65);
  g.fillStyle = "#2b1e16";
  g.textBaseline = "middle";
  g.fillText(name, 18, 36);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthWrite: false }));
  sprite.scale.set((width / 68) * 0.55, 0.55, 1);
  sprite.center.set(0.5, 0);
  return sprite;
}

// Instanced parts with a colour each, filled afresh for every frame.
class Parts {
  constructor(geometry, material, scene) {
    this.mesh = new THREE.InstancedMesh(geometry, material, MAX_PARTS);
    this.mesh.castShadow = this.mesh.receiveShadow = true;
    this.mesh.count = 0;
    this.mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.matrix = new THREE.Matrix4();
    this.quaternion = new THREE.Quaternion();
    this.up = new THREE.Vector3(0, 1, 0);
    scene.add(this.mesh);
  }

  clear() { this.mesh.count = 0; }

  add(x, y, z, sx, sy, sz, turn, color) {
    if (this.mesh.count >= MAX_PARTS) return;
    this.quaternion.setFromAxisAngle(this.up, turn);
    this.matrix.compose(new THREE.Vector3(x, y, z), this.quaternion, new THREE.Vector3(sx, sy, sz));
    this.mesh.setMatrixAt(this.mesh.count, this.matrix);
    this.mesh.setColorAt(this.mesh.count, color);
    this.mesh.count++;
  }

  done() {
    this.mesh.instanceMatrix.needsUpdate = true;
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
  }
}

export function createScene(container, { onPick, onHover }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });   // throws where WebGL is missing
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.setAttribute("aria-label", "The world as a block on a table. Drag to turn it, scroll to zoom, click a town to read about it.");
  renderer.domElement.tabIndex = 0;
  container.append(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(PAGE);
  scene.fog = new THREE.Fog(PAGE, 150, 320);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.5, 600);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.minDistance = 8;
  controls.maxDistance = 190;
  controls.minPolarAngle = 0.12;
  controls.maxPolarAngle = 1.32;      // never below the table
  controls.screenSpacePanning = false;

  scene.add(new THREE.HemisphereLight("#d9d2c0", "#3a2a1e", 1.1));
  const sun = new THREE.DirectionalLight("#fff1d6", 2.4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0006;
  sun.shadow.normalBias = 0.02;
  scene.add(sun, sun.target);

  const table = new THREE.Mesh(new THREE.PlaneGeometry(700, 700),
                               new THREE.MeshStandardMaterial({ map: walnut(), roughness: 0.62 }));
  table.rotation.x = -Math.PI / 2;
  table.position.y = TABLE_LEVEL;
  table.receiveShadow = true;
  scene.add(table);

  const flat = (opts) => new THREE.MeshStandardMaterial({ flatShading: true, roughness: 0.9, ...opts });
  const boxes = new Parts(new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), flat({}), scene);
  const roofs = new Parts(prismGeometry(), flat({}), scene);
  const cones = new Parts(new THREE.ConeGeometry(0.5, 1, 5).translate(0, 0.5, 0), flat({}), scene);
  const conifers = new Parts(new THREE.ConeGeometry(0.26, 0.95, 5).translate(0, 0.47, 0), flat({}), scene);
  const crowns = new Parts(new THREE.OctahedronGeometry(0.3).translate(0, 0.62, 0), flat({}), scene);
  const rocks = new Parts(new THREE.IcosahedronGeometry(0.22), flat({}), scene);

  const ring = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.08, 40),
                              new THREE.MeshBasicMaterial({ color: BRASS, side: THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2;
  ring.visible = false;
  scene.add(ring);

  let world = null, size = 0, half = 0;
  let land = null, landColors = null, baseRGB = null, borders = null, water = null, walls = null;
  let trees = [];          // { kind, x, z, y, s, turn, color, tile }
  let frame = null, selected = null;
  const signs = new Map(); // settlement id -> sprite
  let pulses = [];         // { mesh, start }
  let wanted = true;

  const at = (x, y) => ({ x: x - half + 0.5, z: y - half + 0.5 });
  const groundY = (x, y) => Math.max(centreHeight(world, x, y), WATER_LEVEL);

  function requestRender() { wanted = true; }

  function disposeOf(mesh) {
    if (!mesh) return;
    scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }

  // ---------- the block, carved once per run ----------

  function carve() {
    const n = size, corners = cornerHeights(world);
    const corner = (cx, cy) => corners[cy * (n + 1) + cx];
    const positions = new Float32Array(n * n * 12 * 3);
    baseRGB = new Float32Array(n * n * 3);
    let p = 0;
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const x0 = x - half, z0 = y - half;
        const c = [x0 + 0.5, centreHeight(world, x, y), z0 + 0.5];
        const k = [[x0, corner(x, y), z0], [x0 + 1, corner(x + 1, y), z0],
                   [x0 + 1, corner(x + 1, y + 1), z0 + 1], [x0, corner(x, y + 1), z0 + 1]];
        for (let i = 0; i < 4; i++) {
          const a = k[i], b = k[(i + 1) % 4];
          positions.set([...c, ...b, ...a], p);   // counter-clockwise from above
          p += 9;
        }
        baseRGB.set(tileRGB(world, x, y), (y * n + x) * 3);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    landColors = new THREE.BufferAttribute(new Float32Array(positions.length), 3);
    geometry.setAttribute("color", landColors);
    geometry.computeVertexNormals();
    land = new THREE.Mesh(geometry, flat({ vertexColors: true }));
    land.receiveShadow = land.castShadow = true;
    scene.add(land);

    // Four cut sides, banded in strata.
    const wall = [], wallColor = [];
    const sides = [];
    for (let i = 0; i < n; i++) {
      sides.push([[i, 0], [i + 1, 0], [-half + i, -half, -half + i + 1, -half]]);
      sides.push([[i + 1, n], [i, n], [-half + i + 1, half, -half + i, half]]);
      sides.push([[0, i + 1], [0, i], [-half, -half + i + 1, -half, -half + i]]);
      sides.push([[n, i], [n, i + 1], [half, -half + i, half, -half + i + 1]]);
    }
    for (const [[ax, ay], [bx, by], [x1, z1, x2, z2]] of sides) {
      let topA = corner(ax, ay), topB = corner(bx, by);
      for (const [floor, rgb] of STRATA) {
        if (floor >= Math.min(topA, topB)) continue;
        const jitter = 0.94 + hash(Math.round(x1 * 3), Math.round(z1 * 3), Math.round(floor)) * 0.1;
        const color = srgb(rgb.map((v) => v * jitter));
        wall.push(x1, topA, z1, x1, floor, z1, x2, floor, z2, x1, topA, z1, x2, floor, z2, x2, topB, z2);
        for (let v = 0; v < 6; v++) wallColor.push(color.r, color.g, color.b);
        topA = topB = floor;
      }
    }
    const wallGeometry = new THREE.BufferGeometry();
    wallGeometry.setAttribute("position", new THREE.Float32BufferAttribute(wall, 3));
    wallGeometry.setAttribute("color", new THREE.Float32BufferAttribute(wallColor, 3));
    wallGeometry.computeVertexNormals();
    walls = new THREE.Mesh(wallGeometry, flat({ vertexColors: true, side: THREE.DoubleSide }));
    walls.castShadow = walls.receiveShadow = true;
    scene.add(walls);

    // The sea as a slab of glass-clear water, its cut edge showing the depth.
    const depth = WATER_LEVEL - SEA_FLOOR + 0.3;
    water = new THREE.Mesh(new THREE.BoxGeometry(n - 0.02, depth, n - 0.02),
                           new THREE.MeshStandardMaterial({ color: "#2f5a70", transparent: true, opacity: 0.62,
                                                            roughness: 0.18, metalness: 0.05 }));
    water.position.y = WATER_LEVEL - depth / 2;
    water.receiveShadow = true;
    scene.add(water);

    // Trees and rocks stay put for the whole run; a tile that gets built on hides its own.
    trees = [];
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const code = world.biome[y][x];
        if (world.river[y][x] === "1" || code === "S") continue;
        const chance = { F: 1.6, T: 0.4, P: 0.07, C: 0.03 }[code] || 0;
        const many = Math.floor(chance) + (hash(x, y, 21) < chance % 1 ? 1 : 0);
        for (let i = 0; i < many; i++) {
          const { x: wx, z: wz } = at(x, y);
          const dx = (hash(x, y, 22 + i) - 0.5) * 0.7, dz = (hash(x, y, 30 + i) - 0.5) * 0.7;
          const conifer = code === "T" || hash(x, y, 40 + i) < 0.25;
          const green = conifer ? [44, 76, 52] : [86, 118, 52];
          trees.push({ kind: conifer ? conifers : crowns, x: wx + dx, z: wz + dz, y: groundY(x, y) - 0.05,
                       s: 0.75 + hash(x, y, 50 + i) * 0.6, turn: hash(x, y, 60 + i) * 6.3,
                       color: srgb(green.map((c) => c * (0.85 + hash(x, y, 70 + i) * 0.3))), tile: `${x},${y}` });
        }
        if (code === "M" && hash(x, y, 80) < 0.45) {
          const { x: wx, z: wz } = at(x, y);
          trees.push({ kind: rocks, x: wx + (hash(x, y, 81) - 0.5) * 0.6, z: wz + (hash(x, y, 82) - 0.5) * 0.6,
                       y: centreHeight(world, x, y) * 0.8, s: 0.8 + hash(x, y, 83), turn: hash(x, y, 84) * 6.3,
                       color: srgb([112, 104, 94].map((c) => c * (0.85 + hash(x, y, 85) * 0.3))), tile: `${x},${y}` });
        }
      }
    }
  }

  // ---------- one frame ----------

  function paintLand() {
    const n = size, out = landColors.array;
    const color = new THREE.Color();
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const owner = frame.territory[y][x];
        let rgb = Array.from(baseRGB.subarray((y * n + x) * 3, (y * n + x) * 3 + 3));
        if (owner >= 0 && world.biome[y][x] !== "S") rgb = mix(rgb, hexRGB(INK[frame.settlements[owner].civ]), TERRITORY_TINT);
        color.setRGB(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, THREE.SRGBColorSpace);
        const start = (y * n + x) * 36;
        for (let v = 0; v < 12; v++) out.set([color.r, color.g, color.b], start + v * 3);
      }
    }
    landColors.needsUpdate = true;
  }

  function drawBorders() {
    disposeOf(borders);
    const n = size, points = [], colors = [];
    const corners = cornerHeights(world);
    const lift = (cx, cy) => Math.max(corners[cy * (n + 1) + cx], WATER_LEVEL) + 0.06;
    const civOf = (x, y) => {
      if (x < 0 || y < 0 || x >= n || y >= n) return null;
      const o = frame.territory[y][x];
      return o < 0 ? null : frame.settlements[o].civ;
    };
    const edge = (civ, ax, ay, bx, by) => {
      const c = srgb(hexRGB(INK[civ]));
      points.push(ax - half, lift(ax, ay), ay - half, bx - half, lift(bx, by), by - half);
      colors.push(c.r, c.g, c.b, c.r, c.g, c.b);
    };
    for (let y = 0; y < n; y++) {
      for (let x = 0; x < n; x++) {
        const civ = civOf(x, y);
        if (!civ) continue;
        if (civOf(x, y - 1) !== civ) edge(civ, x, y, x + 1, y);
        if (civOf(x, y + 1) !== civ) edge(civ, x, y + 1, x + 1, y + 1);
        if (civOf(x - 1, y) !== civ) edge(civ, x, y, x, y + 1);
        if (civOf(x + 1, y) !== civ) edge(civ, x + 1, y, x + 1, y + 1);
      }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    borders = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ vertexColors: true }));
    scene.add(borders);
  }

  function house(x, y, z, s, turn, civ, ruined) {
    const style = STYLE[civ];
    if (ruined) {
      boxes.add(x, y, z, s * 1.1, s * 0.35, s * 0.8, turn, srgb([118, 112, 104]));
      return;
    }
    const walls = srgb(hexRGB(style.walls));
    const h = s * 0.9;
    boxes.add(x, y, z, s * 1.3, h, s, turn, walls);
    roofs.add(x, y + h, z, s * 1.45, Math.max(style.pitch * s * 1.4, 0.03), s * 1.15, turn, srgb(hexRGB(style.roofs)));
  }

  function pennant(x, y, z, civ, tall) {
    boxes.add(x, y, z, 0.04, tall, 0.04, 0, srgb([60, 44, 32]));
    boxes.add(x + 0.16, y + tall - 0.2, z, 0.3, 0.18, 0.02, 0, srgb(hexRGB(INK[civ])));
  }

  function build() {
    for (const parts of [boxes, roofs, cones, conifers, crowns, rocks]) parts.clear();
    const built = new Set(frame.buildings.map((b) => b.tile));
    for (const t of frame.settlements) built.add(t.tile);
    for (const t of trees) if (!built.has(t.tile)) t.kind.add(t.x, t.y, t.z, t.s, t.s, t.s, t.turn, t.color);

    for (const t of frame.settlements) {
      const { x, y } = tileXY(t.tile);
      const { x: wx, z: wz } = at(x, y);
      const gy = groundY(x, y);
      const seed = x * 131 + y;
      for (const spot of seatLayout(t.stage, seed)) {
        house(wx + spot.dx, gy, wz + spot.dz, spot.size, spot.turn, t.civ, false);
      }
      if (t.capital) {
        boxes.add(wx, gy, wz, 0.42, 1.25, 0.42, 0, srgb(hexRGB(STYLE[t.civ].walls)));
        cones.add(wx, gy + 1.25, wz, 0.62, 0.6, 0.62, 0.3, srgb(hexRGB(STYLE[t.civ].roofs)));
        pennant(wx, gy + 1.85, wz, t.civ, 0.6);
      }
    }

    for (const b of frame.buildings) {
      const town = frame.settlements[b.town];
      if (b.tile === town.tile) continue;
      const { x, y } = tileXY(b.tile);
      const { x: wx, z: wz } = at(x, y);
      const gy = groundY(x, y);
      const turn = hash(x, y, 90) * Math.PI;
      if (b.type === "farm" || b.type === "pasture") {
        const crop = b.type === "farm" ? [196, 170, 86] : [120, 150, 70];
        for (let r = 0; r < 4; r++) {
          const shade = r % 2 ? 0.86 : 1;
          boxes.add(wx, gy, wz - 0.33 + r * 0.22, 0.86, 0.04, 0.2, 0, srgb((b.ruin ? [110, 100, 80] : crop).map((c) => c * shade)));
        }
      } else if (b.type === "mine") {
        boxes.add(wx, gy - 0.1, wz, 0.5, 0.32, 0.4, turn, srgb([46, 40, 36]));
        cones.add(wx + 0.3, gy, wz + 0.2, 0.45, 0.28, 0.45, turn, srgb([120, 108, 96]));
      } else if (b.type === "lumber_camp") {
        for (let r = 0; r < 3; r++) boxes.add(wx - 0.15 + r * 0.04, gy + r * 0.09, wz, 0.6, 0.09, 0.12 + r * 0.02, turn, srgb([112, 78, 48]));
        house(wx + 0.25, gy, wz + 0.25, 0.22, turn, town.civ, b.ruin);
      } else if (b.type === "housing") {
        house(wx - 0.18, gy, wz - 0.1, 0.28, turn, town.civ, b.ruin);
        house(wx + 0.2, gy, wz + 0.18, 0.25, turn + 1.2, town.civ, b.ruin);
      } else if (b.type === "stone_fortress" || b.type === "town_walls") {
        boxes.add(wx, gy, wz, 0.5, b.ruin ? 0.4 : 1.0, 0.5, turn, srgb([128, 122, 112]));
      } else {
        house(wx, gy, wz, 0.42, turn, town.civ, b.ruin);   // a hall: library, workshop, market and the rest
      }
    }

    for (const node of frame.nodes) {
      if (node.kind === "forest" || !node.left) continue;
      const { x, y } = tileXY(node.tile);
      const { x: wx, z: wz } = at(x, y);
      const rgb = node.kind === "metal" ? [150, 92, 60] : node.kind === "stone" ? [150, 146, 136] : [170, 120, 160];
      cones.add(wx + 0.3, groundY(x, y), wz - 0.3, 0.3, 0.32, 0.3, 0.6, srgb(rgb));
    }

    for (const [i, u] of frame.units.entries()) {
      const { x, y } = tileXY(u.tile);
      const { x: wx, z: wz } = at(x, y);
      const gy = groundY(x, y), jitter = (i % 3) * 0.18 - 0.18;
      if (u.kind === "caravan") {
        boxes.add(wx + jitter, gy + 0.08, wz, 0.42, 0.22, 0.26, 0.4, srgb([120, 86, 52]));
        pennant(wx + jitter - 0.1, gy + 0.3, wz, u.civ, 0.5);
      } else {
        boxes.add(wx + jitter, gy, wz, 0.14, 0.32, 0.14, 0, srgb([70, 56, 44]));
        pennant(wx + jitter + 0.08, gy, wz, u.civ, 0.75);
      }
    }
    for (const parts of [boxes, roofs, cones, conifers, crowns, rocks]) parts.done();
  }

  function label() {
    const here = new Set();
    for (const t of frame.settlements) {
      here.add(t.id);
      let sign = signs.get(t.id);
      if (!sign) {
        sign = placard(t.name);
        signs.set(t.id, sign);
        scene.add(sign);
      }
      const { x, y } = tileXY(t.tile);
      const { x: wx, z: wz } = at(x, y);
      const step = STAGE_ORDER.indexOf(t.stage);
      sign.position.set(wx, groundY(x, y) + (t.capital ? 2.6 : 1.3) + step * 0.15, wz);
      sign.visible = true;
    }
    for (const [id, sign] of signs) if (!here.has(id)) sign.visible = false;
  }

  function placeRing() {
    const town = selected && frame.settlements.find((t) => t.id === selected);
    ring.visible = Boolean(town);
    if (!town) return;
    const { x, y } = tileXY(town.tile);
    const { x: wx, z: wz } = at(x, y);
    ring.position.set(wx, groundY(x, y) + 0.08, wz);
    const r = 0.9 + STAGE_ORDER.indexOf(town.stage) * 0.4;
    ring.scale.set(r, r, 1);
  }

  function pulse(town) {
    const { x, y } = tileXY(town.tile);
    const { x: wx, z: wz } = at(x, y);
    const mesh = new THREE.Mesh(new THREE.RingGeometry(0.8, 1, 40),
                                new THREE.MeshBasicMaterial({ color: INK[town.civ], transparent: true, side: THREE.DoubleSide }));
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(wx, groundY(x, y) + 0.1, wz);
    scene.add(mesh);
    pulses.push({ mesh, start: performance.now() });
  }

  // ---------- camera, light and the render loop ----------

  function frameCamera() {
    // The block fills the view with its front edge and strata showing, seen from the table's edge.
    camera.position.set(0, size * 0.95, size * 1.24);
    controls.target.set(0, -4, size * 0.13);
    controls.update();
    sun.position.set(-size * 0.6, size * 1.1, size * 0.35);
    const reach = size * 0.75;
    Object.assign(sun.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, near: 1, far: size * 4 });
    sun.shadow.camera.updateProjectionMatrix();
  }

  function resize() {
    const { clientWidth: w, clientHeight: h } = container;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    requestRender();
  }

  function loop(now) {
    if (pulses.length) {
      pulses = pulses.filter((p) => {
        const k = (now - p.start) / PULSE_MS;
        if (k >= 1) { disposeOf(p.mesh); return false; }
        const r = 1 + k * 4;
        p.mesh.scale.set(r, r, 1);
        p.mesh.material.opacity = 1 - k;
        return true;
      });
      wanted = true;
    }
    if (wanted) {
      wanted = false;
      renderer.render(scene, camera);
    }
    requestAnimationFrame(loop);
  }

  controls.addEventListener("change", () => {
    if (world) {   // keep the view over the block
      controls.target.x = Math.max(-half, Math.min(half, controls.target.x));
      controls.target.z = Math.max(-half, Math.min(half, controls.target.z));
    }
    requestRender();
  });
  new ResizeObserver(resize).observe(container);

  // ---------- pointing at the land ----------

  const ray = new THREE.Raycaster(), pointer = new THREE.Vector2(), plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -0.3);
  function tileUnder(event) {
    if (!world) return null;
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const hit = ray.ray.intersectPlane(plane, new THREE.Vector3());
    if (!hit) return null;
    const x = Math.floor(hit.x + half), y = Math.floor(hit.z + half);
    return x >= 0 && y >= 0 && x < size && y < size ? { x, y } : null;
  }

  let down = null;
  renderer.domElement.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY }; });
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) onPick(tileUnder(e));
    down = null;
  });
  renderer.domElement.addEventListener("pointermove", (e) => onHover(tileUnder(e)));
  renderer.domElement.addEventListener("pointerleave", () => onHover(null));

  resize();
  requestAnimationFrame(loop);

  return {
    load(nextWorld) {
      for (const mesh of [land, walls, water, borders]) disposeOf(mesh);
      for (const sign of signs.values()) { scene.remove(sign); sign.material.map.dispose(); sign.material.dispose(); }
      signs.clear();
      borders = null;
      world = nextWorld;
      size = world.size;
      half = size / 2;
      carve();
      frameCamera();
      requestRender();
    },
    show(next, before, animate) {
      frame = next;
      paintLand();
      drawBorders();
      build();
      label();
      placeRing();
      if (animate && before && next.tick > before.tick) {
        const was = new Map(before.settlements.map((t) => [t.id, t.stage]));
        for (const t of next.settlements) {
          if (was.has(t.id) && STAGE_ORDER.indexOf(t.stage) > STAGE_ORDER.indexOf(was.get(t.id))) pulse(t);
        }
      }
      requestRender();
    },
    select(id) {
      selected = id;
      if (frame) placeRing();
      requestRender();
    },
    resetView() {
      if (world) frameCamera();
      requestRender();
    },
  };
}
