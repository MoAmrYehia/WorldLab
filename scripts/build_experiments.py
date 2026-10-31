"""Record the demo season and paired experiments branched from it, for the static website.

Each experiment reruns the recorded season from the start with exactly one input changed (same farm seed,
weather year, scenario and crop choices otherwise), so the differences are paired comparisons. The last one
starts a second season from the soil the first one left behind.

  python scripts/build_experiments.py [out_dir]     writes replay.json and experiments.json (default: worldlab/dashboard)
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

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "worldlab" / "dashboard")
runs = Path(tempfile.mkdtemp())
BASE = dict(agent="scripted-rl", seed=7, speed=0, perception="sim", scenario="drip_fault", perturb=["clog@95"], runs_dir=str(runs))


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
               "controller": lab.controller, "faults": faults, "seconds": round(time.time() - t0)}
    print(f"{label}: {summary['people_fed']} people, {summary['water_used_m3']} m3, {summary['energy_used_kwh']} kWh ({summary['seconds']} s)", flush=True)
    return s, summary


base_s, base = run("Recorded season")
export(base_s.run_dir, out / "replay.json",
       note="Recorded season: scripted decision protocol with a learned irrigation policy, farm 7, drip-fault scenario, hard water and energy budget. A drip line in F4 is silently clogged on 4 January.")
soil = json.loads((base_s.run_dir / "soil_end.json").read_text())
exps = []
for label, change, kw in [
    ("Fixed irrigation rule", {"kind": "controller", "label": "irrigation by the fixed rule instead of the learned policy"}, {"agent": "scripted"}),
    ("No hidden fault", {"kind": "fault", "label": "the drip line is never clogged"}, {"scenario": "baseline", "perturb": []}),
    ("Ignore alarms", {"kind": "adapt", "label": "the scientist ignores its alarms (no investigation or repair), fixed rule"}, {"agent": "scripted-noadapt"}),
    ("Next season, same soil", {"kind": "next_season", "label": "a second season starting from the salt the first one left, no hidden fault"},
     {"soil": soil, "scenario": "baseline", "perturb": []}),
]:
    _, sm = run(label, **kw)
    sm["change"] = change
    exps.append(sm)
note = ("Paired experiments: each reruns the recorded season from the start with one input changed; farm seed, weather year and "
        "crop choices are the same. 'Ignore alarms' also uses the fixed rule, so compare it with 'Fixed irrigation rule'. "
        "Exact mid-season checkpoints are not stored, so every branch is a full rerun.")
(out / "experiments.json").write_text(json.dumps({"baseline": base, "experiments": exps, "note": note,
                                                  "fields": [f["id"] for f in FIELDS]}, indent=1))
print("wrote", out / "replay.json", out / "experiments.json")
