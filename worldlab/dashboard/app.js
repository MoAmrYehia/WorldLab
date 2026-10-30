// WorldLab: Green Frontier — simulator interface.
// Live mode: the Python server streams a run over server-sent events. Replay mode: a recorded run (replay.json)
// plays with no server. Missions and achievements come from the server's ledger-based scoring ("mission" events).
// Everything shown is read from the run: measured, predicted, inferred and hidden values are labelled as such.
import { api, apiJson, stream, go, PAGES, setToken } from "./client.js";

const $ = (id) => document.getElementById(id);
const D = 273;
const CROP_LABEL = { wheat: "Wheat", rice: "Rice", maize: "Maize", potato: "Potatoes", cassava: "Cassava", soybean: "Soybeans",
  sorghum: "Sorghum", millet: "Millet", beans: "Common beans", sweet_potato: "Sweet potatoes" };
const SALT = { wheat: 6, rice: 3, maize: 1.7, potato: 1.7, cassava: 2, soybean: 5, sorghum: 6.8, millet: 6, beans: 1, sweet_potato: 1.5 };
const NUTRIENT = { kcal: "calories", protein_g: "protein", vitA_ug: "vitamin A" };
const TRAIT = { wp: "Water productivity", cgc: "Canopy growth", heat: "Heat tolerance", salt: "Salinity threshold" };
const TRAIT_UNIT = { wp: (v) => `×${fmt(v, 2)}`, cgc: (v) => `×${fmt(v, 2)}`, heat: (v) => `${v >= 0 ? "+" : ""}${fmt(v, 1)} °C`, salt: (v) => `${v >= 0 ? "+" : ""}${fmt(v, 1)} dS/m` };
const FIELD_IDS = ["F1", "F2", "F3", "F4", "F5", "F6"];
const NAMES = ["North", "Palm edge", "Dune", "Old wadi", "Loam block", "Sabkha rim"];
const SOILS = ["loamy sand", "sandy loam", "sand", "sandy loam over loam", "loam", "loamy sand"];
const ECE0 = [2.0, 1.5, 1.0, 5.0, 3.0, 7.0];       // initial topsoil salinity per field, dS/m (farm definition)
const CHAPTERS = [["discover", "Discover", "Study the farm and run crop experiments."], ["strategize", "Strategize", "Plan crops and water within the limits."],
  ["survive", "Survive", "Run the season through heat, salt and faults."], ["recover", "Recover", "Investigate anomalies, find causes, repair, update the model."],
  ["harvest", "Harvest", "Judge food security, water use and resilience."]];
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } },
  del(k) { try { localStorage.removeItem(k); } catch (e) { /* storage blocked */ } } };

const fresh = () => ({ days: [], events: [], perturbations: [], beliefs: null, projections: [], trials: [], scene: {}, drone: [],
  plan: null, status: {}, fields: null, rl_train: [], rl: null, agentKind: null, mission: null, award: null, lastSeq: -1 });
let S = fresh();
let portrait = () => null, stageOf = () => 2, dfSel = -1, dfKey = "", droneTimer = 0;
let sel = -1, scene = null, mode = "live", info = {}, progress = null, dirty = true, caps = null, streamState = "";
let inspKey = "", serverUp = false, meta = {};
let metric = "health", overlay = "", drawer = null, invClosedFor = null, reportShownFor = null, seenBadges = new Set();
let lastFocus = null;

// ------------------------------------------------------------ helpers
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
const yfmt = (y) => (y == null ? "–" : y === 0 ? "0" : y < 0.1 ? "<0.1" : fmt(y, y < 10 ? 1 : 0));
// One calendar for the whole app: the run's own date labels when present, else the simulator's (from 1 October, no leap day).
const MON = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"], MLEN = [31, 30, 31, 31, 28, 31, 30, 31, 30, 31, 31, 30];
function dayLabel(d) {
  if (d == null) return "";
  const rec = S.days[d];
  if (rec && rec.day === d && rec.date) return String(rec.date).replace(/^0/, "");
  let m = 0; d = Math.max(0, Math.round(d));
  while (m < 11 && d >= MLEN[m]) { d -= MLEN[m]; m++; }
  return `${d + 1} ${MON[m]}`;
}
const crop = (c) => CROP_LABEL[c] || (c ? c : "Fallow");
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function nice(lo, hi) { if (!(hi > lo)) hi = lo + 1; const pad = (hi - lo) * 0.08; return [lo - pad, hi + pad]; }
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const fieldIndex = (id) => FIELD_IDS.indexOf(String(id || "").toUpperCase());
const lastProj = () => S.projections[S.projections.length - 1];
const lastDay = () => S.days[S.days.length - 1];
const signed = (x) => (x == null ? "–" : (x > 0 ? "+" : "") + x);
const curDay = () => { const ld = lastDay(); return ld ? ld.day : null; };
function fieldsNow() {
  if (S.fields) return S.fields;
  if (S.plan && S.plan.fields) return S.plan.fields.map((f, i) => ({ id: f.field || FIELD_IDS[i], crop: f.crop, label: crop(f.crop), planned: true, sow: f.mgmt && f.mgmt.sow }));
  return FIELD_IDS.map((id) => ({ id, crop: null, label: "Not planned" }));
}
const agentName = (k) => ({ spark: "Muse Spark", glimmer: "Muse Glimmer", "scripted-rl": "Scripted protocol with RL", scripted: "Scripted protocol", "scripted-noadapt": "Scripted, ignores alarms" }[k] || "");
const kinds = (k) => S.events.filter((e) => e.kind === k);
function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}

// ------------------------------------------------------------ reducer
const WORLD_EVENTS = new Set(["anomaly", "look", "field_test", "adjust", "model_update", "harvest", "season_result"]);
function apply(m, live = true) {
  const d = m.data;
  switch (m.kind) {
    case "reset": S = fresh(); S.agentKind = d && d.agent; reportShownFor = null; invClosedFor = null; if (live && scene) scene.reset(); break;
    case "day": S.days.push(d); if (live && scene) { scene.update(d); const k = d.fields.findIndex((f) => f.cc_obs != null); if (k >= 0 && d.day % 8 === 3) scene.hover(k); } break;
    case "ledger":
      if (d.seq != null && d.seq <= S.lastSeq) break;        // a reconnect must never apply an entry twice
      if (d.seq != null) S.lastSeq = d.seq;
      S.events.push(d); if (S.events.length > 8000) S.events.splice(0, 500);
      if (live && scene && WORLD_EVENTS.has(d.kind)) scene.event(d.kind, d.data);
      if (live && d.kind === "anomaly") { sel = d.data.field_index; if (scene) scene.setSelected(sel); invClosedFor = null; }
      if (live && d.kind === "season_result" && mode === "live") setTimeout(() => showReport(), reducedMotion ? 0 : 2200);
      break;
    case "perturbation": S.perturbations.push({ ...d, _order: S.events.length }); break;
    case "beliefs": S.beliefs = d; break;
    case "projection": S.projections.push(d); break;
    case "trials": S.trials.push(d); if (live && scene) scene.addTrial(d); break;
    case "scene": S.scene[d.field] = d; if (live && scene) scene.scan(fieldIndex(d.field));
      if (d.image) droneArrived({ ...d, kind: "inspection" }, live); break;
    case "drone_frame": droneArrived(d, live); if (live && scene) scene.scan(d.field_index); break;
    case "plan": S.plan = d; if (live && scene && !S.fields) scene.setFields(fieldsNow()); break;
    case "status": S.status = d; if (live && scene) syncAnomaly(); break;
    case "fields": S.fields = d; if (live && scene) scene.setFields(d); break;
    case "rl_train": if (d.reset) S.rl_train = []; else S.rl_train.push(d); break;
    case "rl": S.rl = d; break;
    case "mission": S.mission = d; if (live) badgeToasts(d); break;
    case "award": S.award = d; if (live) { toast("Season scored", `+${fmt(d.gained)} XP${d.new_achievements && d.new_achievements.length ? `, ${d.new_achievements.length} new achievement${d.new_achievements.length > 1 ? "s" : ""}` : ""}`); loadProgress(); } break;
  }
  dirty = true;
}
function droneArrived(f, live) {
  S.drone.push(f); if (S.drone.length > 60) S.drone.shift();
  if (!live) return;
  dfSel = -1;
  if (!$("droneTab").classList.contains("on")) $("droneDot").hidden = false;
  $("dfLiveTxt").textContent = `${f.kind === "inspection" ? "Inspecting" : "Surveying"} ${f.field}`;
  clearTimeout(droneTimer); droneTimer = setTimeout(() => ($("dfLiveTxt").textContent = "On patrol"), 5000);
}
function syncAnomaly() { if (!scene) return; const a = S.status && S.status.anomaly; scene.setAnomaly(a ? a.field_index : -1, a ? `${cap(a.signal_label)} ${a.direction}` : ""); }
function sceneSync() {
  if (!scene) return;
  scene.reset();
  scene.setFields(fieldsNow());
  S.trials.forEach((t) => scene.addTrial(t));
  const ld = lastDay(); if (ld) scene.update(ld);
  syncAnomaly(); scene.setSelected(sel); scene.setOverlay(overlay || null);
}

// ------------------------------------------------------------ render
function render() {
  if (!dirty) return;
  dirty = false;
  renderTop(); renderTransport(); renderMissions(); renderImpact(); renderDock(); renderInspector(); renderIncident(); renderInvestigation();
  renderLegend(); renderDrone(); renderMap2d();
  if (drawer) renderDrawer();
}

function renderTop() {
  let xp = 0, lvl = 1, floor = 0, next = 100, demo = !progress;
  if (progress) ({ xp, level: lvl, level_floor: floor, next_level_at: next } = progress.level);
  else if (S.mission) { xp = S.mission.xp_items.reduce((a, b) => a + b.xp, 0); ({ lvl, floor, next } = levelFor(xp)); }
  $("xpLevel").textContent = demo ? `Preview LVL ${String(lvl).padStart(2, "0")}` : `LVL ${String(lvl).padStart(2, "0")}`;
  $("xpText").textContent = `${fmt(xp)} XP`;
  $("xpBar").style.width = `${Math.min(100, (100 * (xp - floor)) / Math.max(1, next - floor))}%`;
  $("xpPill").title = demo ? "Preview experience: what the season on screen would earn. Not saved; sign up to keep your own." : "Your saved level and experience";
}
function levelFor(xp) { let n = 1; while (100 * n * n <= xp) n++; return { lvl: n, floor: 100 * (n - 1) ** 2, next: 100 * n * n }; }

// who decides, what perceives, what irrigates: shown in the run header at all times
function deciderName() { const k = S.agentKind || info.agent; return /spark|glimmer/.test(k || "") ? agentName(k) : "Scripted protocol"; }
function perceptionName() {
  const src = Object.values(S.scene || {}).map((x) => x.source).find(Boolean) || "";
  return /simulated/i.test(src) ? "Simulated perception" : src ? "SAM 3.1 + Muse Spark" : (caps && caps.perception === "meta" ? "SAM 3.1 + Muse Spark" : "Simulated perception");
}
function controllerName() {
  const ld = lastDay(), c = (ld && ld.controller) || (S.status && S.status.controller);
  return c === "rl_policy" ? "Learned irrigation policy" : c ? "Fixed irrigation rule" : (S.rl && S.rl.recommend === "rl_policy" ? "Learned irrigation policy (ready)" : "Irrigation not started");
}
function renderTransport() {
  const res = S.status && S.status.result;
  let state;
  if (mode === "replay") state = `Recorded · ${R.playing ? "playing" : R.pos >= R.total - 0.01 ? "finished" : R.pos > 0 ? "paused" : "ready to play"}`;
  else state = `Live · ${streamState === "connected" ? (info.running ? "running" : res ? "season finished" : "idle") : streamState || "connecting"}`;
  if ($("runState").textContent !== state) $("runState").textContent = state;
  $("runState").className = `run-state ${mode} ${R.playing || info.running ? "on" : ""}`;
  $("provChip").textContent = `${deciderName()} · ${perceptionName()} · ${controllerName()}`;
  const d = curDay();
  const date = d == null ? (S.trials.length || S.plan ? "Before sowing: trials and planning" : "Before sowing") : `${dayLabel(d)} · day ${d + 1} of ${D}`;
  if (mode === "replay") { $("tpDate").textContent = date; $("dateScrub").setAttribute("aria-valuetext", date); }
  else $("tpDateLive").textContent = date;
  $("reportBtn").hidden = !res;
  const p = res ? res.people_fed : lastProj() ? lastProj().people_p10 : S.plan ? S.plan.people_p10 : null;
  const st = S.status || {}, ld = lastDay();
  const w = (ld && ld.water_used_m3) ?? st.water_used_m3, e = (ld && ld.energy_used_kwh) ?? st.energy_used_kwh;
  $("tpMetrics").textContent = p == null ? "" : `${fmt(p)} people · water ${fmt((100 * (w || 0)) / (st.water_quota_m3 || 60000))}% · energy ${fmt((100 * (e || 0)) / (st.energy_kwh || 90000))}%`;
}

function renderMissions() {
  const m = S.mission, st = S.status || {};
  const cur = m ? m.current_chapter : st.phase === "season" ? "survive" : st.phase === "planning" ? "strategize" : "discover";
  const ld = lastDay();
  const T = { discover: ["Discover", "Learn the land before you plant it."], strategize: ["Strategize", "Plan a better harvest."], survive: ["Survive", "Keep the farm alive."],
    recover: ["Recover", "Find the cause, fix it, update the model."], harvest: ["Harvest", st.result ? "The season is in." : "Bring the season home."] }[cur];
  $("seasonEyebrow").textContent = ld ? `Season, ${dayLabel(Math.min(ld.day, D - 1))} (day ${ld.day + 1} of ${D})` : st.phase === "planning" ? "Before sowing: planning" : S.trials.length ? "Before sowing: trial plots" : "Before the season";
  $("headline").innerHTML = `${esc(T[0])}. <em>${esc(T[1])}</em>`;
  const chapters = m ? m.chapters : CHAPTERS.map(([id, title, about]) => ({ id, title, about, objectives: [], status: "open" }));
  const KIND = { optional: "optional", stretch: "goal", na: "not applicable" };
  const html = chapters.map((c, k) => {
    const status = c.status || (c.done ? "done" : "open");
    const cls = status === "done" ? "done" : status === "na" ? "na" : c.id === cur ? "now" : "";
    const objs = (c.id === cur || status === "na") && c.objectives.length ? `<ul class="objs">${c.objectives.map((o) => {
      const kind = o.kind && o.kind !== "required" ? `<em class="okind ${o.kind}">${KIND[o.kind]}</em>` : "";
      const label = o.go ? `<button type="button" class="olink" data-go="${o.go}">${esc(o.label)}</button>` : esc(o.label);
      return `<li class="${o.done ? "ok" : ""} ${o.kind || ""}"><span>${label} ${kind}</span><span>${o.value ? esc(o.value) : ""}</span></li>`;
    }).join("")}</ul>` : "";
    const mark = status === "done" ? "✓" : status === "na" ? "–" : k + 1;
    return `<li class="chapter ${cls}"><span class="num" aria-hidden="true">${mark}</span><b>${esc(c.title)}${status === "na" ? ' <span class="sr-only">(not applicable)</span>' : status === "done" ? ' <span class="sr-only">(complete)</span>' : ""}</b><span class="about">${esc(c.about)}</span>${objs}</li>`;
  }).join("");
  if ($("chapters").dataset.h !== html) {
    $("chapters").innerHTML = html; $("chapters").dataset.h = html;
    $("chapters").querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => goTo(b.dataset.go)));
  }
  const out = m && m.outcome;
  $("outcome").hidden = !out; if (out) $("outcome").textContent = out;
}
function goTo(key) {
  const map = { trials: ["research", "trials"], traits: ["research", "traits"], rl: ["research", "rl"], plan: ["plan", "plan"], planner: ["planner"],
    incidents: ["incidents"], agent: ["agent", "record"], results: ["results", "report"] };
  const [v, t] = map[key] || [key];
  openView(v, t);
}

function renderImpact() {
  const st = S.status || {}, res = st.result, proj = lastProj(), plan = S.plan;
  let n = null, label = "", lim = null, by = null;
  if (res) { n = res.people_fed; label = "realised: people fed by this harvest"; lim = res.limiting; by = res.by_nutrient; }
  else if (st.phase === "season" && proj) { n = proj.people_p10; label = "projected for a bad year (10th percentile)"; lim = minKey(proj.by_nutrient_p50); by = proj.by_nutrient_p50; }
  else if (plan) { n = plan.people_p10; label = "planned for a bad year (10th percentile)"; lim = plan.limiting; by = plan.by_nutrient_p50 || null; }
  $("livesN").textContent = n == null ? "–" : fmt(n);
  $("livesSub").textContent = n == null ? "modelled person-years, once the season is planned" : label;
  $("stages").innerHTML = [["Planned", plan && plan.people_p10, "bad year"], ["Projected", proj && proj.people_p10, "bad year"], ["Realised", res && res.people_fed, "harvest"]]
    .map(([k, v, s]) => `<div class="${v == null ? "na" : ""}"><dt>${k}</dt><dd>${v == null ? "–" : fmt(v)}<small>${v == null ? "" : s}</small></dd></div>`).join("");
  if (by) {
    const mx = Math.max(...Object.values(by), 1), keys = ["kcal", "protein_g", "vitA_ug"];
    $("nutrients").innerHTML = `<p class="nh">Person-years covered by each need${res ? "" : " (typical year)"}</p>` + keys.map((k) => `<div class="nut ${k === lim ? "lim" : ""}"><span>${cap(NUTRIENT[k])}${k === lim ? " · limiting" : ""}</span><i><b style="width:${Math.min(100, (100 * (by[k] || 0)) / Math.min(mx, (by[lim] || 1) * 3))}%"></b></i><em>${fmt(by[k])}</em></div>`).join("");
  } else $("nutrients").innerHTML = "";
  $("limitNote").textContent = lim ? `Limited by ${NUTRIENT[lim] || lim}: a person counts only when calories, protein and vitamin A are all covered, so the scarcest need sets the number. A model metric, not a full diet.` : "A person counts only when calories, protein and vitamin A are all covered. A model metric, not a full diet.";
  const wq = st.water_quota_m3 || 60000, eq = st.energy_kwh || 90000, ld = lastDay();
  const w = (ld && ld.water_used_m3 != null ? ld.water_used_m3 : st.water_used_m3) || 0;
  const e = (ld && ld.energy_used_kwh != null ? ld.energy_used_kwh : st.energy_used_kwh) || 0;
  $("waterTxt").textContent = `${fmt(w / 1000, 1)}k / ${fmt(wq / 1000)}k m³`; $("energyTxt").textContent = `${fmt(e / 1000, 1)}k / ${fmt(eq / 1000)}k kWh`;
  bar("waterBar", w / wq); bar("energyBar", e / eq);
  const fcW = !res && proj && proj.water_total_p50_m3, fcE = !res && proj && proj.energy_total_p50_kwh;
  fc("waterFc", w, fcW, wq); fc("energyFc", e, fcE, eq);
  $("waterSub").textContent = res ? `${fmt(wq - w)} m³ left unused` : fcW ? `${fmt(Math.max(wq - w, 0))} left · forecast to harvest ${fmt(proj.water_total_p50_m3)} (1 year in 10: ${fmt(proj.water_total_p90_m3)})` : `${fmt(Math.max(wq - w, 0))} m³ left`;
  $("energySub").textContent = res ? `${fmt(eq - e)} kWh left unused` : fcE ? `${fmt(Math.max(eq - e, 0))} left · forecast to harvest ${fmt(proj.energy_total_p50_kwh)} (1 year in 10: ${fmt(proj.energy_total_p90_kwh)})` : `${fmt(Math.max(eq - e, 0))} kWh left`;
  const rl = (ld && ld.controller ? ld.controller : st.controller) === "rl_policy";
  $("ctrlPill").textContent = rl ? "RL policy" : st.phase === "season" || res ? "Fixed rule" : "Not started"; $("ctrlPill").classList.toggle("rl", rl);
  const hard = (st.budget_mode || (res && res.budget_mode)) !== "soft";
  const curt = (ld && ld.curtailed != null) ? `Today's irrigation was curtailed to ${Math.round(ld.curtailed * 100)}% to stay within the budget. ` : (st.curtailed_m3 ? `${fmt(st.curtailed_m3)} m³ of demand was curtailed this season. ` : "");
  const risk = !res && proj && (proj.water_total_p90_m3 > wq || (proj.energy_total_p90_kwh || 0) > eq)
    ? `At risk: in 1 year in 10 the forecast demand passes the ${proj.water_total_p90_m3 > wq ? "water quota" : "energy budget"}; ${hard ? "irrigation would then be curtailed, not overrun" : "this run has no hard cut-off"}. ` : "";
  $("budgetNote").textContent = `${curt}${risk}${hard ? "Hard limits: no day's irrigation may exceed what remains of the quota or energy budget." : "Soft limits (research mode): the plan aims to stay within them, but use can overrun."} Desalinated water is made from the same groundwater, so it counts against the quota.`;
  $("budgetNote").classList.toggle("warn", !!(curt || risk));
  $("agentName").textContent = agentName(S.agentKind || info.agent);
  const items = streamItems();
  const lastSci = [...items].reverse().find((x) => ["decide", "test", "learn", "alarm", "rl"].includes(x.it[0]));
  $("scQuote").innerHTML = lastSci ? `${lastSci.it[1]}` : "Waiting for the season to start.";
  const active = (mode === "live" && info.running) || (mode === "replay" && R.playing);
  $("scLive").textContent = res ? "Season done" : active ? (mode === "replay" ? "Replaying" : "Working") : mode === "replay" ? "Paused" : "Idle";
  $("scLive").classList.toggle("on", !!active && !res);
}
function bar(id, frac, over = true) { const el = $(id); el.style.width = `${Math.min(100, Math.max(0, frac * 100))}%`; el.classList.toggle("over", over && frac > 1); }
function fc(id, used, total, q) { const el = $(id); if (!total) { el.style.width = "0"; return; } el.style.left = `${Math.min(100, (100 * used) / q)}%`; el.style.width = `${Math.max(0, Math.min(100, (100 * total) / q) - Math.min(100, (100 * used) / q))}%`; el.classList.toggle("over", total > q); }
function minKey(o) { if (!o) return null; return Object.keys(o).reduce((a, b) => (o[a] <= o[b] ? a : b)); }

