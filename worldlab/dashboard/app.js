// WorldLab web app: live run (Python backend over SSE) or recorded replay (static replay.json).
const $ = (id) => document.getElementById(id);
const D = 273;
const CROP_LABEL = { wheat: "Wheat", rice: "Rice", maize: "Maize", potato: "Potatoes", cassava: "Cassava", soybean: "Soybeans",
  sorghum: "Sorghum", millet: "Millet", beans: "Common beans", sweet_potato: "Sweet potatoes" };
const NUTRIENT = { kcal: "calories", protein_g: "protein", vitA_ug: "vitamin A" };
const TRAIT = { wp: "Water productivity", cgc: "Canopy growth", heat: "Heat tolerance", salt: "Salt tolerance" };
const FIELD_IDS = ["F1", "F2", "F3", "F4", "F5", "F6"];
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

const fresh = () => ({ days: [], events: [], perturbations: [], beliefs: null, projections: [], trials: [], scene: {},
  plan: null, status: {}, fields: null, rl_train: [], rl: null, agentKind: null });
let S = fresh();
let sel = 1;                 // selected field index
let scene = null;
let mode = "live";
let info = {};
let drawerTab = null, drawerUserClosed = new Set();
let dirty = true;

// ------------------------------------------------------------ helpers
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "–" : Number(x).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
function dayLabel(d) { const dt = new Date(Date.UTC(2026, 9, 1) + d * 864e5); return dt.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" }); }
const crop = (c) => CROP_LABEL[c] || (c ? c : "Fallow");
const NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }
function nice(lo, hi) { if (!(hi > lo)) { hi = lo + 1; } const pad = (hi - lo) * 0.08; return [lo - pad, hi + pad]; }
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function fieldIndex(id) { return FIELD_IDS.indexOf(String(id || "").toUpperCase()); }
function lastProj() { return S.projections[S.projections.length - 1]; }
function lastDay() { return S.days[S.days.length - 1]; }
function fieldsNow() {
  if (S.fields) return S.fields;
  if (S.plan && S.plan.fields) return S.plan.fields.map((f, i) => ({ id: f.field || FIELD_IDS[i], crop: f.crop, label: crop(f.crop), planned: true, sow: f.mgmt && f.mgmt.sow }));
  return FIELD_IDS.map((id) => ({ id, crop: null, label: "Not planned" }));
}

// ------------------------------------------------------------ reducer
function apply(m, live = true) {
  const d = m.data;
  switch (m.kind) {
    case "reset": S = fresh(); S.agentKind = d && d.agent; if (live && scene) scene.reset(); break;
    case "day": S.days.push(d); if (live && scene) { scene.update(d); const k = d.fields.findIndex((f) => f.cc_obs != null); if (k >= 0 && d.day % 8 === 3) scene.hover(k); } break;
    case "ledger": S.events.push(d); if (S.events.length > 4000) S.events.splice(0, 500); break;
    case "perturbation": S.perturbations.push({ ...d, _order: S.events.length }); break;
    case "beliefs": S.beliefs = d; break;
    case "projection": S.projections.push(d); break;
    case "trials": S.trials.push(d); if (live && scene) scene.addTrial(d); if (live) autoOpen("trials"); break;
    case "scene": S.scene[d.field] = d; if (live && scene) scene.scan(fieldIndex(d.field)); break;
    case "plan": S.plan = d; if (live && scene && !S.fields) scene.setFields(fieldsNow()); break;
    case "status": { const prev = S.status && S.status.anomaly; S.status = d;
      if (live && scene) syncAnomaly();
      if (live && d.anomaly && (!prev || prev.detected_day !== d.anomaly.detected_day)) { sel = d.anomaly.field_index; if (scene) scene.setSelected(sel); }
      break; }
    case "fields": S.fields = d; if (live && scene) scene.setFields(d); break;
    case "rl_train": if (d.reset) S.rl_train = []; else S.rl_train.push(d); if (live) autoOpen("rl"); break;
    case "rl": S.rl = d; break;
    case "agent": break;
  }
  dirty = true;
}

function syncAnomaly() {
  const a = S.status && S.status.anomaly;
  scene.setAnomaly(a ? a.field_index : -1, a ? `${cap(a.signal_label)} ${a.direction}` : "");
}
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");

function sceneSync() {
  if (!scene) return;
  scene.reset();
  scene.setFields(fieldsNow());
  S.trials.forEach((t) => scene.addTrial(t));
  const ld = lastDay(); if (ld) scene.update(ld);
  syncAnomaly();
  scene.setSelected(sel);
}

function autoOpen(tab) {
  if (drawerTab || drawerUserClosed.has(tab) || window.innerWidth < 860) { markFresh(tab); return; }
  openDrawer(tab);
}
function markFresh(tab) { const b = document.querySelector(`.dock button[data-tab="${tab}"]`); if (b && drawerTab !== tab) b.classList.add("fresh"); }

// ------------------------------------------------------------ render
function render() {
  if (!dirty) return;
  dirty = false;
  renderBrand(); renderKpi(); renderStream(); renderField(); renderToast();
  if (drawerTab) renderDrawer();
}

function renderBrand() {
  const st = S.status || {};
  const order = ["trials", "planning", "season", "harvested"];
  const now = order.indexOf(st.phase);
  document.querySelectorAll("#phases li").forEach((li, i) => { li.classList.toggle("now", i === now); li.classList.toggle("done", now > i); });
  const ld = lastDay();
  if (st.phase === "season" || st.phase === "harvested") {
    $("date").textContent = ld ? dayLabel(Math.min(ld.day, D - 1)) + (st.phase === "harvested" ? ", season over" : "") : "1 Oct";
    if (ld) { $("weather").textContent = `${fmt(ld.tmax, 0)}°C high, ET₀ ${fmt(ld.et0, 1)} mm`; $("weather").classList.toggle("hot", ld.tmax >= 40); }
  } else {
    $("date").textContent = st.phase === "planning" ? "Planning the season" : S.trials.length ? "Trial season" : "Before sowing";
    $("weather").textContent = S.trials.length ? `${S.trials.length} of ${st.plots_budget || 16} trial plots grown` : "";
  }
  const day = ld ? ld.day + 1 : 0;
  $("tlFill").style.width = `${(100 * day) / D}%`;
  const tl = $("timeline"); tl.querySelectorAll(".tl-mark").forEach((e) => e.remove());
  const mark = (d, cls, title) => { const e = document.createElement("i"); e.className = `tl-mark ${cls}`; e.style.left = `${(100 * d) / D}%`; e.title = title; tl.appendChild(e); };
  S.perturbations.forEach((p) => mark(p.day, "change", `${dayLabel(p.day)}: ${p.note}`));
  S.events.filter((e) => e.kind === "anomaly").forEach((e) => mark(e.data.detected_day, "alarm", `${dayLabel(e.data.detected_day)}: alarm in ${e.data.field}`));
  S.events.filter((e) => e.kind === "harvest").forEach((e) => mark(e.data.day, "harvest", `${dayLabel(e.data.day)}: ${e.data.field} harvested`));
  $("agentName").textContent = agentName(S.agentKind || info.agent);
}
function agentName(k) { return { spark: "Muse Spark", glimmer: "Muse Glimmer", "scripted-rl": "Scripted protocol with RL", scripted: "Scripted protocol", "scripted-noadapt": "Scripted, ignores alarms" }[k] || ""; }

