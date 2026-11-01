"""Freeze the holdout challenge (P1.1): eight unfamiliar cases, generated once from a fixed seed and committed before any
run, so nothing is tuned against them.

  python scripts/make_holdout.py docs/bench/holdout/holdout_v1.json

Selection rules (written before the runs):
  - new farm seeds 401-408 (never used in development, the recorded season or benchmarks v1/v2), one per case
  - one case per family: clean control, forecast heat wave, clog, pest outbreak, saltier groundwater, a compound fault
    (clog then pests in another field), a biased soil-moisture sensor, and a root disease no available test can detect
  - onset day drawn uniformly from 75-150 (heat wave 120-170); severity from the family's range; the affected field is
    picked at random among the fields growing a crop on that day (scenarios.draw_challenge)
  - each case is run once per scientist: Muse Spark (Meta perception) and the scripted protocol with RL (same
    perception), with the same tool and test budgets; every run is kept, including failures
"""
import hashlib
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from worldlab import scenarios as SC                              # noqa: E402
from worldlab.agent import SYSTEM_PROMPT, TOOLS                    # noqa: E402
from worldlab.session import parse_perturb, perturb_extras         # noqa: E402

GEN_SEED = 20261101


def events(specs):
    out = []
    for sp in specs:
        kind, day, fi = parse_perturb(sp)
        ev = {"kind": kind, "day": day, **perturb_extras(sp)}
        if fi is not None:
            ev["field"] = fi
        out.append(ev)
    return out


def main(dst: str):
    rng = random.Random(GEN_SEED)
    fams = ["none", "heatwave", "clog", "pest", "salinity", "compound", "sensor_bias", "blight"]
    order = list(range(len(fams)))
    rng.shuffle(order)                                 # which farm gets which family is random too
    cases = []
    for k, fi in enumerate(order):
        fam, specs = SC.draw_challenge(rng, fams[fi])
        cases.append({"id": f"h{401 + k}-{fam}", "seed": 401 + k, "label": fam, "specs": specs, "events": events(specs)})
    cases.sort(key=lambda c: c["seed"])
    body = json.dumps(cases, sort_keys=True).encode()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    doc = {"schema": "worldlab.holdout/1", "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "generator_seed": GEN_SEED,
           "generated_from_commit": commit, "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
           "tool_schema_sha256": hashlib.sha256(json.dumps(TOOLS, sort_keys=True).encode()).hexdigest(),
           "rules": __doc__.split("Selection rules (written before the runs):", 1)[1].strip(),
           "scientists": ["spark/meta", "scripted-rl/meta"], "cases_sha256": hashlib.sha256(body).hexdigest(), "cases": cases}
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text(json.dumps(doc, indent=1))
    for c in cases:
        print(c["id"], c["specs"])
    print("cases_sha256", doc["cases_sha256"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/bench/holdout/holdout_v1.json")
