// Landing hero: the real 3D farm, replaying a recorded season on a loop.
const base = document.body.dataset.app || "";
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function hero() {
  const el = document.getElementById("heroScene");
  if (!el) return;
  // 1. the recorded season's numbers, independent of the 3D view
  let data = null;
  try { data = await fetch(`${base}replay.json`).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  catch (e) { console.warn("Recording unavailable:", e); }
  if (data) worldStatus(data.messages || data);
  // 2. the 3D flyover; anything that fails falls back to a still image of the same farm
  let scene = null;
  try {
    if (!data) throw new Error("no recording");
    const mod = await import(`./${base}scene.js?v=9ac5d4508e`);
    scene = mod.createScene(el, { time: "golden", reducedMotion: reduced, interactive: false, labels: false, flyover: true,
      homePos: [46, 26, 58], shiftX: (w) => (w > 960 ? 0.2 : w > 600 ? 0.26 : 0), onFps: (f, q) => { window.__wlFps = [Math.round(f), q]; } });
  } catch (e) {
    console.warn("Hero scene unavailable:", e);
    stillHero();
    return;
  }
  window.__wlScene = scene;
  if ("IntersectionObserver" in window && scene.setPaused) {          // stop drawing when the hero is off screen
    new IntersectionObserver(([en]) => scene.setPaused(!en.isIntersecting)).observe(el);
  }
  const msgs = data.messages || data;
  const fields = msgs.find((m) => m.kind === "fields");
  const trials = msgs.filter((m) => m.kind === "trials").map((m) => m.data);
  const timeline = msgs.filter((m) => m.kind === "day" || (m.kind === "status" && m.data.phase === "season"));
  let i = 0, t = 0, last = performance.now(), stage = "trials", hold = 0;
  const restart = () => { scene.reset(); i = 0; stage = "trials"; hold = 0; };
  restart();
  if (reduced) {           // one still frame, mid-season
    if (fields) scene.setFields(fields.data);
    const mid = msgs.filter((m) => m.kind === "day")[110];
    if (mid) scene.update(mid.data);
    return;
  }
  const tick = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000); last = now; t += dt;
    if (stage === "trials") {
      hold += dt;
      const n = Math.min(trials.length, Math.floor(hold / 0.25));
      while (i < n) scene.addTrial(trials[i++]);
      if (n >= trials.length && hold > trials.length * 0.25 + 1) { stage = "season"; i = 0; hold = 0; if (fields) scene.setFields(fields.data); }
    } else if (stage === "season") {
      hold += dt;
      while (hold > 0.09 && i < timeline.length) {
        hold -= 0.09;
        const m = timeline[i++];
        if (m.kind === "day") scene.update(m.data);
        else { const a = m.data.anomaly; scene.setAnomaly(a ? a.field_index : -1, ""); }
      }
      if (i >= timeline.length) { stage = "end"; hold = 0; }
    } else if ((hold += dt) > 4) restart();
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
// The strip under the hero: numbers from the recorded season's ledger, never invented.
function worldStatus(msgs) {
  const box = document.getElementById("worldStatus");
  if (!box) return;
  const fmt = (x) => Math.round(x).toLocaleString("en-US");
  const res = msgs.filter((m) => m.kind === "ledger" && m.data.kind === "season_result").map((m) => m.data.data).pop();
  const mis = msgs.filter((m) => m.kind === "mission").map((m) => m.data).pop();
  if (!res) return;
  const faults = (mis && mis.metrics.faults) || [];
  const fixed = faults.filter((f) => f.detected && f.diagnosed && f.recovered).length;
  const vals = [fmt(res.people_fed), fmt(res.water_used_m3), fmt(res.energy_used_kwh), faults.length ? `${fixed} of ${faults.length}` : "None"];
  box.querySelectorAll("b").forEach((b, k) => (b.textContent = vals[k]));
  box.querySelector(".a span").textContent = faults.length ? `hidden ${faults.map((f) => f.label).join(", ")}, found and fixed` : "hidden faults this season";
  const note = document.getElementById("statusNote");
  if (note) note.textContent = "From the recorded season replaying above: one farm, one growing year, October to June.";
}
function stillHero() {
  document.querySelector(".hero").classList.add("still");
  const cap = document.getElementById("heroCaption");
  if (cap) cap.textContent = "A still image of the 3D farm. This browser couldn't start the live 3D view; the recorded season still plays.";
}
hero();