function renderKpi() {
  const st = S.status || {};
  let n = null, label = "people fed in a bad year", lim = null;
  if (st.result) { n = st.result.people_fed; label = "people fed by this harvest"; lim = st.result.limiting; }
  else if (st.phase === "season" && lastProj()) { const p = lastProj(); n = p.people_p10; label = "people fed in a bad year, projected"; lim = minKey(p.by_nutrient_p50); }
  else if (S.plan) { n = S.plan.people_p10; label = "people fed in a bad year, planned"; lim = S.plan.limiting; }
  $("fedN").textContent = n == null ? "–" : fmt(n);
  $("fedL").textContent = label;
  $("fedLimit").textContent = lim ? `Limited by ${NUTRIENT[lim] || lim}. A person counts only when calories, protein and vitamin A are all covered.` : "Counts a person only when calories, protein and vitamin A are all covered.";
  const wq = st.water_quota_m3 || 60000, eq = st.energy_kwh || 90000;
  const ld = lastDay();
  const w = (ld && ld.water_used_m3 != null ? ld.water_used_m3 : st.water_used_m3) || 0;
  const e = (ld && ld.energy_used_kwh != null ? ld.energy_used_kwh : st.energy_used_kwh) || 0;
  $("waterTxt").textContent = `${fmt(w)} of ${fmt(wq)} m³`; $("energyTxt").textContent = `${fmt(e)} of ${fmt(eq)} kWh`;
  $("waterBar").style.width = `${Math.min(100, (100 * w) / wq)}%`; $("waterBar").classList.toggle("over", w > wq);
  $("energyBar").style.width = `${Math.min(100, (100 * e) / eq)}%`; $("energyBar").classList.toggle("over", e > eq);
  const rl = (ld && ld.controller ? ld.controller : st.controller) === "rl_policy";
  $("ctrlPill").textContent = rl ? "RL policy" : "Fixed rule"; $("ctrlPill").classList.toggle("rl", rl);
}
function minKey(o) { if (!o) return null; return Object.keys(o).reduce((a, b) => (o[a] <= o[b] ? a : b)); }

function streamItem(e) {
  const d = e.data || {};
  const why = (s) => (s ? `<div class="why">${esc(s)}</div>` : "");
  switch (e.kind) {
    case "hypothesis": return ["decide", `Hypothesis ${d.id}: ${esc(d.statement)}`, why(`Predicts: ${d.prediction}`)];
    case "conclusion": return [d.verdict === "supported" ? "learn" : "decide", `${d.hypothesis_id} ${esc(d.verdict)}`, why(d.evidence)];
    case "trial_start": return ["decide", `Plants ${d.plots.length} trial plots`, why(d.rationale)];
    case "trial_result": { const held = d.plots.filter((p) => p.prediction_held).length; return [held < d.plots.length ? "test" : "learn", `${held} of ${d.plots.length} trial predictions held`, why(d.plots.filter((p) => !p.prediction_held).slice(0, 3).map((p) => `${crop(p.crop)} (${p.plot}): predicted ${p.predicted_yield_90pct[0]}–${p.predicted_yield_90pct[1]}, measured ${p.measured_yield_t_ha} t/ha`).join("; "))]; }
    case "model_update": return ["learn", d.crops ? `Calibrates ${d.crops.map((c) => crop(c.crop)).join(", ")}` : `Teaches the model: ${esc(String(d.finding).replace(/_/g, " "))} = ${d.value} in ${d.field} since ${dayLabel(d.since_day)}`, why(d.rationale)];
    case "plan": return ["decide", `Plan ${d.plan_id}: <span class="num-b">${fmt(d.people_p10)}</span> people in a bad year`, why(d.scientist_choice ? `Keeps your crops. With a free choice the scientist would feed ${fmt(d.scientist_choice.people_p10)}. Uncertainty costs ${fmt(d.cost_of_uncertainty_people)} people.` : `Uncertainty costs ${fmt(d.cost_of_uncertainty_people)} people. ${d.rationale || ""}`)];
    case "farmer_choices": return ["decide", "Your crop choices", why(d.fields.filter((f) => f.crop || f.choice === "fallow").map((f) => `${f.field}: ${f.choice}${f.season ? `, ${f.season.toLowerCase()}` : ""}`).join("; "))];
    case "rl_train_start": return ["rl", `Trains an irrigation policy for ${d.plan_id} by reinforcement learning`, why(d.rationale)];
    case "rl_policy": { const c = d.held_out_comparison || {}; return ["rl", d.recommend === "rl_policy" ? `Policy beats the fixed rule in its model: people fed ${signed(c.people_mean_change_pct)}% on average, water ${signed(c.water_change_pct)}%, energy ${signed(c.energy_change_pct)}%` : "Policy did not beat the fixed rule; keeps the rule", why(d.note)]; }
    case "controller": return ["rl", d.controller === "rl_policy" ? "Hands daily irrigation to the RL policy" : "Hands daily irrigation back to the fixed rule", why(d.rationale)];
    case "season_start": return ["decide", `Sows plan ${d.plan_id}, irrigation by ${d.controller === "rl_policy" ? "the RL policy" : "the fixed rule"}`, why(d.rationale)];
    case "anomaly": return ["alarm", `Alarm in ${d.field}: ${esc(d.signal_label)} ${esc(d.direction)}`, why(`Onset around ${dayLabel(d.onset_day)}. The season is paused for investigation.`)];
    case "field_test": { const r = Object.entries(d).filter(([k]) => !["rationale", "field", "day", "test", "note"].includes(k)).map(([k, v]) => `${k.replace(/_/g, " ")} ${Array.isArray(v) ? v.join(", ") : v}`).join(", "); return ["test", `${d.field} ${String(d.test).replace("_", " ")} test: <span class="num-m">${esc(r)}</span>`, why(d.rationale)]; }
    case "look": return ["test", `Drone over ${d.field}: canopy <span class="num-m">${fmt(d.canopy_cover_measured, 2)}</span> measured vs <span class="num-b">${fmt(d.canopy_cover_predicted, 2)}</span> predicted`, why(d.diagnosis && d.diagnosis.condition ? `Diagnosis: ${String(d.diagnosis.condition).replace(/_/g, " ")}` : d.reason)];
    case "adjust": return ["decide", `${d.field}: ${[d.repair ? "repairs the drip line" : "", d.pest_control ? "applies pest control" : "", d.irr != null ? `irrigation ${Math.round(d.irr * 100)}%` : "", d.desal != null ? `desalinated water ${Math.round(d.desal * 100)}%` : ""].filter(Boolean).join(", ")}`, why(d.rationale)];
    case "rebalance": return ["decide", `Re-plans water: bad-year people ${d.people_p10_before} → ${d.people_p10_after}`, why(d.rationale)];
    case "anomaly_dismissed": return ["decide", "Dismisses the alarm", why(d.rationale)];
    case "harvest": return ["learn", `${d.field} ${crop(d.crop)} harvested: ${d.yield_t_ha} t/ha`, ""];
    case "season_result": return ["learn", `Season over: feeds <b>${fmt(d.people_fed)}</b> people`, why(`${fmt(d.water_used_m3)} m³ groundwater, ${fmt(d.energy_used_kwh)} kWh. Limited by ${NUTRIENT[d.limiting] || d.limiting}.`)];
    case "run_end": return ["learn", "Summary", why(d.summary)];
    case "agent_step": return d.role === "agent" ? ["decide", esc(d.text), ""] : null;
    default: return null;
  }
}
const signed = (x) => (x == null ? "–" : (x > 0 ? "+" : "") + x);

