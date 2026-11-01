"""Missions, achievements and experience points, computed only from what happened.

Everything here is derived from a run's audit ledger, the hidden changes made to
the farm (known to the game, never to the scientist) and the season result. The
same function scores a live run on the server and a recorded run in a replay, so
the game layer can never claim more than the science shows.
"""
from __future__ import annotations

import hashlib
import json

TARGET_PEOPLE = 500            # the farm's food-security goal for the season
WATER_TARGET_M3_PER_PERSON = 125.0
SEASON_DAYS = 273
FAULT_FINDING = {"clog": "drip_delivery", "pest": "pest", "salinity": "groundwater_ec"}
FAULT_LABEL = {"clog": "clogged drip line", "pest": "pest outbreak", "salinity": "saltier groundwater", "heatwave": "heat wave"}

ACHIEVEMENTS = {
    "first_sprout": ("First Sprout", "Grow a round of trial plots and compare every harvest with its prediction."),
    "diverse_farm": ("Diverse Farm", "Grow at least four different crops in one season."),
    "adaptive_intelligence": ("Adaptive Intelligence", "Validate an RL irrigation policy on held-out seasons, deploy it, and finish within the water quota."),
    "scientific_detective": ("Scientific Detective", "Detect a hidden fault and identify its true cause from field evidence."),
    "resilience_architect": ("Resilience Architect", "Recover from a fault: repair it or correct the model, and still meet the plan's bad-year projection."),
    "water_steward": ("Water Steward", f"Finish a season within the quota using at most {WATER_TARGET_M3_PER_PERSON:.0f} m³ of groundwater per person fed."),
    "harvest_guardian": ("Harvest Guardian", "Feed at least 450 people from one season."),
}

XP = {"season": 100, "trial_round": 30, "plan": 20, "policy": 40, "detected": 40, "diagnosed": 60, "repaired": 40,
      "achievement": 150}


def level_for(xp: int) -> dict:
    """Level n needs 100 * (n - 1)^2 XP."""
    n = 1
    while 100 * n * n <= xp:
        n += 1
    lo, hi = 100 * (n - 1) ** 2, 100 * n * n
    return {"level": n, "xp": xp, "level_floor": lo, "next_level_at": hi}


def _entries(events: list[dict]) -> list[dict]:
    """Accept raw ledger entries or bus messages ({kind: 'ledger', data: entry})."""
    out = []
    for e in events:
        if e.get("kind") == "ledger" and isinstance(e.get("data"), dict) and "seq" in e["data"]:
            out.append(e["data"])
        elif "seq" in e and "data" in e:
            out.append(e)
    return out


