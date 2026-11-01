"""WorldLab website and API server: standard library only.

Pages
GET  /                  landing page
GET  /login, /signup    account pages
GET  /app               the 3D farm app (requires an account)
GET  /demo              a recorded season, no account needed
GET  /classic.html      the earlier 2D dashboard

Accounts
POST /api/auth/signup   {name, email, password}
POST /api/auth/login    {email, password}
POST /api/auth/logout
GET  /api/me
Sessions use an HttpOnly cookie on the same site, or "Authorization: Bearer <token>" from another
site listed in WORLDLAB_ALLOWED_ORIGINS (for example the GitHub Pages copy of the website).

Farm (each account has its own farm and run)
GET  /api/seasons                  sowing seasons and which crops fit each
GET  /api/crop-guide?season=ID     per-crop guide with a model preview per field
GET  /api/state                    snapshot of your current run
GET  /api/stream                   server-sent events for live updates
POST /api/start                    {agent, speed, choices: [{mode, crop, season}] x 6}
POST /api/perturb                  {kind, field}  (hidden from the agent: clog, pest, salinity, heatwave)
POST /api/stop
POST /api/speed                    {speed}
GET  /api/verify                   verify your run's ledger hash chain
GET  /api/runs                     your past seasons
GET  /api/progress                 level, XP and achievements (awarded from each season's ledger)
GET  /api/runs/ID/replay           a past season as a replay
GET  /api/scenarios                the scenario library and the farm editor's allowed ranges
POST /api/decide                   {request, choice} answer a decision in human decision mode
POST /api/runs/ID/branch           {change} rerun a finished season with one input changed
POST /api/runs/ID/next             start the next season on the soil this one left behind
POST /api/runs/ID/share            make a public read-only snapshot link
GET  /api/shared/TOKEN             a shared snapshot (no account needed)
"""
from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
from dataclasses import asdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .accounts import Accounts, AuthError, SESSION_DAYS, BEARER_SESSION_S
from .lab import Bus
from .ledger import verify
from .session import Session, Settings

HERE = Path(__file__).parent
APP = HERE / "dashboard"
SITE = HERE / "site"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
         ".jpg": "image/jpeg", ".webmanifest": "application/manifest+json", ".gz": "application/gzip",
         ".zip": "application/zip", ".txt": "text/plain; charset=utf-8", ".py": "text/plain; charset=utf-8"}
STATIC = {name: APP / name for name in ("app.js", "client.js", "scene.js", "style.css", "replay.json", "experiments.json", "classic.html")}
# the recorded season's offline evidence bundle (complete raw ledger, manifest, verifier)
STATIC.update({f"evidence/{n}": APP / "evidence" / n for n in ("manifest.json", "ledger.jsonl.gz", "verify_evidence.py", "README.txt",
                                                               "worldlab-evidence.zip")})
STATIC.update({name: SITE / name for name in ("site.css", "site.js", "hero.js", "favicon.svg", "seasons.json", "favicon.ico",
                                               "apple-touch-icon.png", "icon-192.png", "icon-512.png", "og-image.jpg", "site.webmanifest", "hero-still.jpg")})
PAGES = {"/": SITE / "index.html", "/login": SITE / "login.html", "/signup": SITE / "signup.html",
         "/demo": APP / "index.html", "/app": APP / "index.html"}
COOKIE = "wl_session"


def release_info() -> dict:
    """Which source this server runs: worldlab/release.json written by the release workflow, else git, else unknown."""
    for var in ("WORLDLAB_RELEASE_SHA", "RENDER_GIT_COMMIT"):          # set by the host when it builds from git
        if os.environ.get(var):
            return {"sha": os.environ[var], "source": var}
    f = Path(__file__).resolve().parent / "release.json"
    if f.is_file():
        try:
            return json.loads(f.read_text())
        except ValueError:
            pass
    try:
        import subprocess
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3,
                             cwd=Path(__file__).resolve().parent).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "."], capture_output=True, text=True, timeout=3,
                                    cwd=Path(__file__).resolve().parent).stdout.strip())
        return {"sha": sha or None, "source": "git working tree", "dirty": dirty}
    except Exception:
        return {"sha": None, "source": "unknown"}


def allowed_origins() -> set[str]:
    """Sites (for example the GitHub Pages copy) allowed to call this API from the browser."""
    return {o.strip().rstrip("/") for o in os.environ.get("WORLDLAB_ALLOWED_ORIGINS", "").split(",") if o.strip()}
