// WorldLab 3D farm: a stylized low-poly desert farm driven by the simulation stream.
// The scene shows the real (hidden) farm, as a camera would see it. The agent never sees this view.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

const PLOT_W = 15, PLOT_D = 10;
const COLS = [-18, 0, 18], ROWS = [-7.5, 7.5];
const LINES = 10, PLANTS = 16;
const TRIAL_Z = -27;

const PALETTES = {
  day: {
    skyTop: "#a9c8ec", skyHorizon: "#f3e6d3", skyBottom: "#e9d4b2", fog: "#efdfc8",
    sun: "#fff3df", sunI: 2.6, hemiSky: "#dcecff", hemiGround: "#c9a97a", hemiI: 1.15,
    sand: ["#e8cfa3", "#e2c393", "#dcb986", "#efd9b3"], pad: "#d8bf98",
  },
  dusk: {
    skyTop: "#1d2546", skyHorizon: "#e2946a", skyBottom: "#3a2f3c", fog: "#8c6a68",
    sun: "#ffc59a", sunI: 1.5, hemiSky: "#6a74b8", hemiGround: "#6b4f3f", hemiI: 0.75,
    sand: ["#b9906f", "#ad8566", "#a27b5e", "#c49c7a"], pad: "#a7866a",
  },
};

const CROP_FORM = {
  wheat: "grass", rice: "grass", millet: "grass", sorghum: "grass",
  maize: "maize", cassava: "cassava",
  potato: "bush", sweet_potato: "vine", soybean: "bush", beans: "bush",
};
const CROP_GREEN = {
  wheat: "#86b04c", rice: "#6fb14f", maize: "#5c9d3b", potato: "#5b9846", cassava: "#4c8b3c",
  soybean: "#6aa647", sorghum: "#7a9f3b", millet: "#8aab48", beans: "#62a144", sweet_potato: "#5a9a50",
};
const CROP_HEIGHT = { grass: 1.0, maize: 2.1, cassava: 1.8, bush: 0.75, vine: 0.45 };
const CEREALS = new Set(["wheat", "rice", "millet", "sorghum", "maize"]);

// ------------------------------------------------------------------ helpers
const C = (h) => new THREE.Color(h);
const lerpC = (a, b, t) => a.clone().lerp(b, Math.min(Math.max(t, 0), 1));
const clamp01 = (x) => Math.min(Math.max(x, 0), 1);
function hash(i) { const s = Math.sin(i * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); }

function noise2(x, z) {
  return Math.sin(x * 0.045 + Math.sin(z * 0.021) * 2.2) * 0.6 + Math.sin(z * 0.06 + x * 0.013) * 0.3
    + Math.sin((x + z) * 0.11) * 0.12;
}

