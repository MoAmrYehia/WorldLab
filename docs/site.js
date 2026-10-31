import { api, apiJson, setToken, PAGES } from "./client.js?v=ce00be84d4";
// WorldLab site: account state in the nav, the log-in and sign-up forms, and the season calendar.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ------------------------------------------------------------- server or static host
async function me() {
  try {
    const r = await api("api/me");
    const json = (r.headers.get("Content-Type") || "").includes("json");
    if (r.status === 200 && json) return { server: true, user: (await r.json()).user };
    if (r.status === 401 && json) return { server: true, user: null };
  } catch (e) { /* static hosting, or the server is unreachable */ }
  return { server: false, user: null };
}

function safeNext() {
  const n = new URLSearchParams(location.search).get("next") || PAGES.app;
  return /^[\w./?=&%-]*$/.test(n) && !n.startsWith("//") ? n : PAGES.app;
}

function linkPages() {
  const map = { login: PAGES.login, signup: PAGES.signup, app: PAGES.app, demo: PAGES.demo, "./": PAGES.home };
  document.querySelectorAll("a[href]").forEach((a) => {
    const h = a.getAttribute("href");
    if (h in map) a.setAttribute("href", map[h]);
    else if (h.startsWith("demo#")) a.setAttribute("href", PAGES.demo + h.slice(4));     // a view inside the recorded season
  });
  document.querySelectorAll("a.logo").forEach((a) => a.setAttribute("href", PAGES.home));
}

async function nav() {
  const st = await me();
  const box = $("navAuth");
  if (!st.server) {
    // Static copy (for example GitHub Pages): accounts need the WorldLab server.
    document.querySelectorAll("[data-needs-server]").forEach((a) => {
      if (a.closest(".cta")) { a.textContent = "Run it locally"; a.href = "https://github.com/MoAmrYehia/WorldLab#quick-start"; a.title = "The hosted server isn't available right now; run WorldLab on your own computer"; }
      else a.remove();
    });
    if (box) box.innerHTML = `<a class="btn solid" href="${PAGES.demo}">Watch a season</a>`;
    return;
  }
  if (st.user && box) {
    box.innerHTML = `<span class="who">${esc(st.user.name)}</span><a class="btn solid" href="${PAGES.app}">Open your farm</a>`;
    document.querySelectorAll(".cta [data-needs-server]").forEach((a) => { a.textContent = "Open your farm"; a.href = PAGES.app; });
  }
}

// ------------------------------------------------------------- forms
function authForm() {
  const f = $("authForm");
  if (!f) return;
  const mode = f.dataset.mode;
  const next = safeNext();
  const swap = $("swapLink");
  if (swap && next !== PAGES.app) swap.href += `?next=${encodeURIComponent(next)}`;
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("err"); err.hidden = true;
    const body = Object.fromEntries(new FormData(f).entries());
    if (mode === "signup" && (body.password || "").length < 8) { err.textContent = "Use a password of at least 8 characters."; err.hidden = false; $("password").focus(); return; }
    const btn = $("submit"); btn.disabled = true; const label = btn.textContent; btn.textContent = mode === "signup" ? "Creating your account…" : "Logging in…";
    try {
      const r = await apiJson(`api/auth/${mode}`, { method: "POST", body });
      const d = r.data;
      if (!r.ok || !d.ok) throw new Error(d.error || "Something went wrong. Try again.");
      setToken(d.token);
      location.href = next;
    } catch (ex) {
      err.textContent = ex.message === "Failed to fetch" ? "Can't reach the WorldLab server. Check your connection and try again." : ex.message;
      err.hidden = false; btn.disabled = false; btn.textContent = label;
    }
  });
}

