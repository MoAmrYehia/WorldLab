// Moving things: the inspection drone, dust and rain, clouds, the service truck, and event markers.
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { V } from "./geo.js?v=01ca7ed07b";
import { DEPOT, FIELD_POS, PLOT_D } from "./farm.js?v=01ca7ed07b";

// --------------------------------------------------------------- drone
export function buildDrone(tex) {
  const d = new THREE.Group();
  const shell = new THREE.MeshStandardMaterial({ color: "#eef0f2", roughness: 0.35, metalness: 0.2 });
  const carbon = new THREE.MeshStandardMaterial({ color: "#23272b", roughness: 0.5, metalness: 0.4 });
  const body = new THREE.Mesh(new THREE.SphereGeometry(0.45, 16, 10), shell); body.scale.set(1.3, 0.45, 1); d.add(body);
  const props = [];
  for (const [x, z] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
    const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 1.3, 6), carbon);
    arm.rotation.z = Math.PI / 2; arm.rotation.y = Math.atan2(z, x); arm.position.set(x * 0.45, 0.02, z * 0.45); d.add(arm);
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.14, 10), carbon); motor.position.set(x * 0.9, 0.08, z * 0.9); d.add(motor);
    const prop = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.012, 0.07), new THREE.MeshStandardMaterial({ color: "#111", transparent: true, opacity: 0.75 }));
    prop.position.set(x * 0.9, 0.17, z * 0.9); d.add(prop); props.push(prop);
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.035, 6, 4), new THREE.MeshBasicMaterial({ color: z > 0 ? "#ff3b3b" : "#3bff7a" }));
    led.position.set(x * 0.9, 0.0, z * 0.9); d.add(led);
  }
  const gimbal = new THREE.Mesh(new THREE.SphereGeometry(0.13, 10, 8), carbon); gimbal.position.set(0, -0.22, 0.25); d.add(gimbal);
  const lens = new THREE.Mesh(new THREE.CircleGeometry(0.06, 12), new THREE.MeshStandardMaterial({ color: "#0c1a24", emissive: new THREE.Color("#3cf0ff"), emissiveIntensity: 0.6 }));
  lens.position.set(0, -0.22, 0.38); d.add(lens);
  const cone = new THREE.Mesh(new THREE.ConeGeometry(4.2, 8, 32, 1, true), new THREE.MeshBasicMaterial({ color: "#59f0b0", transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
  cone.position.y = -4.2; d.add(cone);
  d.traverse((o) => { if (o.isMesh && o !== cone) o.castShadow = true; });
  d.scale.setScalar(1.15);
  d.userData = { props, cone, target: V(-40, 9, -6), scanUntil: 0, homeAt: 0 };
  d.position.set(-40, 9, -6);
  return d;
}

// --------------------------------------------------------------- dust and rain
export function buildDust(tex, count) {
  const g = new THREE.BufferGeometry();
  const p = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) { p[i * 3] = (Math.random() - 0.5) * 200; p[i * 3 + 1] = Math.random() * 18; p[i * 3 + 2] = (Math.random() - 0.5) * 140; }
  g.setAttribute("position", new THREE.BufferAttribute(p, 3));
  const m = new THREE.PointsMaterial({ map: tex.dust, color: "#e8cfa8", size: 0.55, transparent: true, opacity: 0.35, depthWrite: false, sizeAttenuation: true });
  const pts = new THREE.Points(g, m); pts.frustumCulled = false;
  return pts;
}
export function buildRain(count) {
  const g = new THREE.BufferGeometry();
  const p = new Float32Array(count * 6);
  for (let i = 0; i < count; i++) {
    const x = (Math.random() - 0.5) * 160, y = Math.random() * 40, z = (Math.random() - 0.5) * 120;
    p.set([x, y, z, x + 0.15, y - 0.9, z], i * 6);
  }
  g.setAttribute("position", new THREE.BufferAttribute(p, 3));
  const r = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: "#b8c7d6", transparent: true, opacity: 0 }));
  r.frustumCulled = false; r.visible = false;
  return r;
}
export function buildClouds(tex) {
  const g = new THREE.Group();
  for (let k = 0; k < 14; k++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex.cloud, color: "#ffffff", transparent: true, opacity: 0, depthWrite: false, fog: false }));
    const a = (k / 14) * Math.PI * 2, r = 260 + (k % 4) * 90;
    s.position.set(Math.cos(a) * r, 120 + (k % 3) * 30, Math.sin(a) * r - 120);
    s.scale.set(180 + (k % 5) * 40, 60 + (k % 3) * 18, 1);
    g.add(s);
  }
  return g;
}

