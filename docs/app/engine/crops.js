// The ten crops, each with recognisable geometry for four growth stages plus the harvested field.
// Stage, size, colour, droop and damage all come from the simulation's state for that field.
import * as THREE from "three";
import { GeoBuilder, V, C, rng, polar } from "./geo.js?v=3e51a05a34";

// Published thresholds the visuals use (same values as worldlab/farm/crops.py).
export const CROP_INFO = {
  wheat: { label: "Wheat", salt: 6.0, heat: 31, big: false, flower: [0.5, 0.65] },
  rice: { label: "Rice", salt: 3.0, heat: 36, big: false, flower: [0.55, 0.7] },
  maize: { label: "Maize", salt: 1.7, heat: 36, big: true, flower: [0.48, 0.6] },
  potato: { label: "Potatoes", salt: 1.7, heat: 30, big: false, flower: [0.35, 0.6] },
  cassava: { label: "Cassava", salt: 2.0, heat: 40, big: true, flower: [0.45, 0.8] },
  soybean: { label: "Soybeans", salt: 5.0, heat: 35, big: false, flower: [0.45, 0.65] },
  sorghum: { label: "Sorghum", salt: 6.8, heat: 40, big: true, flower: [0.5, 0.62] },
  millet: { label: "Millet", salt: 6.0, heat: 41, big: true, flower: [0.48, 0.6] },
  beans: { label: "Common beans", salt: 1.0, heat: 32, big: false, flower: [0.4, 0.6] },
  sweet_potato: { label: "Sweet potatoes", salt: 1.5, heat: 38, big: false, flower: [0.4, 0.7] },
};

const G = { leaf: C("#4e8a32"), leaf2: C("#5f9a3c"), dark: C("#3d7028"), pale: C("#8db45a"), yellow: C("#c9b14a"),
  gold: C("#d8b25a"), straw: C("#c8a865"), brown: C("#8a6338"), purple: C("#8a5cb0"), white: C("#f1efe6"), stem: C("#6f9a45") };
const mixc = (a, b, t) => a.clone().lerp(b, t);

// ---------------------------------------------------------------- grasses
function cereal(stage, r, o) {
  const b = new GeoBuilder();
  const tillers = [2, 5, 8, 8][stage];
  const H = o.H * [0.18, 0.5, 0.95, 1][stage];
  const leafCol = stage === 3 ? mixc(G.leaf, G.straw, 0.75) : o.leaf;
  const tipCol = stage === 3 ? G.straw : mixc(o.leaf, G.pale, 0.3);
  for (let k = 0; k < tillers; k++) {
    const a = (k / tillers) * Math.PI * 2 + r() * 0.6, lean = 0.08 + r() * 0.12;
    const base = polar(0.03, a, 0);
    const top = base.clone().add(V(Math.cos(a) * lean * H, H * (0.85 + r() * 0.15), Math.sin(a) * lean * H));
    if (stage >= 1) b.stem([base, base.clone().lerp(top, 0.5), top], 0.012, 0.008, stage === 3 ? G.straw : G.stem, 4);
    const nl = stage === 0 ? 2 : 3;
    for (let l = 0; l < nl; l++) {
      const y = stage === 0 ? 0 : H * (0.15 + l * 0.22);
      const la = a + (l % 2 ? 2.4 : -0.6);
      b.leaf(base.clone().lerp(top, y / Math.max(H, 0.01)), V(Math.cos(la), 1.1 - l * 0.15, Math.sin(la)),
        o.leafLen * (stage === 0 ? 0.5 : 1), o.leafW, { bend: 0.45, seg: 4, base: leafCol, tip: tipCol, fold: 0.3 });
    }
    if (stage >= 2) o.head(b, top, stage, a, r);
  }
  return b.build();
}

