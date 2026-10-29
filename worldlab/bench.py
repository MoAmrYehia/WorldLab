"""Benchmark: agents on randomised farms, scored against hidden ground truth.

Each farm has its own hidden variety traits, drip efficiencies and weather
year. Scenarios add a hidden change on day 90 (early January), in mid-season:
  none        nothing happens
  clog        a drip line clogs (45% delivered); the water meter cannot see it
  pest        a pest outbreak eats 3% of a field's canopy per day
  salinity    groundwater turns saltier (4.5 -> 9 dS/m) without warning
  heatwave    a heat wave arrives (it is in the weather forecast)

Scores:
  people_fed        people fed for a year by the harvest (scarcest of calories, protein, vitamin A)
  pct_of_oracle     against a planner that knows the true traits and suffers no faults
  detect_days       days from the hidden change to the first alarm
  diagnosis_ok      the hypothesis the agent ended up supporting names what really changed
  false_alarms      alarms with no change behind them
  within_limits     groundwater and energy within budget
  trait_error       mean |belief - truth| / prior sd over the planted crops' traits (1.0 = no better than the prior)
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .agent import ScriptedScientist, LLMScientist
from .farm.belief import CropBelief
from .farm.crops import CROP_IDS, TRAITS, TRAIT_IDS, NUTRIENTS, nutrients_per_ha, people_fed
from .farm.optimize import evaluate, optimise
from .farm.world import Farm, FIELDS, FIELD_HA
from .lab import Lab, Limits
from .llm import LLMConfig
from .perception import SimPerception

EVENT_DAY = 90
KEYWORDS = {"clog": ("drip line", "clog"), "pest": ("pests",), "salinity": ("saltier", "groundwater"), "none": (), "heatwave": ()}


def oracle(seed: int) -> float:
    """Plan with the true traits, then grow it in this farm's actual year without faults."""
    farm = Farm(seed=seed)
    sure = {}
    for c in CROP_IDS:
        b = CropBelief(c)
        b.mean = np.array([farm.traits[c][k] for k in TRAIT_IDS])
        b.cov = np.eye(4) * 1e-10
        sure[c] = b
    lim = Limits()
    plan = optimise(evaluate(sure, S=24, seed=99), lim.water_quota_m3, lim.energy_kwh)
    lab = Lab(farm, perception=None)
    lab.plans["P0"] = {"plan_id": "P0", **plan}
    lab.start_season("P0", "oracle")
    while lab.phase == "season":
        lab.advance(60)
        if lab.anomaly:
            lab.dismiss_anomaly("oracle ignores")
    return lab.result["people_fed"]


def one(args) -> dict:
    seed, scenario, agent = args
    farm = Farm(seed=seed)
    if scenario != "none":
        farm.schedule(scenario, EVENT_DAY)
    lab = Lab(farm, perception=SimPerception())
    t0 = time.time()
    err = None
    try:
        if agent == "scripted":
            ScriptedScientist(lab).run()
        elif agent == "scripted-noadapt":
            ScriptedScientist(lab, adapt=False).run()
        elif agent == "scripted-notrials":
            ScriptedScientist(lab, trials=False).run()
        elif agent == "scripted-rl":
            ScriptedScientist(lab, rl=True).run()
        else:
            LLMScientist(lab, LLMConfig.for_agent(agent), max_turns=140).run()
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    ev = farm.events[0]["day"] if farm.events else None
    alarms = [a["detected_day"] for a in lab.anomalies]
    detect = next((a - ev for a in alarms if ev is not None and a >= ev), None)
    false_alarms = sum(1 for a in alarms if ev is None or a < ev)
    if scenario == "heatwave":
        false_alarms = len(alarms)
        detect = None
    sup = [h["statement"].lower() for h in lab.hyps.values() if h["status"] == "supported" and h.get("phase") == "season"]
    named = {k: any(all(w in s for w in kw[:1]) for s in sup) for k, kw in KEYWORDS.items() if kw}
    if scenario in ("clog", "pest", "salinity"):
        diag = named[scenario] and not any(v for k, v in named.items() if k != scenario)
    else:
        diag = not any(named.values())
    planted = sorted({f["crop"] for f in getattr(lab, "run_plan", []) if f.get("crop")})
    terr = []
    for c in planted:
        for i, k in enumerate(TRAIT_IDS):
            terr.append(abs(lab.beliefs[c].mean[i] - farm.traits[c][k]) / TRAITS[k]["sd"])
    res = lab.result or {}
    return {"seed": seed, "scenario": scenario, "agent": agent, "error": err,
            "people_fed": res.get("people_fed"), "limiting": res.get("limiting"),
            "water_m3": res.get("water_used_m3"), "energy_kwh": res.get("energy_used_kwh"),
            "within_limits": bool(res.get("within_quota") and res.get("within_energy")),
            "detect_days": detect, "detected": detect is not None, "false_alarms": false_alarms,
            "diagnosis_ok": diag, "trait_error": round(float(np.mean(terr)), 3) if terr else None,
            "controller": lab.controller, "rl_recommended": bool(lab.policy and lab.policy.get("recommended")),
            "crops": planted, "plots": lab.plots_used, "tests": lab.tests_used, "wall_s": round(time.time() - t0, 1)}