// --------------------------------------------------------------- event markers floating over fields
export class Markers {
  constructor(root) { this.root = root; this.items = []; }
  add(i, icon, text, life = 6) {
    const el = document.createElement("div");
    el.className = `fmark fmark-${icon}`;
    el.innerHTML = `<span class="fm-ic" aria-hidden="true"></span><span>${text}</span>`;
    const o = new CSS2DObject(el);
    const [x, z] = i >= 0 ? FIELD_POS[i] : [-30, 32];
    o.position.set(x, 7, z);
    this.root.add(o);
    this.items.push({ o, el, t: 0, life });
  }
  tick(dt) {
    this.items = this.items.filter((m) => {
      m.t += dt;
      m.o.position.y += dt * 0.15;
      m.el.style.opacity = String(Math.max(0, Math.min(1, m.t * 3, (m.life - m.t) * 1.5)));
      if (m.t > m.life) { this.root.remove(m.o); m.el.remove(); return false; }
      return true;
    });
  }
  clear() { this.items.forEach((m) => { this.root.remove(m.o); m.el.remove(); }); this.items = []; }
}

// An expanding ring across the farm when the scientist corrects its model.
export class Pulse {
  constructor(root) {
    this.mesh = new THREE.Mesh(new THREE.RingGeometry(0.96, 1, 96), new THREE.MeshBasicMaterial({ color: "#5ef0d0", transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    this.mesh.rotation.x = -Math.PI / 2; this.mesh.position.set(0, 0.5, 0); root.add(this.mesh); this.t = 2;
  }
  fire(x = 0, z = 0) { this.t = 0; this.mesh.position.set(x, 0.5, z); }
  tick(dt) {
    if (this.t > 1.8) { this.mesh.material.opacity = 0; return; }
    this.t += dt;
    const s = 2 + this.t * 45; this.mesh.scale.set(s, s, s);
    this.mesh.material.opacity = Math.max(0, 0.7 * (1 - this.t / 1.8));
  }
}

// --------------------------------------------------------------- service truck route: depot -> ring road -> field lane
export class TruckRun {
  constructor(truck, onArrive) { this.truck = truck; this.onArrive = onArrive; this.path = null; this.t = 0; }
  go(i) {
    const [fx, fz] = FIELD_POS[i];
    const lane = fz < 0 ? -18 : 17;
    const pts = [DEPOT.clone(), V(-52, 0, 14), V(-52, 0, lane), V(fx - 9, 0, lane), V(fx, 0, lane + (fz < 0 ? 1.2 : -1.2))];
    this.path = new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.2);
    this.back = new THREE.CatmullRomCurve3([...pts].reverse(), false, "centripetal", 0.2);
    this.leg = "out"; this.t = 0; this.field = i; this.wait = 0;
  }
  tick(dt) {
    if (!this.path) return;
    const curve = this.leg === "out" ? this.path : this.back;
    if (this.leg === "work") {
      this.wait += dt;
      this.truck.userData.beacon.material.emissiveIntensity = 1 + Math.sin(this.wait * 10);
      if (this.wait > 2.5) { this.leg = "back"; this.t = 0; }
      return;
    }
    const L = curve.getLength();
    this.t = Math.min(1, this.t + (dt * 9) / L);
    const p = curve.getPointAt(this.t), a = curve.getTangentAt(this.t);
    this.truck.position.set(p.x, 0.05, p.z);
    this.truck.rotation.y = Math.atan2(-a.z, a.x);
    this.truck.userData.beacon.material.emissiveIntensity = 0.8 + Math.sin(performance.now() / 120) * 0.6;
    if (this.t >= 1) {
      if (this.leg === "out") { this.leg = "work"; this.wait = 0; this.onArrive && this.onArrive(this.field); }
      else { this.path = null; this.truck.userData.beacon.material.emissiveIntensity = 0; }
    }
  }
}

// --------------------------------------------------------------- harvest dust over a field
export class HarvestBurst {
  constructor(root, tex) {
    const n = 220, g = new THREE.BufferGeometry();
    this.base = new Float32Array(n * 3); this.vel = new Float32Array(n * 3);
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    this.pts = new THREE.Points(g, new THREE.PointsMaterial({ map: tex.dust, color: "#f2d38a", size: 0.5, transparent: true, opacity: 0, depthWrite: false }));
    this.pts.frustumCulled = false; root.add(this.pts); this.t = 9; this.n = n;
  }
  fire(i) {
    const [fx, fz] = FIELD_POS[i], p = this.pts.geometry.attributes.position;
    for (let k = 0; k < this.n; k++) {
      p.setXYZ(k, fx + (Math.random() - 0.5) * 14, 0.4 + Math.random() * 0.8, fz + (Math.random() - 0.5) * (PLOT_D - 1));
      this.vel.set([(Math.random() - 0.5) * 0.6, 0.6 + Math.random() * 1.2, (Math.random() - 0.5) * 0.6], k * 3);
    }
    p.needsUpdate = true; this.t = 0;
  }
  tick(dt) {
    if (this.t > 3) { this.pts.material.opacity = 0; return; }
    this.t += dt;
    const p = this.pts.geometry.attributes.position;
    for (let k = 0; k < this.n; k++) p.setXYZ(k, p.getX(k) + this.vel[k * 3] * dt, p.getY(k) + this.vel[k * 3 + 1] * dt, p.getZ(k) + this.vel[k * 3 + 2] * dt);
    p.needsUpdate = true;
    this.pts.material.opacity = 0.8 * (1 - this.t / 3);
  }
}
