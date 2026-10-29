"""Benchmark: agents against randomised hidden worlds, scored on ground truth.

For each world (random heat capacity, airflow curve, fan stall point, room
temperature...) and each scenario (no change, fan moved, hidden heater drift,
room warms), every agent runs the full task. A perturbation is applied 600 s
into the agent's first control plan. The simulator's hidden truth is used only
for scoring:

  compliance          share of hold time at or below target (+tolerance)
  detect_s            seconds from the hidden change to the first alarm
  false_alarms        alarms with no physical change behind them
  diagnosis_ok        the agent's supported hypothesis matches what changed
  energy_overhead     task fan energy per hold-second vs an oracle that knows the physics
  model_error         mean relative error of the learned cooling rate k(u) at the end
"""
from __future__ import annotations

import json
import math
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from . import model as M
from .agent import ScriptedScientist, LLMScientist
from .lab import Lab, Goal
from .llm import LLMConfig
from .perception import SimPerception
from .rig.base import fan_power_model
from .rig.sim import SimRig, World

EXPECTED = {"fan_moved": "fan", "heater_drift": "heat", "ambient_step": None, "none": None}


def oracle_power(rig: SimRig, goal: Goal) -> float:
    """Fan power (W) of the cheapest duty that holds the target with perfect knowledge."""
    w = rig.w
    Ta = w.Ta + rig._Ta_offset
    q = w.heater_w * rig._heater_factor
    for u in np.arange(0, 1.0001, 0.01):
        if Ta + q / (w.C * rig.true_k(u)) <= goal.target_C - 0.1:
            return fan_power_model(u) * w.power_scale
    return fan_power_model(1.0) * w.power_scale


def one(args) -> dict:
    seed, scenario, agent = args
    world = World.randomized(seed)
    rig = SimRig(world)
    perception = SimPerception(rig)
    lab = Lab(rig, perception=perception)
    state = {"pert_t": None}
    orig = lab.execute_plan

    def wrapped(plan_id, rationale):
        if scenario != "none" and state["pert_t"] is None:
            state["pert_t"] = rig.now() + 600
            rig.schedule(scenario, state["pert_t"])
        return orig(plan_id, rationale)

    lab.execute_plan = wrapped
    t0 = time.time()
    err = None
    try:
        if agent == "scripted":
            ScriptedScientist(lab).run()
        elif agent == "scripted-noadapt":
            ScriptedScientist(lab, adapt=False).run()
        else:
            LLMScientist(lab, LLMConfig.for_agent(agent), max_turns=80).run()
    except Exception as e:  # keep the benchmark going
        err = f"{type(e).__name__}: {e}"
    pt = rig.perturbations[0]["t"] if rig.perturbations else None
    alarms = [a["t_detected"] for a in lab.anomalies]
    detect = next((a - pt for a in alarms if pt is not None and a >= pt), None)
    false_alarms = sum(1 for a in alarms if pt is None or a < pt)
    if scenario == "ambient_step":
        false_alarms = len(alarms)
    # diagnosis: which change hypothesis ended up supported?
    supported = [h["statement"].lower() for h in lab.hyps.values() if h["status"] == "supported"]
    said_fan = any("fan" in s and ("moved" in s or "coupling" in s) for s in supported)
    said_heat = any("heat input" in s or "heater power" in s for s in supported)
    exp = EXPECTED[scenario]
    if exp == "fan":
        diag = said_fan and not said_heat
    elif exp == "heat":
        diag = said_heat and not said_fan
    else:
        diag = not (said_fan or said_heat)
    # energy vs oracle
    hold = max(lab.hold_done_s, 1.0)
    task_w = lab.energy["task"] / max(sum(1 for s in lab.samples if s["activity"] == "task"), 1)
    oracle_w = oracle_power(rig, lab.goal)
    # model error against the (post-change) truth
    p = lab.fit.params()
    us = np.linspace(0, 1, 21)
    k_fit = np.array([float(M.cooling_rate(lab.fit.structure, p, u)) for u in us])
    k_true = np.array([rig.true_k(u) for u in us])
    model_err = float(np.mean(np.abs(k_fit - k_true) / k_true))
    return {
        "seed": seed, "scenario": scenario, "agent": agent, "error": err,
        "goal_complete": lab.hold_done_s >= lab.goal.hold_s - 1,
        "compliance": round(lab.hold_ok_s / hold, 3) if lab.hold_done_s else 0.0,
        "detect_s": detect, "false_alarms": false_alarms, "diagnosis_ok": diag,
        "task_J": round(lab.energy["task"], 1), "exploration_J": round(lab.energy["exploration"], 1),
        "task_W": round(task_w, 3), "oracle_W": round(oracle_w, 3),
        "energy_overhead": round(task_w / oracle_w - 1, 3) if oracle_w > 0 else None,
        "model_error": round(model_err, 3), "structure": lab.fit.structure,
        "experiments": len(lab.experiments), "rig_time_s": round(rig.now()),
        "wall_s": round(time.time() - t0, 1),
    }


