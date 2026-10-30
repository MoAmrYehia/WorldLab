// WorldLab: Green Frontier 3D engine.
// A procedural, physically lit desert farm near Al Ain. Everything that moves or changes colour is driven by
// the simulation stream (crop stage, canopy, water stress, soil moisture and salinity, irrigation, delivered
// flow, pests, harvest, measured weather). Time of day is a viewing choice: the simulation steps whole days.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { Sky } from "three/addons/objects/Sky.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { makeTextures, disposeTextures } from "./engine/textures.js";
import { buildTerrain } from "./engine/terrain.js";
import { buildFlora } from "./engine/flora.js";
import { Field, buildInfrastructure, FIELD_POS, OVERLAYS, PLOT_D } from "./engine/farm.js";
import { cropGeometry, clearCropCache, CROP_INFO } from "./engine/crops.js";
import { buildDrone, buildDust, buildRain, buildClouds, Markers, Pulse, TruckRun, HarvestBurst } from "./engine/fx.js";

export { OVERLAYS, CROP_INFO };
export { cropPortrait, stageOf } from "./engine/portrait.js";
export const QUALITIES = ["low", "medium", "high", "ultra"];
export const TIMES = {
  morning: { label: "Morning", elev: 14, az: 100, turb: 7, ray: 1.6, mie: 0.005, exp: 0.5, fog: "#d8c9b4", dens: 0.0013, sun: "#ffe2bf", sunI: 2.6, hemi: 0.75 },
  noon: { label: "Noon", elev: 66, az: 170, turb: 9, ray: 1.1, mie: 0.004, exp: 0.38, fog: "#d6d0c2", dens: 0.0011, sun: "#fff6e8", sunI: 3.2, hemi: 0.9 },
  golden: { label: "Golden hour", elev: 7, az: 258, turb: 10, ray: 2.6, mie: 0.007, exp: 0.62, fog: "#d9a877", dens: 0.0014, sun: "#ffbe7a", sunI: 2.8, hemi: 0.55 },
  night: { label: "Night", elev: -14, az: 258, turb: 2, ray: 0.4, mie: 0.002, exp: 0.9, fog: "#1a2030", dens: 0.0016, sun: "#9db4ff", sunI: 0.35, hemi: 0.18 },
};
const DENSITY = { low: 0.35, medium: 0.6, high: 1, ultra: 1.6 };
const CENTER = new THREE.Vector3(-2, 0, -4);

function webglOK() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; }
}
export function suggestQuality() {
  const mobile = /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent) || Math.min(screen.width, screen.height) < 700;
  const cores = navigator.hardwareConcurrency || 4, mem = navigator.deviceMemory || 8;
  if (mobile || cores <= 4 || mem <= 4) return "medium";
  return "high";
}

