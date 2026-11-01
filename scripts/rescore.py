"""Rescore archived benchmark runs with the current scorer, keeping the score they were published with.

  python scripts/rescore.py docs/bench/v2/runs docs/bench/holdout/runs

For each run directory (manifest.json + ledger.jsonl.gz): checks the ledger against the manifest's hash, rescores it
from the ledger and the realized events, stores the old score once as score_v<version> and the new one as score.
The ledger is never modified.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worldlab.benchscore import score, SCORER_VERSION           # noqa: E402


def realized(m: dict) -> list[dict]:
    """The realized events, with severity from the scheduled events (or the documented default) when the archive lacks it."""
    defaults = {"clog": 0.45, "pest": 0.03, "salinity": 9.0, "blight": 0.02, "sensor_bias": -0.06}
    sched = list(m.get("hidden_events") or [])
    out = []
    for i, e in enumerate(m.get("applied_events") or []):
        sev = e.get("severity")
        if sev is None and e["kind"] != "heatwave":
            match = next((s for s in sched if s["kind"] == e["kind"] and s.get("severity") is not None), None)
            sev = match["severity"] if match else defaults.get(e["kind"])
        out.append({**e, "severity": sev})
    return out


def main(dirs):
    n = 0
    for root in dirs:
        for mf in sorted(Path(root).glob("*/*/manifest.json")):
            m = json.loads(mf.read_text())
            gz = mf.parent / "ledger.jsonl.gz"
            if not gz.exists():
                print("no ledger:", mf.parent)
                continue
            raw = gzip.decompress(gz.read_bytes())
            want = (m.get("artifacts") or {}).get("ledger.jsonl.gz", {}).get("sha256")
            if want and hashlib.sha256(raw).hexdigest() != want:
                sys.exit(f"ledger hash mismatch: {gz}")
            entries = [json.loads(x) for x in raw.decode().splitlines() if x.strip()]
            old = m.get("score") or {}
            ov = old.get("scorer_version", "2.0")
            if ov != SCORER_VERSION:
                m.setdefault(f"score_v{ov.replace('.', '_')}", old)
            m["applied_events"] = realized(m)
            m["score"] = score(entries, m["applied_events"], m.get("label", ""))
            mf.write_text(json.dumps(m, indent=1, default=str))
            n += 1
    print(f"rescored {n} runs with scorer {SCORER_VERSION}")


if __name__ == "__main__":
    main(sys.argv[1:])
