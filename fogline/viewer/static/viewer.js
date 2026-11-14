"use strict";

// The read-only viewer. The world is drawn in 3D by scene.js; where WebGL isn't available, the
// map below is painted top-down instead. Every piece of text from the run goes in with
// textContent. Nothing here uses Math.random: every wobble comes from a hash of the tile, so a
// frame always looks the same.

const TILE = 24;                // canvas pixels per map tile
const PLAY_MS = 250;            // four snapshots a second
const PULSE_MS = 700;

const BIOME = {
  S: { name: "sea", rgb: [44, 79, 102] },
  C: { name: "coast", rgb: [185, 180, 126] },
  P: { name: "plains", rgb: [159, 174, 106] },
  F: { name: "forest", rgb: [86, 112, 63] },
  D: { name: "desert", rgb: [210, 176, 119] },
  T: { name: "tundra", rgb: [214, 220, 216] },
  M: { name: "mountains", rgb: [138, 127, 112] },
};
const SHALLOW = [79, 138, 154];
const BEACH = [216, 203, 152];

const INK = {
  ironhold: "#c0412b",
  dunerunners: "#e0a030",
  saltreach: "#1f9e9a",
  frostmark: "#4a7fd0",
  verdance: "#b8de4c",
};

// How each culture builds: roof shape, roof colour, wall colour.
const STYLE = {
  ironhold: { roof: "gable", roofs: "#7d3326", walls: "#9a948a" },
  dunerunners: { roof: "flat", roofs: "#c98f3a", walls: "#e6cf9f" },
  saltreach: { roof: "gable", roofs: "#2d7f86", walls: "#ece6d8" },
  frostmark: { roof: "steep", roofs: "#35558c", walls: "#8a6a4c" },
  verdance: { roof: "thatch", roofs: "#c8a84e", walls: "#d8c7a0" },
};

const STAGE_ORDER = ["hamlet", "village", "town", "city"];
const GROUND_RADIUS = { hamlet: 1.0, village: 1.7, town: 2.6, city: 3.5 };
const FLAT = new Set(["farm", "pasture"]);
const LABEL = {
  lumber_camp: "lumber camp", town_walls: "town walls", stone_fortress: "stone fortress",
  printing_house: "printing house",
};

const $ = (id) => document.getElementById(id);
const canvas = $("map");
const ctx = canvas.getContext("2d");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

let run = null;          // { manifest, world, frames }
let terrain = null;      // offscreen canvas of the fixed map
let at = 0;              // frame index
let timer = null;
let pulses = [];         // { x, y, ink, start }
let selected = null;     // settlement id
let animating = false;   // a pulse redraw is already queued
let loading = 0;         // counts loads, so a slower earlier one can't win
let runName = "";
let asking = 0;          // counts turn requests, for the same reason
let diorama = null;      // the 3D scene, or null when the flat map is drawn instead
let following = null;    // the timer that checks a run still being played for new frames
let catching = false;    // a check is already on its way
const FOLLOW_MS = 10000;

// ---------- small helpers ----------

function tileXY(key) {
  const [x, y] = key.split(",").map(Number);
  return { x, y };
}

function hash(x, y, salt) {
  let h = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(salt | 0, 2246822519)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function noise(x, y, salt) {
  // Smooth value noise on a unit lattice.
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const fx = x - x0, fy = y - y0;
  const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
  const a = hash(x0, y0, salt), b = hash(x0 + 1, y0, salt);
  const c = hash(x0, y0 + 1, salt), d = hash(x0 + 1, y0 + 1, salt);
  return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy;
}

function shade(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const f = (c) => Math.max(0, Math.min(255, Math.round(c + amount * 255)));
  return `rgb(${f(n >> 16)},${f((n >> 8) & 255)},${f(n & 255)})`;
}

function alpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function nice(word) {
  return LABEL[word] || word.replace(/_/g, " ");
}

function setText(el, text) {
  el.textContent = text;
}

function civName(id) {
  const civ = run.world.civs.find((c) => c.id === id);
  return civ ? civ.name : id;
}

function centreOf(x, y) {
  return [x * TILE + TILE / 2, y * TILE + TILE / 2];
}

function poly(g, points, fill) {
  g.beginPath();
  g.moveTo(points[0], points[1]);
  for (let i = 2; i < points.length; i += 2) g.lineTo(points[i], points[i + 1]);
  g.closePath();
  g.fillStyle = fill;
  g.fill();
}

function disc(g, x, y, r, fill) {
  g.beginPath();
  g.arc(x, y, r, 0, Math.PI * 2);
  g.fillStyle = fill;
  g.fill();
}

// ---------- terrain (painted once per run) ----------

function drawTerrain(world) {
  const size = world.size;
  const px = size * TILE;
  const off = document.createElement("canvas");
  off.width = off.height = px;
  const g = off.getContext("2d");
  const code = (x, y) => world.biome[Math.max(0, Math.min(size - 1, Math.floor(y)))][Math.max(0, Math.min(size - 1, Math.floor(x)))];

  // Ground: each pixel looks up its biome through a warped position, so edges wander like
  // real coastlines, then gets broad light and dark patches and a fine grain.
  const image = g.createImageData(px, px);
  const data = image.data;
  for (let py = 0; py < px; py++) {
    const v = (py + 0.5) / TILE;
    for (let pxx = 0; pxx < px; pxx++) {
      const u = (pxx + 0.5) / TILE;
      const wx = u + (noise(u * 0.8, v * 0.8, 11) - 0.5) * 0.9 + (noise(u * 2.6, v * 2.6, 12) - 0.5) * 0.35;
      const wy = v + (noise(u * 0.8, v * 0.8, 13) - 0.5) * 0.9 + (noise(u * 2.6, v * 2.6, 14) - 0.5) * 0.35;
      const here = code(wx, wy);
      let rgb = BIOME[here] ? BIOME[here].rgb : BIOME.P.rgb;
      const sea = here === "S";
      let shoreMix = 0;
      for (const [dx, dy] of [[0.32, 0], [-0.32, 0], [0, 0.32], [0, -0.32]]) {
        if ((code(wx + dx, wy + dy) === "S") !== sea) shoreMix++;
      }
      if (shoreMix) rgb = sea ? SHALLOW : BEACH;
      const broad = noise(u * 0.3, v * 0.3, 20) - 0.5;
      const mid = noise(u * 1.4, v * 1.4, 21) - 0.5;
      const grain = hash(pxx, py, 22) - 0.5;
      let light = 1 + broad * 0.16 + mid * 0.1 + grain * 0.05;
      if (sea && !shoreMix) light += (noise(u * 0.5, v * 0.5, 23) - 0.5) * 0.12;
      const i = (py * px + pxx) * 4;
      data[i] = Math.min(255, rgb[0] * light);
      data[i + 1] = Math.min(255, rgb[1] * light);
      data[i + 2] = Math.min(255, rgb[2] * light);
      data[i + 3] = 255;
    }
  }
  g.putImageData(image, 0, 0);

  drawRivers(g, world);

  // Features, painted back to front so nearer ones overlap farther ones.
  const marks = [];
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const c = world.biome[y][x];
      const nearSnow = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => code(x + dx, y + dy) === "T");
      if (c === "F") {
        const n = 3 + Math.floor(hash(x, y, 30) * 3);
        for (let k = 0; k < n; k++) {
          marks.push({ y: y + hash(x, y, 31 + k), draw: () => tree(g, x, y, k, nearSnow) });
        }
      } else if (c === "M") {
        marks.push({ y: y + 0.6, draw: () => peak(g, x, y, nearSnow) });
      } else if (c === "S" && hash(x, y, 40) < 0.22) {
        marks.push({ y, draw: () => wave(g, x, y) });
      } else if (c === "D" && hash(x, y, 41) < 0.45) {
        marks.push({ y, draw: () => dune(g, x, y) });
      } else if ((c === "P" || c === "C") && hash(x, y, 42) < 0.35) {
        marks.push({ y, draw: () => tuft(g, x, y, c) });
      } else if (c === "T" && hash(x, y, 43) < 0.25) {
        marks.push({ y, draw: () => rock(g, x, y) });
      }
    }
  }
  marks.sort((a, b) => a.y - b.y).forEach((m) => m.draw());
  return off;
}