// ------------------------------------------------------------- season calendar
const MLEN = [31, 30, 31, 31, 28, 31, 30, 31, 30, 31, 31, 30];   // the simulator's calendar, from 1 October
function dateOf(d) {
  let m = 0; d = Math.max(0, Math.round(d));
  while (m < 11 && d >= MLEN[m]) { d -= MLEN[m]; m++; }
  return `${d + 1} ${MONTHS[m]}`;
}
const MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"];
const MONTH_START = [0, 31, 61, 92, 123, 151, 182, 212, 243, 273, 304, 335, 365];
async function calendar() {
  const box = $("calendar");
  if (!box) return;
  let data;
  try { data = await (await fetch("seasons.json")).json(); } catch (e) { box.textContent = "The season calendar could not load."; return; }
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const order = { autumn: 0, winter: 1, late_winter: 2 };
  const crops = [...data.crops].sort((a, b) => order[a.windows[0].season] - order[b.windows[0].season] || a.windows[0].sow[0] - b.windows[0].sow[0]);
  const L = 132, R = 12, T = 30, rowH = 30, W = 1080, H = T + crops.length * rowH + 14;
  const X = (d) => L + (d / 365) * (W - L - R);
  let s = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  // summer: fields rest
  s += `<defs><pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" stroke="${css("--line")}" stroke-width="3"/></pattern></defs>`;
  s += `<rect x="${X(273)}" y="${T - 6}" width="${X(365) - X(273)}" height="${H - T}" fill="url(#hatch)"/>`;
  s += `<text x="${(X(273) + X(365)) / 2}" y="${T + crops.length * rowH / 2}" text-anchor="middle" font-size="13" fill="${css("--ink-3")}">Fields rest</text>`;
  MONTHS.forEach((m, i) => {
    s += `<line x1="${X(MONTH_START[i])}" x2="${X(MONTH_START[i])}" y1="${T - 6}" y2="${H - 8}" stroke="${css("--line")}"/>`;
    s += `<text x="${(X(MONTH_START[i]) + X(MONTH_START[i + 1])) / 2}" y="${T - 12}" text-anchor="middle" font-size="12.5" fill="${css("--ink-3")}">${m}</text>`;
  });
  crops.forEach((c, k) => {
    const y = T + k * rowH;
    s += `<text x="0" y="${y + rowH / 2 + 4}" font-size="14" fill="${css("--ink")}">${esc(c.label)}</text>`;
    c.windows.forEach((w) => {
      const col = css(`--s-${w.season}`);
      const sowMid = (w.sow[0] + w.sow[1]) / 2;
      if (w.cycle_days) s += `<rect x="${X(sowMid)}" y="${y + 11}" width="${Math.max(2, X(Math.min(sowMid + w.cycle_days, 272)) - X(sowMid))}" height="8" rx="4" fill="${css("--ink")}" opacity="0.14"><title>${esc(c.label)}: about ${w.cycle_days} days to harvest</title></rect>`;
      s += `<rect x="${X(w.sow[0])}" y="${y + 6}" width="${Math.max(6, X(w.sow[1]) - X(w.sow[0]))}" height="18" rx="5" fill="${col}"><title>${esc(c.label)}: sow ${dateOf(w.sow[0])} to ${dateOf(w.sow[1])}${w.cycle_days ? `, about ${w.cycle_days} days to harvest` : ""}</title></rect>`;
    });
  });
  s += "</svg>";
  box.innerHTML = s;
  const SEASON = Object.fromEntries(data.seasons.map((x) => [x.id, x.label]));
  if ($("calTable")) $("calTable").innerHTML = `<table><thead><tr><th>Crop</th><th>Sowing season</th><th>Sow between</th><th class="n">Days to harvest</th><th class="n">Typical yield, t/ha</th></tr></thead><tbody>${
    crops.flatMap((c) => c.windows.map((w) => `<tr><td>${esc(c.label)}</td><td>${esc(SEASON[w.season] || w.season)}</td><td>${dateOf(w.sow[0])} and ${dateOf(w.sow[1])}</td><td class="n">${w.cycle_days ?? "–"}</td><td class="n">${w.yield_t_ha_p50 < 0.1 ? (w.yield_t_ha_p50 > 0 ? "&lt;0.1" : "0") : w.yield_t_ha_p50}</td></tr>`)).join("")}</tbody></table><p class="fine">Typical yield: median across the six fields, published crop values, fresh weight.</p>`;
  $("calLegend").innerHTML = data.seasons.map((x) => `<span style="--c:var(--s-${x.id})">${esc(x.label)}</span>`).join("") + `<span class="grow">Growing to harvest, typical</span>`;
}

// ------------------------------------------------------------- nav shadow
function navShadow() {
  const n = document.querySelector(".nav");
  if (!n) return;
  const f = () => n.classList.toggle("scrolled", scrollY > 24);
  addEventListener("scroll", f, { passive: true }); f();
}

linkPages(); nav(); authForm(); calendar(); navShadow();
