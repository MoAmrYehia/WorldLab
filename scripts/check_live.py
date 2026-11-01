"""Check a deployed WorldLab server end to end. Exits non-zero on the first failure, and prints what it measured.

  python scripts/check_live.py https://moamryehia-worldlab.hf.space [--site https://moamryehia.github.io]
         [--release SHA] [--spark] [--full-spark] [--wait 900]

Always (scripted scientist, no model cost):
  1. readiness: /api/ready answers, and (with --release) reports exactly that release
  2. CORS: a guest session can be created from the website's origin
  3. a season starts, and the audit ledger keeps growing: at least 25 new entries and a plan or trial result,
     over at least two polls (a keep-alive or an idle "trials" phase is not progress)
  4. the event stream delivers ledger entries, and a second connection (a reconnect) delivers them too
  5. cancellation: /api/stop ends the run with status "cancelled"

With --spark (one bounded Muse Spark start; costs a few model calls):
  6. the run is decided by Muse Spark, an authenticated model call happens (the ledger shows a tool call made by the
     model) and a tool runs without error; then the run is cancelled. Fails if the server has no model key.

With --full-spark: as --spark, but waits (up to --spark-minutes) for the season to reach harvest with status
"completed" and checks the result and the run's ledger verification. This is the full public-path proof.
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
    if raw:
        return urllib.request.urlopen(r, timeout=timeout)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}"), dict(e.headers)
        except Exception:
            return e.code, {}, dict(e.headers)


def fail(msg):
    sys.exit(f"FAIL {msg}")


def state(base, tok, site):
    st, s, _ = req(base, "/api/state", None, tok, origin=site)
    if st != 200:
        fail(f"state: HTTP {st}")
    return s


def stream_entries(base, tok, site, seconds=12):
    """Read the event stream for a while; return the messages seen (keep-alive pings don't count)."""
    seen, t0 = [], time.time()
    try:
        resp = req(base, "/api/stream", None, tok, origin=site, timeout=seconds + 5, raw=True)
    except Exception as e:
        fail(f"stream: could not connect ({e})")
    try:
        while time.time() - t0 < seconds:
            line = resp.readline().decode("utf-8", "replace")
            if not line:
                break
            if line.startswith("data:"):
                try:
                    msgs = json.loads(line[5:])
                except ValueError:
                    continue
                seen += [m for m in (msgs if isinstance(msgs, list) else [msgs]) if isinstance(m, dict) and m.get("kind")]
    except Exception:
        pass
    finally:
        resp.close()
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--site", default="https://moamryehia.github.io")
    ap.add_argument("--release", default=None, help="the commit the server must report")
    ap.add_argument("--wait", type=float, default=600, help="seconds to wait for the server to become ready")
    ap.add_argument("--spark", action="store_true")
    ap.add_argument("--full-spark", action="store_true")
    ap.add_argument("--spark-minutes", type=float, default=60)
    a = ap.parse_args()
    base = a.base.rstrip("/")
    report = {"server": base}

    # 1. readiness
    t0, last, d = time.time(), None, {}
    while True:
        try:
            st, d, _ = req(base, "/api/ready")
            got = str((d.get("release") or {}).get("sha") or "")
            if st == 200 and d.get("ready") and (not a.release or got.startswith(a.release[:7])):
                break
            last = f"HTTP {st}, release {got[:7] or 'unknown'}"     # a host that builds from git may still be on the previous commit
        except Exception as e:
            last = e
        if time.time() - t0 > a.wait:
            fail(f"ready: {base}/api/ready not ready after {a.wait:.0f} s ({last})")
        time.sleep(10)
    ready = d
    rel = d.get("release") or {}
    print(f"ok   ready after {time.time() - t0:.0f} s: release {rel.get('sha')}, models {d.get('models')}, capacity {d.get('capacity')}")
    if a.release and not str(rel.get("sha") or "").startswith(a.release[:7]):
        fail(f"release: the server reports {rel.get('sha')!r}, expected {a.release[:12]}")
    report["release"] = rel.get("sha")

    # 2. CORS + guest
    st, g, hdr = req(base, "/api/auth/guest", {}, origin=a.site)
    allow = hdr.get("Access-Control-Allow-Origin")
    if st != 200 or "token" not in g:
        fail(f"guest: HTTP {st} {g}")
    if allow not in (a.site, "*"):
        fail(f"cors: Access-Control-Allow-Origin is {allow!r}; the website at {a.site} can't call the server")
    print(f"ok   guest session from the website's origin (CORS allows {allow})")
    tok = g["token"]

    # 3. a scripted season makes real progress
    st, d, _ = req(base, "/api/start", {"agent": "scripted", "speed": 60}, tok, origin=a.site)
    if st != 200 or not d.get("run_id"):
        fail(f"start: HTTP {st} {d}")
    print(f"ok   scripted season started: run {d['run_id']}")
    counts, kinds, t1 = [], set(), time.time()
    while time.time() - t1 < 240:
        s = state(base, tok, a.site)
        ev = s.get("events") or []
        counts.append(len(ev))
        kinds |= {e.get("kind") for e in ev}
        if len(counts) >= 2 and counts[-1] - counts[0] >= 25 and kinds & {"plan", "trial_result"}:
            break
        time.sleep(6)
    else:
        fail(f"progress: ledger entries over time {counts[:12]}, kinds {sorted(k for k in kinds if k)}; the season did not progress")
    print(f"ok   the run progresses: ledger {counts[0]} -> {counts[-1]} entries over {len(counts)} polls, reached {sorted(kinds & {'plan', 'trial_result', 'season_start'})}")

    # 4. stream, then a reconnect
    a1 = stream_entries(base, tok, a.site, 20)
    a2 = stream_entries(base, tok, a.site, 20)
    if not a1 or not a2:
        fail(f"stream: messages on first connection {len(a1)}, on reconnect {len(a2)}")
    print(f"ok   event stream delivers events ({len(a1)}: {sorted({m['kind'] for m in a1})[:5]}), and again after reconnecting ({len(a2)})")

    # 5. cancellation: a fresh, slow season, stopped while it runs
    st, d3, _ = req(base, "/api/start", {"agent": "scripted", "speed": 1}, tok, origin=a.site)
    if st != 200:
        fail(f"start for the cancellation check: HTTP {st} {d3}")
    for _ in range(20):
        if (state(base, tok, a.site).get("status") or {}).get("run_status") == "running":
            break
        time.sleep(2)
    req(base, "/api/stop", {}, tok, origin=a.site)
    for _ in range(20):
        rs = (state(base, tok, a.site).get("status") or {}).get("run_status")
        if rs == "cancelled":
            break
        time.sleep(3)
    else:
        fail(f"cancel: run status after stop is {rs!r}, expected 'cancelled'")
    print(f"ok   stop ends a running season as cancelled (run {d3.get('run_id')})")

    # 6. Muse Spark
    if a.spark or a.full_spark:
        if not (ready.get("models") or {}).get("muse_spark"):
            fail("spark: the server reports no Muse Spark key, so live Spark seasons are unavailable")
        g2 = req(base, "/api/auth/guest", {}, origin=a.site)[1]
        tok2 = g2.get("token")
        st, d2, _ = req(base, "/api/start", {"agent": "spark", "speed": 60}, tok2, origin=a.site)
        if st != 200:
            fail(f"spark start: HTTP {st} {d2}")
        print(f"ok   Muse Spark season started: run {d2.get('run_id')}")
        t2, called, ran = time.time(), None, None
        limit = a.spark_minutes * 60 if a.full_spark else 300
        while time.time() - t2 < limit:
            s = state(base, tok2, a.site)
            ev = s.get("events") or []
            steps = [e["data"] for e in ev if e.get("kind") == "agent_step"]
            called = called or next((x for x in steps if x.get("role") == "tool_call"), None)
            ran = ran or next((e for e in ev if e.get("kind") in ("plan", "hypothesis", "trial_start")), None)
            rs = (s.get("status") or {}).get("run_status")
            if rs in ("failed", "timeout"):
                fail(f"spark: the run ended {rs}: {(s.get('status') or {}).get('run_end_reason')}")
            if not a.full_spark and called and ran:
                break
            if a.full_spark and rs == "completed":
                break
            time.sleep(10)
        else:
            fail(f"spark: no model tool call and tool result within {limit / 60:.0f} min" if not a.full_spark
                 else f"spark: the season did not complete within {a.spark_minutes:.0f} min")
        print(f"ok   Muse Spark called a tool ({called.get('text') if called else '?'}) and the lab ran it ({ran['kind'] if ran else '?'})")
        if a.full_spark:
            res = (state(base, tok2, a.site).get("status") or {}).get("result") or {}
            v = req(base, "/api/verify", None, tok2, origin=a.site)[1]
            if not res.get("people_fed") or not v.get("ok"):
                fail(f"spark full season: result {res}, ledger verification {v}")
            print(f"ok   full Muse Spark season: {res.get('people_fed')} people fed, ledger verified ({v.get('message')})")
        else:
            req(base, "/api/stop", {}, tok2, origin=a.site)
            print("ok   Muse Spark run stopped after the bounded check")
    print("ok   live check passed")


if __name__ == "__main__":
    main()
