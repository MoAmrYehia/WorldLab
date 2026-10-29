"""Dashboard server: standard library only.

GET  /                 dashboard
GET  /api/state        snapshot of the current run
GET  /api/stream       server-sent events for live updates
POST /api/start        start a run      {agent, speed, seed, randomize, goal}
POST /api/perturb      change the world {kind}   (simulator only, hidden from the agent)
POST /api/stop         stop the run and put the rig in its safe state
POST /api/speed        {speed}          (simulator pacing)
GET  /api/verify       verify the ledger's hash chain
"""
from __future__ import annotations

import json
import math
import os
import queue
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .lab import Bus
from .ledger import verify
from .session import Session, Settings

STATIC = Path(__file__).parent / "dashboard"


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


class App:
    def __init__(self, defaults: Settings):
        self.defaults = defaults
        self.bus = Bus()
        self.session: Session | None = None
        self.lock = threading.Lock()

    def start(self, overrides: dict) -> dict:
        with self.lock:
            if self.session and self.session.alive():
                self.session.stop()
                self.session.thread.join(timeout=10)
            s = Settings(**{**asdict(self.defaults), **{k: v for k, v in overrides.items() if k in asdict(self.defaults)}})
            # fresh snapshot for the new run
            self.bus.snapshot.update({"samples": [], "events": [], "forecasts": [], "scene": None, "model": None,
                                      "plan": None, "status": {}, "agent": [], "fits": [],
                                      "perturbations": []})
            self.bus.publish("reset", {"agent": s.resolved_agent()})
            self.session = Session(s, bus=self.bus).start()
            return {"ok": True, "agent": self.session.agent_kind, "run_dir": str(self.session.run_dir),
                    "simulated": self.session.rig.caps.simulated}

    def info(self) -> dict:
        s = self.session
        return {
            "running": bool(s and s.alive()), "agent": s.agent_kind if s else self.defaults.resolved_agent(),
            "simulated": (s.rig.caps.simulated if s else self.defaults.rig == "sim"),
            "speed": getattr(s.rig, "speed", None) if s else self.defaults.speed,
            "run_dir": str(s.run_dir) if s else None, "error": s.error if s else None,
            "has_api_key": bool(os.environ.get("MODEL_API_KEY")),
            "perturbations": getattr(s.rig, "perturbations", []) if s else [],
        }


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode() or "{}")
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                data = (STATIC / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif path == "/api/state":
                self._json({"info": app.info(), **app.bus.snapshot})
            elif path == "/api/verify":
                s = app.session
                if not s:
                    return self._json({"ok": False, "message": "no run yet"})
                ok, msg = verify(s.run_dir / "ledger.jsonl")
                self._json({"ok": ok, "message": msg, "file": str(s.run_dir / "ledger.jsonl")})
            elif path == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q = app.bus.subscribe()
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
                            data = dumps(batch)
                            self.wfile.write(f"data: {data}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    app.bus.unsubscribe(q)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            path = self.path.split("?")[0]
            b = self._body()
            if path == "/api/start":
                try:
                    self._json(app.start(b))
                except Exception as e:
                    self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 400)
            elif path == "/api/perturb":
                s = app.session
                if not s or not hasattr(s.rig, "perturb"):
                    return self._json({"ok": False, "error": "perturbations need a running simulator"}, 400)
                try:
                    info = s.rig.perturb(b.get("kind", "fan_moved"))
                except ValueError as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
                self._json({"ok": True, **info})
            elif path == "/api/stop":
                if app.session:
                    app.session.stop()
                self._json({"ok": True})
            elif path == "/api/speed":
                if app.session and hasattr(app.session.rig, "speed"):
                    app.session.rig.speed = max(0.0, float(b.get("speed", 20)))
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)

    return H


def serve(defaults: Settings, host: str = "127.0.0.1", port: int = 8765, autostart: bool = False,
          open_browser: bool = False):
    app = App(defaults)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    url = f"http://{host}:{port}/"
    print(f"WorldLab dashboard: {url}")
    print(f"agent: {defaults.resolved_agent()}   rig: {defaults.rig}")
    if autostart:
        app.start({})
    if open_browser:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if app.session:
            app.session.stop()
            try:
                app.session.rig.safe_state()
            except Exception:
                pass
        httpd.server_close()