// ------------------------------------------------------------ dock: field gauges, timeline, activity
function lastObs(i, key) { for (let k = S.days.length - 1; k >= 0; k--) { const f = S.days[k].fields[i]; if (f && f[key + "_obs"] != null) return { f, day: S.days[k].day }; } return null; }
function renderDock() {
  const ld = lastDay(), fl = fieldsNow(), an = S.status && S.status.anomaly;
  const box = $("gauges"), C = 2 * Math.PI * 26;
  if (box.children.length !== FIELD_IDS.length) {
    box.innerHTML = FIELD_IDS.map((id, i) => `<button class="gauge" data-i="${i}" type="button">
      <span class="g-title"></span>
      <svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="26" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="6"/><circle class="g-arc" cx="32" cy="32" r="26" fill="none" stroke-width="6" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C}" transform="rotate(-90 32 32)"/>
      <text class="g-val" x="32" y="36" text-anchor="middle" font-weight="700" font-family="Sora, sans-serif"></text></svg>
      <span class="g-sub"></span><span class="g-warn"></span></button>`).join("");
    box.querySelectorAll(".gauge").forEach((b) => (b.onclick = () => select(Number(b.dataset.i), true)));
  }
  FIELD_IDS.forEach((id, i) => {
    const f = ld && ld.fields[i], w = ld && ld.world && ld.world[i], c = fl[i] || {};
    let frac = 0, val = "–", sub, col = css("--emerald");
    const state = !c.crop ? (S.plan || S.fields ? "Fallow" : "Not planned") : !w || !w.sown ? "Not sown yet" : w.done ? "Harvested" : null;
    sub = state || "";
    if (f && w && w.sown && !w.done) {
      if (metric === "health") {
        const o = lastObs(i, "cc");
        if (o && o.f.cc_pred > 0.05) {
          const r = o.f.cc_obs / o.f.cc_pred, age = ld.day - o.day;
          frac = Math.min(1, r / 1.2); val = `${Math.round(r * 100)}%`;
          sub = `${r >= 0.9 ? "Canopy on track" : r >= 0.75 ? "Canopy below model" : "Canopy well below model"} · drone ${age <= 0 ? "today" : `${age} d ago`}`;
          col = r >= 0.9 ? css("--emerald") : r >= 0.75 ? css("--amber") : css("--alarm");
        } else { val = "–"; sub = "Canopy too small to compare"; }
      } else if (metric === "moisture") { frac = (f.sw_obs - 0.04) / 0.26; val = fmt(f.sw_obs, 3); sub = `m³/m³ · model ${fmt(f.sw_lo, 3)}–${fmt(f.sw_hi, 3)}`; col = css("--cyan"); }
      else if (metric === "salinity") { const thr = SALT[c.crop] || 3; frac = f.ec_obs / (thr * 2); val = `${fmt(f.ec_obs, 1)}`; sub = `dS/m · threshold ${thr}`; col = f.ec_obs > thr ? css("--alarm") : css("--amber"); }
      else { frac = (f.irr_mm || 0) / 12; val = `${fmt(f.irr_mm, 1)}`; sub = `mm today${f.desal ? `, ${Math.round(f.desal * 100)}% desalinated` : ""}`; col = css("--cyan"); }
    } else if (w && w.done) { frac = 1; val = "Done"; col = css("--amber"); }
    frac = Math.min(1, Math.max(0, frac));
    // warnings stay visible whatever metric is shown: salinity over the crop's threshold, an open alarm
    const warns = [];
    if (an && an.field_index === i) warns.push(`⚠ Alarm: ${an.signal_label} ${an.direction}`);
    if (f && w && w.sown && !w.done && c.crop && f.ec_obs > (SALT[c.crop] || 99)) warns.push(`⚠ Salinity ${fmt(f.ec_obs, 1)} > ${SALT[c.crop]} dS/m threshold`);
    const b = box.children[i], title = `${id} ${c.crop ? crop(c.crop) : "Fallow"}`;
    const st = c.crop ? stageOf(c.crop, w) : -1, tkey = `${title}|${st}`;
    b.classList.toggle("sel", i === sel); b.classList.toggle("alarm", !!(an && an.field_index === i)); b.classList.toggle("warn", warns.length > 0);
    b.setAttribute("aria-label", `${title}: ${val} ${sub}. ${warns.join(". ")}`);
    b.setAttribute("aria-pressed", String(i === sel));
    if (b.children[0].dataset.k !== tkey) {
      b.children[0].dataset.k = tkey;
      const pic = c.crop ? portrait(c.crop, st, 48) : null;
      b.children[0].innerHTML = `${pic ? `<img class="g-pic" src="${pic}" alt="">` : ""}${esc(title)}`;
    }
    const arc = b.querySelector(".g-arc"); arc.setAttribute("stroke", col); arc.setAttribute("stroke-dashoffset", String(C * (1 - frac)));
    const t = b.querySelector(".g-val"); if (t.textContent !== val) { t.textContent = val; t.setAttribute("font-size", val.length > 6 ? 9 : val.length > 3 ? 12 : 13); t.setAttribute("fill", css("--ink")); }
    if (b.children[2].textContent !== sub) b.children[2].textContent = sub;
    const wt = warns.join(" "); if (b.children[3].textContent !== wt) b.children[3].textContent = wt;
  });
  // timeline: marks are buttons that move the replay to that event
  const day = ld ? ld.day + 1 : 0;
  $("tlFill").style.width = `${(100 * day) / D}%`;
  const tl = $("timeline").querySelector(".tl-track");
  const marks = [];
  S.perturbations.forEach((p) => marks.push([p.day, "change", `${dayLabel(p.day)}: hidden change, ${p.note} (not known to the scientist)`]));
  kinds("anomaly").forEach((e) => marks.push([e.data.detected_day, "alarm", `${dayLabel(e.data.detected_day)}: alarm in ${e.data.field}, ${e.data.signal_label} ${e.data.direction}`]));
  kinds("adjust").forEach((e) => marks.push([e.t, "fix", `${dayLabel(e.t)}: action in ${e.data.field}`]));
  kinds("harvest").forEach((e) => marks.push([e.data.day, "harvest", `${dayLabel(e.data.day)}: ${e.data.field} harvested`]));
  const mk = marks.map((m) => m.join("|")).join(";") + `|${day}`;
  if (tl.dataset.k !== mk) {
    tl.dataset.k = mk;
    tl.querySelectorAll(".tl-mark,.tl-now").forEach((e) => e.remove());
    marks.forEach(([d, cls, title]) => {
      const e = document.createElement("button"); e.type = "button"; e.className = `tl-mark ${cls}`; e.style.left = `${(100 * Math.min(d, D)) / D}%`;
      e.title = title; e.setAttribute("aria-label", title);
      e.onclick = () => { if (mode === "replay") seekToDay(d); };
      tl.appendChild(e);
    });
    if (ld) { const n = document.createElement("i"); n.className = "tl-now"; n.style.left = `${(100 * day) / D}%`; tl.appendChild(n); }
  }
  if (!$("tlMonths").children.length) $("tlMonths").innerHTML = MON.slice(0, 9).map((m) => `<span>${m}</span>`).join("");
  // activity
  const items = streamItems();
  const key = String(items.length);
  if ($("activity").dataset.k !== key) {
    $("activity").dataset.k = key;
    $("activity").innerHTML = items.slice(-80).reverse().map(({ it, t, tl: lab }) => `<li class="k-${it[0]}"><span>${it[1]}${it[2] || ""}</span><time>${t != null ? `${lab ? `${lab} ` : ""}${dayLabel(Math.min(t, D - 1))}` : "before sowing"}</time></li>`).join("");
  }
}

// ------------------------------------------------------------ the scientist's activity, from the ledger
function streamItem(e) {
  const d = e.data || {};
  const why = (s) => (s ? `<span class="why">${esc(s)}</span>` : "");
  switch (e.kind) {
    case "hypothesis": return ["decide", `Hypothesis ${d.id}: ${esc(d.statement)}`, why(`Predicts: ${d.prediction}`)];
    case "conclusion": return [d.verdict === "supported" ? "learn" : "decide", `${d.hypothesis_id} ${esc(d.verdict)}`, why(d.evidence)];
    case "trial_start": return ["decide", `Plants ${d.plots.length} trial plots`, why(d.rationale)];
    case "trial_result": { const held = d.plots.filter((p) => p.prediction_held).length; return [held < d.plots.length ? "test" : "learn", `${held} of ${d.plots.length} trial predictions held`, why(`${d.plots.length - held} missed: evidence for calibration`)]; }
    case "model_update": return ["learn", d.crops ? `Calibrates ${d.crops.map((c) => crop(c.crop)).join(", ")}` : `Teaches the model: ${esc(String(d.finding).replace(/_/g, " "))} = ${d.value} in ${d.field}`, why(d.rationale)];
    case "plan": return ["decide", `Plans the season (${d.plan_id}): ${fmt(d.people_p10)} people in a bad year`, why(d.scientist_choice ? (d.scientist_choice.people_p10 > d.people_p10 ? `Keeps your crops; its own choice would feed ${fmt(d.scientist_choice.people_p10)}.` : "Keeps your crops; it found no better mix.") : `Not knowing the varieties exactly costs ${fmt(d.cost_of_uncertainty_people)} people.`)];
    case "farmer_choices": return ["decide", "Your crop choices recorded", why(d.fields.filter((f) => f.crop || f.choice === "fallow").map((f) => `${f.field}: ${f.choice}`).join("; "))];
    case "rl_train_start": return ["rl", "Trains an irrigation policy by reinforcement learning", why(d.rationale)];
    case "rl_policy": { const c = d.held_out_comparison || {}; return ["rl", d.recommend === "rl_policy" ? `Policy chosen on held-out imagined seasons: people (bad year) ${signed(c.people_p10_change_pct)}%, water ${signed(c.water_change_pct)}%, energy ${signed(c.energy_change_pct)}%` : "Policy did not beat the fixed rule; keeps the rule", why(d.note)]; }
    case "controller": return ["rl", d.controller === "rl_policy" ? "Hands irrigation to the RL policy" : "Hands irrigation back to the fixed rule", why(d.rationale)];
    case "season_start": return ["decide", `Sows the season, irrigation by ${d.controller === "rl_policy" ? "the RL policy" : "the fixed rule"}`, ""];
    case "anomaly": return ["alarm", `Alarm in ${d.field}: ${esc(d.signal_label)} ${esc(d.direction)}`, why(`Measured on ${dayLabel(d.detected_day)}; drift began around ${dayLabel(d.onset_day)}. Season paused to investigate.`)];
    case "field_test": return ["test", `${d.field}: ${esc(testText(d))}`, why(d.rationale)];
    case "look": return ["test", `Drone over ${d.field}: canopy ${fmt(d.canopy_cover_measured, 2)} measured vs ${fmt(d.canopy_cover_predicted, 2)} predicted`, why(d.diagnosis && d.diagnosis.condition ? `Image analysis (${d.source || "perception"}): ${String(d.diagnosis.condition).replace(/_/g, " ")}` : d.reason)];
    case "adjust": return ["decide", `${d.field}: ${[d.repair ? "repairs the drip line" : "", d.pest_control ? "applies pest control" : "", d.irr != null ? `irrigation ${Math.round(d.irr * 100)}%` : "", d.desal != null ? `desalinated water ${Math.round(d.desal * 100)}%` : ""].filter(Boolean).join(", ")}`, why(d.rationale)];
    case "rebalance": return ["decide", `Re-plans water: ${d.people_p10_before} → ${d.people_p10_after} people in a bad year`, ""];
    case "anomaly_dismissed": return ["decide", "Dismisses the alarm", why(d.rationale)];
    case "curtailment": return ["alarm", `Budget reached: irrigation curtailed to ${Math.round(d.fraction_applied * 100)}% of demand`, why(d.note)];
    case "harvest": return ["learn", `${d.field} ${crop(d.crop)} harvested: ${d.yield_t_ha} t/ha`, ""];
    case "season_result": return ["learn", `Season over: ${fmt(d.people_fed)} people fed`, why(`${fmt(d.water_used_m3)} m³ groundwater, ${fmt(d.energy_used_kwh)} kWh`)];
    case "agent_step": return d.role === "agent" ? ["decide", esc(d.text), why("Recorded explanation from the model")] : null;
    default: return null;
  }
}
function testText(d) {
  if (d.test === "emitter_flow") return `emitter flow test reads ${Math.round((d.delivered_vs_design || 0) * 100)}% of design`;
  if (d.test === "water_test") return `water test: groundwater ${d.groundwater_ec_dS_m} dS/m (model assumes ${d.assumed_by_model ?? 4.5})`;
  if (d.test === "soil_sample") return `soil sample: ${(d.ece_dS_m_by_layer || []).join(", ")} dS/m by layer`;
  if (d.test === "leaf_inspection") return d.pest_damage_seen ? `leaf inspection: ${d.severity} pest damage, ${d.insects_per_leaf} insects per leaf` : "leaf inspection: no pests found";
  return String(d.test || "field test");
}
// When something happened: measurements carry their own day; tool actions are logged on the day they were taken.
function eventDay(e) {
  const d = e.data || {};
  if (e.kind === "anomaly") return [d.detected_day, "measured"];
  if (e.kind === "harvest") return [d.day, ""];
  return [e.t, ""];
}
let itemsCache = { n: -1, p: -1, items: [] };
function streamItems() {
  if (itemsCache.n === S.events.length && itemsCache.p === S.perturbations.length) return itemsCache.items;
  const items = []; let inSeason = false;
  const pert = [...S.perturbations];
  const due = (p, k, e) => (p._order != null ? p._order <= k : !e || (inSeason && e.t != null && e.t > p.day));
  const pushPert = (k, e) => { while (pert.length && due(pert[0], k, e)) { const p = pert.shift(); items.push({ it: ["world", `Hidden change in ${p.field === "all" ? "the farm" : p.field}`, `<span class="why">${esc(p.note)}. The scientist is not told.</span>`], t: p.day }); } };
  S.events.forEach((e, k) => {
    pushPert(k, e); if (e.kind === "season_start") inSeason = true;
    const it = streamItem(e); if (!it) return;
    const [t, tl] = eventDay(e);
    items.push({ it, t: inSeason && e.kind !== "season_start" ? t : null, tl, e });
  });
  pushPert(1e13, null);
  itemsCache = { n: S.events.length, p: S.perturbations.length, items };
  return items;
}