function drawRivers(g, world) {
  const size = world.size;
  const isRiver = (x, y) => x >= 0 && y >= 0 && x < size && y < size && world.river[y][x] === "1";
  const point = (x, y) => [
    x * TILE + TILE / 2 + (hash(x, y, 50) - 0.5) * TILE * 0.4,
    y * TILE + TILE / 2 + (hash(x, y, 51) - 0.5) * TILE * 0.4,
  ];
  const links = [];
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (!isRiver(x, y)) continue;
      for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
        const diagonal = dx !== 0 && dy !== 0;
        if (diagonal && (isRiver(x + dx, y) || isRiver(x, y + dy))) continue;
        if (isRiver(x + dx, y + dy)) links.push([point(x, y), point(x + dx, y + dy)]);
      }
    }
  }
  g.lineCap = "round";
  g.lineJoin = "round";
  for (const [width, colour] of [[TILE * 0.42, "rgba(170,200,210,0.45)"], [TILE * 0.24, "#3d7ba2"]]) {
    g.lineWidth = width;
    g.strokeStyle = colour;
    for (const [[ax, ay], [bx, by]] of links) {
      const mx = (ax + bx) / 2 + (hash(ax | 0, ay | 0, 52) - 0.5) * TILE * 0.3;
      const my = (ay + by) / 2 + (hash(bx | 0, by | 0, 53) - 0.5) * TILE * 0.3;
      g.beginPath();
      g.moveTo(ax, ay);
      g.quadraticCurveTo(mx, my, bx, by);
      g.stroke();
    }
  }
}

function tree(g, x, y, k, conifer) {
  const tx = x * TILE + 3 + hash(x, y, 33 + k) * (TILE - 6);
  const ty = y * TILE + 4 + hash(x, y, 31 + k) * (TILE - 6);
  const r = TILE * (0.16 + hash(x, y, 36 + k) * 0.08);
  g.save();
  g.globalAlpha = 0.28;
  g.beginPath();
  g.ellipse(tx + r * 0.5, ty + r * 0.7, r, r * 0.55, 0, 0, Math.PI * 2);
  g.fillStyle = "#16220f";
  g.fill();
  g.restore();
  if (conifer) {
    poly(g, [tx, ty - r * 1.6, tx + r, ty + r * 0.6, tx - r, ty + r * 0.6], "#2c4a2e");
    poly(g, [tx, ty - r * 1.6, tx + r * 0.4, ty - r * 0.8, tx - r * 0.4, ty - r * 0.8], "#e9eeee");
    return;
  }
  const tone = 0.85 + hash(x, y, 38 + k) * 0.3;
  disc(g, tx, ty, r, `rgb(${50 * tone | 0},${82 * tone | 0},${40 * tone | 0})`);
  disc(g, tx - r * 0.3, ty - r * 0.35, r * 0.5, `rgba(150,180,100,0.35)`);
}

function peak(g, x, y, snowy) {
  const cx = x * TILE + TILE / 2 + (hash(x, y, 44) - 0.5) * TILE * 0.3;
  const base = y * TILE + TILE * 0.85;
  const w = TILE * (0.6 + hash(x, y, 45) * 0.35);
  const h = TILE * (0.7 + hash(x, y, 46) * 0.5);
  const top = base - h;
  poly(g, [cx - w, base, cx, top, cx + w * 0.15, base], "#b1a796");
  poly(g, [cx + w * 0.15, base, cx, top, cx + w, base], "#655b4f");
  if (snowy || hash(x, y, 47) < 0.4) {
    const s = 0.32;
    poly(g, [cx - w * s, top + h * s, cx, top, cx + w * s, top + h * s, cx + w * 0.05, top + h * s * 0.7], "#f1f1ec");
  }
}

function wave(g, x, y) {
  const wx = x * TILE + 4 + hash(x, y, 48) * (TILE - 12), wy = y * TILE + TILE / 2;
  g.strokeStyle = "rgba(200,225,235,0.35)";
  g.lineWidth = 1.5;
  g.beginPath();
  g.moveTo(wx, wy);
  g.quadraticCurveTo(wx + 4, wy - 3, wx + 8, wy);
  g.stroke();
}