def evaluate(events: list[dict], perturbations: list[dict] | None = None, result: dict | None = None) -> dict:
    """Score one run. Returns chapters (with objectives), achievements earned, metrics and XP earned."""
    L = _entries(events)
    kinds = lambda k: [e for e in L if e["kind"] == k]
    perturbations = perturbations or []
    if result is None:
        res = kinds("season_result")
        result = res[-1]["data"] if res else None

    trial_results = kinds("trial_result")
    plots = sum(len(e["data"].get("plots", [])) for e in trial_results)
    missed = sum(1 for e in trial_results for p in e["data"].get("plots", []) if not p.get("prediction_held"))
    calibrated = any(e["data"].get("crops") for e in kinds("model_update"))
    plans = kinds("plan")
    season = kinds("season_start")
    season_on = bool(season)
    fields = season[-1]["data"].get("fields", []) if season else []
    crops = sorted({f.get("crop") for f in fields if f.get("crop")})
    choices = kinds("farmer_choices")
    picked = [f for f in (choices[-1]["data"]["fields"] if choices else []) if f.get("crop")]
    policy = kinds("rl_policy")
    policy_ok = any(e["data"].get("recommend") == "rl_policy" for e in policy)
    deployed = bool(season) and season[-1]["data"].get("controller") == "rl_policy"
    anomalies = kinds("anomaly")
    tests = kinds("field_test")
    updates = [e for e in kinds("model_update") if e["data"].get("finding")]
    repairs = [e for e in kinds("adjust") if (e["data"].get("repair") or e["data"].get("pest_control"))]
    harvests = kinds("harvest")
    days = max([e["t"] or 0 for e in L if e["kind"] in ("advance", "harvest", "season_result")] + [0])

    # faults: what was really done to the farm, and whether the scientist found it
    faults = []
    for p in perturbations:
        k = p.get("kind")
        if k not in FAULT_FINDING:
            continue
        day = p.get("day", 0)
        det = [a for a in anomalies if (a["data"].get("detected_day", 0) >= day) and
               (p.get("field") in (None, "all") or a["data"].get("field") == p.get("field") or k == "salinity")]
        found = [u for u in updates if u["data"]["finding"] == FAULT_FINDING[k] and (u["t"] or 0) >= day and
                 (k == "salinity" or u["data"].get("field") == p.get("field"))]
        fixed = bool(found) or any((r["t"] or 0) >= day and r["data"].get("field") == p.get("field") for r in repairs)
        faults.append({"kind": k, "label": FAULT_LABEL[k], "field": p.get("field"), "day": day,
                       "detected": bool(det), "detected_day": det[0]["data"]["detected_day"] if det else None,
                       "diagnosed": bool(found), "recovered": fixed})

    people = result.get("people_fed") if result else None
    water = result.get("water_used_m3") if result else None
    plan_p10 = plans[-1]["data"].get("people_p10") if plans else None
    w_per = round(water / people, 1) if (people and water) else None
    metrics = {"people_fed": people, "target_people": TARGET_PEOPLE, "water_m3": water,
               "energy_kwh": result.get("energy_used_kwh") if result else None,
               "water_m3_per_person": w_per, "plan_people_p10": plan_p10,
               "within_quota": bool(result and result.get("within_quota")),
               "within_energy": bool(result and result.get("within_energy")),
               "crops": crops, "trial_plots": plots, "trial_predictions_missed": missed,
               "faults": faults, "anomalies": len(anomalies), "field_tests": len(tests)}

    def obj(label, done, value=None, kind="required", go=None):
        """kind: required (decides the chapter), optional (a choice, never blocks), stretch (a goal beyond completion)."""
        return {"label": label, "done": bool(done), "value": value, "kind": kind, "go": go}

    recover = [
        obj("Detect every hidden fault", all(f["detected"] for f in faults), f"{sum(f['detected'] for f in faults)} of {len(faults)}", go="incidents"),
        obj("Identify the true cause", all(f["diagnosed"] for f in faults), go="incidents"),
        obj("Repair or correct the model", all(f["recovered"] for f in faults), go="incidents")] if faults else [
        obj("No hidden faults this season", False, "nothing to recover from", kind="na")]
    chapters = [
        {"id": "discover", "title": "Discover", "about": "Study the farm and run crop experiments.", "objectives": [
            obj("Grow trial plots", plots > 0, f"{plots} plots", go="trials"),
            obj("Calibrate the crop models", calibrated, go="traits"),
            obj("Test the first hypothesis", any(e["data"].get("verdict") for e in kinds("conclusion")), go="agent")]},
        {"id": "strategize", "title": "Strategize", "about": "Plan crops and water within the limits.", "objectives": [
            obj("Plan the season", bool(plans), f"{plan_p10} people in a bad year" if plan_p10 is not None else None, go="plan"),
            obj("Choose your own crops", bool(picked), f"{len(picked)} fields" if picked else "left to the scientist", kind="optional", go="planner"),
            obj("Validate an irrigation policy", policy_ok, kind="optional", go="rl")]},
        {"id": "survive", "title": "Survive", "about": "Run the season through heat, salt and faults.", "objectives": [
            obj("Sow the season", season_on),
            obj("Reach harvest", bool(result), f"day {min(days, SEASON_DAYS)} of {SEASON_DAYS}" if season_on else None),
            obj("Stay within the water quota", metrics["within_quota"] if result else False)]},
        {"id": "recover", "title": "Recover", "about": "Investigate anomalies, find causes, repair, update the model.", "objectives": recover},
        {"id": "harvest", "title": "Harvest", "about": "Judge food security, water use and resilience.", "objectives": [
            obj("Harvest every field", bool(harvests) and len(harvests) >= len(crops) and bool(crops), go="results"),
            obj(f"Farm goal: feed {TARGET_PEOPLE} people", people is not None and people >= TARGET_PEOPLE, f"{people} fed" if people is not None else None, kind="stretch", go="results"),
            obj(f"At most {WATER_TARGET_M3_PER_PERSON:.0f} m³ per person fed", w_per is not None and w_per <= WATER_TARGET_M3_PER_PERSON, f"{w_per} m³" if w_per else None, kind="stretch", go="results")]},
    ]
    for c in chapters:
        req = [o for o in c["objectives"] if o["kind"] == "required"]
        n = sum(o["done"] for o in req)
        c["na"] = not req
        c["done"] = bool(req) and n == len(req)
        c["progress"] = n / len(req) if req else 1.0
        c["status"] = "na" if c["na"] else "done" if c["done"] else "open"
    if result:
        stretch = [o for c in chapters for o in c["objectives"] if o["kind"] == "stretch"]
        missed_goals = [o["label"] for o in stretch if not o["done"]]
        outcome = ("Season complete" + ("; all goals met." if not missed_goals else f"; not reached: {', '.join(missed_goals)}."))
    else:
        outcome = None
    current = next((c["id"] for c in chapters if c["status"] == "open"), "harvest")
    # a chapter whose phase hasn't arrived isn't "current" just because an earlier optional objective is open
    if result:
        current = "harvest"
    elif season_on:
        current = "recover" if anomalies else "survive"
    elif plans:
        current = "strategize"
    else:
        current = "discover"

    earned = []
    def earn(aid, evidence):
        earned.append({"id": aid, "title": ACHIEVEMENTS[aid][0], "about": ACHIEVEMENTS[aid][1], "evidence": evidence})
    if trial_results:
        earn("first_sprout", f"{plots} trial plots grown; {plots - missed} predictions held, {missed} missed.")
    if len(crops) >= 4:
        earn("diverse_farm", f"{len(crops)} crops: {', '.join(crops)}.")
    if policy_ok and deployed and result and result.get("within_quota"):
        earn("adaptive_intelligence", f"Policy deployed; season used {water:,} m³ of a quota.")
    if any(f["detected"] and f["diagnosed"] for f in faults):
        f = next(f for f in faults if f["detected"] and f["diagnosed"])
        from .farm.weather import day_label
        dl = lambda d: day_label(d).lstrip("0")
        earn("scientific_detective", f"{f['label'].capitalize()} in {f['field']} from {dl(f['day'])}; detected on {dl(f['detected_day'])} ({f['detected_day'] - f['day']} days later) and identified by test.")
    if result and plan_p10 is not None and any(f["recovered"] for f in faults) and people >= plan_p10:
        earn("resilience_architect", f"{people} people fed against a bad-year projection of {plan_p10}, after a {next(f['label'] for f in faults if f['recovered'])}.")
    if result and result.get("within_quota") and w_per is not None and w_per <= WATER_TARGET_M3_PER_PERSON:
        earn("water_steward", f"{w_per} m³ of groundwater per person fed, within the quota.")
    if people is not None and people >= 450:
        earn("harvest_guardian", f"{people} people fed.")

    xp = []
    if result:
        xp.append(("Season completed", XP["season"]))
    if trial_results:
        xp.append((f"{len(trial_results)} trial round(s)", XP["trial_round"] * len(trial_results)))
    if plans:
        xp.append(("Season planned", XP["plan"]))
    if policy_ok:
        xp.append(("Irrigation policy validated", XP["policy"]))
    for f in faults:
        if f["detected"]:
            xp.append((f"Detected the {f['label']}", XP["detected"]))
        if f["diagnosed"]:
            xp.append((f"Identified the {f['label']}", XP["diagnosed"]))
        if f["recovered"]:
            xp.append((f"Recovered from the {f['label']}", XP["repaired"]))
    if people:
        xp.append((f"{people:.0f} people fed", int(people)))
    # how the run ended: a stopped, failed or handed-over run is reported as such and earns nothing
    ends = kinds("run_end")
    run_status = (ends[-1]["data"].get("status") if ends else None) or ("completed" if result else "running")
    if kinds("handover") and run_status == "completed":
        run_status = "degraded"
    if run_status in ("failed", "timeout", "cancelled"):
        reason = ends[-1]["data"].get("reason") or run_status
        outcome = f"Season stopped ({run_status}): {reason}. No harvest was recorded."
        earned, xp = [], []
    elif run_status == "degraded":
        outcome = (outcome or "Season complete") + " Part of it was run by the scripted protocol after a handover, so it is a mixed result."
        earned, xp = [], []
    metrics["run_status"] = run_status
    return {"chapters": chapters, "current_chapter": current, "achievements": earned, "metrics": metrics,
            "xp_items": [{"label": a, "xp": b} for a, b in xp], "complete": bool(result) and run_status == "completed", "outcome": outcome,
            "run_status": run_status,
            "catalog": [{"id": k, "title": v[0], "about": v[1]} for k, v in ACHIEVEMENTS.items()]}


