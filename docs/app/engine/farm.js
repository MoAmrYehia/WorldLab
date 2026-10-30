// The six fields (soil, drip irrigation, crops, labels) and the farm's infrastructure.
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { FieldCrop, CROP_INFO } from "./crops.js?v=3e51a05a34";
import { GeoBuilder, V, C } from "./geo.js?v=3e51a05a34";

export const PLOT_W = 15, PLOT_D = 10;
export const FIELD_POS = [[-18, -7.5], [0, -7.5], [18, -7.5], [-18, 7.5], [0, 7.5], [18, 7.5]];
export const FIELD_NAMES = ["North", "Palm edge", "Dune", "Old wadi", "Loam block", "Sabkha rim"];
export const DEPOT = new THREE.Vector3(-44, 0, 14);          // maintenance yard by the pump station
const LINES = 12;                                               // drip laterals per field

// Overlay colour ramps: sequential, light to dark, with units the UI legend repeats.
export const OVERLAYS = {
  health: { label: "Canopy vs model", unit: "%", lo: 50, hi: 110, ramp: ["#f3e7c6", "#9fd28a", "#2f8f5b", "#0f5132"] },
  moisture: { label: "Soil moisture, 0–50 cm", unit: "m³/m³", lo: 0.04, hi: 0.3, ramp: ["#f0e6d2", "#9fd3e6", "#3b8fc4", "#163f7a"] },
  salinity: { label: "Soil salinity, 0–50 cm", unit: "dS/m", lo: 1, hi: 12, ramp: ["#fdf3d8", "#f6c76b", "#d9772e", "#8c2d17"] },
  water: { label: "Irrigation applied today", unit: "mm", lo: 0, hi: 12, ramp: ["#eef6f6", "#9ee0e4", "#2bb3c2", "#0b6b86"] },
};
export function rampColor(key, v) {
  const o = OVERLAYS[key];
  const t = Math.min(1, Math.max(0, (v - o.lo) / (o.hi - o.lo))) * (o.ramp.length - 1);
  const i = Math.min(o.ramp.length - 2, Math.floor(t));
  return new THREE.Color(o.ramp[i]).lerp(new THREE.Color(o.ramp[i + 1]), t - i);
}

// --------------------------------------------------------------- soil with moisture, salt crust and emitter wet spots
function soilMaterial(tex) {
  const map = tex.soil.clone(); map.needsUpdate = true; map.repeat.set(3, 2);
  const nm = tex.soilN.clone(); nm.needsUpdate = true; nm.repeat.copy(map.repeat);
  const m = new THREE.MeshStandardMaterial({ map, normalMap: nm, normalScale: new THREE.Vector2(1.2, 1.2), roughness: 0.95, color: "#ffffff" });
  const u = { uWet: { value: 0.2 }, uSalt: { value: 0 }, uSpot: { value: 0 }, uDeliver: { value: 1 }, uOv: { value: new THREE.Vector4(0, 0, 0, 0) } };
  m.userData.u = u;
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, u);
    sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nvarying vec2 vLocal;")
      .replace("#include <uv_vertex>", "#include <uv_vertex>\nvLocal = uv;");
    sh.fragmentShader = sh.fragmentShader.replace("#include <common>", `#include <common>
      varying vec2 vLocal; uniform float uWet; uniform float uSalt; uniform float uSpot; uniform float uDeliver; uniform vec4 uOv;
      float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float vn(vec2 p){ vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
        return mix(mix(h21(i),h21(i+vec2(1,0)),f.x), mix(h21(i+vec2(0,1)),h21(i+vec2(1,1)),f.x), f.y); }`)
      .replace("#include <map_fragment>", `#include <map_fragment>
        vec2 lp = vLocal * vec2(${PLOT_W.toFixed(1)}, ${PLOT_D.toFixed(1)});
        float lx = (lp.x - 0.6) / ${((PLOT_W - 1.2) / (LINES - 1)).toFixed(4)};
        float dl = abs(fract(lx + 0.5) - 0.5) * ${((PLOT_W - 1.2) / (LINES - 1)).toFixed(4)};
        float de = abs(fract(lp.y / 0.45 + 0.5) - 0.5) * 0.45;
        float spot = 1.0 - smoothstep(0.0, uSpot * uDeliver * 0.42 + 0.001, length(vec2(dl, de * 1.4)));
        float stripe = 1.0 - smoothstep(0.0, 0.18 + uSpot * uDeliver * 0.25, dl);
        float wet = clamp(uWet * 0.75 + spot * 0.8 + stripe * uWet * 0.35, 0.0, 1.0);
        diffuseColor.rgb *= mix(1.0, 0.5, wet);
        float n = vn(lp * 3.1) * 0.6 + vn(lp * 11.0) * 0.4;
        float crust = smoothstep(1.0 - uSalt, 1.0 - uSalt + 0.18, n) * (1.0 - spot * 0.7);
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.93, 0.92, 0.88), crust * 0.85);
        float cracks = (1.0 - uWet) * smoothstep(0.47, 0.5, abs(vn(lp * 5.0) - 0.5) + 0.48) * (1.0 - spot);
        diffuseColor.rgb *= 1.0 - cracks * 0.25;
        diffuseColor.rgb = mix(diffuseColor.rgb, uOv.rgb, uOv.a);`)
      .replace("#include <roughnessmap_fragment>", `#include <roughnessmap_fragment>
        roughnessFactor = mix(roughnessFactor, 0.45, wet * 0.8);`);
  };
  m.customProgramCacheKey = () => "soil-v1";
  return m;
}

