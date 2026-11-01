// Desert terrain near Al Ain: a levelled farm, dunes beyond, and the Jebel Hafeet ridge on the horizon.
import * as THREE from "three";
import { fbm2, ridged, noise2 } from "./textures.js?v=3481ce85d1";

export const FARM = { x0: -62, x1: 40, z0: -42, z1: 30 };     // levelled farm area (scene units ~ 6 m)

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

// distance outside the farm rectangle (0 inside)
function outside(x, z) {
  const dx = Math.max(FARM.x0 - x, 0, x - FARM.x1), dz = Math.max(FARM.z0 - z, 0, z - FARM.z1);
  return Math.hypot(dx, dz);
}

export function heightAt(x, z) {
  const d = outside(x, z);
  const flat = (noise2(x * 0.05, z * 0.05, 5) - 0.5) * 0.12;
  if (d <= 0) return flat - 0.02;
  const m = smooth(4, 70, d);
  const wx = x + fbm2(x * 0.004, z * 0.004, 3, 7) * 120, wz = z + fbm2(z * 0.004, x * 0.004, 3, 8) * 120;
  const dune = Math.pow(ridged(wx * 0.006, wz * 0.0105, 4, 11), 1.7) * 26;
  const swell = fbm2(x * 0.003, z * 0.003, 3, 13) * 14;
  return flat + m * (dune + swell) - m * 2;
}

export function buildTerrain(tex, quality) {
  const group = new THREE.Group();
  const seg = { low: 140, medium: 210, high: 280, ultra: 360 }[quality] || 280;
  const size = 1800;
  const g = new THREE.PlaneGeometry(size, size, seg, seg);
  g.rotateX(-Math.PI / 2);
  const pos = g.attributes.position;
  const col = new Float32Array(pos.count * 3);
  const cLow = new THREE.Color("#c99a68"), cHigh = new THREE.Color("#e8c99a"), cRed = new THREE.Color("#c4805a");
  const c = new THREE.Color();
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), z = pos.getZ(i);
    // finer resolution where it matters: pull vertices towards the centre
    const h = heightAt(x, z);
    pos.setY(i, h);
    const t = Math.min(1, Math.max(0, h / 22));
    c.copy(cLow).lerp(cHigh, t * 0.8 + 0.1).lerp(cRed, fbm2(x * 0.01, z * 0.01, 3, 17) * 0.35);
    col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
  }
  g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  g.computeVertexNormals();
  const sand = tex.sand.clone(); sand.needsUpdate = true; sand.repeat.set(size / 9, size / 9);
  const sandN = tex.sandN.clone(); sandN.needsUpdate = true; sandN.repeat.copy(sand.repeat);
  const ground = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ map: sand, normalMap: sandN, normalScale: new THREE.Vector2(0.55, 0.55),
    vertexColors: true, roughness: 0.96, metalness: 0 }));
  ground.receiveShadow = true;
  ground.name = "terrain";
  group.add(ground);

  // compacted farm pad and roads
  const soilTex = tex.gravel.clone(); soilTex.needsUpdate = true; soilTex.repeat.set(30, 22);
  const pad = new THREE.Mesh(new THREE.PlaneGeometry(FARM.x1 - FARM.x0 + 6, FARM.z1 - FARM.z0 + 6),
    new THREE.MeshStandardMaterial({ color: "#d7b98f", map: soilTex, roughness: 1, metalness: 0 }));
  pad.rotation.x = -Math.PI / 2;
  pad.position.set((FARM.x0 + FARM.x1) / 2, 0.005, (FARM.z0 + FARM.z1) / 2);
  pad.receiveShadow = true;
  group.add(pad);

  const gravel = tex.gravel.clone(); gravel.needsUpdate = true;
  const gravelN = tex.gravelN.clone(); gravelN.needsUpdate = true;
  const roadMat = new THREE.MeshStandardMaterial({ color: "#bfa889", map: gravel, normalMap: gravelN, roughness: 0.95 });
  const road = (x0, z0, x1, z1, w) => {
    const len = Math.hypot(x1 - x0, z1 - z0);
    const geo = new THREE.PlaneGeometry(len, w, 1, 1);
    const uv = geo.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * len / 3, uv.getY(i) * w / 3);
    const m = new THREE.Mesh(geo, roadMat);
    m.rotation.x = -Math.PI / 2; m.rotation.z = -Math.atan2(z1 - z0, x1 - x0);
    m.position.set((x0 + x1) / 2, 0.03, (z0 + z1) / 2);
    m.receiveShadow = true;
    group.add(m);
  };
  // ring road, field lanes, access road to the highway
  road(-52, -37, 34, -37, 3.2); road(-52, 23, 34, 23, 3.2); road(-52, -37, -52, 23, 3.2); road(34, -37, 34, 23, 3.2);
  road(-29, -18, 29, -18, 2.2); road(-29, 17, 29, 17, 2.2); road(-29, 0, 29, 0, 2.6);
  road(-9, -14, -9, 14, 2.0); road(9, -14, 9, 14, 2.0); road(-29, -18, -29, 17, 2.2); road(29, -18, 29, 17, 2.2);
  road(34, 8, 240, 30, 4.5);

  group.add(buildMountains(tex, quality));
  group.add(buildRocks(tex, quality));
  return group;
}

