// Crop portraits: small pictures of each crop rendered from the same 3D models that grow in the fields,
// at the growth stage the field is in. One offscreen renderer, results cached as image URLs.
import * as THREE from "three";
import { cropGeometry, cropMaterial, CROP_INFO } from "./crops.js?v=3e51a05a34";

let R = null;
const cache = new Map();

function setup() {
  const canvas = document.createElement("canvas");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight("#e4efff", "#8a6a44", 1.5));
  const sun = new THREE.DirectionalLight("#fff0d2", 2.6); sun.position.set(3, 6, 4); scene.add(sun);
  const rim = new THREE.DirectionalLight("#9fd8ff", 0.8); rim.position.set(-4, 3, -5); scene.add(rim);
  const soil = new THREE.Mesh(new THREE.CircleGeometry(1, 48), new THREE.MeshStandardMaterial({ color: "#7a5636", roughness: 1 }));
  soil.rotation.x = -Math.PI / 2; scene.add(soil);
  const camera = new THREE.PerspectiveCamera(28, 1, 0.01, 100);
  const material = cropMaterial({ time: { value: 0 }, wind: { value: 0 } });
  R = { renderer, scene, camera, soil, material };
}

// stage: 0 seedling, 1 growing, 2 flowering, 3 ripening, 4 harvested. Returns a PNG data URL, or null without WebGL.
export function cropPortrait(crop, stage = 2, size = 128) {
  if (!crop || !CROP_INFO[crop]) return null;
  const key = `${crop}:${stage}:${size}`;
  if (cache.has(key)) return cache.get(key);
  let url = null;
  try {
    if (!R) setup();
    const { renderer, scene, camera, soil, material } = R;
    const geo = cropGeometry(crop, stage);
    geo.computeBoundingBox();
    const bb = geo.boundingBox, h = Math.max(bb.max.y, 0.12), w = Math.max(bb.max.x - bb.min.x, bb.max.z - bb.min.z, 0.12);
    const gap = w * 0.85, n = CROP_INFO[crop].big ? 5 : 7;
    const spots = [[0, 0], [gap, -gap * 0.4], [-gap, -gap * 0.3], [gap * 0.5, -gap * 1.3], [-gap * 0.6, -gap * 1.25], [gap * 1.6, -gap * 1.4], [-gap * 1.7, -gap * 1.2]].slice(0, n);
    const im = new THREE.InstancedMesh(geo, material, n);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), up = new THREE.Vector3(0, 1, 0);
    spots.forEach(([x, z], k) => {
      const s = 0.85 + ((k * 37) % 10) / 33;
      q.setFromAxisAngle(up, k * 1.7);
      m.compose(new THREE.Vector3(x, 0, z), q, new THREE.Vector3(s, s, s));
      im.setMatrixAt(k, m);
      im.setColorAt(k, new THREE.Color(1, 1, 1).multiplyScalar(0.94 + (k % 3) * 0.04));
    });
    scene.add(im);
    soil.scale.setScalar(gap * 2.6 + w);
    soil.position.z = -gap * 0.6;
    const span = Math.max(h * 1.15, (gap * 2 + w) * 0.62);
    const dist = span / (2 * Math.tan(THREE.MathUtils.degToRad(14)));
    const look = new THREE.Vector3(0, h * 0.45, -gap * 0.5);
    camera.position.copy(look).add(new THREE.Vector3(Math.sin(0.55) * dist, dist * 0.32, Math.cos(0.55) * dist));
    camera.lookAt(look);
    camera.near = dist / 50; camera.far = dist * 10; camera.updateProjectionMatrix();
    renderer.setSize(size * 2, size * 2, false);
    renderer.setClearColor(0x000000, 0);
    renderer.render(scene, camera);
    url = renderer.domElement.toDataURL("image/png");
    scene.remove(im); im.dispose();
  } catch (e) {
    console.warn("Crop portrait unavailable:", e);
  }
  cache.set(key, url);
  return url;
}

// Which model stage a field shows, from the simulator's world state (same thresholds as the field crop).
export function stageOf(crop, w) {
  if (!w || !w.sown) return 2;
  if (w.done) return 4;
  const f = w.stage || 0, fl = CROP_INFO[crop] ? CROP_INFO[crop].flower : [0.5, 0.6];
  return f < 0.22 ? 0 : f < fl[0] - 0.02 ? 1 : f < fl[1] + 0.12 ? 2 : 3;
}