AGENTS = ("scripted-rl", "scripted", "scripted-noadapt", "spark", "glimmer")


def _clean(o):
    """JSON has no NaN/Infinity; send null instead so browsers can parse it."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def dumps(o) -> str:
    return json.dumps(_clean(o), default=str)


class Slot:
    """One account's farm: an event bus that outlives runs, and the current run."""

    def __init__(self):
        self.bus = Bus()
        self.session: Session | None = None
        self.run_id: int | None = None


class App:
    def __init__(self, defaults: Settings, data_dir: str | Path = "data", max_runs: int | None = None):
        self.defaults = defaults
        self.data_dir = Path(data_dir)
        self.accounts = Accounts(self.data_dir / "worldlab.db")
        self.slots: dict[int, Slot] = {}
        self.lock = threading.Lock()
        self.max_runs = max_runs or int(os.environ.get("WORLDLAB_MAX_RUNS", "3"))
        self.reserved: set[int] = set()            # users whose start is being set up (counted as active)
        self.started = time.time()
        self.guest_hits: dict[str, list[float]] = {}
        # inference budget: Muse Spark seasons per day (all accounts) and per guest; guests' total seasons
        self.spark_daily = int(os.environ.get("WORLDLAB_SPARK_DAILY", "40"))
        self.guest_spark_daily = int(os.environ.get("WORLDLAB_GUEST_SPARK_DAILY", "25"))
        self.guest_runs = int(os.environ.get("WORLDLAB_GUEST_RUNS", "3"))
        self.guests_enabled = os.environ.get("WORLDLAB_GUESTS", "1") != "0"

    def day_start(self) -> float:
        now = time.time()
        return now - now % 86400                      # midnight UTC

    def spark_left(self, guest: bool) -> int:
        since = self.day_start()
        left = self.spark_daily - self.accounts.count_runs(since, "spark")
        if guest:
            guests = self.db_guest_spark(since)
            left = min(left, self.guest_spark_daily - guests)
        return max(0, left)

    def db_guest_spark(self, since: float) -> int:
        return int(self.accounts.db.execute(
            "SELECT COUNT(*) FROM runs r JOIN users u ON u.id = r.user_id WHERE r.created >= ? AND r.agent = 'spark' AND u.email LIKE ?",
            (since, "%" + self.accounts.GUEST_DOMAIN)).fetchone()[0])

    def ready(self) -> dict:
        """Public readiness: what works right now, no secrets."""
        key = bool(os.environ.get("MODEL_API_KEY"))
        return {"ready": True, "service": "worldlab", "uptime_s": round(time.time() - self.started),
                "version": os.environ.get("WORLDLAB_VERSION") or None, "release": release_info(),
                "models": {"muse_spark": key, "sam_3_1": key, "muse_glimmer": bool(os.environ.get("WORLDLAB_GLIMMER_BASE_URL"))},
                "capacity": {"runs_active": self.active_runs(), "run_capacity": self.max_runs, "busy": self.active_runs() >= self.max_runs},
                "guests": {"enabled": self.guests_enabled, "seasons_per_guest": self.guest_runs,
                           "muse_spark_seasons_left_today": self.spark_left(True) if key else 0}}

    def slot(self, user_id: int) -> Slot:
        with self.lock:
            return self.slots.setdefault(user_id, Slot())

    def active_runs(self) -> int:
        return sum(1 for s in self.slots.values() if s.session and s.session.alive())

    def start(self, user: dict, body: dict) -> dict:
        slot = self.slot(user["id"])
        agent = body.get("agent") or self.defaults.resolved_agent()
        if agent not in AGENTS:
            raise ValueError(f"unknown agent {agent!r}")
        from .lab import normalize_choices
        normalize_choices(body.get("choices") or [])          # reject impossible picks before touching the farm
        if agent == "spark" and not os.environ.get("MODEL_API_KEY"):
            raise ValueError("Muse Spark needs MODEL_API_KEY on the server. Choose the scripted scientist instead.")
        guest = Accounts.is_guest(user)
        since = self.day_start()
        if guest and self.accounts.count_runs(0, user_id=user["id"]) >= self.guest_runs:
            raise RuntimeError(f"Guest sessions can run {self.guest_runs} seasons. Sign up to run more, or watch the recorded season.")
        if agent == "spark" and self.spark_left(guest) <= 0:
            raise RuntimeError("Today's Muse Spark budget on this server is used up. The scripted scientist is still available, "
                               "and the recorded Muse Spark season is always available.")
        with self.lock:                               # admission is atomic: check and reserve under one lock
            if user["id"] in self.reserved:
                raise RuntimeError("A season is already starting for this account.")
            busy = bool(slot.session and slot.session.alive())
            others = self.active_runs() - (1 if busy else 0) + len(self.reserved)
            if others >= self.max_runs:
                raise RuntimeError("The farm simulator is busy with other seasons. Try again in a few minutes.")
            self.reserved.add(user["id"])
        try:
            return self._start(user, body, slot, agent, busy)
        finally:
            with self.lock:
                self.reserved.discard(user["id"])

    def _start(self, user: dict, body: dict, slot: "Slot", agent: str, busy: bool) -> dict:
        if busy:
            slot.session.stop()
            slot.session.thread.join(timeout=10)
        speed = float(body.get("speed", self.defaults.speed))
        s = Settings(**{**asdict(self.defaults), "agent": agent, "speed": max(0.5, min(speed, 60.0)),
                        "runs_dir": str(self.data_dir / "runs" / str(user["id"])),
                        "choices": body.get("choices") or [], "perturb": []})
        # scenario library and farm editor, validated here whatever the browser sent
        from . import scenarios as SC
        sc = SC.BY_ID.get(body.get("scenario") or "baseline")
        if sc is None:
            raise ValueError("unknown scenario")
        if sc["id"] == "mystery":                       # drawn now, from the operating system's randomness; revealed after the season
            import random
            _, specs = SC.draw_challenge(random.SystemRandom())
            s.scenario, s.perturb = sc["id"], specs
        else:
            s.scenario, s.perturb = sc["id"], list(sc["perturb"])
        s.weather = sc.get("weather")
        s.limits = {**s.limits, **sc["limits"]}
        s.salinity_scale = sc["salinity_scale"]
        ed = body.get("farm") or {}
        if "seed" in ed:
            s.seed = int(SC.clamp("seed", ed["seed"]))
        for k in ("water_quota_m3", "energy_kwh"):
            if k in ed:
                s.limits[k] = SC.clamp(k, ed[k])
        if "salinity_scale" in ed:
            s.salinity_scale = SC.clamp("salinity_scale", ed["salinity_scale"])
        s.human = bool(body.get("human"))
        for k in ("soil", "parent_run", "change"):            # set only by branch and next-season requests
            if k in body:
                setattr(s, k, body[k])
        slot.bus.record_to(None)                         # stop recording into the previous season's log
        slot.bus.reset()
        slot.bus.publish("reset", {"agent": agent})
        sess = Session(s, bus=slot.bus)                  # raises ValueError for an impossible crop choice
        run_id = self.accounts.add_run(user["id"], str(sess.run_dir), agent, sess.lab.choices_summary(),
                                       {k: v for k, v in asdict(s).items() if k not in ("runs_dir",)}, s.parent_run)
        sess.on_finish = lambda ss: self._finish(user, run_id, ss)
        slot.session, slot.run_id = sess, run_id
        sess.start()
        return {"ok": True, "agent": agent, "run_id": run_id}

    BRANCH_CHANGES = {"controller", "fault", "crop", "seed", "human"}

    def branch(self, user: dict, run_id: int, change: dict) -> dict:
        """Rerun a season from the start with exactly one input changed: same farm seed, weather, scenario
        and choices otherwise, so the two outcomes form a paired comparison. Exact mid-season checkpoints
        aren't stored, so the whole season is rerun."""
        r = self.accounts.run(user["id"], run_id)
        if not r:
            raise ValueError("run not found")
        st = json.loads(r["settings"] or "{}")
        kind = (change or {}).get("kind")
        if kind not in self.BRANCH_CHANGES:
            raise ValueError("change one of: controller, fault, crop, seed, human")
        body = {"agent": r["agent"], "choices": st.get("choices") or [], "scenario": st.get("scenario") or "baseline",
                "farm": {"seed": st.get("seed", 7), "salinity_scale": st.get("salinity_scale", 1.0),
                         **{k: v for k, v in (st.get("limits") or {}).items() if k in ("water_quota_m3", "energy_kwh")}},
                "human": st.get("human", False), "parent_run": run_id, "speed": st.get("speed", 12)}
        if st.get("soil"):
            body["soil"] = st["soil"]
        if kind == "controller":
            body["agent"] = "scripted" if r["agent"] == "scripted-rl" else "scripted-rl"
            label = f"irrigation by {'the fixed rule' if body['agent'] == 'scripted' else 'the learned policy'}"
        elif kind == "fault":
            body["scenario"] = "baseline"
            label = "no hidden events"
        elif kind == "seed":
            body["farm"]["seed"] = int(SC_clamp_seed(change.get("value", st.get("seed", 7) + 1)))
            label = f"farm seed {body['farm']['seed']}"
        elif kind == "human":
            body["human"] = not st.get("human", False)
            label = "human decision mode " + ("on" if body["human"] else "off")
        else:
            fld, cr, season = change.get("field"), change.get("crop"), change.get("season")
            ch = list(body["choices"]) if body["choices"] else [{"mode": "scientist"}] * 6
            fi = ["F1", "F2", "F3", "F4", "F5", "F6"].index(str(fld).upper())
            ch = [dict(c) if isinstance(c, dict) else {"mode": "scientist"} for c in ch]
            ch[fi] = {"mode": "crop", "crop": cr, "season": season} if cr else {"mode": "scientist"}
            body["choices"] = ch
            label = f"{fld}: {cr or 'scientist decides'}"
        body["change"] = {"kind": kind, "label": label}
        return self.start(user, body)

    def next_season(self, user: dict, run_id: int) -> dict:
        """The next season on the same farm, starting from the salt this season left in the soil."""
        r = self.accounts.run(user["id"], run_id)
        if not r or not r["result"]:
            raise ValueError("finish the season first")
        soil_file = Path(r["run_dir"]) / "soil_end.json"
        if not soil_file.exists():
            raise ValueError("this season's end soil wasn't saved")
        st = json.loads(r["settings"] or "{}")
        return self.start(user, {"agent": r["agent"], "choices": st.get("choices") or [], "scenario": "baseline",
                                 "farm": {"seed": st.get("seed", 7)}, "soil": json.loads(soil_file.read_text()),
                                 "parent_run": run_id, "change": {"kind": "next_season", "label": "next season on the same soil"},
                                 "human": st.get("human", False)})

    def _finish(self, user: dict, run_id: int, sess: Session):
        """Score the season from its ledger and apply it to the player's progress (once per scenario)."""
        from .progression import evaluate, award, scenario_key
        ev = evaluate(sess.lab.ledger.entries, list(sess.farm.events), sess.lab.result)
        ev["run_status"] = sess.lab.run_status
        out = None
        if ev["complete"] and sess.lab.run_status == "completed":       # failed, stopped or mixed seasons earn nothing
            key = scenario_key(sess.settings.seed, sess.lab.choices_summary())
            out = award(self.accounts.progress(user["id"]), ev, key)
            self.accounts.save_progress(user["id"], out["progress"])
            out = {k: v for k, v in out.items() if k != "progress"}
            sess.bus.publish("award", {**out, "run_id": run_id, "evaluation": ev})
        self.accounts.finish_run(run_id, sess.lab.result, {"evaluation": ev, "run_status": sess.lab.run_status,
                                                           "run_end_reason": sess.lab.run_end_reason, **(out or {})})

    def progress(self, user: dict) -> dict:
        from .progression import level_for, ACHIEVEMENTS
        p = self.accounts.progress(user["id"])
        return {"level": level_for(p.get("xp", 0)), "achievements": p.get("achievements", {}),
                "best_people": p.get("best_people"), "seasons": p.get("seasons", 0),
                "catalog": [{"id": k, "title": v[0], "about": v[1]} for k, v in ACHIEVEMENTS.items()]}

    def info(self, user: dict) -> dict:
        slot = self.slot(user["id"])
        s = slot.session
        return {"running": bool(s and s.alive()), "agent": s.agent_kind if s else self.defaults.resolved_agent(),
                "speed": s.lab.speed if s else self.defaults.speed, "run_id": slot.run_id,
                "error": s.error if s else None, "has_api_key": bool(os.environ.get("MODEL_API_KEY")),
                "user": {"name": user["name"], "email": user["email"]},
                "choices": s.lab.choices_summary() if s else None}