// --------------------------------------------------------------- fields
export class Field {
  constructor(i, root, tex, density, shared, onSelect) {
    this.i = i;
    const g = this.g = new THREE.Group();
    g.position.set(FIELD_POS[i][0], 0, FIELD_POS[i][1]);
    root.add(g);
    this.soil = soilMaterial(tex);
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(PLOT_W, PLOT_D, 1, 1), this.soil);
    plane.rotation.x = -Math.PI / 2; plane.position.y = 0.06; plane.receiveShadow = true;
    plane.userData.field = i; this.pick = plane; g.add(plane);
    // berms
    const berm = new THREE.MeshStandardMaterial({ map: this.soil.map, color: "#d8bf98", roughness: 1 });
    for (const [w, d, x, z] of [[PLOT_W + 0.7, 0.35, 0, -PLOT_D / 2 - 0.17], [PLOT_W + 0.7, 0.35, 0, PLOT_D / 2 + 0.17], [0.35, PLOT_D, -PLOT_W / 2 - 0.17, 0], [0.35, PLOT_D, PLOT_W / 2 + 0.17, 0]]) {
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, 0.22, d), berm); b.position.set(x, 0.1, z); b.receiveShadow = true; b.castShadow = true; g.add(b);
    }
    // drip laterals and the field manifold on the header side
    this.lineMat = new THREE.MeshStandardMaterial({ color: "#1d2226", roughness: 0.55, emissive: new THREE.Color("#00e5ff"), emissiveIntensity: 0 });
    const lines = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.035, 0.035, PLOT_D - 0.5, 5), this.lineMat, LINES);
    const m = new THREE.Matrix4();
    for (let k = 0; k < LINES; k++) {
      const x = -PLOT_W / 2 + 0.6 + (k * (PLOT_W - 1.2)) / (LINES - 1);
      m.makeRotationX(Math.PI / 2).setPosition(x, 0.1, 0);
      lines.setMatrixAt(k, m);
    }
    g.add(lines);
    const hz = i < 3 ? PLOT_D / 2 + 0.45 : -PLOT_D / 2 - 0.45;
    const pvc = new THREE.MeshStandardMaterial({ color: "#d9dde0", roughness: 0.4 });
    const man = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, PLOT_W, 8), pvc);
    man.rotation.z = Math.PI / 2; man.position.set(0, 0.14, hz); man.castShadow = true; g.add(man);
    const valve = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.42, 0.5), new THREE.MeshStandardMaterial({ color: "#2c6b4a", roughness: 0.6 }));
    valve.position.set(-PLOT_W / 2 + 0.6, 0.21, hz + (i < 3 ? 0.55 : -0.55)); valve.castShadow = true; g.add(valve);
    // corner sensor posts with a status light
    this.ledMat = new THREE.MeshStandardMaterial({ color: "#123", emissive: new THREE.Color("#35f08f"), emissiveIntensity: 0.6 });
    const post = new THREE.CylinderGeometry(0.05, 0.05, 1.1, 6), head = new THREE.SphereGeometry(0.09, 10, 8);
    const postMat = new THREE.MeshStandardMaterial({ color: "#8c96a0", roughness: 0.5, metalness: 0.6 });
    for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
      const p = new THREE.Mesh(post, postMat); p.position.set(sx * (PLOT_W / 2 + 0.45), 0.55, sz * (PLOT_D / 2 + 0.45)); g.add(p);
      const h = new THREE.Mesh(head, this.ledMat); h.position.set(p.position.x, 1.12, p.position.z); g.add(h);
    }
    // selection frame and anomaly ring
    this.frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(PLOT_W + 1.4, 0.8, PLOT_D + 1.4)),
      new THREE.LineBasicMaterial({ color: "#5ef0a6", transparent: true, opacity: 0 }));
    this.frame.position.y = 0.4; g.add(this.frame);
    this.ring = new THREE.Mesh(new THREE.RingGeometry(9.2, 9.9, 64), new THREE.MeshBasicMaterial({ color: "#ff5a3c", transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
    this.ring.rotation.x = -Math.PI / 2; this.ring.scale.set(1, 0.7, 1); this.ring.position.y = 0.3; g.add(this.ring);
    this.crop = new FieldCrop(g, PLOT_W, PLOT_D, density, shared);
    // label
    const tag = this.tag = document.createElement("button");
    tag.className = "ftag empty"; tag.type = "button";
    tag.innerHTML = `<span class="ft-ring"><svg viewBox="0 0 36 36"><circle cx="18" cy="18" r="15" class="bg"/><circle cx="18" cy="18" r="15" class="fg"/></svg><b class="ft-id">F${i + 1}</b></span><span class="ft-txt"><b class="ft-crop">Not planned</b><span class="ft-state"></span></span>`;
    tag.addEventListener("click", () => onSelect && onSelect(i));
    this.tagObj = new CSS2DObject(tag); this.tagObj.position.set(0, 3.2, 0); g.add(this.tagObj);
    this.alarm = document.createElement("div"); this.alarm.className = "falarm";
    this.alarmObj = new CSS2DObject(this.alarm); this.alarmObj.position.set(0, 5.4, 0); this.alarmObj.visible = false; g.add(this.alarmObj);
    this.state = { wet: 0.2, salt: 0, spot: 0, deliver: 1, flow: 0 };
    this.target = { ...this.state };
    this.alarmOn = false; this.selected = false; this.pulse = 0;
  }

  setCrop(crop, label, planned = false) {
    this.crop.setCrop(crop, planned);
    this.tag.querySelector(".ft-crop").textContent = crop ? (label || CROP_INFO[crop].label) : label || "Fallow";
    this.tag.classList.toggle("empty", !crop && (!label || label === "Not planned"));
    this.tag.title = crop ? "" : label || "";
    this.tag.classList.toggle("fallow", !crop);
    this.tag.classList.toggle("planned", planned);
  }

  update(w, f, tmax, overlay) {
    const sw = f && f.sw_obs != null ? f.sw_obs : w ? w.theta_top : 0.12;
    this.target.wet = Math.min(1, Math.max(0, (sw - 0.05) / 0.22));
    this.target.salt = Math.min(0.9, Math.max(0, ((w ? w.ece_top : 2) - 3) / 10));
    const irr = f ? f.irr_mm || 0 : 0;
    this.target.flow = Math.min(1, irr / 8);
    this.target.spot = Math.min(1, irr / 6);
    this.target.deliver = w ? w.deliver ?? 1 : 1;
    this.crop.update(w, tmax);
    // tag text and growth ring (stage of the cycle, from the crop model's thermal time)
    let state = "", pct = 0;
    if (w && w.crop) {
      if (w.done) { state = "Harvested"; pct = 1; }
      else if (!w.sown) state = "Waiting to sow";
      else { pct = Math.min(1, w.stage || 0); state = pct < 0.04 ? "Sown" : pct < 0.22 ? "Emerging" : pct < 0.5 ? "Growing" : pct < 0.75 ? "Flowering" : "Ripening"; }
    }
    this.tag.querySelector(".ft-state").textContent = state;
    this.tag.querySelector(".fg").style.strokeDashoffset = String(94.2 * (1 - pct));
    this.applyOverlay(overlay, w, f);
  }

  applyOverlay(key, w, f) {
    this.ovKey = key;
    const u = this.soil.userData.u.uOv.value;
    if (!key || !f) { u.w = 0; this.tag.removeAttribute("data-ov"); return; }
    let v = null;
    if (key === "health" && f.cc_pred > 0.05) v = (100 * (this.lastCc ?? f.cc_pred)) / f.cc_pred;
    if (key === "moisture") v = f.sw_obs;
    if (key === "salinity") v = f.ec_obs;
    if (key === "water") v = f.irr_mm;
    if (f.cc_obs != null) this.lastCc = f.cc_obs;
    if (v == null) { u.w = 0; this.tag.setAttribute("data-ov", "no reading"); return; }
    const c = rampColor(key, v); u.set(c.r, c.g, c.b, 0.78);
    const o = OVERLAYS[key];
    this.tag.setAttribute("data-ov", `${key === "moisture" ? v.toFixed(3) : v.toFixed(key === "salinity" ? 1 : 0)} ${o.unit}`);
  }

  tick(dt, t, reduced) {
    const k = Math.min(1, dt * 3), s = this.state, tg = this.target;
    for (const key of Object.keys(tg)) s[key] += (tg[key] - s[key]) * k;
    const u = this.soil.userData.u;
    u.uWet.value = s.wet; u.uSalt.value = s.salt; u.uSpot.value = s.spot; u.uDeliver.value = s.deliver;
    const clog = s.deliver < 0.9;
    this.lineMat.emissive.set(clog ? "#ff5a3c" : "#00d5ff");
    this.lineMat.emissiveIntensity = this.pulse > 0 ? this.pulse * 1.5 : (this.ovKey === "water" ? 0.25 + s.flow : 0) * (clog ? 1.4 : 1);
    if (this.pulse > 0) this.pulse = Math.max(0, this.pulse - dt * 0.5);
    this.ledMat.emissive.set(this.alarmOn ? "#ff5a3c" : "#35f08f");
    this.ledMat.emissiveIntensity = this.alarmOn ? 1.2 + Math.sin(t * 6) * 0.6 : 0.7;
    this.frame.material.opacity += ((this.selected ? 0.95 : 0) - this.frame.material.opacity) * Math.min(1, dt * 6);
    const ring = this.alarmOn ? 0.5 + 0.4 * Math.sin(t * 4) : 0;
    this.ring.material.opacity += (ring - this.ring.material.opacity) * Math.min(1, dt * 6);
    if (!reduced && this.alarmOn) { const sc = 1 + 0.03 * Math.sin(t * 4); this.ring.scale.set(sc, 0.7 * sc, sc); }
  }

  setAlarm(on, text) {
    this.alarmOn = on;
    this.alarmObj.visible = !!(on && text);
    if (text) this.alarm.textContent = text;
    this.tag.classList.toggle("alarm", on);
  }

  setSelected(on) { this.selected = on; this.tag.classList.toggle("sel", on); }
  dispose() { this.crop.dispose(); this.soil.dispose(); this.lineMat.dispose(); this.ledMat.dispose(); }
}

// --------------------------------------------------------------- infrastructure
export function buildInfrastructure(tex, quality, env) {
  const group = new THREE.Group();
  const concrete = tex.concrete.clone(); concrete.needsUpdate = true; concrete.repeat.set(2, 2);
  const white = new THREE.MeshStandardMaterial({ map: concrete, color: "#f4efe6", roughness: 0.82 });
  const sand = new THREE.MeshStandardMaterial({ map: concrete, color: "#e2cfb0", roughness: 0.9 });
  const glass = new THREE.MeshStandardMaterial({ color: "#1f3a4a", roughness: 0.08, metalness: 0.9, envMapIntensity: 1.4 });
  const steel = new THREE.MeshStandardMaterial({ color: "#cfd5da", roughness: 0.32, metalness: 0.85 });
  const darkSteel = new THREE.MeshStandardMaterial({ color: "#5b6670", roughness: 0.45, metalness: 0.7 });
  const pipeMat = new THREE.MeshStandardMaterial({ color: "#8e98a3", roughness: 0.35, metalness: 0.8 });
  const windowsLit = new THREE.MeshStandardMaterial({ color: "#2a3d48", roughness: 0.2, metalness: 0.5, emissive: new THREE.Color("#ffcf8a"), emissiveIntensity: 0 });
  const lamps = [];
  const box = (w, h, d, mat, x, y, z, ry = 0) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); m.position.set(x, y, z); m.rotation.y = ry;
    m.castShadow = true; m.receiveShadow = true; group.add(m); return m;
  };
  const cyl = (r, h, mat, x, y, z, seg = 20, r2 = r) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r2, r, h, seg), mat); m.position.set(x, y, z);
    m.castShadow = true; m.receiveShadow = true; group.add(m); return m;
  };

  // research centre with control tower (north-east, behind the fields)
  box(22, 6, 9, white, 30, 3, -50); box(22.2, 1.2, 9.2, sand, 30, 6.6, -50);
  box(21, 2.2, 0.15, windowsLit, 30, 3.6, -45.45); box(21, 2.2, 0.15, windowsLit, 30, 3.6, -54.55);
  box(10, 4, 8, white, 47, 2, -50); box(9.4, 1.6, 0.15, windowsLit, 47, 2.4, -45.95);
  cyl(2.2, 16, white, 18, 8, -50, 24); cyl(3.6, 2.6, glass, 18, 17.3, -50, 24); cyl(3.9, 0.4, white, 18, 18.8, -50, 24);
  cyl(0.15, 3, steel, 18, 20.5, -50, 6);
  const logo = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 2.6), new THREE.MeshStandardMaterial({ map: tex.logo, roughness: 0.6, emissive: new THREE.Color("#7ff2b6"), emissiveMap: tex.logo, emissiveIntensity: 0.15 }));
  logo.position.set(18, 11, -47.75); group.add(logo);
  // rooftop solar
  const solarTex = tex.solar;
  const panel = new THREE.MeshStandardMaterial({ map: solarTex, roughness: 0.25, metalness: 0.6, envMapIntensity: 1.2 });
  const panelGeo = new THREE.BoxGeometry(2.4, 0.06, 1.4);
  const nRoof = 12, roof = new THREE.InstancedMesh(panelGeo, panel, nRoof);
  const mm = new THREE.Matrix4(), qq = new THREE.Quaternion(), ss = new THREE.Vector3(1, 1, 1);
  for (let k = 0; k < nRoof; k++) {
    qq.setFromEuler(new THREE.Euler(-0.35, 0, 0));
    mm.compose(V(22 + (k % 6) * 3, 7.6, -52 + Math.floor(k / 6) * 2.4), qq, ss); roof.setMatrixAt(k, mm);
  }
  roof.castShadow = true; group.add(roof);

  // solar farm east of the fields
  const rows = quality === "low" ? 4 : 7, perRow = quality === "low" ? 8 : 14;
  const solar = new THREE.InstancedMesh(panelGeo, panel, rows * perRow);
  const legs = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.06, 0.06, 1, 5), darkSteel, rows * perRow);
  let n = 0;
  for (let r = 0; r < rows; r++) for (let c = 0; c < perRow; c++) {
    const x = 44 + c * 2.6, z = -32 + r * 3.4;
    qq.setFromEuler(new THREE.Euler(-0.42, 0, 0)); mm.compose(V(x, 1.15, z), qq, ss); solar.setMatrixAt(n, mm);
    mm.compose(V(x, 0.5, z + 0.2), new THREE.Quaternion(), ss); legs.setMatrixAt(n, mm); n++;
  }
  solar.castShadow = true; solar.receiveShadow = true; group.add(solar); group.add(legs);

  // pump station and reverse-osmosis desalination plant (west)
  box(7, 4, 6, white, -44, 2, -6); box(7.4, 0.5, 6.4, sand, -44, 4.25, -6);
  box(0.12, 2.2, 1.6, darkSteel, -40.45, 1.1, -6);
  const roGlow = new THREE.MeshStandardMaterial({ color: "#e6f0f2", roughness: 0.3, metalness: 0.4, emissive: new THREE.Color("#2fd3e0"), emissiveIntensity: 0 });
  box(8, 0.5, 4, darkSteel, -44, 0.25, 3);
  for (let k = 0; k < 4; k++) { const v = cyl(0.42, 6.5, roGlow, -44, 1.1 + k * 0.9, 3, 14); v.rotation.z = Math.PI / 2; }
  box(0.3, 4.2, 4, darkSteel, -47.4, 2.1, 3); box(0.3, 4.2, 4, darkSteel, -40.6, 2.1, 3);
  // storage tanks
  for (const [x, z, r, h] of [[-52, -14, 2.6, 6], [-52, -6, 2.6, 6], [-38, -22, 1.8, 4.5]]) {
    cyl(r, h, steel, x, h / 2, z, 28);
    cyl(r + 0.05, 0.3, darkSteel, x, h, z, 28);
    for (let k = 1; k < 4; k++) cyl(r + 0.03, 0.1, darkSteel, x, (h * k) / 4, z, 28);
  }
  // elevated header tank
  for (const [dx, dz] of [[-1.3, -1.3], [1.3, -1.3], [-1.3, 1.3], [1.3, 1.3]]) cyl(0.12, 6, darkSteel, -36 + dx, 3, 14 + dz, 6);
  cyl(2.2, 3, steel, -36, 7.5, 14, 24);

  // reservoir: lined circular pond with a reflective, rippling surface
  const res = new THREE.Group(); res.position.set(-30, 0, 32); group.add(res);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(9, 0.45, 10, 64), new THREE.MeshStandardMaterial({ map: concrete, color: "#d9cdb8", roughness: 0.85 }));
  rim.rotation.x = Math.PI / 2; rim.position.y = 0.35; rim.receiveShadow = true; res.add(rim);
  const liner = new THREE.Mesh(new THREE.CylinderGeometry(9, 8.2, 1.2, 64, 1, true), new THREE.MeshStandardMaterial({ color: "#2b2f33", roughness: 0.8, side: THREE.BackSide }));
  liner.position.y = -0.3; res.add(liner);
  const wn = tex.waterN.clone(); wn.needsUpdate = true; wn.repeat.set(4, 4);
  const wn2 = tex.waterN.clone(); wn2.needsUpdate = true; wn2.repeat.set(7, 7);
  const water = new THREE.Mesh(new THREE.CircleGeometry(8.6, 64), new THREE.MeshPhysicalMaterial({
    color: "#2d6f78", roughness: 0.06, metalness: 0.0, transmission: 0, normalMap: wn, normalScale: new THREE.Vector2(0.35, 0.35),
    clearcoat: 1, clearcoatRoughness: 0.08, clearcoatNormalMap: wn2, envMapIntensity: 1.3 }));
  water.rotation.x = -Math.PI / 2; water.position.y = 0.12; water.receiveShadow = true; res.add(water);

  // greenhouse for the trial nursery
  const gh = new THREE.Group(); gh.position.set(-34, 0, -34); group.add(gh);
  const hoop = new THREE.Mesh(new THREE.CylinderGeometry(3, 3, 12, 24, 1, true, 0, Math.PI), new THREE.MeshPhysicalMaterial({ color: "#eef6f4", roughness: 0.15, transmission: 0.6, transparent: true, opacity: 0.55, side: THREE.DoubleSide, thickness: 0.1 }));
  hoop.rotation.z = Math.PI / 2; hoop.rotation.y = Math.PI / 2; hoop.position.y = 0.05; gh.add(hoop);
  for (let k = -2; k <= 2; k++) { const a = new THREE.Mesh(new THREE.TorusGeometry(3, 0.05, 6, 24, Math.PI), steel); a.position.set(0, 0.05, k * 2.9); gh.add(a); }

  // header pipeline from the pump station along the centre lane, and feeds into each manifold
  const pipe = (a, b, r = 0.22) => {
    const d = b.clone().sub(a), len = d.length();
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, 10), pipeMat);
    m.position.copy(a).add(b).multiplyScalar(0.5); m.quaternion.setFromUnitVectors(V(0, 1, 0), d.normalize());
    m.castShadow = true; group.add(m); return m;
  };
  pipe(V(-40, 0.3, 0.6), V(27, 0.3, 0.6));
  pipe(V(-44, 0.3, -2.8), V(-44, 0.3, 0.6)); pipe(V(-44, 0.3, 0.6), V(-40, 0.3, 0.6));
  for (const [fx] of FIELD_POS.slice(0, 3)) { pipe(V(fx - 7.5, 0.25, 0.6), V(fx - 7.5, 0.25, -2.0), 0.12); pipe(V(fx - 7.5, 0.25, 0.6), V(fx - 7.5, 0.25, 2.0), 0.12); }
  pipe(V(-30, 0.3, 23.4), V(-30, 0.3, 0.6), 0.2);

  // weather mast (its cups turn at the measured wind speed)
  const mast = new THREE.Group(); mast.position.set(-24, 0, -28); group.add(mast);
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.1, 8, 6), steel); pole.position.y = 4; mast.add(pole);
  const cups = new THREE.Group(); cups.position.y = 8.1; mast.add(cups);
  for (let k = 0; k < 3; k++) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.03, 0.03), steel); arm.position.x = 0.4;
    const cup = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 6, 0, Math.PI), white); cup.position.x = 0.8; cup.rotation.y = Math.PI / 2;
    const a = new THREE.Group(); a.add(arm, cup); a.rotation.y = (k * Math.PI * 2) / 3; cups.add(a);
  }
  const panelBox = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.8, 0.3), white); panelBox.position.set(0, 2.2, 0.15); mast.add(panelBox);

  // lamp posts along the ring road (lit at night)
  const lampHead = new THREE.MeshStandardMaterial({ color: "#333", emissive: new THREE.Color("#ffd9a0"), emissiveIntensity: 0 });
  const lampSpots = [[-52, -37], [-20, -37], [12, -37], [34, -37], [34, -8], [34, 23], [2, 23], [-30, 23], [-52, 23], [-52, -8]];
  lampSpots.forEach(([x, z], k) => {
    const p = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.09, 5, 6), darkSteel); p.position.set(x + 1.8, 2.5, z + 1.8); p.castShadow = true; group.add(p);
    const h = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.15, 0.3), lampHead); h.position.set(x + 1.5, 5, z + 1.8); group.add(h);
    if (k % 2 === 0) { const L = new THREE.PointLight("#ffcf8f", 0, 26, 1.6); L.position.set(x + 1.5, 4.7, z + 1.8); group.add(L); lamps.push(L); }
  });

  // maintenance yard: containers and the service truck that drives out for repairs
  box(6, 2.6, 2.4, new THREE.MeshStandardMaterial({ color: "#2f6b55", roughness: 0.7 }), -48, 1.3, 18);
  box(6, 2.6, 2.4, new THREE.MeshStandardMaterial({ color: "#b0653a", roughness: 0.7 }), -48, 1.3, 21);
  const truck = buildTruck();
  truck.position.copy(DEPOT); group.add(truck);

  // trial strip (16 mini plots, north of the fields)
  const trial = new THREE.Group(); trial.position.set(-2, 0, -27); group.add(trial);
  const base = new THREE.Mesh(new THREE.BoxGeometry(46, 0.12, 8.6), new THREE.MeshStandardMaterial({ color: "#c9ae87", roughness: 1 }));
  base.position.y = 0.06; base.receiveShadow = true; trial.add(base);
  const slots = [];
  for (let k = 0; k < 16; k++) {
    const x = -19.6 + (k % 8) * 5.6, z = k < 8 ? -2 : 2.1;
    const pm = new THREE.Mesh(new THREE.BoxGeometry(4.4, 0.2, 3.2), new THREE.MeshStandardMaterial({ color: "#b89a74", roughness: 1 }));
    pm.position.set(x, 0.16, z); pm.receiveShadow = true; trial.add(pm);
    slots.push({ x, z, mesh: pm, used: false, objs: [] });
  }
  const tl = document.createElement("div"); tl.className = "areatag"; tl.textContent = "Trial plots";
  const tlo = new CSS2DObject(tl); tlo.position.set(-25, 1.4, 0); trial.add(tlo);

  return { group, lamps, lampHead, windowsLit, roGlow, cups, water, wn, wn2, truck, trial, slots };
}