let streamCount = -1;
function renderStream() {
  const items = [];
  let inSeason = false;
  const pert = [...S.perturbations];
  const due = (p, k, e) => (p._order != null ? p._order <= k : !e || (inSeason && e.t != null && e.t > p.day));
  const pushPert = (k, e) => { while (pert.length && due(pert[0], k, e)) { const p = pert.shift(); items.push({ it: ["world", `Hidden change in ${p.field === "all" ? "the farm" : p.field}`, `<div class="why">${esc(p.note)}. The scientist is not told.</div>`], t: p.day }); } };
  S.events.forEach((e, k) => { pushPert(k, e); if (e.kind === "season_start") inSeason = true; const it = streamItem(e); if (it) items.push({ it, t: inSeason && e.kind !== "season_start" ? e.t : null, seq: e.seq }); });
  pushPert(1e13, null);
  if (items.length === streamCount) return;
  streamCount = items.length;
  const list = $("stream");
  const atTop = list.scrollTop < 30;
  const shown = items.slice(-140).reverse();
  list.innerHTML = shown.map(({ it, t }) => {
    const [k, txt, extra] = it;
    const when = t != null ? `<span class="t">${dayLabel(Math.min(t, D - 1))}</span>` : "";
    return `<li class="k-${k}">${when}${txt}${extra || ""}</li>`;
  }).join("");
  if (atTop) list.scrollTop = 0;
  const hyps = (S.status.hypotheses || []).slice(-3).reverse();
  $("hyps").innerHTML = hyps.map((h) => `<div class="hyp ${h.status}"><span class="st">${h.status}</span><b>${h.id}</b> ${esc(h.statement)}</div>`).join("");
}

function renderField() {
  const fl = fieldsNow();
  const tabs = $("fieldTabs");
  if (!tabs.children.length) {
    FIELD_IDS.forEach((id, i) => { const b = document.createElement("button"); b.textContent = id; b.setAttribute("role", "tab"); b.onclick = () => select(i); tabs.appendChild(b); });
  }
  const an = S.status && S.status.anomaly;
  [...tabs.children].forEach((b, i) => { b.classList.toggle("on", i === sel); b.classList.toggle("alarm", !!an && an.field_index === i); b.setAttribute("aria-selected", i === sel); });
  const f = fl[sel] || {};
  $("fieldTitle").textContent = `${FIELD_IDS[sel]} ${fieldName(sel)}`;
  const ld = lastDay();
  const w = ld && ld.world && ld.world[sel];
  let sub = f.crop ? crop(f.crop) : "Fallow";
  if (f.crop && f.sow != null) sub += `, sown ${dayLabel(f.sow)}`;
  if (w && w.sown && !w.done) sub += `, ${Math.round(100 * Math.min(w.stage, 1))}% through its cycle`;
  if (w && w.done) sub += ", harvested";
  if (S.status.phase === "trials" || (!S.fields && !S.plan)) sub = "Not planned yet. The scientist is running trial plots.";
  $("fieldSub").textContent = sub;
  const marks = markersFor(sel);
  bandChart($("chSw"), "sw", { fmt: (v) => fmt(v, 3), unit: "m³/m³", marks });
  bandChart($("chCc"), "cc", { fmt: (v) => fmt(v, 2), unit: "", marks, sparse: true, min: 0, max: 1 });
  bandChart($("chEc"), "ec", { fmt: (v) => fmt(v, 1), unit: "dS/m", marks, min: 0 });
  irrChart($("chIrr"));
  const sc = S.scene[FIELD_IDS[sel]];
  $("droneFig").hidden = !sc;
  if (sc && $("droneImg").dataset.src !== sc.image) {
    $("droneImg").src = sc.image; $("droneImg").dataset.src = sc.image;
    const diag = sc.diagnosis && sc.diagnosis.condition ? `, diagnosis: ${String(sc.diagnosis.condition).replace(/_/g, " ")}` : "";
    $("droneCap").textContent = `Drone image analysed${sc.source ? ` by ${sc.source}` : ""}${diag}.`;
  }
  $("perturb").hidden = !(mode === "live" && S.status.phase === "season");
}
const NAMES = ["North", "Palm edge", "Dune", "Old wadi", "Loam block", "Sabkha rim"];
function fieldName(i) { return (S.fields && S.fields[i] && S.fields[i].name) || NAMES[i]; }

function markersFor(i) {
  const id = FIELD_IDS[i];
  const m = [];
  S.perturbations.forEach((p) => { if (p.field === id || p.field === "all") m.push({ day: p.day, cls: "change" }); });
  S.events.forEach((e) => { if (e.kind === "anomaly" && e.data.field === id) m.push({ day: e.data.detected_day, cls: "alarm" }); });
  return m;
}