def _agg(rows: list[dict]) -> dict:
    def mean(vals):
        vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
        return round(float(np.mean(vals)), 3) if vals else None
    det = [r["detect_s"] for r in rows if r["detect_s"] is not None]
    return {
        "runs": len(rows),
        "goal_complete": mean([1.0 if r["goal_complete"] else 0.0 for r in rows]),
        "compliance": mean([r["compliance"] for r in rows]),
        "detected": f"{len(det)}/{len(rows)}" if rows and rows[0]["scenario"] in ("fan_moved", "heater_drift") else "-",
        "detect_s_median": round(float(np.median(det)), 1) if det else None,
        "false_alarms": sum(r["false_alarms"] for r in rows),
        "diagnosis_ok": mean([1.0 if r["diagnosis_ok"] else 0.0 for r in rows]),
        "energy_overhead": mean([r["energy_overhead"] for r in rows]),
        "exploration_J": mean([r["exploration_J"] for r in rows]),
        "model_error": mean([r["model_error"] for r in rows]),
    }


def run_bench(worlds: int, agents: list[str], scenarios: list[str], out: str, seed0: int = 100):
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(seed0 + i, sc, ag) for ag in agents for sc in scenarios for i in range(worlds)]
    llm = any(a in ("spark", "glimmer") for a in agents)
    print(f"{len(jobs)} runs: {worlds} worlds x {len(scenarios)} scenarios x {len(agents)} agents")
    rows = []
    if llm:
        for j in jobs:  # API agents run one at a time
            rows.append(one(j))
            print(rows[-1])
    else:
        with ProcessPoolExecutor(max_workers=max(1, min(8, (os.cpu_count() or 2)))) as ex:
            for r in ex.map(one, jobs):
                rows.append(r)
    (out_dir / "runs.json").write_text(json.dumps(rows, indent=1))
    return summarize(rows, agents, scenarios, out_dir)


def summarize(rows: list[dict], agents: list[str], scenarios: list[str], out_dir: Path) -> list[dict]:
    table = []
    for ag in agents:
        for sc in scenarios:
            sel = [r for r in rows if r["agent"] == ag and r["scenario"] == sc]
            row = {"agent": ag, "scenario": sc, **_agg(sel)}
            if sc != "none":
                # the oracle's power is computed for the final physics, so the
                # comparison is only fair when nothing changed mid-run
                row["energy_overhead"] = None
            table.append(row)
    (out_dir / "summary.json").write_text(json.dumps(table, indent=1))
    cols = ["agent", "scenario", "goal_complete", "compliance", "detected", "detect_s_median", "false_alarms",
            "diagnosis_ok", "energy_overhead", "exploration_J", "model_error"]
    md = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for t in table:
        md.append("| " + " | ".join("–" if t[c] is None else str(t[c]) for c in cols) + " |")
    (out_dir / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return table