const wheatHead = (b, top, stage, a, r) => {
  const col = stage === 3 ? G.gold : C("#9bb85a");
  const end = top.clone().add(V(Math.cos(a) * 0.02, 0.11, Math.sin(a) * 0.02));
  b.rod(top, end, 0.013, col, 5);
  for (let k = 0; k < 4; k++) b.leaf(top.clone().lerp(end, 0.3 + k * 0.2), V(Math.cos(a + k * 1.6) * 0.3, 1, Math.sin(a + k * 1.6) * 0.3), 0.07, 0.004, { bend: 0, seg: 1, base: col, tip: col, fold: 0 });
};
const riceHead = (b, top, stage, a) => {
  const col = stage === 3 ? G.gold : C("#a9c26a");
  let p = top.clone();
  for (let k = 0; k < 6; k++) {
    const q = p.clone().add(V(Math.cos(a) * 0.035, 0.02 - k * 0.022, Math.sin(a) * 0.035));
    b.rod(p, q, 0.004, col, 3); b.blob(q, 0.012, col, { detail: 0 }); p = q;
  }
};

function maizeLike(stage, r, o) {
  const b = new GeoBuilder();
  const H = o.H * [0.12, 0.5, 1, 1][stage];
  const senesce = stage === 3 ? 0.65 : 0;
  const stalk = mixc(G.stem, G.straw, senesce);
  const top = V(0, H, 0);
  if (stage >= 1) b.stem([V(0, 0, 0), V(0.01, H * 0.5, 0), top], o.r0, o.r0 * 0.55, stalk, 6);
  const n = [3, 7, 10, 10][stage];
  for (let l = 0; l < n; l++) {
    const t = stage === 0 ? 0 : 0.08 + (l / n) * 0.82;
    const la = l * 2.4 + r() * 0.3;
    const col = mixc(o.leaf, G.straw, senesce * (1 - t * 0.5));
    b.leaf(V(0, H * t, 0), V(Math.cos(la), 0.9 - t * 0.4, Math.sin(la)), o.leafLen * (stage === 0 ? 0.45 : 1 - t * 0.35), o.leafW,
      { bend: 0.55, seg: 5, base: col, tip: mixc(col, G.yellow, 0.25), fold: 0.35 });
  }
  if (stage >= 2) o.top(b, top, stage, r, H);
  return b.build();
}
const maizeTop = (b, top, stage, r, H) => {
  const tassel = stage === 3 ? G.brown : C("#c9b36a");
  b.rod(top, top.clone().add(V(0, 0.22, 0)), 0.01, tassel, 4);
  for (let k = 0; k < 6; k++) b.leaf(top.clone().add(V(0, 0.12, 0)), V(Math.cos(k * 1.05), 0.7, Math.sin(k * 1.05)), 0.18, 0.012, { bend: 0.5, seg: 2, base: tassel, tip: tassel, fold: 0 });
  const cobAt = V(0.05, H * 0.5, 0), cobEnd = V(0.16, H * 0.62, 0.02);
  b.rod(cobAt, cobEnd, 0.05, stage === 3 ? C("#cdb27a") : C("#7fa64b"), 7, 0.035);
  if (stage === 2) b.blob(cobEnd, 0.025, C("#c98f52"), { detail: 0 });                      // silks
};
const sorghumTop = (b, top, stage) => {
  const col = stage === 3 ? C("#9a4f2a") : C("#9fb158");
  b.blob(top.clone().add(V(0, 0.12, 0)), 0.08, col, { sy: 1.6, detail: 1, jitter: 0.25 });
};
const milletTop = (b, top, stage) => {
  const col = stage === 3 ? C("#b59a6a") : C("#8aa356");
  b.rod(top, top.clone().add(V(0.01, 0.3, 0)), 0.032, col, 7, 0.026);
};

