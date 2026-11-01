// Native and planted vegetation around the farm: date palms, ghaf trees, desert shrubs and grass.
import * as THREE from "three";
import { GeoBuilder, V, C, rng, polar } from "./geo.js?v=f3621d8e7e";
import { heightAt, FARM } from "./terrain.js?v=f3621d8e7e";

// --------------------------------------------------------------- date palm (Phoenix dactylifera)
function palmCrown(seed) {
  const r = rng(seed), b = new GeoBuilder();
  const green = C("#5d8a3a"), dark = C("#3f6b2c"), tipY = C("#a3a457"), rachis = C("#7d7a3f");
  const fronds = 20 + Math.floor(r() * 6);
  for (let f = 0; f < fronds; f++) {
    const a = (f / fronds) * Math.PI * 2 + r() * 0.3;
    const tier = f % 3;
    const elev = 0.95 - tier * 0.32 + r() * 0.15;           // young fronds up, old ones down
    const L = 2.6 + r() * 0.8;
    const dir = V(Math.cos(a) * Math.cos(elev), Math.sin(elev), Math.sin(a) * Math.cos(elev));
    const side = new THREE.Vector3().crossVectors(dir, V(0, 1, 0)).normalize();
    const pts = [];
    for (let i = 0; i <= 8; i++) { const t = i / 8; pts.push(dir.clone().multiplyScalar(L * t).add(V(0, -0.55 * L * t * t * (1.1 - elev * 0.5), 0))); }
    b.stem(pts, 0.05, 0.015, rachis, 4);
    for (let i = 1; i < 8; i++) {
      const t = i / 8, p = pts[i];
      const seg = pts[i + 1].clone().sub(p).normalize();
      const len = 0.55 * Math.sin(Math.PI * (0.15 + t * 0.85)) + 0.12;
      for (const s of [-1, 1]) {
        for (const k of [0, 0.5]) {
          const q = p.clone().lerp(pts[i + 1], k);
          const ld = seg.clone().multiplyScalar(0.55).addScaledVector(side, s).add(V(0, 0.35, 0)).normalize();
          b.leaf(q, ld, len, 0.07, { bend: 0.25, shape: "lance", seg: 2, base: (f + i) % 2 ? green : dark, tip: tipY, fold: 0 });
        }
      }
    }
  }
  // skirt of dry fronds and two clusters of dates
  const dry = C("#8a6a3e");
  for (let f = 0; f < 7; f++) {
    const a = r() * Math.PI * 2, d = V(Math.cos(a) * 0.35, -1, Math.sin(a) * 0.35).normalize();
    b.leaf(V(0, -0.05, 0), d, 1.6 + r() * 0.5, 0.25, { bend: -0.05, shape: "lance", seg: 3, base: dry, tip: C("#6b5030") });
  }
  for (let k = 0; k < 3; k++) {
    const a = r() * Math.PI * 2, c = polar(0.45, a, -0.45);
    for (let j = 0; j < 9; j++) b.blob(c.clone().add(V((r() - 0.5) * 0.3, -r() * 0.4, (r() - 0.5) * 0.3)), 0.08, C(r() > 0.5 ? "#c8732a" : "#a5521f"), { detail: 0 });
  }
  return b.build();
}

function palmTrunk(H) {
  const g = new THREE.CylinderGeometry(0.28, 0.4, H, 12, 14, true);
  g.translate(0, H / 2, 0);
  const p = g.attributes.position, uv = g.attributes.uv;
  for (let i = 0; i < p.count; i++) {
    const y = p.getY(i), t = y / H;
    p.setX(i, p.getX(i) + 0.35 * t * t);
    uv.setXY(i, uv.getX(i) * 2, uv.getY(i) * H / 1.4);
  }
  g.computeVertexNormals();
  return g;
}