// The Jebel Hafeet ridge: a long limestone massif rising south-east of Al Ain, seen here on the horizon.
function buildMountains(tex, quality) {
  const group = new THREE.Group();
  const seg = { low: 120, medium: 170, high: 220, ultra: 280 }[quality] || 220;
  const ridge = (cx, cz, len, width, height, rot, seed) => {
    const g = new THREE.PlaneGeometry(len, width, seg, Math.round(seg / 3));
    g.rotateX(-Math.PI / 2);
    const pos = g.attributes.position;
    const col = new Float32Array(pos.count * 3), c = new THREE.Color();
    const base = new THREE.Color("#a77c5a"), top = new THREE.Color("#c8ab8c"), shadow = new THREE.Color("#7d5d46");
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), z = pos.getZ(i);
      const across = 1 - Math.pow(Math.abs(z) / (width / 2), 1.6);
      const along = Math.pow(Math.sin(Math.PI * (x / len + 0.5)), 0.6);
      const r = ridged(x * 0.006 + seed, z * 0.012, 6, 30 + seed);
      const h = Math.max(0, across) * along * (0.35 + r * 0.9) * height;
      pos.setY(i, h);
      const strata = Math.sin(h * 0.25 + fbm2(x * 0.02, z * 0.02, 2, seed) * 3) * 0.5 + 0.5;
      c.copy(base).lerp(top, Math.min(1, h / height)).lerp(shadow, strata * 0.25);
      col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b;
    }
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    g.computeVertexNormals();
    const rock = tex.rock.clone(); rock.needsUpdate = true; rock.repeat.set(len / 40, width / 40);
    const rockN = tex.rockN.clone(); rockN.needsUpdate = true; rockN.repeat.copy(rock.repeat);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ map: rock, normalMap: rockN, vertexColors: true, roughness: 0.92 }));
    m.position.set(cx, -2, cz); m.rotation.y = rot;
    group.add(m);
  };
  ridge(-120, -760, 1500, 360, 210, 0.12, 2);      // Jebel Hafeet, the long ridge
  ridge(620, -520, 700, 260, 120, 0.9, 5);         // lower outliers to the east
  ridge(-700, -420, 600, 240, 95, -0.7, 8);
  return group;
}

function buildRocks(tex, quality) {
  const n = { low: 40, medium: 90, high: 160, ultra: 260 }[quality] || 160;
  const g = new THREE.IcosahedronGeometry(1, 2);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const v = new THREE.Vector3().fromBufferAttribute(p, i);
    const k = 0.75 + noise2(v.x * 2.1 + 3, v.y * 2.1 + v.z * 1.7, 77) * 0.5;
    v.multiplyScalar(k); v.y *= 0.62;
    p.setXYZ(i, v.x, v.y, v.z);
  }
  g.computeVertexNormals();
  const rock = tex.rock.clone(); rock.needsUpdate = true;
  const im = new THREE.InstancedMesh(g, new THREE.MeshStandardMaterial({ map: rock, normalMap: tex.rockN, color: "#c9a27e", roughness: 0.9 }), n);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3();
  let k = 0, tries = 0;
  while (k < n && tries < n * 20) {
    tries++;
    const a = noise2(tries * 0.37, 1.3, 91) * Math.PI * 2 + tries, r = 70 + noise2(tries * 0.71, 2.9, 93) * 260;
    const x = Math.cos(a) * r * 1.2 - 10, z = Math.sin(a) * r - 6;
    if (outside(x, z) < 6) continue;
    const sc = 0.6 + Math.pow(noise2(tries * 1.3, 4.1, 97), 3) * 5;
    q.setFromEuler(new THREE.Euler(0, a * 3, (noise2(tries, 7, 3) - 0.5) * 0.4));
    m.compose(v.set(x, heightAt(x, z) - sc * 0.15, z), q, s.set(sc * 1.3, sc, sc));
    im.setMatrixAt(k++, m);
  }
  im.count = k;
  im.castShadow = true; im.receiveShadow = true;
  return im;
}