function buildTruck() {
  const t = new THREE.Group();
  const body = new THREE.MeshStandardMaterial({ color: "#f2f2ee", roughness: 0.45, metalness: 0.3 });
  const dark = new THREE.MeshStandardMaterial({ color: "#1b1e22", roughness: 0.7 });
  const accent = new THREE.MeshStandardMaterial({ color: "#2fae6a", roughness: 0.5 });
  const cab = new THREE.Mesh(new THREE.BoxGeometry(1.4, 1.2, 1.5), body); cab.position.set(1.0, 0.95, 0); t.add(cab);
  const win = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.5, 1.3), new THREE.MeshStandardMaterial({ color: "#20323c", metalness: 0.8, roughness: 0.1 })); win.position.set(1.71, 1.15, 0); t.add(win);
  const bed = new THREE.Mesh(new THREE.BoxGeometry(2.2, 0.5, 1.5), body); bed.position.set(-0.8, 0.6, 0); t.add(bed);
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(3.62, 0.12, 1.52), accent); stripe.position.set(0.1, 0.75, 0); t.add(stripe);
  const beacon = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.12, 0.6), new THREE.MeshStandardMaterial({ color: "#552", emissive: new THREE.Color("#ffb020"), emissiveIntensity: 0 }));
  beacon.position.set(1.0, 1.62, 0); t.add(beacon); t.userData.beacon = beacon;
  for (const [x, z] of [[1.0, 0.75], [1.0, -0.75], [-1.2, 0.75], [-1.2, -0.75]]) {
    const w = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.32, 0.25, 12), dark); w.rotation.x = Math.PI / 2; w.position.set(x, 0.32, z); t.add(w);
  }
  t.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
  t.scale.setScalar(0.9);
  return t;
}