// ---------------------------------------------------------------- broadleaf crops
function potato(stage, r) {
  const b = new GeoBuilder();
  const H = [0.12, 0.38, 0.5, 0.36][stage], col = stage === 3 ? mixc(G.leaf, G.yellow, 0.6) : G.leaf;
  const stems = [3, 6, 7, 6][stage];
  for (let s = 0; s < stems; s++) {
    const a = (s / stems) * Math.PI * 2 + r() * 0.5;
    const tip = V(Math.cos(a) * H * 0.7, H * (0.7 + r() * 0.3), Math.sin(a) * H * 0.7);
    b.stem([V(0, 0, 0), tip.clone().multiplyScalar(0.5).add(V(0, 0.05, 0)), tip], 0.012, 0.007, G.stem, 4);
    const nl = stage === 0 ? 2 : 5;
    for (let k = 0; k < nl; k++) {
      const p = V(0, 0, 0).lerp(tip, 0.35 + k * 0.14), la = a + (k % 2 ? 1.2 : -1.2);
      b.leaf(p, V(Math.cos(la), 0.25, Math.sin(la)), 0.11, 0.06, { bend: 0.2, shape: "oval", seg: 3, base: col, tip: mixc(col, G.dark, 0.3) });
    }
    if (stage === 2 && s % 2 === 0) for (let f = 0; f < 4; f++) b.blob(tip.clone().add(V((r() - 0.5) * 0.06, 0.03, (r() - 0.5) * 0.06)), 0.018, f % 2 ? G.white : C("#c9a8e0"), { detail: 0 });
  }
  return b.build();
}

function sweetPotato(stage, r) {
  const b = new GeoBuilder();
  const reach = [0.12, 0.35, 0.55, 0.6][stage], vines = [3, 5, 7, 8][stage];
  const col = stage === 3 ? mixc(G.leaf2, G.yellow, 0.3) : G.leaf2;
  for (let s = 0; s < vines; s++) {
    const a = (s / vines) * Math.PI * 2 + r() * 0.6;
    const pts = [];
    for (let i = 0; i <= 4; i++) pts.push(V(Math.cos(a + i * 0.15) * reach * i / 4, 0.02 + Math.sin(i) * 0.01, Math.sin(a + i * 0.15) * reach * i / 4));
    b.stem(pts, 0.008, 0.006, C("#7a6a3c"), 3);
    pts.slice(1).forEach((p, i) => {
      const la = a + (i % 2 ? 1.3 : -1.3);
      b.leaf(p, V(Math.cos(la), 0.9, Math.sin(la)), 0.1, 0.09, { bend: 0.4, shape: "heart", seg: 3, base: col, tip: mixc(col, G.purple, 0.15) });
    });
  }
  return b.build();
}

function cassava(stage, r) {
  const b = new GeoBuilder();
  const H = [0.25, 0.8, 1.4, 1.6][stage];
  const stem = C("#8a7a5a"), col = stage === 3 ? mixc(G.dark, G.yellow, 0.25) : G.dark;
  const top = V(0.02, H, 0);
  b.stem([V(0, 0, 0), V(0, H * 0.5, 0.01), top], 0.025, 0.015, stem, 5);
  const branches = stage >= 2 ? [top.clone().add(V(0.2, 0.25, 0)), top.clone().add(V(-0.18, 0.22, 0.1))] : [top];
  if (stage >= 2) branches.forEach((t) => b.stem([top, t], 0.014, 0.01, stem, 4));
  branches.forEach((t) => {
    const nl = stage === 0 ? 3 : 6;
    for (let k = 0; k < nl; k++) {
      const a = (k / nl) * Math.PI * 2 + r();
      const petiole = t.clone().add(V(Math.cos(a) * 0.14, 0.04, Math.sin(a) * 0.14));
      b.stem([t, petiole], 0.004, 0.003, C("#a0503a"), 3);                     // red petioles
      for (let lobe = -3; lobe <= 3; lobe++) {
        const la = a + lobe * 0.42;
        b.leaf(petiole, V(Math.cos(la), 0.15, Math.sin(la)), 0.16 - Math.abs(lobe) * 0.02, 0.035, { bend: 0.3, shape: "lance", seg: 3, base: col, tip: mixc(col, G.pale, 0.2) });
      }
    }
  });
  return b.build();
}