function dune(g, x, y) {
  const dx = x * TILE + 3 + hash(x, y, 49) * 8, dy = y * TILE + 8 + hash(x, y, 54) * 10;
  g.strokeStyle = "rgba(120,85,40,0.35)";
  g.lineWidth = 1.5;
  g.beginPath();
  g.moveTo(dx, dy);
  g.quadraticCurveTo(dx + 6, dy - 5, dx + 13, dy);
  g.stroke();
}

function tuft(g, x, y, c) {
  const tx = x * TILE + 4 + hash(x, y, 55) * (TILE - 8), ty = y * TILE + 6 + hash(x, y, 56) * (TILE - 10);
  g.strokeStyle = c === "C" ? "rgba(110,110,70,0.5)" : "rgba(80,100,45,0.55)";
  g.lineWidth = 1.2;
  g.beginPath();
  for (const d of [-2.5, 0, 2.5]) {
    g.moveTo(tx, ty + 3);
    g.lineTo(tx + d, ty - 2);
  }
  g.stroke();
}

function rock(g, x, y) {
  const rx = x * TILE + 5 + hash(x, y, 57) * (TILE - 10), ry = y * TILE + 6 + hash(x, y, 58) * (TILE - 10);
  disc(g, rx, ry, 2.5, "#9aa09c");
  disc(g, rx - 0.8, ry - 0.8, 1.2, "#c4c9c6");
}

// ---------- territory ----------

function drawTerritory(frame, size) {
  const towns = frame.settlements;
  // Soft wash: one pixel per tile, scaled up with smoothing so edges fade.
  const wash = document.createElement("canvas");
  wash.width = wash.height = size;
  const w = wash.getContext("2d");
  const img = w.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const o = frame.territory[y][x];
      if (o < 0) continue;
      const n = parseInt(INK[towns[o].civ].slice(1), 16);
      const i = (y * size + x) * 4;
      img.data[i] = n >> 16;
      img.data[i + 1] = (n >> 8) & 255;
      img.data[i + 2] = n & 255;
      img.data[i + 3] = 62;
    }
  }
  w.putImageData(img, 0, 0);
  ctx.save();
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(wash, 0, 0, size * TILE, size * TILE);
  ctx.restore();

  // Borders: marching squares over each civ's tiles, which cuts the stair steps into
  // diagonals so the line reads as a drawn frontier.
  const civs = [...new Set(towns.map((t) => t.civ))];
  for (const civ of civs) {
    const inside = (x, y) => x >= 0 && y >= 0 && x < size && y < size
      && frame.territory[y][x] >= 0 && towns[frame.territory[y][x]].civ === civ;
    const segs = [];
    for (let y = -1; y < size; y++) {
      for (let x = -1; x < size; x++) {
        const a = inside(x, y), b = inside(x + 1, y), c = inside(x + 1, y + 1), d = inside(x, y + 1);
        const k = (a ? 8 : 0) | (b ? 4 : 0) | (c ? 2 : 0) | (d ? 1 : 0);
        if (k === 0 || k === 15) continue;
        const top = [x + 0.5, y], right = [x + 1, y + 0.5], bottom = [x + 0.5, y + 1], left = [x, y + 0.5];
        const table = {
          1: [[left, bottom]], 2: [[bottom, right]], 3: [[left, right]], 4: [[top, right]],
          5: [[top, left], [bottom, right]], 6: [[top, bottom]], 7: [[top, left]], 8: [[top, left]],
          9: [[top, bottom]], 10: [[top, right], [left, bottom]], 11: [[top, right]], 12: [[left, right]],
          13: [[bottom, right]], 14: [[left, bottom]],
        };
        for (const s of table[k]) segs.push(s);
      }
    }
    const toPx = ([gx, gy]) => [gx * TILE + TILE / 2, gy * TILE + TILE / 2];
    ctx.lineCap = "round";
    for (const [width, colour] of [[TILE * 0.32, "rgba(20,25,28,0.35)"], [TILE * 0.13, INK[civ]]]) {
      ctx.lineWidth = width;
      ctx.strokeStyle = colour;
      ctx.beginPath();
      for (const [p, q] of segs) {
        const [ax, ay] = toPx(p), [bx, by] = toPx(q);
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
      }
      ctx.stroke();
    }
  }
}

// ---------- towns ----------

function ground(t) {
  // Trodden earth under a settlement, larger as it grows.
  const [cx, cy] = centreOf(tileXY(t.tile).x, tileXY(t.tile).y);
  const r = GROUND_RADIUS[t.stage] * TILE;
  const grad = ctx.createRadialGradient(cx, cy, r * 0.2, cx, cy, r);
  grad.addColorStop(0, "rgba(176,150,108,0.55)");
  grad.addColorStop(1, "rgba(176,150,108,0)");
  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fill();
}

function paths(t, buildings) {
  // Lanes: grow out from the seat, joining each building to the nearest place already joined
  // (a minimum spanning tree), so the lanes branch like streets instead of fanning out.
  const points = [tileXY(t.tile), ...buildings.map((b) => tileXY(b.tile))];
  const n = points.length;
  const joined = new Array(n).fill(false);
  const best = new Array(n).fill(Infinity);
  const from = new Array(n).fill(0);
  best[0] = 0;
  ctx.strokeStyle = "rgba(122,98,66,0.55)";
  ctx.lineWidth = TILE * 0.14;
  ctx.lineCap = "round";
  ctx.beginPath();
  for (let step = 0; step < n; step++) {
    let pick = -1;
    for (let i = 0; i < n; i++) if (!joined[i] && (pick < 0 || best[i] < best[pick])) pick = i;
    joined[pick] = true;
    if (pick > 0) {
      const [ax, ay] = centreOf(points[from[pick]].x, points[from[pick]].y);
      const [bx, by] = centreOf(points[pick].x, points[pick].y);
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
    }
    for (let i = 0; i < n; i++) {
      if (joined[i]) continue;
      const d = (points[i].x - points[pick].x) ** 2 + (points[i].y - points[pick].y) ** 2;
      if (d < best[i]) { best[i] = d; from[i] = pick; }
    }
  }
  ctx.stroke();
}