def scenario_key(seed: int, choices) -> str:
    """Same farm and same crop choices = same scenario, so replaying it can't farm rewards."""
    return hashlib.sha256(json.dumps([seed, choices], sort_keys=True, default=str).encode()).hexdigest()[:16]


def award(progress: dict, run_eval: dict, key: str) -> dict:
    """Apply one finished run to a player's saved progress. Season XP counts once per scenario;
    people-fed XP only for beating that scenario's best; each achievement unlocks once."""
    progress = {"xp": 0, "achievements": {}, "best_people": None, "scenarios": {}, "seasons": 0, **(progress or {})}
    prev = progress["scenarios"].get(key)
    gained, lines = 0, []
    people = run_eval["metrics"].get("people_fed") or 0
    for it in run_eval["xp_items"]:
        if it["label"].endswith("people fed"):
            best = prev["best_people"] if prev else 0
            extra = int(max(0, people - best))
            if extra:
                lines.append({"label": f"{extra} more people fed than your best on this farm" if prev else it["label"], "xp": extra})
                gained += extra
        elif not prev:
            lines.append(it)
            gained += it["xp"]
    new_badges = []
    for a in run_eval["achievements"]:
        if a["id"] not in progress["achievements"]:
            progress["achievements"][a["id"]] = {"title": a["title"], "evidence": a["evidence"]}
            new_badges.append(a)
            lines.append({"label": f"Achievement: {a['title']}", "xp": XP["achievement"]})
            gained += XP["achievement"]
    progress["xp"] += gained
    progress["seasons"] += 1 if run_eval["complete"] else 0
    if run_eval["complete"]:
        progress["scenarios"][key] = {"best_people": max(people, prev["best_people"] if prev else 0)}
        progress["best_people"] = max(people, progress["best_people"] or 0)
    return {"progress": progress, "gained": gained, "lines": lines, "new_achievements": new_badges,
            "level": level_for(progress["xp"])}