function legume(stage, r, o) {
  const b = new GeoBuilder();
  const H = o.H * [0.25, 0.75, 1, 0.9][stage];
  const col = stage === 3 ? mixc(o.leaf, G.yellow, o.senesce) : o.leaf;
  const stems = [2, 5, 6, 6][stage];
  for (let s = 0; s < stems; s++) {
    const a = (s / stems) * Math.PI * 2 + r() * 0.5;
    const tip = V(Math.cos(a) * H * 0.45, H * (0.75 + r() * 0.25), Math.sin(a) * H * 0.45);
    b.stem([V(0, 0, 0), tip.clone().multiplyScalar(0.55), tip], 0.01, 0.006, G.stem, 4);
    const nodes = stage === 0 ? 1 : 3;
    for (let k = 0; k < nodes; k++) {
      const p = V(0, 0, 0).lerp(tip, 0.45 + k * 0.25), la = a + k * 2.1;
      const pet = p.clone().add(V(Math.cos(la) * 0.06, 0.02, Math.sin(la) * 0.06));
      b.stem([p, pet], 0.003, 0.003, G.stem, 3);
      for (const off of [-0.9, 0, 0.9]) b.leaf(pet, V(Math.cos(la + off), 0.3, Math.sin(la + off)), o.leafLen, o.leafW, { bend: 0.2, shape: "oval", seg: 3, base: col, tip: mixc(col, G.dark, 0.25) });
      if (stage === 2) b.blob(p.clone().add(V(0, 0.015, 0)), 0.012, o.flower, { detail: 0 });
      if (stage === 3) for (let q = 0; q < 2; q++) b.rod(p, p.clone().add(V(Math.cos(la + q) * 0.02, -0.07, Math.sin(la + q) * 0.02)), 0.008, o.pod, 4);
    }
  }
  return b.build();
}

// ---------------------------------------------------------------- harvested field
function stubble(crop, r) {
  const b = new GeoBuilder();
  if (["potato", "sweet_potato", "cassava"].includes(crop)) {
    b.blob(V(0, 0.01, 0), 0.16, C("#9a7552"), { sy: 0.35, detail: 1, jitter: 0.2 });      // lifted ridge
    if (crop === "potato") for (let k = 0; k < 3; k++) b.blob(V((r() - 0.5) * 0.2, 0.04, (r() - 0.5) * 0.2), 0.03, C("#c9a46a"), { sy: 0.8 });
  } else {
    for (let k = 0; k < 6; k++) { const a = r() * 6.28; b.rod(polar(0.03, a, 0), polar(0.04, a, 0.07 + r() * 0.04), 0.006, G.straw, 3); }
  }
  return b.build();
}

const BUILDERS = {
  wheat: (s, r) => cereal(s, r, { H: 0.85, leaf: G.leaf2, leafLen: 0.26, leafW: 0.018, head: wheatHead }),
  rice: (s, r) => cereal(s, r, { H: 0.8, leaf: C("#5aa046"), leafLen: 0.34, leafW: 0.014, head: riceHead }),
  millet: (s, r) => maizeLike(s, r, { H: 1.5, r0: 0.018, leaf: C("#5a9238"), leafLen: 0.45, leafW: 0.035, top: milletTop }),
  sorghum: (s, r) => maizeLike(s, r, { H: 1.3, r0: 0.024, leaf: C("#4f8a34"), leafLen: 0.5, leafW: 0.05, top: sorghumTop }),
  maize: (s, r) => maizeLike(s, r, { H: 1.9, r0: 0.03, leaf: C("#4a8a30"), leafLen: 0.7, leafW: 0.075, top: maizeTop }),
  potato: (s, r) => potato(s, r),
  sweet_potato: (s, r) => sweetPotato(s, r),
  cassava: (s, r) => cassava(s, r),
  soybean: (s, r) => legume(s, r, { H: 0.55, leaf: C("#4f8a2e"), leafLen: 0.07, leafW: 0.04, flower: C("#9b6fc9"), pod: C("#8a6a3a"), senesce: 0.8 }),
  beans: (s, r) => legume(s, r, { H: 0.45, leaf: C("#5a9a36"), leafLen: 0.09, leafW: 0.06, flower: G.white, pod: C("#9fb85a"), senesce: 0.45 }),
};

