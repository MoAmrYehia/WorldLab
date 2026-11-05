// A small mesh builder for procedural plants: leaves, stems and blobs with vertex colours.
import * as THREE from "three";

const UP = new THREE.Vector3(0, 1, 0);

export class GeoBuilder {
  constructor() { this.pos = []; this.col = []; this.idx = []; }
  get count() { return this.pos.length / 3; }
  vert(p, c) { this.pos.push(p.x, p.y, p.z); this.col.push(c.r, c.g, c.b); return this.count - 1; }
  tri(a, b, c) { this.idx.push(a, b, c); }
  quad(a, b, c, d) { this.idx.push(a, b, c, a, c, d); }

  // A leaf along `dir`, bending under its own weight. shape: strap (grass), oval, heart, lance.
  leaf(origin, dir, length, width, { bend = 0.35, twist = 0, shape = "strap", seg = 5, base, tip, fold = 0.25 } = {}) {
    const d = dir.clone().normalize();
    let side = new THREE.Vector3().crossVectors(d, UP);
    if (side.lengthSq() < 1e-4) side.set(1, 0, 0);
    side.normalize().applyAxisAngle(d, twist);
    const up = new THREE.Vector3().crossVectors(side, d).normalize();
    const cb = base || new THREE.Color("#4f8a34"), ct = tip || cb;
    const rows = [];
    for (let i = 0; i <= seg; i++) {
      const t = i / seg;
      const p = origin.clone().addScaledVector(d, length * t).addScaledVector(UP, -bend * length * t * t);
      let w;
      if (shape === "strap") w = width * (1 - Math.pow(t, 2.2)) * (0.6 + 0.4 * Math.sin(Math.min(1, t * 3) * Math.PI / 2));
      else if (shape === "oval") w = width * Math.sin(Math.PI * Math.pow(t, 0.85));
      else if (shape === "heart") w = width * Math.sin(Math.PI * Math.pow(t, 0.7)) * (t < 0.15 ? 1.15 : 1);
      else w = width * Math.sin(Math.PI * t) * (1 - t * 0.3);                // lance
      const c = cb.clone().lerp(ct, t);
      const mid = p.clone().addScaledVector(up, fold * w * 0.5);
      rows.push([this.vert(p.clone().addScaledVector(side, -w / 2), c), this.vert(mid, c), this.vert(p.clone().addScaledVector(side, w / 2), c)]);
    }
    for (let i = 0; i < seg; i++) {
      const [a0, m0, b0] = rows[i], [a1, m1, b1] = rows[i + 1];
      this.quad(a0, a1, m1, m0); this.quad(m0, m1, b1, b0);
    }
    return origin.clone().addScaledVector(d, length).addScaledVector(UP, -bend * length);
  }

  // A tube through points.
  stem(points, r0, r1, color, sides = 5) {
    const rings = [];
    for (let i = 0; i < points.length; i++) {
      const t = i / (points.length - 1), r = r0 + (r1 - r0) * t;
      const p = points[i];
      const d = (i < points.length - 1 ? points[i + 1].clone().sub(p) : p.clone().sub(points[i - 1])).normalize();
      let a = new THREE.Vector3().crossVectors(d, UP); if (a.lengthSq() < 1e-4) a.set(1, 0, 0); a.normalize();
      const b = new THREE.Vector3().crossVectors(a, d).normalize();
      const ring = [];
      for (let k = 0; k < sides; k++) {
        const ang = (k / sides) * Math.PI * 2;
        ring.push(this.vert(p.clone().addScaledVector(a, Math.cos(ang) * r).addScaledVector(b, Math.sin(ang) * r), color));
      }
      rings.push(ring);
    }
    for (let i = 0; i < rings.length - 1; i++) for (let k = 0; k < sides; k++) {
      const k2 = (k + 1) % sides;
      this.quad(rings[i][k], rings[i + 1][k], rings[i + 1][k2], rings[i][k2]);
    }
  }

  // A lumpy ball (fruit, tuber, flower cluster, canopy clump).
  blob(center, radius, color, { sy = 1, detail = 0, jitter = 0.15, seed = 1 } = {}) {
    const g = new THREE.IcosahedronGeometry(radius, detail).toNonIndexed();
    const p = g.attributes.position;
    const start = this.count;
    for (let i = 0; i < p.count; i++) {
      const v = new THREE.Vector3().fromBufferAttribute(p, i);
      const k = 1 + (Math.sin(v.x * 12.9 + seed) * Math.sin(v.y * 7.3 + seed * 2) * Math.sin(v.z * 9.1)) * jitter;
      v.multiplyScalar(k); v.y *= sy;
      this.vert(v.add(center), color);
    }
    for (let i = 0; i < p.count; i += 3) this.tri(start + i, start + i + 1, start + i + 2);
    g.dispose();
  }

  // A cylinder segment (spike, cob, tank detail) from a to b.
  rod(a, b, r, color, sides = 6, r2 = r) { this.stem([a, b], r, r2, color, sides); }

  build() {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.pos, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(this.col, 3));
    g.setIndex(this.idx);
    g.computeVertexNormals();
    g.computeBoundingSphere();
    return g;
  }
}

export const V = (x, y, z) => new THREE.Vector3(x, y, z);
export const C = (h) => new THREE.Color(h);

// deterministic pseudo random for geometry variety
export function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
}

export function polar(r, a, y = 0) { return V(Math.cos(a) * r, y, Math.sin(a) * r); }