function field(b, civ) {
  const { x, y } = tileXY(b.tile);
  const px = x * TILE, py = y * TILE;
  const g = ctx;
  const inset = 2;
  g.save();
  g.beginPath();
  g.roundRect(px + inset, py + inset, TILE - inset * 2, TILE - inset * 2, 3);
  g.clip();
  if (b.type === "farm") {
    const ripe = hash(x, y, 61) < 0.5;
    g.fillStyle = b.ruin ? "#8d8a6e" : ripe ? "#d8be62" : "#a9c25c";
    g.fillRect(px, py, TILE, TILE);
    g.strokeStyle = b.ruin ? "rgba(60,60,50,0.4)" : "rgba(110,90,30,0.45)";
    g.lineWidth = 1.2;
    const across = hash(x, y, 62) < 0.5;
    g.beginPath();
    for (let i = 3; i < TILE; i += 4) {
      if (across) { g.moveTo(px, py + i); g.lineTo(px + TILE, py + i); } else { g.moveTo(px + i, py); g.lineTo(px + i, py + TILE); }
    }
    g.stroke();
  } else {
    g.fillStyle = b.ruin ? "#8d917a" : "#9cc56a";
    g.fillRect(px, py, TILE, TILE);
    if (!b.ruin) {
      for (let k = 0; k < 3; k++) {
        disc(g, px + 5 + hash(x, y, 63 + k) * (TILE - 10), py + 5 + hash(x, y, 66 + k) * (TILE - 10), 1.8, "#f4f2ea");
      }
    }
  }
  g.restore();
  g.strokeStyle = b.ruin ? "#6e6a60" : shade(INK[civ], -0.25);
  g.lineWidth = 1.2;
  g.setLineDash([2, 2]);
  g.strokeRect(px + inset, py + inset, TILE - inset * 2, TILE - inset * 2);
  g.setLineDash([]);
}

function shadow(x, y, w, h) {
  ctx.save();
  ctx.globalAlpha = 0.3;
  ctx.beginPath();
  ctx.ellipse(x + 2, y + 2, w, h, 0, 0, Math.PI * 2);
  ctx.fillStyle = "#1b1712";
  ctx.fill();
  ctx.restore();
}

function house(cx, cy, w, h, style, ruined) {
  // A house seen from above and a little south: wall front, roof over it.
  const walls = ruined ? "#8a857c" : style.walls;
  const roofs = ruined ? "#5d5953" : style.roofs;
  shadow(cx, cy + h * 0.4, w * 0.6, h * 0.35);
  ctx.fillStyle = shade(walls, -0.12);
  ctx.fillRect(cx - w / 2, cy, w, h * 0.45);
  if (ruined) {
    ctx.strokeStyle = "#3d3a36";
    ctx.lineWidth = 1;
    ctx.strokeRect(cx - w / 2, cy - h * 0.4, w, h * 0.85);
    return;
  }
  if (style.roof === "flat") {
    ctx.fillStyle = walls;
    ctx.fillRect(cx - w / 2, cy - h * 0.45, w, h * 0.5);
    ctx.fillStyle = roofs;
    ctx.fillRect(cx - w / 2 + 1, cy - h * 0.45 + 1, w - 2, 2);
    disc(ctx, cx + w * 0.2, cy - h * 0.2, w * 0.16, shade(walls, 0.06));
  } else if (style.roof === "thatch") {
    ctx.beginPath();
    ctx.ellipse(cx, cy - h * 0.1, w * 0.62, h * 0.42, 0, Math.PI, 0);
    ctx.lineTo(cx + w * 0.62, cy + 1);
    ctx.lineTo(cx - w * 0.62, cy + 1);
    ctx.fillStyle = roofs;
    ctx.fill();
    ctx.strokeStyle = shade(roofs, -0.18);
    ctx.lineWidth = 1;
    ctx.stroke();
  } else {
    const peakUp = style.roof === "steep" ? h * 0.75 : h * 0.5;
    poly(ctx, [cx - w * 0.6, cy + 1, cx, cy - peakUp, cx + w * 0.6, cy + 1], roofs);
    poly(ctx, [cx, cy - peakUp, cx + w * 0.6, cy + 1, cx + w * 0.1, cy + 1], shade(roofs, -0.12));
    if (style.roof === "steep") poly(ctx, [cx - w * 0.18, cy - peakUp * 0.62, cx, cy - peakUp, cx + w * 0.18, cy - peakUp * 0.62], "#eef2f2");
  }
  ctx.fillStyle = "#3a2c22";
  ctx.fillRect(cx - 1, cy + h * 0.15, 2.4, h * 0.3);
}

