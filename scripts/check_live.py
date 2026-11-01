"""Check a deployed WorldLab server end to end: readiness, a guest session, a season that actually starts and
streams, and the CORS headers the website needs. Exits non-zero on the first failure.

  python scripts/check_live.py https://moamryehia-worldlab.hf.space [--site https://moamryehia.github.io] [--wait 600]
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def req(base, path, body=None, token=None, origin=None, timeout=20, raw=False):
    h = {"Content-Type": "application/json", "Origin": origin or base}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(), h)
    if raw:                                               # a stream: the caller reads and closes it
        return urllib.request.urlopen(r, timeout=timeout)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read()), dict(resp.headers)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--site", default="https://moamryehia.github.io")
    ap.add_argument("--wait", type=float, default=600, help="seconds to wait for the server to become ready")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    t0, last = time.time(), None
    while True:                                           # a new or sleeping Space takes minutes to build and start
        try:
            st, d, _ = req(base, "/api/ready")
            if st == 200 and d.get("ready"):
                break
        except Exception as e:
            last = e
        if time.time() - t0 > a.wait:
            sys.exit(f"FAIL ready: {base}/api/ready not ready after {a.wait:.0f} s ({last})")
        time.sleep(10)
    print(f"ok   ready after {time.time() - t0:.0f} s: models {d['models']}, capacity {d['capacity']}, guests {d['guests']}")
    st, g, hdr = req(base, "/api/auth/guest", {}, origin=a.site)
    allow = hdr.get("Access-Control-Allow-Origin")
    if allow not in (a.site, "*"):
        sys.exit(f"FAIL cors: Access-Control-Allow-Origin is {allow!r}, the website at {a.site} can't call the server")
    print(f"ok   guest session from the website's origin (CORS allows {allow})")
    tok = g["token"]
    st, d, _ = req(base, "/api/start", {"agent": "scripted", "speed": 60}, tok, origin=a.site)
    run = d.get("run_id")
    print(f"ok   season started: run {run}")
    resp = req(base, "/api/stream", None, tok, origin=a.site, timeout=20, raw=True)
    got = resp.readline().decode() + resp.readline().decode()
    resp.close()
    if "data" not in got and "ping" not in got:
        sys.exit(f"FAIL stream: nothing arrived ({got[:80]!r})")
    print("ok   event stream open (" + ("events arriving" if "data" in got else "keep-alive received") + ")")
    t1 = time.time()
    while time.time() - t1 < 180:
        st, s, _ = req(base, "/api/state", None, tok, origin=a.site)
        stt = s.get("status") or {}
        if stt.get("phase") in ("trials", "planned", "season", "harvested") or (stt.get("plots_used") or 0) > 0:
            break
        time.sleep(5)
    else:
        sys.exit("FAIL run: the season did not progress within 3 minutes")
    print(f"ok   the run progresses: phase {stt.get('phase')}, plots {stt.get('plots_used')}, run status {stt.get('run_status')}")
    req(base, "/api/stop", {}, tok, origin=a.site)
    print("ok   stopped; live check passed")


if __name__ == "__main__":
    main()
