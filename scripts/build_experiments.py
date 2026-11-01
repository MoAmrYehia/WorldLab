"""Record the demo season and the comparisons shown in Results > Compare, with their provenance.

Every comparison is a pair of runs with a machine-readable configuration diff, the realised differences in
what the scientist did, the parent run and the artifact hashes. Pairs are typed:

  single_factor  exactly one treatment input differs, and the decision maker is deterministic, so the runs are
                 checked to be identical before the treatment takes effect (for a hidden fault: before its day)
  illustrative   one treatment input differs, but the decision maker is a language model whose choices vary
                 between runs, so the difference mixes the treatment with run-to-run variation
  system         several inputs differ at once (for example the scientist and its perception); a comparison of
                 two complete systems, not of one factor

  python scripts/build_experiments.py [out_dir]          scripted scientist only (no API key needed)
  python scripts/build_experiments.py [out_dir] --spark  Muse Spark as the recorded scientist (needs MODEL_API_KEY)

Runs are cached in runs/experiments/manifest.json by their exact configuration, so rebuilding reuses them.
Writes replay.json and experiments.json (default out_dir: worldlab/dashboard).
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from worldlab.farm.world import FIELDS            # noqa: E402
from worldlab.replay import export                 # noqa: E402

SPARK = "--spark" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
out = Path(args[0] if args else ROOT / "worldlab" / "dashboard")
RUNS = ROOT / "runs" / "experiments"
RUNS.mkdir(parents=True, exist_ok=True)
MANIFEST = RUNS / "manifest.json"
BASE = dict(seed=7, speed=0, scenario="drip_fault", perturb=["clog@95"])
TREATMENT_KEYS = ("scientist", "irrigation_learning", "investigation", "perception", "hidden_fault", "starting_soil")
DETERMINISTIC = ("scripted protocol",)
VOLATILE = {"trained_seconds", "wall", "seconds", "wall_s"}


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def config_of(settings: dict, parent: str | None = None) -> dict:
    a = settings["agent"]
    sci = "Muse Spark (muse-spark-1.3)" if a == "spark" else "Muse Glimmer" if a == "glimmer" else "scripted protocol"
    return {"scientist": sci,
            "irrigation_learning": "chosen by the scientist" if a in ("spark", "glimmer") else ("trained, used if it wins" if a == "scripted-rl" else "none (fixed rule)"),
            "investigation": "chosen by the scientist" if a in ("spark", "glimmer") else ("ignores alarms" if a == "scripted-noadapt" else "fixed protocol"),
            "perception": "SAM 3.1 + Muse Spark vision on drone images" if settings.get("perception") == "meta" else "direct simulator state (no image model)",
            "hidden_fault": ", ".join(settings.get("perturb") or []) or "none",
            "starting_soil": f"carried over from {parent}" if settings.get("soil") else f"standard farm x{settings.get('salinity_scale', 1.0)}",
            "farm_seed": settings["seed"], "weather_year": f"seed {settings['seed']}"}


def record(label: str, kw: dict) -> Path:
    """A run with these settings: reused from the manifest when it exists, otherwise recorded now."""
    from worldlab.session import Session, Settings
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    want = {**BASE, **kw}
    key = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()[:16]
    if key in man and (RUNS / man[key]).exists():
        print(f"{label}: reusing {man[key]}", flush=True)
        return RUNS / man[key]
    t0 = time.time()
    s = Session(Settings(**want, runs_dir=str(RUNS)))
    s.start(); s.thread.join()
    if s.error:
        raise SystemExit(s.error)
    man[key] = s.run_dir.name
    MANIFEST.write_text(json.dumps(man, indent=1))
    print(f"{label}: recorded {s.run_dir.name} ({time.time() - t0:.0f} s)", flush=True)
    return s.run_dir


def summary(label: str, run_dir: Path, parent: str | None = None) -> dict:
    st = json.loads((run_dir / "settings.json").read_text())
    L = [json.loads(x) for x in (run_dir / "ledger.jsonl").read_text().splitlines() if x.strip()]
    kinds = lambda k: [e for e in L if e["kind"] == k]
    res = (kinds("season_result") or [{"data": None}])[-1]["data"]
    end = (kinds("run_end") or [{"data": {}}])[-1]["data"]
    season = (kinds("season_start") or [{"data": {}}])[-1]["data"]
    ctrl = [season.get("controller")] + [e["data"].get("controller") for e in kinds("controller")]
    faults = []
    for p in st.get("perturb") or []:
        kind, day = p.split("@")[0], int(p.split("@")[1].split(":")[0])
        a = [e["data"] for e in kinds("anomaly") if e["data"].get("detected_day", 0) >= day]
        faults.append({"kind": kind, "day": day, "detected_day": a[0]["detected_day"] if a else None})
    soil_true_end = json.loads((run_dir / "soil_end.json").read_text()) if (run_dir / "soil_end.json").exists() else None
    start = st.get("soil") or [[v * st.get("salinity_scale", 1.0) for v in f["ece"]] for f in FIELDS]
    usage = (kinds("model_usage") or [{"data": None}])[-1]["data"]
    return {
        "label": label, "run": run_dir.name, "parent_run": parent, "config": config_of(st, parent), "settings": st,
        "status": end.get("status") or ("completed" if res else "unknown"),
        "people_fed": res and res["people_fed"], "limiting": res and res["limiting"], "by_nutrient": res and res["by_nutrient"],
        "water_used_m3": res and res["water_used_m3"], "energy_used_kwh": res and res["energy_used_kwh"],
        "within_limits": bool(res and res["within_quota"] and res["within_energy"]), "quantities": res and res.get("quantities"),
        "soil": [{"field": f["id"], "ece_top_start_true_dS_m": round(sum(start[i][:2]) / 2, 2),
                  "ece_top_end_true_dS_m": round(sum(soil_true_end[i][:2]) / 2, 2) if soil_true_end else None,
                  "ece_top_end_measured_dS_m": (res["soil"][i]["ece_top_end_measured_dS_m"] if res and res.get("soil") else None)}
                 for i, f in enumerate(FIELDS)],
        "harvest": {e["data"]["field"]: {"crop": e["data"]["crop"], "yield_t_ha": e["data"]["yield_t_ha"]} for e in kinds("harvest")},
        "realised": {"crops": {FIELDS[i]["id"]: f.get("crop") for i, f in enumerate(season.get("fields", []))},
                     "controller": [c for c in ctrl if c], "trial_plots": res and res["quantities"]["trial_plots"],
                     "field_tests": len(kinds("field_test")), "repairs": sum(1 for e in kinds("adjust") if e["data"].get("repair")),
                     "drone_looks": len(kinds("look")), "alarms": len(kinds("anomaly"))},
        "faults": faults, "model_usage": usage, "perception_check": res and res.get("perception_check"),
        "artifacts": {"ledger_sha256": sha(run_dir / "ledger.jsonl"), "events_sha256": sha(run_dir / "events.jsonl"),
                      "settings_sha256": sha(run_dir / "settings.json"), "ledger_head": L[-1]["hash"] if L else None},
    }


def pre_event_identical(a: Path, b: Path, day: int) -> bool:
    """Did two runs record the same decisions and measurements before `day`? (wall times and hashes ignored)"""
    def body(p):
        out = []
        for x in (p / "ledger.jsonl").read_text().splitlines():
            e = json.loads(x)
            if (e.get("t") or 0) >= day:
                break
            if e["kind"] in ("session", "run_start"):
                continue
            if e["kind"] == "agent_step" and str(e["data"].get("text", "")).startswith("agent:"):
                continue                             # the line naming the scientist variant is the treatment itself
            out.append((e["kind"], json.dumps(strip(e["data"]), sort_keys=True, default=str)))
        return out

    def strip(v):                                    # timings measure the computer, not the run
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k not in VOLATILE}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return body(a) == body(b)


def pair(title: str, kind: str, base: dict, treat: dict, base_dir: Path, treat_dir: Path) -> dict:
    diff = {k: [base["config"][k], treat["config"][k]] for k in base["config"] if base["config"][k] != treat["config"].get(k)}
    keys = [k for k in diff if k in TREATMENT_KEYS]
    if kind in ("single_factor", "illustrative") and len(keys) != 1:
        raise ValueError(f"{title}: a {kind} pair must change exactly one treatment input, not {keys}")
    det = base["config"]["scientist"] in DETERMINISTIC and treat["config"]["scientist"] in DETERMINISTIC
    if kind == "single_factor" and not det:
        raise ValueError(f"{title}: a single-factor pair needs a deterministic scientist")
    identical = None
    if kind == "single_factor":
        day = min([f["day"] for f in base["faults"] + treat["faults"]] or [0])
        if keys == ["investigation"]:
            day = min([f["detected_day"] for f in base["faults"] + treat["faults"] if f["detected_day"]] or [0]) + 1
        identical = pre_event_identical(base_dir, treat_dir, day)
        if not identical:
            raise ValueError(f"{title}: runs differ before the treatment takes effect (day {day})")
    infer = {
        "single_factor": "Only one input differs, and the scripted scientist is deterministic: both runs were checked to be identical "
                         "until the treatment takes effect. The difference is that input's total effect on this farm, including how the "
                         "scientist responded. One farm and one weather year: not an average.",
        "illustrative": "Only one input differs, but Muse Spark's choices vary between runs (it is a language model), so the "
                        "difference mixes that input's effect with run-to-run variation. One run each: illustrative, not a measured effect.",
        "system": f"Several inputs differ at once ({', '.join(k.replace('_', ' ') for k in keys)}), so this compares two complete "
                  "systems on the same farm, weather and hidden fault. It does not say which input made the difference.",
    }[kind]
    return {"title": title, "kind": kind, "baseline": base["label"], "treatment": treat["label"], "config_diff": diff,
            "treatment_inputs": keys, "pre_event_identical": identical, "can_infer": infer}


def main():
    head = "spark" if SPARK else "scripted-rl"
    runs = {}
    runs["Recorded season"] = record("Recorded season", {"agent": head, "perception": "meta" if SPARK else "sim"})
    if SPARK:
        runs["Scripted scientist"] = record("Scripted scientist", {"agent": "scripted-rl", "perception": "sim"})
        runs["Muse Spark, no hidden fault"] = record("Muse Spark, no hidden fault", {"agent": "spark", "perception": "meta", "scenario": "baseline", "perturb": []})
    runs["Scripted, no hidden fault"] = record("Scripted, no hidden fault", {"agent": "scripted-rl", "perception": "sim", "scenario": "baseline", "perturb": []})
    runs["Scripted, fixed rule"] = record("Scripted, fixed rule", {"agent": "scripted", "perception": "sim"})
    runs["Scripted, ignores alarms"] = record("Scripted, ignores alarms", {"agent": "scripted-noadapt", "perception": "sim"})
    soil = json.loads((runs["Recorded season"] / "soil_end.json").read_text())
    runs["Next season, same soil"] = record("Next season, same soil", {"agent": head, "perception": "meta" if SPARK else "sim",
                                                                       "soil": soil, "scenario": "baseline", "perturb": []})
    S = {k: summary(k, v, parent=runs["Recorded season"].name if k == "Next season, same soil" else None) for k, v in runs.items()}
    rec = "Recorded season"
    scripted_base = "Scripted scientist" if SPARK else rec
    if SPARK:
        S["Scripted scientist"] = summary("Scripted scientist", runs["Scripted scientist"])
    P = []
    if SPARK:
        P.append(pair("Muse Spark against the scripted scientist", "system", S[rec], S["Scripted scientist"], runs[rec], runs["Scripted scientist"]))
        P.append(pair("Muse Spark with and without the hidden fault", "illustrative", S[rec], S["Muse Spark, no hidden fault"], runs[rec], runs["Muse Spark, no hidden fault"]))
    P.append(pair("Effect of the hidden clog (scripted scientist)", "single_factor", S[scripted_base], S["Scripted, no hidden fault"],
                  runs[scripted_base if SPARK else rec], runs["Scripted, no hidden fault"]))
    P.append(pair("Effect of investigating alarms (scripted scientist, fixed rule)", "single_factor", S["Scripted, fixed rule"], S["Scripted, ignores alarms"],
                  runs["Scripted, fixed rule"], runs["Scripted, ignores alarms"]))
    P.append(pair("A second season on the soil the first left", "system", S[rec], S["Next season, same soil"], runs[rec], runs["Next season, same soil"]))
    carry = [{"field": a["field"], "end_of_season_1_true": a["ece_top_end_true_dS_m"], "start_of_season_2_true": b["ece_top_start_true_dS_m"],
              "end_of_season_1_measured": a["ece_top_end_measured_dS_m"]}
             for a, b in zip(S[rec]["soil"], S["Next season, same soil"]["soil"])]
    note = ("Every pair lists what differs between its two runs and what can and cannot be inferred from it. Runs are full reruns from "
            "1 October; exact mid-season checkpoints are not stored. Drone images are synthetic renders of the simulator's state.")
    export(runs[rec], out / "replay.json", note=(
        "Recorded season: Muse Spark (Meta Model API) as the scientist, SAM 3.1 and Muse Spark vision reading synthetic drone images, "
        "farm 7, hard water and energy budget. One hidden fault was scheduled; it is revealed after the season." if SPARK else
        "Recorded season: scripted decision protocol with a learned irrigation policy, farm 7, hard water and energy budget. "
        "One hidden fault was scheduled; it is revealed after the season."))
    data = {"schema": 2, "baseline": S[rec], "runs": S, "pairs": P, "soil_carryover": carry, "note": note,
            "fields": [f["id"] for f in FIELDS], "built": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
    (out / "experiments.json").write_text(json.dumps(data, indent=1, default=str))
    for p in P:
        a, b = S[p["baseline"]], S[p["treatment"]]
        print(f"{p['kind']:<13} {p['title']}: {a['people_fed']} -> {b['people_fed']} | diff {list(p['config_diff'])} | identical before: {p['pre_event_identical']}")
    print("wrote", out / "replay.json", out / "experiments.json")


if __name__ == "__main__":
    main()