const cache = new Map();
export function cropGeometry(crop, stage) {           // stage 0-3, or 4 = harvested
  const key = `${crop}:${stage}`;
  if (!cache.has(key)) {
    const r = rng(crop.length * 97 + stage * 13);
    cache.set(key, stage === 4 ? stubble(crop, r) : BUILDERS[crop](stage, r));
  }
  return cache.get(key);
}
export function clearCropCache() { cache.forEach((g) => g.dispose()); cache.clear(); }

// ---------------------------------------------------------------- material with wind and drought droop
export function cropMaterial(shared) {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.72, metalness: 0, side: THREE.DoubleSide });
  m.userData.droop = { value: 0 };
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uTime = shared.time; sh.uniforms.uWind = shared.wind; sh.uniforms.uDroop = m.userData.droop;
    sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nuniform float uTime; uniform float uWind; uniform float uDroop;")
      .replace("#include <begin_vertex>", `#include <begin_vertex>
        float hgt = max(transformed.y, 0.0);
        #ifdef USE_INSTANCING
          vec2 ip = vec2(instanceMatrix[3].x, instanceMatrix[3].z);
        #else
          vec2 ip = vec2(0.0);
        #endif
        float ph = ip.x * 0.35 + ip.y * 0.27;
        float sway = sin(uTime * 1.6 + ph) * 0.65 + sin(uTime * 3.3 + ph * 1.9) * 0.25;
        float k = hgt * hgt;
        transformed.x += sway * uWind * k * 0.16;
        transformed.z += cos(uTime * 1.2 + ph) * uWind * k * 0.06;
        float rr = length(transformed.xz);
        transformed.y -= uDroop * (rr * rr * 0.9 + hgt * 0.12);`);
  };
  m.customProgramCacheKey = () => "crop-wind";
  return m;
}

// ---------------------------------------------------------------- one field's crop
export class FieldCrop {
  constructor(parent, W, D, density, shared) {
    this.parent = parent; this.W = W; this.D = D; this.density = density; this.shared = shared;
    this.meshes = []; this.crop = null; this.key = "";
    this.material = cropMaterial(shared);
    this.ghost = new THREE.MeshStandardMaterial({ vertexColors: true, transparent: true, opacity: 0.35, depthWrite: false, side: THREE.DoubleSide,
      emissive: new THREE.Color("#2fbf7a"), emissiveIntensity: 0.25 });
  }