// ------------------------------------------------------------ field inspector
function select(i, focus = false) {
  if (i == null || i < 0) return;
  sel = i; inspKey = ""; if (scene) { scene.setSelected(i); if (focus) scene.focus(i, "field"); }
  $("inspector").hidden = false; dirty = true; render();
}
function renderInspector() {
  if ($("inspector").hidden || sel < 0) return;
  const ik = `${sel}|${S.days.length}|${S.events.length}|${S.perturbations.length}|${mode}|${S.status.phase}|${Object.keys(S.scene).length}`;
  if (ik === inspKey) return; inspKey = ik;
  const fl = fieldsNow(), f = fl[sel] || {}, ld = lastDay(), w = ld && ld.world && ld.world[sel];
  $("fiTitle").textContent = `${FIELD_IDS[sel]} ${NAMES[sel]}`;
  const fpic = f.crop ? portrait(f.crop, stageOf(f.crop, w), 80) : null;
  $("fiPic").hidden = !fpic; if (fpic) { $("fiPic").src = fpic; $("fiPic").alt = `${crop(f.crop)} at its current stage, rendered from its 3D model`; }
  const state = !f.crop ? (S.plan || S.fields ? "fallow" : "not planned yet") : !w || !w.sown ? "not sown yet" : w.done ? "harvested" : `growing, ${Math.round(100 * Math.min(w.stage, 1))}% through its cycle`;
  let sub = `${cap(SOILS[sel])}, 2 ha, topsoil salinity at the start ${ECE0[sel]} dS/m. ${f.crop ? crop(f.crop) : "No crop"}: ${state}`;
  if (f.crop && f.sow != null) sub += `, sown ${dayLabel(f.sow)}`;
  $("fiSub").textContent = sub + ".";
  const marks = markersFor(sel);
  const cur = (key, dec, unit) => { const o = lastObs(sel, key); return o ? ` Latest ${fmt(o.f[key + "_obs"], dec)}${unit} on ${dayLabel(o.day)} (model ${fmt(o.f[key + "_lo"], dec)}–${fmt(o.f[key + "_hi"], dec)}).` : ""; };
  $("capSw").textContent = `Soil moisture, top 50 cm (m³/m³).${cur("sw", 3, "")}`;
  $("capCc").textContent = `Canopy cover from the drone (0–1).${cur("cc", 2, "")}`;
  const thr = f.crop ? SALT[f.crop] : null;
  $("capEc").textContent = `Soil salinity, top 50 cm (dS/m)${thr ? `; ${crop(f.crop).toLowerCase()} threshold ${thr}` : ""}.${cur("ec", 1, " dS/m")}`;
  bandChart($("chSw"), sel, "sw", { fmt: (v) => fmt(v, 3), marks });
  bandChart($("chCc"), sel, "cc", { fmt: (v) => fmt(v, 2), marks, sparse: true, min: 0, max: 1 });
  bandChart($("chEc"), sel, "ec", { fmt: (v) => fmt(v, 1), marks, min: 0, thr });
  irrChart($("chIrr"));
  const sc = S.scene[FIELD_IDS[sel]];
  $("droneFig").hidden = !sc || !sc.image;
  if (sc && sc.image) {
    if ($("droneImg").dataset.src !== sc.image) { $("droneImg").src = sc.image; $("droneImg").dataset.src = sc.image; }
    const diag = sc.diagnosis && sc.diagnosis.condition ? ` Analysis: ${String(sc.diagnosis.condition).replace(/_/g, " ")}.` : "";
    const age = ld ? ld.day - sc.day : 0;
    const old = age > 8 || (w && w.done);
    $("droneCap").innerHTML = `${old ? "<b>Historical evidence.</b> " : ""}Drone image captured ${dayLabel(sc.day)}${age > 0 ? `, ${age} days before the date shown` : ""}; analysed by ${esc(sc.source || "perception")}.${esc(diag)}${old ? " It may not reflect the field now." : ""}`;
  }
  $("perturb").hidden = !(mode === "live" && S.status.phase === "season");
}
function markersFor(i) {
  const id = FIELD_IDS[i], m = [];
  S.perturbations.forEach((p) => { if (p.field === id || p.field === "all") m.push({ day: p.day, cls: "change" }); });
  S.events.forEach((e) => { if (e.kind === "anomaly" && e.data.field === id) m.push({ day: e.data.detected_day, cls: "alarm" }); if (e.kind === "adjust" && e.data.field === id) m.push({ day: e.t, cls: "fix" }); });
  return m;
}
function bandChart(svg, fi, key, opts) {
  svg.innerHTML = "";
  const W = 300, H = 80, d0 = opts.d0 ?? 0, d1 = opts.d1 ?? D - 1;
  const rows = S.days.filter((d) => d.day >= d0 && d.day <= d1).map((d) => ({ day: d.day, f: d.fields[fi] })).filter((r) => r.f);
  if (!rows.length) { svgEl("text", { x: 4, y: H / 2, "font-size": 11, fill: css("--ink-3") }, svg).textContent = "Starts when the season begins"; return; }
  const lo = rows.map((r) => r.f[key + "_lo"]), hi = rows.map((r) => r.f[key + "_hi"]), pr = rows.map((r) => r.f[key + "_pred"]), ob = rows.map((r) => r.f[key + "_obs"]);
  const vals = [...lo, ...hi, ...ob, ...(opts.thr ? [opts.thr] : [])].filter((v) => v != null && Number.isFinite(v));
  let [y0, y1] = nice(Math.min(...vals), Math.max(...vals));
  if (opts.min != null) y0 = Math.max(opts.min, y0);
  if (opts.max != null) y1 = Math.min(opts.max, y1);
  const X = (d) => ((d - d0) / Math.max(1, d1 - d0)) * W, Y = (v) => H - ((v - y0) / (y1 - y0)) * H;
  for (let k = 0; k <= 2; k++) svgEl("line", { x1: 0, x2: W, y1: (k * H) / 2, y2: (k * H) / 2, stroke: "rgba(255,255,255,.07)", "vector-effect": "non-scaling-stroke" }, svg);
  let band = "";
  rows.forEach((r, k) => { if (hi[k] != null) band += `${band ? "L" : "M"}${X(r.day).toFixed(1)},${Y(hi[k]).toFixed(1)}`; });
  for (let k = rows.length - 1; k >= 0; k--) if (lo[k] != null) band += `L${X(rows[k].day).toFixed(1)},${Y(lo[k]).toFixed(1)}`;
  svgEl("path", { d: band + "Z", fill: css("--model-band"), stroke: "none" }, svg);
  let line = ""; rows.forEach((r, k) => { if (pr[k] != null) line += `${line ? "L" : "M"}${X(r.day).toFixed(1)},${Y(pr[k]).toFixed(1)}`; });
  svgEl("path", { d: line, fill: "none", stroke: css("--model"), "stroke-width": 1.6, "vector-effect": "non-scaling-stroke" }, svg);
  if (opts.thr && opts.thr > y0 && opts.thr < y1) svgEl("line", { x1: 0, x2: W, y1: Y(opts.thr), y2: Y(opts.thr), stroke: css("--alarm"), "stroke-width": 1, "stroke-dasharray": "2 3", opacity: 0.8, "vector-effect": "non-scaling-stroke" }, svg);
  (opts.marks || []).forEach((m) => { if (m.day >= d0 && m.day <= d1) svgEl("line", { x1: X(m.day), x2: X(m.day), y1: 0, y2: H, stroke: m.cls === "alarm" ? css("--alarm") : m.cls === "fix" ? css("--emerald") : css("--ink-2"), "stroke-width": 1.4, "stroke-dasharray": m.cls === "alarm" ? "" : "3 3", "vector-effect": "non-scaling-stroke" }, svg); });
  let dots = ""; rows.forEach((r, k) => { if (ob[k] != null) dots += `M${X(r.day).toFixed(1)},${Y(ob[k]).toFixed(1)}h0`; });
  svgEl("path", { d: dots, stroke: css("--measured"), "stroke-width": opts.sparse ? 4.5 : 3, "stroke-linecap": "round", fill: "none", "vector-effect": "non-scaling-stroke" }, svg);
  svgEl("text", { x: W - 2, y: 10, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = opts.fmt(y1);
  svgEl("text", { x: W - 2, y: H - 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = opts.fmt(y0);
  svgEl("text", { x: 2, y: H - 3, "font-size": 9, fill: css("--ink-3") }, svg).textContent = dayLabel(rows[0].day);
  const cursor = svgEl("line", { x1: 0, x2: 0, y1: 0, y2: H, stroke: css("--ink-2"), "stroke-width": 1, "vector-effect": "non-scaling-stroke", visibility: "hidden" }, svg);
  const hit = svgEl("rect", { x: 0, y: 0, width: W, height: H, fill: "transparent" }, svg);
  const show = (k, ev) => {
    cursor.setAttribute("x1", X(rows[k].day)); cursor.setAttribute("x2", X(rows[k].day)); cursor.setAttribute("visibility", "visible");
    const tip = $("tip"); tip.hidden = false;
    tip.innerHTML = `${dayLabel(rows[k].day)}<br><span style="color:var(--model)">Model ${opts.fmt(pr[k])} (90% band ${opts.fmt(lo[k])}–${opts.fmt(hi[k])})</span>${ob[k] != null ? `<br><span style="color:var(--measured)">Measured ${opts.fmt(ob[k])}</span>` : ""}`;
    const r = svg.getBoundingClientRect(), x = ev ? ev.clientX : r.left + (X(rows[k].day) / W) * r.width, y = ev ? ev.clientY : r.top;
    tip.style.left = `${Math.min(x + 12, innerWidth - 200)}px`; tip.style.top = `${y + 12}px`;
  };
  hit.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect(); const day = d0 + Math.round(((ev.clientX - r.left) / r.width) * (d1 - d0));
    const k = rows.findIndex((x) => x.day >= day); if (k >= 0) show(k, ev);
  });
  hit.addEventListener("mouseleave", () => { $("tip").hidden = true; cursor.setAttribute("visibility", "hidden"); });
  // keyboard: focus the chart and step through days with the arrow keys
  svg.setAttribute("tabindex", "0"); let kk = rows.length - 1;
  svg.onkeydown = (ev) => { if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") { ev.preventDefault(); kk = Math.max(0, Math.min(rows.length - 1, kk + (ev.key === "ArrowLeft" ? -1 : 1))); show(kk); } };
  svg.onblur = () => { $("tip").hidden = true; cursor.setAttribute("visibility", "hidden"); };
}
function irrChart(svg) {
  svg.innerHTML = "";
  const W = 300, H = 40;
  const rows = S.days.map((d) => ({ day: d.day, f: d.fields[sel], c: d.curtailed })).filter((r) => r.f);
  if (!rows.length) return;
  const mx = Math.max(10, ...rows.map((r) => r.f.irr_mm || 0)), bw = W / D;
  let p = "", pd = "";
  rows.forEach((r) => {
    const h = ((r.f.irr_mm || 0) / mx) * H; if (h <= 0) return;
    const x = r.day * bw;
    p += `M${x.toFixed(2)},${H}v${(-h).toFixed(2)}h${(bw * 0.8).toFixed(2)}v${h.toFixed(2)}z`;
    const hd = h * (r.f.desal || 0);
    if (hd > 0) pd += `M${x.toFixed(2)},${H}v${(-hd).toFixed(2)}h${(bw * 0.8).toFixed(2)}v${hd.toFixed(2)}z`;
  });
  svgEl("path", { d: p, fill: css("--cyan"), opacity: 0.45 }, svg);
  svgEl("path", { d: pd, fill: css("--cyan") }, svg);
}
function exportFieldCsv() {
  const rows = [["day", "date", "field", "crop", "irrigation_mm_applied", "desal_fraction", "soil_moisture_measured", "soil_moisture_model", "soil_moisture_model_lo90", "soil_moisture_model_hi90",
    "canopy_measured", "canopy_model", "salinity_measured_dS_m", "salinity_model_dS_m"]];
  const c = (fieldsNow()[sel] || {}).crop || "";
  S.days.forEach((d) => { const f = d.fields[sel]; if (f) rows.push([d.day, dayLabel(d.day), FIELD_IDS[sel], c, f.irr_mm, f.desal, f.sw_obs, f.sw_pred, f.sw_lo, f.sw_hi, f.cc_obs ?? "", f.cc_pred, f.ec_obs, f.ec_pred]); });
  download(`worldlab-${FIELD_IDS[sel]}-${meta.run || "season"}.csv`, rows.map((r) => r.join(",")).join("\n"), "text/csv");
}

// ------------------------------------------------------------ incidents: from divergence to verified recovery
function incidentList() {
  const ev = S.events, out = [];
  ev.forEach((e, k) => {
    if (e.kind !== "anomaly") return;
    const next = ev.findIndex((x, j) => j > k && x.kind === "anomaly");
    const seg = ev.slice(k + 1, next >= 0 ? next : undefined);
    out.push({ a: e, seg, idx: k });
  });
  return out;
}
function incidentFacts(inc) {
  const { a, seg } = inc, d = a.data, fi = d.field_index;
  const tests = seg.filter((e) => e.kind === "field_test" || e.kind === "look");
  const hyps = seg.filter((e) => e.kind === "hypothesis").map((e) => e.data);
  const concl = {}; seg.filter((e) => e.kind === "conclusion").forEach((e) => (concl[e.data.hypothesis_id] = e.data));
  const fixes = seg.filter((e) => e.kind === "adjust" || (e.kind === "model_update" && e.data.finding) || e.kind === "rebalance" || e.kind === "anomaly_dismissed" || e.kind === "controller");
  const identified = Object.values(concl).some((c) => c.verdict === "supported") || seg.some((e) => e.kind === "model_update" && e.data.finding);
  const actDay = fixes.length ? fixes[0].t : null;
  // recovery: does the measured signal return inside the model's band after the action?
  let recovery = null;
  if (actDay != null) {
    const sig = d.signal, after = S.days.filter((x) => x.day >= actDay && x.day <= actDay + 45);
    const back = after.find((x) => { const f = x.fields[fi]; return f && f[sig + "_obs"] != null && f[sig + "_obs"] >= f[sig + "_lo"] && f[sig + "_obs"] <= f[sig + "_hi"]; });
    const seen = after.length ? after[after.length - 1].day : null;
    recovery = back ? { ok: true, day: back.day, lag: back.day - actDay } : { ok: false, until: seen };
  }
  const open = !!(S.status && S.status.anomaly && S.status.anomaly.detected_day === d.detected_day && S.status.anomaly.field === d.field);
  return { d, fi, tests, hyps, concl, fixes, identified, actDay, recovery, open };
}
function currentIncident() {
  const list = incidentList(); if (!list.length) return null;
  const inc = list[list.length - 1];
  const ld = lastDay(), open = !!(S.status && S.status.anomaly);
  if (ld && ld.day > inc.a.data.detected_day + 40 && !open) return null;
  return { ...inc, open };
}
function renderIncident() {
  const inc = currentIncident(), open = inc && inc.open;
  $("incident").hidden = !open;
  document.body.classList.toggle("incident-on", !!open);
  if (open) $("incidentText").textContent = `Field ${inc.a.data.field} · ${inc.a.data.signal_label} ${inc.a.data.direction} · measured ${dayLabel(inc.a.data.detected_day)}`;
}
function incidentHtml(inc, full) {
  const F = incidentFacts(inc), { d } = F;
  const steps = [["Detect the divergence", true], ["Gather evidence", F.tests.length > 0], ["Identify the cause", F.identified], ["Repair or correct", F.fixes.length > 0], ["Recovery observed", !!(F.recovery && F.recovery.ok)]];
  const nowStep = steps.findIndex((s) => !s[1]);
  const day = S.days.find((x) => x.day === d.detected_day);
  const f = day && day.fields[F.fi];
  const sig = d.signal, unit = sig === "ec" ? " dS/m" : sig === "sw" ? " m³/m³" : "";
  const dec = sig === "sw" ? 3 : sig === "cc" ? 2 : 1;
  const obs = f && f[sig + "_obs"], pred = f && f[sig + "_pred"];
  const pert = S.perturbations.find((p) => p.field === d.field || p.field === "all");
  const done = S.status && S.status.result;
  const rec = F.recovery;
  const recText = F.actDay == null ? "No repair or correction yet." : rec.ok ? `Measured ${d.signal_label} was back inside the model's band on ${dayLabel(rec.day)}, ${rec.lag} days after the first action (${dayLabel(F.actDay)}).` : `Not back inside the band by ${dayLabel(rec.until)}. A repair command was issued on ${dayLabel(F.actDay)}; recovery has not been observed yet.`;
  return `
    <p class="eyebrow" style="color:var(--alarm)">Field ${esc(d.field)} ${esc(crop(d.crop))}</p>
    <h3 class="inc-t">${esc(cap(d.signal_label))} ${esc(d.direction)}</h3>
    <p class="note" style="margin:0 0 8px">Drift began around ${dayLabel(d.onset_day)}; the alarm fired on the measurement of ${dayLabel(d.detected_day)}. Tests and repairs are logged on the day they were taken${F.actDay != null ? ` (${dayLabel(F.actDay)})` : ""}.</p>
    <ol class="inv-steps">${steps.map((s, k) => `<li class="${s[1] ? "done" : k === nowStep ? "now" : ""}"><i aria-hidden="true">${s[1] ? "✓" : k + 1}</i>${s[0]}<span class="sr-only">${s[1] ? " (done)" : " (open)"}</span></li>`).join("")}</ol>
    ${obs != null ? `<p class="inv-h">At detection</p><div class="mvp"><div class="p"><span>Model predicted</span><b>${fmt(pred, dec)}${unit}</b><small>90% band ${fmt(f[sig + "_lo"], dec)}–${fmt(f[sig + "_hi"], dec)}</small></div><div class="m"><span>Measured</span><b>${fmt(obs, dec)}${unit}</b></div></div>` : ""}
    <p class="inv-h">Competing hypotheses</p>${F.hyps.length ? F.hyps.map((h) => { const c = F.concl[h.id]; return `<div class="hyp ${c ? c.verdict : "open"}"><span class="st">${c ? c.verdict : "open"}</span>${esc(h.statement)}${full ? `<br><span class="note">Predicts: ${esc(h.prediction)}${c ? `. Evidence: ${esc(c.evidence)}` : ""}</span>` : ""}</div>`; }).join("") : `<p class="note">None recorded yet.</p>`}
    ${F.tests.length ? `<p class="inv-h">Evidence</p>${F.tests.map((e) => `<div class="test"><time>${dayLabel(e.t)}</time> ${e.kind === "look" ? `Drone image: canopy <b>${fmt(e.data.canopy_cover_measured, 2)}</b> vs ${fmt(e.data.canopy_cover_predicted, 2)} predicted (${esc(e.data.source || "perception")})` : esc(cap(testText(e.data)))}</div>`).join("")}` : ""}
    ${F.fixes.length ? `<p class="inv-h">What it did</p>${F.fixes.map((e) => `<div class="fix"><time>${dayLabel(e.t)}</time> ${streamItem(e) ? streamItem(e)[1] : esc(e.kind)}</div>`).join("")}` : ""}
    <p class="inv-h">Recovery check</p><p class="rec ${rec && rec.ok ? "ok" : ""}">${recText}</p>
    ${full ? `<figure class="chart"><figcaption>${esc(cap(d.signal_label))} in ${esc(d.field)}: model band and measurements around the incident</figcaption><svg class="incChart" data-fi="${F.fi}" data-sig="${sig}" data-d0="${Math.max(0, d.onset_day - 25)}" data-d1="${Math.min(D - 1, (F.actDay ?? d.detected_day) + 45)}" viewBox="0 0 300 80" preserveAspectRatio="none"></svg></figure>` : ""}
    ${pert && done ? `<p class="note">Hidden cause, revealed after the season: ${esc(pert.note)} on ${dayLabel(pert.day)}.</p>` : pert ? `<p class="note">The true cause stays hidden until the season ends.</p>` : ""}
    ${full ? "" : `<button class="ghost sm" type="button" data-open-incidents>Open in Incidents</button>`}`;
}
function renderInvestigation() {
  const inc = currentIncident();
  const show = inc && invClosedFor !== inc.a.seq && !drawer;
  $("investigation").hidden = !show;
  $("missionPanel").classList.toggle("dimmed", !!show);
  if (!show) return;
  const k = `${inc.a.seq}|${S.events.length}|${S.days.length > inc.a.data.detected_day + 46 ? "x" : S.days.length}`;
  if ($("invBody").dataset.k === k) return; $("invBody").dataset.k = k;
  $("invBody").innerHTML = incidentHtml(inc, false);
  const b = $("invBody").querySelector("[data-open-incidents]"); if (b) b.onclick = () => openView("incidents");
}
function incidentsHtml() {
  const list = incidentList();
  if (!list.length) return `<p class="empty">No incidents ${S.status && S.status.result ? "this season" : "so far"}. An incident opens when a field's measurements leave the model's 90% prediction band.</p>`;
  return list.slice().reverse().map((inc) => {
    const F = incidentFacts(inc);
    const status = F.open ? "Open" : F.recovery && F.recovery.ok ? "Resolved, recovery observed" : F.fixes.length ? "Action taken, recovery not yet observed" : "Closed";
    return `<section class="inc-card"><div class="inc-head"><b>${esc(inc.a.data.field)}: ${esc(inc.a.data.signal_label)} ${esc(inc.a.data.direction)}</b><span class="pill ${F.open ? "alarm" : ""}">${status}</span></div>${incidentHtml(inc, true)}</section>`;
  }).join("");
}
function drawIncidentCharts() {
  document.querySelectorAll(".incChart").forEach((svg) => {
    const fi = Number(svg.dataset.fi), sig = svg.dataset.sig;
    const dec = sig === "sw" ? 3 : sig === "cc" ? 2 : 1;
    bandChart(svg, fi, sig, { fmt: (v) => fmt(v, dec), marks: markersFor(fi), d0: Number(svg.dataset.d0), d1: Number(svg.dataset.d1), min: sig === "sw" ? undefined : 0, sparse: sig === "cc", thr: sig === "ec" ? SALT[(fieldsNow()[fi] || {}).crop] : null });
  });
}

function renderLegend() {
  const box = $("ovLegend");
  if (!overlay || !OV[overlay]) { box.hidden = true; return; }
  const o = OV[overlay];
  box.hidden = false;
  box.innerHTML = `<b>${esc(o.label)}</b><div class="ramp" style="background:linear-gradient(90deg,${o.ramp.join(",")})"></div><div class="ends"><span>${o.lo} ${esc(o.unit)}</span><span>${o.hi} ${esc(o.unit)}</span></div><p class="note">${overlay === "health" ? "Measured canopy as a percentage of the model's prediction; not an overall health score." : "Field colour from the latest sensor reading."} Fields without a reading stay natural.</p>`;
}
let OV = {};

// ------------------------------------------------------------ 2D field map (when the 3D view can't start)
const RAMP2D = { health: [50, 110, ["#f3e7c6", "#9fd28a", "#2f8f5b"]], moisture: [0.05, 0.3, ["#e9d7b6", "#7cc3d6", "#1d6fa3"]], salinity: [1, 12, ["#f1e9c9", "#e6a15a", "#b33a2b"]], water: [0, 12, ["#efe6d2", "#7fd0e6", "#1b8bb5"]] };
function rampAt(stops, t) { t = Math.max(0, Math.min(1, t)); const k = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1))), u = t * (stops.length - 1) - k; const a = stops[k].match(/\w\w/g).map((h) => parseInt(h, 16)), b = stops[k + 1].match(/\w\w/g).map((h) => parseInt(h, 16)); return `rgb(${a.map((v, j) => Math.round(v + (b[j] - v) * u)).join(",")})`; }
function renderMap2d() {
  const box = $("map2d"); if (box.hidden) return;
  const ld = lastDay(), fl = fieldsNow(), an = S.status && S.status.anomaly;
  const k = `${S.days.length}|${sel}|${overlay}|${an ? an.field : ""}|${fl.map((f) => f.crop).join()}`;
  if (box.dataset.k === k) return; box.dataset.k = k;
  const cells = FIELD_IDS.map((id, i) => {
    const f = ld && ld.fields[i], w = ld && ld.world && ld.world[i], c = fl[i] || {};
    let fill = "#5b4630", val = "";
    if (overlay && f && w && w.sown) {
      const [lo, hi, stops] = RAMP2D[overlay];
      const v = overlay === "health" ? (f.cc_pred > 0.05 && lastObs(i, "cc") ? (100 * lastObs(i, "cc").f.cc_obs) / lastObs(i, "cc").f.cc_pred : null) : overlay === "moisture" ? f.sw_obs : overlay === "salinity" ? f.ec_obs : f.irr_mm;
      if (v != null) { fill = rampAt(stops, (v - lo) / (hi - lo)); val = overlay === "health" ? `${Math.round(v)}%` : fmt(v, overlay === "moisture" ? 3 : 1); }
    } else if (w && w.sown && !w.done) fill = rampAt(["#6b5a3a", "#4f8a3a", "#2f7a3a"], Math.min(1, (w.cc || 0) / 0.85));
    else if (w && w.done) fill = "#a88a4a";
    const x = 20 + (i % 3) * 200, y = 20 + Math.floor(i / 3) * 140;
    const status = !c.crop ? "Fallow" : !w || !w.sown ? "Not sown" : w.done ? "Harvested" : `${Math.round(100 * Math.min(w.stage, 1))}% grown`;
    return `<g class="m2-field ${i === sel ? "sel" : ""} ${an && an.field_index === i ? "alarm" : ""}" data-i="${i}" tabindex="0" role="button" aria-label="${id} ${esc(crop(c.crop))}, ${status}${val ? `, ${val}` : ""}">
      <rect x="${x}" y="${y}" width="180" height="120" rx="10" fill="${fill}"/>
      <text x="${x + 12}" y="${y + 24}" class="m2-id">${id}</text><text x="${x + 12}" y="${y + 46}" class="m2-crop">${esc(c.crop ? crop(c.crop) : "Fallow")}</text>
      <text x="${x + 12}" y="${y + 66}" class="m2-st">${esc(status)}</text>${val ? `<text x="${x + 168}" y="${y + 24}" text-anchor="end" class="m2-val">${esc(val)}</text>` : ""}
      ${an && an.field_index === i ? `<text x="${x + 12}" y="${y + 106}" class="m2-alarm">⚠ ${esc(an.signal_label)} alarm</text>` : ""}</g>`;
  }).join("");
  box.innerHTML = `<svg viewBox="0 0 620 300" role="group" aria-label="Six fields, 2D map">${cells}</svg>`;
  box.querySelectorAll(".m2-field").forEach((g) => { g.onclick = () => select(Number(g.dataset.i)); g.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(Number(g.dataset.i)); } }; });
}