function canvasTexture(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function dashTexture() {
  // gradient runs along v: a cylinder's uv.y follows its length
  const t = canvasTexture(4, 64, (g, w, h) => {
    g.clearRect(0, 0, w, h);
    const grd = g.createLinearGradient(0, 0, 0, h);
    grd.addColorStop(0, "rgba(255,255,255,0)"); grd.addColorStop(0.55, "rgba(255,255,255,0.15)");
    grd.addColorStop(0.8, "rgba(255,255,255,1)"); grd.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grd; g.fillRect(0, 0, w, h);
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

function glowTexture() {
  return canvasTexture(128, 128, (g, w) => {
    const r = g.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2);
    r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.35, "rgba(255,255,255,0.45)");
    r.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = r; g.fillRect(0, 0, w, w);
  });
}

function saltTexture(seed) {
  const t = canvasTexture(256, 160, (g, w, h) => {
    g.clearRect(0, 0, w, h);
    let s = seed;
    const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 900; i++) {
      const x = rnd() * w, y = rnd() * h, r = 1 + rnd() * 6;
      g.fillStyle = `rgba(255,255,255,${0.25 + rnd() * 0.6})`;
      g.beginPath(); g.ellipse(x, y, r * 1.6, r, rnd() * 3, 0, Math.PI * 2); g.fill();
    }
  });
  return t;
}

// ------------------------------------------------------------- crop shapes
function grassGeo() {
  const parts = [];
  for (let k = 0; k < 6; k++) {
    const g = new THREE.ConeGeometry(0.055, 1, 3);
    g.translate(0, 0.5, 0);
    g.rotateZ((k % 2 ? 1 : -1) * (0.12 + 0.05 * k));
    g.rotateY(k * 1.05);
    parts.push(g);
  }
  const head = new THREE.ConeGeometry(0.08, 0.28, 4); head.translate(0, 1.05, 0); parts.push(head);
  return mergeGeometries(parts);
}
function maizeGeo() {
  const parts = [];
  const stalk = new THREE.CylinderGeometry(0.045, 0.07, 1, 5); stalk.translate(0, 0.5, 0); parts.push(stalk);
  for (let k = 0; k < 5; k++) {
    const leaf = new THREE.BoxGeometry(0.55, 0.015, 0.11);
    leaf.translate(0.27, 0, 0); leaf.rotateZ(-0.35 - 0.08 * k); leaf.rotateY(k * 2.4);
    leaf.translate(0, 0.25 + k * 0.15, 0); parts.push(leaf);
  }
  const cob = new THREE.CylinderGeometry(0.05, 0.06, 0.2, 5); cob.rotateZ(0.4); cob.translate(0.08, 0.55, 0); parts.push(cob);
  const tassel = new THREE.ConeGeometry(0.06, 0.18, 4); tassel.translate(0, 1.06, 0); parts.push(tassel);
  return mergeGeometries(parts);
}
function cassavaGeo() {
  const parts = [];
  const stem = new THREE.CylinderGeometry(0.035, 0.05, 0.8, 5); stem.translate(0, 0.4, 0); parts.push(stem);
  for (let k = 0; k < 5; k++) {
    const lf = new THREE.ConeGeometry(0.16, 0.42, 4); lf.rotateZ(Math.PI / 2 + 0.5);
    lf.translate(0.2, 0, 0); lf.rotateY(k * 1.25); lf.translate(0, 0.82, 0); parts.push(lf);
  }
  return mergeGeometries(parts);
}
function bushGeo() {
  const parts = [];
  [[0, 0.32, 0, 0.32], [0.2, 0.22, 0.08, 0.22], [-0.17, 0.2, -0.1, 0.24], [0.02, 0.18, -0.22, 0.2]].forEach(([x, y, z, r]) => {
    const g = new THREE.IcosahedronGeometry(r, 0); g.translate(x, y, z); parts.push(g);
  });
  return mergeGeometries(parts.map((g) => g.toNonIndexed()));
}
function vineGeo() {
  const parts = [];
  for (let k = 0; k < 6; k++) {
    const g = new THREE.IcosahedronGeometry(0.19, 0); g.scale(1.4, 0.6, 1);
    g.translate(Math.cos(k) * 0.28, 0.12, Math.sin(k * 1.7) * 0.25); parts.push(g.toNonIndexed());
  }
  return mergeGeometries(parts);
}

// ------------------------------------------------------------------- scene
export function createScene(container, { onSelect, theme = "day", reducedMotion = false, interactive = true, labels: showLabels = true,
  target = [-2, 0, -4], homePos = [30, 36, 58], shiftX = 0 } = {}) {
  const P = PALETTES[theme] || PALETTES.day;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = theme === "dusk" ? 1.0 : 1.05;
  container.appendChild(renderer.domElement);

  const labels = new CSS2DRenderer();
  labels.domElement.className = "scene-labels";
  if (!showLabels) labels.domElement.style.visibility = "hidden";
  if (!interactive) labels.domElement.style.pointerEvents = "none";
  container.appendChild(labels.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(P.fog, 90, 260);

  const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 800);
  const home = new THREE.Vector3(...homePos);
  camera.position.copy(reducedMotion ? home : new THREE.Vector3(120, 95, 170));

  const controls = new OrbitControls(camera, labels.domElement);
  controls.target.set(...target);
  controls.enabled = interactive;
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.maxPolarAngle = Math.PI * 0.46;
  controls.minDistance = 14;
  controls.maxDistance = 170;
  controls.autoRotateSpeed = 0.35;

  // sky dome
  const sky = new THREE.Mesh(new THREE.SphereGeometry(500, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: C(P.skyTop) }, horizon: { value: C(P.skyHorizon) }, bottom: { value: C(P.skyBottom) }, heat: { value: 0 } },
    vertexShader: "varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }",
    fragmentShader: `uniform vec3 top; uniform vec3 horizon; uniform vec3 bottom; uniform float heat; varying vec3 vP;
      void main(){ float h = vP.y; vec3 c = h > 0.0 ? mix(horizon, top, pow(clamp(h*1.6,0.0,1.0), 0.8)) : mix(horizon, bottom, clamp(-h*4.0,0.0,1.0));
      c = mix(c, vec3(1.0,0.62,0.38), heat*0.35*(1.0-clamp(h*2.0,0.0,1.0))); gl_FragColor = vec4(c,1.0);
      #include <colorspace_fragment>
      }`,
  }));
  scene.add(sky);

  // light
  const hemi = new THREE.HemisphereLight(P.hemiSky, P.hemiGround, P.hemiI);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(P.sun, P.sunI);
  sun.position.set(-45, 70, 35);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -62, right: 62, top: 50, bottom: -50, near: 10, far: 200 });
  sun.shadow.camera.updateProjectionMatrix();
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.04;
  scene.add(sun);

  // ------------------------------------------------------------ terrain
  {
    const g = new THREE.PlaneGeometry(520, 520, 150, 150);
    g.rotateX(-Math.PI / 2);
    const pos = g.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), z = pos.getZ(i);
      const r = Math.hypot(x / 1.25, z);
      const w = THREE.MathUtils.smoothstep(r, 46, 110);
      const dune = Math.max(0, noise2(x, z) + 0.35) * 9 + Math.abs(Math.sin(x * 0.03 + z * 0.012)) * 4;
      pos.setY(i, -0.05 + w * dune + (hash(i) - 0.5) * 0.25 * w);
    }
    const geo = g.toNonIndexed();
    geo.computeVertexNormals();
    const cols = new Float32Array(geo.attributes.position.count * 3);
    const sands = P.sand.map(C);
    for (let f = 0; f < geo.attributes.position.count / 3; f++) {
      const c = sands[Math.floor(hash(f * 3.7) * sands.length)];
      for (let k = 0; k < 3; k++) cols.set([c.r, c.g, c.b], (f * 3 + k) * 3);
    }
    geo.setAttribute("color", new THREE.BufferAttribute(cols, 3));
    const ground = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 1 }));
    ground.receiveShadow = true;
    scene.add(ground);

    const pad = new THREE.Mesh(new THREE.BoxGeometry(104, 0.12, 74), new THREE.MeshStandardMaterial({ color: P.pad, roughness: 1 }));
    pad.position.set(-4, 0.02, -6);
    pad.receiveShadow = true;
    scene.add(pad);
  }

  const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.85, flatShading: true, ...extra });
  const glowTex = glowTexture();
  const DASH = dashTexture();
  const anim = [];      // per-frame callbacks

  // -------------------------------------------------------- equipment
  const equip = new THREE.Group();
  equip.position.set(-40, 0, 0);
  scene.add(equip);
  const flowParts = [];
  {
    const house = new THREE.Mesh(new THREE.BoxGeometry(6, 3.4, 5), mat("#efe6d8"));
    house.position.set(0, 1.7, -6); house.castShadow = house.receiveShadow = true; equip.add(house);
    const roof = new THREE.Mesh(new THREE.BoxGeometry(6.6, 0.35, 5.6), mat("#c9b9a3"));
    roof.position.set(0, 3.55, -6); roof.castShadow = true; equip.add(roof);
    const door = new THREE.Mesh(new THREE.BoxGeometry(0.1, 2, 1.3), mat("#7b8796"));
    door.position.set(3.02, 1, -6); equip.add(door);
    const panel = new THREE.Mesh(new THREE.BoxGeometry(5.2, 0.12, 3.2), mat("#2f3b55", { roughness: 0.35, metalness: 0.3 }));
    panel.position.set(0, 3.95, -6); panel.rotation.x = -0.25; equip.add(panel);

    // reverse-osmosis skid: pressure vessels that glow teal while desalting
    const ro = new THREE.Group(); ro.position.set(0, 0, 3); equip.add(ro);
    const skid = new THREE.Mesh(new THREE.BoxGeometry(6, 0.5, 3.4), mat("#9aa5b4")); skid.position.y = 0.25; skid.castShadow = true; ro.add(skid);
    const roMat = new THREE.MeshStandardMaterial({ color: "#e9f3f5", emissive: "#19b5c7", emissiveIntensity: 0.0, roughness: 0.4, metalness: 0.2 });
    for (let k = 0; k < 3; k++) {
      const v = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.42, 5.4, 10), roMat);
      v.rotation.z = Math.PI / 2; v.position.set(0, 1.0 + k * 0.9, 0); v.castShadow = true; ro.add(v);
    }
    const roGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: "#2fd3e0", transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending }));
    roGlow.scale.set(9, 6, 1); roGlow.position.set(0, 2, 0); ro.add(roGlow);
    flowParts.push({ kind: "ro", mat: roMat, glow: roGlow });

    // elevated tank
    const tank = new THREE.Group(); tank.position.set(4, 0, 11); equip.add(tank);
    for (const [x, z] of [[-1.3, -1.3], [1.3, -1.3], [-1.3, 1.3], [1.3, 1.3]]) {
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 5, 5), mat("#8b96a6")); leg.position.set(x, 2.5, z); leg.castShadow = true; tank.add(leg);
    }
    const drum = new THREE.Mesh(new THREE.CylinderGeometry(2.1, 2.1, 3, 14), mat("#f4f1ea")); drum.position.y = 6.5; drum.castShadow = true; tank.add(drum);
    const cap = new THREE.Mesh(new THREE.ConeGeometry(2.25, 0.9, 14), mat("#cdd5de")); cap.position.y = 8.45; tank.add(cap);
    const band = new THREE.Mesh(new THREE.CylinderGeometry(2.14, 2.14, 0.35, 14), new THREE.MeshStandardMaterial({ color: "#19b5c7", emissive: "#19b5c7", emissiveIntensity: 0.35 }));
    band.position.y = 6.1; tank.add(band);

    // weather mast
    const mast = new THREE.Group(); mast.position.set(-2, 0, 18); equip.add(mast);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 7, 6), mat("#aab3bf")); pole.position.y = 3.5; pole.castShadow = true; mast.add(pole);
    const cups = new THREE.Group(); cups.position.y = 7.1; mast.add(cups);
    for (let k = 0; k < 3; k++) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.04, 0.04), mat("#aab3bf")); arm.position.x = 0.45; arm.rotation.y = 0;
      const cup = new THREE.Mesh(new THREE.SphereGeometry(0.13, 6, 4, 0, Math.PI), mat("#f2f2f2")); cup.position.x = 0.9; cup.rotation.y = Math.PI / 2;
      const a = new THREE.Group(); a.add(arm, cup); a.rotation.y = (k * Math.PI * 2) / 3; cups.add(a);
    }
    const vane = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.4, 0.03), mat("#ef8a2b")); vane.position.set(0.5, 6.4, 0); mast.add(vane);
    anim.push((dt, t) => { cups.rotation.y += dt * (2 + 1.5 * Math.sin(t * 0.3)); });
  }

  // ---------------------------------------------------------- pipes
  const pipeMat = mat("#5b6b80", { roughness: 0.5, metalness: 0.2 });
  function flowLine(len, radius, color) {
    const tex = DASH.clone(); tex.needsUpdate = true;
    tex.repeat.set(1, Math.max(1, len / 2.2));
    const m = new THREE.MeshBasicMaterial({ map: tex, color, transparent: true, opacity: 0.0, depthWrite: false, blending: THREE.AdditiveBlending });
    const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius * 1.25, radius * 1.25, len, 6, 1, true), m);
    return { mesh, tex, m };
  }
  const mains = [];
  {
    // main header from the pump house to the far plots, between the two rows
    const len = 70;
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, len, 8), pipeMat);
    body.rotation.z = Math.PI / 2; body.position.set(-5, 0.35, 0); body.castShadow = true; scene.add(body);
    const fl = flowLine(len, 0.3, "#3fe0ef"); fl.mesh.rotation.z = Math.PI / 2; fl.mesh.position.copy(body.position); scene.add(fl.mesh);
    mains.push(fl);
    const feed = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 10, 8), pipeMat);
    feed.rotation.x = Math.PI / 2; feed.position.set(-40, 0.35, 5); scene.add(feed);
  }

  // ------------------------------------------------------------- plots
  const geos = { grass: grassGeo(), maize: maizeGeo(), cassava: cassavaGeo(), bush: bushGeo(), vine: vineGeo() };
  const plantMat = new THREE.MeshStandardMaterial({ roughness: 0.8, flatShading: true });
  const plots = [];
  const pickables = [];
  const soilDry = C("#dcc195"), soilWet = C("#8a6646"), saltC = C("#f6f3ec");
  for (let i = 0; i < 6; i++) {
    const g = new THREE.Group();
    g.position.set(COLS[i % 3], 0, ROWS[Math.floor(i / 3)]);
    scene.add(g);
    const soilMat = new THREE.MeshStandardMaterial({ color: soilDry.clone(), roughness: 1, flatShading: true });
    const soil = new THREE.Mesh(new THREE.BoxGeometry(PLOT_W, 0.36, PLOT_D), soilMat);
    soil.position.y = 0.18; soil.receiveShadow = true; soil.userData.field = i; g.add(soil);
    pickables.push(soil);
    // berms
    const bermMat = mat("#cdb084");
    for (const [w, d, x, z] of [[PLOT_W + 0.6, 0.3, 0, -PLOT_D / 2 - 0.15], [PLOT_W + 0.6, 0.3, 0, PLOT_D / 2 + 0.15], [0.3, PLOT_D, -PLOT_W / 2 - 0.15, 0], [0.3, PLOT_D, PLOT_W / 2 + 0.15, 0]]) {
      const b = new THREE.Mesh(new THREE.BoxGeometry(w, 0.55, d), bermMat); b.position.set(x, 0.27, z); b.castShadow = true; b.receiveShadow = true; g.add(b);
    }
    const saltMat = new THREE.MeshBasicMaterial({ map: saltTexture(17 + i * 29), transparent: true, opacity: 0, depthWrite: false });
    const salt = new THREE.Mesh(new THREE.PlaneGeometry(PLOT_W, PLOT_D), saltMat);
    salt.rotation.x = -Math.PI / 2; salt.position.y = 0.375; g.add(salt);

    // drip laterals run north-south, fed from the header between the rows
    const lines = [];
    for (let k = 0; k < LINES; k++) {
      const x = -PLOT_W / 2 + 0.75 + (k * (PLOT_W - 1.5)) / (LINES - 1);
      const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, PLOT_D - 0.4, 5), new THREE.MeshStandardMaterial({ color: "#2b3442", roughness: 0.6 }));
      tube.rotation.x = Math.PI / 2; tube.position.set(x, 0.42, 0); g.add(tube);
      const fl = flowLine(PLOT_D - 0.4, 0.05, "#45e3f0");
      fl.mesh.rotation.x = Math.PI / 2; fl.mesh.position.set(x, 0.42, 0); g.add(fl.mesh);
      fl.dir = i < 3 ? -1 : 1;       // water flows away from the header
      lines.push(fl);
    }
    // plants
    const plant = {};
    for (const form of Object.keys(geos)) {
      const im = new THREE.InstancedMesh(geos[form], plantMat, LINES * PLANTS);
      im.castShadow = true; im.receiveShadow = false; im.visible = false; im.count = LINES * PLANTS;
      im.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      im.userData.field = i;
      g.add(im); plant[form] = im;
      const col = new THREE.Color("#6aa34a");
      for (let n = 0; n < LINES * PLANTS; n++) im.setColorAt(n, col);
    }
    // label
    const tag = document.createElement("div");
    tag.className = "plot-tag";
    tag.innerHTML = `<span class="pt-id"></span><span class="pt-crop"></span>`;
    tag.addEventListener("click", () => onSelect && onSelect(i));
    const tagObj = new CSS2DObject(tag);
    tagObj.position.set(0, 3.4, i < 3 ? -PLOT_D / 2 : PLOT_D / 2);
    g.add(tagObj);
    // selection frame
    const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(PLOT_W + 1.6, 1.4, PLOT_D + 1.6)),
      new THREE.LineBasicMaterial({ color: "#7a68ff", transparent: true, opacity: 0.0 }));
    frame.position.y = 0.6; g.add(frame);
    const selGlow = new THREE.Mesh(new THREE.PlaneGeometry(PLOT_W + 9, PLOT_D + 9), new THREE.MeshBasicMaterial({ map: glowTex, color: "#7a68ff", transparent: true, opacity: 0, depthWrite: false }));
    selGlow.rotation.x = -Math.PI / 2; selGlow.position.y = 0.09; g.add(selGlow);
    // alarm ring
    const ring = new THREE.Mesh(new THREE.RingGeometry(9.6, 10.3, 48), new THREE.MeshBasicMaterial({ color: "#e5484d", transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.5; ring.scale.set(1, 0.72, 1); g.add(ring);
    const alarmTag = document.createElement("div"); alarmTag.className = "alarm-tag";
    const alarmObj = new CSS2DObject(alarmTag); alarmObj.position.set(0, 6.2, 0); alarmObj.visible = false; g.add(alarmObj);

    plots.push({ g, soilMat, saltMat, lines, plant, tag, frame, selGlow, ring, alarmTag, alarmObj, crop: null, form: null,
      seed: i * 1000, state: null, target: null, wet: 0, salt: 0, flow: 0, deliver: 1 });
  }

  // --------------------------------------------------------------- palms
  {
    const trunkMat = mat("#9a7a52"), frondMat = mat("#4f8a3c"), frondMat2 = mat("#5f9a45");
    const frond = new THREE.ConeGeometry(0.5, 3.6, 3); frond.scale(1, 1, 0.2); frond.translate(0, 1.8, 0); frond.rotateZ(-1.15);
    const palm = (x, z, s) => {
      const p = new THREE.Group(); p.position.set(x, 0, z); p.scale.setScalar(s); p.rotation.y = hash(x * z) * 6;
      let y = 0; const lean = (hash(x + z) - 0.5) * 0.25;
      for (let k = 0; k < 6; k++) {
        const seg = new THREE.Mesh(new THREE.CylinderGeometry(0.26 - k * 0.02, 0.32 - k * 0.02, 1.25, 6), trunkMat);
        seg.position.set(lean * y, y + 0.62, 0); seg.castShadow = true; p.add(seg); y += 1.15;
      }
      for (let k = 0; k < 8; k++) {
        const f = new THREE.Mesh(frond, k % 2 ? frondMat : frondMat2);
        f.position.set(lean * y, y + 0.2, 0); f.rotation.y = (k / 8) * Math.PI * 2 + hash(k + x) * 0.3; f.castShadow = true; p.add(f);
      }
      scene.add(p);
      return p;
    };
    for (let x = -46; x <= 40; x += 5.5) palm(x + hash(x) * 2, -40 + hash(x * 3) * 2.5, 0.95 + hash(x * 7) * 0.35);
    for (let z = -32; z <= 26; z += 6) palm(-58 + hash(z) * 2, z, 0.9 + hash(z * 5) * 0.3);
    for (const [x, z] of [[-2, -16.5], [5, -17], [-8, -17.2], [33, 24], [-28, 26], [44, -12]]) palm(x, z, 0.85 + hash(x + z) * 0.3);
  }

  // ----------------------------------------------------------- trial strip
  const trialGroup = new THREE.Group(); trialGroup.position.set(-2, 0, TRIAL_Z); scene.add(trialGroup);
  const trialSlots = [];
  {
    const base = new THREE.Mesh(new THREE.BoxGeometry(46, 0.14, 8.6), mat("#d2b78e")); base.position.y = 0.07; base.receiveShadow = true; trialGroup.add(base);
    for (let k = 0; k < 16; k++) {
      const x = -19.6 + (k % 8) * 5.6, z = k < 8 ? -2 : 2.1;
      const pm = new THREE.Mesh(new THREE.BoxGeometry(4.4, 0.25, 3.2), mat("#ccb083"));
      pm.position.set(x, 0.2, z); pm.receiveShadow = true; trialGroup.add(pm);
      trialSlots.push({ x, z, mesh: pm, used: false, objs: [] });
    }
    const tt = document.createElement("div"); tt.className = "area-tag"; tt.textContent = "Trial plots";
    const to = new CSS2DObject(tt); to.position.set(-26.5, 1.2, 0); trialGroup.add(to);
  }

  // ---------------------------------------------------------------- drone
  const drone = new THREE.Group();
  const rotors = [];
  {
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.28, 0.9), mat("#f4f6f9", { roughness: 0.4 }));
    drone.add(body);
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.16, 8, 6), new THREE.MeshStandardMaterial({ color: "#1e2533", emissive: "#7a68ff", emissiveIntensity: 0.8 }));
    eye.position.set(0, -0.18, 0.3); drone.add(eye);
    for (const [x, z] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.07, 0.1), mat("#b9c1cc"));
      arm.position.set(x * 0.5, 0.05, z * 0.5); arm.rotation.y = Math.atan2(z, -x) ; drone.add(arm);
      const rotor = new THREE.Mesh(new THREE.BoxGeometry(0.95, 0.02, 0.09), new THREE.MeshStandardMaterial({ color: "#2b3442", transparent: true, opacity: 0.7 }));
      rotor.position.set(x * 0.95, 0.15, z * 0.95); drone.add(rotor); rotors.push(rotor);
    }
    const cone = new THREE.Mesh(new THREE.ConeGeometry(5.5, 9, 24, 1, true), new THREE.MeshBasicMaterial({ color: "#8d7bff", transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
    cone.position.y = -4.6; drone.add(cone);
    drone.userData.cone = cone;
    drone.position.set(-40, 6, -6);
    drone.scale.setScalar(1.25);
    scene.add(drone);
  }
  const droneTarget = new THREE.Vector3(-38, 8, -6);
  let scanUntil = 0, droneHomeAt = 0;

  // --------------------------------------------------------- state & API
  const sph = new THREE.Spherical();
  let swaying = false, swayT = 0, swayBase = 0;
  let selected = -1, heat = 0, heatTarget = 0, clock = 0, lastInteract = performance.now(), intro = reducedMotion ? 1 : 0;
  const introFrom = camera.position.clone();

  function placePlants(p, w, dt) {
    const form = p.form;
    if (!form) return;
    const im = p.plant[form];
    const H = CROP_HEIGHT[form];
    const green = C(CROP_GREEN[p.crop] || "#6aa34a");
    const stress = C("#cdb55c"), ripe = C("#d9b552"), dead = C("#8d6a3e"), stubble = C("#cdb27a");
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3();
    const st = p.state;
    const sown = w.sown, done = w.done;
    const stage = w.stage || 0;
    const hgt = done ? 0.12 : sown ? Math.max(0.04, Math.pow(clamp01(stage / 0.55), 0.85)) : 0;
    const wid = done ? 0.5 : 0.3 + 0.7 * clamp01((w.cc || 0) / 0.8);
    let color = green.clone();
    color = lerpC(color, stress, (1 - (w.ksw ?? 1)) * 1.4);
    if (CEREALS.has(p.crop)) color = lerpC(color, ripe, (stage - 0.72) / 0.25);
    color = lerpC(color, dead, (w.pest || 0) * 30);
    if (done) color = stubble;
    const stand = w.stand ?? 1;
    let n = 0;
    for (let k = 0; k < LINES; k++) {
      const x = -PLOT_W / 2 + 0.75 + (k * (PLOT_W - 1.5)) / (LINES - 1);
      for (let j = 0; j < PLANTS; j++) {
        const id = p.seed + n;
        const z = -PLOT_D / 2 + 0.55 + (j * (PLOT_D - 1.1)) / (PLANTS - 1) + (hash(id * 1.3) - 0.5) * 0.2;
        const xx = x + 0.22 + (hash(id * 2.1) - 0.5) * 0.14;
        const alive = hash(id * 4.7) < stand;
        const jit = 0.85 + hash(id * 3.3) * 0.3;
        const sc = alive ? jit : 0;
        q.setFromAxisAngle(v.set(0, 1, 0), hash(id * 5.9) * Math.PI * 2);
        s.set(wid * sc, H * hgt * sc + 1e-4, wid * sc);
        m.compose(v.set(xx, 0.36, z), q, s);
        im.setMatrixAt(n, m);
        const c = color.clone().offsetHSL((hash(id * 6.1) - 0.5) * 0.03, 0, (hash(id * 7.7) - 0.5) * 0.08);
        im.setColorAt(n, c);
        n++;
      }
    }
    im.instanceMatrix.needsUpdate = true;
    if (im.instanceColor) im.instanceColor.needsUpdate = true;
  }

  function setFields(fields) {
    fields.forEach((f, i) => {
      const p = plots[i];
      const crop = f.crop || null;
      p.crop = crop;
      p.form = crop ? CROP_FORM[crop] : null;
      for (const [form, im] of Object.entries(p.plant)) im.visible = form === p.form;
      p.tag.querySelector(".pt-id").textContent = f.id || `F${i + 1}`;
      p.tag.querySelector(".pt-crop").textContent = f.label || (crop ? crop : "Fallow");
      p.tag.classList.toggle("fallow", !crop);
      if (crop) placePlants(p, { sown: false, stage: 0, cc: 0 }, 0);
    });
  }

  function update(rec) {
    if (!rec || !rec.world) return;
    let flowTot = 0, desalTot = 0, nAct = 0;
    rec.world.forEach((w, i) => {
      const p = plots[i]; const f = rec.fields[i] || {};
      p.state = w;
      // soil: darker when wet, crusted white when salty
      const sw = f.sw_obs ?? w.theta_top ?? 0.12;
      p.wet = clamp01((sw - 0.05) / 0.22);
      p.salt = clamp01(((w.ece_top ?? 2) - 3.5) / 9);
      p.flow = clamp01((f.irr_mm || 0) / 9);
      p.deliver = w.deliver ?? 1;
      if (p.flow > 0) { flowTot += p.flow; desalTot += f.desal || 0; nAct++; }
      placePlants(p, w);
    });
    const mainFlow = clamp01(flowTot / 3);
    mains.forEach((m) => (m.target = mainFlow));
    const desal = nAct ? desalTot / nAct : 0;
    flowParts.forEach((fp) => { fp.target = mainFlow > 0 ? desal : 0; });
    heatTarget = clamp01(((rec.tmax ?? 30) - 39) / 6);
  }

  function setSelected(i) {
    selected = i;
    plots.forEach((p, k) => p.tag.classList.toggle("selected", k === i));
  }

  function setAnomaly(i, text) {
    plots.forEach((p, k) => {
      const on = k === i;
      p.alarm = on;
      p.alarmObj.visible = on && !!text;      // CSS2DRenderer owns style.display
      if (on && text) p.alarmTag.textContent = text;
      p.tag.classList.toggle("alarm", on);
    });
  }

  function scan(i) {
    if (i == null || i < 0) return;
    const p = plots[i];
    droneTarget.set(p.g.position.x, 9.5, p.g.position.z);
    scanUntil = clock + 3.2;
    droneHomeAt = clock + 7;
  }

  function hover(i) {
    if (i == null || i < 0 || clock < scanUntil) return;
    const p = plots[i];
    droneTarget.set(p.g.position.x + 3, 11, p.g.position.z + 2);
    droneHomeAt = clock + 2.5;
  }

  function addTrial(t) {
    const slot = trialSlots.find((s) => !s.used);
    if (!slot) return;
    slot.used = true;
    const form = CROP_FORM[t.crop] || "bush";
    const ratio = t.predicted_yield_median > 0 ? t.measured_yield_t_ha / t.predicted_yield_median : 1;
    const im = new THREE.InstancedMesh(geos[form], plantMat, 24);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), s = new THREE.Vector3();
    const col = lerpC(C(CROP_GREEN[t.crop] || "#6aa34a"), C("#cdb55c"), 1 - Math.min(ratio, 1));
    const hgt = CROP_HEIGHT[form] * (0.45 + 0.55 * Math.min(ratio, 1.2));
    for (let n = 0; n < 24; n++) {
      q.setFromAxisAngle(v.set(0, 1, 0), hash(n * 9 + slot.x) * 6.28);
      s.set(0.8, hgt, 0.8);
      m.compose(v.set(slot.x - 1.8 + (n % 6) * 0.72, 0.32, slot.z - 1.1 + Math.floor(n / 6) * 0.72), q, s);
      im.setMatrixAt(n, m); im.setColorAt(n, col);
    }
    im.castShadow = true;
    trialGroup.add(im);
    const ring = new THREE.Mesh(new THREE.RingGeometry(2.55, 2.85, 32), new THREE.MeshBasicMaterial({ color: t.prediction_held ? "#2e9e6a" : "#f08c2e", transparent: true, opacity: 0.9, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.set(slot.x, 0.36, slot.z); ring.scale.set(1, 0.72, 1);
    trialGroup.add(ring);
    slot.mesh.material = mat(t.plot === "saline" ? "#e7dfcf" : "#b08b5f");
    if (!t.prediction_held) {
      const d = document.createElement("div"); d.className = "trial-tag missed"; d.textContent = "Prediction missed";
      const o = new CSS2DObject(d); o.position.set(slot.x, 2.6, slot.z); trialGroup.add(o); slot.objs.push(o);
    }
    slot.objs.push(im, ring);
    droneTarget.set(-2 + slot.x, 8, TRIAL_Z + slot.z); droneHomeAt = clock + 2;
  }

  function reset() {
    trialSlots.forEach((s) => { s.objs.forEach((o) => { trialGroup.remove(o); if (o.element) o.element.remove(); }); s.objs = []; s.used = false; s.mesh.material = mat("#ccb083"); });
    plots.forEach((p) => { p.crop = null; p.form = null; p.state = null; p.flow = 0; p.wet = 0; p.salt = 0; for (const im of Object.values(p.plant)) im.visible = false; });
    setFields([0, 1, 2, 3, 4, 5].map((i) => ({ id: `F${i + 1}`, crop: null, label: "Not planned" })));
    setAnomaly(-1);
  }

  // ------------------------------------------------------------ picking
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let downAt = null;
  labels.domElement.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; lastInteract = performance.now(); swaying = false; });
  labels.domElement.addEventListener("pointerup", (e) => {
    if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(pickables, false)[0];
    if (hit && onSelect) onSelect(hit.object.userData.field);
  });
  labels.domElement.addEventListener("wheel", () => { lastInteract = performance.now(); swaying = false; }, { passive: true });

  // -------------------------------------------------------------- render
  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    renderer.setSize(w, h, false);
    labels.setSize(w, h);
    camera.aspect = w / Math.max(h, 1);
    const sx = typeof shiftX === "function" ? shiftX(w, h) : shiftX;
    if (sx) camera.setViewOffset(w, h, -sx * w, 0, w, h); else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  const t0 = performance.now();
  let last = t0, running = true;
  const soilTmp = new THREE.Color();
  function frame(now) {
    if (!running) return;
    const dt = Math.min((now - last) / 1000, 0.05); last = now; clock += dt;
    // one orchestrated arrival: fly in from the dunes
    if (intro < 1) {
      intro = Math.min(1, intro + dt / 2.8);
      const e = 1 - Math.pow(1 - intro, 3);
      camera.position.lerpVectors(introFrom, home, e);
    }
    // When idle, sway gently around the current view instead of orbiting, so palms never swing in front of the farm.
    if (!reducedMotion && intro >= 1 && (!interactive || performance.now() - lastInteract > 12000)) {
      sph.setFromVector3(camera.position.clone().sub(controls.target));
      if (!swaying) { swaying = true; swayT = 0; swayBase = sph.theta; }
      swayT += dt;
      sph.theta = swayBase + 0.32 * Math.sin(swayT * 0.13);
      camera.position.setFromSpherical(sph).add(controls.target);
    }
    controls.update();

    heat += (heatTarget - heat) * Math.min(1, dt * 1.5);
    sky.material.uniforms.heat.value = heat;
    scene.fog.color.copy(C(P.fog)).lerp(C("#f1b48a"), heat * 0.35);

    for (const [k, p] of plots.entries()) {
      soilTmp.copy(soilDry).lerp(soilWet, p.wet * 0.85).lerp(saltC, p.salt * 0.35);
      p.soilMat.color.lerp(soilTmp, Math.min(1, dt * 4));
      p.saltMat.opacity += (p.salt * 0.85 - p.saltMat.opacity) * Math.min(1, dt * 3);
      const clogged = p.deliver < 0.9;
      for (const ln of p.lines) {
        const target = p.flow * (clogged ? 0.35 : 1);
        ln.m.opacity += (target * 0.95 - ln.m.opacity) * Math.min(1, dt * 4);
        ln.m.color.set(clogged ? "#ff6b5e" : "#45e3f0");
        if (!reducedMotion) ln.tex.offset.y += dt * ln.dir * (clogged ? 0.25 : 0.9);
      }
      const sel = k === selected;
      p.frame.material.opacity += ((sel ? 0.95 : 0) - p.frame.material.opacity) * Math.min(1, dt * 6);
      p.selGlow.material.opacity += ((sel ? 0.28 : 0) - p.selGlow.material.opacity) * Math.min(1, dt * 6);
      const pulse = p.alarm ? 0.55 + 0.45 * Math.sin(clock * 5) : 0;
      p.ring.material.opacity += (pulse - p.ring.material.opacity) * Math.min(1, dt * 8);
      const rs = p.alarm && !reducedMotion ? 1 + 0.04 * Math.sin(clock * 5) : 1;
      p.ring.scale.set(rs, 0.72 * rs, rs);
    }
    for (const m of mains) {
      m.m.opacity += ((m.target || 0) * 0.9 - m.m.opacity) * Math.min(1, dt * 3);
      if (!reducedMotion) m.tex.offset.y -= dt * 1.4;
    }
    for (const fp of flowParts) {
      const tv = fp.target || 0;
      fp.mat.emissiveIntensity += (tv * 1.2 - fp.mat.emissiveIntensity) * Math.min(1, dt * 3);
      fp.glow.material.opacity += (tv * 0.55 - fp.glow.material.opacity) * Math.min(1, dt * 3);
    }
    // drone
    if (clock > droneHomeAt) droneTarget.set(-34, 8 + Math.sin(clock * 0.4), -4);
    drone.position.lerp(droneTarget, Math.min(1, dt * 1.1));
    drone.position.y += Math.sin(clock * 2.1) * 0.01;
    drone.rotation.z = THREE.MathUtils.clamp((droneTarget.x - drone.position.x) * -0.02, -0.25, 0.25);
    rotors.forEach((r, k) => (r.rotation.y += dt * (k % 2 ? 40 : -40)));
    const cone = drone.userData.cone;
    cone.material.opacity += ((clock < scanUntil ? 0.16 + 0.05 * Math.sin(clock * 9) : 0) - cone.material.opacity) * Math.min(1, dt * 5);
    anim.forEach((f) => f(dt, clock));

    renderer.render(scene, camera);
    labels.render(scene, camera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  reset();

  return {
    setFields, update, setSelected, setAnomaly, scan, hover, addTrial, reset,
    home() { intro = 0; introFrom.copy(camera.position); controls.target.set(...target); },
    dispose() { running = false; renderer.dispose(); },
  };
}