  setCrop(crop, planned = false) {
    if (crop === this.crop && planned === this.planned) return;
    this.clear();
    this.crop = crop; this.planned = planned;
    if (!crop || !CROP_INFO[crop]) return;
    const big = CROP_INFO[crop].big;
    const cols = Math.max(6, Math.round((big ? 13 : 18) * Math.sqrt(this.density)));
    const rows = Math.max(6, Math.round((big ? 18 : 30) * Math.sqrt(this.density)));
    this.layout = [];
    const r = rng(crop.length * 31 + 7);
    for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
      const x = -this.W / 2 + 0.6 + (i + 0.5) * (this.W - 1.2) / cols + (r() - 0.5) * 0.12;
      const z = -this.D / 2 + 0.5 + (j + 0.5) * (this.D - 1.0) / rows + (r() - 0.5) * 0.1;
      this.layout.push({ x, z, rot: r() * Math.PI * 2, jit: 0.85 + r() * 0.3, alive: r(), pest: r(), shade: r() });
    }
    for (let s = 0; s <= 4; s++) {
      const im = new THREE.InstancedMesh(cropGeometry(crop, s), planned ? this.ghost : this.material, this.layout.length);
      im.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      im.castShadow = !planned; im.receiveShadow = true; im.visible = false;
      im.frustumCulled = false;
      this.parent.add(im); this.meshes.push(im);
    }
    this.key = "";
  }

  clear() {
    this.meshes.forEach((m) => { this.parent.remove(m); m.dispose(); });
    this.meshes = []; this.crop = null;
  }

  // w: world state for this field (stage, cc, ksw, pest, stand, done, ece_top, sown); tmax for heat at flowering
  update(w, tmax = 30, preview = false) {
    if (!this.crop || !this.meshes.length) return;
    const info = CROP_INFO[this.crop];
    let stage, grow, cover;
    if (preview) { stage = 2; grow = 1; cover = 0.8; }
    else if (!w || !w.sown) { this.meshes.forEach((m) => (m.visible = false)); this.material.userData.droop.value = 0; this.key = "none"; return; }
    else if (w.done) { stage = 4; grow = 1; cover = 1; }
    else {
      const f = w.stage || 0;
      if (f < 0.03) { this.meshes.forEach((m) => (m.visible = false)); this.key = "seed"; return; }
      stage = f < 0.22 ? 0 : f < info.flower[0] - 0.02 ? 1 : f < info.flower[1] + 0.12 ? 2 : 3;
      const lo = [0.03, 0.22, info.flower[0] - 0.02, info.flower[1] + 0.12][stage], hi = [0.22, info.flower[0] - 0.02, info.flower[1] + 0.12, 1.05][stage];
      grow = 0.55 + 0.45 * Math.min(1, (f - lo) / Math.max(hi - lo, 0.01));
      cover = Math.min(1, (w.cc || 0) / 0.85);
    }
    const ksw = w ? (w.ksw ?? 1) : 1, pest = w ? (w.pest || 0) : 0, stand = w ? (w.stand ?? 1) : 1;
    const salt = w ? Math.max(0, ((w.ece_top || 0) - info.salt) / (info.salt * 2)) : 0;
    const heat = stage === 2 && tmax > info.heat ? Math.min(1, (tmax - info.heat) / 6) : 0;
    const key = [stage, grow.toFixed(2), cover.toFixed(2), ksw.toFixed(2), (pest * 100).toFixed(1), stand.toFixed(2), salt.toFixed(2), heat.toFixed(1)].join("|");
    this.material.userData.droop.value = preview ? 0 : Math.max(0, 1 - ksw) * 0.9;
    if (key === this.key) return;
    this.key = key;
    this.meshes.forEach((m, s) => (m.visible = s === stage));
    const im = this.meshes[stage];
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), p = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
    const healthy = new THREE.Color(1, 1, 1), dry = new THREE.Color(1.0, 0.86, 0.5), burn = new THREE.Color(0.92, 0.74, 0.5),
      bleach = new THREE.Color(1.05, 1.0, 0.82), pestC = new THREE.Color(0.62, 0.46, 0.28);
    const pestFrac = Math.min(0.9, pest * 25), c = new THREE.Color();
    const width = stage === 4 ? 1 : 0.55 + 0.45 * cover;
    this.layout.forEach((L, i) => {
      const alive = L.alive < stand;
      const hit = !preview && L.pest < pestFrac;
      const s = alive ? L.jit * (hit ? 0.75 : 1) : 0.0001;
      q.setFromAxisAngle(up, L.rot);
      m.compose(p.set(L.x, 0.02, L.z), q, sc.set(s * width, s * grow, s * width));
      im.setMatrixAt(i, m);
      c.copy(healthy).lerp(dry, (1 - ksw) * 1.2).lerp(burn, Math.min(1, salt)).lerp(bleach, heat * 0.6);
      if (hit) c.lerp(pestC, 0.75);
      c.multiplyScalar(0.92 + L.shade * 0.16);
      im.setColorAt(i, c);
    });
    im.instanceMatrix.needsUpdate = true;
    if (im.instanceColor) im.instanceColor.needsUpdate = true;
  }

  dispose() { this.clear(); this.material.dispose(); this.ghost.dispose(); }
}
