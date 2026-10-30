// WorldLab: Green Frontier — simulator interface.
// Live mode: the Python server streams a run over server-sent events. Replay mode: a recorded run (replay.json)
// plays with no server. Missions and achievements come from the server's ledger-based scoring ("mission" events).
import { api, apiJson, stream, go, PAGES, setToken } from "./client.js?v=b2e635c2ae";

const $ = (id) => document.getElementById(id);
const D = 273;
const CROP_LABEL = { wheat: "Wheat", rice: "Rice", maize: "Maize", potato: "Potatoes", cassava: "Cassava", soybean: "Soybeans",
  sorghum: "Sorghum", millet: "Millet", beans: "Common beans", sweet_potato: "Sweet potatoes" };
const SALT = { wheat: 6, rice: 3, maize: 1.7, potato: 1.7, cassava: 2, soybean: 5, sorghum: 6.8, millet: 6, beans: 1, sweet_potato: 1.5 };
const NUTRIENT = { kcal: "calories", protein_g: "protein", vitA_ug: "vitamin A" };
const TRAIT = { wp: "Water productivity", cgc: "Canopy growth", heat: "Heat tolerance", salt: "Salt tolerance" };
const FIELD_IDS = ["F1", "F2", "F3", "F4", "F5", "F6"];
const NAMES = ["North", "Palm edge", "Dune", "Old wadi", "Loam block", "Sabkha rim"];
const SOILS = ["loamy sand", "sandy loam", "sand", "saline sandy loam", "loam", "very saline"];
const CHAPTERS = [["discover", "Discover", "Study the farm and run crop experiments."], ["strategize", "Strategize", "Choose crops and plan within the water and energy limits."],
  ["survive", "Survive", "Run the season through heat, salt and faults."], ["recover", "Recover", "Investigate anomalies, find causes, repair, update the model."],
  ["harvest", "Harvest", "Judge food security, water use and resilience."]];
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } } };

const fresh = () => ({ days: [], events: [], perturbations: [], beliefs: null, projections: [], trials: [], scene: {}, drone: [],
  plan: null, status: {}, fields: null, rl_train: [], rl: null, agentKind: null, mission: null, award: null });
let S = fresh();
let portrait = () => null, stageOf = () => 2, dfSel = -1, dfKey = "", droneTimer = 0;
let sel = -1, scene = null, mode = "live", info = {}, progress = null, dirty = true;
let inspKey = "", serverUp = false;
let metric = "health", overlay = "", drawer = null, invClosedFor = null, resultsShownFor = null, seenBadges = new Set();

// ------------------------------------------------------------ helpers
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
function dayLabel(d) { const dt = new Date(Date.UTC(2026, 9, 1) + d * 864e5); return dt.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }); }
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
function fieldsNow() {
  if (S.fields) return S.fields;
  if (S.plan && S.plan.fields) return S.plan.fields.map((f, i) => ({ id: f.field || FIELD_IDS[i], crop: f.crop, label: crop(f.crop), planned: true, sow: f.mgmt && f.mgmt.sow }));
  return FIELD_IDS.map((id) => ({ id, crop: null, label: "Not planned" }));
}
const agentName = (k) => ({ spark: "Muse Spark", glimmer: "Muse Glimmer", "scripted-rl": "Scripted protocol with RL", scripted: "Scripted protocol", "scripted-noadapt": "Scripted, ignores alarms" }[k] || "");