function building(b, civ) {
  const { x, y } = tileXY(b.tile);
  const [cx, cy] = centreOf(x, y);
  const style = STYLE[civ] || STYLE.ironhold;
  const ink = INK[civ];
  const r = b.ruin;
  switch (b.type) {
    case "housing": {
      const two = hash(x, y, 70) < 0.55;
      if (two) {
        house(cx - 5, cy - 4, 10, 10, style, r);
        house(cx + 5, cy + 3, 10, 10, style, r);
      } else {
        house(cx, cy, 13, 12, style, r);
      }
      break;
    }
    case "lumber_camp":
      shadow(cx, cy + 4, 9, 4);
      for (const [dx, dy] of [[-4, 3], [0, 3], [4, 3], [-2, 0], [2, 0]]) {
        disc(ctx, cx + dx, cy + dy, 2.4, r ? "#76706a" : "#8a5d36");
        disc(ctx, cx + dx, cy + dy, 1.1, r ? "#9a948c" : "#d2a774");
      }
      house(cx + 4, cy - 6, 8, 7, style, r);
      break;
    case "mine":
      shadow(cx, cy + 4, 10, 5);
      poly(ctx, [cx - 10, cy + 6, cx - 2, cy - 7, cx + 9, cy + 6], r ? "#7d776e" : "#857a6a");
      poly(ctx, [cx - 2, cy - 7, cx + 9, cy + 6, cx + 2, cy + 6], "#5c5247");
      ctx.fillStyle = "#16120e";
      ctx.fillRect(cx - 3, cy, 5, 6);
      ctx.strokeStyle = r ? "#6a655d" : "#a07a4c";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(cx - 3.5, cy - 0.5, 6, 6.5);
      break;
    case "workshop":
    case "sawmill":
      house(cx - 1, cy + 1, 16, 12, style, r);
      if (!r) {
        ctx.fillStyle = "#5b524a";
        ctx.fillRect(cx + 4, cy - 9, 3, 6);
        disc(ctx, cx + 6, cy - 12, 2.5, "rgba(220,220,215,0.6)");
        disc(ctx, cx + 8, cy - 15, 3.2, "rgba(220,220,215,0.4)");
        if (b.type === "sawmill") {
          ctx.strokeStyle = "#cfd3d6";
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(cx - 7, cy + 5, 3.5, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
      break;
    case "granary":
      shadow(cx, cy + 5, 7, 4);
      ctx.fillStyle = r ? "#8a857c" : "#d9c9a3";
      ctx.fillRect(cx - 6, cy - 2, 12, 9);
      poly(ctx, [cx - 7.5, cy - 1, cx, cy - 10, cx + 7.5, cy - 1], r ? "#5d5953" : style.roofs);
      break;
    case "library":
    case "printing_house":
      shadow(cx, cy + 6, 11, 4);
      ctx.fillStyle = r ? "#8a857c" : "#e4ddcc";
      ctx.fillRect(cx - 10, cy - 3, 20, 10);
      if (!r) {
        ctx.fillStyle = "#b9b09c";
        for (const dx of [-7, -3, 1, 5]) ctx.fillRect(cx + dx, cy - 2, 2, 8);
        poly(ctx, [cx - 12, cy - 3, cx, cy - 10, cx + 12, cy - 3], style.roofs);
        if (b.type === "printing_house") disc(ctx, cx, cy - 6, 2, "#f4f2ea");
      }
      break;
    case "market":
      for (let k = 0; k < 3; k++) {
        const mx = cx - 7 + k * 7, my = cy - 2 + (k % 2) * 4;
        shadow(mx, my + 4, 4, 2);
        for (let s = 0; s < 3; s++) {
          ctx.fillStyle = r ? "#76706a" : s % 2 ? "#f4f2ea" : ink;
          ctx.fillRect(mx - 3 + s * 2, my - 2, 2, 4);
        }
      }
      break;
    case "barracks":
      house(cx, cy + 2, 18, 11, style, r);
      if (!r) {
        ctx.strokeStyle = "#3a2c22";
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        ctx.moveTo(cx + 8, cy + 2);
        ctx.lineTo(cx + 8, cy - 12);
        ctx.stroke();
        poly(ctx, [cx + 8, cy - 12, cx + 15, cy - 9.5, cx + 8, cy - 7], ink);
      }
      break;
    case "town_walls":
    case "stone_fortress": {
      const big = b.type === "stone_fortress";
      const s = big ? 9 : 6;
      shadow(cx, cy + s, s + 2, 4);
      ctx.fillStyle = r ? "#77736c" : "#a59d8f";
      ctx.fillRect(cx - s, cy - s, s * 2, s * 2);
      ctx.fillStyle = r ? "#5f5b55" : "#7d7568";
      ctx.fillRect(cx - s, cy + s * 0.4, s * 2, s * 0.6);
      if (!r) {
        ctx.fillStyle = "#c2baa9";
        for (let k = -s; k < s; k += 4) ctx.fillRect(cx + k, cy - s - 2, 2.5, 2.5);
        if (big) poly(ctx, [cx - 2, cy - s - 2, cx + 6, cy - s - 6, cx - 2, cy - s - 9], ink);
      }
      break;
    }
    case "harbour":
      ctx.fillStyle = r ? "#6f655a" : "#8a6a44";
      ctx.fillRect(cx - 2, cy - 11, 4, 22);
      ctx.fillRect(cx - 9, cy + 4, 18, 3);
      if (!r) {
        poly(ctx, [cx + 5, cy - 6, cx + 12, cy - 6, cx + 10, cy - 2, cx + 7, cy - 2], "#6b4b2c");
        poly(ctx, [cx + 8.5, cy - 15, cx + 8.5, cy - 7, cx + 13, cy - 7], "#f4f2ea");
      }
      break;
    default:
      house(cx, cy, 12, 11, style, r);
  }
}

function seat(t) {
  // The hall at the heart of a settlement: a bigger building that gains a tower, then a
  // spire, as the place grows.
  const { x, y } = tileXY(t.tile);
  const [cx, cy] = centreOf(x, y);
  const style = STYLE[t.civ] || STYLE.ironhold;
  const ink = INK[t.civ];
  const step = STAGE_ORDER.indexOf(t.stage);
  const w = 15 + step * 3;
  if (step >= 2) {
    // A plaza of stone around the hall.
    disc(ctx, cx, cy + 2, TILE * (0.55 + step * 0.08), "rgba(200,190,170,0.85)");
    ctx.strokeStyle = "rgba(120,110,95,0.6)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  house(cx, cy + 2, w, w * 0.8, style, false);
  if (step >= 1) {
    const tx = cx + w * 0.45;
    shadow(tx, cy + 4, 4, 2);
    ctx.fillStyle = shade(style.walls, -0.05);
    ctx.fillRect(tx - 3, cy - 8 - step * 2, 6, 12 + step * 2);
    poly(ctx, [tx - 4.5, cy - 8 - step * 2, tx, cy - 16 - step * 4, tx + 4.5, cy - 8 - step * 2], style.roofs);
  }
  // A pennant in the civ's colour, so every seat reads at a glance.
  const fx = cx - w * 0.35, top = cy - w * 0.55 - step * 3;
  ctx.strokeStyle = "#2a211a";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(fx, cy - 2);
  ctx.lineTo(fx, top);
  ctx.stroke();
  poly(ctx, [fx, top, fx + 8, top + 2.5, fx, top + 5], ink);
}

function nodeMark(node) {
  if (node.kind === "forest") return;   // the trees already show it
  const { x, y } = tileXY(node.tile);
  const [cx, cy] = centreOf(x, y);
  const spent = node.left === 0;
  const colour = { stone: "#d8d2c4", metal: "#b0663a", luxury: "#f0c75e" }[node.kind] || "#ffffff";
  for (const [dx, dy, r] of [[-4, 4, 3], [2, 5, 2.5], [-1, 1, 2.2]]) {
    disc(ctx, cx + dx, cy + dy, r, spent ? "rgba(120,115,105,0.6)" : shade(colour, -0.25));
    if (!spent) disc(ctx, cx + dx - 0.7, cy + dy - 0.7, r * 0.55, colour);
  }
  if (node.kind === "luxury" && !spent) {
    ctx.strokeStyle = "#fff6d0";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx + 5, cy - 6); ctx.lineTo(cx + 5, cy);
    ctx.moveTo(cx + 2, cy - 3); ctx.lineTo(cx + 8, cy - 3);
    ctx.stroke();
  }
}

function unitMark(u) {
  const { x, y } = tileXY(u.tile);
  const cx = x * TILE + 6, cy = y * TILE + TILE - 6;
  shadow(cx, cy + 4, 3.5, 1.8);
  disc(ctx, cx, cy - 3, 2.3, "#e8d2b4");
  ctx.fillStyle = INK[u.civ];
  ctx.beginPath();
  ctx.moveTo(cx - 3.5, cy + 4);
  ctx.lineTo(cx, cy - 1);
  ctx.lineTo(cx + 3.5, cy + 4);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = "rgba(20,20,20,0.6)";
  ctx.lineWidth = 0.8;
  ctx.stroke();
}

// ---------- one frame ----------

function draw() {
  if (!run) return;
  const frame = run.frames[at];
  const size = run.world.size;
  const towns = frame.settlements;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(terrain, 0, 0);
  drawTerritory(frame, size);

  const byTown = towns.map(() => []);
  for (const b of frame.buildings) byTown[b.town].push(b);
  towns.forEach((t) => ground(t));
  towns.forEach((t, i) => paths(t, byTown[i].filter((b) => b.tile !== t.tile)));
  for (const b of frame.buildings) if (FLAT.has(b.type)) field(b, towns[b.town].civ);
  for (const node of frame.nodes) nodeMark(node);

  // Standing things, back to front.
  const seats = new Set(towns.map((t) => t.tile));
  const standing = [];
  for (const b of frame.buildings) {
    if (FLAT.has(b.type) || seats.has(b.tile)) continue;
    standing.push({ y: tileXY(b.tile).y, draw: () => building(b, towns[b.town].civ) });
  }
  for (const t of towns) standing.push({ y: tileXY(t.tile).y + 0.1, draw: () => seat(t) });
  for (const u of frame.units) standing.push({ y: tileXY(u.tile).y + 0.2, draw: () => unitMark(u) });
  standing.sort((a, b) => a.y - b.y).forEach((s) => s.draw());

  // Names last, so they sit on top.
  const serif = getComputedStyle(document.body).getPropertyValue("--serif");
  ctx.textBaseline = "middle";
  ctx.lineJoin = "round";
  for (const t of towns) {
    const { x, y } = tileXY(t.tile);
    const step = STAGE_ORDER.indexOf(t.stage);
    ctx.font = `${step >= 2 ? "600 26px" : step === 1 ? "600 22px" : "500 19px"} ${serif}`;
    const tx = x * TILE + TILE + 6 + step * 3, ty = y * TILE + TILE / 2;
    ctx.lineWidth = 5;
    ctx.strokeStyle = "rgba(23,32,37,0.8)";
    ctx.strokeText(t.name, tx, ty);
    ctx.fillStyle = t.id === selected ? "#f0c75e" : "#f4f0e4";
    ctx.fillText(t.name, tx, ty);
  }

  drawPulses(performance.now());
}

function drawPulses(now) {
  pulses = pulses.filter((p) => now - p.start < PULSE_MS);
  for (const p of pulses) {
    const k = (now - p.start) / PULSE_MS;
    ctx.strokeStyle = alpha(p.ink, 1 - k);
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 16 + k * 52, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (pulses.length && !animating) {
    animating = true;
    requestAnimationFrame(() => { animating = false; draw(); });
  }
}

// ---------- panels ----------

function renderCivs() {
  const frame = run.frames[at];
  const list = $("civs");
  list.replaceChildren();
  for (const civ of run.world.civs) {
    const mine = frame.settlements.filter((t) => t.civ === civ.id);
    const people = mine.reduce((sum, t) => sum + t.pop, 0);
    const counts = STAGE_ORDER.map((s) => [s, mine.filter((t) => t.stage === s).length]).filter(([, n]) => n);
    const li = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = INK[civ.id];
    const name = document.createElement("span");
    name.className = "name";
    setText(name, civ.name);
    const pop = document.createElement("span");
    pop.className = "people";
    setText(pop, plural(people, "person").replace("persons", "people"));
    const detail = document.createElement("span");
    detail.className = "detail";
    const towns = counts.map(([s, n]) => plural(n, s)).join(", ") || "no settlements";
    setText(detail, `${towns}; ${frame.civs[civ.id].techs} of ${run.world.techs} techs`);
    li.append(swatch, name, pop, detail);
    list.append(li);
  }
}

function renderTown() {
  const town = selected && run.frames[at].settlements.find((t) => t.id === selected);
  $("town").hidden = !town;
  $("town-hint").hidden = Boolean(town);
  if (!town) return;
  setText($("town-title"), town.name);
  setText($("town-sub"), `${town.capital ? "Capital" : "Outpost"} of ${civName(town.civ)}`);
  const facts = [
    ["Stage", town.stage],
    ["People", String(town.pop)],
    ["Strong in", town.specialty.strong || "nothing"],
    ["Weak in", town.specialty.weak || "nothing"],
    ["Needs", town.need || "nothing"],
    ["Quirk", town.quirk ? nice(town.quirk) : "none"],
  ];
  const dl = $("town-facts");
  dl.replaceChildren();
  for (const [k, v] of facts) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    setText(dt, k);
    setText(dd, v);
    dl.append(dt, dd);
  }
}

// ---------- a ruler's turn ----------

function orderText(action) {
  const { kind, ...rest } = action;
  const args = Object.entries(rest).map(([k, v]) => `${k} ${typeof v === "string" ? v : JSON.stringify(v)}`);
  return args.length ? `${kind}: ${args.join(", ")}` : String(kind);
}

function goodsText(goods) {
  const parts = Object.entries(goods || {}).map(([good, n]) => `${n} ${good}`);
  return parts.length ? parts.join(", ") : "nothing";
}

const TURN_WAIT_MS = 200;  // a request reads the whole turn log, so wait until stepping pauses

async function loadTurn() {
  if (!run || timer) return;  // while the time-lapse plays, wait for it to stop
  const mine = ++asking;
  const civ = $("turn-civ").value;
  const newest = following && at === run.frames.length - 1;   // turns are logged every tick, frames every 4
  const tick = newest ? 2 ** 31 - 1 : run.frames[at].tick;
  setText($("turn-sub"), newest ? `Reading ${civName(civ)}'s latest turn.` : `Reading ${civName(civ)}'s turn at tick ${tick}.`);
  $("turn-facts").replaceChildren();
  await new Promise((done) => setTimeout(done, TURN_WAIT_MS));
  if (mine !== asking) return;
  const url = `/api/runs/${encodeURIComponent(runName)}/turns?civ=${encodeURIComponent(civ)}&tick=${tick}`;
  const data = await getJSON(url);
  if (mine === asking) renderTurn(data);
}

function renderTurn(data) {
  const turn = data.decide;
  const facts = $("turn-facts");
  facts.replaceChildren();
  if (!turn) {
    setText($("turn-sub"), `${civName(data.civ)} has not taken a turn by tick ${data.tick}.`);
    setText($("turn-raw"), "");
    setText($("turn-seen"), "");
    return;
  }
  const seen = turn.observation;
  const woke = seen ? seen.triggers.map((t) => (t.detail ? `${t.trigger} (${t.detail})` : t.trigger)).join(", ") : "";
  setText($("turn-sub"), seen ? `Turn at tick ${turn.tick}, woken by ${woke || "nothing"}` : `Turn at tick ${turn.tick} was skipped`);
  const reply = turn.reply && typeof turn.reply === "object" ? turn.reply : null;
  const orders = reply && Array.isArray(reply.actions) ? reply.actions : [];
  const rows = [
    ["Outcome", turn.output ? turn.output.status : "scripted bot, nothing stored"],
    ["Orders", orders.length ? orders.map(orderText).join("\n") : "none"],
    ["Rejected", turn.rejections.length ? turn.rejections.map((r) => `${r.kind || "reply"}: ${r.reason}`).join("\n") : "none"],
    ["Journal", seen && seen.journal.length ? seen.journal.slice(-3).map((e) => `${e.tick}: ${e.text}`).join("\n") : "empty"],
    ["Strategy", (data.reflect && data.reflect.reply) || (seen && seen.strategy) || "none yet"],
    ["Messages", data.messages && data.messages.length
      ? data.messages.slice(-3).map((m) => `${m.from}, sent tick ${m.sent}${m.hearsay ? " (hearsay: names a people it has not met)" : ""}:\n${m.body}`).join("\n\n")
      : "none"],
    ["Offers", seen && seen.offers && seen.offers.length
      ? seen.offers.map((o) => `${o.id} ${o.from} to ${o.to}: ${goodsText(o.give)} for ${goodsText(o.get)} (${o.status}, ends tick ${o.expires})`).join("\n")
      : "none"],
    ["Known peoples", seen && seen.dossiers && seen.dossiers.length
      ? seen.dossiers.map((d) => `${d.name}: ${d.standing}, met tick ${d.met_tick}, ${d.offers_received} offers in, ${d.offers_made} out, ${d.deliveries} deliveries, ${d.messages} messages`).join("\n")
      : "none yet"],
  ];
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    setText(dt, k);
    setText(dd, v);
    facts.append(dt, dd);
  }
  setText($("turn-raw"), turn.output ? turn.output.raw : JSON.stringify(turn.reply, null, 2));
  setText($("turn-seen"), seen ? JSON.stringify(seen, null, 2) : "Nothing: the turn was skipped.");
}

function renderTime() {
  const tick = run.frames[at].tick;
  $("scrub").value = String(at);
  setText($("when"), `Year ${Math.floor(tick / 4)}, tick ${tick}`);
  setText($("play"), timer ? "Pause" : "Play");
}

function show(index, animate) {
  if (!run) return;
  const before = run.frames[at];
  at = Math.max(0, Math.min(run.frames.length - 1, index));
  const now = run.frames[at];
  if (!diorama && animate && !reduceMotion.matches && now.tick > before.tick) {
    const was = new Map(before.settlements.map((t) => [t.id, t.stage]));
    for (const t of now.settlements) {
      if (was.has(t.id) && STAGE_ORDER.indexOf(t.stage) > STAGE_ORDER.indexOf(was.get(t.id))) {
        const { x, y } = tileXY(t.tile);
        pulses.push({ x: x * TILE + TILE / 2, y: y * TILE + TILE / 2, ink: INK[t.civ], start: performance.now() });
      }
    }
  }
  if (diorama) diorama.show(now, before, animate && !reduceMotion.matches);
  else draw();
  renderCivs();
  renderTown();
  renderTime();
  loadTurn().catch(fail);
}

// ---------- time controls ----------

function play() {
  if (!run) return;
  if (timer) return stop();
  if (at === run.frames.length - 1) at = 0;
  timer = setInterval(() => {
    if (at >= run.frames.length - 1) return stop();
    show(at + 1, true);
  }, PLAY_MS);
  renderTime();
}

function stop() {
  clearInterval(timer);
  timer = null;
  if (run) {
    renderTime();
    loadTurn().catch(fail);
  }
}

// ---------- following a run as it is played ----------

function setFollow(on) {
  clearInterval(following);
  following = on ? setInterval(() => catchUp().catch(fail), FOLLOW_MS) : null;
  $("follow").checked = on;
}

// Fetch only the frames saved since the last one held. A viewer on the newest frame moves on
// to the next; one looking back stays where it is.
async function catchUp() {
  if (!run || catching) return;
  catching = true;
  try {
    const name = runName, held = run.frames;
    const data = await getJSON(`/api/runs/${encodeURIComponent(name)}/frames?after=${held[held.length - 1].tick}`);
    if (name !== runName || held !== run.frames) return;   // another run was opened meanwhile
    const onNewest = at === held.length - 1;
    held.push(...data.frames);
    $("scrub").max = String(held.length - 1);
    if (onNewest && data.frames.length && !timer) show(held.length - 1, true);
    else if (onNewest && !timer) loadTurn().catch(fail);
    else renderTime();
    if (held[held.length - 1].tick >= data.ticks) {
      setFollow(false);
      setText($("readout"), "The run has reached its last tick.");
    }
  } finally {
    catching = false;
  }
}

$("follow").addEventListener("change", (e) => setFollow(e.target.checked));

// ---------- map interaction ----------

function tileAt(event) {
  const rect = canvas.getBoundingClientRect();
  const size = run.world.size;
  const x = Math.floor(((event.clientX - rect.left) / rect.width) * size);
  const y = Math.floor(((event.clientY - rect.top) / rect.height) * size);
  return x >= 0 && y >= 0 && x < size && y < size ? { x, y } : null;
}

function nearestTown(x, y) {
  let best = null, bestD = 4;   // within two tiles
  for (const t of run.frames[at].settlements) {
    const p = tileXY(t.tile);
    const d = (p.x - x) ** 2 + (p.y - y) ** 2;
    if (d <= bestD) { best = t; bestD = d; }
  }
  return best;
}

function hoverTile(tile) {
  if (!run) return;
  if (!tile) return setText($("readout"), "");
  const biome = (BIOME[run.world.biome[tile.y][tile.x]] || BIOME.P).name;
  const frame = run.frames[at];
  const o = frame.territory[tile.y][tile.x];
  const held = o < 0 ? "unclaimed" : `${frame.settlements[o].name}, ${civName(frame.settlements[o].civ)}`;
  const river = run.world.river[tile.y][tile.x] === "1" ? ", river" : "";
  setText($("readout"), `Tile ${tile.x},${tile.y}: ${biome}${river}; ${held}`);
}

function pickTile(tile) {
  if (!run) return;
  const town = tile && nearestTown(tile.x, tile.y);
  selected = town ? town.id : null;
  if (diorama) diorama.select(selected);
  else draw();
  renderTown();
}

canvas.addEventListener("mousemove", (event) => hoverTile(run && tileAt(event)));
canvas.addEventListener("click", (event) => pickTile(run && tileAt(event)));

$("play").addEventListener("click", play);
$("back").addEventListener("click", () => { stop(); show(at - 1, false); });
$("forward").addEventListener("click", () => { stop(); show(at + 1, true); });
$("scrub").addEventListener("input", (e) => { stop(); show(Number(e.target.value), false); });

document.addEventListener("keydown", (event) => {
  if (!run || event.target.tagName === "SELECT" || event.target.tagName === "INPUT") return;
  if (event.key === " ") { event.preventDefault(); play(); }
  if (event.key === "ArrowLeft") { stop(); show(at - 1, false); }
  if (event.key === "ArrowRight") { stop(); show(at + 1, true); }
  if ((event.key === "r" || event.key === "R") && diorama) diorama.resetView();
});

// ---------- loading ----------

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`The server answered ${response.status} for ${url}.`);
  return response.json();
}