function bandChart(svg, key, opts) {
  svg.innerHTML = "";
  const W = 300, H = 96;
  const rows = S.days.map((d) => ({ day: d.day, f: d.fields[sel] })).filter((r) => r.f);
  if (!rows.length) { svgEl("text", { x: 4, y: H / 2, "font-size": 11, fill: css("--ink-3") }, svg).textContent = "Starts when the season begins"; return; }
  const lo = rows.map((r) => r.f[key + "_lo"]), hi = rows.map((r) => r.f[key + "_hi"]), pr = rows.map((r) => r.f[key + "_pred"]), ob = rows.map((r) => r.f[key + "_obs"]);
  const vals = [...lo, ...hi, ...ob].filter((v) => v != null && Number.isFinite(v));
  let [y0, y1] = nice(Math.min(...vals), Math.max(...vals));
  if (opts.min != null) y0 = Math.max(opts.min, y0);
  if (opts.max != null) y1 = Math.min(opts.max, y1);
  const X = (d) => (d / (D - 1)) * W, Y = (v) => H - ((v - y0) / (y1 - y0)) * H;
  // recessive grid: three hairlines
  for (let k = 0; k <= 2; k++) svgEl("line", { x1: 0, x2: W, y1: (k * H) / 2, y2: (k * H) / 2, stroke: css("--line"), "vector-effect": "non-scaling-stroke" }, svg);
  let band = "";
  rows.forEach((r, k) => { if (hi[k] != null) band += `${band ? "L" : "M"}${X(r.day).toFixed(1)},${Y(hi[k]).toFixed(1)}`; });
  for (let k = rows.length - 1; k >= 0; k--) if (lo[k] != null) band += `L${X(rows[k].day).toFixed(1)},${Y(lo[k]).toFixed(1)}`;
  svgEl("path", { d: band + "Z", fill: css("--belief-band"), stroke: "none" }, svg);
  let line = ""; rows.forEach((r, k) => { if (pr[k] != null) line += `${line ? "L" : "M"}${X(r.day).toFixed(1)},${Y(pr[k]).toFixed(1)}`; });
  svgEl("path", { d: line, fill: "none", stroke: css("--belief"), "stroke-width": 1.6, "vector-effect": "non-scaling-stroke" }, svg);
  opts.marks.forEach((m) => svgEl("line", { x1: X(m.day), x2: X(m.day), y1: 0, y2: H, stroke: m.cls === "alarm" ? css("--alarm") : css("--ink"), "stroke-width": 1.4, "stroke-dasharray": m.cls === "alarm" ? "" : "3 3", "vector-effect": "non-scaling-stroke" }, svg));
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
    tip.innerHTML = `${dayLabel(rows[k].day)}<br><span style="color:var(--belief)">Model ${opts.fmt(pr[k])} (${opts.fmt(lo[k])}–${opts.fmt(hi[k])})</span>${ob[k] != null ? `<br><span style="color:var(--measured)">Measured ${opts.fmt(ob[k])}</span>` : ""}`;
    tip.style.left = `${Math.min(ev.clientX + 12, innerWidth - 200)}px`; tip.style.top = `${ev.clientY + 12}px`;
  });
  hit.addEventListener("mouseleave", () => { $("tip").hidden = true; cursor.setAttribute("visibility", "hidden"); });
}

