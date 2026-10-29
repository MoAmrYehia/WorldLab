"""WorldLab command line.

  python -m worldlab serve                            dashboard at http://127.0.0.1:8765
  python -m worldlab run --perturb clog@90             headless run, prints the outcome
  python -m worldlab bench --farms 5                   benchmark agents across random farms
  python -m worldlab verify runs/<run>/ledger.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .session import Session, Settings


def _settings(a) -> Settings:
    return Settings(agent=a.agent, seed=a.seed, speed=a.speed, perturb=a.perturb or [],
                    perception=a.perception, runs_dir=a.runs_dir)


def main(argv=None):
    p = argparse.ArgumentParser(prog="worldlab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, speed):
        sp.add_argument("--agent", default="auto", choices=["auto", "spark", "glimmer", "scripted", "scripted-noadapt"],
                        help="auto = Muse Spark if MODEL_API_KEY is set, else the scripted baseline")
        sp.add_argument("--seed", type=int, default=7, help="which farm: hidden variety traits, drip systems, weather year")
        sp.add_argument("--speed", type=float, default=speed, help="season pacing, simulated days per second (0 = flat out)")
        sp.add_argument("--perturb", action="append",
                        help="hidden change, e.g. clog@90, pest@110:F2, salinity@70, heatwave@175 (day 0 = 1 Oct)")
        sp.add_argument("--perception", default="auto", choices=["auto", "meta", "sim", "none"])
        sp.add_argument("--runs-dir", default="runs")

    s = sub.add_parser("serve", help="run the live dashboard")
    common(s, 12.0)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--http-port", type=int, default=8765)
    s.add_argument("--start", action="store_true", help="start a run immediately")
    s.add_argument("--open", action="store_true", help="open the browser")

    r = sub.add_parser("run", help="one headless run")
    common(r, 0.0)

    b = sub.add_parser("bench", help="benchmark agents across random farms")
    b.add_argument("--farms", type=int, default=5)
    b.add_argument("--agents", default="scripted,scripted-noadapt,scripted-notrials")
    b.add_argument("--scenarios", default="none,clog,pest,salinity,heatwave")
    b.add_argument("--out", default="runs/bench")
    b.add_argument("--workers", type=int, default=0)

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
            time.sleep(0.5)
            ev = sess.lab.ledger.entries
            for e in ev[last:]:
                if e["kind"] in ("hypothesis", "trial_result", "plan", "anomaly", "field_test", "conclusion",
                                 "harvest", "season_result", "run_end"):
                    print(f"day {e['t']:>3}  {e['kind']:<14} {json.dumps(e['data'], default=str)[:160]}")
            last = len(ev)
        if sess.error:
            print(sess.error, file=sys.stderr)
            sys.exit(1)
    elif a.cmd == "bench":
        from .bench import run_bench
        run_bench(a.farms, a.agents.split(","), a.scenarios.split(","), a.out, workers=a.workers)
    elif a.cmd == "verify":
        from .ledger import verify
        ok, msg = verify(a.ledger)
        print(msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
