// Talks to the WorldLab server, wherever it runs.
// Served by the Python server itself: same origin, no config needed.
// Served from GitHub Pages: config.js sets window.WORLDLAB.api to the server (for example a Hugging Face Space),
// and the session token travels in an Authorization header instead of a cookie.
const cfg = window.WORLDLAB || {};
export const API = cfg.api ? cfg.api.replace(/\/*$/, "/") : "";
export const PAGES = {
  home: cfg.home ?? "./", login: cfg.login ?? "login", signup: cfg.signup ?? "signup",
  app: cfg.app ?? "app", demo: cfg.demo ?? "demo",
};
const KEY = "worldlab_token";

export function token() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
export function setToken(t) { try { if (t) localStorage.setItem(KEY, t); else localStorage.removeItem(KEY); } catch (e) { /* storage blocked */ } }

export function api(path, { method = "GET", body, headers = {}, ...rest } = {}) {
  const h = { ...headers };
  const t = token();
  if (t) h.Authorization = `Bearer ${t}`;
  if (body !== undefined) h["Content-Type"] = "application/json";
  return fetch(API + path, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body),
    credentials: API ? "include" : "same-origin", cache: "no-store", ...rest });
}

export async function apiJson(path, opts) {
  const r = await api(path, opts);
  let d = {};
  try { d = await r.json(); } catch (e) { /* empty body */ }
  return { status: r.status, ok: r.ok, data: d };
}

// Server-sent events over fetch, so the Authorization header can be sent. Reconnects on drop.
export function stream(path, onBatch, onReconnect) {
  let stopped = false;
  (async () => {
    let first = true;
    while (!stopped) {
      try {
        const r = await api(path, { headers: { Accept: "text/event-stream" } });
        if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
        if (!first && onReconnect) await onReconnect();
        first = false;
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let k;
          while ((k = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, k); buf = buf.slice(k + 2);
            const data = chunk.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
            if (data) { try { onBatch(JSON.parse(data)); } catch (e) { console.warn("bad event", e); } }
          }
        }
      } catch (e) { /* fall through to retry */ }
      if (!stopped) await new Promise((res) => setTimeout(res, 2500));
    }
  })();
  return () => { stopped = true; };
}

export function go(page, query = "") { location.href = PAGES[page] + query; }