// ------------------------------------------------------------ reducer
const WORLD_EVENTS = new Set(["anomaly", "look", "field_test", "adjust", "model_update", "harvest", "season_result"]);
function apply(m, live = true) {
  const d = m.data;
  switch (m.kind) {
    case "reset": S = fresh(); S.agentKind = d && d.agent; resultsShownFor = null; invClosedFor = null; if (live && scene) scene.reset(); break;
    case "day": S.days.push(d); if (live && scene) { scene.update(d); const k = d.fields.findIndex((f) => f.cc_obs != null); if (k >= 0 && d.day % 8 === 3) scene.hover(k); } break;
    case "ledger":
      S.events.push(d); if (S.events.length > 5000) S.events.splice(0, 500);
      if (live && scene && WORLD_EVENTS.has(d.kind)) scene.event(d.kind, d.data);
      if (live && d.kind === "anomaly") { sel = d.data.field_index; if (scene) scene.setSelected(sel); invClosedFor = null; }
      if (live && d.kind === "season_result") setTimeout(() => showResults(), reducedMotion ? 0 : 2200);
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
  S.drone.push(f); if (S.drone.length > 40) S.drone.shift();
  if (!live) return;
  dfSel = -1;
  if ($("droneDot") && $("droneTab") && !$("droneTab").classList.contains("on")) $("droneDot").hidden = false;
  $("dfLiveTxt").textContent = `${f.kind === "inspection" ? "Inspecting" : "Surveying"} ${f.field}`;
  clearTimeout(droneTimer); droneTimer = setTimeout(() => ($("dfLiveTxt").textContent = "On patrol"), 5000);
}
function syncAnomaly() { const a = S.status && S.status.anomaly; scene.setAnomaly(a ? a.field_index : -1, a ? `${cap(a.signal_label)} ${a.direction}` : ""); }
function sceneSync() {
  if (!scene) return;
  scene.reset();
  scene.setFields(fieldsNow());
  S.trials.forEach((t) => scene.addTrial(t));
  const ld = lastDay(); if (ld) scene.update(ld);
  syncAnomaly(); scene.setSelected(sel); scene.setOverlay(overlay);
}

// ------------------------------------------------------------ render
function render() {
  if (!dirty) return;
  dirty = false;
  renderTop(); renderMissions(); renderImpact(); renderDock(); renderInspector(); renderIncident(); renderInvestigation(); renderLegend(); renderDrone();
  if (drawer) renderDrawer();
}

function renderTop() {
  const chip = $("modeChip");
  chip.textContent = mode === "live" ? (info.running ? "Live season" : "Your farm") : "Recorded season";
  chip.classList.toggle("live", mode === "live" && !!info.running);
  let xp = 0, lvl = 1, floor = 0, next = 100, demo = !progress;
  if (progress) ({ xp, level: lvl, level_floor: floor, next_level_at: next } = progress.level);
  else if (S.mission) { xp = S.mission.xp_items.reduce((a, b) => a + b.xp, 0); ({ lvl, floor, next } = levelFor(xp)); }
  $("xpLevel").textContent = demo ? `Demo LVL ${String(lvl).padStart(2, "0")}` : `LVL ${String(lvl).padStart(2, "0")}`;
  $("xpText").textContent = `${fmt(xp)} XP`;
  $("xpBar").style.width = `${Math.min(100, (100 * (xp - floor)) / Math.max(1, next - floor))}%`;
  $("xpPill").title = demo ? "Experience this recorded season would earn. Sign up to keep your own." : "Your level and experience";
}
function levelFor(xp) { let n = 1; while (100 * n * n <= xp) n++; return { lvl: n, floor: 100 * (n - 1) ** 2, next: 100 * n * n }; }

function renderMissions() {
  const m = S.mission, st = S.status || {};
  const cur = m ? m.current_chapter : st.phase === "season" ? "survive" : st.phase === "planning" ? "strategize" : "discover";
  const ld = lastDay();
  const T = { discover: ["Discover", "Learn the land before you plant it."], strategize: ["Strategize", "Plan a better harvest."], survive: ["Survive", "Keep the farm alive."],
    recover: ["Recover", "Find the cause, fix it, update the model."], harvest: ["Harvest", st.result ? "The season is in." : "Bring the season home."] }[cur];
  $("seasonEyebrow").textContent = ld ? `Season, day ${ld.day + 1} of ${D}: ${dayLabel(Math.min(ld.day, D - 1))}` : st.phase === "planning" ? "Season, planning" : S.trials.length ? "Trial season" : "Season";
  $("headline").innerHTML = `${esc(T[0])}. <em>${esc(T[1])}</em>`;
  const chapters = m ? m.chapters : CHAPTERS.map(([id, title, about]) => ({ id, title, about, objectives: [], done: false, progress: 0 }));
  const html = chapters.map((c, k) => {
    const cls = c.done ? "done" : c.id === cur ? "now" : "";
    const objs = c.id === cur && c.objectives.length ? `<ul class="objs">${c.objectives.map((o) => `<li class="${o.done ? "ok" : ""}"><span>${esc(o.label)}</span><span>${o.value ? esc(o.value) : ""}</span></li>`).join("")}</ul>` : "";
    return `<li class="chapter ${cls}"><span class="num">${c.done ? "✓" : k + 1}</span><b>${esc(c.title)}</b><span class="about">${esc(c.about)}</span>${objs}</li>`;
  }).join("");
  if ($("chapters").dataset.h !== html) { $("chapters").innerHTML = html; $("chapters").dataset.h = html; }
}

function renderImpact() {
  const st = S.status || {};
  let n = null, label = "people fed in a bad year", lim = null;
  if (st.result) { n = st.result.people_fed; label = "people fed by this harvest"; lim = st.result.limiting; }
  else if (st.phase === "season" && lastProj()) { const p = lastProj(); n = p.people_p10; label = "people fed in a bad year, projected"; lim = minKey(p.by_nutrient_p50); }
  else if (S.plan) { n = S.plan.people_p10; label = "people fed in a bad year, planned"; lim = S.plan.limiting; }
  $("livesN").textContent = n == null ? "–" : fmt(n);
  $("livesSub").textContent = label;
  $("limitNote").textContent = lim ? `Limited by ${NUTRIENT[lim] || lim}. A person counts only when calories, protein and vitamin A are all covered.` : "A person counts only when calories, protein and vitamin A are all covered.";
  const wq = st.water_quota_m3 || 60000, eq = st.energy_kwh || 90000, ld = lastDay();
  const w = (ld && ld.water_used_m3 != null ? ld.water_used_m3 : st.water_used_m3) || 0;
  const e = (ld && ld.energy_used_kwh != null ? ld.energy_used_kwh : st.energy_used_kwh) || 0;
  $("waterTxt").textContent = `${fmt(w / 1000, 1)}k / ${fmt(wq / 1000)}k m³`; $("energyTxt").textContent = `${fmt(e / 1000, 1)}k / ${fmt(eq / 1000)}k kWh`;
  bar("waterBar", w / wq); bar("energyBar", e / eq);
  $("goalTxt").textContent = n == null ? "–" : `${fmt(n)} / 500`; bar("goalBar", (n || 0) / 500, false);
  const rl = (ld && ld.controller ? ld.controller : st.controller) === "rl_policy";
  $("ctrlPill").textContent = rl ? "RL policy" : "Fixed rule"; $("ctrlPill").classList.toggle("rl", rl);
  $("agentName").textContent = agentName(S.agentKind || info.agent);
  const items = streamItems();
  const lastSci = [...items].reverse().find((x) => ["decide", "test", "learn", "alarm", "rl"].includes(x.it[0]));
  $("scQuote").innerHTML = lastSci ? `${lastSci.it[1]}` : "Waiting for the season to start.";
  const active = (mode === "live" && info.running) || (mode === "replay" && R.playing);
  $("scLive").textContent = st.result ? "Done" : active ? "Active" : "Idle"; $("scLive").classList.toggle("on", !!active && !st.result);
}
function bar(id, frac, over = true) { const el = $(id); el.style.width = `${Math.min(100, Math.max(0, frac * 100))}%`; el.classList.toggle("over", over && frac > 1); }
function minKey(o) { if (!o) return null; return Object.keys(o).reduce((a, b) => (o[a] <= o[b] ? a : b)); }

// ------------------------------------------------------------ dock
function renderDock() {
  const ld = lastDay(), fl = fieldsNow(), an = S.status && S.status.anomaly;
  const lastCc = FIELD_IDS.map((_, i) => { for (let k = S.days.length - 1; k >= 0; k--) { const f = S.days[k].fields[i]; if (f && f.cc_obs != null) return [f.cc_obs, f.cc_pred]; } return null; });
  const box = $("gauges"), C = 2 * Math.PI * 26;
  if (box.children.length !== FIELD_IDS.length) {
    box.innerHTML = FIELD_IDS.map((id, i) => `<button class="gauge" data-i="${i}" type="button">
      <span class="g-title"></span>
      <svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="26" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="6"/><circle class="g-arc" cx="32" cy="32" r="26" fill="none" stroke-width="6" stroke-linecap="round" stroke-dasharray="${C}" stroke-dashoffset="${C}" transform="rotate(-90 32 32)"/>
      <text class="g-val" x="32" y="36" text-anchor="middle" font-weight="700" font-family="Sora, sans-serif"></text></svg>
      <span class="g-sub"></span></button>`).join("");
    box.querySelectorAll(".gauge").forEach((b) => (b.onclick = () => select(Number(b.dataset.i), true)));
  }
  FIELD_IDS.forEach((id, i) => {
    const f = ld && ld.fields[i], w = ld && ld.world && ld.world[i], c = fl[i] || {};
    let frac = 0, val = "–", sub = c.crop ? "Not sown yet" : "Fallow", col = css("--emerald");
    if (f && w && w.sown) {
      if (metric === "health") {
        const cc = lastCc[i];
        if (w.done) { frac = 1; val = "Harvested"; sub = ""; col = css("--amber"); }
        else if (cc && cc[1] > 0.05) { const r = cc[0] / cc[1]; frac = Math.min(1, r / 1.2); val = `${Math.round(r * 100)}%`; sub = r >= 0.9 ? "Canopy on track with model" : r >= 0.75 ? "Canopy below model" : "Canopy well below model"; col = r >= 0.9 ? css("--emerald") : r >= 0.75 ? css("--amber") : css("--alarm"); }
        else { val = "–"; sub = "Canopy too small"; }
      } else if (metric === "moisture") { frac = (f.sw_obs - 0.04) / 0.26; val = fmt(f.sw_obs, 3); sub = "m³/m³, top 50 cm"; col = css("--cyan"); }
      else if (metric === "salinity") { const thr = SALT[c.crop] || 3; frac = f.ec_obs / (thr * 2); val = `${fmt(f.ec_obs, 1)}`; sub = f.ec_obs > thr ? `dS/m, above the ${crop(c.crop).toLowerCase()} limit` : "dS/m, below the crop limit"; col = f.ec_obs > thr ? css("--alarm") : css("--amber"); }
      else { frac = (f.irr_mm || 0) / 12; val = `${fmt(f.irr_mm, 1)}`; sub = `mm today${f.desal ? `, ${Math.round(f.desal * 100)}% desalinated` : ""}`; col = css("--cyan"); }
    }
    frac = Math.min(1, Math.max(0, frac));
    const b = box.children[i], title = `${id} ${c.crop ? crop(c.crop) : "Fallow"}`;
    const st = c.crop ? stageOf(c.crop, w) : -1, tkey = `${title}|${st}`;
    b.classList.toggle("sel", i === sel); b.classList.toggle("alarm", !!(an && an.field_index === i));
    b.setAttribute("aria-label", `${title}: ${val} ${sub}`);
    if (b.children[0].dataset.k !== tkey) {
      b.children[0].dataset.k = tkey;
      const pic = c.crop ? portrait(c.crop, st, 48) : null;
      b.children[0].innerHTML = `${pic ? `<img class="g-pic" src="${pic}" alt="">` : ""}${esc(title)}`;
    }
    const arc = b.querySelector(".g-arc"); arc.setAttribute("stroke", col); arc.setAttribute("stroke-dashoffset", String(C * (1 - frac)));
    const t = b.querySelector(".g-val"); if (t.textContent !== val) { t.textContent = val; t.setAttribute("font-size", val.length > 6 ? 9 : val.length > 3 ? 12 : 13); t.setAttribute("fill", css("--ink")); }
    if (b.children[2].textContent !== sub) b.children[2].textContent = sub;
  });
  // timeline
  const day = ld ? ld.day + 1 : 0;
  $("tlFill").style.width = `${(100 * day) / D}%`;
  const tl = $("timeline").querySelector(".tl-track");
  tl.querySelectorAll(".tl-mark,.tl-now").forEach((e) => e.remove());
  const mark = (d, cls, title) => { const e = document.createElement("i"); e.className = `tl-mark ${cls}`; e.style.left = `${(100 * d) / D}%`; e.title = title; tl.appendChild(e); };
  S.perturbations.forEach((p) => mark(p.day, "change", `${dayLabel(p.day)}: ${p.note}`));
  S.events.filter((e) => e.kind === "anomaly").forEach((e) => mark(e.data.detected_day, "alarm", `${dayLabel(e.data.detected_day)}: alarm in ${e.data.field}`));
  S.events.filter((e) => e.kind === "harvest").forEach((e) => mark(e.data.day, "harvest", `${dayLabel(e.data.day)}: ${e.data.field} harvested`));
  if (ld) { const n = document.createElement("i"); n.className = "tl-now"; n.style.left = `${(100 * day) / D}%`; tl.appendChild(n); }
  if (!$("tlMonths").children.length) $("tlMonths").innerHTML = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"].map((m) => `<span>${m}</span>`).join("");
  // activity
  const items = streamItems();
  const key = String(items.length);
  if ($("activity").dataset.k !== key) {
    $("activity").dataset.k = key;
    $("activity").innerHTML = items.slice(-60).reverse().map(({ it, t }) => `<li class="k-${it[0]}"><span>${it[1]}${it[2] || ""}</span><time>${t != null ? dayLabel(Math.min(t, D - 1)) : ""}</time></li>`).join("");
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
    case "trial_result": { const held = d.plots.filter((p) => p.prediction_held).length; return [held < d.plots.length ? "test" : "learn", `${held} of ${d.plots.length} trial predictions held`, ""]; }
    case "model_update": return ["learn", d.crops ? `Calibrates ${d.crops.map((c) => crop(c.crop)).join(", ")}` : `Teaches the model: ${esc(String(d.finding).replace(/_/g, " "))} = ${d.value} in ${d.field}`, why(d.rationale)];
    case "plan": return ["decide", `Plans the season: ${fmt(d.people_p10)} people in a bad year`, why(d.scientist_choice ? (d.scientist_choice.people_p10 > d.people_p10 ? `Keeps your crops; its own choice would feed ${fmt(d.scientist_choice.people_p10)}.` : "Keeps your crops; it found no better mix.") : `Uncertainty costs ${fmt(d.cost_of_uncertainty_people)} people.`)];
    case "farmer_choices": return ["decide", "Your crop choices recorded", why(d.fields.filter((f) => f.crop || f.choice === "fallow").map((f) => `${f.field}: ${f.choice}`).join("; "))];
    case "rl_train_start": return ["rl", "Trains an irrigation policy by reinforcement learning", why(d.rationale)];
    case "rl_policy": { const c = d.held_out_comparison || {}; return ["rl", d.recommend === "rl_policy" ? `Policy validated: water ${signed(c.water_change_pct)}%, energy ${signed(c.energy_change_pct)}% in held-out seasons` : "Policy did not beat the fixed rule; keeps the rule", why(d.note)]; }
    case "controller": return ["rl", d.controller === "rl_policy" ? "Hands irrigation to the RL policy" : "Hands irrigation back to the fixed rule", why(d.rationale)];
    case "season_start": return ["decide", `Sows the season, irrigation by ${d.controller === "rl_policy" ? "the RL policy" : "the fixed rule"}`, ""];
    case "anomaly": return ["alarm", `Alarm in ${d.field}: ${esc(d.signal_label)} ${esc(d.direction)}`, why(`Onset around ${dayLabel(d.onset_day)}. Season paused to investigate.`)];
    case "field_test": return ["test", `${d.field}: ${esc(testText(d))}`, why(d.rationale)];
    case "look": return ["test", `Drone over ${d.field}: canopy ${fmt(d.canopy_cover_measured, 2)} measured vs ${fmt(d.canopy_cover_predicted, 2)} predicted`, why(d.diagnosis && d.diagnosis.condition ? `Image diagnosis: ${String(d.diagnosis.condition).replace(/_/g, " ")}` : d.reason)];
    case "adjust": return ["decide", `${d.field}: ${[d.repair ? "repairs the drip line" : "", d.pest_control ? "applies pest control" : "", d.irr != null ? `irrigation ${Math.round(d.irr * 100)}%` : "", d.desal != null ? `desalinated water ${Math.round(d.desal * 100)}%` : ""].filter(Boolean).join(", ")}`, why(d.rationale)];
    case "rebalance": return ["decide", `Re-plans water: ${d.people_p10_before} → ${d.people_p10_after} people in a bad year`, ""];
    case "anomaly_dismissed": return ["decide", "Dismisses the alarm", why(d.rationale)];
    case "harvest": return ["learn", `${d.field} ${crop(d.crop)} harvested: ${d.yield_t_ha} t/ha`, ""];
    case "season_result": return ["learn", `Season over: ${fmt(d.people_fed)} people fed`, why(`${fmt(d.water_used_m3)} m³ groundwater, ${fmt(d.energy_used_kwh)} kWh`)];
    case "agent_step": return d.role === "agent" ? ["decide", esc(d.text), ""] : null;
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
let itemsCache = { n: -1, p: -1, items: [] };
function streamItems() {
  if (itemsCache.n === S.events.length && itemsCache.p === S.perturbations.length) return itemsCache.items;
  const items = []; let inSeason = false;
  const pert = [...S.perturbations];
  const due = (p, k, e) => (p._order != null ? p._order <= k : !e || (inSeason && e.t != null && e.t > p.day));
  const pushPert = (k, e) => { while (pert.length && due(pert[0], k, e)) { const p = pert.shift(); items.push({ it: ["world", `Hidden change in ${p.field === "all" ? "the farm" : p.field}`, `<span class="why">${esc(p.note)}. The scientist is not told.</span>`], t: p.day }); } };
  S.events.forEach((e, k) => { pushPert(k, e); if (e.kind === "season_start") inSeason = true; const it = streamItem(e); if (it) items.push({ it, t: inSeason && e.kind !== "season_start" ? e.t : null, e }); });
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
  const ik = `${sel}|${S.days.length}|${S.events.length}|${S.perturbations.length}|${mode}|${S.status.phase}`;
  if (ik === inspKey) return; inspKey = ik;
  const fl = fieldsNow(), f = fl[sel] || {}, ld = lastDay(), w = ld && ld.world && ld.world[sel];
  $("fiTitle").textContent = `${FIELD_IDS[sel]} ${NAMES[sel]}`;
  const fpic = f.crop ? portrait(f.crop, stageOf(f.crop, w), 80) : null;
  $("fiPic").hidden = !fpic; if (fpic) { $("fiPic").src = fpic; $("fiPic").alt = `${crop(f.crop)} at its current stage`; }
  let sub = `${cap(SOILS[sel])}. ${f.crop ? crop(f.crop) : "Fallow"}`;
  if (f.crop && f.sow != null) sub += `, sown ${dayLabel(f.sow)}`;
  if (w && w.sown && !w.done) sub += `, ${Math.round(100 * Math.min(w.stage, 1))}% through its cycle`;
  if (w && w.done) sub += ", harvested";
  if (!S.fields && !S.plan) sub = `${cap(SOILS[sel])}. Not planned yet.`;
  $("fiSub").textContent = sub + ".";
  const marks = markersFor(sel);
  bandChart($("chSw"), "sw", { fmt: (v) => fmt(v, 3), marks });
  bandChart($("chCc"), "cc", { fmt: (v) => fmt(v, 2), marks, sparse: true, min: 0, max: 1 });
  bandChart($("chEc"), "ec", { fmt: (v) => fmt(v, 1), marks, min: 0 });
  irrChart($("chIrr"));
  const sc = S.scene[FIELD_IDS[sel]];
  $("droneFig").hidden = !sc || !sc.image;
  if (sc && sc.image && $("droneImg").dataset.src !== sc.image) {
    $("droneImg").src = sc.image; $("droneImg").dataset.src = sc.image;
    const diag = sc.diagnosis && sc.diagnosis.condition ? `, diagnosis: ${String(sc.diagnosis.condition).replace(/_/g, " ")}` : "";
    $("droneCap").textContent = `Drone image analysed${sc.source ? ` by ${sc.source}` : ""}${diag}.`;
  }
  $("perturb").hidden = !(mode === "live" && S.status.phase === "season");
}
function markersFor(i) {
  const id = FIELD_IDS[i], m = [];
  S.perturbations.forEach((p) => { if (p.field === id || p.field === "all") m.push({ day: p.day, cls: "change" }); });
  S.events.forEach((e) => { if (e.kind === "anomaly" && e.data.field === id) m.push({ day: e.data.detected_day, cls: "alarm" }); });
  return m;
}
function bandChart(svg, key, opts) {
  svg.innerHTML = "";
  const W = 300, H = 80;
  const rows = S.days.map((d) => ({ day: d.day, f: d.fields[sel] })).filter((r) => r.f);
  if (!rows.length) { svgEl("text", { x: 4, y: H / 2, "font-size": 11, fill: css("--ink-3") }, svg).textContent = "Starts when the season begins"; return; }
  const lo = rows.map((r) => r.f[key + "_lo"]), hi = rows.map((r) => r.f[key + "_hi"]), pr = rows.map((r) => r.f[key + "_pred"]), ob = rows.map((r) => r.f[key + "_obs"]);
  const vals = [...lo, ...hi, ...ob].filter((v) => v != null && Number.isFinite(v));
  let [y0, y1] = nice(Math.min(...vals), Math.max(...vals));
  if (opts.min != null) y0 = Math.max(opts.min, y0);
  if (opts.max != null) y1 = Math.min(opts.max, y1);
  const X = (d) => (d / (D - 1)) * W, Y = (v) => H - ((v - y0) / (y1 - y0)) * H;
  for (let k = 0; k <= 2; k++) svgEl("line", { x1: 0, x2: W, y1: (k * H) / 2, y2: (k * H) / 2, stroke: "rgba(255,255,255,.07)", "vector-effect": "non-scaling-stroke" }, svg);
  let band = "";
  rows.forEach((r, k) => { if (hi[k] != null) band += `${band ? "L" : "M"}${X(r.day).toFixed(1)},${Y(hi[k]).toFixed(1)}`; });
  for (let k = rows.length - 1; k >= 0; k--) if (lo[k] != null) band += `L${X(rows[k].day).toFixed(1)},${Y(lo[k]).toFixed(1)}`;
  svgEl("path", { d: band + "Z", fill: css("--model-band"), stroke: "none" }, svg);
  let line = ""; rows.forEach((r, k) => { if (pr[k] != null) line += `${line ? "L" : "M"}${X(r.day).toFixed(1)},${Y(pr[k]).toFixed(1)}`; });
  svgEl("path", { d: line, fill: "none", stroke: css("--model"), "stroke-width": 1.6, "vector-effect": "non-scaling-stroke" }, svg);
  opts.marks.forEach((m) => svgEl("line", { x1: X(m.day), x2: X(m.day), y1: 0, y2: H, stroke: m.cls === "alarm" ? css("--alarm") : css("--ink-2"), "stroke-width": 1.4, "stroke-dasharray": m.cls === "alarm" ? "" : "3 3", "vector-effect": "non-scaling-stroke" }, svg));
  let dots = ""; rows.forEach((r, k) => { if (ob[k] != null) dots += `M${X(r.day).toFixed(1)},${Y(ob[k]).toFixed(1)}h0`; });
  svgEl("path", { d: dots, stroke: css("--measured"), "stroke-width": opts.sparse ? 4.5 : 3, "stroke-linecap": "round", fill: "none", "vector-effect": "non-scaling-stroke" }, svg);
  svgEl("text", { x: W - 2, y: 10, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = opts.fmt(y1);
  svgEl("text", { x: W - 2, y: H - 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = opts.fmt(y0);
  const cursor = svgEl("line", { x1: 0, x2: 0, y1: 0, y2: H, stroke: css("--ink-2"), "stroke-width": 1, "vector-effect": "non-scaling-stroke", visibility: "hidden" }, svg);
  const hit = svgEl("rect", { x: 0, y: 0, width: W, height: H, fill: "transparent" }, svg);
  hit.addEventListener("mousemove", (ev) => {
    const r = svg.getBoundingClientRect(); const day = Math.round(((ev.clientX - r.left) / r.width) * (D - 1));
    const k = rows.findIndex((x) => x.day >= day); if (k < 0) return;
    cursor.setAttribute("x1", X(rows[k].day)); cursor.setAttribute("x2", X(rows[k].day)); cursor.setAttribute("visibility", "visible");
    const tip = $("tip"); tip.hidden = false;
    tip.innerHTML = `${dayLabel(rows[k].day)}<br><span style="color:var(--model)">Model ${opts.fmt(pr[k])} (${opts.fmt(lo[k])}–${opts.fmt(hi[k])})</span>${ob[k] != null ? `<br><span style="color:var(--measured)">Measured ${opts.fmt(ob[k])}</span>` : ""}`;
    tip.style.left = `${Math.min(ev.clientX + 12, innerWidth - 200)}px`; tip.style.top = `${ev.clientY + 12}px`;
  });
  hit.addEventListener("mouseleave", () => { $("tip").hidden = true; cursor.setAttribute("visibility", "hidden"); });
}
function irrChart(svg) {
  svg.innerHTML = "";
  const W = 300, H = 40;
  const rows = S.days.map((d) => ({ day: d.day, f: d.fields[sel] })).filter((r) => r.f);
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

// ------------------------------------------------------------ incident and investigation (only what the ledger shows)
function currentIncident() {
  const ev = S.events; let idx = -1;
  for (let k = ev.length - 1; k >= 0; k--) if (ev[k].kind === "anomaly") { idx = k; break; }
  if (idx < 0) return null;
  const a = ev[idx], after = ev.slice(idx + 1);
  const next = after.findIndex((e) => e.kind === "anomaly");
  const seg = next >= 0 ? after.slice(0, next) : after;
  const ld = lastDay();
  if (ld && ld.day > a.data.detected_day + 40 && !(S.status && S.status.anomaly)) return null;
  return { a, seg, open: !!(S.status && S.status.anomaly) };
}
function renderIncident() {
  const inc = currentIncident(), open = inc && inc.open;
  $("incident").hidden = !open;
  document.body.classList.toggle("incident-on", !!open);
  if (open) $("incidentText").textContent = `Field ${inc.a.data.field} / ${inc.a.data.signal_label} ${inc.a.data.direction}`;
}
function renderInvestigation() {
  const inc = currentIncident();
  const show = inc && invClosedFor !== inc.a.seq;
  $("investigation").hidden = !show;
  $("missionPanel").classList.toggle("dimmed", !!show);
  if (!show) return;
  const { a, seg } = inc, d = a.data, fi = d.field_index;
  const tests = seg.filter((e) => e.kind === "field_test" || e.kind === "look");
  const hyps = seg.filter((e) => e.kind === "hypothesis").map((e) => e.data);
  const concl = {}; seg.filter((e) => e.kind === "conclusion").forEach((e) => (concl[e.data.hypothesis_id] = e.data.verdict));
  const fixes = seg.filter((e) => (e.kind === "adjust") || (e.kind === "model_update" && e.data.finding) || e.kind === "rebalance" || e.kind === "anomaly_dismissed" || e.kind === "controller");
  const identified = Object.values(concl).includes("supported") || seg.some((e) => e.kind === "model_update" && e.data.finding);
  const steps = [["Detect the anomaly", true], ["Gather evidence", tests.length > 0], ["Identify the cause", identified], ["Apply a repair or correction", fixes.length > 0]];
  const nowStep = steps.findIndex((s) => !s[1]);
  const day = S.days.find((x) => x.day === d.detected_day) || lastDay();
  const f = day && day.fields[fi];
  const sig = d.signal, unit = sig === "ec" ? " dS/m" : sig === "sw" ? " m³/m³" : "";
  const dec = sig === "sw" ? 3 : sig === "cc" ? 2 : 1;
  const obs = f && f[sig + "_obs"], pred = f && f[sig + "_pred"];
  const fieldPert = S.perturbations.find((p) => p.field === d.field || p.field === "all");
  $("invBody").innerHTML = `
    <p class="eyebrow" style="color:var(--alarm)">Field ${esc(d.field)} ${esc(crop(d.crop))}</p>
    <h3 style="font-size:19px;margin:4px 0 6px">${esc(cap(d.signal_label))} ${esc(d.direction)}</h3>
    <p class="note" style="margin:0 0 8px">Measurements left the model's 90% band around ${dayLabel(d.onset_day)}; the alarm fired on ${dayLabel(d.detected_day)}.</p>
    <ol class="inv-steps">${steps.map((s, k) => `<li class="${s[1] ? "done" : k === nowStep ? "now" : ""}"><i>${s[1] ? "✓" : k + 1}</i>${s[0]}</li>`).join("")}</ol>
    ${obs != null ? `<p class="inv-h">At detection</p><div class="mvp"><div class="p"><span>Model predicted</span><b>${fmt(pred, dec)}${unit}</b></div><div class="m"><span>Measured</span><b>${fmt(obs, dec)}${unit}</b></div></div>` : ""}
    ${hyps.length ? `<p class="inv-h">Competing hypotheses</p>${hyps.map((h) => `<div class="hyp ${concl[h.id] || "open"}"><span class="st">${concl[h.id] || "open"}</span>${esc(h.statement)}</div>`).join("")}` : `<p class="inv-h">Competing hypotheses</p><p class="note">The scientist has not recorded any yet.</p>`}
    ${tests.length ? `<p class="inv-h">Evidence</p>${tests.map((e) => `<div class="test">${e.kind === "look" ? `Drone image: canopy <b>${fmt(e.data.canopy_cover_measured, 2)}</b> vs ${fmt(e.data.canopy_cover_predicted, 2)} predicted` : esc(cap(testText(e.data)))}</div>`).join("")}` : ""}
    ${fixes.length ? `<p class="inv-h">What it did</p>${fixes.map((e) => `<div class="fix">${streamItem(e) ? streamItem(e)[1] : esc(e.kind)}</div>`).join("")}` : ""}
    ${fieldPert && S.status.result ? `<p class="note">Hidden cause, revealed after the season: ${esc(fieldPert.note)}.</p>` : ""}`;
}

function renderLegend() {
  const box = $("ovLegend");
  if (!overlay || !OV[overlay]) { box.hidden = true; return; }
  const o = OV[overlay];
  box.hidden = false;
  box.innerHTML = `<b>${esc(o.label)}</b><div class="ramp" style="background:linear-gradient(90deg,${o.ramp.join(",")})"></div><div class="ends"><span>${o.lo} ${esc(o.unit)}</span><span>${o.hi} ${esc(o.unit)}</span></div><p class="note">Field colour from the latest sensor reading. Fields without a reading stay natural.</p>`;
}
let OV = {};

// ------------------------------------------------------------ drawers
const DRAWERS = {
  research: { title: "Research lab", tabs: [["trials", "Trial plots"], ["beliefs", "Crop traits"], ["rl", "RL policy"]] },
  agent: { title: "The AI agent", tabs: [["loop", "Agent loop"], ["components", "AI components"]] },
  plan: { title: "Season plan", tabs: [] },
  reasoning: { title: "The scientist's reasoning", tabs: [] },
  ledger: { title: "Audit ledger", tabs: [] },
  history: { title: "Your seasons", tabs: [] },
  badges: { title: "Achievements", tabs: [] },
};
let drawerTab = null, drawerKey = "";
function openDrawer(name, tab) {
  drawer = name; drawerTab = tab || (DRAWERS[name].tabs[0] || [null])[0];
  $("drawer").hidden = false; $("drawerTitle").textContent = DRAWERS[name].title;
  $("drawerTabs").innerHTML = DRAWERS[name].tabs.map(([k, l]) => `<button type="button" data-t="${k}" class="${k === drawerTab ? "on" : ""}">${l}</button>`).join("");
  $("drawerTabs").querySelectorAll("button").forEach((b) => (b.onclick = () => openDrawer(name, b.dataset.t)));
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", (b.id === "navResearch" && name === "research") || (b.id === "navAgent" && name === "agent") || (b.id === "navSim" && name !== "research" && name !== "agent")));
  drawerKey = ""; renderDrawer();
}
function closeDrawer() { drawer = null; $("drawer").hidden = true; document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.id === "navSim")); }
function renderDrawer() {
  const key = `${drawer}|${drawerTab}|${S.drone.length}|${S.trials.length}|${S.rl_train.length}|${!!S.rl}|${S.plan && S.plan.plan_id}|${S.beliefs && S.beliefs.day}|${S.events.length}|${progress ? progress.level.xp : 0}`;
  if (key === drawerKey) return; drawerKey = key;
  const b = $("drawerBody");
  if (drawer === "agent") { b.innerHTML = drawerTab === "loop" ? agentHtml() : componentsHtml(); return; }
  if (drawer === "research") { b.innerHTML = drawerTab === "trials" ? trialsHtml() : drawerTab === "beliefs" ? beliefsHtml() : rlHtml(); if (drawerTab === "rl") drawRl(); }
  else if (drawer === "plan") b.innerHTML = planHtml();
  else if (drawer === "reasoning") b.innerHTML = reasoningHtml();
  else if (drawer === "ledger") { b.innerHTML = ledgerHtml(); const v = $("verifyBtn"); if (v) v.onclick = verifyLedger; }
  else if (drawer === "history") { b.innerHTML = `<p class="empty">Loading…</p>`; historyHtml().then((h) => { if (drawer === "history") b.innerHTML = h; }); }
  else if (drawer === "badges") b.innerHTML = badgesHtml();
}
function rangeSvg(lo, hi, med, meas, max) {
  const X = (v) => 4 + (v / max) * 152;
  return `<svg viewBox="0 0 160 14" width="160" height="14" aria-hidden="true"><line x1="4" x2="156" y1="7" y2="7" stroke="rgba(255,255,255,.12)"/><rect x="${X(lo)}" y="3" width="${Math.max(2, X(hi) - X(lo))}" height="8" rx="2" fill="${css("--model-band")}" stroke="${css("--model")}"/><line x1="${X(med)}" x2="${X(med)}" y1="2" y2="12" stroke="${css("--model")}" stroke-width="1.5"/><circle cx="${X(meas)}" cy="7" r="3.6" fill="${css("--measured")}"/></svg>`;
}
function trialsHtml() {
  if (!S.trials.length) return `<p class="empty">No trial plots yet. Each plot gets a predicted yield range before it is planted; the harvest then shows whether the model was right.</p>`;
  const max = Math.max(...S.trials.map((t) => Math.max(t.predicted_yield_90pct[1], t.measured_yield_t_ha))) * 1.05;
  const held = S.trials.filter((t) => t.prediction_held).length;
  return `<p style="margin:0 0 10px">${held} of ${S.trials.length} predictions held. The misses are the useful ones: calibration learns from them.</p><table><thead><tr><th>Crop</th><th>Plot</th><th>Sown</th><th>Predicted range and measured yield</th><th class="n">Measured</th><th>Prediction</th></tr></thead><tbody>${S.trials.map((t) => `<tr><td>${crop(t.crop)}</td><td>${t.plot}</td><td>${dayLabel(t.sow)}</td><td>${rangeSvg(t.predicted_yield_90pct[0], t.predicted_yield_90pct[1], t.predicted_yield_median, t.measured_yield_t_ha, max)}</td><td class="n">${fmt(t.measured_yield_t_ha, 1)} t/ha</td><td>${t.prediction_held ? '<span class="ok">Held</span>' : '<span class="miss">Missed</span>'}</td></tr>`).join("")}</tbody></table>`;
}
function beliefsHtml() {
  if (!S.beliefs) return `<p class="empty">No beliefs yet.</p>`;
  const crops = [...S.beliefs.crops].sort((a, b) => b.plots - a.plots);
  const cell = (c, k) => {
    const t = c.traits[k], sd0 = t.prior_sd, c0 = k === "wp" || k === "cgc" ? 1 : 0, lo = c0 - 3 * sd0, hi = c0 + 3 * sd0;
    const X = (v) => Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
    return `<svg viewBox="0 0 100 18" preserveAspectRatio="none" aria-label="${TRAIT[k]} ${t.mean} ± ${t.sd}"><line x1="${X(c0 - 2 * sd0)}" x2="${X(c0 + 2 * sd0)}" y1="9" y2="9" stroke="rgba(255,255,255,.12)" stroke-width="6" stroke-linecap="round" vector-effect="non-scaling-stroke"/><line x1="${X(t.mean - 2 * t.sd)}" x2="${X(t.mean + 2 * t.sd)}" y1="9" y2="9" stroke="${css("--model")}" stroke-width="2.5" vector-effect="non-scaling-stroke"/><path d="M${X(t.mean)},9h0" stroke="${css("--model")}" stroke-width="8" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
  };
  return `<p style="margin:0 0 10px">Uncertainty reduction: grey is the published value with its prior uncertainty; cyan is the current belief (mean and 95% interval). It narrows only for traits a trial plot exposed.</p><div class="forest"><span class="h">Crop (plots)</span>${Object.values(TRAIT).map((t) => `<span class="h">${t}</span>`).join("")}${crops.map((c) => `<span>${crop(c.crop)} <span style="color:var(--ink-3)">(${c.plots})</span></span>${["wp", "cgc", "heat", "salt"].map((k) => cell(c, k)).join("")}`).join("")}</div>`;
}
function planHtml() {
  const p = S.plan;
  if (!p) return `<p class="empty">No plan yet.</p>`;
  const cmp = p.scientist_choice ? (p.scientist_choice.people_p10 > p.people_p10 ? ` With a free choice of crops the scientist would feed ${fmt(p.scientist_choice.people_p10)}.` : " The scientist found no crop mix that does better than your picks.") : "";
  return `<p style="margin:0 0 10px">Plan ${p.plan_id} feeds <b>${fmt(p.people_p10)}</b> people in a bad year and ${fmt(p.people_p50)} in a typical one. Not knowing the varieties exactly costs ${fmt(p.cost_of_uncertainty_people)} people.${cmp}</p><table><thead><tr><th>Field</th><th>Crop</th><th>Sowing</th><th class="n">Irrigation</th><th class="n">Desalinated</th><th class="n">Nitrogen</th><th class="n">Yield, typical</th></tr></thead><tbody>${p.fields.map((f, i) => f.crop ? `<tr><td>${f.field} ${NAMES[i]}</td><td>${crop(f.crop)}${f.farmer_choice ? ' <span class="pill rl">your pick</span>' : ""}</td><td>${dayLabel(f.mgmt.sow)}</td><td class="n">${Math.round(f.mgmt.irr * 100)}%</td><td class="n">${Math.round(f.mgmt.desal * 100)}%</td><td class="n">${fmt(f.mgmt.nfert)} kg/ha</td><td class="n">${fmt(f.yield_t_ha_p10_p50_p90[1], 1)} t/ha</td></tr>` : `<tr><td>${f.field} ${NAMES[i]}</td><td colspan="6" style="color:var(--ink-3)">Left fallow</td></tr>`).join("")}</tbody></table>`;
}
function rlHtml() {
  if (!S.rl && !S.rl_train.length) return `<p class="empty">No policy trained yet. After planning, the scientist can train a daily irrigation policy inside its own model of the farm, then decide whether to use it.</p>`;
  const r = S.rl, c = r && r.held_out_comparison;
  const top = c ? `<div class="deltas"><div><b>${signed(c.people_p10_change_pct)}%</b><span>people fed, bad year</span></div><div><b>${signed(c.water_change_pct)}%</b><span>groundwater</span></div><div><b>${signed(c.energy_change_pct)}%</b><span>energy</span></div></div>` : `<p class="note">Training: ${S.rl_train.length} iterations so far.</p>`;
  const tbl = c ? `<table><thead><tr><th></th><th class="n">Fixed rule</th><th class="n">RL policy</th></tr></thead><tbody>
    <tr><td>People fed, bad year</td><td class="n">${fmt(c.rule.people_p10)}</td><td class="n">${fmt(c.policy.people_p10)}</td></tr>
    <tr><td>Groundwater, average m³</td><td class="n">${fmt(c.rule.water_mean_m3)}</td><td class="n">${fmt(c.policy.water_mean_m3)}</td></tr>
    <tr><td>Energy, average kWh</td><td class="n">${fmt(c.rule.energy_mean_kwh)}</td><td class="n">${fmt(c.policy.energy_mean_kwh)}</td></tr>
    <tr><td>Years over the water quota</td><td class="n">${c.rule.years_over_quota_pct}%</td><td class="n">${c.policy.years_over_quota_pct}%</td></tr></tbody></table>` : "";
  const note = r ? `<p class="note">${fmt(r.imagined_farm_seasons)} imagined seasons in ${r.trained_seconds} s. Evolution strategies trained a ${r.policy_parameters}-parameter network inside the scientist's model; validated on held-out imagined seasons. ${r.recommend === "rl_policy" ? "Deployed." : "Not deployed: the rule stays."}</p>` : "";
  return `<div class="rl-grid"><div>${top}<figure class="chart" style="margin:0"><figcaption>People fed per season during training, in the scientist's model</figcaption><svg id="rlCurve" viewBox="0 0 420 150"></svg></figure><div class="legend"><span class="lg model">Training seasons, average</span><span class="lg meas">Held-out seasons, bad year</span></div></div><div>${tbl}</div></div>${note}`;
}
function drawRl() {
  const svg = $("rlCurve"); if (!svg) return;
  const H = 150, W = 420, L = 34, B = 18;
  const tr = S.rl_train.filter((x) => x.iter >= 0);
  const val = (S.rl && S.rl.validation) || [];
  const ys = [...tr.map((x) => x.people), ...val.map((x) => x.val_people_p10)].filter((v) => v != null);
  if (!ys.length) return;
  const n = Math.max(10, tr.length, ...val.map((v) => v.iter));
  const [y0, y1] = nice(Math.min(...ys), Math.max(...ys));
  const X = (i) => L + (i / n) * (W - L - 6), Y = (v) => (H - B) - ((v - y0) / (y1 - y0)) * (H - B - 6);
  [y0, (y0 + y1) / 2, y1].forEach((v) => { svgEl("line", { x1: L, x2: W, y1: Y(v), y2: Y(v), stroke: "rgba(255,255,255,.08)" }, svg); svgEl("text", { x: L - 4, y: Y(v) + 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = fmt(v); });
  svgEl("path", { d: tr.map((x, k) => `${k ? "L" : "M"}${X(x.iter + 1).toFixed(1)},${Y(x.people).toFixed(1)}`).join(""), fill: "none", stroke: css("--model"), "stroke-width": 2 }, svg);
  val.forEach((v) => svgEl("circle", { cx: X(v.iter), cy: Y(v.val_people_p10), r: 4.5, fill: css("--measured") }, svg));
}
function reasoningHtml() {
  const items = streamItems();
  const hyps = S.events.filter((e) => e.kind === "hypothesis").map((e) => e.data);
  const concl = {}; S.events.filter((e) => e.kind === "conclusion").forEach((e) => (concl[e.data.hypothesis_id] = e.data.verdict));
  const src = mode === "live" ? agentName(info.agent || S.agentKind) : agentName(S.agentKind);
  return `<p style="margin:0 0 10px">Every step below comes from the run's audit ledger. Scientist: <b>${esc(src)}</b>. ${/Muse/.test(src) ? "Decisions are made by the Meta model through tool calls." : "Decisions follow a fixed scripted protocol (no language model)."} Drone image analysis is ${S.scene && Object.values(S.scene).some((s) => s.source && /SAM/i.test(s.source)) ? "SAM 3.1 with Muse Spark" : "simulated perception in this run"}.</p>
    ${hyps.length ? `<p class="inv-h">Hypotheses</p>${hyps.map((h) => `<div class="hyp ${concl[h.id] || "open"}"><span class="st">${concl[h.id] || "open"}</span><b>${h.id}</b> ${esc(h.statement)}<br><span class="note">Predicts: ${esc(h.prediction)}. Falsified if: ${esc(h.falsified_if)}</span></div>`).join("")}` : ""}
    <p class="inv-h">Activity</p><ol class="activity" style="max-height:none">${items.slice().reverse().map(({ it, t }) => `<li class="k-${it[0]}"><span>${it[1]}${it[2] || ""}</span><time>${t != null ? dayLabel(Math.min(t, D - 1)) : ""}</time></li>`).join("")}</ol>`;
}
function ledgerHtml() {
  const ev = S.events.slice(-80).reverse();
  return `<p style="margin:0 0 8px">Each entry includes the hash of the one before, so any edit breaks the chain. ${mode === "live" ? '<button class="ghost sm" id="verifyBtn" type="button">Verify ledger</button> <span id="verifyOut"></span>' : ""}</p><table><thead><tr><th class="n">#</th><th>Entry</th><th>Day</th><th>Hash</th></tr></thead><tbody>${ev.map((e) => `<tr><td class="n">${e.seq}</td><td>${esc(e.kind.replace(/_/g, " "))}</td><td>${e.t != null ? e.t : ""}</td><td class="hash">${String(e.hash).slice(0, 16)}</td></tr>`).join("")}</tbody></table>`;
}
async function verifyLedger() { const r = (await apiJson("api/verify")).data; $("verifyOut").innerHTML = r.ok ? `<span class="ok">${esc(r.message)}</span>` : `<span class="miss">${esc(r.message)}</span>`; }
async function historyHtml() {
  let d;
  try { d = (await apiJson("api/runs")).data; } catch (e) { return `<p class="empty">Could not load your seasons.</p>`; }
  if (!d.runs || !d.runs.length) return `<p class="empty">No seasons yet. Plan one to start.</p>`;
  const when = (t) => new Date(t * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return `<table><thead><tr><th>Started</th><th>Scientist</th><th>Your crops</th><th class="n">People fed</th><th class="n">XP</th><th></th></tr></thead><tbody>${d.runs.map((r) => {
    const mine = (r.choices || []).filter((c) => c.crop).map((c) => `${c.field} ${esc(c.choice)}`).join(", ") || "Scientist chose all";
    return `<tr><td>${when(r.created)}</td><td>${esc(agentName(r.agent))}</td><td>${mine}</td><td class="n">${r.result ? fmt(r.result.people_fed) : r.id === info.run_id ? "running" : "stopped"}</td><td class="n">${r.award && r.award.gained != null ? `+${fmt(r.award.gained)}` : ""}</td><td>${r.result ? `<a href="${PAGES.app}?run=${r.id}">Replay</a>` : ""}</td></tr>`;
  }).join("")}</tbody></table><p class="note">Replays never award experience again. Each farm and crop choice earns season XP once; beating your best on it earns the difference.</p>`;
}
function badgesHtml() {
  const catalog = (progress && progress.catalog) || [
    { id: "first_sprout", title: "First Sprout" }, { id: "diverse_farm", title: "Diverse Farm" }, { id: "adaptive_intelligence", title: "Adaptive Intelligence" },
    { id: "scientific_detective", title: "Scientific Detective" }, { id: "resilience_architect", title: "Resilience Architect" }, { id: "water_steward", title: "Water Steward" }, { id: "harvest_guardian", title: "Harvest Guardian" }];
  const mine = progress ? progress.achievements : {};
  const season = {}; (S.mission ? S.mission.achievements : []).forEach((a) => (season[a.id] = a));
  return `<p style="margin:0 0 10px">${progress ? `Level ${progress.level.level}, ${fmt(progress.level.xp)} XP${progress.best_people ? `, best season ${fmt(progress.best_people)} people fed` : ""}.` : "Sign up to keep achievements. Below: what the season on screen has earned."} Each one is checked against the season's audit ledger.</p>
    <div class="badges">${catalog.map((c, k) => { const on = mine[c.id] || season[c.id]; const ev = (mine[c.id] && mine[c.id].evidence) || (season[c.id] && season[c.id].evidence);
      return `<div class="badge ${on ? "on" : ""}"><span class="hex">${on ? "✓" : k + 1}</span><div><b>${esc(c.title)}</b><span>${esc(on ? ev : c.about || "")}</span></div></div>`; }).join("")}</div>`;
}

// ------------------------------------------------------------ drone feed
function renderDrone() {
  if (!$("droneTab").classList.contains("on")) return;
  const frames = S.drone, key = `${frames.length}|${dfSel}`;
  if (key === dfKey) return; dfKey = key;
  const k = dfSel >= 0 && dfSel < frames.length ? dfSel : frames.length - 1, f = frames[k];
  $("dfEmpty").hidden = !!f; $("dfImg").hidden = !f;
  if (f) {
    $("dfImg").src = f.image; $("dfImg").alt = `Drone frame of ${f.field}, ${dayLabel(f.day)}`;
    $("dfTag").textContent = f.kind === "inspection" ? `Inspection, ${f.field}` : `Survey, ${f.field}`;
    $("dfMeta").textContent = `${dayLabel(f.day)}  canopy ${fmt(f.canopy_cover_measured, 2)} vs ${fmt(f.canopy_cover_predicted, 2)} model`;
    const diag = f.diagnosis && f.diagnosis.condition ? ` Image analysis: ${String(f.diagnosis.condition).replace(/_/g, " ")}${f.source ? ` (${f.source})` : ""}.` : "";
    $("dfCap").textContent = f.kind === "inspection"
      ? `Inspection the scientist asked for: ${crop(f.crop)} in ${f.field}.${diag}`
      : `Routine survey frame: ${crop(f.crop)} in ${f.field}. Frames are rendered by the farm simulator from its true state; the canopy number is the drone's noisy measurement.`;
  }
  $("dfStrip").innerHTML = frames.slice(-14).map((x, j) => {
    const idx = frames.length - Math.min(14, frames.length) + j;
    return `<li><button type="button" data-k="${idx}" class="${idx === k ? "on" : ""}" aria-label="${x.field}, ${dayLabel(x.day)}"><img src="${x.image}" alt=""><span>${x.field} ${dayLabel(x.day)}</span></button></li>`;
  }).join("");
  $("dfStrip").querySelectorAll("button").forEach((b) => (b.onclick = () => { dfSel = Number(b.dataset.k); renderDrone(); }));
}

// ------------------------------------------------------------ the agent: its loop, tool calls and AI components
const PHASE = { observe: "Observe", get_beliefs: "Observe", advance: "Observe", record_hypothesis: "Hypothesize",
  evaluate_trials: "Experiment", run_trials: "Experiment", look_at_field: "Experiment", field_test: "Experiment",
  plan_season: "Decide", train_irrigation_policy: "Decide", start_season: "Act", set_irrigation_controller: "Act", adjust_field: "Act",
  rebalance_water: "Decide", dismiss_anomaly: "Act", fit_crop_models: "Learn", conclude: "Learn", update_model: "Learn", finish: "Learn" };
const PHASES = ["Observe", "Hypothesize", "Experiment", "Decide", "Act", "Learn"];
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
    if (d.role === "tool_call") out.push({ day: d.t, tool: d.text, args: d.args || {}, res: null });
    else if (d.role === "tool_result") { const c = [...out].reverse().find((x) => x.tool === d.text && !x.res && x.tool); if (c) c.res = d.result || {}; }
    else if (d.role === "agent" && d.text) out.push({ day: d.t, say: d.text });
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
function deciderName() {
  const k = S.agentKind || info.agent;
  return /spark|glimmer/.test(k || "") ? agentName(k) : "Scripted protocol";
}
function perceptionName() {
  const src = Object.values(S.scene || {}).map((x) => x.source).find(Boolean) || "";
  return /simulated/i.test(src) ? "Simulated perception" : src ? "SAM 3.1 + Muse Spark" : "Not used yet";
}
function loopSvg(cur) {
  const R = 86, cx = 130, cy = 104;
  const pts = PHASES.map((_, i) => { const a = -Math.PI / 2 + (i * 2 * Math.PI) / PHASES.length; return [cx + R * Math.cos(a), cy + R * Math.sin(a)]; });
  return `<svg class="loop" viewBox="0 0 260 210" role="img" aria-label="Agent loop, current step ${cur || "none"}">
    <circle class="arc" cx="${cx}" cy="${cy}" r="${R}"/>
    <text x="${cx}" y="${cy - 4}" text-anchor="middle" fill="${css("--ink-3")}" font-size="11">The scientist</text>
    <text x="${cx}" y="${cy + 12}" text-anchor="middle" fill="${css("--ink")}" font-size="12" font-weight="600">${esc(deciderName())}</text>
    ${pts.map(([x, y], i) => `<g class="node ${PHASES[i] === cur ? "on" : ""}"><circle cx="${x}" cy="${y}" r="27"/><text x="${x}" y="${y + 4}">${PHASES[i]}</text></g>`).join("")}</svg>`;
}
function agentHtml() {
  const steps = agentSteps(), calls = steps.filter((x) => x.tool);
  const last = calls[calls.length - 1], cur = last ? PHASE[last.tool] : null;
  const refused = calls.filter((c) => c.res && (c.res.refused || c.res.error)).length;
  const ld = lastDay(), ctl = (ld && ld.controller) || (S.status && S.status.controller);
  const intro = /Muse/.test(deciderName())
    ? "Muse Spark chooses every tool call below through function calling; numerical code does the agronomy."
    : "This run's decisions come from the scripted protocol, a fixed sequence over the same tools (no language model). With a MODEL_API_KEY the server hands these decisions to Muse Spark.";
  const rows = steps.slice(-60).reverse().map((x) => x.say
    ? `<tr><td class="n">${x.day ?? ""}</td><td><span class="phase">Thinks</span></td><td colspan="3">${esc(x.say)}</td></tr>`
    : `<tr><td class="n">${x.day ?? ""}</td><td><span class="phase">${PHASE[x.tool] || "Act"}</span></td><td class="tool">${esc(x.tool)}<span class="why">${esc(toolEngine(x.tool, x.res))}</span></td>
       <td>${esc(x.args.rationale || x.args.reason || x.args.statement || x.args.evidence || x.args.summary || Object.entries(x.args).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ").slice(0, 140))}</td><td>${brief(x.res)}</td></tr>`).join("");
  return `<p style="margin:0 0 10px">${intro} Every action goes through a bounded tool with budgets for trial plots, field tests, water and energy; a call outside the rules is refused and logged.</p>
    <div class="agent-top"><div>${loopSvg(cur)}</div><div>
      <div class="agent-who">
        <div><span>Decides</span><b>${esc(deciderName())}</b><span>${calls.length} tool calls so far</span></div>
        <div><span>Sees</span><b>${esc(perceptionName())}</b><span>${S.drone.length} drone frames</span></div>
        <div><span>Irrigates</span><b>${ctl === "rl_policy" ? "RL policy" : ctl ? "Fixed rule" : "Not started"}</b><span>${refused} refused call${refused === 1 ? "" : "s"}</span></div>
      </div>
      <p class="note" style="margin:0">The loop: observe the farm, write a testable hypothesis, run the experiment that tells explanations apart, decide, act, and learn by correcting the model. The highlighted step is the latest tool call.</p>
    </div></div>
    <table class="trace"><thead><tr><th class="n">Day</th><th>Step</th><th>Tool and engine</th><th>Why</th><th>Result</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="empty">No tool calls yet.</td></tr>`}</tbody></table>`;
}
function componentsHtml() {
  const llm = /Muse/.test(deciderName()), perc = perceptionName(), ctl = (lastDay() && lastDay().controller) || "";
  const used = (on, label) => `<span class="src ${on ? "on" : "rule"}">${esc(label)}</span>`;
  const rows = [
    ["Muse Spark", "meta", "Meta model", "The scientist: decides the next step by calling tools", "Reads the farm state and tool results, writes hypotheses and calls its 19 tools by function calling", used(llm && /Spark/.test(deciderName()), llm && /Spark/.test(deciderName()) ? "Deciding this run" : "Needs MODEL_API_KEY")],
    ["Muse Glimmer", "meta", "Meta open weights", "The same scientist on your own GPU", "Any OpenAI-compatible endpoint serving Glimmer, same tools and prompt", used(/Glimmer/.test(deciderName()), /Glimmer/.test(deciderName()) ? "Deciding this run" : "Needs a Glimmer endpoint")],
    ["SAM 3.1", "meta", "Meta model", "Reads drone images", "Segments green plants, white salt crust and brown leaf damage by text prompt; counts and areas feed the diagnosis", used(perc === "SAM 3.1 + Muse Spark", perc === "SAM 3.1 + Muse Spark" ? "Used this run" : "Simulated in this run")],
    ["Muse Spark vision", "meta", "Meta model", "Diagnoses crop stress from the same image", "Returns a structured diagnosis: healthy, water, salt or pest stress, gaps, with its evidence", used(perc === "SAM 3.1 + Muse Spark", perc === "SAM 3.1 + Muse Spark" ? "Used this run" : "Simulated in this run")],
    ["Scripted protocol", "rule", "Rules", "Baseline and fallback scientist", "A fixed sequence over the same tools; the comparison the language model must beat", used(!llm, !llm ? "Deciding this run" : "Standing by")],
    ["Experiment design", "num", "Numerical", "Chooses which trial plots to plant", "Scores candidate plots by expected information about the traits that move the plan", used(true, "Used before sowing")],
    ["Bayesian calibration", "num", "Numerical", "Learns each crop's hidden traits", "MAP fit of water productivity, canopy growth, heat and salt tolerance from trial harvests and drone canopy", used(true, "Used after trials")],
    ["Digital twin", "num", "Numerical", "Predicts every field with uncertainty", "An ensemble of the crop and soil model run beside the farm, giving the 90% bands in the charts", used(true, "Running all season")],
    ["Anomaly detector", "num", "Numerical", "Notices when reality leaves the prediction", "CUSUM on measured minus predicted soil moisture, salinity and canopy; it pauses the season", used(true, "Watching all season")],
    ["Robust planner", "num", "Numerical", "Plans crops, sowing, irrigation, blend and nitrogen", "Maximises people fed in a bad year (10th percentile) within the water quota and energy budget", used(true, "Used to plan and re-plan")],
    ["Reinforcement learning", "num", "Numerical", "Learns a daily irrigation policy", "Evolution strategies train a small neural network inside the agent's own model; deployed only if it beats the rule on held-out seasons", used(ctl === "rl_policy", ctl === "rl_policy" ? "Irrigating now" : S.rl ? "Trained, not deployed" : "Not trained yet")],
    ["Audit ledger", "rule", "Integrity", "Makes every step checkable", "A hash-chained log of each hypothesis, prediction, test, decision and result; missions and achievements are scored from it", used(true, `${S.events.length} entries`)],
  ];
  return `<p style="margin:0 0 10px">What each part of WorldLab's AI does, and whether it is active in the season on screen. Meta models decide and perceive; numerical code does the agronomy and the learning; nothing claims a reading or a diagnosis the ledger doesn't hold.</p>
    <table class="ai-table"><thead><tr><th>Component</th><th>Kind</th><th>Role</th><th>How it works</th><th>This season</th></tr></thead><tbody>
    ${rows.map(([n, cls, kind, role, how, st]) => `<tr><td>${n}</td><td><span class="src ${cls}">${kind}</span></td><td>${role}</td><td>${how}</td><td>${st}</td></tr>`).join("")}</tbody></table>`;
}

// ------------------------------------------------------------ toasts and achievements
function toast(title, body, ms = 5200) {
  const t = document.createElement("div"); t.className = "toast";
  t.innerHTML = `<span class="hex" aria-hidden="true"></span><div><b>${esc(title)}</b><span>${esc(body)}</span></div>`;
  $("toasts").appendChild(t); setTimeout(() => t.remove(), ms);
}
function badgeToasts(m) {
  (m.achievements || []).forEach((a) => { if (!seenBadges.has(a.id)) { seenBadges.add(a.id); toast(`Achievement: ${a.title}`, a.evidence); } });
}

// ------------------------------------------------------------ results
function showResults() {
  const res = S.status && S.status.result, m = S.mission;
  if (!res || resultsShownFor === S.events.length) return;
  resultsShownFor = S.events.length;
  if (scene) scene.event("season_result", {});
  const mt = m ? m.metrics : {}, plan = S.plan;
  const faults = (mt.faults || []).map((f) => `<li>${esc(cap(f.label))} in ${esc(f.field)}: ${f.detected ? `detected on ${dayLabel(f.detected_day)}` : "not detected"}${f.diagnosed ? ", cause identified" : ""}${f.recovered ? ", repaired or corrected" : ""}</li>`).join("");
  const award = S.award;
  const xp = award ? award.lines : m ? m.xp_items : [];
  $("resTitle").textContent = `${fmt(res.people_fed)} people fed`;
  $("resBody").innerHTML = `
    <div class="res-kpis"><div><b>${fmt(res.people_fed)}</b><span>people fed for a year${plan ? `, plan said ${fmt(plan.people_p10)} in a bad year` : ""}</span></div>
    <div><b>${fmt(res.water_used_m3)}</b><span>m³ groundwater ${res.within_quota ? "(within quota)" : "(over quota)"}</span></div>
    <div><b>${mt.water_m3_per_person ? fmt(mt.water_m3_per_person, 1) : "–"}</b><span>m³ per person fed</span></div>
    <div><b>${fmt(res.energy_used_kwh)}</b><span>kWh ${res.within_energy ? "(within budget)" : "(over budget)"}</span></div></div>
    <div class="res-crops">${(mt.crops || []).map((c) => { const pic = portrait(c, 3, 60); return `<span>${pic ? `<img src="${pic}" alt="">` : ""}${esc(crop(c))}</span>`; }).join("")}</div>
    <p>Limited by ${NUTRIENT[res.limiting] || res.limiting}.</p>
    ${faults ? `<p class="inv-h">Faults this season</p><ul>${faults}</ul>` : ""}
    ${m && m.achievements.length ? `<p class="inv-h">Achievements earned</p><div class="badges">${m.achievements.map((a) => `<div class="badge on"><span class="hex">✓</span><div><b>${esc(a.title)}</b><span>${esc(a.evidence)}</span></div></div>`).join("")}</div>` : ""}
    ${xp && xp.length ? `<p class="inv-h">${award ? `Experience earned: +${fmt(award.gained)} XP` : "Experience this season is worth (recorded season, not saved)"}</p><ul class="xp-lines">${xp.map((l) => `<li><span>${esc(l.label)}</span><b>+${fmt(l.xp)}</b></li>`).join("")}</ul>` : ""}`;
  $("results").hidden = false;
  $("resPlan").hidden = mode !== "live";
  $("resReplay").hidden = mode !== "replay";
}

// ------------------------------------------------------------ season planner
const SEASON_COLORS = { autumn: "var(--s-autumn)", winter: "var(--s-winter)", late_winter: "var(--s-late_winter)" };
const P = { data: null, season: "autumn", brush: null, picks: FIELD_IDS.map(() => ({ mode: "scientist" })) };
async function openPlanner() {
  if (!P.data) {
    try { P.data = await (await fetch(new URL(PAGES.home + "seasons.json", location.href))).json(); } catch (e) { toast("Planner unavailable", "Could not load the crop guide."); return; }
  }
  closeDrawer(); $("inspector").hidden = true;
  document.body.classList.add("planning");
  $("planner").hidden = false; $("plErr").hidden = true;
  ["missionPanel", "impactPanel", "dock", "viewbar"].forEach((id) => ($(id).style.visibility = "hidden"));
  renderSeasonTabs(); renderCards(); renderFieldRows(); preview();
  $("startBtn").textContent = mode === "live" ? "Start the season" : serverUp ? "Sign up to grow this plan" : "Start the season";
  if (scene) scene.view("overview");
}
function closePlanner() {
  $("planner").hidden = true; document.body.classList.remove("planning");
  ["missionPanel", "impactPanel", "dock", "viewbar"].forEach((id) => ($(id).style.visibility = ""));
  if (scene) { scene.setFields(fieldsNow()); const ld = lastDay(); if (ld) scene.update(ld); scene.home(); }
}
const seasonLabel = (id) => { const x = P.data && P.data.seasons.find((s) => s.id === id); return x ? x.label : id; };
function renderSeasonTabs() {
  $("seasonTabs").innerHTML = P.data.seasons.map((x) => `<button role="tab" type="button" data-s="${x.id}" class="${x.id === P.season ? "on" : ""}" aria-selected="${x.id === P.season}" style="--c:${SEASON_COLORS[x.id]}"><span class="dot"></span>${esc(x.label)}</button>`).join("")
    + `<button class="rest" type="button" disabled title="${esc(P.data.summer.about)}">Summer: fields rest</button>`;
  $("seasonTabs").querySelectorAll("button[data-s]").forEach((b) => (b.onclick = () => { P.season = b.dataset.s; P.brush = null; renderSeasonTabs(); renderCards(); renderFieldRows(); }));
  $("seasonAbout").textContent = P.data.seasons.find((s) => s.id === P.season).about;
}
function guideFor(season) { const g = P.data.guides && P.data.guides[season]; return g ? g.crops : []; }
function renderCards() {
  const crops = guideFor(P.season);
  $("plHint").textContent = P.brush ? `Click fields in the 3D view or the list to sow ${crop(P.brush)}. Click the card again when you're done.` : "Each card: sowing window, days to harvest, needs covered, salt limit, and expected yield on each field (published values, typical management).";
  $("cropCards").innerHTML = crops.map((c) => {
    const cmax = Math.max(...c.fields.map((f) => f.yield_t_ha_p50), 0.1);
    const needs = c.good_for.map((n) => `<span class="need ${n === "protein" ? "p" : n === "vitamin A" ? "v" : ""}">${esc(n)}</span>`).join("");
    return `<button type="button" class="crop-card ${P.brush === c.crop ? "on" : ""}" data-c="${c.crop}" aria-pressed="${P.brush === c.crop}">
      <span class="cc-head">${portrait(c.crop, 2, 88) ? `<img class="crop-pic" src="${portrait(c.crop, 2, 88)}" alt="${esc(c.label)}, rendered from its 3D model">` : ""}<h4>${esc(c.label)}<span>${c.cycle_days ? `${c.cycle_days} days` : ""}</span></h4></span>
      <span class="meta">Sow ${esc(c.sow_window_label)}${c.harvest_label ? `; harvest around ${esc(c.harvest_label)}` : ""}</span>
      <span class="needs">${needs}<span class="need salt">salt limit ${c.salt_threshold_ds_m} dS/m</span></span>
      <span class="yields">${c.fields.map((f) => `<span><i><b style="height:${Math.round((100 * f.yield_t_ha_p50) / cmax)}%"></b></i>${f.field}<br>${fmt(f.yield_t_ha_p50, f.yield_t_ha_p50 < 10 ? 1 : 0)}</span>`).join("")}</span>
    </button>`;
  }).join("") || `<p class="note">No crop on the list is sown in this season.</p>`;
  $("cropCards").querySelectorAll(".crop-card").forEach((b) => (b.onclick = () => { P.brush = P.brush === b.dataset.c ? null : b.dataset.c; renderCards(); renderFieldRows(); }));
}
function renderFieldRows() {
  const inSeason = guideFor(P.season).map((c) => c.crop);
  $("fieldRows").innerHTML = FIELD_IDS.map((id, i) => {
    const p = P.picks[i];
    const tag = p.mode === "crop" ? `<span class="sz" style="--c:${SEASON_COLORS[p.season]}">${esc(seasonLabel(p.season))}</span>` : "";
    let ctl;
    if (P.brush) {
      const here = p.mode === "crop" && p.crop === P.brush && p.season === P.season;
      ctl = `<button type="button" class="${here ? "ghost" : "primary"} sm sow" data-i="${i}">${here ? `Remove ${esc(crop(P.brush))}` : `Sow ${esc(crop(P.brush))} here`}</button>`;
    } else {
      const opts = [`<option value="scientist" ${p.mode === "scientist" ? "selected" : ""}>Scientist decides</option>`, `<option value="fallow" ${p.mode === "fallow" ? "selected" : ""}>Leave fallow</option>`];
      if (p.mode === "crop" && (p.season !== P.season || !inSeason.includes(p.crop))) opts.push(`<option value="keep" selected>${esc(crop(p.crop))}, ${esc(seasonLabel(p.season).toLowerCase())}</option>`);
      inSeason.forEach((c) => opts.push(`<option value="c:${c}" ${p.mode === "crop" && p.crop === c && p.season === P.season ? "selected" : ""}>${esc(crop(c))}, ${esc(seasonLabel(P.season).toLowerCase())}</option>`));
      ctl = `<select aria-label="Crop for ${id}" data-i="${i}">${opts.join("")}</select>`;
    }
    return `<li class="pl-row ${P.brush ? "hot" : ""}"><span class="fid">${id}</span><span class="soil">${NAMES[i]}, ${SOILS[i]}</span><span class="pick">${p.mode === "crop" && portrait(p.crop, 2, 56) ? `<img class="pick-pic" src="${portrait(p.crop, 2, 56)}" alt="">` : ""}${ctl}${tag}</span></li>`;
  }).join("");
  $("fieldRows").querySelectorAll("select").forEach((s) => (s.onchange = () => {
    const i = Number(s.dataset.i), v = s.value;
    if (v === "scientist" || v === "fallow") P.picks[i] = { mode: v };
    else if (v.startsWith("c:")) P.picks[i] = { mode: "crop", crop: v.slice(2), season: P.season };
    renderFieldRows(); preview();
  }));
  $("fieldRows").querySelectorAll("button.sow").forEach((b) => (b.onclick = () => brushField(Number(b.dataset.i))));
}
function brushField(i) {
  if (!P.brush) return;
  const p = P.picks[i];
  P.picks[i] = p.mode === "crop" && p.crop === P.brush && p.season === P.season ? { mode: "scientist" } : { mode: "crop", crop: P.brush, season: P.season };
  renderFieldRows(); preview();
}
function preview() { if (scene) scene.previewPlan(P.picks.map((p) => (p.mode === "crop" ? { crop: p.crop, label: crop(p.crop) } : { fallow: p.mode === "fallow" }))); }
async function startSeason() {
  if (mode !== "live") {
    if (serverUp) { go("signup"); return; }
    $("plErr").textContent = "Running a season needs the WorldLab server, which isn't reachable from here. Run it yourself from the source to grow this plan."; $("plErr").hidden = false; return;
  }
  const btn = $("startBtn"); btn.disabled = true; $("plErr").hidden = true;
  try {
    const r = await apiJson("api/start", { method: "POST", body: { agent: $("agentSel").value, speed: Number($("speed").value), choices: P.picks } });
    if (r.status === 401) { go("login", `?next=${encodeURIComponent(PAGES.app)}`); return; }
    if (!r.ok || !r.data.ok) throw new Error(r.data.error || "The season could not start.");
    closePlanner(); $("modeNote").textContent = ""; seenBadges = new Set();
  } catch (e) { $("plErr").textContent = e.message; $("plErr").hidden = false; }
  finally { btn.disabled = false; }
}

// ------------------------------------------------------------ live mode
async function post(path, body) { return (await apiJson(path, { method: "POST", body: body || {} })).data; }
async function loadProgress() { try { const r = await apiJson("api/progress"); if (r.ok) { progress = r.data; dirty = true; } } catch (e) { /* offline */ } }
async function startLive(state) {
  mode = "live";
  info = state.info || {};
  $("liveControls").hidden = false;
  $("profileName").textContent = info.user ? `${info.user.name} (${info.user.email})` : "Signed in";
  $("loginLink").hidden = true;
  const opt = $("agentSel").querySelector('option[value="spark"]');
  if (!info.has_api_key) { opt.textContent = "Muse Spark (needs MODEL_API_KEY on the server)"; opt.disabled = true; }
  $("agentSel").querySelector('option[value="glimmer"]').textContent = "Muse Glimmer (needs a Glimmer endpoint)";
  if (info.agent && [...$("agentSel").options].some((o) => o.value === info.agent && !o.disabled)) $("agentSel").value = info.agent;
  $("speed").value = info.speed || 12;
  S = { ...fresh(), ...state, events: state.events || [], agentKind: info.agent };
  delete S.info; delete S.agent; delete S.beliefs_hist;
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
    const r = await apiJson("api/state");
    if (r.ok) { S = { ...fresh(), ...r.data, events: r.data.events || [], agentKind: info.agent }; delete S.info; delete S.agent; delete S.beliefs_hist; sceneSync(); dirty = true; }
  });
  if (!info.running && !(S.status && S.status.phase)) { $("modeNote").textContent = "Your farm is ready. Plan a season to start."; if (!store.get("wl-toured", false)) startTour(); else openPlanner(); }
}
function setRunning(on) { $("planBtn").textContent = on ? "Plan a different season" : "Plan a new season"; $("stopBtn").hidden = !on; dirty = true; }

// ------------------------------------------------------------ replay mode
const R = { msgs: [], pt: [], idx: 0, pos: 0, total: 0, playing: false, rate: 1 };
function beat(m) {
  if (m.kind === "day") return 0.13;
  if (m.kind === "rl_train") return 0.05;
  if (m.kind === "trials") return 0.32;
  if (m.kind === "perturbation") return 0.8;
  if (m.kind === "ledger") return streamItem(m.data) ? (m.data.kind === "anomaly" ? 2.2 : m.data.kind === "season_result" ? 2 : 0.55) : 0;
  return 0;
}
function buildTimeline(msgs) { let t = 0; R.pt = msgs.map((m) => (t += beat(m))); R.total = t + 0.5; }
function seek(pos) {
  if (pos < R.pos || pos - R.pos > 3) {
    if (pos < R.pos) { S = fresh(); R.idx = 0; seenBadges = new Set(); }
    while (R.idx < R.msgs.length && R.pt[R.idx] <= pos) apply(R.msgs[R.idx++], false);
    R.pos = pos; sceneSync();
    (S.mission ? S.mission.achievements : []).forEach((a) => seenBadges.add(a.id));
  } else {
    while (R.idx < R.msgs.length && R.pt[R.idx] <= pos) apply(R.msgs[R.idx++], true);
    R.pos = pos;
  }
  dirty = true;
}
async function startReplay(url) {
  mode = "replay";
  const res = url.startsWith("api/") ? await api(url) : await fetch(url);
  if (!res.ok) throw new Error(`${res.status}`);
  const data = await res.json();
  R.msgs = data.messages || data;
  buildTimeline(R.msgs);
  S.agentKind = (data.meta && data.meta.agent) || null;
  $("replayControls").hidden = false; $("scrub").hidden = false;
  $("modeNote").textContent = data.meta && data.meta.note ? data.meta.note : "Recorded season. Decisions, predictions and measurements replay exactly as logged.";
  $("playBtn").onclick = togglePlay;
  $("rate").onchange = () => (R.rate = Number($("rate").value));
  $("scrub").oninput = () => seek((Number($("scrub").value) / 1000) * R.total);
  let last = performance.now();
  const tick = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (R.playing) {
      seek(Math.min(R.total, R.pos + dt * R.rate));
      $("scrub").value = String(Math.round((1000 * R.pos) / Math.max(R.total, 1e-6)));
      if (R.pos >= R.total) { R.playing = false; $("playBtn").textContent = "Watch again"; if (S.status && S.status.result) showResults(); }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  if (!store.get("wl-toured", false) && !reducedMotion) startTour(); else setTimeout(() => { if (!R.playing && R.pos === 0) togglePlay(); }, reducedMotion ? 0 : 2600);
}
function togglePlay() {
  if (mode !== "replay") return;
  R.playing = !R.playing;
  if (R.playing && R.pos >= R.total) { $("results").hidden = true; seek(0); }
  $("playBtn").textContent = R.playing ? "Pause" : "Play"; dirty = true;
}

// ------------------------------------------------------------ guided tour
const TOUR = [
  ["#stage", "This farm is real geometry", "Six fields near Al Ain, drip-irrigated from brackish groundwater. Drag to orbit, scroll to zoom. Everything you see grows and changes with the simulation.", "center"],
  ["#gauges", "Inspect a field", "Each ring is one field. Click one (or a field in 3D) to fly there and open its sensor charts: the model's 90% band against what the sensors measure."],
  ["#missionPanel", "Your missions", "Discover, Strategize, Survive, Recover, Harvest. Objectives tick off only when the season's audit ledger shows they happened."],
  ["#impactPanel", "Watch the AI scientist", "It designs trial plots, calibrates its crop model, plans, trains an irrigation policy, and investigates anything its model can't explain."],
  ["#dock", "Advance the season", "The season runs from 1 October to 30 June. The timeline marks hidden changes, alarms and harvests."],
  ["#viewbar", "See what the sensors see", "Switch from the realistic view to scientific overlays: crop health, soil moisture, salinity and irrigation, with units."],
  ["#droneTab", "Drone feed", "The drone's live camera in the 3D farm, beside the frames it captures on survey and inspection flights."],
  ["#navAgent", "Follow the agent", "Every tool call the scientist makes, where it is in its loop, and a table of all the AI components."],
  ["#impactPanel .lives", "The outcome that matters", "People fed for a year, counting only those whose calories, protein and vitamin A are all covered."],
];
let tourStep = -1;
function startTour() { tourStep = 0; $("tour").hidden = false; showTour(); }
function endTour() { $("tour").hidden = true; tourStep = -1; store.set("wl-toured", true); if (mode === "replay" && !R.playing && R.pos === 0) togglePlay(); if (mode === "live" && !info.running && !(S.status && S.status.phase)) openPlanner(); }
function showTour() {
  const [selq, title, body, where] = TOUR[tourStep];
  const el = document.querySelector(selq);
  const r = el && where !== "center" ? el.getBoundingClientRect() : { left: innerWidth / 2 - 180, top: innerHeight / 2 - 120, width: 360, height: 200 };
  const hole = $("tourHole");
  Object.assign(hole.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
  const card = $("tourCard");
  card.innerHTML = `<h3>${esc(title)}</h3><p>${esc(body)}</p><div class="tc-foot"><span>${tourStep + 1} of ${TOUR.length}</span><span><button class="ghost sm" type="button" id="tourSkip">Skip</button> <button class="primary sm" type="button" id="tourNext">${tourStep === TOUR.length - 1 ? "Start" : "Next"}</button></span></div>`;
  const cw = 320, ch = card.offsetHeight || 170;
  let x = r.left + r.width + 16, y = r.top;
  if (x + cw > innerWidth - 10) x = r.left - cw - 16;
  if (x < 10) { x = Math.max(10, Math.min(innerWidth - cw - 10, r.left)); y = r.top + r.height + 16; }
  if (y + ch > innerHeight - 10) y = Math.max(10, r.top - ch - 16);
  Object.assign(card.style, { left: `${x}px`, top: `${y}px` });
  $("tourNext").onclick = () => { tourStep++; if (tourStep >= TOUR.length) endTour(); else showTour(); };
  $("tourSkip").onclick = endTour;
  $("tourNext").focus();
}

// ------------------------------------------------------------ boot
async function loadScene() {
  try {
    const mod = await import("./scene.js?v=b2e635c2ae");
    OV = mod.OVERLAYS || {};
    if (mod.cropPortrait) { portrait = mod.cropPortrait; stageOf = mod.stageOf; }
    scene = mod.createScene($("stage"), {
      onSelect: (i, src) => { if ($("planner").hidden) select(i, true); else if (P.brush) brushField(i); else select(i, false); },
      reducedMotion, quality: store.get("wl-quality", "auto"), time: store.get("wl-time", "golden"),
      onFps: (f, q) => { $("fpsTxt").textContent = `${Math.round(f)} frames per second at ${q} quality${scene && scene.isAuto() ? " (auto)" : ""}`; },
      onQuality: (q, auto) => { $("qualitySel").value = auto ? "auto" : q; },
    });
    window.__wlScene = scene;
    if (scene.droneView) scene.droneView($("droneLive"));
  } catch (e) {
    console.warn("3D view unavailable:", e);
    $("noGL").hidden = false;
    $("droneLive").insertAdjacentHTML("afterend", `<p class="df-empty">The live drone camera needs the 3D view.</p>`); $("noGLWhy").textContent = String(e && e.message || e).includes("WebGL") ? "This browser has no WebGL." : "It needs WebGL and access to cdn.jsdelivr.net.";
  }
}
function wireUi() {
  document.querySelectorAll(".home-link").forEach((a) => (a.href = PAGES.home));
  $("demoCta").href = PAGES.signup;
  $("loginLink").href = PAGES.login;
  document.querySelectorAll("[data-collapse]").forEach((b) => (b.onclick = () => { const p = $(b.dataset.collapse); p.classList.toggle("collapsed"); b.textContent = p.classList.contains("collapsed") ? "+" : "–"; }));
  document.querySelectorAll(".dock-tabs [data-dt]").forEach((b) => (b.onclick = () => {
    document.querySelectorAll(".dock-tabs [data-dt]").forEach((x) => x.classList.toggle("on", x === b));
    document.querySelectorAll(".dt-pane").forEach((p) => (p.hidden = p.dataset.pane !== b.dataset.dt));
    $("dock").classList.remove("collapsed");
    if (b.dataset.dt === "drone") { $("droneDot").hidden = true; dfKey = ""; renderDrone(); }
  }));
  document.querySelectorAll("#metricTabs button").forEach((b) => (b.onclick = () => { metric = b.dataset.m; document.querySelectorAll("#metricTabs button").forEach((x) => x.classList.toggle("on", x === b)); dirty = true; }));
  document.querySelectorAll("[data-cam]").forEach((b) => (b.onclick = () => scene && (b.dataset.cam === "home" ? scene.home() : scene.view(b.dataset.cam))));
  document.querySelectorAll("[data-ov]").forEach((b) => (b.onclick = () => setOverlay(b.dataset.ov)));
  $("fiClose").onclick = () => { $("inspector").hidden = true; sel = -1; if (scene) scene.setSelected(-1); };
  $("fiFocus").onclick = () => scene && scene.focus(sel, "field");
  $("fiClose2").onclick = () => scene && scene.focus(sel, "closeup");
  $("fiDrone").onclick = () => { if (scene) { scene.scan(sel); scene.view("drone"); } };
  $("invClose").onclick = () => { const inc = currentIncident(); invClosedFor = inc ? inc.a.seq : null; dirty = true; };
  $("incidentFocus").onclick = () => { const inc = currentIncident(); if (!inc) return; if (scene) scene.focus(inc.a.data.field_index, "incident"); select(inc.a.data.field_index); invClosedFor = null; dirty = true; };
  $("navMissions").onclick = () => { const p = $("missionPanel"); p.classList.remove("collapsed"); p.scrollIntoView({ block: "nearest" }); p.animate([{ boxShadow: "0 0 0 2px var(--emerald)" }, { boxShadow: "var(--shadow)" }], { duration: 900 }); };
  $("navResearch").onclick = () => (drawer === "research" ? closeDrawer() : openDrawer("research"));
  $("navAgent").onclick = () => (drawer === "agent" ? closeDrawer() : openDrawer("agent"));
  $("navSim").onclick = closeDrawer;
  $("drawerClose").onclick = closeDrawer;
  $("reasoningBtn").onclick = () => openDrawer("reasoning");
  $("xpPill").onclick = () => openDrawer("badges");
  $("badgesBtn").onclick = () => { pop(null); openDrawer("badges"); };
  $("historyBtn").onclick = () => { pop(null); if (mode === "live") openDrawer("history"); else go("login"); };
  $("logoutBtn").onclick = async () => { await post("api/auth/logout").catch(() => {}); setToken(null); go("home"); };
  $("settingsBtn").onclick = () => pop("settings");
  $("profileBtn").onclick = () => pop("profile");
  $("qualitySel").value = store.get("wl-quality", "auto");
  $("qualitySel").onchange = () => { store.set("wl-quality", $("qualitySel").value); if (scene) { scene.setQuality($("qualitySel").value); sceneSync(); } };
  $("timeSel").value = store.get("wl-time", "golden");
  $("timeSel").onchange = () => { store.set("wl-time", $("timeSel").value); scene && scene.setTime($("timeSel").value); };
  $("labelsChk").onchange = () => scene && scene.setLabels($("labelsChk").checked);
  $("tourBtn").onclick = () => { pop(null); startTour(); };
  $("plannerClose").onclick = closePlanner;
  $("tryPlanBtn").onclick = () => { if (R.playing) togglePlay(); openPlanner(); };
  $("startBtn").onclick = startSeason;
  $("resClose").onclick = () => ($("results").hidden = true);
  $("resPlan").onclick = () => { $("results").hidden = true; openPlanner(); };
  $("resReplay").onclick = () => { $("results").hidden = true; R.playing = false; seek(0); togglePlay(); };
  document.addEventListener("keydown", onKey);
  document.addEventListener("click", (e) => { if (!e.target.closest(".popover,#settingsBtn,#profileBtn")) pop(null); });
}
function pop(id) { ["settings", "profile"].forEach((k) => { $(k).hidden = k !== id || !$(k).hidden; }); $("settingsBtn").setAttribute("aria-expanded", String(!$("settings").hidden)); $("profileBtn").setAttribute("aria-expanded", String(!$("profile").hidden)); }
function setOverlay(k) { overlay = k || ""; document.querySelectorAll("[data-ov]").forEach((b) => b.classList.toggle("on", b.dataset.ov === overlay)); if (scene) scene.setOverlay(overlay || null); dirty = true; }
function onKey(e) {
  if (e.target.closest("input,select,textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (!$("tour").hidden) { if (e.key === "Escape") endTour(); return; }
  const k = e.key.toLowerCase();
  if (k >= "1" && k <= "6") { select(Number(k) - 1, true); }
  else if (k === "o") scene && scene.view("overview");
  else if (k === "d") scene && scene.view("drone");
  else if (k === "r") scene && scene.home();
  else if (k === "i" && sel >= 0) scene && scene.focus(sel, "closeup");
  else if (k === "v") { const order = ["", "health", "moisture", "salinity", "water"]; setOverlay(order[(order.indexOf(overlay) + 1) % order.length]); }
  else if (k === " " && mode === "replay") { e.preventDefault(); togglePlay(); }
  else if (k === "escape") { if (!$("results").hidden) $("results").hidden = true; else if (!$("planner").hidden) closePlanner(); else if (drawer) closeDrawer(); else if (!$("inspector").hidden) $("fiClose").click(); }
  else return;
}

async function boot() {
  wireUi();
  await loadScene();
  const q = new URLSearchParams(location.search);
  const isDemo = /\/demo\/?$/.test(location.pathname) || q.has("demo");
  let replay = q.get("replay") || window.WORLDLAB_REPLAY || (isDemo ? "replay.json" : null);
  if (q.get("run")) replay = `api/runs/${encodeURIComponent(q.get("run"))}/replay`;
  let state = null;
  if (!replay) {
    try {
      const r = await api("api/state");
      if (r.status === 401) { go("login", `?next=${encodeURIComponent(PAGES.app)}`); return; }
      if (r.ok && (r.headers.get("Content-Type") || "").includes("json")) state = await r.json();
    } catch (e) { /* static hosting */ }
  }
  if (state) await startLive(state);
  else {
    let server = false;
    try { const m = await api("api/me"); server = serverUp = m.status === 200 || m.status === 401; if (m.status === 200) { $("profileName").textContent = (await m.json()).user.name; $("loginLink").hidden = true; } } catch (e) { /* no server */ }
    if (!server) { $("demoCta").href = "https://github.com/MoAmrYehia/WorldLab#quick-start"; $("demoCta").textContent = "Run your own season"; $("logoutBtn").hidden = true; $("historyBtn").hidden = true; }
    if (q.get("run")) $("demoCta").outerHTML = `<a class="ghost" href="${PAGES.app}">Back to your farm</a>`;
    await startReplay(replay || "replay.json").catch((e) => { $("modeNote").textContent = `No live server and no recording found (${e.message}).`; });
  }
  const loop = () => { render(); requestAnimationFrame(loop); };
  loop();
}
boot();