// --------------------------------------------------------------- ghaf tree (Prosopis cineraria), the UAE's national tree
function ghafTree(seed) {
  const r = rng(seed), b = new GeoBuilder();
  const bark = C("#5c4a3a"), leafA = C("#7d9a5a"), leafB = C("#93a86b"), leafC = C("#6a8a4c");
  b.stem([V(0, 0, 0), V(0.1, 1.2, 0), V(0.25, 2.2, 0.1)], 0.32, 0.2, bark, 7);
  const tips = [];
  for (let k = 0; k < 5; k++) {
    const a = (k / 5) * Math.PI * 2 + r(), L = 1.8 + r() * 1.2;
    const end = V(0.25 + Math.cos(a) * L, 2.2 + 1.2 + r() * 0.8, 0.1 + Math.sin(a) * L);
    b.stem([V(0.25, 2.2, 0.1), V(0.25 + Math.cos(a) * L * 0.5, 3.0, 0.1 + Math.sin(a) * L * 0.5), end], 0.17, 0.06, bark, 5);
    tips.push(end);
  }
  for (let k = 0; k < 46; k++) {
    const t = tips[k % tips.length];
    const c = t.clone().add(V((r() - 0.5) * 2.4, (r() - 0.6) * 1.4, (r() - 0.5) * 2.4));
    b.blob(c, 0.55 + r() * 0.45, [leafA, leafB, leafC][k % 3], { sy: 0.7, detail: 1, jitter: 0.3, seed: k });
  }
  return b.build();
}

function shrub(seed) {
  const r = rng(seed), b = new GeoBuilder();
  const cols = [C("#8f9a6a"), C("#7c8a5a"), C("#a2a77a")];
  for (let k = 0; k < 7; k++) b.blob(V((r() - 0.5) * 0.9, 0.25 + r() * 0.35, (r() - 0.5) * 0.9), 0.3 + r() * 0.25, cols[k % 3], { sy: 0.8, detail: 1, jitter: 0.35, seed: k });
  return b.build();
}

function grassTuft(seed) {
  const r = rng(seed), b = new GeoBuilder();
  for (let k = 0; k < 9; k++) {
    const a = r() * Math.PI * 2;
    b.leaf(V(0, 0, 0), V(Math.cos(a) * 0.35, 1, Math.sin(a) * 0.35), 0.5 + r() * 0.35, 0.04, { bend: 0.4, seg: 3, base: C("#b5a96a"), tip: C("#d8c98e"), fold: 0 });
  }
  return b.build();
}

// --------------------------------------------------------------- placement
function scatter(n, rMin, rMax, seed, keepOut) {
  const r = rng(seed), out = [];
  let tries = 0;
  while (out.length < n && tries < n * 30) {
    tries++;
    const a = r() * Math.PI * 2, d = rMin + Math.sqrt(r()) * (rMax - rMin);
    const x = Math.cos(a) * d * 1.25 - 10, z = Math.sin(a) * d - 6;
    if (keepOut(x, z)) continue;
    out.push([x, z, r()]);
  }
  return out;
}
const inFarm = (x, z, pad = 4) => x > FARM.x0 - pad && x < FARM.x1 + pad && z > FARM.z0 - pad && z < FARM.z1 + pad;