def run_bench(farms: int, agents: list[str], scenarios: list[str], out: str, seed0: int = 200, workers: int = 0):
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = [seed0 + i for i in range(farms)]
    jobs = [(s, sc, ag) for ag in agents for sc in scenarios for s in seeds]
    llm = any(a in ("spark", "glimmer") for a in agents)
    print(f"{len(jobs)} runs: {farms} farms x {len(scenarios)} scenarios x {len(agents)} agents (+ {farms} oracle runs)")
    workers = workers or max(1, min(8, os.cpu_count() or 2))
    if llm:
        rows = [one(j) for j in jobs]
        oracles = [oracle(s) for s in seeds]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            orc = ex.map(oracle, seeds)
            rows = list(ex.map(one, jobs))
            oracles = list(orc)
    orc = dict(zip(seeds, oracles))
    for r in rows:
        o = orc[r["seed"]]
        r["oracle_people"] = o
        r["pct_of_oracle"] = round(100 * r["people_fed"] / o, 1) if r["people_fed"] and o else None
    (out_dir / "runs.json").write_text(json.dumps(rows, indent=1))
    return summarize(rows, agents, scenarios, out_dir)


def summarize(rows, agents, scenarios, out_dir: Path):
    def mean(v):
        v = [x for x in v if x is not None]
        return round(float(np.mean(v)), 1) if v else None
    table = []
    for ag in agents:
        for sc in scenarios:
            sel = [r for r in rows if r["agent"] == ag and r["scenario"] == sc]
            if not sel:
                continue
            det = [r["detect_days"] for r in sel if r["detect_days"] is not None]
            fault = sc in ("clog", "pest", "salinity")
            table.append({
                "agent": ag, "scenario": sc, "runs": len(sel),
                "people_fed": mean([r["people_fed"] for r in sel]),
                "pct_of_oracle": mean([r["pct_of_oracle"] for r in sel]),
                "detected": f"{len(det)}/{len(sel)}" if fault else "–",
                "detect_days_median": round(float(np.median(det)), 1) if (det and fault) else None,
                "diagnosis_ok": f"{sum(r['diagnosis_ok'] for r in sel)}/{len(sel)}",
                "false_alarms": sum(r["false_alarms"] for r in sel),
                "within_limits": f"{sum(r['within_limits'] for r in sel)}/{len(sel)}",
                "trait_error": mean([r["trait_error"] for r in sel]),
            })
    (out_dir / "summary.json").write_text(json.dumps(table, indent=1))
    cols = list(table[0].keys()) if table else []
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for t in table:
        md.append("| " + " | ".join("–" if t[c] is None else str(t[c]) for c in cols) + " |")
    (out_dir / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return table