async function loadRun(name) {
  stop();
  setFollow(false);
  const mine = ++loading;
  setText($("status"), "Loading the run.");
  const loaded = await getJSON(`/api/runs/${encodeURIComponent(name)}`);
  if (mine !== loading) return;
  setText($("status"), diorama ? "Carving the block." : "Painting the map.");
  // A short pause lets the status line paint; a hidden tab still finishes loading.
  await new Promise((done) => setTimeout(done, 30));
  if (mine !== loading) return;
  if (diorama) {
    diorama.load(loaded.world);
  } else {
    const painted = drawTerrain(loaded.world);    // about a second, once per run
    if (mine !== loading) return;
    terrain = painted;
  }
  run = loaded;
  runName = name;
  const pick = $("turn-civ");
  pick.replaceChildren();
  for (const civ of run.world.civs) {
    const option = document.createElement("option");
    option.value = civ.id;
    setText(option, civ.name);
    pick.append(option);
  }
  pick.value = (run.manifest.llm_civs && run.manifest.llm_civs[0]) || run.world.civs[0].id;
  if (!diorama) canvas.width = canvas.height = run.world.size * TILE;
  $("scrub").max = String(run.frames.length - 1);
  const m = run.manifest;
  const parts = [`Seed ${m.seed}, ${m.ticks} ticks, ${m.bot} bots`];
  if (m.events_enabled === false) parts.push("events off");
  let note = parts.join(", ") + ".";
  if (m.supply) note += ` Supplied run: a test stand-in for trade (ADR 0004), topping basics up to ${m.supply}.`;
  setText($("run-note"), note);
  selected = null;
  if (diorama) diorama.select(null);
  const unfinished = run.frames[run.frames.length - 1].tick < m.ticks;
  at = unfinished ? run.frames.length - 1 : 0;   // a run still being played opens on its newest frame
  setText($("status"), "");
  setFollow(unfinished);
  show(at, false);
}