function irrChart(svg) {
  svg.innerHTML = "";
  const W = 300, H = 44;
  const rows = S.days.map((d) => ({ day: d.day, f: d.fields[sel] })).filter((r) => r.f);
  if (!rows.length) return;
  const mx = Math.max(10, ...rows.map((r) => r.f.irr_mm || 0));
  const bw = W / D;
  let p = "", pd = "";
  rows.forEach((r) => {
    const h = ((r.f.irr_mm || 0) / mx) * H; if (h <= 0) return;
    const x = r.day * bw;
    p += `M${x.toFixed(2)},${H}v${(-h).toFixed(2)}h${(bw * 0.8).toFixed(2)}v${h.toFixed(2)}z`;
    const hd = h * (r.f.desal || 0);
    if (hd > 0) pd += `M${x.toFixed(2)},${H}v${(-hd).toFixed(2)}h${(bw * 0.8).toFixed(2)}v${hd.toFixed(2)}z`;
  });
  svgEl("path", { d: p, fill: css("--water"), opacity: 0.55 }, svg);
  svgEl("path", { d: pd, fill: css("--water") }, svg);
  svgEl("text", { x: W - 2, y: 10, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = `${fmt(mx, 0)} mm, darker share desalinated`;
}

function renderToast() {
  const a = S.status && S.status.anomaly;
  const t = $("toast");
  if (a) { t.hidden = false; t.innerHTML = `<b>Alarm in ${a.field}:</b> ${esc(a.signal_label)} ${esc(a.direction)}. The scientist is investigating before the season continues.`; }
  else if (S.status.result) { t.hidden = true; }
  else t.hidden = true;
}

// ------------------------------------------------------------ drawer
const TITLES = { history: "Your seasons", trials: "Trial plots: predicted before planting, measured at harvest", beliefs: "What the scientist believes about the local varieties", plan: "Season plan", rl: "Irrigation policy learned by reinforcement learning", ledger: "Audit ledger" };
function openDrawer(tab) {
  drawerTab = tab;
  document.querySelectorAll(".dock button").forEach((b) => { b.classList.toggle("on", b.dataset.tab === tab); if (b.dataset.tab === tab) b.classList.remove("fresh"); });
  $("drawer").hidden = false; $("drawerTitle").textContent = TITLES[tab];
  dirty = true; render(); renderDrawer();
}
function closeDrawer() { if (drawerTab) drawerUserClosed.add(drawerTab); drawerTab = null; $("drawer").hidden = true; document.querySelectorAll(".dock button").forEach((b) => b.classList.remove("on")); }

let drawerKey = "";
function renderDrawer() {
  const key = `${drawerTab}|${S.trials.length}|${S.rl_train.length}|${!!S.rl}|${S.plan && S.plan.plan_id}|${S.beliefs && S.beliefs.day}|${S.events.length}|${S.fields ? 1 : 0}`;
  if (key === drawerKey) return; drawerKey = key;
  const b = $("drawerBody");
  if (drawerTab === "trials") b.innerHTML = trialsHtml();
  else if (drawerTab === "beliefs") b.innerHTML = beliefsHtml();
  else if (drawerTab === "plan") b.innerHTML = planHtml();
  else if (drawerTab === "rl") { b.innerHTML = rlHtml(); drawRl(); }
  else if (drawerTab === "ledger") { b.innerHTML = ledgerHtml(); const v = $("verifyBtn"); if (v) v.onclick = verifyLedger; }
  else if (drawerTab === "history") { b.innerHTML = `<p class="empty">Loading…</p>`; historyHtml().then((h) => { if (drawerTab === "history") b.innerHTML = h; }); }
}

function rangeSvg(lo, hi, med, meas, max) {
  const X = (v) => 4 + (v / max) * 152;
  return `<svg viewBox="0 0 160 14" width="160" height="14" aria-hidden="true"><line x1="4" x2="156" y1="7" y2="7" stroke="${css("--line")}"/><rect x="${X(lo)}" y="3" width="${Math.max(2, X(hi) - X(lo))}" height="8" rx="2" fill="${css("--belief-band")}" stroke="${css("--belief")}"/><line x1="${X(med)}" x2="${X(med)}" y1="2" y2="12" stroke="${css("--belief")}" stroke-width="1.5"/><circle cx="${X(meas)}" cy="7" r="3.6" fill="${css("--measured")}" stroke="${css("--glass-strong")}" stroke-width="1.5"/></svg>`;
}
function trialsHtml() {
  if (!S.trials.length) return `<p class="empty">No trial plots yet. Each plot gets a predicted yield range before it is planted; the harvest then shows whether the model was right.</p>`;
  const max = Math.max(...S.trials.map((t) => Math.max(t.predicted_yield_90pct[1], t.measured_yield_t_ha))) * 1.05;
  return `<table><thead><tr><th>Crop</th><th>Plot</th><th>Sown</th><th>Predicted range and measured yield</th><th class="n">Measured</th><th>Prediction</th></tr></thead><tbody>${S.trials.map((t) => `<tr><td>${crop(t.crop)}</td><td>${t.plot}</td><td>${dayLabel(t.sow)}</td><td>${rangeSvg(t.predicted_yield_90pct[0], t.predicted_yield_90pct[1], t.predicted_yield_median, t.measured_yield_t_ha, max)}</td><td class="n">${fmt(t.measured_yield_t_ha, 1)} t/ha</td><td>${t.prediction_held ? '<span class="ok">Held</span>' : '<span class="miss">Missed</span>'}</td></tr>`).join("")}</tbody></table><p class="note">Violet: the model's 90% range and median before planting. Orange: the harvest. A miss is information: the next calibration learns from it.</p>`;
}
function beliefsHtml() {
  if (!S.beliefs) return `<p class="empty">No beliefs yet.</p>`;
  const crops = [...S.beliefs.crops].sort((a, b) => b.plots - a.plots);
  const cell = (c, k) => {
    const t = c.traits[k]; const sd0 = t.prior_sd; const c0 = k === "wp" || k === "cgc" ? 1 : 0;
    const lo = c0 - 3 * sd0, hi = c0 + 3 * sd0; const X = (v) => Math.min(100, Math.max(0, ((v - lo) / (hi - lo)) * 100));
    return `<svg viewBox="0 0 100 18" preserveAspectRatio="none" aria-label="${TRAIT[k]} ${t.mean} ± ${t.sd}"><line x1="${X(c0 - 2 * sd0)}" x2="${X(c0 + 2 * sd0)}" y1="9" y2="9" stroke="${css("--line")}" stroke-width="6" stroke-linecap="round" vector-effect="non-scaling-stroke"/><line x1="${X(c0)}" x2="${X(c0)}" y1="2" y2="16" stroke="${css("--ink-3")}" stroke-dasharray="2 2" vector-effect="non-scaling-stroke"/><line x1="${X(t.mean - 2 * t.sd)}" x2="${X(t.mean + 2 * t.sd)}" y1="9" y2="9" stroke="${css("--belief")}" stroke-width="2.5" vector-effect="non-scaling-stroke"/><path d="M${X(t.mean)},9h0" stroke="${css("--belief")}" stroke-width="8" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
  };
  return `<div class="forest"><span class="h">Crop (plots)</span>${Object.values(TRAIT).map((t) => `<span class="h">${t}</span>`).join("")}${crops.map((c) => `<span>${crop(c.crop)} <span style="color:var(--ink-3)">(${c.plots})</span></span>${["wp", "cgc", "heat", "salt"].map((k) => cell(c, k)).join("")}`).join("")}</div><p class="note">Grey: the published value with its prior uncertainty. Violet: the current belief, mean and 95% interval. It narrows only for traits a trial plot actually exposed.</p>`;
}
function planHtml() {
  const p = S.plan;
  if (!p) return `<p class="empty">No plan yet.</p>`;
  const cmp = p.scientist_choice ? ` With a free choice of crops the scientist would feed ${fmt(p.scientist_choice.people_p10)} (${p.scientist_choice.fields.filter((f) => f.crop).map((f) => `${f.field} ${crop(f.crop)}`).join(", ")}).` : "";
  return `<p style="margin:0 0 8px">Plan ${p.plan_id} feeds <b>${fmt(p.people_p10)}</b> people in a bad year and ${fmt(p.people_p50)} in a typical one. Not knowing the varieties exactly costs ${fmt(p.cost_of_uncertainty_people)} people. Bad-year water ${fmt(p.water_p90_m3)} m³, energy ${fmt(p.energy_p90_kwh)} kWh.${cmp}</p><table><thead><tr><th>Field</th><th>Crop</th><th>Sowing</th><th class="n">Irrigation</th><th class="n">Desalinated</th><th class="n">Nitrogen</th><th class="n">Yield, typical</th></tr></thead><tbody>${p.fields.map((f, i) => f.crop ? `<tr><td>${f.field} ${NAMES[i]}</td><td>${crop(f.crop)}${f.farmer_choice ? ' <span class="pill">your pick</span>' : ""}</td><td>${dayLabel(f.mgmt.sow)}</td><td class="n">${Math.round(f.mgmt.irr * 100)}%</td><td class="n">${Math.round(f.mgmt.desal * 100)}%</td><td class="n">${fmt(f.mgmt.nfert)} kg/ha</td><td class="n">${fmt(f.yield_t_ha_p10_p50_p90[1], 1)} t/ha</td></tr>` : `<tr><td>${f.field} ${NAMES[i]}</td><td colspan="6" style="color:var(--ink-3)">Left fallow</td></tr>`).join("")}</tbody></table>`;
}
function rlHtml() {
  if (!S.rl && !S.rl_train.length) return `<p class="empty">No policy trained yet. After planning, the scientist can train a daily irrigation policy inside its own model of the farm, then decide whether to use it.</p>`;
  const r = S.rl; const c = r && r.held_out_comparison;
  const top = c ? `<div class="deltas"><div><b class="big-delta">${signed(c.people_p10_change_pct)}%</b><span>people fed in a bad year</span></div><div><b class="big-delta">${signed(c.water_change_pct)}%</b><span>groundwater</span></div><div><b class="big-delta">${signed(c.energy_change_pct)}%</b><span>energy</span></div></div>` : `<p class="note" style="margin-top:0">Training: ${S.rl_train.length} iterations so far.</p>`;
  const tbl = c ? `<table><thead><tr><th></th><th class="n">Fixed rule</th><th class="n">RL policy</th></tr></thead><tbody>
    <tr><td>People fed, bad year</td><td class="n">${fmt(c.rule.people_p10)}</td><td class="n">${fmt(c.policy.people_p10)}</td></tr>
    <tr><td>People fed, average</td><td class="n">${fmt(c.rule.people_mean)}</td><td class="n">${fmt(c.policy.people_mean)}</td></tr>
    <tr><td>Groundwater, average m³</td><td class="n">${fmt(c.rule.water_mean_m3)}</td><td class="n">${fmt(c.policy.water_mean_m3)}</td></tr>
    <tr><td>Energy, average kWh</td><td class="n">${fmt(c.rule.energy_mean_kwh)}</td><td class="n">${fmt(c.policy.energy_mean_kwh)}</td></tr>
    <tr><td>Years over the water quota</td><td class="n">${c.rule.years_over_quota_pct}%</td><td class="n">${c.policy.years_over_quota_pct}%</td></tr></tbody></table>` : "";
  const note = r ? `<p class="note">${fmt(r.imagined_farm_seasons)} imagined farm seasons, ${r.trained_seconds} s. Evolution strategies trained a ${r.policy_parameters}-parameter network that reads the sensors each day and scales the plan's drip schedule and water blend. Crop traits come from the scientist's calibrated beliefs; the real farm stays hidden. Compared on 40 held-out imagined seasons. ${r.recommend === "rl_policy" ? "Recommended." : "Not recommended: the rule stays."}</p>` : "";
  return `<div class="rl-grid"><div>${top}<figure class="chart" style="margin:0"><figcaption>People fed per season during training, in the scientist's model</figcaption><svg id="rlCurve" viewBox="0 0 420 150"></svg></figure><div class="legend"><span class="lg belief">Training seasons, average</span><span class="lg measured">Held-out seasons, bad year</span></div></div><div>${tbl}<figure class="chart"><figcaption>Policy irrigation relative to the plan, by week</figcaption><svg id="rlWeek" viewBox="0 0 300 80"></svg></figure></div></div>${note}`;
}
function drawRl() {
  const svg = $("rlCurve"); if (!svg) return;
  const H = 150, W = 420, L = 34, B = 18;
  const tr = S.rl_train.filter((x) => x.iter >= 0);
  const val = (S.rl && S.rl.validation) || tr.filter((x) => x.val_people_p10 != null).map((x) => ({ iter: x.iter + 1, val_people_p10: x.val_people_p10 }));
  const ys = [...tr.map((x) => x.people), ...val.map((x) => x.val_people_p10)].filter((v) => v != null);
  if (!ys.length) return;
  const n = Math.max(10, tr.length, ...val.map((v) => v.iter));
  const [y0, y1] = nice(Math.min(...ys), Math.max(...ys));
  const X = (i) => L + (i / n) * (W - L - 6), Y = (v) => (H - B) - ((v - y0) / (y1 - y0)) * (H - B - 6);
  [y0, (y0 + y1) / 2, y1].forEach((v) => { svgEl("line", { x1: L, x2: W, y1: Y(v), y2: Y(v), stroke: css("--line") }, svg); svgEl("text", { x: L - 4, y: Y(v) + 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = fmt(v); });
  svgEl("text", { x: W, y: H - 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, svg).textContent = `iteration ${tr.length}`;
  svgEl("path", { d: tr.map((x, k) => `${k ? "L" : "M"}${X(x.iter + 1).toFixed(1)},${Y(x.people).toFixed(1)}`).join(""), fill: "none", stroke: css("--belief"), "stroke-width": 2 }, svg);
  val.forEach((v) => svgEl("circle", { cx: X(v.iter), cy: Y(v.val_people_p10), r: 4.5, fill: css("--measured"), stroke: css("--glass-strong"), "stroke-width": 2 }, svg));
  if (S.rl && S.rl.best_checkpoint_iter > 0) { const b = S.rl.best_checkpoint_iter; svgEl("line", { x1: X(b), x2: X(b), y1: 6, y2: H - B, stroke: css("--ink-3"), "stroke-dasharray": "3 3" }, svg); svgEl("text", { x: X(b) - 4, y: 14, "text-anchor": "end", "font-size": 10, fill: css("--ink-2") }, svg).textContent = "kept"; }
  const wk = $("rlWeek"); if (!wk || !S.rl) return;
  const m = S.rl.policy_irrigation_multiplier_by_week || []; const pts = m.map((v, k) => [k, v]).filter(([, v]) => v > 0);
  if (!pts.length) return;
  const Wx = (k) => 26 + (k / Math.max(1, m.length - 1)) * 268, Wy = (v) => 72 - ((v - 0.5) / 1.0) * 64;
  [0.5, 1, 1.5].forEach((v) => { svgEl("line", { x1: 26, x2: 296, y1: Wy(v), y2: Wy(v), stroke: v === 1 ? css("--ink-3") : css("--line"), "stroke-dasharray": v === 1 ? "3 3" : "" }, wk); svgEl("text", { x: 22, y: Wy(v) + 3, "text-anchor": "end", "font-size": 10, fill: css("--ink-3") }, wk).textContent = `${v}×`; });
  svgEl("path", { d: pts.map(([k, v], i) => `${i ? "L" : "M"}${Wx(k).toFixed(1)},${Wy(v).toFixed(1)}`).join(""), fill: "none", stroke: css("--water"), "stroke-width": 2 }, wk);
}
function ledgerHtml() {
  const ev = S.events.slice(-60).reverse();
  return `<p style="margin:0 0 8px">Every hypothesis, prediction, test and decision is written to a hash-chained ledger: each entry includes the hash of the one before, so any edit breaks the chain. ${mode === "live" ? '<button class="btn" id="verifyBtn">Verify ledger</button> <span id="verifyOut"></span>' : ""}</p><table><thead><tr><th class="n">#</th><th>Entry</th><th>Day</th><th>Hash</th></tr></thead><tbody>${ev.map((e) => `<tr><td class="n">${e.seq}</td><td>${esc(e.kind.replace(/_/g, " "))}</td><td>${e.t != null ? e.t : ""}</td><td class="hash">${String(e.hash).slice(0, 16)}</td></tr>`).join("")}</tbody></table>`;
}
async function verifyLedger() { const r = await (await fetch("api/verify")).json(); $("verifyOut").innerHTML = r.ok ? `<span class="ok">${esc(r.message)}</span>` : `<span class="miss">${esc(r.message)}</span>`; }

// ------------------------------------------------------------ selection
function select(i) { if (i == null || i < 0) return; sel = i; if (scene) scene.setSelected(i); dirty = true; render(); }

// ------------------------------------------------------------ live mode
async function post(path, body) { const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) }); return r.json(); }
async function startLive(state) {
  info = state.info || {};
  $("liveControls").hidden = false;
  $("historyTab").hidden = false;
  if (info.user) { $("account").hidden = false; $("userName").textContent = info.user.name; }
  $("logoutBtn").onclick = async () => { await post("api/auth/logout"); location.href = "./"; };
  const opt = $("agentSel").querySelector('option[value="spark"]');
  if (!info.has_api_key) { opt.textContent = "Muse Spark (needs MODEL_API_KEY on the server)"; opt.disabled = true; }
  const glim = $("agentSel").querySelector('option[value="glimmer"]'); glim.textContent = "Muse Glimmer (needs a Glimmer endpoint)";
  if (info.agent && [...$("agentSel").options].some((o) => o.value === info.agent && !o.disabled)) $("agentSel").value = info.agent;
  $("speed").value = info.speed || 12;
  S = { ...fresh(), ...state, events: state.events || [], agentKind: info.agent };
  delete S.info; delete S.agent; delete S.beliefs_hist;
  sceneSync();
  dirty = true;
  setRunning(info.running);
  if (!info.running && !(S.status && S.status.phase)) { $("modeNote").textContent = "Your farm is ready. Plan a season to start."; openPlanner(); }
  $("planBtn").onclick = openPlanner;
  $("stopBtn").onclick = async () => { await post("api/stop"); };
  $("startBtn").onclick = startSeason;
  $("speed").oninput = () => post("api/speed", { speed: Number($("speed").value) });
  document.querySelectorAll("#perturb .btn").forEach((b) => (b.onclick = async () => {
    const r = await post("api/perturb", { kind: b.dataset.kind, field: FIELD_IDS[sel] });
    if (!r.ok) $("modeNote").textContent = r.error || "Could not change the farm";
  }));
  const es = new EventSource("api/stream");
  es.onmessage = (ev) => { JSON.parse(ev.data).forEach((m) => { apply(m, true); if (m.kind === "reset") setRunning(true); if (m.kind === "status" && (m.data.done || m.data.phase === "harvested")) setRunning(false); }); };
}
function setRunning(on) { $("planBtn").textContent = on ? "Plan a different season" : "Plan a new season"; $("stopBtn").hidden = !on; }

// ------------------------------------------------------------ season planner
const SEASON_ORDER = ["autumn", "winter", "late_winter"];
const P = { seasons: null, guide: {}, season: "autumn", brush: null, picks: FIELD_IDS.map(() => ({ mode: "scientist" })) };
const SOILS = ["North, loamy sand", "Palm edge, sandy loam", "Dune, sand", "Old wadi, saline", "Loam block", "Sabkha rim, very saline"];
async function openPlanner() {
  $("planner").hidden = false; $("plErr").hidden = true;
  $("plannerClose").onclick = closePlanner;
  $("planner").onclick = (e) => { if (e.target === $("planner")) closePlanner(); };
  document.addEventListener("keydown", escClose);
  if (!P.seasons) {
    try { P.seasons = await (await fetch("api/seasons")).json(); } catch (e) { $("seasonAbout").textContent = "Could not load the seasons. Check your connection."; return; }
  }
  renderSeasonTabs(); await showSeason(P.season); renderFieldRows();
  setTimeout(() => $("seasonTabs").querySelector("button.on")?.focus(), 30);
}
function escClose(e) { if (e.key === "Escape") closePlanner(); }
function closePlanner() { $("planner").hidden = true; document.removeEventListener("keydown", escClose); }
function seasonLabel(id) { const x = P.seasons && P.seasons.seasons.find((s) => s.id === id); return x ? x.label : id; }
function renderSeasonTabs() {
  const box = $("seasonTabs");
  box.innerHTML = P.seasons.seasons.map((x) => `<button role="tab" data-s="${x.id}" class="${x.id === P.season ? "on" : ""}" aria-selected="${x.id === P.season}" style="--c:var(--s-${x.id})"><span class="dot"></span>${esc(x.label)}</button>`).join("")
    + `<button class="rest" disabled title="${esc(P.seasons.summer.about)}">Summer: fields rest</button>`;
  box.querySelectorAll("button[data-s]").forEach((b) => (b.onclick = () => { P.season = b.dataset.s; P.brush = null; renderSeasonTabs(); showSeason(P.season); renderFieldRows(); }));
}
async function showSeason(id) {
  const meta = P.seasons.seasons.find((s) => s.id === id);
  $("seasonAbout").textContent = meta.about;
  const cards = $("cropCards");
  if (!P.guide[id]) {
    cards.innerHTML = `<p class="season-about">Asking the crop model what grows in this season…</p>`;
    try { P.guide[id] = await (await fetch(`api/crop-guide?season=${id}`)).json(); } catch (e) { cards.innerHTML = `<p class="err">Could not load the crop guide.</p>`; return; }
  }
  if (P.season !== id) return;
  const g = P.guide[id];
  const ymax = Math.max(...g.crops.flatMap((c) => c.fields.map((f) => f.yield_t_ha_p50)), 0.1);
  cards.innerHTML = g.crops.map((c) => {
    const cmax = Math.max(...c.fields.map((f) => f.yield_t_ha_p50), 0.1);
    return `<button class="crop-card ${P.brush === c.crop ? "on" : ""}" data-c="${c.crop}" aria-pressed="${P.brush === c.crop}">
      <h4>${esc(c.label)}<span class="meta">${c.cycle_days ? `${c.cycle_days} days` : ""}</span></h4>
      <span class="meta">Sow ${esc(c.sow_window_label)}${c.harvest_label ? `, harvest around ${esc(c.harvest_label)}` : ""}</span>
      <span class="needs">${c.good_for.map((n) => `<span class="need">${esc(n)}</span>`).join("")}<span class="need">salt limit ${c.salt_threshold_ds_m} dS/m</span></span>
      <span class="meta">Expected yield per field, t/ha</span>
      <span class="yields">${c.fields.map((f) => `<span><i><b style="height:${Math.round((100 * f.yield_t_ha_p50) / cmax)}%"></b></i>${f.field}<br>${fmt(f.yield_t_ha_p50, f.yield_t_ha_p50 < 10 ? 1 : 0)}</span>`).join("")}</span>
    </button>`;
  }).join("") || `<p class="season-about">No crop on the list is sown in this season.</p>`;
  cards.querySelectorAll(".crop-card").forEach((b) => (b.onclick = () => { P.brush = P.brush === b.dataset.c ? null : b.dataset.c; showSeason(P.season); renderFieldRows(); }));
  void ymax;
}
function renderFieldRows() {
  const box = $("fieldRows");
  const g = P.guide[P.season];
  const inSeason = g ? g.crops.map((c) => c.crop) : [];
  $("plHint").textContent = P.brush ? `Choose the fields for ${crop(P.brush)} in ${seasonLabel(P.season).toLowerCase()}. Click the card again when you're done.` : "Pick a crop card to sow it on several fields, or use the menu on each field.";
  box.innerHTML = FIELD_IDS.map((id, i) => {
    const p = P.picks[i];
    const opts = [`<option value="scientist" ${p.mode === "scientist" ? "selected" : ""}>Scientist decides</option>`,
      `<option value="fallow" ${p.mode === "fallow" ? "selected" : ""}>Leave fallow</option>`];
    if (p.mode === "crop" && (p.season !== P.season || !inSeason.includes(p.crop))) opts.push(`<option value="keep" selected>${esc(crop(p.crop))}, ${esc(seasonLabel(p.season).toLowerCase())}</option>`);
    inSeason.forEach((c) => opts.push(`<option value="c:${c}" ${p.mode === "crop" && p.crop === c && p.season === P.season ? "selected" : ""}>${esc(crop(c))}, ${esc(seasonLabel(P.season).toLowerCase())}</option>`));
    const tag = p.mode === "crop" ? `<span class="sz" style="--c:var(--s-${p.season})">${esc(seasonLabel(p.season))}</span>` : "";
    if (P.brush) {
      const here = p.mode === "crop" && p.crop === P.brush && p.season === P.season;
      const now = p.mode === "crop" ? `${crop(p.crop)}, ${seasonLabel(p.season).toLowerCase()}` : p.mode === "fallow" ? "Fallow" : "Scientist decides";
      return `<li class="field-row target" data-i="${i}"><span class="fid">${id}</span><span class="soil">${esc(SOILS[i])}: ${esc(now)}</span>
        <span class="pick"><button class="btn sow ${here ? "" : "primary"}" data-i="${i}">${here ? `Remove ${esc(crop(P.brush))}` : `Sow ${esc(crop(P.brush))} here`}</button>${tag}</span></li>`;
    }
    return `<li class="field-row" data-i="${i}"><span class="fid">${id}</span><span class="soil">${esc(SOILS[i])}</span>
      <span class="pick"><select aria-label="Crop for ${id}" data-i="${i}">${opts.join("")}</select>${tag}</span></li>`;
  }).join("");
  box.querySelectorAll("select").forEach((sel) => (sel.onchange = (e) => {
    const i = Number(sel.dataset.i), v = sel.value;
    if (v === "scientist" || v === "fallow") P.picks[i] = { mode: v };
    else if (v.startsWith("c:")) P.picks[i] = { mode: "crop", crop: v.slice(2), season: P.season };
    renderFieldRows(); e.stopPropagation();
  }));
  box.querySelectorAll("button.sow").forEach((btn) => (btn.onclick = () => {
    const i = Number(btn.dataset.i);
    const p = P.picks[i];
    P.picks[i] = p.mode === "crop" && p.crop === P.brush && p.season === P.season ? { mode: "scientist" } : { mode: "crop", crop: P.brush, season: P.season };
    renderFieldRows();
  }));
}
async function startSeason() {
  const btn = $("startBtn"); btn.disabled = true; $("plErr").hidden = true;
  try {
    const r = await fetch("api/start", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
      body: JSON.stringify({ agent: $("agentSel").value, speed: Number($("speed").value), choices: P.picks }) });
    const d = await r.json().catch(() => ({}));
    if (r.status === 401) { location.href = "login?next=/app"; return; }
    if (!r.ok || !d.ok) throw new Error(d.error || "The season could not start.");
    closePlanner(); $("modeNote").textContent = ""; drawerUserClosed.clear();
  } catch (e) { $("plErr").textContent = e.message; $("plErr").hidden = false; }
  finally { btn.disabled = false; }
}

// ------------------------------------------------------------ past seasons
async function historyHtml() {
  let d;
  try { d = await (await fetch("api/runs", { cache: "no-store" })).json(); } catch (e) { return `<p class="empty">Could not load your seasons.</p>`; }
  if (!d.runs || !d.runs.length) return `<p class="empty">No seasons yet. Plan one to start.</p>`;
  const when = (t) => new Date(t * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  return `<table><thead><tr><th>Started</th><th>Scientist</th><th>Your crops</th><th class="n">People fed</th><th></th></tr></thead><tbody>${d.runs.map((r) => {
    const mine = (r.choices || []).filter((c) => c.crop).map((c) => `${c.field} ${esc(c.choice)}`).join(", ") || "Scientist chose all";
    return `<tr><td>${when(r.created)}</td><td>${esc(agentName(r.agent))}</td><td>${mine}</td><td class="n">${r.result ? fmt(r.result.people_fed) : r.id === info.run_id ? "running" : "stopped"}</td><td class="hist-actions">${r.result ? `<a href="app?run=${r.id}">Replay</a>` : ""}</td></tr>`;
  }).join("")}</tbody></table>`;
}

// ------------------------------------------------------------ replay mode
const R = { msgs: [], pt: [], idx: 0, pos: 0, total: 0, playing: false, rate: 1 };
// Paced by what each message is, not by wall-clock time, so model latency and
// headless runs replay at the same rhythm.
function beat(m) {
  if (m.kind === "day") return 0.13;
  if (m.kind === "rl_train") return 0.05;
  if (m.kind === "trials") return 0.32;
  if (m.kind === "perturbation") return 0.8;
  if (m.kind === "ledger") return streamItem(m.data) ? (m.data.kind === "anomaly" ? 1.6 : 0.55) : 0;
  return 0;
}
function buildTimeline(msgs) {
  let t = 0;
  R.pt = msgs.map((m) => (t += beat(m)));
  R.total = t + 0.5;
}
function seek(pos) {
  if (pos < R.pos || pos - R.pos > 3) {
    if (pos < R.pos) { S = fresh(); R.idx = 0; }
    while (R.idx < R.msgs.length && R.pt[R.idx] <= pos) apply(R.msgs[R.idx++], false);
    R.pos = pos; sceneSync();
  } else {
    while (R.idx < R.msgs.length && R.pt[R.idx] <= pos) apply(R.msgs[R.idx++], true);
    R.pos = pos;
  }
  dirty = true;
}
async function startReplay(url) {
  mode = "replay";
  const data = await (await fetch(url)).json();
  R.msgs = data.messages || data;
  buildTimeline(R.msgs);
  S.agentKind = (data.meta && data.meta.agent) || null;
  $("replayControls").hidden = false;
  $("modeNote").textContent = data.meta && data.meta.note ? data.meta.note : "Recorded run. The scientist's decisions, predictions and measurements replay exactly as logged.";
  $("playBtn").onclick = () => { R.playing = !R.playing; if (R.playing && R.pos >= R.total) seek(0); $("playBtn").textContent = R.playing ? "Pause" : "Play"; };
  $("rate").onchange = () => (R.rate = Number($("rate").value));
  $("scrub").oninput = () => seek((Number($("scrub").value) / 1000) * R.total);
  setTimeout(() => { R.playing = true; $("playBtn").textContent = "Pause"; }, reducedMotion ? 0 : 2400);
  let last = performance.now();
  const tick = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (R.playing) {
      seek(Math.min(R.total, R.pos + dt * R.rate));
      $("scrub").value = String(Math.round((1000 * R.pos) / Math.max(R.total, 1e-6)));
      if (R.pos >= R.total) { R.playing = false; $("playBtn").textContent = "Replay"; }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ------------------------------------------------------------ boot
async function loadScene() {
  try {
    const mod = await import("./scene.js");
    const dark = document.documentElement.dataset.theme === "dark" || (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
    scene = mod.createScene($("stage"), { onSelect: select, theme: dark ? "dusk" : "day", reducedMotion });
    scene.setSelected(sel);
  } catch (e) {
    console.warn("3D view unavailable:", e);
    $("noGL").hidden = false;
  }
}

async function boot() {
  document.querySelectorAll(".dock button").forEach((b) => (b.onclick = () => (drawerTab === b.dataset.tab ? closeDrawer() : openDrawer(b.dataset.tab))));
  $("drawerClose").onclick = closeDrawer;
  await loadScene();
  const q = new URLSearchParams(location.search);
  const isDemo = /\/demo\/?$/.test(location.pathname);
  let replay = q.get("replay") || window.WORLDLAB_REPLAY || (isDemo ? "replay.json" : null);
  if (q.get("run")) replay = `api/runs/${encodeURIComponent(q.get("run"))}/replay`;
  let state = null;
  if (!replay) {
    try {
      const r = await fetch("api/state", { cache: "no-store", credentials: "same-origin" });
      if (r.status === 401) { location.href = "login?next=/app"; return; }
      if (r.ok) state = await r.json();
    } catch (e) { /* static hosting */ }
  }
  if (state) await startLive(state);
  else {
    $("demoControls").hidden = false;
    if (q.get("run")) { $("demoControls").hidden = false; $("demoControls").innerHTML = `<a class="btn primary" href="app">Back to your farm</a>`; }
    await startReplay(replay || "replay.json").catch((e) => { $("modeNote").textContent = `No live server and no recording found (${e.message}).`; });
  }
  const loop = () => { render(); requestAnimationFrame(loop); };
  loop();
}
boot();
