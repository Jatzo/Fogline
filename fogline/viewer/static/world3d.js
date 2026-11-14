// The diorama's fixed rules: how high each tile stands, what colour it is painted, and where a
// town's houses go. No WebGL here, and no Math.random: every wobble comes from a hash of the
// tile, so the same run always carves the same block.

export const BIOME = {
  S: { name: "sea", rgb: [58, 88, 104] },
  C: { name: "coast", rgb: [196, 182, 132] },
  P: { name: "plains", rgb: [150, 166, 96] },
  F: { name: "forest", rgb: [78, 104, 58] },
  D: { name: "desert", rgb: [214, 176, 116] },
  T: { name: "tundra", rgb: [206, 210, 202] },
  M: { name: "mountains", rgb: [128, 118, 104] },
};
export const RIVER_RGB = [70, 118, 138];
export const SNOW_RGB = [232, 230, 222];

export const INK = {
  ironhold: "#c0412b",
  dunerunners: "#e0a030",
  saltreach: "#1f9e9a",
  frostmark: "#4a7fd0",
  verdance: "#b8de4c",
};

// How each culture builds: roof pitch (0 is flat), roof colour, wall colour.
export const STYLE = {
  ironhold: { pitch: 0.45, roofs: "#7d3326", walls: "#9a948a" },
  dunerunners: { pitch: 0.04, roofs: "#c98f3a", walls: "#e6cf9f" },
  saltreach: { pitch: 0.4, roofs: "#2d7f86", walls: "#ece6d8" },
  frostmark: { pitch: 0.75, roofs: "#35558c", walls: "#8a6a4c" },
  verdance: { pitch: 0.5, roofs: "#c8a84e", walls: "#d8c7a0" },
};

export const STAGE_ORDER = ["hamlet", "village", "town", "city"];
const SEAT_HOUSES = { hamlet: 3, village: 6, town: 10, city: 16 };

export const WATER_LEVEL = -0.12;
export const SEA_FLOOR = -1.1;
export const TABLE_LEVEL = -11;
// Strata on the block's sides, top to bottom: [lower edge, colour].
export const STRATA = [[-2.4, [92, 66, 46]], [-5.0, [138, 96, 64]], [-8.0, [104, 98, 90]], [TABLE_LEVEL, [62, 56, 52]]];

export function hash(x, y, salt) {
  let h = (Math.imul(x | 0, 374761393) + Math.imul(y | 0, 668265263) + Math.imul(salt | 0, 2246822519)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

export function noise(x, y, salt) {
  // Smooth value noise on a unit lattice.
  const x0 = Math.floor(x), y0 = Math.floor(y);
  const fx = x - x0, fy = y - y0;
  const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
  const a = hash(x0, y0, salt), b = hash(x0 + 1, y0, salt);
  const c = hash(x0, y0 + 1, salt), d = hash(x0 + 1, y0 + 1, salt);
  const top = a + (b - a) * sx;
  return top + ((c + (d - c) * sx) - top) * sy;
}

export function tileXY(key) {
  const [x, y] = key.split(",").map(Number);
  return { x, y };
}

// Height of a tile's centre. Mountains peak here; everything else is gentle.
export function centreHeight(world, x, y) {
  const code = world.biome[y][x];
  const n = noise(x * 0.35, y * 0.35, 11);
  if (code === "S") return SEA_FLOOR + n * 0.3;
  if (world.river[y][x] === "1") return WATER_LEVEL + 0.06;
  switch (code) {
    case "C": return 0.06 + n * 0.08;
    case "D": return 0.22 + n * 0.45;
    case "F": return 0.38 + n * 0.3;
    case "T": return 0.45 + n * 0.35;
    case "M": return 1.2 + noise(x * 0.45, y * 0.45, 12) * 1.6 + hash(x, y, 13) * 0.5;  // ranges, not a field of spikes
    default: return 0.28 + n * 0.25;
  }
}

// What a tile lends to the corners it shares: mountains only a shoulder, so peaks stay sharp.
function cornerShare(world, x, y) {
  const h = centreHeight(world, x, y);
  return world.biome[y][x] === "M" ? Math.min(h, 1.3) : h;
}

// Heights of every tile corner, (size + 1) squared, each the mean of the tiles that meet there.
export function cornerHeights(world) {
  const n = world.size, out = new Float32Array((n + 1) * (n + 1));
  for (let cy = 0; cy <= n; cy++) {
    for (let cx = 0; cx <= n; cx++) {
      let sum = 0, count = 0;
      for (const [x, y] of [[cx - 1, cy - 1], [cx, cy - 1], [cx - 1, cy], [cx, cy]]) {
        if (x >= 0 && y >= 0 && x < n && y < n) { sum += cornerShare(world, x, y); count++; }
      }
      out[cy * (n + 1) + cx] = sum / count;
    }
  }
  return out;
}

// The painted colour of a tile, 0 to 255 per channel, before any civ's tint.
export function tileRGB(world, x, y) {
  const code = world.biome[y][x];
  let rgb = world.river[y][x] === "1" && code !== "S" ? RIVER_RGB : (BIOME[code] || BIOME.P).rgb;
  if (code === "M" && centreHeight(world, x, y) > 2.75) rgb = SNOW_RGB;
  const k = 0.9 + hash(x, y, 3) * 0.18;
  return rgb.map((c) => Math.min(255, c * k));
}

export function hexRGB(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}

export function mix(a, b, t) {
  return a.map((c, i) => c + (b[i] - c) * t);
}

// Where the houses of a settlement's seat stand, as offsets from the tile centre, nearest first.
export function seatLayout(stage, seed) {
  const count = SEAT_HOUSES[stage] || SEAT_HOUSES.hamlet;
  const spots = [];
  for (let i = 0; i < count; i++) {
    const ring = i < 6 ? 0.55 : 1.1;
    const slot = i < 6 ? i : i - 6;
    const slots = i < 6 ? 6 : 10;
    const angle = (slot / slots) * Math.PI * 2 + hash(seed, i, 7) * 0.5;
    spots.push({ dx: Math.cos(angle) * ring, dz: Math.sin(angle) * ring, turn: hash(seed, i, 8) * Math.PI,
                 size: 0.24 + hash(seed, i, 9) * 0.1 });
  }
  return spots;
}
