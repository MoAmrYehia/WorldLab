"""Record the demo season and paired experiments branched from it, for the static website.

Each experiment reruns the recorded season from the start with exactly one input changed (same farm seed,
weather year, scenario and crop choices otherwise), so the differences are paired comparisons. The last one
starts a second season from the soil the first one left behind.

  python scripts/build_experiments.py [out_dir]          scripted scientist (no API key needed)
  python scripts/build_experiments.py [out_dir] --spark  Muse Spark as the scientist, SAM 3.1 + Muse Spark vision
                                                         (needs MODEL_API_KEY); the scripted protocol becomes one of the experiments
writes replay.json and experiments.json (default out_dir: worldlab/dashboard)
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worldlab.session import Session, Settings
from worldlab.replay import export
from worldlab.farm.world import FIELDS

SPARK = "--spark" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
out = Path(args[0] if args else Path(__file__).resolve().parent.parent / "worldlab" / "dashboard")
runs = Path(__file__).resolve().parent.parent / "runs" / "experiments" if SPARK else Path(tempfile.mkdtemp())
runs.mkdir(parents=True, exist_ok=True)
BASE = dict(agent="spark" if SPARK else "scripted-rl", seed=7, speed=0, perception="meta" if SPARK else "sim",
            scenario="drip_fault", perturb=["clog@95"], runs_dir=str(runs))


def run(label, **kw):
    t0 = time.time()
    s = Session(Settings(**{**BASE, **kw}))
    s.start(); s.thread.join()
    if s.error:
        raise SystemExit(s.error)
    lab, res = s.lab, s.lab.result
    faults = []
    for p in s.farm.events:
        a = [e["data"] for e in lab.ledger.entries if e["kind"] == "anomaly" and e["data"]["field"] == p.get("field")]
        faults.append({"kind": p["kind"], "field": p.get("field"), "day": p.get("day"), "detected_day": a[0]["detected_day"] if a else None})
    summary = {"label": label, "settings": {k: v for k, v in kw.items() if k != "runs_dir"},
               "people_fed": res["people_fed"], "limiting": res["limiting"], "by_nutrient": res["by_nutrient"],
               "water_used_m3": res["water_used_m3"], "energy_used_kwh": res["energy_used_kwh"],
               "within_limits": res["within_quota"] and res["within_energy"], "quantities": res["quantities"], "soil": res["soil"],
               "harvest": {k: {"crop": v["crop"], "yield_t_ha": v["yield_t_ha"]} for k, v in lab.harvest.items()},
               "controller": lab.controller, "faults": faults, "seconds": round(time.time() - t0),
               "agent": kw.get("agent", BASE["agent"]), "perception_check": res.get("perception_check")}
    print(f"{label}: {summary['people_fed']} people, {summary['water_used_m3']} m3, {summary['energy_used_kwh']} kWh ({summary['seconds']} s)", flush=True)
    return s, summary


base_s, base = run("Recorded season")
if SPARK:
    export(base_s.run_dir, out / "replay.json",
           note="Recorded season: Muse Spark (Meta Model API) as the scientist, SAM 3.1 and Muse Spark vision reading the drone "
                "photos, farm 7, drip-fault scenario, hard water and energy budget. A drip line in F4 is silently clogged on 4 January.")
else:
    export(base_s.run_dir, out / "replay.json",
           note="Recorded season: scripted decision protocol with a learned irrigation policy, farm 7, drip-fault scenario, hard water and energy budget. A drip line in F4 is silently clogged on 4 January.")
soil = json.loads((base_s.run_dir / "soil_end.json").read_text())
exps = []
plan = [
    ("Scripted scientist", {"kind": "agent", "label": "the scripted protocol with a learned irrigation policy instead of Muse Spark"},
     {"agent": "scripted-rl", "perception": "sim"}),
    ("No hidden fault", {"kind": "fault", "label": "the drip line is never clogged"}, {"scenario": "baseline", "perturb": []}),
    ("Ignore alarms", {"kind": "adapt", "label": "a scientist that ignores its alarms (no investigation or repair), fixed rule"},
     {"agent": "scripted-noadapt", "perception": "sim"}),
    ("Next season, same soil", {"kind": "next_season", "label": "a second season starting from the salt the first one left, no hidden fault"},
     {"soil": soil, "scenario": "baseline", "perturb": []}),
] if SPARK else [
    ("Fixed irrigation rule", {"kind": "controller", "label": "irrigation by the fixed rule instead of the learned policy"}, {"agent": "scripted"}),
    ("No hidden fault", {"kind": "fault", "label": "the drip line is never clogged"}, {"scenario": "baseline", "perturb": []}),
    ("Ignore alarms", {"kind": "adapt", "label": "the scientist ignores its alarms (no investigation or repair), fixed rule"}, {"agent": "scripted-noadapt"}),
    ("Next season, same soil", {"kind": "next_season", "label": "a second season starting from the salt the first one left, no hidden fault"},
     {"soil": soil, "scenario": "baseline", "perturb": []}),
]
for label, change, kw in plan:
    _, sm = run(label, **kw)
    sm["change"] = change
    exps.append(sm)
note = ("Paired experiments: each reruns the recorded season from the start with one input changed; farm seed, weather year and "
        "hidden faults are the same. Exact mid-season checkpoints are not stored, so every branch is a full rerun. "
        + ("Muse Spark's choices can differ between runs (it is a language model), so a Muse Spark rerun shows one outcome, not an average."
           if SPARK else "'Ignore alarms' also uses the fixed rule, so compare it with 'Fixed irrigation rule'."))
(out / "experiments.json").write_text(json.dumps({"baseline": base, "experiments": exps, "note": note,
                                                  "fields": [f["id"] for f in FIELDS]}, indent=1))
print("wrote", out / "replay.json", out / "experiments.json")