// ------------------------------------------------------------ navigation: one destination at a time, kept in the URL
const DRAWERS = {
  plan: { title: "Plan", tabs: [["plan", "Season plan"], ["versions", "Plan history"]] },
  research: { title: "Research lab", tabs: [["trials", "Trial plots"], ["traits", "Crop traits"], ["rl", "Irrigation policy"]] },
  incidents: { title: "Incidents", tabs: [] },
  agent: { title: "The AI agent", tabs: [["record", "Decision record"], ["components", "AI components"], ["ledger", "Audit ledger"]] },
  results: { title: "Results", tabs: [["report", "Harvest report"], ["seasons", "Your seasons"]] },
  badges: { title: "Achievements", tabs: [] },
};
let drawerTab = null, drawerKey = "", hashLock = false;
function openView(view, tab, fromHash = false) {
  if (view === "planner") { openPlanner(); return; }
  if (!view || view === "farm") { closeDrawer(fromHash); return; }
  if (!DRAWERS[view]) return;
  if (!$("planner").hidden) closePlanner();
  if (!drawer) lastFocus = document.activeElement;
  drawer = view; drawerTab = tab && DRAWERS[view].tabs.some((t) => t[0] === tab) ? tab : (DRAWERS[view].tabs[0] || [null])[0];
  $("drawer").hidden = false; $("drawerTitle").textContent = DRAWERS[view].title;
  $("drawerTabs").setAttribute("role", "tablist");
  $("drawerTabs").innerHTML = DRAWERS[view].tabs.map(([k, l]) => `<button type="button" role="tab" data-t="${k}" aria-selected="${k === drawerTab}" class="${k === drawerTab ? "on" : ""}">${l}</button>`).join("");
  $("drawerTabs").querySelectorAll("button").forEach((b) => (b.onclick = () => openView(view, b.dataset.t)));
  markNav(view);
  drawerKey = ""; renderDrawer(); dirty = true;
  if (!fromHash) setHash(`${view}${drawerTab ? `/${drawerTab}` : ""}`);
  $("drawerTitle").focus({ preventScroll: true });
}
function closeDrawer(fromHash = false) {
  const was = drawer;
  drawer = null; $("drawer").hidden = true; markNav("farm"); dirty = true;
  if (!fromHash && was) setHash("");
  if (was && lastFocus && lastFocus.isConnected) lastFocus.focus({ preventScroll: true });
}
function markNav(view) { document.querySelectorAll("[data-view]").forEach((b) => { if (b.dataset.view === view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); }); }
function setHash(h) { hashLock = true; if (h) location.hash = h; else history.pushState(null, "", location.pathname + location.search); setTimeout(() => (hashLock = false), 0); }
function applyHash() {
  if (hashLock) return;
  const [v, t] = location.hash.replace(/^#/, "").split("/");
  openView(v || "farm", t === "beliefs" ? "traits" : t, true);
}
function renderDrawer() {
  const key = `${drawer}|${drawerTab}|${S.drone.length}|${S.trials.length}|${S.rl_train.length}|${!!S.rl}|${S.plan && S.plan.plan_id}|${S.beliefs && S.beliefs.day}|${S.events.length}|${S.days.length}|${progress ? progress.level.xp : 0}|${traceFilter}|${ledgerQ}|${ledgerN}`;
  if (key === drawerKey) return; drawerKey = key;
  const b = $("drawerBody");
  const keepScroll = b.scrollTop;
  if (drawer === "agent") { b.innerHTML = drawerTab === "record" ? agentHtml() : drawerTab === "components" ? componentsHtml() : ledgerHtml(); wireAgent(); }
  else if (drawer === "research") { b.innerHTML = drawerTab === "trials" ? trialsHtml() : drawerTab === "traits" ? beliefsHtml() : rlHtml(); if (drawerTab === "rl") drawRl(); }
  else if (drawer === "plan") { b.innerHTML = drawerTab === "versions" ? versionsHtml() : planHtml(); const o = $("openPlanner"); if (o) o.onclick = openPlanner; }
  else if (drawer === "incidents") { b.innerHTML = incidentsHtml(); drawIncidentCharts(); }
  else if (drawer === "results") {
    if (drawerTab === "seasons") { b.innerHTML = `<p class="empty">Loading…</p>`; historyHtml().then((h) => { if (drawer === "results" && drawerTab === "seasons") b.innerHTML = h; }); }
    else { b.innerHTML = reportHtml(); wireReport(); }
  }
  else if (drawer === "badges") b.innerHTML = badgesHtml();
  b.scrollTop = keepScroll;
  b.querySelectorAll("[data-goto]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); goTo(a.dataset.goto); }));
}

// ------------------------------------------------------------ research: trials, traits, irrigation policy
function rangeSvg(lo, hi, med, meas, max) {
  const X = (v) => 4 + (v / max) * 152;
  return `<svg viewBox="0 0 160 14" width="160" height="14" aria-hidden="true"><line x1="4" x2="156" y1="7" y2="7" stroke="rgba(255,255,255,.12)"/><rect x="${X(lo)}" y="3" width="${Math.max(2, X(hi) - X(lo))}" height="8" rx="2" fill="${css("--model-band")}" stroke="${css("--model")}"/><line x1="${X(med)}" x2="${X(med)}" y1="2" y2="12" stroke="${css("--model")}" stroke-width="1.5"/><circle cx="${X(meas)}" cy="7" r="3.6" fill="${css("--measured")}"/></svg>`;
}
function trialsHtml() {
  if (!S.trials.length) return `<p class="empty">No trial plots yet. Each plot gets a predicted yield range before it is planted; the harvest then shows whether the model was right.</p>`;
  const max = Math.max(...S.trials.map((t) => Math.max(t.predicted_yield_90pct[1], t.measured_yield_t_ha))) * 1.05;
  const held = S.trials.filter((t) => t.prediction_held).length, st = S.status || {};
  const crops = [...new Set(S.trials.map((t) => t.crop))];
  const plans = kinds("plan").map((e) => e.data);
  const before = plans[0], after = plans[plans.length - 1];
  const changed = before && after && before !== after
    ? `Before the trials, plan ${before.plan_id} projected ${fmt(before.people_p10)} people in a bad year on published crop values. After calibration, plan ${after.plan_id} projects ${fmt(after.people_p10)} (${signed(Math.round(after.people_p10 - before.people_p10))}). Crops changed on ${before.fields.filter((f, i) => f.crop !== after.fields[i].crop).map((f) => f.field).join(", ") || "no field"}.`
    : "";
  const rows = S.trials.map((t) => {
    const [lo, hi] = t.predicted_yield_90pct, m = t.measured_yield_t_ha, resid = m - t.predicted_yield_median;
    const outBy = m < lo ? lo - m : m > hi ? m - hi : 0;
    return `<tr><td colspan="6" class="trow"><details><summary><span>${crop(t.crop)}</span><span>${t.plot} plot</span><span>${dayLabel(t.sow)}</span><span>${rangeSvg(lo, hi, t.predicted_yield_median, m, max)}</span><span class="n">${yfmt(m)} t/ha</span><span>${t.prediction_held ? '<span class="ok">Held</span>' : '<span class="miss">Missed</span>'}</span></summary>
      <p>Predicted ${yfmt(lo)}–${yfmt(hi)} t/ha (median ${yfmt(t.predicted_yield_median)}), measured ${yfmt(m)} t/ha: ${resid >= 0 ? "+" : ""}${fmt(resid, 2)} t/ha from the median${outBy ? `, outside the 90% range by ${fmt(outBy, 2)} t/ha` : ", inside the 90% range"}. Canopy inside the predicted band on ${t.canopy_inside_band_pct}% of drone visits. Sown ${dayLabel(t.sow)} on the ${t.plot} plot${t.plot === "saline" ? " (exposes salt tolerance)" : t.sow > 120 ? " (late sowing: exposes heat at flowering)" : ""}, harvested ${dayLabel(t.harvest_day)}.${t.prediction_held ? "" : " A miss is evidence: calibration uses it to correct this crop's traits."}</p></details></td></tr>`;
  }).join("");
  return `<div class="summary-row"><div><b>${st.plots_used ?? S.trials.length}</b><span>of ${st.plots_budget ?? 16} trial plots used</span></div><div><b>${crops.length}</b><span>crops tested</span></div><div><b>${held} of ${S.trials.length}</b><span>predictions held</span></div><div><b>${S.trials.length - held}</b><span>useful misses</span></div></div>
    ${changed ? `<p>${changed} <a href="#" data-goto="plan">See the plans</a></p>` : ""}
    <table class="trials"><thead><tr><th>Crop</th><th>Plot</th><th>Sown</th><th>Predicted 90% range and measured</th><th class="n">Measured</th><th>Prediction</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note">Range: the model's 90% prediction interval for yield, written down before planting. Open a row for the detail.</p>`;
}
function beliefsHtml() {
  if (!S.beliefs) return `<p class="empty">No crop beliefs yet.</p>`;
  const crops = [...S.beliefs.crops].sort((a, b) => b.plots - a.plots);
  const cal = {}; kinds("model_update").forEach((e) => (e.data.crops || []).forEach((c) => (cal[c.crop] = c)));
  const cell = (c, k) => {
    const t = c.traits[k], sd0 = t.prior_sd, c0 = k === "wp" || k === "cgc" ? 1 : 0, lo = c0 - 3 * sd0, hi = c0 + 3 * sd0;
    const X = (v) => Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
    const narrowed = t.sd < 0.75 * sd0, red = Math.round(100 * (1 - t.sd / sd0));
    const U = TRAIT_UNIT[k];
    return `<div class="tcell ${narrowed ? "id" : "weak"}"><svg viewBox="0 0 100 18" preserveAspectRatio="none" aria-hidden="true"><line x1="${X(c0 - 2 * sd0)}" x2="${X(c0 + 2 * sd0)}" y1="9" y2="9" stroke="rgba(255,255,255,.12)" stroke-width="6" stroke-linecap="round" vector-effect="non-scaling-stroke"/><line x1="${X(t.mean - 2 * t.sd)}" x2="${X(t.mean + 2 * t.sd)}" y1="9" y2="9" stroke="${css("--model")}" stroke-width="2.5" vector-effect="non-scaling-stroke"/><path d="M${X(t.mean)},9h0" stroke="${css("--model")}" stroke-width="8" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>
      <span class="tv">${U(t.mean)} <small>± ${k === "wp" || k === "cgc" ? fmt(2 * t.sd, 2) : fmt(2 * t.sd, 1)}</small></span><span class="tr">${narrowed ? `uncertainty −${red}%` : c.plots ? "weakly identified" : "not tested"}</span></div>`;
  };
  return `<p style="margin:0 0 10px">Each crop's four hidden local-variety traits, relative to the published values: water productivity and canopy growth as multipliers, heat tolerance as a shift in °C, salinity threshold as a shift in dS/m. Grey is the published prior (±2 sd); cyan is the current belief, mean and 95% interval. This is a belief about a trait, not the 90% prediction band used for field measurements.</p>
    <div class="forest"><span class="h">Crop (plots)</span>${Object.values(TRAIT).map((t) => `<span class="h">${t}</span>`).join("")}${crops.map((c) => `<span>${crop(c.crop)} <span style="color:var(--ink-3)">(${c.plots})</span>${cal[c.crop] ? `<br><small class="note">fit: yield error ${cal[c.crop].yield_err_pct}%</small>` : ""}</span>${["wp", "cgc", "heat", "salt"].map((k) => cell(c, k)).join("")}`).join("")}</div>
    <p class="note">"Weakly identified": the trials so far did not narrow this trait (for example heat tolerance stays uncertain unless a plot flowered in the heat). Untested crops keep their published uncertainty.</p>`;
}
function rlStatus() {
  const r = S.rl, ld = lastDay(), ctl = (ld && ld.controller) || (S.status && S.status.controller), res = S.status && S.status.result;
  if (!r) return S.rl_train.length ? "Training" : "Not trained";
  if (r.recommend !== "rl_policy") return "Trained, not deployed (the rule stays)";
  if (res) return ctl === "rl_policy" ? "Completed: irrigated until harvest" : "Superseded: the rule took over during the season";
  if (ctl === "rl_policy") return "Deployed: irrigating now";
  if (S.status && S.status.phase === "season") return "Superseded: the rule took over";
  return "Available, deployment pending";
}
function rlHtml() {
  if (!S.rl && !S.rl_train.length) return `<p class="empty">No policy trained yet. After planning, the scientist can train a daily irrigation policy inside its own model of the farm, then decide whether to use it.</p>`;
  const r = S.rl, c = r && r.held_out_comparison;
  let tradeoff = "";
  if (c) {
    const parts = [`people fed in a bad year ${signed(c.people_p10_change_pct)}%`, `average groundwater ${signed(c.water_change_pct)}%`, `average energy ${signed(c.energy_change_pct)}%`];
    const better = c.policy.reward > c.rule.reward;
    tradeoff = `On ${r.samples ? `${r.samples.test_seasons_per_field} held-out imagined seasons per field` : "held-out imagined seasons"}, the policy compared with the fixed rule: ${parts.join(", ")}. Its reward was ${better ? "higher" : "not higher"} (${fmt(c.policy.reward, 1)} against ${fmt(c.rule.reward, 1)}), so it was ${r.recommend === "rl_policy" ? "deployed" : "not deployed"}.`;
    if (c.people_p10_change_pct < 0 && r.recommend === "rl_policy") tradeoff += " It feeds slightly fewer people in a bad year in exchange for using less water and energy, which the reward values.";
    if (c.water_change_pct > 0 || c.energy_change_pct > 0) tradeoff += " It uses more of the budget than the rule to grow more food; under the hard budget neither controller can exceed the limits.";
  }
  const top = c ? `<div class="deltas"><div><b>${signed(c.people_p10_change_pct)}%</b><span>people fed, bad year</span></div><div><b>${signed(c.people_mean_change_pct)}%</b><span>people fed, average</span></div><div><b>${signed(c.water_change_pct)}%</b><span>groundwater</span></div><div><b>${signed(c.energy_change_pct)}%</b><span>energy</span></div></div>` : `<p class="note">Training: ${S.rl_train.length} iterations so far.</p>`;
  const tbl = c ? `<table><thead><tr><th>Held-out imagined seasons</th><th class="n">Fixed rule</th><th class="n">RL policy</th></tr></thead><tbody>
    <tr><td>People fed, bad year (10th percentile)</td><td class="n">${fmt(c.rule.people_p10)}</td><td class="n">${fmt(c.policy.people_p10)}</td></tr>
    <tr><td>People fed, average</td><td class="n">${fmt(c.rule.people_mean)}</td><td class="n">${fmt(c.policy.people_mean)}</td></tr>
    <tr><td>Groundwater, average m³</td><td class="n">${fmt(c.rule.water_mean_m3)}</td><td class="n">${fmt(c.policy.water_mean_m3)}</td></tr>
    <tr><td>Energy, average kWh</td><td class="n">${fmt(c.rule.energy_mean_kwh)}</td><td class="n">${fmt(c.policy.energy_mean_kwh)}</td></tr>
    ${c.rule.years_at_budget_pct != null ? `<tr><td>Seasons that reached a hard limit</td><td class="n">${c.rule.years_at_budget_pct}%</td><td class="n">${c.policy.years_at_budget_pct}%</td></tr>` : `<tr><td>Seasons over the water quota</td><td class="n">${c.rule.years_over_quota_pct}%</td><td class="n">${c.policy.years_over_quota_pct}%</td></tr>`}
    <tr><td>Reward (what training maximises)</td><td class="n">${fmt(c.rule.reward, 1)}</td><td class="n">${fmt(c.policy.reward, 1)}</td></tr></tbody></table>` : "";
  const how = r ? `<details class="more" open><summary>How the deployment was decided</summary>
      <p><b>Status:</b> ${esc(rlStatus())}.</p>
      ${r.reward ? `<p><b>Reward:</b> ${esc(r.reward)}.</p>` : ""}
      ${r.deployment_criterion ? `<p><b>Criterion:</b> ${esc(r.deployment_criterion)}.</p>` : `<p><b>Criterion:</b> deploy if the policy's reward on held-out seasons beats the rule's.</p>`}
      ${r.samples ? `<p><b>Samples:</b> ${r.samples.training_seasons_per_field} training, ${r.samples.validation_seasons_per_field} validation and ${r.samples.test_seasons_per_field} test seasons per planted field (seeds ${r.samples.seeds.join(", ")}); ${fmt(r.imagined_farm_seasons)} imagined farm-seasons in ${r.trained_seconds} s; a ${r.policy_parameters}-parameter network trained by evolution strategies.</p>` : ""}
      <p class="note">All of these are imagined seasons sampled from the scientist's calibrated model, not the one realised harvest and not an external field validation. During the season the anomaly detector keeps checking the model against the farm.</p></details>` : "";
  return `${tradeoff ? `<p style="margin:0 0 10px">${tradeoff}</p>` : ""}<div class="rl-grid"><div>${top}<figure class="chart" style="margin:0"><figcaption>People fed per season during training, in the scientist's model</figcaption><svg id="rlCurve" viewBox="0 0 420 150"></svg></figure><div class="legend"><span class="lg model">Training seasons, average</span><span class="lg meas">Validation seasons, bad year</span></div></div><div>${tbl}<figure class="chart" style="margin:10px 0 0"><figcaption>Policy's irrigation multiplier by week (held-out seasons; 1 = the plan's rule)</figcaption><svg id="rlMult" viewBox="0 0 420 70"></svg></figure></div></div>${how}`;
}
function drawRl() {
  const svg = $("rlCurve"); if (!svg) return;
  const H = 150, W = 420, L = 34, B = 18;
  const tr = S.rl_train.filter((x) => x.iter >= 0);
  const val = (S.rl && S.rl.validation) || [];
  const ys = [...tr.map((x) => x.people), ...val.map((x) => x.val_people_p10)].filter((v) => v != null);
  if (ys.length) {
    const n = Math.max(10, tr.length, ...val.map((v) => v.iter));
    const [y0, y1] = nice(Math.min(...ys), Math.max(...ys));
    const X = (i) => L + (i / n) * (W - L - 6), Y = (v) => (H - B) - ((v - y0) / (y1 - y0)) * (H - B - 6);
    [y0, (y0 + y1) / 2, y1].forEach((v) => { svgEl("line", { x1: L, x2: W, y1: Y(v), y2: Y(v), stroke: "rgba(255,255,255,.08)" }, svg); svgEl("text", { x: L - 4, y: Y(v) + 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = fmt(v); });
    svgEl("text", { x: W - 4, y: H - 4, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = "training iteration";
    svgEl("path", { d: tr.map((x, k) => `${k ? "L" : "M"}${X(x.iter + 1).toFixed(1)},${Y(x.people).toFixed(1)}`).join(""), fill: "none", stroke: css("--model"), "stroke-width": 2 }, svg);
    val.forEach((v) => svgEl("circle", { cx: X(v.iter), cy: Y(v.val_people_p10), r: 4.5, fill: css("--measured") }, svg));
  }
  const ms = $("rlMult"), mult = S.rl && S.rl.policy_irrigation_multiplier_by_week;
  if (ms && mult && mult.length) {
    const W2 = 420, H2 = 70, mx = Math.max(1.5, ...mult), X = (i) => 30 + (i / (mult.length - 1)) * (W2 - 36), Y = (v) => H2 - 12 - (v / mx) * (H2 - 18);
    svgEl("line", { x1: 30, x2: W2, y1: Y(1), y2: Y(1), stroke: "rgba(255,255,255,.25)", "stroke-dasharray": "3 3" }, ms);
    svgEl("text", { x: 26, y: Y(1) + 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, ms).textContent = "1×";
    svgEl("path", { d: mult.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(""), fill: "none", stroke: css("--cyan"), "stroke-width": 2 }, ms);
    svgEl("text", { x: 30, y: H2 - 1, "font-size": 9, fill: css("--ink-3") }, ms).textContent = "Oct";
    svgEl("text", { x: W2 - 4, y: H2 - 1, "text-anchor": "end", "font-size": 9, fill: css("--ink-3") }, ms).textContent = "Jun";
  }
}

// ------------------------------------------------------------ plan and plan history
function planHtml() {
  const p = S.plan;
  const open = `<p><button class="ghost sm" id="openPlanner" type="button">${mode === "live" ? "Open the crop planner" : "Open the crop planner (preview)"}</button></p>`;
  if (!p) return `<p class="empty">No plan yet. The scientist plans after its trial plots; you can choose crops for any field in the planner first.</p>${open}`;
  const cmp = p.scientist_choice ? (p.scientist_choice.people_p10 > p.people_p10 ? ` With a free choice of crops the scientist would feed ${fmt(p.scientist_choice.people_p10)}.` : " The scientist found no crop mix that does better than your picks.") : "";
  return `<p style="margin:0 0 10px">Plan ${p.plan_id} feeds <b>${fmt(p.people_p10)}</b> people in a bad year (10th percentile) and ${fmt(p.people_p50)} in a typical one. Not knowing the varieties exactly costs ${fmt(p.cost_of_uncertainty_people)} people.${cmp}</p>
    <table><thead><tr><th>Field</th><th>Crop</th><th>Sowing</th><th class="n">Irrigation</th><th class="n">Desalinated</th><th class="n">Nitrogen</th><th class="n">Yield, t/ha: bad, typical, good year</th></tr></thead><tbody>${p.fields.map((f, i) => f.crop ? `<tr><td>${f.field} ${NAMES[i]}</td><td>${crop(f.crop)}${f.farmer_choice ? ' <span class="pill rl">your pick, locked</span>' : ""}</td><td>${dayLabel(f.mgmt.sow)}</td><td class="n">${Math.round(f.mgmt.irr * 100)}% of demand</td><td class="n">${Math.round(f.mgmt.desal * 100)}%</td><td class="n">${fmt(f.mgmt.nfert)} kg/ha</td><td class="n">${f.yield_t_ha_p10_p50_p90.map(yfmt).join(", ")}</td></tr>` : `<tr><td>${f.field} ${NAMES[i]}</td><td colspan="6" style="color:var(--ink-3)">Left fallow</td></tr>`).join("")}</tbody></table>
    <p class="note">The irrigation policy then adjusts the daily schedule if one is deployed (see Research). ${open}</p>`;
}
function versionsHtml() {
  const vs = S.events.filter((e) => e.kind === "plan" || e.kind === "rebalance" || e.kind === "farmer_choices");
  if (!vs.length) return `<p class="empty">No plans yet.</p>`;
  let prev = null;
  return `<ol class="versions">${vs.map((e) => {
    const d = e.data;
    if (e.kind === "farmer_choices") return `<li><b>Your crop choices</b><span class="note">${esc(d.fields.filter((f) => f.crop || f.choice === "fallow").map((f) => `${f.field}: ${f.choice}`).join("; ") || "all fields left to the scientist")}</span></li>`;
    if (e.kind === "rebalance") return `<li><b>Re-planned water, ${dayLabel(e.t)}</b><span>${d.people_p10_before} → ${d.people_p10_after} people in a bad year. ${esc(d.rationale || "")}</span><span class="note">${(d.fields || []).filter((f) => f.changed).map((f) => `${f.field} irrigation ${Math.round(f.irr * 100)}%, desalinated ${Math.round(f.desal * 100)}%`).join("; ")}</span></li>`;
    const why = !prev ? "First plan, on published crop values before any trials." : `Replaced ${prev.plan_id} after ${kinds("model_update").some((u) => u.data.crops && u.seq < e.seq) ? "calibration from the trial plots" : "new information"}: ${signed(Math.round(d.people_p10 - prev.people_p10))} people in a bad year; crops changed on ${d.fields.filter((f, i) => f.crop !== prev.fields[i].crop).map((f) => f.field).join(", ") || "no field"}.`;
    prev = d;
    return `<li><b>Plan ${d.plan_id}</b><span>${fmt(d.people_p10)} people in a bad year: ${d.fields.map((f) => `${f.field} ${crop(f.crop)}`).join(", ")}</span><span class="note">${why} ${esc(d.rationale || "")}</span></li>`;
  }).join("")}</ol>`;
}

// ------------------------------------------------------------ agent: decision record, components, ledger
const PHASE = { observe: "Observe", get_beliefs: "Observe", advance: "Observe", record_hypothesis: "Hypothesize",
  evaluate_trials: "Experiment", run_trials: "Experiment", look_at_field: "Experiment", field_test: "Experiment",
  plan_season: "Decide", train_irrigation_policy: "Decide", start_season: "Act", set_irrigation_controller: "Act", adjust_field: "Act",
  rebalance_water: "Decide", dismiss_anomaly: "Act", fit_crop_models: "Learn", conclude: "Learn", update_model: "Learn", finish: "Learn" };
const PHASES = ["Observe", "Hypothesize", "Experiment", "Decide", "Act", "Learn"];
let traceFilter = "", ledgerQ = "", ledgerN = 100;
function toolEngine(name, res) {
  return ({ observe: "Sensors and farm state", get_beliefs: "Bayesian crop beliefs", advance: "Digital twin with CUSUM alarms",
    record_hypothesis: "Audit ledger", conclude: "Audit ledger", evaluate_trials: "Experiment design (expected information)",
    run_trials: "Trial plots in the farm simulator", fit_crop_models: "Bayesian calibration", plan_season: "Robust planner",
    rebalance_water: "Robust planner", train_irrigation_policy: "Reinforcement learning (evolution strategies)",
    start_season: "Irrigation controller", set_irrigation_controller: "Irrigation controller", adjust_field: "Farm actuators",
    update_model: "Digital twin update", dismiss_anomaly: "Audit ledger", finish: "Audit ledger",
    field_test: "Field test (simulated measurement)" }[name]) || (name === "look_at_field" ? (res && res.source) || "Drone perception" : "Tool");
}
function agentSteps() {
  const out = [];
  S.events.forEach((e) => {
    if (e.kind !== "agent_step") return;
    const d = e.data || {};
    if (d.role === "tool_call") out.push({ day: d.t, tool: d.text, args: d.args || {}, res: null, seq: e.seq });
    else if (d.role === "tool_result") { const c = [...out].reverse().find((x) => x.tool === d.text && !x.res && x.tool); if (c) c.res = d.result || {}; }
    else if (d.role === "agent" && d.text) out.push({ day: d.t, say: d.text, seq: e.seq });
  });
  return out;
}
function brief(r) {
  if (!r) return "";
  if (r.refused) return `<span class="refused">Refused: ${esc(r.refused)}</span>`;
  if (r.error) return `<span class="refused">${esc(r.error)}</span>`;
  return Object.entries(r).filter(([, v]) => v != null && typeof v !== "object").slice(0, 3)
    .map(([k, v]) => `${esc(k.replace(/_/g, " "))} ${esc(typeof v === "number" ? fmt(v, Math.abs(v) < 10 ? 2 : 0) : String(v))}`).join(", ");
}
function loopSvg(cur) {
  const R = 86, cx = 130, cy = 104;
  const pts = PHASES.map((_, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / PHASES.length; return [cx + R * Math.cos(a), cy + R * Math.sin(a)]; });
  return `<svg class="loop" viewBox="0 0 260 210" role="img" aria-label="Agent loop, current step ${cur || "none"}">
    <circle class="arc" cx="${cx}" cy="${cy}" r="${R}"/>
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" fill="${css("--ink-3")}" font-size="11">Decides</text>
    <text x="${cx}" y="${cy + 12}" text-anchor="middle" fill="${css("--ink")}" font-size="12" font-weight="600">${esc(deciderName())}</text>
    ${pts.map(([x, y], i) => `<g class="node ${PHASES[i] === cur ? "on" : ""}"><circle cx="${x}" cy="${y}" r="27"/><text x="${x}" y="${y + 4}">${PHASES[i]}</text></g>`).join("")}</svg>`;
}
function argWhy(a) { return a.rationale || a.reason || a.statement || a.evidence || a.summary || Object.entries(a).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ").slice(0, 160); }
function agentHtml() {
  const steps = agentSteps(), calls = steps.filter((x) => x.tool);
  const last = calls[calls.length - 1], cur = last ? PHASE[last.tool] : null;
  const refused = calls.filter((c) => c.res && (c.res.refused || c.res.error)).length;
  const llm = /Muse/.test(deciderName());
  const intro = llm ? `${esc(deciderName())} chose every tool call below through function calling; its written explanations are shown as "Model explanation". Numerical code does the agronomy.`
    : "This run's decisions come from the scripted protocol: a fixed sequence over the same tools, with no language model. The reasons below are the protocol's recorded rationales.";
  const shown = steps.filter((x) => !traceFilter || (traceFilter === "refused" ? x.res && (x.res.refused || x.res.error) : x.tool ? PHASE[x.tool] === traceFilter : traceFilter === "Explain"));
  const rows = shown.slice().reverse().map((x) => x.say
    ? `<tr><td class="n">${x.day ?? ""}</td><td><span class="phase">Explain</span></td><td colspan="3">${esc(x.say)}<span class="why">Model explanation, recorded in the ledger</span></td></tr>`
    : `<tr><td class="n">${x.day != null ? dayLabel(Math.min(x.day, D - 1)) : ""}</td><td><span class="phase">${PHASE[x.tool] || "Act"}</span></td><td class="tool">${esc(x.tool)}<span class="why">${esc(toolEngine(x.tool, x.res))}</span></td>
       <td>${esc(argWhy(x.args))}<details class="raw"><summary>Raw call</summary><pre>${esc(JSON.stringify({ args: x.args, result: x.res }, null, 1))}</pre></details></td><td>${brief(x.res)}</td></tr>`).join("");
  const filter = `<label class="filter">Show <select id="traceFilter"><option value="">all steps</option>${PHASES.map((p) => `<option value="${p}" ${traceFilter === p ? "selected" : ""}>${p}</option>`).join("")}${llm ? `<option value="Explain" ${traceFilter === "Explain" ? "selected" : ""}>model explanations</option>` : ""}<option value="refused" ${traceFilter === "refused" ? "selected" : ""}>refused or failed</option></select></label>`;
  return `<p style="margin:0 0 10px">${intro} Every action goes through a bounded tool with budgets for trial plots, field tests, water and energy; a call outside the rules is refused and logged.</p>
    <div class="agent-top"><div>${loopSvg(cur)}</div><div>
      <div class="agent-who">
        <div><span>Decides</span><b>${esc(deciderName())}</b><span>${calls.length} tool calls so far</span></div>
        <div><span>Sees</span><b>${esc(perceptionName())}</b><span>${S.drone.length} drone frames</span></div>
        <div><span>Irrigates</span><b>${esc(controllerName())}</b><span>${refused} refused call${refused === 1 ? "" : "s"}</span></div>
      </div>
      ${last ? `<p class="now-act"><b>Latest:</b> ${esc(last.tool)}: ${esc(argWhy(last.args))}</p>` : ""}
      <p class="note" style="margin:0">The loop: observe the farm, write a testable hypothesis, run the experiment that tells explanations apart, decide, act, and learn by correcting the model. For the causal story of an incident (observation, hypothesis, test, evidence, action, outcome) see <a href="#" data-goto="incidents">Incidents</a>.</p>
    </div></div>
    <div class="trace-bar">${filter}<span class="note">${shown.length} of ${steps.length} steps, newest first. Day: when the action was taken.</span></div>
    <table class="trace"><thead><tr><th class="n">Action day</th><th>Step</th><th>Tool and engine</th><th>Why (recorded rationale)</th><th>Result</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="empty">No matching steps.</td></tr>`}</tbody></table>`;
}
function lifecycle() {
  const st = S.status || {}, res = st.result, phase = st.phase, season = phase === "season" || !!res;
  const llm = /Muse/.test(deciderName()), perc = perceptionName();
  const has = (k) => kinds(k).length > 0;
  return {
    spark: llm && /Spark/.test(deciderName()) ? (res ? ["completed", "Decided this run"] : ["running", "Deciding this run"]) : ["inactive", caps && caps.agents && caps.agents.spark ? "Available on this server; not chosen for this run" : "Inactive: no model key in this run"],
    glimmer: /Glimmer/.test(deciderName()) ? (res ? ["completed", "Decided this run"] : ["running", "Deciding this run"]) : ["inactive", "Inactive in this run"],
    sam: perc === "SAM 3.1 + Muse Spark" ? ["running", "Reading drone images"] : ["inactive", "Inactive: simulated perception, labelled as such"],
    vision: perc === "SAM 3.1 + Muse Spark" ? ["running", "Diagnosing drone images"] : ["inactive", "Inactive: simulated perception"],
    scripted: !llm ? (res ? ["completed", "Decided this run"] : ["running", "Deciding this run"]) : ["inactive", "Standing by as fallback"],
    design: has("trial_start") ? ["completed", "Chose the trial plots"] : ["awaiting", "Awaiting the trial season"],
    calib: kinds("model_update").some((e) => e.data.crops) ? ["completed", `Calibrated ${new Set(kinds("model_update").flatMap((e) => (e.data.crops || []).map((c) => c.crop))).size} crops`] : ["awaiting", "Awaiting trial results"],
    twin: res ? ["completed", "Ran beside the farm all season"] : season ? ["running", "Predicting every field"] : ["awaiting", "Starts at sowing"],
    detector: res ? ["completed", `${kinds("anomaly").length} alarm${kinds("anomaly").length === 1 ? "" : "s"} this season`] : season ? ["running", "Watching the measurements"] : ["awaiting", "Starts at sowing"],
    planner: has("plan") ? [res ? "completed" : "available", `${kinds("plan").length} plan${kinds("plan").length === 1 ? "" : "s"}, ${kinds("rebalance").length} re-plan${kinds("rebalance").length === 1 ? "" : "s"}`] : ["awaiting", "Awaiting calibration"],
    rl: S.rl ? [/irrigating now/i.test(rlStatus()) ? "running" : /Completed/.test(rlStatus()) ? "completed" : "available", rlStatus()] : S.rl_train.length ? ["running", "Training"] : ["awaiting", "Not trained yet"],
    ledger: ["running", `${S.events.length} entries`],
  };
}
function componentsHtml() {
  const L = lifecycle();
  const st = (k) => `<span class="src lc-${L[k][0]}">${esc(cap(L[k][0]))}</span> <span class="note">${esc(L[k][1])}</span>`;
  const rows = [
    ["Muse Spark", "meta", "Meta model", "The scientist: decides the next step by calling tools", "Reads the farm state and tool results, writes hypotheses and calls its 19 tools by function calling", "spark"],
    ["Muse Glimmer", "meta", "Meta open weights", "The same scientist on your own GPU", "Any OpenAI-compatible endpoint serving Glimmer, same tools and prompt", "glimmer"],
    ["SAM 3.1", "meta", "Meta model", "Reads drone images", "Segments green plants, white salt crust and brown leaf damage by text prompt; counts and areas feed the diagnosis", "sam"],
    ["Muse Spark vision", "meta", "Meta model", "Diagnoses crop stress from the same image", "Returns a structured diagnosis: healthy, water, salt or pest stress, gaps, with its evidence", "vision"],
    ["Scripted protocol", "rule", "Rules", "Baseline and fallback scientist", "A fixed sequence over the same tools; the comparison the language model must beat", "scripted"],
    ["Experiment design", "num", "Numerical", "Chooses which trial plots to plant", "Scores candidate plots by expected information about the traits that move the plan", "design"],
    ["Bayesian calibration", "num", "Numerical", "Learns each crop's hidden traits", "MAP fit of water productivity, canopy growth, heat and salt tolerance from trial harvests and drone canopy", "calib"],
    ["Digital twin", "num", "Numerical", "Predicts every field with uncertainty", "An ensemble of the crop and soil model run beside the farm, giving the 90% bands in the charts", "twin"],
    ["Anomaly detector", "num", "Numerical", "Notices when reality leaves the prediction", "CUSUM on measured minus predicted soil moisture, salinity and canopy; it pauses the season", "detector"],
    ["Robust planner", "num", "Numerical", "Plans crops, sowing, irrigation, blend and nitrogen", "Maximises people fed in a bad year (10th percentile) within the water quota and energy budget", "planner"],
    ["Reinforcement learning", "num", "Numerical", "Learns a daily irrigation policy", "Evolution strategies train a small neural network inside the agent's own model; deployed only if its held-out reward beats the rule", "rl"],
    ["Audit ledger", "rule", "Integrity", "Makes every step checkable", "A hash-chained, tamper-evident log of each hypothesis, prediction, test, decision and result; missions and achievements are scored from it", "ledger"],
  ];
  return `<p style="margin:0 0 10px">What each part of WorldLab's AI does, and its state in the season on screen: running, completed, available, awaiting data or inactive. Meta models decide and perceive; numerical code does the agronomy and the learning.</p>
    <table class="ai-table"><thead><tr><th>Component</th><th>Kind</th><th>Role</th><th>How it works</th><th>This season</th></tr></thead><tbody>
    ${rows.map(([n, cls, kind, role, how, k]) => `<tr><td>${n}</td><td><span class="src ${cls}">${kind}</span></td><td>${role}</td><td>${how}</td><td>${st(k)}</td></tr>`).join("")}</tbody></table>
    <details class="more"><summary>For developers: enabling the Meta models</summary><p class="note">The hosted server uses Muse Spark and SAM 3.1 when <code>MODEL_API_KEY</code> is set, and Muse Glimmer when <code>WORLDLAB_GLIMMER_BASE_URL</code> points at an OpenAI-compatible endpoint. Without them it falls back to the scripted protocol and simulated perception, and labels the run that way.</p></details>`;
}
function ledgerHtml() {
  const q = ledgerQ.toLowerCase();
  const all = S.events.filter((e) => !q || e.kind.includes(q) || JSON.stringify(e.data).toLowerCase().includes(q));
  const ev = all.slice(-ledgerN).reverse();
  const verify = mode === "live"
    ? '<button class="ghost sm" id="verifyBtn" type="button">Verify the full ledger on the server</button> <span id="verifyOut" role="status"></span>'
    : '<span class="note">A recorded replay omits some large entries, so its chain can\'t be re-verified here; verify a live run on the server.</span>';
  return `<p style="margin:0 0 8px">Each entry stores the hash of the one before, so editing any entry breaks the chain from there on (tamper-evident). A consistent chain shows the record wasn't altered after it was written; it does not prove the observations themselves are true. ${verify}</p>
    <div class="trace-bar"><label class="filter">Search <input id="ledgerQ" type="search" value="${esc(ledgerQ)}" placeholder="kind or text, e.g. anomaly"></label><span class="note">${all.length} matching of ${S.events.length} entries</span></div>
    <table><thead><tr><th class="n">#</th><th>Entry</th><th>Day</th><th>Hash</th><th>Payload</th></tr></thead><tbody>${ev.map((e) => `<tr><td class="n">${e.seq}</td><td>${esc(e.kind.replace(/_/g, " "))}</td><td>${e.t != null ? dayLabel(Math.min(e.t, D - 1)) : ""}</td><td class="hash">${String(e.hash || "").slice(0, 16)}</td><td><details class="raw"><summary>Show</summary><pre>${esc(JSON.stringify(e.data, null, 1)).slice(0, 4000)}</pre></details></td></tr>`).join("")}</tbody></table>
    ${all.length > ledgerN ? `<p><button class="ghost sm" id="ledgerMore" type="button">Show ${Math.min(100, all.length - ledgerN)} older entries</button></p>` : ""}`;
}
function wireAgent() {
  const f = $("traceFilter"); if (f) f.onchange = () => { traceFilter = f.value; renderDrawer(); };
  const q = $("ledgerQ"); if (q) { q.oninput = () => { ledgerQ = q.value; ledgerN = 100; renderDrawer(); const n = $("ledgerQ"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }; }
  const m = $("ledgerMore"); if (m) m.onclick = () => { ledgerN += 100; renderDrawer(); };
  const v = $("verifyBtn"); if (v) v.onclick = verifyLedger;
}
async function verifyLedger() {
  $("verifyOut").textContent = "Checking…";
  try { const r = (await apiJson("api/verify", { timeout: 15000 })).data; $("verifyOut").innerHTML = r.ok ? `<span class="ok">${esc(r.message)}</span>` : `<span class="miss">Verification failed: ${esc(r.message)}. The ledger may have been altered or truncated; the entry named is where the chain breaks.</span>`; }
  catch (e) { $("verifyOut").innerHTML = `<span class="miss">Couldn't reach the server to verify. Try again.</span>`; }
}

// ------------------------------------------------------------ results: harvest report, seasons, achievements
function reportHtml() {
  const res = S.status && S.status.result, m = S.mission, plan = S.plan, proj = lastProj();
  if (!res) return `<p class="empty">The harvest report appears when the season ends.${proj ? ` So far the model projects ${fmt(proj.people_p10)} people in a bad year and ${fmt(proj.people_p50)} in a typical one.` : ""}${mode === "replay" ? ' <button class="ghost sm" type="button" id="toEnd">Skip to the harvest</button>' : ""}</p>`;
  const mt = m ? m.metrics : {};
  const harvest = S.status.harvest || {};
  const goalMet = res.people_fed >= 500;
  const verdict = `${goalMet ? "Season complete; farm goal of 500 people met." : `Season complete; the farm goal of 500 people was not reached (${fmt(res.people_fed)}).`} ${res.within_quota && res.within_energy ? "Water and energy stayed within the limits." : "A resource limit was exceeded."}`;
  const by = res.by_nutrient || {};
  const contrib = {};
  Object.entries(harvest).forEach(([f, h]) => Object.entries(h.people || {}).forEach(([n, v]) => { (contrib[n] = contrib[n] || []).push([`${f} ${crop(h.crop)}`, v]); }));
  const lim = res.limiting;
  const fieldsRows = (plan ? plan.fields : []).map((f, i) => {
    const h = harvest[f.field];
    if (!f.crop) return `<tr><td>${f.field}</td><td colspan="4" style="color:var(--ink-3)">Fallow</td></tr>`;
    const [p10, p50] = f.yield_t_ha_p10_p50_p90;
    const y = h ? h.yield_t_ha : null;
    return `<tr><td>${f.field} ${NAMES[i]}</td><td>${crop(f.crop)}</td><td class="n">${yfmt(p10)}</td><td class="n">${yfmt(p50)}</td><td class="n">${y == null ? "–" : yfmt(y)}${y != null ? (y < p10 ? ' <span class="miss">below bad-year</span>' : y >= p50 ? ' <span class="ok">at or above typical</span>' : "") : ""}</td></tr>`;
  }).join("");
  const faults = mt.faults || [];
  const plans = kinds("plan");
  const story = [
    S.trials.length ? `Grew ${S.trials.length} trial plots; ${S.trials.filter((t) => !t.prediction_held).length} predictions missed and were used for calibration <a href="#" data-goto="trials">(trials)</a>.` : "",
    plans.length ? `Planned ${plans.length > 1 ? `${plans.length} times; the final plan` : "once; the plan"} projected ${fmt(plan.people_p10)} people in a bad year <a href="#" data-goto="plan">(plan)</a>.` : "",
    S.rl ? `Irrigation policy: ${rlStatus().toLowerCase()} <a href="#" data-goto="rl">(policy)</a>.` : "",
    ...faults.map((f) => `${cap(f.label)} in ${f.field} on ${dayLabel(f.day)}: ${f.detected ? `detected ${dayLabel(f.detected_day)} (${f.detected_day - f.day} days later)` : "not detected"}${f.diagnosed ? ", cause identified by test" : ""}${f.recovered ? ", repaired or corrected" : ""} <a href="#" data-goto="incidents">(incident)</a>.`),
    `Harvest: ${fmt(res.people_fed)} people fed against a bad-year plan of ${fmt(plan ? plan.people_p10 : null)} and a typical-year plan of ${fmt(plan ? plan.people_p50 : null)}.`,
  ].filter(Boolean);
  // next steps from the actual bottlenecks
  const next = [];
  if (lim && contrib[lim]) {
    const strong = Object.entries(CROP_LABEL).filter(([k]) => ({ kcal: ["sweet_potato", "cassava", "maize", "potato"], protein_g: ["soybean", "beans", "wheat"], vitA_ug: ["sweet_potato"] }[lim] || []).includes(k)).map(([, l]) => l);
    next.push(`${cap(NUTRIENT[lim])} limited the count (${fmt(by[lim])} person-years against ${fmt(Math.max(...Object.values(by)))} for the best-covered need). Try giving one more field to a crop rich in ${NUTRIENT[lim]}${strong.length ? `, such as ${strong.slice(0, 2).join(" or ")}` : ""}, and compare.`);
  }
  if (res.water_used_m3 < 0.9 * (S.status.water_quota_m3 || 60000)) next.push(`${fmt((S.status.water_quota_m3 || 60000) - res.water_used_m3)} m³ of the water quota went unused; a plan with higher irrigation on the best fields may feed more people.`);
  const weak = (plan ? plan.fields : []).filter((f) => f.crop && harvest[f.field] && harvest[f.field].yield_t_ha < f.yield_t_ha_p10_p50_p90[0]);
  if (weak.length) next.push(`${weak.map((f) => f.field).join(", ")} harvested below the bad-year estimate; a trial plot of that crop on similar soil would show why.`);
  if (!next.length) next.push("Change one crop choice and run again on the same farm to see what it costs or gains.");
  const award = S.award, xp = award ? award.lines : m ? m.xp_items : [];
  return `<p class="verdict">${verdict}</p>
    <div class="res-kpis"><div><b>${fmt(res.people_fed)}</b><span>people fed (modelled person-years)</span></div>
    <div><b>${fmt(res.water_used_m3)}</b><span>m³ groundwater of ${fmt(S.status.water_quota_m3 || 60000)}${res.within_quota ? "" : " (over)"}</span></div>
    <div><b>${mt.water_m3_per_person ? fmt(mt.water_m3_per_person, 1) : "–"}</b><span>m³ per person fed</span></div>
    <div><b>${fmt(res.energy_used_kwh)}</b><span>kWh of ${fmt(S.status.energy_kwh || 90000)}${res.within_energy ? "" : " (over)"}</span></div></div>
    <div class="res-crops">${(mt.crops || []).map((c) => { const pic = portrait(c, 3, 60); return `<span>${pic ? `<img src="${pic}" alt="">` : ""}${esc(crop(c))}</span>`; }).join("")}</div>
    <p class="inv-h">Coverage by need</p>
    <div class="nutrients wide">${["kcal", "protein_g", "vitA_ug"].map((k) => `<div class="nut ${k === lim ? "lim" : ""}"><span>${cap(NUTRIENT[k])}${k === lim ? " · limiting" : ""}</span><i><b style="width:${Math.min(100, (100 * (by[k] || 0)) / ((by[lim] || 1) * 3))}%"></b></i><em>${fmt(by[k])}</em></div>`).join("")}</div>
    ${contrib[lim] ? `<p class="note">${cap(NUTRIENT[lim])} came from: ${contrib[lim].sort((a, b) => b[1] - a[1]).map(([f, v]) => `${f} ${fmt(v)}`).join(", ")}.</p>` : ""}
    <p class="inv-h">Planned and realised yield, t/ha</p>
    <table><thead><tr><th>Field</th><th>Crop</th><th class="n">Plan, bad year</th><th class="n">Plan, typical</th><th class="n">Harvested</th></tr></thead><tbody>${fieldsRows}</tbody></table>
    <p class="inv-h">What happened</p><ol class="story">${story.map((s) => `<li>${s}</li>`).join("")}</ol>
    <p class="inv-h">Worth trying next</p><ul class="story">${next.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
    ${m && m.achievements.length ? `<p class="inv-h">Achievements earned</p><div class="badges">${m.achievements.map((a) => `<div class="badge on"><span class="hex">✓</span><div><b>${esc(a.title)}</b><span>${esc(a.evidence)}</span></div></div>`).join("")}</div>` : ""}
    ${xp && xp.length ? `<p class="inv-h">${award ? `Experience earned and saved: +${fmt(award.gained)} XP` : "Preview experience (recorded season, not saved)"}</p><ul class="xp-lines">${xp.map((l) => `<li><span>${esc(l.label)}</span><b>+${fmt(l.xp)}</b></li>`).join("")}</ul>` : ""}
    <div class="rep-actions">${mode === "replay" ? '<button class="ghost sm" type="button" id="repIncident">Replay the incident</button><button class="ghost sm" type="button" id="repAgain">Watch again</button>' : '<button class="primary sm" type="button" id="repPlan">Plan another season</button>'}
      <button class="ghost sm" type="button" id="repJson">Export JSON</button><button class="ghost sm" type="button" id="repCsv">Export CSV</button></div>
    <p class="note">Exports contain the run's inputs, results, assumptions and provenance; no account details.</p>`;
}
function runExport() {
  const res = S.status && S.status.result;
  return { schema: "worldlab.run/2", exported_at: new Date().toISOString(), run: meta.run || info.run_id || null, source: mode === "replay" ? "recorded replay" : "live server",
    decision_source: deciderName(), perception: perceptionName(), controller: controllerName(), budget_mode: (S.status && S.status.budget_mode) || (res && res.budget_mode) || "soft (recorded before hard budgets)",
    calendar: "day 0 = 1 October; 273-day season", units: { water: "m3", energy: "kWh", yield: "t/ha fresh weight", people: "person-years covered for calories, protein and vitamin A (scarcest need)" },
    limits: { water_quota_m3: S.status.water_quota_m3, energy_kwh: S.status.energy_kwh },
    plan: S.plan, harvest: S.status.harvest, result: res, missions: S.mission && { outcome: S.mission.outcome, chapters: S.mission.chapters.map((c) => ({ id: c.id, status: c.status })), achievements: S.mission.achievements },
    hidden_changes: res ? S.perturbations.map(({ _order, ...p }) => p) : "revealed after the season", irrigation_policy: S.rl && { status: rlStatus(), held_out_comparison: S.rl.held_out_comparison, criterion: S.rl.deployment_criterion, samples: S.rl.samples } };
}
function wireReport() {
  const on = (id, f) => { const b = $(id); if (b) b.onclick = f; };
  on("repJson", () => download(`worldlab-${meta.run || "season"}.json`, JSON.stringify(runExport(), null, 2), "application/json"));
  on("repCsv", () => {
    const res = S.status.result, h = S.status.harvest || {};
    const rows = [["field", "crop", "plan_yield_t_ha_bad_year", "plan_yield_t_ha_typical", "harvested_yield_t_ha", "harvest_day", "kcal_person_years", "protein_person_years", "vitA_person_years"]];
    (S.plan ? S.plan.fields : []).forEach((f) => { const x = h[f.field] || {}; rows.push([f.field, f.crop || "fallow", f.crop ? f.yield_t_ha_p10_p50_p90[0] : "", f.crop ? f.yield_t_ha_p10_p50_p90[1] : "", x.yield_t_ha ?? "", x.day ?? "", (x.people || {}).kcal ?? "", (x.people || {}).protein_g ?? "", (x.people || {}).vitA_ug ?? ""]); });
    rows.push([], ["people_fed", res.people_fed], ["water_used_m3", res.water_used_m3], ["energy_used_kwh", res.energy_used_kwh], ["limiting", res.limiting]);
    download(`worldlab-${meta.run || "season"}.csv`, rows.map((r) => r.join(",")).join("\n"), "text/csv");
  });
  on("repPlan", () => { closeDrawer(); openPlanner(); });
  on("repAgain", () => { closeDrawer(); R.playing = false; seek(0); togglePlay(); });
  on("repIncident", () => { const a = R.msgs.findIndex((x) => x.kind === "ledger" && x.data.kind === "anomaly"); if (a >= 0) { closeDrawer(); R.playing = false; seek(Math.max(0, R.pt[a] - 4)); syncScrub(); togglePlay(); } });
  on("toEnd", () => { R.playing = false; seek(R.total); syncScrub(); renderDrawer(); });
}
function showReport() {
  const res = S.status && S.status.result;
  if (!res || reportShownFor === S.events.length) return;
  reportShownFor = S.events.length;
  if (scene) scene.event("season_result", {});
  openView("results", "report");
}
async function historyHtml() {
  if (mode !== "live" && !serverUp) return `<p class="empty">Your seasons are saved with an account on the WorldLab server, which isn't reachable from here.</p>`;
  if (mode !== "live") return `<p class="empty"><a href="${PAGES.login}">Log in</a> to see your saved seasons.</p>`;
  let d;
  try { d = (await apiJson("api/runs", { timeout: 10000 })).data; } catch (e) { return `<p class="empty">Couldn't load your seasons. Check your connection and try again.</p>`; }
  if (!d.runs || !d.runs.length) return `<p class="empty">No seasons yet. Plan one to start.</p>`;
  const when = (t) => new Date(t * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return `<table><thead><tr><th>Started</th><th>Scientist</th><th>Your crops</th><th>Status</th><th class="n">People fed</th><th class="n">Water m³</th><th class="n">XP</th><th></th></tr></thead><tbody>${d.runs.map((r) => {
    const mine = (r.choices || []).filter((c) => c.crop).map((c) => `${c.field} ${esc(c.choice)}`).join(", ") || "Scientist chose all";
    const status = r.result ? "Finished" : r.id === info.run_id ? "Running" : "Stopped";
    return `<tr><td>${when(r.created)}</td><td>${esc(agentName(r.agent))}</td><td>${mine}</td><td>${status}</td><td class="n">${r.result ? fmt(r.result.people_fed) : "–"}</td><td class="n">${r.result ? fmt(r.result.water_used_m3) : "–"}</td><td class="n">${r.award && r.award.gained != null ? `+${fmt(r.award.gained)}` : ""}</td><td>${r.result ? `<a href="${PAGES.app}?run=${r.id}">Replay</a>` : ""}</td></tr>`;
  }).join("")}</tbody></table><p class="note">Replays never award experience again. Each farm and crop choice earns season experience once; beating your best on it earns the difference.</p>`;
}
function badgesHtml() {
  const catalog = (progress && progress.catalog) || (S.mission && S.mission.catalog) || [];
  const mine = progress ? progress.achievements : {};
  const season = {}; (S.mission ? S.mission.achievements : []).forEach((a) => (season[a.id] = a));
  return `<p style="margin:0 0 10px">${progress ? `Level ${progress.level.level}, ${fmt(progress.level.xp)} XP saved${progress.best_people ? `; best season ${fmt(progress.best_people)} people fed` : ""}.` : "Preview: what the season on screen has earned. Nothing is saved without an account."} Each achievement is checked against the season's audit ledger; open one for its evidence.</p>
    <div class="badges">${catalog.map((c, k) => { const on = mine[c.id] || season[c.id]; const ev = (mine[c.id] && mine[c.id].evidence) || (season[c.id] && season[c.id].evidence);
      return `<details class="badge ${on ? "on" : ""}"><summary><span class="hex" aria-hidden="true">${on ? "✓" : k + 1}</span><div><b>${esc(c.title)}</b><span>${on ? (mine[c.id] ? "Earned and saved" : "Earned this season (preview)") : "Not earned yet"}</span></div></summary><p><b>How to earn it:</b> ${esc(c.about || "")}</p>${on ? `<p><b>Evidence:</b> ${esc(ev)}</p>` : ""}</details>`; }).join("")}</div>
    <p class="note">The farm goal (500 people) is a stretch target in the Harvest chapter; Harvest Guardian is a separate achievement at 450 people.</p>`;
}

// ------------------------------------------------------------ drone feed
function renderDrone() {
  const live = mode === "live";
  $("dfLiveTag").innerHTML = scene ? `<i class="live"></i>${live ? "Live simulated camera" : "3D camera at replay time"}` : "3D view unavailable";
  if (!$("droneTab").classList.contains("on")) return;
  const frames = S.drone, key = `${frames.length}|${dfSel}|${curDay()}`;
  if (key === dfKey) return; dfKey = key;
  const k = dfSel >= 0 && dfSel < frames.length ? dfSel : frames.length - 1, f = frames[k];
  $("dfEmpty").hidden = !!f; $("dfImg").hidden = !f;
  if (f) {
    const age = curDay() != null ? curDay() - f.day : 0;
    $("dfImg").src = f.image; $("dfImg").alt = `Drone frame of ${f.field}, ${dayLabel(f.day)}`;
    $("dfTag").textContent = `${f.kind === "inspection" ? "Inspection" : "Survey"} · ${f.field} · ${dayLabel(f.day)}`;
    $("dfMeta").textContent = `canopy ${fmt(f.canopy_cover_measured, 2)} vs ${fmt(f.canopy_cover_predicted, 2)} model${age > 0 ? ` · ${age} d old` : ""}`;
    const diag = f.diagnosis && f.diagnosis.condition ? ` Image analysis by ${f.source || "perception"}: ${String(f.diagnosis.condition).replace(/_/g, " ")}.` : "";
    $("dfCap").textContent = (f.kind === "inspection"
      ? `Inspection the scientist asked for: ${crop(f.crop)} in ${f.field}, captured ${dayLabel(f.day)}.${diag}`
      : `Routine survey frame: ${crop(f.crop)} in ${f.field}, captured ${dayLabel(f.day)}. Rendered by the farm simulator from its true state; the canopy figure is the drone's noisy measurement.`)
      + (age > 8 ? " Historical: it may not show the field now." : "") + ` Frame ${k + 1} of ${frames.length} kept${frames.length >= 60 ? " (the oldest are dropped)" : ""}.`;
  }
  $("dfStrip").innerHTML = frames.map((x, idx) => `<li><button type="button" data-k="${idx}" class="${idx === k ? "on" : ""}" aria-label="${x.field}, ${dayLabel(x.day)}" aria-pressed="${idx === k}"><img src="${x.image}" alt=""><span>${x.field} ${dayLabel(x.day)}</span></button></li>`).join("");
  $("dfStrip").querySelectorAll("button").forEach((b) => (b.onclick = () => { dfSel = Number(b.dataset.k); renderDrone(); }));
  const on = $("dfStrip").querySelector(".on"); if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// ------------------------------------------------------------ toasts and achievements
function toast(title, body, ms = 5200) {
  const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status");
  t.innerHTML = `<span class="hex" aria-hidden="true"></span><div><b>${esc(title)}</b><span>${esc(body)}</span></div>`;
  $("toasts").appendChild(t); setTimeout(() => t.remove(), ms);
}
function badgeToasts(m) {
  (m.achievements || []).forEach((a) => { if (!seenBadges.has(a.id)) { seenBadges.add(a.id); toast(`Achievement: ${a.title}`, a.evidence); } });
}

// ------------------------------------------------------------ season planner
const SEASON_COLORS = { autumn: "var(--s-autumn)", winter: "var(--s-winter)", late_winter: "var(--s-late_winter)" };
const DRAFT_KEY = "wl-plan-draft";
const P = { data: null, season: "autumn", brush: null, picks: FIELD_IDS.map(() => ({ mode: "scientist" })), undo: [] };
const canRun = () => mode === "live";
async function openPlanner() {
  if (!P.data) {
    try { P.data = await (await fetch(new URL(PAGES.home + "seasons.json", location.href))).json(); } catch (e) { toast("Planner unavailable", "Couldn't load the crop guide. Check your connection and try again."); return; }
  }
  const draft = store.get(DRAFT_KEY, null);
  if (draft && Array.isArray(draft.picks) && draft.picks.length === 6) { P.picks = draft.picks; P.season = draft.season || P.season; }
  if (drawer) closeDrawer();
  $("inspector").hidden = true;
  if (mode === "replay" && R.playing) togglePlay();
  lastFocus = document.activeElement;
  document.body.classList.add("planning");
  $("planner").hidden = false; $("plErr").hidden = true;
  ["missionPanel", "impactPanel", "dock", "viewbar"].forEach((id) => ($(id).style.visibility = "hidden"));
  // say what this planner can do before any choices are made
  const pb = $("previewBanner");
  if (canRun()) pb.hidden = true;
  else {
    pb.hidden = false;
    pb.textContent = serverUp
      ? "Preview: this is a recorded season, so the plan can't run here. Your draft is saved in this browser; sign up and it will be waiting in your planner."
      : "Preview only: the hosted WorldLab server isn't reachable, so this plan can't run here. Your draft is saved in this browser.";
  }
  const sel_ = $("agentSel");
  sel_.disabled = !canRun();
  [...sel_.options].forEach((o) => { if (o.value === "spark") o.disabled = !(caps && caps.agents && caps.agents.spark); if (o.value === "glimmer") o.disabled = !(caps && caps.agents && caps.agents.glimmer); });
  sel_.title = canRun() ? "" : "Choosing a scientist needs the hosted server";
  $("startBtn").textContent = canRun() ? "Start the season" : serverUp ? "Sign up to run this plan" : "Save draft";
  renderSeasonTabs(); renderCards(); renderFieldRows(); preview();
  if (scene) scene.view("overview");
  $("planner").focus({ preventScroll: true });
}
function closePlanner() {
  $("planner").hidden = true; document.body.classList.remove("planning");
  ["missionPanel", "impactPanel", "dock", "viewbar"].forEach((id) => ($(id).style.visibility = ""));
  if (scene) { scene.setFields(fieldsNow()); const ld = lastDay(); if (ld) scene.update(ld); scene.home(); }
  if (lastFocus && lastFocus.isConnected) lastFocus.focus({ preventScroll: true });
}
const seasonLabel = (id) => { const x = P.data && P.data.seasons.find((s) => s.id === id); return x ? x.label : id; };
function saveDraft() { store.set(DRAFT_KEY, { picks: P.picks, season: P.season, saved: Date.now() }); }
function setPick(i, v) { P.undo.push(JSON.stringify(P.picks)); if (P.undo.length > 50) P.undo.shift(); P.picks[i] = v; saveDraft(); renderFieldRows(); preview(); }
function renderSeasonTabs() {
  $("seasonTabs").innerHTML = P.data.seasons.map((x) => {
    const n = P.picks.filter((p) => p.mode === "crop" && p.season === x.id).length;
    return `<button role="tab" type="button" data-s="${x.id}" class="${x.id === P.season ? "on" : ""}" aria-selected="${x.id === P.season}" style="--c:${SEASON_COLORS[x.id]}"><span class="dot"></span>${esc(x.label)}${n ? ` <span class="cnt">${n}</span>` : ""}</button>`;
  }).join("") + `<button class="rest" type="button" disabled title="${esc(P.data.summer.about)}">Summer: fields rest</button>`;
  $("seasonTabs").querySelectorAll("button[data-s]").forEach((b) => (b.onclick = () => { P.season = b.dataset.s; P.brush = null; saveDraft(); renderSeasonTabs(); renderCards(); renderFieldRows(); }));
  $("seasonAbout").textContent = P.data.seasons.find((s) => s.id === P.season).about;
}
function guideFor(season) { const g = P.data.guides && P.data.guides[season]; return g ? g.crops : []; }
function guideCrop(c, season) { return guideFor(season).find((x) => x.crop === c); }
// Why a crop does poorly on a field, from the model preview: heat at flowering, root-zone salinity, or both.
function suitability(c, season, i) {
  const g = guideCrop(c, season); if (!g) return null;
  const f = g.fields[i], best = Math.max(...g.fields.map((x) => x.yield_t_ha_p50));
  const poor = f.yield_t_ha_p50 < 0.3 || f.yield_t_ha_p50 < 0.35 * best;
  const reasons = [];
  if (f.heat_factor != null && f.heat_factor < 0.75) reasons.push(`heat at flowering cuts the harvest to about ${Math.round(f.heat_factor * 100)}% (the crop's limit is ${g.heat_limit_c} °C)`);
  if (f.ece_root_zone_end != null && f.ece_root_zone_end > g.salt_threshold_ds_m) reasons.push(`root-zone salinity reaches about ${fmt(f.ece_root_zone_end, 1)} dS/m, above its ${g.salt_threshold_ds_m} dS/m salinity threshold (this field starts at ${ECE0[i]} dS/m and the groundwater is ${(P.data.assumptions || {}).irrigation_water_ec_ds_m || 4.5} dS/m)`);
  const alts = guideFor(season).filter((x) => x.crop !== c).map((x) => [x, x.fields[i].yield_t_ha_p50]).sort((a, b) => b[1] - a[1]).slice(0, 2).map(([x]) => x.label);
  return { poor, f, reasons, alts };
}
function renderCards() {
  const crops = guideFor(P.season);
  $("plHint").textContent = P.brush ? `Click fields in the 3D view or the list to sow ${crop(P.brush)}. Click the card again when you're done.` : "Each card: sowing window, days to harvest, needs covered, salinity threshold, and expected fresh yield on each field (t/ha; bars scaled to that crop's best field).";
  $("cropCards").innerHTML = crops.map((c) => {
    const cmax = Math.max(...c.fields.map((f) => f.yield_t_ha_p50), 0.1);
    const needs = c.good_for.map((n) => `<span class="need ${n === "protein" ? "p" : n === "vitamin A" ? "v" : ""}">${esc(n)}</span>`).join("");
    const pic = portrait(c.crop, 2, 88);
    const poorAll = c.fields.every((f) => f.yield_t_ha_p50 < 0.3);
    return `<button type="button" class="crop-card ${P.brush === c.crop ? "on" : ""} ${poorAll ? "poor" : ""}" data-c="${c.crop}" aria-pressed="${P.brush === c.crop}">
      <span class="cc-head">${pic ? `<img class="crop-pic" src="${pic}" alt="">` : ""}<h4>${esc(c.label)}<span>${c.cycle_days ? `${c.cycle_days} days` : ""}</span></h4></span>
      <span class="meta">Sow ${esc(c.sow_window_label)}${c.harvest_label ? `; harvest around ${esc(c.harvest_label)}` : ""}</span>
      <span class="needs">${needs}<span class="need salt" title="Above this root-zone salinity the model starts to cut yield; it is not a survival cut-off">salinity threshold ${c.salt_threshold_ds_m} dS/m</span></span>
      <span class="yields" aria-label="Expected yield per field, t/ha">${c.fields.map((f) => `<span title="${f.field}: ${yfmt(f.yield_t_ha_p50)} t/ha (${yfmt(f.yield_t_ha_p10)}–${yfmt(f.yield_t_ha_p90)} in 8 of 10 years)"><i><b style="height:${Math.round((100 * f.yield_t_ha_p50) / cmax)}%"></b></i>${f.field}<br>${yfmt(f.yield_t_ha_p50)}</span>`).join("")}</span>
      ${poorAll ? `<span class="warn-line">⚠ Negligible yield on every field in this season with the preview's management</span>` : ""}
    </button>`;
  }).join("") || `<p class="note">No crop on the list is sown in this season.</p>`;
  $("cropCards").querySelectorAll(".crop-card").forEach((b) => (b.onclick = () => { P.brush = P.brush === b.dataset.c ? null : b.dataset.c; renderCards(); renderFieldRows(); }));
}
function renderFieldRows() {
  const inSeason = guideFor(P.season).map((c) => c.crop);
  const fields = (P.data.fields || []);
  $("fieldRows").innerHTML = FIELD_IDS.map((id, i) => {
    const p = P.picks[i], fd = fields[i] || {};
    const tag = p.mode === "crop" ? `<span class="sz" style="--c:${SEASON_COLORS[p.season]}">${esc(seasonLabel(p.season))}</span>` : "";
    let ctl;
    if (P.brush) {
      const here = p.mode === "crop" && p.crop === P.brush && p.season === P.season;
      ctl = `<button type="button" class="${here ? "ghost" : "primary"} sm sow" data-i="${i}">${here ? `Remove ${esc(crop(P.brush))}` : `Sow ${esc(crop(P.brush))} here`}</button>`;
    } else {
      const opts = [`<option value="scientist" ${p.mode === "scientist" ? "selected" : ""}>Scientist decides</option>`, `<option value="fallow" ${p.mode === "fallow" ? "selected" : ""}>Leave fallow</option>`];
      if (p.mode === "crop" && (p.season !== P.season || !inSeason.includes(p.crop))) opts.push(`<option value="keep" selected>${esc(crop(p.crop))}, ${esc(seasonLabel(p.season).toLowerCase())}</option>`);
      inSeason.forEach((c) => { const y = guideCrop(c, P.season).fields[i].yield_t_ha_p50; opts.push(`<option value="c:${c}" ${p.mode === "crop" && p.crop === c && p.season === P.season ? "selected" : ""}>${esc(crop(c))}, ${esc(seasonLabel(P.season).toLowerCase())} (${yfmt(y)} t/ha)</option>`); });
      ctl = `<select aria-label="Crop for ${id}" data-i="${i}">${opts.join("")}</select>`;
    }
    let warn = "";
    if (p.mode === "crop") {
      const s = suitability(p.crop, p.season, i);
      if (s && s.poor) warn = `<p class="pl-warn" role="note">⚠ ${esc(crop(p.crop))} is expected to yield only ${yfmt(s.f.yield_t_ha_p50)} t/ha here${s.reasons.length ? `: ${esc(s.reasons.join("; "))}` : ""}.${s.alts.length ? ` Better fits in this season: ${esc(s.alts.join(", "))}.` : ""} You can keep it as an experiment.</p>`;
    }
    const pic = p.mode === "crop" ? portrait(p.crop, 2, 56) : null;
    return `<li class="pl-row ${P.brush ? "hot" : ""}"><span class="fid">${id}</span><span class="soil">${NAMES[i]}: ${esc(fd.soil || SOILS[i])}, ${fd.area_ha || 2} ha, starts at ${fd.ece_top ?? ECE0[i]} dS/m</span><span class="pick">${pic ? `<img class="pick-pic" src="${pic}" alt="">` : ""}${ctl}${tag}</span>${warn}</li>`;
  }).join("");
  $("fieldRows").querySelectorAll("select").forEach((s) => (s.onchange = () => {
    const i = Number(s.dataset.i), v = s.value;
    if (v === "scientist" || v === "fallow") setPick(i, { mode: v });
    else if (v.startsWith("c:")) setPick(i, { mode: "crop", crop: v.slice(2), season: P.season });
  }));
  $("fieldRows").querySelectorAll("button.sow").forEach((b) => (b.onclick = () => brushField(Number(b.dataset.i))));
  $("plUndo").disabled = !P.undo.length;
  renderSummary();
  renderSeasonTabsCounts();
}
function renderSeasonTabsCounts() {
  $("seasonTabs").querySelectorAll("button[data-s]").forEach((b) => {
    const n = P.picks.filter((p) => p.mode === "crop" && p.season === b.dataset.s).length;
    let c = b.querySelector(".cnt"); if (!n) { if (c) c.remove(); return; }
    if (!c) { c = document.createElement("span"); c.className = "cnt"; b.appendChild(c); } c.textContent = n;
  });
}
function renderSummary() {
  const mine = P.picks.filter((p) => p.mode === "crop"), fallow = P.picks.filter((p) => p.mode === "fallow").length, sci = P.picks.filter((p) => p.mode === "scientist").length;
  const crops = [...new Set(mine.map((p) => p.crop))];
  const needs = new Set(); mine.forEach((p) => { const g = guideCrop(p.crop, p.season); (g ? g.good_for : []).forEach((n) => needs.add(n)); });
  const poor = P.picks.map((p, i) => (p.mode === "crop" ? suitability(p.crop, p.season, i) : null)).filter((s) => s && s.poor).length;
  const missing = ["calories", "protein", "vitamin A"].filter((n) => !needs.has(n));
  $("plSummary").innerHTML = `<b>Your farm so far</b><ul>
    <li>${mine.length} field${mine.length === 1 ? "" : "s"} chosen by you, ${sci} left to the scientist, ${fallow} fallow</li>
    <li>${crops.length ? `Crops: ${crops.map(crop).join(", ")}` : "No crops chosen yet"}</li>
    ${mine.length ? `<li>${missing.length ? `Your picks don't cover ${missing.join(" or ")}${sci ? "; the scientist will try to cover it on its fields" : ": nobody counts as fed without all three"}` : "Your picks cover calories, protein and vitamin A"}</li>` : ""}
    ${poor ? `<li class="warn">${poor} choice${poor === 1 ? " has" : "s have"} negligible expected yield</li>` : ""}
    <li class="note">Water, energy and management are planned by the scientist within the quota when the season starts.</li></ul>`;
}
function brushField(i) {
  if (!P.brush) return;
  const p = P.picks[i];
  setPick(i, p.mode === "crop" && p.crop === P.brush && p.season === P.season ? { mode: "scientist" } : { mode: "crop", crop: P.brush, season: P.season });
}
function preview() { if (scene) scene.previewPlan(P.picks.map((p) => (p.mode === "crop" ? { crop: p.crop, label: crop(p.crop) } : { fallow: p.mode === "fallow" }))); }
async function startSeason() {
  saveDraft();
  if (!canRun()) {
    if (serverUp) { go("signup", `?next=${encodeURIComponent(PAGES.app)}`); return; }
    toast("Draft saved", "Your crop choices are kept in this browser. Run WorldLab locally to grow them.");
    return;
  }
  if (caps && caps.busy) { $("plErr").textContent = "The server is running as many seasons as it can right now. Your draft is saved; try again in a few minutes."; $("plErr").hidden = false; return; }
  const btn = $("startBtn"); btn.disabled = true; $("plErr").hidden = true; btn.textContent = "Starting…";
  try {
    const r = await apiJson("api/start", { method: "POST", body: { agent: $("agentSel").value, speed: Number($("speed").value), choices: P.picks }, timeout: 20000 });
    if (r.status === 401) { go("login", `?next=${encodeURIComponent(PAGES.app)}`); return; }
    if (!r.ok || !r.data.ok) throw new Error(r.data.error || "The season could not start.");
    store.del(DRAFT_KEY); P.undo = [];
    closePlanner(); $("modeNote").textContent = ""; seenBadges = new Set();
  } catch (e) { $("plErr").textContent = e.name === "TimeoutError" ? "The server didn't answer in time. Your draft is saved; try again." : e.message; $("plErr").hidden = false; }
  finally { btn.disabled = false; btn.textContent = "Start the season"; }
}

// ------------------------------------------------------------ live mode
async function post(path, body) { return (await apiJson(path, { method: "POST", body: body || {}, timeout: 15000 })).data; }
async function loadProgress() { try { const r = await apiJson("api/progress", { timeout: 8000 }); if (r.ok) { progress = r.data; dirty = true; } } catch (e) { /* offline */ } }
function hydrate(state) {
  S = { ...fresh(), ...state, events: state.events || [], agentKind: info.agent };
  S.lastSeq = S.events.length ? Math.max(...S.events.map((e) => e.seq ?? -1)) : -1;
  delete S.info; delete S.agent; delete S.beliefs_hist;
}
async function startLive(state) {
  mode = "live";
  info = state.info || {};
  $("liveControls").hidden = false;
  $("profileName").textContent = info.user ? `${info.user.name} (${info.user.email})` : "Signed in";
  $("loginLink").hidden = true;
  if (info.agent && [...$("agentSel").options].some((o) => o.value === info.agent && !o.disabled)) $("agentSel").value = info.agent;
  $("speed").value = info.speed || 12;
  hydrate(state);
  (S.mission ? S.mission.achievements : []).forEach((a) => seenBadges.add(a.id));
  sceneSync(); dirty = true;
  setRunning(info.running);
  loadProgress();
  $("planBtn").onclick = openPlanner;
  $("stopBtn").onclick = () => post("api/stop");
  $("speed").oninput = () => post("api/speed", { speed: Number($("speed").value) });
  document.querySelectorAll("#perturb button").forEach((b) => (b.onclick = async () => {
    const r = await post("api/perturb", { kind: b.dataset.kind, field: FIELD_IDS[sel] });
    if (!r.ok) toast("The farm didn't change", r.error || "Try again once the season is running.");
    else toast("Hidden change made", `${r.note}. The scientist is not told.`);
  }));
  stream("api/stream", (batch) => batch.forEach((m) => {
    apply(m, true);
    if (m.kind === "reset") { setRunning(true); info.running = true; }
    if (m.kind === "status" && (m.data.done || m.data.phase === "harvested")) { setRunning(false); info.running = false; }
  }), async () => {
    const r = await apiJson("api/state", { timeout: 10000 });
    if (r.ok) { info = r.data.info || info; hydrate(r.data); sceneSync(); dirty = true; }
  }, (s) => { streamState = s; dirty = true; });
  if (!info.running && !(S.status && S.status.phase)) { $("modeNote").textContent = "Your farm is ready. Plan a season to start."; if (!store.get("wl-toured", false)) startTour(); else openPlanner(); }
}
function setRunning(on) { $("planBtn").textContent = on ? "Plan a different season" : "Plan a new season"; $("stopBtn").hidden = !on; dirty = true; }

// ------------------------------------------------------------ replay mode: the scrubber is the season calendar
const R = { msgs: [], pt: [], idx: 0, pos: 0, total: 0, playing: false, rate: 1, dayPos: [], preEnd: 0, events: [] };
function beat(m) {
  if (m.kind === "day") return 0.13;
  if (m.kind === "rl_train") return 0.05;
  if (m.kind === "trials") return 0.32;
  if (m.kind === "perturbation") return 0.8;
  if (m.kind === "ledger") return streamItem(m.data) ? (m.data.kind === "anomaly" ? 2.2 : m.data.kind === "season_result" ? 2 : 0.55) : 0;
  return 0;
}
const STORY = new Set(["trial_result", "plan", "rl_policy", "season_start", "anomaly", "field_test", "adjust", "model_update", "rebalance", "harvest", "season_result", "curtailment"]);
function buildTimeline(msgs) {
  let t = 0; R.pt = msgs.map((m) => (t += beat(m))); R.total = t + 0.5;
  R.dayPos = []; msgs.forEach((m, i) => { if (m.kind === "day" && R.dayPos[m.data.day] == null) R.dayPos[m.data.day] = R.pt[i]; });
  R.preEnd = R.dayPos[0] ?? R.total;
  R.events = msgs.map((m, i) => (m.kind === "ledger" && STORY.has(m.data.kind) ? R.pt[i] : null)).filter((x) => x != null);
}
function seek(pos) {
  pos = Math.max(0, Math.min(R.total, pos));
  if (pos < R.pos || pos - R.pos > 3) {
    // backwards (or a big jump): rebuild state from the start so nothing from the future leaks in
    if (pos < R.pos) { S = fresh(); S.agentKind = meta.agent || null; R.idx = 0; seenBadges = new Set(); invClosedFor = null; dfSel = -1; reportShownFor = null; }
    while (R.idx < R.msgs.length && R.pt[R.idx] <= pos) apply(R.msgs[R.idx++], false);
    R.pos = pos; sceneSync();
    (S.mission ? S.mission.achievements : []).forEach((a) => seenBadges.add(a.id));
    inspKey = ""; dfKey = ""; $("invBody").dataset.k = "";
  } else {
    while (R.idx < R.msgs.length && R.pt[R.idx] <= pos) apply(R.msgs[R.idx++], true);
    R.pos = pos;
  }
  dirty = true;
}
function scrubToPos(v) {
  if (v <= 100) return (v / 100) * R.preEnd;
  const day = Math.min(D - 1, Math.round(((v - 100) / 900) * (D - 1)));
  return v >= 1000 ? R.total : (R.dayPos[day] ?? R.total);
}
function posToScrub(pos) {
  if (pos < R.preEnd) return Math.round((100 * pos) / Math.max(R.preEnd, 1e-6));
  if (pos >= R.total - 0.01) return 1000;
  const d = curDay(); return d == null ? 100 : Math.round(100 + (900 * d) / (D - 1));
}
function syncScrub() { $("dateScrub").value = String(posToScrub(R.pos)); }
function seekToDay(d) { const p = R.dayPos[Math.max(0, Math.min(D - 1, d))]; if (p != null) { seek(p); syncScrub(); } }
function stepEvent(dir) {
  if (dir > 0) { const n = R.events.find((p) => p > R.pos + 0.01); seek(n ?? R.total); }
  else { const prev = R.events.filter((p) => p < R.pos - 0.6); seek(prev.length ? prev[prev.length - 1] : 0); }
  syncScrub();
}
async function startReplay(url) {
  mode = "replay";
  const res = url.startsWith("api/") ? await api(url, { timeout: 20000 }) : await fetch(url);
  if (!res.ok) throw new Error(`${res.status}`);
  const data = await res.json();
  R.msgs = data.messages || data;
  meta = data.meta || {};
  buildTimeline(R.msgs);
  S.agentKind = meta.agent || null;
  $("replayControls").hidden = false; $("demoControls").hidden = false;
  $("modeNote").textContent = meta.note ? `${meta.note} Decisions, predictions and measurements replay exactly as logged.` : "Recorded season. Decisions, predictions and measurements replay exactly as logged.";
  $("playBtn").onclick = togglePlay;
  $("rate").onchange = () => (R.rate = Number($("rate").value));
  $("dateScrub").oninput = () => { seek(scrubToPos(Number($("dateScrub").value))); };
  $("prevEvt").onclick = () => stepEvent(-1);
  $("nextEvt").onclick = () => stepEvent(1);
  $("jumpIncident").onclick = () => { const a = R.msgs.findIndex((x) => x.kind === "ledger" && x.data.kind === "anomaly"); if (a >= 0) { seek(R.pt[a] + 0.01); syncScrub(); if (drawer) closeDrawer(); } };
  $("jumpIncident").hidden = !R.msgs.some((x) => x.kind === "ledger" && x.data.kind === "anomaly");
  $("jumpHarvest").onclick = () => { R.playing = false; seek(R.total); syncScrub(); $("playBtn").textContent = "Watch again"; };
  let last = performance.now();
  const tick = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (R.playing) {
      seek(Math.min(R.total, R.pos + dt * R.rate));
      syncScrub();
      if (R.pos >= R.total) { R.playing = false; $("playBtn").textContent = "Watch again"; dirty = true; if (S.status && S.status.result) showReport(); }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  // deep links (from the landing page): show the state the view is about
  const h = location.hash.replace(/^#/, "").split("/")[0];
  if (["results", "plan", "research", "agent"].includes(h)) { seek(R.total); syncScrub(); }
  else if (h === "incidents") { const a = R.msgs.map((x, i) => (x.kind === "ledger" && x.data.kind === "rebalance" ? i : -1)).filter((i) => i >= 0)[0]; seek(a != null ? R.pt[a] + 0.01 : R.total); syncScrub(); }
  if (h) { applyHash(); return; }
  if (!store.get("wl-toured", false) && !reducedMotion) startTour();
}
function togglePlay() {
  if (mode !== "replay") return;
  R.playing = !R.playing;
  if (R.playing && R.pos >= R.total) seek(0);
  $("playBtn").textContent = R.playing ? "Pause" : "Play"; dirty = true;
}

// ------------------------------------------------------------ guided tour (short, with Back, adapted to 2D and phones)
function tourSteps() {
  const narrow = innerWidth < 1020;
  const s = [
    ["#stage", scene ? "This farm is real geometry" : "The six fields", scene ? "Six fields near Al Ain, drip-irrigated from brackish groundwater. Drag to orbit, scroll to zoom; everything grows and changes with the simulation." : "This browser can't show the 3D farm, so the fields appear as a 2D map. Everything else works the same.", "center"],
    ["#transport", "Play the season", "Play, pause, jump between events or drag the date. The header always says whether this is a recording or a live run, and who is deciding."],
    ["#gauges", "Inspect a field", "Each ring is a field. Select one to open its sensor charts: the model's 90% band against what the sensors measured."],
    ["#missionPanel", "Missions", "Objectives tick off only when the season's audit ledger shows they happened. Optional choices and stretch goals are marked."],
    [narrow ? "#bottomNav" : ".tabs", "Everything else", "Plan, Research, Incidents, Agent and Results each open here, and the address bar remembers where you are."],
  ];
  return s;
}
let tourStep = -1;
function startTour() { tourStep = 0; $("tour").hidden = false; showTour(); }
function endTour() { $("tour").hidden = true; tourStep = -1; store.set("wl-toured", true); if (mode === "live" && !info.running && !(S.status && S.status.phase)) openPlanner(); else $("playBtn").focus(); }
function showTour() {
  const steps = tourSteps();
  const [selq, title, body, where] = steps[tourStep];
  const el = document.querySelector(selq);
  const r = el && where !== "center" && el.offsetParent ? el.getBoundingClientRect() : { left: innerWidth / 2 - 160, top: innerHeight / 2 - 110, width: 320, height: 180 };
  const hole = $("tourHole");
  Object.assign(hole.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
  const card = $("tourCard");
  card.innerHTML = `<h3 id="tourTitle">${esc(title)}</h3><p>${esc(body)}</p><div class="tc-foot"><span>${tourStep + 1} of ${steps.length}</span><span><button class="ghost sm" type="button" id="tourSkip">Skip</button>${tourStep ? ' <button class="ghost sm" type="button" id="tourBack">Back</button>' : ""} <button class="primary sm" type="button" id="tourNext">${tourStep === steps.length - 1 ? "Done" : "Next"}</button></span></div>`;
  const cw = Math.min(320, innerWidth - 20), ch = card.offsetHeight || 170;
  let x = r.left + r.width + 16, y = r.top;
  if (x + cw > innerWidth - 10) x = r.left - cw - 16;
  if (x < 10) { x = Math.max(10, Math.min(innerWidth - cw - 10, r.left)); y = r.top + r.height + 16; }
  if (y + ch > innerHeight - 10) y = Math.max(10, r.top - ch - 16);
  Object.assign(card.style, { left: `${x}px`, top: `${y}px`, width: `${cw}px` });
  $("tourNext").onclick = () => { tourStep++; if (tourStep >= steps.length) endTour(); else showTour(); };
  if ($("tourBack")) $("tourBack").onclick = () => { tourStep--; showTour(); };
  $("tourSkip").onclick = endTour;
  $("tourNext").focus();
}

// ------------------------------------------------------------ boot
async function loadScene() {
  try {
    if (!window.WebGLRenderingContext) throw new Error("WebGL is not available");
    const mod = await import("./scene.js");
    OV = mod.OVERLAYS || {};
    if (mod.cropPortrait) { portrait = mod.cropPortrait; stageOf = mod.stageOf; }
    scene = mod.createScene($("stage"), {
      onSelect: (i) => { if ($("planner").hidden) select(i, true); else if (P.brush) brushField(i); else select(i, false); },
      reducedMotion, quality: store.get("wl-quality", "auto"), time: store.get("wl-time", "golden"),
      onFps: (f, q) => { $("fpsTxt").textContent = `${Math.round(f)} frames per second at ${q} quality${scene && scene.isAuto() ? " (auto)" : ""}`; },
      onQuality: (q, auto) => { $("qualitySel").value = auto ? "auto" : q; },
    });
    window.__wlScene = scene;
    if (scene.droneView) scene.droneView($("droneLive"));
    if (scene.setFollow) scene.setFollow(store.get("wl-follow", true));
    $("noGL").hidden = true; $("map2d").hidden = true; document.body.classList.remove("no3d");
  } catch (e) {
    console.warn("3D view unavailable:", e);
    scene = null;
    document.body.classList.add("no3d");
    $("noGL").hidden = false; $("map2d").hidden = false;
    $("noGLWhy").textContent = /WebGL/i.test(String(e && e.message)) ? "This browser has no WebGL, so the farm is shown as a 2D map." : "The 3D view couldn't load (it needs WebGL and cdn.jsdelivr.net), so the farm is shown as a 2D map.";
    $("fpsTxt").textContent = "3D unavailable: showing the 2D field map.";
    ["qualitySel", "timeSel", "labelsChk", "followChk"].forEach((id) => ($(id).disabled = true));
    document.querySelectorAll("[data-cam]").forEach((b) => { b.disabled = true; b.title = "Camera controls need the 3D view"; });
    ["fiFocus", "fiClose2", "fiDrone"].forEach((id) => ($(id).disabled = true));
    if (!$("droneLive").nextElementSibling || !$("droneLive").nextElementSibling.classList.contains("df-empty")) $("droneLive").insertAdjacentHTML("afterend", `<p class="df-empty">The drone camera needs the 3D view. The captured frames on the right still work.</p>`);
    OV = Object.fromEntries(Object.entries(RAMP2D).map(([k, [lo, hi, ramp]]) => [k, { label: { health: "Canopy vs model", moisture: "Soil moisture, top 50 cm", salinity: "Soil salinity, top 50 cm", water: "Irrigation applied today" }[k], unit: { health: "%", moisture: "m³/m³", salinity: "dS/m", water: "mm" }[k], lo, hi, ramp }]));
    dirty = true;
  }
}
function setDockTab(b) {
  document.querySelectorAll(".dock-tabs [data-dt]").forEach((x) => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-selected", String(on)); x.tabIndex = on ? 0 : -1; });
  document.querySelectorAll(".dt-pane").forEach((p) => (p.hidden = p.dataset.pane !== b.dataset.dt));
  $("dock").classList.remove("collapsed");
  if (b.dataset.dt === "drone") { $("droneDot").hidden = true; dfKey = ""; renderDrone(); }
}
function wireUi() {
  document.querySelectorAll(".home-link").forEach((a) => (a.href = PAGES.home));
  $("demoCta").href = PAGES.signup;
  $("loginLink").href = PAGES.login;
  document.querySelectorAll("[data-collapse]").forEach((b) => (b.onclick = () => { const p = $(b.dataset.collapse); p.classList.toggle("collapsed"); b.textContent = p.classList.contains("collapsed") ? "+" : "–"; b.setAttribute("aria-expanded", String(!p.classList.contains("collapsed"))); store.set(`wl-collapsed-${b.dataset.collapse}`, p.classList.contains("collapsed")); }));
  ["missionPanel", "impactPanel", "dock"].forEach((id) => { const c = store.get(`wl-collapsed-${id}`, innerWidth < 760 && id !== "dock"); if (c) { $(id).classList.add("collapsed"); const b = document.querySelector(`[data-collapse="${id}"]`); if (b) { b.textContent = "+"; b.setAttribute("aria-expanded", "false"); } } });
  const dts = [...document.querySelectorAll(".dock-tabs [data-dt]")];
  dts.forEach((b, k) => { b.onclick = () => setDockTab(b); b.onkeydown = (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); const n = dts[(k + (e.key === "ArrowRight" ? 1 : dts.length - 1)) % dts.length]; setDockTab(n); n.focus(); } }; });
  document.querySelectorAll("#metricTabs button").forEach((b) => (b.onclick = () => { metric = b.dataset.m; document.querySelectorAll("#metricTabs button").forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); }); dirty = true; }));
  document.querySelectorAll("[data-cam]").forEach((b) => (b.onclick = () => scene && (b.dataset.cam === "home" ? scene.home() : scene.view(b.dataset.cam))));
  document.querySelectorAll("[data-ov]").forEach((b) => (b.onclick = () => setOverlay(b.dataset.ov)));
  $("ovSel").onchange = () => setOverlay($("ovSel").value);
  document.querySelectorAll("[data-view]").forEach((b) => (b.onclick = () => (drawer === b.dataset.view ? closeDrawer() : openView(b.dataset.view))));
  window.addEventListener("hashchange", applyHash);
  window.addEventListener("popstate", applyHash);
  $("fiClose").onclick = () => { $("inspector").hidden = true; sel = -1; if (scene) scene.setSelected(-1); dirty = true; };
  $("fiFocus").onclick = () => scene && scene.focus(sel, "field");
  $("fiClose2").onclick = () => scene && scene.focus(sel, "closeup");
  $("fiDrone").onclick = () => { if (scene) { scene.scan(sel); scene.view("drone"); } };
  $("fiCsv").onclick = exportFieldCsv;
  $("invClose").onclick = () => { const inc = currentIncident(); invClosedFor = inc ? inc.a.seq : null; dirty = true; };
  $("incidentFocus").onclick = () => { const inc = currentIncident(); if (!inc) return; if (scene) scene.focus(inc.a.data.field_index, "incident"); select(inc.a.data.field_index); invClosedFor = null; dirty = true; };
  $("drawerClose").onclick = () => closeDrawer();
  $("reasoningBtn").onclick = () => openView("agent", "record");
  $("reportBtn").onclick = () => openView("results", "report");
  $("xpPill").onclick = () => openView("badges");
  $("badgesBtn").onclick = () => { pop(null); openView("badges"); };
  $("historyBtn").onclick = () => { pop(null); openView("results", "seasons"); };
  $("logoutBtn").onclick = async () => { await post("api/auth/logout").catch(() => {}); setToken(null); go("home"); };
  $("settingsBtn").onclick = () => pop("settings");
  $("profileBtn").onclick = () => pop("profile");
  $("qualitySel").value = store.get("wl-quality", "auto");
  $("qualitySel").onchange = () => { store.set("wl-quality", $("qualitySel").value); if (scene) { scene.setQuality($("qualitySel").value); sceneSync(); } };
  $("timeSel").value = store.get("wl-time", "golden");
  $("timeSel").onchange = () => { store.set("wl-time", $("timeSel").value); scene && scene.setTime($("timeSel").value); };
  $("labelsChk").onchange = () => scene && scene.setLabels($("labelsChk").checked);
  $("followChk").checked = store.get("wl-follow", true);
  $("followChk").onchange = () => { store.set("wl-follow", $("followChk").checked); if (scene && scene.setFollow) scene.setFollow($("followChk").checked); };
  $("tourBtn").onclick = () => { pop(null); startTour(); };
  $("retry3d").onclick = () => location.reload();
  $("plannerClose").onclick = closePlanner;
  $("tryPlanBtn").onclick = openPlanner;
  $("startBtn").onclick = startSeason;
  $("plUndo").onclick = () => { if (!P.undo.length) return; P.picks = JSON.parse(P.undo.pop()); saveDraft(); renderFieldRows(); preview(); };
  $("plClear").onclick = () => { P.undo.push(JSON.stringify(P.picks)); P.picks = FIELD_IDS.map(() => ({ mode: "scientist" })); P.brush = null; saveDraft(); renderCards(); renderFieldRows(); preview(); };
  document.addEventListener("keydown", onKey);
  document.addEventListener("click", (e) => { if (!e.target.closest(".popover,#settingsBtn,#profileBtn")) pop(null); });
}
function pop(id) { ["settings", "profile"].forEach((k) => { $(k).hidden = k !== id || !$(k).hidden; }); $("settingsBtn").setAttribute("aria-expanded", String(!$("settings").hidden)); $("profileBtn").setAttribute("aria-expanded", String(!$("profile").hidden)); }
function setOverlay(k) { overlay = k || ""; document.querySelectorAll("[data-ov]").forEach((b) => { b.classList.toggle("on", b.dataset.ov === overlay); b.setAttribute("aria-pressed", String(b.dataset.ov === overlay)); }); $("ovSel").value = overlay; if (scene) scene.setOverlay(overlay || null); dirty = true; }
// keep keyboard focus inside the planner while it is open (it's a modal dialog)
function trapFocus(e, root) {
  const f = [...root.querySelectorAll("button:not([disabled]),select:not([disabled]),input:not([disabled]),a[href],[tabindex='0']")].filter((x) => x.offsetParent);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}
function onKey(e) {
  if (e.key === "Tab" && !$("planner").hidden) { trapFocus(e, $("planner")); return; }
  if (e.target.closest("input,select,textarea,details summary") && e.key !== "Escape") return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (!$("tour").hidden) { if (e.key === "Escape") endTour(); return; }
  const k = e.key.toLowerCase();
  if (k >= "1" && k <= "6") { select(Number(k) - 1, true); }
  else if (k === "o") scene && scene.view("overview");
  else if (k === "d") scene && scene.view("drone");
  else if (k === "r") scene && scene.home();
  else if (k === "i" && sel >= 0) scene && scene.focus(sel, "closeup");
  else if (k === "v") { const order = ["", "health", "moisture", "salinity", "water"]; setOverlay(order[(order.indexOf(overlay) + 1) % order.length]); }
  else if (k === " " && mode === "replay") { e.preventDefault(); togglePlay(); }
  else if (k === "]" && mode === "replay") stepEvent(1);
  else if (k === "[" && mode === "replay") stepEvent(-1);
  else if (k === "escape") { if (!$("planner").hidden) closePlanner(); else if (drawer) closeDrawer(); else if (!$("inspector").hidden) $("fiClose").click(); }
  else return;
}

async function boot() {
  wireUi();
  await loadScene();
  const q = new URLSearchParams(location.search);
  const isDemo = /\/demo\/?$/.test(location.pathname) || q.has("demo");
  let replay = q.get("replay") || window.WORLDLAB_REPLAY || (isDemo ? "replay.json" : null);
  if (q.get("run")) replay = `api/runs/${encodeURIComponent(q.get("run"))}/replay`;
  // what the server can do, with a short timeout so a missing server never blocks the page
  try { const r = await api("api/capabilities", { timeout: 4000 }); if (r.ok && (r.headers.get("Content-Type") || "").includes("json")) { caps = await r.json(); serverUp = true; } } catch (e) { /* no server */ }
  let state = null;
  if (!replay && serverUp) {
    try {
      const r = await api("api/state", { timeout: 8000 });
      if (r.status === 401) { go("login", `?next=${encodeURIComponent(PAGES.app)}`); return; }
      if (r.ok && (r.headers.get("Content-Type") || "").includes("json")) state = await r.json();
    } catch (e) { /* unreachable */ }
  }
  if (state) await startLive(state);
  else {
    if (serverUp) { try { const m = await api("api/me", { timeout: 4000 }); if (m.status === 200) { $("profileName").textContent = (await m.json()).user.name; $("loginLink").hidden = true; } } catch (e) { /* ignore */ } }
    if (!serverUp) { $("demoCta").href = "https://github.com/MoAmrYehia/WorldLab#quick-start"; $("demoCta").textContent = "Run WorldLab locally"; $("logoutBtn").hidden = true; }
    if (q.get("run")) $("demoCta").outerHTML = `<a class="ghost" href="${PAGES.app}">Back to your farm</a>`;
    await startReplay(replay || "replay.json").catch((e) => { $("modeNote").textContent = `No live server and no recording found (${e.message}).`; });
  }
  const loop = () => { render(); requestAnimationFrame(loop); };
  loop();
}
boot();
