// Procedural PBR textures, generated on a canvas at start-up. No image files, so no licences to track.
import * as THREE from "three";

// ------------------------------------------------------------------ noise
function hash2(ix, iy, seed) {
  let h = (ix * 374761393 + iy * 668265263 + seed * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}
const fade = (t) => t * t * (3 - 2 * t);

// Tileable value noise: lattice wraps every `period` cells.
export function vnoise(x, y, period, seed = 1) {
  const xi = Math.floor(x), yi = Math.floor(y);
  const xf = x - xi, yf = y - yi;
  const w = (v) => ((v % period) + period) % period;
  const a = hash2(w(xi), w(yi), seed), b = hash2(w(xi + 1), w(yi), seed);
  const c = hash2(w(xi), w(yi + 1), seed), d = hash2(w(xi + 1), w(yi + 1), seed);
  const u = fade(xf), v = fade(yf);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
export function fbm(x, y, period, oct = 4, seed = 1) {
  let s = 0, amp = 0.5, f = 1, n = 0;
  for (let o = 0; o < oct; o++) { s += amp * vnoise(x * f, y * f, period * f, seed + o * 17); n += amp; amp *= 0.5; f *= 2; }
  return s / n;
}

// Non-periodic noise for geometry (terrain, rocks)
export function noise2(x, y, seed = 3) {
  const xi = Math.floor(x), yi = Math.floor(y);
  const xf = x - xi, yf = y - yi;
  const a = hash2(xi, yi, seed), b = hash2(xi + 1, yi, seed), c = hash2(xi, yi + 1, seed), d = hash2(xi + 1, yi + 1, seed);
  const u = fade(xf), v = fade(yf);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
export function fbm2(x, y, oct = 5, seed = 3) {
  let s = 0, amp = 0.5, f = 1, n = 0;
  for (let o = 0; o < oct; o++) { s += amp * noise2(x * f, y * f, seed + o * 31); n += amp; amp *= 0.5; f *= 2.03; }
  return s / n;
}
export function ridged(x, y, oct = 5, seed = 9) {
  let s = 0, amp = 0.5, f = 1, n = 0;
  for (let o = 0; o < oct; o++) { const v = 1 - Math.abs(noise2(x * f, y * f, seed + o * 13) * 2 - 1); s += amp * v * v; n += amp; amp *= 0.5; f *= 2.1; }
  return s / n;
}

// ------------------------------------------------------------------ canvas helpers
function canvasOf(size) { const c = document.createElement("canvas"); c.width = c.height = size; return c; }

function fromField(size, fn, srgb = true) {
  const c = canvasOf(size), g = c.getContext("2d"), img = g.createImageData(size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const [r, gg, b, a = 255] = fn(x, y);
    const i = (y * size + x) * 4;
    img.data[i] = r; img.data[i + 1] = gg; img.data[i + 2] = b; img.data[i + 3] = a;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.anisotropy = 8;
  return t;
}

function normalFromHeight(size, h, strength = 2) {
  return fromField(size, (x, y) => {
    const at = (xx, yy) => h[((yy + size) % size) * size + ((xx + size) % size)];
    const dx = (at(x + 1, y) - at(x - 1, y)) * strength, dy = (at(x, y + 1) - at(x, y - 1)) * strength;
    const nz = 1 / Math.sqrt(dx * dx + dy * dy + 1);
    return [(-dx * nz * 0.5 + 0.5) * 255, (dy * nz * 0.5 + 0.5) * 255, (nz * 0.5 + 0.5) * 255];
  }, false);
}

function heightField(size, fn) {
  const h = new Float32Array(size * size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) h[y * size + x] = fn(x / size, y / size);
  return h;
}

const mix = (a, b, t) => a + (b - a) * t;
const clamp01 = (v) => Math.min(1, Math.max(0, v));

// ------------------------------------------------------------------ materials' textures
export function makeTextures(quality) {
  const S = quality === "low" ? 128 : quality === "medium" ? 256 : 512;
  const out = {};

  // Desert sand: fine grain plus wind ripples
  const sandH = heightField(S, (u, v) => {
    const ripple = Math.sin((u * 18 + fbm(u * 4, v * 4, 4, 3, 5) * 2.5) * Math.PI * 2) * 0.5 + 0.5;
    return ripple * 0.55 + fbm(u * 32, v * 32, 32, 2, 7) * 0.45;
  });
  out.sand = fromField(S, (x, y) => {
    const g = hash2(x, y, 11), n = fbm(x / S * 6, y / S * 6, 6, 3, 2), h = sandH[y * S + x];
    const r = mix(214, 232, n) + (g - 0.5) * 16 + h * 5, gg = mix(186, 204, n) + (g - 0.5) * 15 + h * 4, b = mix(148, 168, n) + (g - 0.5) * 13;
    return [r, gg, b];
  });
  out.sandN = normalFromHeight(S, sandH, 1.8);

  // Tilled field soil: furrows along v, clods
  const soilH = heightField(S, (u, v) => {
    const furrow = Math.pow(Math.abs(Math.sin(u * Math.PI * 8)), 0.6);
    return furrow * 0.6 + fbm(u * 16, v * 16, 16, 4, 21) * 0.4;
  });
  out.soil = fromField(S, (x, y) => {
    const n = fbm(x / S * 8, y / S * 8, 8, 4, 23), g = hash2(x, y, 29), h = soilH[y * S + x];
    const v = 0.75 + h * 0.3;
    return [(150 + n * 40 + (g - 0.5) * 18) * v, (112 + n * 30 + (g - 0.5) * 14) * v, (78 + n * 22 + (g - 0.5) * 12) * v];
  });
  out.soilN = normalFromHeight(S, soilH, 4.5);

  // Rock with strata, for the mountains and boulders
  const rockH = heightField(S, (u, v) => fbm(u * 6, v * 6, 6, 5, 41) * 0.7 + Math.abs(Math.sin((v * 22 + fbm(u * 3, v * 3, 3, 3, 43) * 3) * Math.PI)) * 0.3);
  out.rock = fromField(S, (x, y) => {
    const h = rockH[y * S + x], n = fbm(x / S * 3, y / S * 3, 3, 3, 47);
    return [mix(120, 176, h) + n * 30, mix(92, 138, h) + n * 22, mix(70, 104, h) + n * 14];
  });
  out.rockN = normalFromHeight(S, rockH, 5);

  // Gravel road
  const gravH = heightField(S, (u, v) => Math.pow(fbm(u * 48, v * 48, 48, 2, 51), 1.6));
  out.gravel = fromField(S, (x, y) => {
    const g = hash2(x, y, 53), h = gravH[y * S + x];
    const c = 150 + h * 70 + (g - 0.5) * 40;
    return [c * 1.02, c * 0.93, c * 0.82];
  });
  out.gravelN = normalFromHeight(S, gravH, 3);

  // Date palm bark: diamond leaf-base scars
  const barkH = heightField(S, (u, v) => {
    const a = Math.abs(Math.sin((u * 6 + v * 10) * Math.PI)), b = Math.abs(Math.sin((u * 6 - v * 10) * Math.PI));
    return Math.min(a, b) * 0.7 + fbm(u * 20, v * 20, 20, 2, 61) * 0.3;
  });
  out.bark = fromField(S, (x, y) => {
    const h = barkH[y * S + x], n = hash2(x, y, 63);
    return [mix(70, 150, h) + n * 12, mix(52, 112, h) + n * 9, mix(36, 74, h) + n * 6];
  });
  out.barkN = normalFromHeight(S, barkH, 4);

  // Water ripples (normal only)
  const waterH = heightField(S, (u, v) => fbm(u * 8, v * 8, 8, 5, 71));
  out.waterN = normalFromHeight(S, waterH, 2.4);

  // Concrete / render for buildings
  out.concrete = fromField(S, (x, y) => {
    const n = fbm(x / S * 10, y / S * 10, 10, 4, 81), g = hash2(x, y, 83);
    const c = 214 + n * 26 + (g - 0.5) * 10;
    return [c, c * 0.975, c * 0.94];
  });

  // Solar cells: blue-black cells with silver busbars
  out.solar = fromField(S, (x, y) => {
    const cx = (x / S) * 6, cy = (y / S) * 10;
    const gap = Math.min(cx % 1, 1 - (cx % 1), cy % 1, 1 - (cy % 1)) < 0.035;
    const bus = Math.abs((cx % 1) - 0.5) < 0.008;
    if (gap) return [196, 200, 206];
    if (bus) return [120, 130, 150];
    const n = hash2(x, y, 91) * 12;
    return [22 + n, 34 + n, 68 + n * 1.5];
  });
  out.solar.wrapS = out.solar.wrapT = THREE.ClampToEdgeWrapping;

  // Brand mark for the research tower
  out.logo = (() => {
    const c = canvasOf(256), g = c.getContext("2d");
    g.fillStyle = "#13261d"; g.fillRect(0, 0, 256, 256);
    g.strokeStyle = "#6ee7a8"; g.lineWidth = 10; g.beginPath(); g.arc(128, 118, 70, 0, Math.PI * 2); g.stroke();
    g.strokeStyle = "#7ff2b6"; g.lineWidth = 12; g.lineCap = "round";
    g.beginPath(); g.moveTo(92, 150); g.quadraticCurveTo(110, 80, 168, 84); g.quadraticCurveTo(160, 140, 92, 150); g.stroke();
    g.fillStyle = "#e9f7ef"; g.font = "600 30px sans-serif"; g.textAlign = "center"; g.fillText("WORLDLAB", 128, 228);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();

  // Soft sprites
  out.glow = sprite(128, (d) => Math.pow(clamp01(1 - d), 2.2));
  out.dust = sprite(64, (d) => Math.pow(clamp01(1 - d), 3) * 0.9);
  out.cloud = (() => {
    const s = 256, c = canvasOf(s), g = c.getContext("2d"), img = g.createImageData(s, s);
    for (let y = 0; y < s; y++) for (let x = 0; x < s; x++) {
      const dx = (x / s - 0.5) * 2, dy = (y / s - 0.5) * 2.6, d = Math.sqrt(dx * dx + dy * dy);
      const n = fbm2(x / 40, y / 40, 5, 101);
      const a = clamp01((1 - d) * 1.6 * (0.45 + n)) ;
      const i = (y * s + x) * 4;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = 255; img.data[i + 3] = a * 210;
    }
    g.putImageData(img, 0, 0);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  })();
  return out;
}

function sprite(s, f) {
  const c = canvasOf(s), g = c.getContext("2d"), img = g.createImageData(s, s);
  for (let y = 0; y < s; y++) for (let x = 0; x < s; x++) {
    const d = Math.hypot(x / s - 0.5, y / s - 0.5) * 2, i = (y * s + x) * 4;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = 255; img.data[i + 3] = f(d) * 255;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

export function disposeTextures(tex) { Object.values(tex || {}).forEach((t) => t && t.dispose && t.dispose()); }