def SC_clamp_seed(v):
    from .scenarios import clamp
    return clamp("seed", v)


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "WorldLab"

        def log_message(self, *a):
            pass

        # ------------------------------------------------------------ helpers
        def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in self._cors().items():
                self.send_header(k, v)
            for k, v in (headers or {}).items():
                if isinstance(v, list):
                    for x in v:
                        self.send_header(k, x)
                else:
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200, headers=None):
            self._send(code, dumps(obj).encode(), "application/json", headers)

        def _file(self, path: Path):
            body = path.read_bytes()
            extra = None
            if path.suffix == ".html":                      # pages run only their own and the pinned three.js scripts
                from .csp import policy
                extra = {"Content-Security-Policy": policy(body.decode("utf-8", "replace")) + "; frame-ancestors 'self'"}
            self._send(200, body, TYPES.get(path.suffix, "application/octet-stream"), extra)

        def _redirect(self, to: str):
            self._send(302, b"", "text/plain", {"Location": to})

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n or n > 100_000:
                return {}
            try:
                d = json.loads(self.rfile.read(n).decode() or "{}")
                return d if isinstance(d, dict) else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}

        def _cors(self) -> dict:
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and origin in allowed_origins():
                return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true", "Vary": "Origin"}
            return {}

        def _bearer(self):
            auth = self.headers.get("Authorization") or ""
            return auth[7:].strip() if auth.startswith("Bearer ") else None

        def _token(self):
            b = self._bearer()
            if b:
                return b
            c = SimpleCookie(self.headers.get("Cookie") or "")
            return c[COOKIE].value if COOKIE in c else None

        def _user(self):
            return app.accounts.user_for(self._token())

        def _secure(self) -> bool:
            return self.headers.get("X-Forwarded-Proto", "") == "https" or os.environ.get("WORLDLAB_SECURE_COOKIES") == "1"

        def _cookie(self, token: str | None) -> str:
            # SameSite=None (with Secure) lets login work inside an embedding page such as a Hugging Face Space;
            # POSTs are still refused unless their Origin matches this host.
            same = "None" if os.environ.get("WORLDLAB_COOKIE_SAMESITE") == "None" and self._secure() else "Lax"
            attrs = f"Path=/; HttpOnly; SameSite={same}" + ("; Secure" if self._secure() else "")
            if token is None:
                return f"{COOKIE}=; Max-Age=0; {attrs}"
            return f"{COOKIE}={token}; Max-Age={SESSION_DAYS * 86400}; {attrs}"

        def _same_origin(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin:
                return True
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
            return urlsplit(origin).netloc == host or origin.rstrip("/") in allowed_origins()

        def do_OPTIONS(self):
            cors = self._cors()
            if not cors:
                return self._send(403, b"", "text/plain")
            self._send(204, b"", "text/plain", {"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                                 "Access-Control-Allow-Headers": "Content-Type, Authorization",
                                                 "Access-Control-Max-Age": "600"})

        # ---------------------------------------------------------------- GET
        def do_GET(self):
            url = urlsplit(self.path)
            path = url.path.rstrip("/") or "/"
            q = parse_qs(url.query)
            if path in PAGES:
                user = self._user()
                if path == "/app" and not user and "guest" not in parse_qs(url.query):
                    return self._redirect("/login?next=/app" + (f"%3F{url.query}" if url.query else ""))
                if path in ("/login", "/signup") and user:
                    return self._redirect("/app")
                return self._file(PAGES[path])
            name = path.lstrip("/")
            if name in STATIC:
                return self._file(STATIC[name])
            if name.startswith("engine/") and name.endswith(".js") and "/" not in name[7:] and (APP / name).is_file():
                return self._file(APP / name)
            if path == "/api/seasons":
                from .farm.seasons import all_seasons
                return self._json(all_seasons())
            if path == "/api/crop-guide":
                from .farm.seasons import crop_guide, SEASON_IDS
                sid = (q.get("season") or [""])[0]
                if sid not in SEASON_IDS:
                    return self._json({"error": "unknown season"}, 400)
                return self._json(crop_guide(sid))
            if path == "/api/scenarios":
                from . import scenarios as SC
                return self._json({"scenarios": SC.public(), "editor": {k: list(v) for k, v in SC.EDITOR_RANGES.items()},
                                   "start_dates": ["1 Oct"], "note": "The season always starts on 1 October; the simulator's calendar is fixed."})
            if path.startswith("/api/shared/"):      # a public snapshot someone chose to share
                r = app.accounts.shared_run(path.rsplit("/", 1)[-1])
                if not r or not (Path(r["run_dir"]) / "events.jsonl").exists():
                    return self._json({"error": "not found"}, 404)
                from .replay import build
                return self._json(build(r["run_dir"], note="A shared WorldLab season, replayed read-only from its log."))
            if path in ("/api/ready", "/healthz"):     # readiness for deploy checks and the website, no secrets
                return self._json(app.ready())
            if path == "/api/capabilities":       # what this server can do right now, no account needed
                return self._json({"service": "ok", "schema": 2, "accounts": True,
                                   "agents": {"scripted": True, "scripted-rl": True,
                                              "spark": bool(os.environ.get("MODEL_API_KEY")),
                                              "glimmer": bool(os.environ.get("WORLDLAB_GLIMMER_BASE_URL"))},
                                   "perception": "meta" if os.environ.get("MODEL_API_KEY") else "simulated",
                                   "budget_mode": "hard", "run_capacity": app.max_runs,
                                   "runs_active": app.active_runs(),
                                   "busy": app.active_runs() >= app.max_runs,
                                   "guests": app.guests_enabled,
                                   "features": ["scenarios", "farm_editor", "human_mode", "branch", "next_season", "share", "guest", "handover"]})
            if path == "/api/me":
                user = self._user()
                return self._json({"user": user}, 200 if user else 401)
            if not path.startswith("/api/"):
                return self._json({"error": "not found"}, 404)
            user = self._user()
            if not user:
                return self._json({"error": "log in first", "login": "/login"}, 401)
            slot = app.slot(user["id"])
            if path == "/api/state":
                return self._json({"info": app.info(user), **slot.bus.snapshot})
            if path == "/api/verify":
                s = slot.session
                if not s:
                    return self._json({"ok": False, "message": "no run yet"})
                ok, msg = verify(s.run_dir / "ledger.jsonl")
                return self._json({"ok": ok, "message": msg})
            if path == "/api/progress":
                return self._json(app.progress(user))
            if path == "/api/runs":
                return self._json({"runs": app.accounts.runs(user["id"])})
            if path.startswith("/api/runs/") and path.endswith("/replay"):
                try:
                    rid = int(path.split("/")[3])
                except ValueError:
                    return self._json({"error": "bad run id"}, 400)
                r = app.accounts.run(user["id"], rid)
                if not r or not (Path(r["run_dir"]) / "events.jsonl").exists():
                    return self._json({"error": "run not found"}, 404)
                from .replay import build
                return self._json(build(r["run_dir"], note=f"Your season {rid}, replayed from its log."))
            if path == "/api/stream":
                return self._stream(slot)
            return self._json({"error": "not found"}, 404)

        def _stream(self, slot: Slot):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            for k, v in self._cors().items():
                self.send_header(k, v)
            self.end_headers()
            q = slot.bus.subscribe()
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                        batch = [msg]
                        while len(batch) < 200:
                            try:
                                batch.append(q.get_nowait())
                            except queue.Empty:
                                break
                        self.wfile.write(f"data: {dumps(batch)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                slot.bus.unsubscribe(q)

        # --------------------------------------------------------------- POST
        def do_POST(self):
            path = urlsplit(self.path).path.rstrip("/")
            # A request carrying a bearer token can't be forged by another site; a cookie-only one must be same-origin.
            if not self._same_origin() and not (self._bearer() and path not in ("/api/auth/signup", "/api/auth/login", "/api/auth/guest")):
                return self._json({"error": "cross-site request refused"}, 403)
            b = self._body()
            # the client address: forwarded headers are trusted only behind a configured proxy (Hugging Face sets one)
            client = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip() if os.environ.get("WORLDLAB_TRUST_PROXY") == "1" else "") \
                or self.client_address[0]
            if path == "/api/auth/guest":              # a short-lived guest session for trying a live season
                if not app.guests_enabled:
                    return self._json({"ok": False, "error": "Guest sessions are turned off on this server."}, 403)
                now = time.time()
                hits = [t for t in app.guest_hits.get(client, []) if now - t < 3600]
                if len(hits) >= 5:
                    return self._json({"ok": False, "error": "Too many guest sessions from this address. Try again later."}, 429)
                app.guest_hits[client] = hits + [now]
                user = app.accounts.guest()
                token = app.accounts.new_session(user["id"], seconds=4 * 3600)
                return self._json({"ok": True, "user": {**user, "guest": True}, "token": token, "expires_in_s": 4 * 3600},
                                  headers={"Set-Cookie": self._cookie(token)})
            if path in ("/api/auth/signup", "/api/auth/login"):
                try:
                    if path.endswith("signup"):
                        user = app.accounts.signup(b.get("email", ""), b.get("password", ""), b.get("name", ""))
                    else:
                        user = app.accounts.login(b.get("email", ""), b.get("password", ""), client)
                except AuthError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
                # a token handed to another origin lives in that page's storage, not an HttpOnly cookie: keep it short
                origin = self.headers.get("Origin") or ""
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
                life = BEARER_SESSION_S if origin and urlsplit(origin).netloc != host else None
                token = app.accounts.new_session(user["id"], seconds=life)
                return self._json({"ok": True, "user": user, "token": token, "expires_in_s": life or SESSION_DAYS * 86400},
                                  headers={"Set-Cookie": self._cookie(token)})
            if path == "/api/auth/logout":
                app.accounts.end_session(self._token())
                return self._json({"ok": True}, headers={"Set-Cookie": self._cookie(None)})
            user = self._user()
            if not user:
                return self._json({"ok": False, "error": "log in first"}, 401)
            slot = app.slot(user["id"])
            if path == "/api/start":
                try:
                    # soil, parent and change labels are set only by the branch and next-season routes
                    return self._json(app.start(user, {k: v for k, v in b.items() if k not in ("soil", "parent_run", "change")}))
                except RuntimeError as e:
                    return self._json({"ok": False, "error": str(e)}, 429)
                except (ValueError, TypeError) as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            s = slot.session
            if path == "/api/decide":
                if not s:
                    return self._json({"ok": False, "error": "No season is running."}, 400)
                r = s.lab.answer_decision(str(b.get("request", "")), str(b.get("choice", "")))
                return self._json(r, 200 if r["ok"] else 400)
            if path.startswith("/api/runs/") and path.rsplit("/", 1)[-1] in ("branch", "next", "share"):
                try:
                    rid = int(path.split("/")[3])
                except ValueError:
                    return self._json({"ok": False, "error": "bad run id"}, 400)
                act = path.rsplit("/", 1)[-1]
                try:
                    if act == "share":
                        tok = app.accounts.share_run(user["id"], rid)
                        if not tok:
                            return self._json({"ok": False, "error": "Only a finished season of yours can be shared."}, 400)
                        return self._json({"ok": True, "token": tok})
                    return self._json(app.branch(user, rid, b.get("change") or {}) if act == "branch" else app.next_season(user, rid))
                except RuntimeError as e:
                    return self._json({"ok": False, "error": str(e)}, 429)
                except (ValueError, TypeError, KeyError) as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            if path == "/api/perturb":
                if not s or s.lab.phase != "season":
                    return self._json({"ok": False, "error": "You can change the farm once the season has started."}, 400)
                from .farm.world import FIELDS
                fi = next((i for i, f in enumerate(FIELDS) if f["id"] == str(b.get("field", "")).upper()), None)
                try:
                    info = s.farm.perturb(b.get("kind", "clog"), field=fi)
                except ValueError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
                return self._json({"ok": True, **info})
            if path == "/api/handover":                    # continue a failed model-run season with the scripted protocol
                sess = slot.session
                if not sess or not sess.handover():
                    return self._json({"ok": False, "error": "Only a failed or timed-out season that is still in progress can be handed over."}, 409)
                return self._json({"ok": True})
            if path == "/api/stop":
                if s:
                    s.stop()
                return self._json({"ok": True})
            if path == "/api/speed":
                if s:
                    try:
                        s.lab.speed = max(0.5, min(float(b.get("speed", 12)), 60.0))
                    except (TypeError, ValueError):
                        return self._json({"ok": False, "error": "speed must be a number"}, 400)
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)

    return H


def serve(defaults: Settings, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False,
          data_dir: str | Path | None = None):
    app = App(defaults, data_dir or os.environ.get("WORLDLAB_DATA", "data"))
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"
    print(f"WorldLab: {url}")
    print(f"default agent: {defaults.resolved_agent()}   data: {app.data_dir.resolve()}")
    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for s in app.slots.values():
            if s.session:
                s.session.stop()
        httpd.server_close()
    return app