// The 3D scene, if this browser can draw it. Any failure (no WebGL, a module that won't load)
// leaves the flat map in place, and says so.
async function openDiorama() {
  try {
    if (new URLSearchParams(location.search).has("flat")) throw new Error("the address asks for it with ?flat");
    const { createScene } = await import("./scene.js");
    diorama = createScene($("scene"), { onPick: pickTile, onHover: hoverTile });
    $("flat").hidden = true;
  } catch (error) {
    diorama = null;
    $("flat").hidden = false;
    setText($("readout"), `The flat map is shown because ${error.message}. Open the page without ?flat in a browser with WebGL for the 3D view.`);
  }
}

async function start() {
  await openDiorama();
  try {
    const runs = await getJSON("/api/runs");
    const select = $("run");
    for (const r of runs) {
      const option = document.createElement("option");
      option.value = r.name;
      setText(option, r.name);
      select.append(option);
    }
    if (!runs.length) {
      setText($("status"), "No runs found. Make one with: python -m fogline.run --out runs/<name>");
      return;
    }
    select.addEventListener("change", () => loadRun(select.value).catch(fail));
    $("turn-civ").addEventListener("change", () => loadTurn().catch(fail));
    await loadRun(runs[0].name);
  } catch (error) {
    fail(error);
  }
}

function fail(error) {
  setText($("status"), `Could not load the run. ${error.message} Check the viewer is still running, then reload the page.`);
}

start();
