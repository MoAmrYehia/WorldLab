"""WorldLab command line.

  python -m worldlab serve                     dashboard at http://127.0.0.1:8765
  python -m worldlab run --perturb fan_moved@2400   headless run, prints the outcome
  python -m worldlab bench --worlds 8          benchmark agents across random worlds
  python -m worldlab verify runs/<run>/ledger.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .session import Session, Settings


def _settings(a) -> Settings:
    goal = {}
    if a.target is not None:
        goal["target_C"] = a.target
    if a.hold is not None:
        goal["hold_s"] = a.hold
    if a.budget is not None:
        goal["task_budget_J"] = a.budget
    return Settings(agent=a.agent, rig=a.rig, serial_port=a.port or "", camera_index=a.camera,
                    speed=a.speed, seed=a.seed, randomize=a.randomize, perturb=a.perturb or [],
                    perception=a.perception, runs_dir=a.runs_dir, goal=goal)


def main(argv=None):
    p = argparse.ArgumentParser(prog="worldlab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--agent", default="auto", choices=["auto", "spark", "glimmer", "scripted", "scripted-noadapt"],
                        help="auto = Muse Spark if MODEL_API_KEY is set, else the scripted baseline")
        sp.add_argument("--rig", default="sim", choices=["sim", "serial"])
        sp.add_argument("--port", help="serial port for the hardware rig, e.g. COM3 or /dev/ttyACM0")
        sp.add_argument("--camera", type=int, default=-1, help="hardware rig camera index (OpenCV), -1 = none")
        sp.add_argument("--seed", type=int, default=7)
        sp.add_argument("--randomize", action="store_true", help="randomise the hidden physics (simulator)")
        sp.add_argument("--perturb", action="append", help="simulator change, e.g. fan_moved@2400 (rig seconds)")
        sp.add_argument("--perception", default="auto", choices=["auto", "meta", "sim", "none"])
        sp.add_argument("--runs-dir", default="runs")
        sp.add_argument("--target", type=float, help="goal temperature, C (default 42)")
        sp.add_argument("--hold", type=float, help="seconds to hold the target (default 1200)")
        sp.add_argument("--budget", type=float, help="task fan-energy budget, J (default 1500)")

    s = sub.add_parser("serve", help="run the live dashboard")
    common(s)
    s.add_argument("--speed", type=float, default=20.0, help="simulator pacing, x real time")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--http-port", type=int, default=8765)
    s.add_argument("--start", action="store_true", help="start a run immediately")
    s.add_argument("--open", action="store_true", help="open the browser")

    r = sub.add_parser("run", help="one headless run")
    common(r)
    r.add_argument("--speed", type=float, default=0.0)

    b = sub.add_parser("bench", help="benchmark agents across randomised worlds")
    b.add_argument("--worlds", type=int, default=6)
    b.add_argument("--agents", default="scripted,scripted-noadapt")
    b.add_argument("--scenarios", default="none,fan_moved,heater_drift,ambient_step")
    b.add_argument("--out", default="runs/bench")

    v = sub.add_parser("verify", help="verify a ledger's hash chain")
    v.add_argument("ledger")

    a = p.parse_args(argv)
    if a.cmd == "serve":
        from .server import serve
        serve(_settings(a), host=a.host, port=a.http_port, autostart=a.start, open_browser=a.open)
    elif a.cmd == "run":
        sess = Session(_settings(a))
        print(f"agent {sess.agent_kind} · run folder {sess.run_dir}")
        sess.start()
        last = 0
        while sess.alive():
            time.sleep(1.0)
            ev = sess.lab.ledger.entries
            for e in ev[last:]:
                if e["kind"] in ("hypothesis", "experiment_result", "model_update", "anomaly", "conclusion", "plan_result", "run_end"):
                    print(f"{e['t']:>7}  {e['kind']:<18} {json.dumps(e['data'], default=str)[:150]}")
            last = len(ev)
        if sess.error:
            print(sess.error, file=sys.stderr)
            sys.exit(1)
    elif a.cmd == "bench":
        from .bench import run_bench
        run_bench(a.worlds, a.agents.split(","), a.scenarios.split(","), a.out)
    elif a.cmd == "verify":
        from .ledger import verify
        ok, msg = verify(a.ledger)
        print(msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