export function buildFlora(tex, quality, lights) {
  const group = new THREE.Group();
  const Q = { low: 0.35, medium: 0.6, high: 1, ultra: 1.6 }[quality] || 1;
  const leafMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, side: THREE.DoubleSide });
  const bark = tex.bark.clone(); bark.needsUpdate = true;
  const barkMat = new THREE.MeshStandardMaterial({ map: bark, normalMap: tex.barkN, roughness: 0.95, color: "#d9c3a5" });
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3();

  // date palms: windbreaks along the north and west edges, a grove by the buildings, scattered oases
  const spots = [];
  for (let x = FARM.x0 + 2; x <= FARM.x1 - 2; x += 4.4) spots.push([x, FARM.z0 - 3.5]);
  for (let z = FARM.z0 + 2; z <= FARM.z1 - 2; z += 4.6) spots.push([FARM.x0 - 3.5, z]);
  for (let k = 0; k < 14; k++) spots.push([-58 + (k % 4) * 4.2 + (k % 2), 28 + Math.floor(k / 4) * 4.5]);
  scatter(Math.round(26 * Q), 90, 320, 5, (x, z) => inFarm(x, z, 20)).forEach(([x, z]) => spots.push([x, z]));
  const H = 7;
  const trunks = new THREE.InstancedMesh(palmTrunk(H), barkMat, spots.length);
  const crowns = [palmCrown(11), palmCrown(23)].map((g) => new THREE.InstancedMesh(g, leafMat, spots.length));
  const counts = [0, 0];
  spots.forEach(([x, z], i) => {
    const sc = 0.85 + ((i * 37) % 10) / 22, rot = (i * 2.399) % (Math.PI * 2);
    const y = heightAt(x, z);
    q.setFromAxisAngle(V(0, 1, 0), rot);
    m.compose(v.set(x, y - 0.1, z), q, s.set(sc, sc, sc));
    trunks.setMatrixAt(i, m);
    const top = V(0.35 * sc, H * sc - 0.05, 0).applyQuaternion(q).add(v.set(x, y - 0.1, z));
    m.compose(top, q, s.set(sc, sc, sc));
    const k = i % 2; crowns[k].setMatrixAt(counts[k]++, m);
  });
  crowns.forEach((c, k) => { c.count = counts[k]; });
  [trunks, ...crowns].forEach((x) => { x.castShadow = true; x.receiveShadow = true; group.add(x); });

  // ghaf trees on the dunes and near the entrance
  const ghafSpots = scatter(Math.round(22 * Q), 60, 240, 9, (x, z) => inFarm(x, z, 10));
  ghafSpots.push([50, 12, 0.5], [46, -30, 0.3]);
  const ghaf = new THREE.InstancedMesh(ghafTree(31), leafMat, ghafSpots.length);
  ghafSpots.forEach(([x, z, r], i) => {
    const sc = 0.8 + r * 0.6; q.setFromAxisAngle(V(0, 1, 0), r * 6.28);
    m.compose(v.set(x, heightAt(x, z) - 0.1, z), q, s.set(sc, sc, sc)); ghaf.setMatrixAt(i, m);
  });
  ghaf.castShadow = true; ghaf.receiveShadow = true; group.add(ghaf);

  // shrubs and grass tufts
  const shrubSpots = scatter(Math.round(220 * Q), 46, 300, 13, (x, z) => inFarm(x, z, 3));
  const sh = new THREE.InstancedMesh(shrub(41), leafMat, shrubSpots.length);
  shrubSpots.forEach(([x, z, r], i) => {
    const sc = 0.6 + r * 1.1; q.setFromAxisAngle(V(0, 1, 0), r * 6.28);
    m.compose(v.set(x, heightAt(x, z) - 0.05, z), q, s.set(sc, sc * (0.8 + r * 0.4), sc)); sh.setMatrixAt(i, m);
  });
  sh.castShadow = quality !== "low"; sh.receiveShadow = true; group.add(sh);
  const grassSpots = scatter(Math.round(900 * Q), 44, 260, 17, (x, z) => inFarm(x, z, 2));
  const gr = new THREE.InstancedMesh(grassTuft(51), leafMat, grassSpots.length);
  grassSpots.forEach(([x, z, r], i) => {
    const sc = 0.6 + r * 0.9; q.setFromAxisAngle(V(0, 1, 0), r * 6.28);
    m.compose(v.set(x, heightAt(x, z) - 0.02, z), q, s.set(sc, sc, sc)); gr.setMatrixAt(i, m);
  });
  gr.receiveShadow = true; group.add(gr);
  return group;
}