export function createScene(container, opts = {}) {
  if (!webglOK()) throw new Error("WebGL is not available in this browser");
  const o = { onSelect: null, theme: "day", reducedMotion: false, interactive: true, labels: true, quality: "auto",
    time: "golden", homePos: [34, 30, 52], target: [CENTER.x, CENTER.y, CENTER.z], shiftX: 0, flyover: false, onFps: null, onQuality: null, ...opts };
  if (o.theme === "dusk" && !opts.time) o.time = "golden";
  let quality = o.quality === "auto" ? suggestQuality() : o.quality;
  let auto = o.quality === "auto";
  const cache = { fields: null, rec: null, trials: [], anomaly: [-1, ""], selected: -1, overlay: null, time: o.time, preview: null, labels: o.labels };
  let W = null;                      // the built world
  let follow = true;                 // camera flies to events unless the user turned it off
  let running = true;

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);
  renderer.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); running = false; }, false);
  const labels = new CSS2DRenderer();
  labels.domElement.className = "scene-labels";
  if (!o.interactive) labels.domElement.style.pointerEvents = "none";
  container.appendChild(labels.domElement);

  const camera = new THREE.PerspectiveCamera(40, 1, 0.3, 4000);
  const home = new THREE.Vector3(...o.homePos);
  camera.position.copy(o.reducedMotion ? home : home.clone().multiplyScalar(2.6).add(new THREE.Vector3(60, 40, 120)));
  const controls = new OrbitControls(camera, labels.domElement);
  controls.target.set(...o.target);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.47; controls.minDistance = 4; controls.maxDistance = 260;
  controls.enabled = o.interactive;
  controls.keys = { LEFT: "ArrowLeft", UP: "ArrowUp", RIGHT: "ArrowRight", BOTTOM: "ArrowDown" };
  if (o.interactive) controls.listenToKeyEvents(window);

  // camera rig: tweens between viewpoints, and follow modes
  const rig = { tween: null, mode: o.flyover ? "flyover" : "intro", follow: null, idle: performance.now(), sway: null };
  function flyTo(pos, tgt, dur = 1.8, then = null) {
    rig.tween = { p0: camera.position.clone(), t0: controls.target.clone(), p1: pos.clone(), t1: tgt.clone(), t: 0, dur: o.reducedMotion ? 0.001 : dur, then };
  }
  const fieldCenter = (i) => new THREE.Vector3(FIELD_POS[i][0], 0, FIELD_POS[i][1]);
  const views = {
    overview: () => flyTo(new THREE.Vector3(10, 78, 96), CENTER.clone()),
    home: () => flyTo(home.clone(), new THREE.Vector3(...o.target)),
    field: (i) => { const c = fieldCenter(i); flyTo(c.clone().add(new THREE.Vector3(9, 11, 15)), c.clone().add(new THREE.Vector3(0, 0.6, 0))); },
    closeup: (i) => { const c = fieldCenter(i); flyTo(c.clone().add(new THREE.Vector3(3.2, 1.7, PLOT_D / 2 + 3.4)), c.clone().add(new THREE.Vector3(0, 0.7, 1))); },
    incident: (i) => { const c = fieldCenter(i); flyTo(c.clone().add(new THREE.Vector3(-11, 7, 13)), c.clone().add(new THREE.Vector3(0, 0.5, 0)), 2.4); },
    harvest: () => { flyTo(new THREE.Vector3(48, 34, 62), CENTER.clone(), 2.6); rig.mode = "harvest"; },
  };

  // ---------------------------------------------------------------- build / rebuild the world for a quality level
  function build(q) {
    const tex = makeTextures(q);
    const scene = new THREE.Scene();
    const T = TIMES[cache.time] || TIMES.golden;
    scene.fog = new THREE.FogExp2(T.fog, T.dens);
    const sky = new Sky(); sky.scale.setScalar(3000); scene.add(sky);
    const skyScene = new THREE.Scene(); const sky2 = new Sky(); sky2.scale.setScalar(500); skyScene.add(sky2);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const hemi = new THREE.HemisphereLight("#cfe0ff", "#b0895c", 0.6); scene.add(hemi);
    const sun = new THREE.DirectionalLight("#ffd2a0", 2.6);
    sun.castShadow = true;
    const sm = { low: 1024, medium: 2048, high: 2048, ultra: 4096 }[q];
    sun.shadow.mapSize.set(sm, sm);
    Object.assign(sun.shadow.camera, { left: -78, right: 78, top: 62, bottom: -62, near: 1, far: 420 });
    sun.shadow.camera.updateProjectionMatrix();
    sun.shadow.bias = -0.0003; sun.shadow.normalBias = 0.035;
    sun.target.position.copy(CENTER); scene.add(sun, sun.target);
    const shared = { time: { value: 0 }, wind: { value: 0.35 } };
    const root = new THREE.Group(); scene.add(root);
    root.add(buildTerrain(tex, q));
    root.add(buildFlora(tex, q));
    const infra = buildInfrastructure(tex, q);
    root.add(infra.group);
    const fields = FIELD_POS.map((_, i) => new Field(i, root, tex, DENSITY[q], shared, (k) => o.onSelect && o.onSelect(k)));
    const drone = buildDrone(tex); root.add(drone);
    const dust = buildDust(tex, { low: 300, medium: 700, high: 1400, ultra: 2400 }[q]); root.add(dust);
    const rain = buildRain(q === "low" ? 800 : 2500); root.add(rain);
    const clouds = buildClouds(tex); scene.add(clouds);
    const markers = new Markers(root), pulse = new Pulse(root), burst = new HarvestBurst(root, tex);
    const truck = new TruckRun(infra.truck, (i) => { fields[i].pulse = 1; markers.add(i, "repair", "Drip line repaired", 5); });
    let composer = null;
    if (q === "high" || q === "ultra") {
      const rt = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: q === "ultra" ? 8 : 4 });
      composer = new EffectComposer(renderer, rt);
      composer.addPass(new RenderPass(scene, camera));
      composer.addPass(new UnrealBloomPass(new THREE.Vector2(256, 256), 0.22, 0.45, 0.88));
      composer.addPass(new OutputPass());
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, { low: 1, medium: 1.25, high: 1.5, ultra: 2 }[q]));
    renderer.shadowMap.type = q === "low" ? THREE.PCFShadowMap : THREE.PCFSoftShadowMap;
    W = { q, tex, scene, sky, sky2, skyScene, pmrem, envRT: null, hemi, sun, shared, root, infra, fields, drone, dust, rain, clouds, markers, pulse, burst, truck, composer,
      wind: 0.35, windTarget: 0.35, dustTarget: 0.3, cloudTarget: 0, rainTarget: 0, heat: 0, heatTarget: 0, u2: 2 };
    applyTime(cache.time);
    resize();
    // restore state
    if (cache.fields) setFields(cache.fields, true);
    if (cache.preview) previewPlan(cache.preview);
    cache.trials.forEach((t) => addTrial(t, true));
    if (cache.rec) update(cache.rec);
    setAnomaly(...cache.anomaly);
    setSelected(cache.selected);
    setOverlay(cache.overlay);
    setLabels(cache.labels);
  }

  function disposeWorld() {
    if (!W) return;
    W.fields.forEach((f) => f.dispose());
    W.markers.clear();
    W.scene.traverse((ob) => {
      if (ob.geometry) ob.geometry.dispose();
      if (ob.material) (Array.isArray(ob.material) ? ob.material : [ob.material]).forEach((m) => m.dispose());
      if (ob.isCSS2DObject && ob.element) ob.element.remove();
    });
    if (W.envRT) W.envRT.dispose();
    W.pmrem.dispose();
    if (W.composer) W.composer.dispose();
    disposeTextures(W.tex);
    clearCropCache();
    W = null;
  }

  // ---------------------------------------------------------------- lighting presets
  function applyTime(key) {
    cache.time = key;
    if (!W) return;
    const T = TIMES[key] || TIMES.golden;
    const phi = THREE.MathUtils.degToRad(90 - T.elev), theta = THREE.MathUtils.degToRad(T.az);
    const sunDir = new THREE.Vector3().setFromSphericalCoords(1, phi, theta);
    for (const s of [W.sky, W.sky2]) {
      const u = s.material.uniforms;
      u.turbidity.value = T.turb + W.heat * 4; u.rayleigh.value = T.ray; u.mieCoefficient.value = T.mie; u.mieDirectionalG.value = 0.82;
      u.sunPosition.value.copy(sunDir);
    }
    renderer.toneMappingExposure = T.exp;
    const night = T.elev < 0;
    W.sun.color.set(T.sun); W.sun.intensity = T.sunI;
    const lightDir = night ? new THREE.Vector3().setFromSphericalCoords(1, THREE.MathUtils.degToRad(40), theta + Math.PI) : sunDir;
    W.sun.position.copy(CENTER).addScaledVector(lightDir, 200);
    W.hemi.intensity = T.hemi;
    W.hemi.color.set(night ? "#4a5a8a" : "#cfe0ff"); W.hemi.groundColor.set(night ? "#2a2018" : "#b0895c");
    W.scene.fog.color.set(T.fog); W.scene.fog.density = T.dens;
    W.infra.lamps.forEach((L, k) => { L.intensity = night ? 18 : 0; L.visible = night && (W.q !== "low" || k % 2 === 0); });   // hidden lights cost nothing by day
    W.infra.lampHead.emissiveIntensity = night ? 3 : 0;
    W.infra.windowsLit.emissiveIntensity = night ? 1.6 : key === "golden" ? 0.25 : 0;
    W.fields.forEach((f) => (f.ledMat.emissiveIntensity = night ? 2 : 0.7));
    if (W.envRT) W.envRT.dispose();
    W.envRT = W.pmrem.fromScene(W.skyScene, 0, 0.1, 1000);
    W.scene.environment = W.envRT.texture;
    W.scene.environmentIntensity = night ? 0.25 : 1;
  }

  // ---------------------------------------------------------------- API
  function setFields(fields, silent = false) {
    cache.fields = fields; if (!silent) cache.preview = null;
    if (!W) return;
    fields.forEach((f, i) => W.fields[i] && W.fields[i].setCrop(f.crop || null, f.label, !!f.planned));
  }

  function previewPlan(picks) {          // picks: [{crop, label} | null] x 6 — ghost crops for the planner
    cache.preview = picks;
    if (!W) return;
    picks.forEach((p, i) => {
      const F = W.fields[i];
      if (p && p.crop) { F.setCrop(p.crop, p.label, true); F.crop.update(null, 30, true); }
      else if (cache.fields && cache.fields[i]) F.setCrop(cache.fields[i].crop || null, cache.fields[i].label, !!cache.fields[i].planned);
      else F.setCrop(null, p && p.fallow ? "Fallow" : "Scientist decides", false);
    });
  }

  function update(rec) {
    if (!rec || !rec.world) return;
    cache.rec = rec;
    if (!W) return;
    rec.world.forEach((w, i) => W.fields[i] && W.fields[i].update(w, rec.fields[i], rec.tmax, cache.overlay));
    let flow = 0, desal = 0, n = 0;
    rec.fields.forEach((f) => { if (f.irr_mm > 0) { flow += f.irr_mm; desal += f.desal || 0; n++; } });
    W.infra.roGlow.emissiveIntensity = n ? (desal / n) * 0.8 : 0;
    // measured weather drives the atmosphere
    const u2 = rec.u2 ?? 2.2;
    W.u2 = u2;
    W.windTarget = Math.min(1.2, 0.12 + u2 / 4.5);
    W.dustTarget = Math.min(0.75, 0.12 + Math.max(0, u2 - 1.5) * 0.18);
    W.cloudTarget = rec.clearness != null ? Math.max(0, Math.min(0.9, (0.92 - rec.clearness) * 2.2)) : 0;
    W.rainTarget = rec.rain > 0.5 ? Math.min(1, rec.rain / 8) : 0;
    W.heatTarget = Math.max(0, Math.min(1, ((rec.tmax ?? 30) - 40) / 6));
  }

  function setSelected(i) { cache.selected = i; if (W) W.fields.forEach((f, k) => f.setSelected(k === i)); }
  function setAnomaly(i, text = "") { cache.anomaly = [i, text]; if (W) W.fields.forEach((f, k) => f.setAlarm(k === i, k === i ? text : "")); }
  function setOverlay(key) {
    cache.overlay = key && OVERLAYS[key] ? key : null;
    if (!W) return;
    W.fields.forEach((f, i) => f.applyOverlay(cache.overlay, cache.rec && cache.rec.world[i], cache.rec && cache.rec.fields[i]));
    container.classList.toggle("ov-on", !!cache.overlay);
  }
  function setLabels(on) { cache.labels = on; labels.domElement.style.visibility = on ? "visible" : "hidden"; }

  function scan(i) {
    if (!W || i == null || i < 0) return;
    const d = W.drone.userData, c = fieldCenter(i);
    d.target.set(c.x, 10, c.z); d.scanUntil = clock + 3.6; d.homeAt = clock + 8;
  }
  function hover(i) {
    if (!W || i == null || i < 0 || clock < W.drone.userData.scanUntil) return;
    const d = W.drone.userData, c = fieldCenter(i);
    d.target.set(c.x + 3, 12, c.z + 2); d.homeAt = clock + 3;
  }

  function addTrial(t, silent = false) {
    if (!silent) cache.trials.push(t);
    if (!W) return;
    const slot = W.infra.slots.find((s) => !s.used);
    if (!slot) return;
    slot.used = true;
    const crop = CROP_INFO[t.crop] ? t.crop : "wheat";
    const ratio = t.predicted_yield_median > 0 ? t.measured_yield_t_ha / t.predicted_yield_median : 1;
    const im = new THREE.InstancedMesh(cropGeometry(crop, 3), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.75, side: THREE.DoubleSide }), 30);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), s = new THREE.Vector3();
    const tint = new THREE.Color(1, 1, 1).lerp(new THREE.Color(1, 0.85, 0.5), Math.max(0, 1 - Math.min(ratio, 1)));
    const h = 0.4 + 0.6 * Math.min(ratio, 1.2);
    for (let n = 0; n < 30; n++) {
      q.setFromAxisAngle(v.set(0, 1, 0), n * 2.4);
      m.compose(v.set(slot.x - 1.8 + (n % 6) * 0.72, 0.26, slot.z - 1.2 + Math.floor(n / 6) * 0.6), q, s.set(1, h, 1));
      im.setMatrixAt(n, m); im.setColorAt(n, tint);
    }
    im.castShadow = true; W.infra.trial.add(im);
    const ring = new THREE.Mesh(new THREE.RingGeometry(2.55, 2.8, 40), new THREE.MeshBasicMaterial({ color: t.prediction_held ? "#35f08f" : "#ff8a3c", transparent: true, opacity: 0.85, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(slot.x, 0.3, slot.z); ring.scale.set(1, 0.72, 1); W.infra.trial.add(ring);
    slot.mesh.material = new THREE.MeshStandardMaterial({ color: t.plot === "saline" ? "#e6dcc8" : "#9c7b55", roughness: 1 });
    slot.objs.push(im, ring);
    if (!t.prediction_held) {
      const el = document.createElement("div"); el.className = "ttag"; el.textContent = "Prediction missed";
      const ob = new CSS2DObject(el); ob.position.set(slot.x, 2.4, slot.z); W.infra.trial.add(ob); slot.objs.push(ob);
    }
    if (!silent) { const d = W.drone.userData; d.target.set(-2 + slot.x, 8, -27 + slot.z); d.homeAt = clock + 2.5; }
  }

  // AI scientist actions shown in the world
  function event(kind, data = {}) {
    if (!W) return;
    const fi = typeof data.field === "string" ? Number(String(data.field).replace(/\D/g, "")) - 1 : data.field_index ?? -1;
    switch (kind) {
      case "anomaly": if (fi >= 0) { if (o.interactive && follow) views.incident(fi); W.markers.add(fi, "alarm", `${data.signal_label} ${data.direction}`, 7); } break;
      case "look": if (fi >= 0) scan(fi); break;
      case "field_test": if (fi >= 0) W.markers.add(fi, data.test === "emitter_flow" ? "flow" : data.test === "leaf_inspection" ? "leaf" : "lab", testText(data), 7); break;
      case "hypothesis": if (fi >= 0) W.markers.add(fi, "idea", "New hypothesis", 4); break;
      case "adjust": if (fi >= 0 && data.repair) W.truck.go(fi); else if (fi >= 0) W.markers.add(fi, "adjust", data.pest_control ? "Pest control applied" : "Irrigation adjusted", 4); break;
      case "model_update": W.pulse.fire(fi >= 0 ? FIELD_POS[fi][0] : CENTER.x, fi >= 0 ? FIELD_POS[fi][1] : CENTER.z); break;
      case "harvest": if (fi >= 0) W.burst.fire(fi); break;
      case "season_result": if (o.interactive && follow) views.harvest(); break;
    }
  }
  const testText = (d) => d.test === "emitter_flow" ? `Emitter flow ${Math.round((d.delivered_vs_design || 0) * 100)}% of design`
    : d.test === "water_test" ? `Groundwater ${d.groundwater_ec_dS_m} dS/m` : d.test === "soil_sample" ? "Soil sampled by layer"
    : d.test === "leaf_inspection" ? (d.pest_damage_seen ? `Pests: ${d.severity}` : "No pests found") : String(d.test || "Field test");

  function view(mode, i) {
    rig.mode = "free";
    if (mode === "drone") { rig.mode = "drone"; return; }
    if (mode === "flyover") { rig.mode = "flyover"; return; }
    if (views[mode]) views[mode](i);
  }

  function reset() {
    cache.fields = null; cache.rec = null; cache.trials = []; cache.anomaly = [-1, ""]; cache.preview = null;
    if (!W) return;
    W.infra.slots.forEach((s) => { s.objs.forEach((ob) => { W.infra.trial.remove(ob); if (ob.element) ob.element.remove(); }); s.objs = []; s.used = false; });
    W.fields.forEach((f, i) => { f.setCrop(null, "Not planned"); f.update(null, null, 30, null); });
    setAnomaly(-1, "");
  }

  // ---------------------------------------------------------------- picking and input
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let downAt = null;
  const onDown = (e) => { downAt = [e.clientX, e.clientY]; rig.idle = performance.now(); rig.sway = null; if (rig.mode !== "drone") rig.mode = "free"; rig.tween = null; };
  const onUp = (e) => {
    if (!downAt || !W || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 6) return;
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(W.fields.map((f) => f.pick), false)[0];
    if (hit && o.onSelect) o.onSelect(hit.object.userData.field, "3d");
  };
  if (o.interactive) {
    labels.domElement.addEventListener("pointerdown", onDown);
    labels.domElement.addEventListener("pointerup", onUp);
    labels.domElement.addEventListener("wheel", () => { rig.idle = performance.now(); rig.sway = null; rig.tween = null; if (rig.mode === "flyover" || rig.mode === "harvest") rig.mode = "free"; }, { passive: true });
  }

  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h, false); labels.setSize(w, h);
    camera.aspect = w / Math.max(h, 1);
    const sx = typeof o.shiftX === "function" ? o.shiftX(w, h) : o.shiftX;
    if (sx) camera.setViewOffset(w, h, -sx * w, 0, w, h); else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    if (W && W.composer) W.composer.setSize(w, h);
  }
  const ro = new ResizeObserver(resize); ro.observe(container);

  // ---------------------------------------------------------------- frame loop
  let clock = 0, last = performance.now(), fpsAcc = 0, fpsN = 0, fps = 60, fpsT = 0, autoChecked = 0;
  const intro = { t: o.reducedMotion ? 1 : 0, from: camera.position.clone() };
  const sph = new THREE.Spherical();
  let paused = false;
  function frame(now) {
    if (!running) return;
    requestAnimationFrame(frame);
    if (paused || document.hidden) { last = now; return; }
    const dt = Math.min((now - last) / 1000, 0.1); last = now; clock += dt;
    fpsAcc += dt; fpsN++;
    if (fpsAcc > 1) { fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0; o.onFps && o.onFps(fps, quality); fpsT++; maybeAuto(); }
    if (!W) return;
    W.shared.time.value = clock;
    W.wind += (W.windTarget - W.wind) * Math.min(1, dt * 0.8); W.shared.wind.value = o.reducedMotion ? 0 : W.wind;
    // camera
    if (rig.mode === "intro") {
      intro.t = Math.min(1, intro.t + dt / 3.2);
      const e = 1 - Math.pow(1 - intro.t, 3);
      camera.position.lerpVectors(intro.from, home, e);
      if (intro.t >= 1) rig.mode = o.flyover ? "flyover" : "free";
    } else if (rig.tween) {
      const tw = rig.tween; tw.t = Math.min(1, tw.t + dt / tw.dur);
      const e = tw.t < 0.5 ? 4 * tw.t ** 3 : 1 - Math.pow(-2 * tw.t + 2, 3) / 2;
      camera.position.lerpVectors(tw.p0, tw.p1, e); controls.target.lerpVectors(tw.t0, tw.t1, e);
      if (tw.t >= 1) { rig.tween = null; rig.idle = performance.now(); tw.then && tw.then(); }
    } else if (rig.mode === "drone") {
      const d = W.drone;
      const want = d.position.clone().add(new THREE.Vector3(-7, 4.5, 9));
      camera.position.lerp(want, Math.min(1, dt * 2)); controls.target.lerp(d.position.clone().add(new THREE.Vector3(0, -3, -2)), Math.min(1, dt * 3));
    } else if ((rig.mode === "flyover" || rig.mode === "harvest") && !o.reducedMotion) {
      sph.setFromVector3(camera.position.clone().sub(controls.target));
      sph.theta += dt * (rig.mode === "harvest" ? 0.06 : 0.035);
      if (rig.mode === "flyover") sph.phi = THREE.MathUtils.degToRad(58 + 6 * Math.sin(clock * 0.07));
      camera.position.setFromSpherical(sph).add(controls.target);
    } else if (o.interactive && !o.reducedMotion && performance.now() - rig.idle > 15000) {
      sph.setFromVector3(camera.position.clone().sub(controls.target));
      if (!rig.sway) rig.sway = { base: sph.theta, t: 0 };
      rig.sway.t += dt; sph.theta = rig.sway.base + 0.25 * Math.sin(rig.sway.t * 0.12);
      camera.position.setFromSpherical(sph).add(controls.target);
    }
    controls.update();

    // atmosphere follows measured weather (smoothly)
    W.heat += (W.heatTarget - W.heat) * Math.min(1, dt);
    const T = TIMES[cache.time] || TIMES.golden;
    W.sky.material.uniforms.turbidity.value = T.turb + W.heat * 5 + W.dust.material.opacity * 4;
    W.scene.fog.density = T.dens * (1 + W.heat * 0.5 + W.dust.material.opacity * 0.6);
    W.dust.material.opacity += (W.dustTarget - W.dust.material.opacity) * Math.min(1, dt * 0.5);
    if (!o.reducedMotion) {
      const p = W.dust.geometry.attributes.position, sp = 0.6 + W.u2 * 1.2;
      for (let k = 0; k < p.count; k++) {
        let x = p.getX(k) + dt * sp, y = p.getY(k) + Math.sin(clock + k) * dt * 0.2;
        if (x > 100) x -= 200;
        p.setX(k, x); p.setY(k, y);
      }
      p.needsUpdate = true;
    }
    W.clouds.children.forEach((c, k) => {
      c.material.opacity += (W.cloudTarget * 0.85 - c.material.opacity) * Math.min(1, dt * 0.4);
      if (!o.reducedMotion) c.position.x += dt * (1 + W.u2 * 0.6) * (k % 2 ? 1 : 0.8);
      if (c.position.x > 700) c.position.x = -700;
    });
    W.rain.visible = W.rainTarget > 0.01;
    W.rain.material.opacity += (W.rainTarget * 0.55 - W.rain.material.opacity) * Math.min(1, dt);
    if (W.rain.visible) {
      const p = W.rain.geometry.attributes.position;
      for (let k = 0; k < p.count; k += 2) {
        let y = p.getY(k) - dt * 28; if (y < 0) y += 40;
        p.setY(k, y); p.setY(k + 1, y - 0.9);
      }
      p.needsUpdate = true;
    }
    // drone
    const d = W.drone, du = d.userData;
    if (clock > du.homeAt) du.target.set(-36 + Math.sin(clock * 0.3) * 4, 10 + Math.sin(clock * 0.5), -10);
    d.position.lerp(du.target, Math.min(1, dt * 0.9));
    d.position.y += Math.sin(clock * 2.2) * 0.008;
    d.rotation.z = THREE.MathUtils.clamp((du.target.x - d.position.x) * -0.03, -0.3, 0.3);
    d.rotation.x = THREE.MathUtils.clamp((du.target.z - d.position.z) * 0.03, -0.3, 0.3);
    du.props.forEach((p, k) => (p.rotation.y += dt * (k % 2 ? 50 : -50)));
    var scanning = clock < du.scanUntil;
    du.cone.material.opacity += ((scanning ? 0.12 + 0.05 * Math.sin(clock * 8) : 0) - du.cone.material.opacity) * Math.min(1, dt * 5);
    // infrastructure motion
    W.infra.cups.rotation.y += dt * (o.reducedMotion ? 0 : 1 + W.u2 * 1.8);
    if (!o.reducedMotion) { W.infra.wn.offset.x += dt * 0.012 * (1 + W.u2 * 0.3); W.infra.wn2.offset.y -= dt * 0.02; }
    W.fields.forEach((f) => f.tick(dt, clock, o.reducedMotion));
    W.markers.tick(dt); W.pulse.tick(dt); W.burst.tick(dt); W.truck.tick(dt);
    if (W.composer) W.composer.render(); else renderer.render(W.scene, camera);
    labels.render(W.scene, camera);
    if (DV && DV.canvas.isConnected && DV.canvas.offsetParent && ++DV.n % DV.every === 0) renderDroneView(scanning);
  }

  // ---------------------------------------------------------------- the drone's own camera, drawn into a 2D canvas
  // Rendered off screen at a low rate, tone-mapped on the CPU (render targets skip the renderer's output transform).
  let DV = null;
  const droneCam = new THREE.PerspectiveCamera(60, 16 / 10, 0.1, 900);
  function droneView(canvas) {
    if (DV) { DV.rt.dispose(); DV = null; }
    if (!canvas) return;
    const w = canvas.width = 320, h = canvas.height = 200;
    const float = renderer.capabilities.isWebGL2 && renderer.extensions.has("EXT_color_buffer_float");
    const rt = new THREE.WebGLRenderTarget(w, h, { type: float ? THREE.FloatType : THREE.UnsignedByteType, depthBuffer: true });
    DV = { canvas, ctx: canvas.getContext("2d"), rt, w, h, float, n: 0, every: 4,
      buf: float ? new Float32Array(w * h * 4) : new Uint8Array(w * h * 4), img: new ImageData(w, h) };
  }
  const aces = (x) => Math.min(1, Math.max(0, (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)));
  function renderDroneView(scanning) {
    const d = W.drone, du = d.userData;
    droneCam.position.copy(d.position).add(new THREE.Vector3(0, -0.6, 0));
    const ground = scanning ? new THREE.Vector3(d.position.x, 0, d.position.z + 1.5)
      : new THREE.Vector3(d.position.x + (CENTER.x - d.position.x) * 0.25, 0, d.position.z + (CENTER.z - d.position.z) * 0.25 + 4);
    droneCam.lookAt(ground);
    const vis = d.visible; d.visible = false;
    renderer.setRenderTarget(DV.rt);
    renderer.render(W.scene, droneCam);
    renderer.setRenderTarget(null);
    d.visible = vis;
    renderer.readRenderTargetPixels(DV.rt, 0, 0, DV.w, DV.h, DV.buf);
    const out = DV.img.data, b = DV.buf, W4 = DV.w * 4, exp = renderer.toneMappingExposure, k = DV.float ? 1 : 1 / 255;
    for (let y = 0; y < DV.h; y++) {
      const src = (DV.h - 1 - y) * W4, dst = y * W4;
      for (let x = 0; x < W4; x += 4) {
        for (let c = 0; c < 3; c++) out[dst + x + c] = 255 * Math.pow(aces(b[src + x + c] * k * exp * 0.9), 1 / 2.2);
        out[dst + x + 3] = 255;
      }
    }
    DV.ctx.putImageData(DV.img, 0, 0);
  }

  function maybeAuto() {
    if (!auto || !W || fpsT < 5 || autoChecked > 2) return;
    if (fps < 34 && QUALITIES.indexOf(quality) > 0) {
      autoChecked++; fpsT = 0;
      setQuality(QUALITIES[QUALITIES.indexOf(quality) - 1], true);
    } else if (fpsT > 8) autoChecked = 3;
  }

  function setQuality(q, fromAuto = false) {
    if (!fromAuto) auto = q === "auto";
    const next = q === "auto" ? suggestQuality() : q;
    if (!QUALITIES.includes(next)) return;
    quality = next;
    disposeWorld();
    build(quality);
    o.onQuality && o.onQuality(quality, auto);
  }

  build(quality);
  requestAnimationFrame(frame);
  o.onQuality && o.onQuality(quality, auto);

  return {
    setFields, update, setSelected, setAnomaly, scan, hover, addTrial, reset, setOverlay, setLabels, previewPlan, event, view,
    setTime: (k) => applyTime(TIMES[k] ? k : "golden"),
    droneView, setPaused: (p) => { paused = !!p; }, setFollow: (f) => { follow = !!f; }, setQuality, getQuality: () => quality, isAuto: () => auto, getFps: () => fps,
    focus: (i, mode = "field") => views[mode] && views[mode](i),
    home() { rig.mode = "free"; views.home(); },
    dispose() {
      if (DV) { DV.rt.dispose(); DV = null; }
      running = false; ro.disconnect(); controls.dispose(); disposeWorld(); renderer.dispose();
      renderer.domElement.remove(); labels.domElement.remove();
    },
  };
}
