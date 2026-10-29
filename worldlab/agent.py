"""The scientist: an LLM (Muse Spark or Muse Glimmer) that drives the lab
through tool calls, plus a scripted baseline that follows a fixed protocol.

The LLM decides what to believe and what to try next; the lab does the
numbers and enforces the bounds. Every tool call and its rationale is
written to the ledger.
"""
from __future__ import annotations

import json
import time
import traceback

from .lab import Lab, StopRequested
from .llm import LLMClient, LLMConfig, APIError

SYSTEM_PROMPT = """You are WorldLab, an AI scientist running a real tabletop cooling rig: a finned heatsink heated by a resistor (a stand-in for a chip), a PWM fan, temperature sensors on the heatsink and in the room, a fan power meter and a top-down camera.

You never touch hardware directly. Your tools run experiments, fit models and execute control plans, and a safety governor bounds every one of them. Your job is to discover how this rig actually behaves, then use that knowledge to meet the cooling goal with as little fan energy as possible, and to notice and recover when the world changes under you.

Method:
1. Orient: observe the rig and look at the scene.
2. Before every experiment, record a hypothesis with a numeric prediction and a clear falsification condition (record_hypothesis).
3. Design experiments with evaluate_experiments. You may propose your own step sequences; compare candidates on expected information, how much they shrink the goal uncertainty, energy and safety. Prefer cheap, informative, discriminating experiments. Do not run experiments that will not change a decision.
4. After each experiment, call fit_model. The lab compares several physical hypotheses for how airflow scales with fan duty (linear, sqrt, power, stall_power) by AIC. Then conclude your hypothesis honestly: supported, refuted or inconclusive, citing numbers.
5. When the model is good enough for the goal (goal uncertainty well below 1 K), plan_control and execute_plan. The plan reports an uncertainty premium: the extra energy spent because the model is uncertain.
6. If execution reports an anomaly, the model no longer explains the world. Do not just replan. Investigate:
   - look_at_scene to check whether the physical setup changed.
   - Record competing hypotheses, e.g. the fan moved or turned (only the fan coupling k1 changed); heater power changed (b*q changed); the ambient changed; a sensor fault.
   - Run a discriminating experiment. A fan-off step isolates natural convection and heat input (k0, b) from fan coupling; a full-fan step measures the new coupling.
   - Refit with since_t set to the anomaly onset. Use hold_params to test which parameters stayed the same, for example hold k0 and b and compare against a free fit.
   - Conclude the hypotheses, then replan and resume the goal.
7. Stay within the exploration and task energy budgets. Call finish when the hold requirement is met, or when you have shown the goal is infeasible, with an honest summary of what you learned.

Style: keep your messages to one or two sentences. Put your reasoning in each tool's rationale argument; it is recorded in the audit ledger and shown on the dashboard."""


def _p(desc: str, **props) -> dict:
    return {"type": "object", "properties": props, "required": [k for k, v in props.items() if not v.pop("_optional", False)],
            "description": desc}


STEP_SCHEMA = {"type": "array", "description": "Sequence of steps, each held for its duration.",
               "items": {"type": "object", "properties": {
                   "fan_duty": {"type": "number", "description": "0 to 1"},
                   "heater_on": {"type": "boolean"},
                   "duration_s": {"type": "number", "description": "30 to 900 seconds"}},
                   "required": ["fan_duty", "heater_on", "duration_s"]}}

TOOLS = [
    {"name": "observe", "description": "Current sensor readings, trends, energy use and budgets, goal progress, model status and any active anomaly.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "look_at_scene", "description": "Capture a camera frame and locate the fan and heatsink (SAM 3.1), judge the fan's aim (Muse Spark), and compare with the reference layout.",
     "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "get_model", "description": "The current model: structure, parameters with uncertainty, and predicted steady-state temperature at several fan duties.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "record_hypothesis", "description": "Record a testable hypothesis before experimenting.",
     "parameters": {"type": "object", "properties": {
         "statement": {"type": "string"},
         "prediction": {"type": "string", "description": "What you expect to measure, with numbers."},
         "falsified_if": {"type": "string", "description": "The measurement that would refute it."}},
         "required": ["statement", "prediction", "falsified_if"]}},
    {"name": "evaluate_experiments", "description": "Predict outcome, energy, information gain and safety for candidate experiments. Pass an empty list to get a standard menu. Returns candidate_ids to run.",
     "parameters": {"type": "object", "properties": {
         "candidates": {"type": "array", "items": {"type": "object", "properties": {
             "name": {"type": "string"}, "steps": STEP_SCHEMA}, "required": ["name", "steps"]}}},
         "required": ["candidates"]}},
    {"name": "run_experiment", "description": "Run an evaluated candidate on the rig and compare the measurement with the prediction made beforehand.",
     "parameters": {"type": "object", "properties": {
         "candidate_id": {"type": "string"}, "hypothesis_id": {"type": "string"},
         "rationale": {"type": "string"}}, "required": ["candidate_id", "hypothesis_id", "rationale"]}},
    {"name": "fit_model", "description": "Fit all model structures to the data and adopt the best by AIC. since_t restricts to data after a time (e.g. an anomaly onset); hold_params keeps named parameters at their values in the last model trusted before the most recent anomaly, to test whether they changed.",
     "parameters": {"type": "object", "properties": {
         "rationale": {"type": "string"},
         "since_t": {"type": "number", "description": "Rig time in seconds; omit to use all data."},
         "hold_params": {"type": "array", "items": {"type": "string", "enum": ["k0", "k1", "b", "n", "u0"]}},
         "structures": {"type": "array", "items": {"type": "string", "enum": ["linear", "sqrt", "power", "stall_power"]}}},
         "required": ["rationale"]}},
    {"name": "conclude", "description": "Mark a hypothesis supported, refuted or inconclusive, with the evidence.",
     "parameters": {"type": "object", "properties": {
         "hypothesis_id": {"type": "string"},
         "verdict": {"type": "string", "enum": ["supported", "refuted", "inconclusive"]},
         "evidence": {"type": "string"}}, "required": ["hypothesis_id", "verdict", "evidence"]}},
    {"name": "plan_control", "description": "Compute the cheapest fan schedule that robustly meets the goal under the current model.",
     "parameters": {"type": "object", "properties": {"rationale": {"type": "string"}}, "required": ["rationale"]}},
    {"name": "execute_plan", "description": "Run a plan on the rig. Returns early if the model's predictions diverge from reality or the camera sees the setup change.",
     "parameters": {"type": "object", "properties": {"plan_id": {"type": "string"}, "rationale": {"type": "string"}},
                    "required": ["plan_id", "rationale"]}},
    {"name": "finish", "description": "End the run with an honest summary of what was learned and achieved.",
     "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}},
]


def dispatch(lab: Lab, name: str, args: dict):
    if name == "observe":
        return lab.observe()
    if name == "look_at_scene":
        return lab.look_at_scene(args.get("reason", ""))
    if name == "get_model":
        return lab.get_model()
    if name == "record_hypothesis":
        return lab.record_hypothesis(args["statement"], args["prediction"], args["falsified_if"])
    if name == "evaluate_experiments":
        return lab.evaluate_experiments(args.get("candidates") or None)
    if name == "run_experiment":
        return lab.run_experiment(args.get("hypothesis_id", ""), args.get("rationale", ""),
                                  candidate_id=args.get("candidate_id"))
    if name == "fit_model":
        return lab.fit_model(args.get("rationale", ""), structures=args.get("structures"),
                             since_t=args.get("since_t"), hold_params=args.get("hold_params"))
    if name == "conclude":
        return lab.conclude(args["hypothesis_id"], args["verdict"], args["evidence"])
    if name == "plan_control":
        return lab.plan_control(args.get("rationale", ""))
    if name == "execute_plan":
        return lab.execute_plan(args["plan_id"], args.get("rationale", ""))
    if name == "finish":
        return lab.finish(args.get("summary", ""))
    return {"error": f"unknown tool {name}"}


def _short(obj, limit=6000) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= limit else s[:limit] + '..."(truncated)"'


class LLMScientist:
    def __init__(self, lab: Lab, cfg: LLMConfig, max_turns: int = 80):
        self.lab = lab
        self.cfg = cfg
        self.client = LLMClient(cfg)
        self.max_turns = max_turns

    def run(self) -> dict:
        lab = self.lab
        tools = [{"type": "function", "function": t} for t in TOOLS]
        first = {"goal": lab.goal.describe(), "now": lab.observe()}
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "Begin. Here is the goal and the current state:\n" + _short(first)}]
        lab.agent_note("system", f"agent: {self.cfg.label} · model {self.cfg.model}")
        nudges = 0
        for turn in range(self.max_turns):
            if lab.done or lab.stop_flag.is_set():
                break
            try:
                msg = self.client.chat(messages, tools=tools)
            except APIError as e:
                lab.agent_note("error", f"model API error: {e}")
                if e.status in (400, 401, 403, 404):
                    break
                time.sleep(5)
                continue
            text = (msg.get("content") or "").strip()
            calls = msg.get("tool_calls") or []
            if text:
                lab.agent_note("agent", text)
            if not calls:
                messages.append({"role": "assistant", "content": text})
                nudges += 1
                if nudges > 3:
                    break
                messages.append({"role": "user", "content": "Continue by calling a tool. If the goal is complete or infeasible, call finish."})
                continue
            messages.append({"role": "assistant", "content": text, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or "{}"}}
                for c in calls]})
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                lab.agent_note("tool_call", name, {"args": args})
                try:
                    result = dispatch(lab, name, args)
                except StopRequested:
                    raise
                except Exception as e:  # report tool errors back to the model
                    result = {"error": f"{type(e).__name__}: {e}"}
                    lab.agent_note("error", traceback.format_exc(limit=2))
                lab.agent_note("tool_result", name, {"result": _brief(name, result)})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": _short(result)})
        if not lab.done:
            lab.finish("Run ended without the agent calling finish (turn limit, stop, or API error).")
        return {"turns": turn + 1, "api_calls": self.client.calls, "usage": self.client.usage}


def _brief(name: str, r) -> dict:
    """Small summary of a tool result for the dashboard trail."""
    if not isinstance(r, dict):
        return {"value": str(r)[:200]}
    keys = {
        "run_experiment": ["experiment_id", "name", "measured_final_C", "predicted_final_C", "coverage_90pct_band", "prediction_held", "fan_energy_J", "refused"],
        "fit_model": ["adopted", "error"],
        "plan_control": ["plan_id", "phases", "predicted_energy_J", "uncertainty_premium_J", "feasible", "refused"],
        "execute_plan": ["status", "hold_done_s", "hold_compliant_s", "task_energy_used_J", "anomaly", "goal_complete", "refused"],
        "look_at_scene": ["source", "changed_vs_reference", "changes", "aim"],
        "evaluate_experiments": ["options"],
        "record_hypothesis": ["hypothesis_id"],
        "conclude": ["ok", "error"],
    }.get(name)
    if not keys:
        return {k: r[k] for k in list(r)[:6]}
    out = {k: r[k] for k in keys if k in r}
    if "adopted" in out:
        out["adopted"] = {"structure": out["adopted"]["structure"], "rmse_K": out["adopted"]["rmse_K"]}
    if "options" in out:
        out["options"] = [{k: o.get(k) for k in ("candidate_id", "name", "fan_energy_J", "expected_information_bits", "goal_uncertainty_K_before_after", "rejected")} for o in out["options"]]
    return out


# ------------------------------------------------------------ scripted baseline

class ScriptedScientist:
    """A fixed protocol with the same tools: the baseline the LLM is compared
    against, and the fallback when no model endpoint is configured."""

    def __init__(self, lab: Lab, adapt: bool = True):
        self.lab = lab
        self.adapt = adapt  # adapt=False: ignores anomalies (no-learning ablation)

    def call(self, name, args):
        self.lab.agent_note("tool_call", name, {"args": args})
        r = dispatch(self.lab, name, args)
        self.lab.agent_note("tool_result", name, {"result": _brief(name, r)})
        return r

    def run(self) -> dict:
        lab = self.lab
        lab.agent_note("system", "agent: scripted protocol (no LLM)")
        self.call("observe", {})
        self.call("look_at_scene", {"reason": "record the reference layout"})
        h1 = self.call("record_hypothesis", {
            "statement": "The heatsink follows Newtonian cooling; fan airflow raises the cooling rate monotonically with duty.",
            "prediction": "Steady temperature with heater on falls as duty rises; each step response is first-order.",
            "falsified_if": "A fitted first-order model misses step responses by more than 0.5 K RMSE."})["hypothesis_id"]
        done_names: set[str] = set()
        for _ in range(6):
            ev = self.call("evaluate_experiments", {"candidates": []})
            opts = [o for o in ev["options"] if "candidate_id" in o and o["safe"] and o["within_budget"]
                    and o["name"] not in done_names]
            if not opts:
                break
            heat = [o for o in opts if o["name"].startswith("heat-up")]
            pick = heat[0] if heat else max(opts, key=lambda o: o["goal_uncertainty_K_before_after"][0] - o["goal_uncertainty_K_before_after"][1])
            before, after = pick["goal_uncertainty_K_before_after"]
            if not heat and before < 0.35:
                break
            done_names.add(pick["name"])
            self.call("run_experiment", {"candidate_id": pick["candidate_id"], "hypothesis_id": h1,
                                         "rationale": f"largest expected cut in goal uncertainty ({before:.2f} -> {after:.2f} K)"})
            self.call("fit_model", {"rationale": "learn from the new data"})
        m = lab.fit.to_json()
        self.call("conclude", {"hypothesis_id": h1, "verdict": "supported" if m["rmse_K"] < 0.5 else "refuted",
                               "evidence": f"best structure {m['structure']}, RMSE {m['rmse_K']} K"})
        for _ in range(6):
            plan = self.call("plan_control", {"rationale": "cheapest robust plan for the goal"})
            if "refused" in plan:
                if not self.adapt and lab.anomaly:
                    lab.anomaly = None
                    lab.model_status = "fitted"
                    continue
                break
            res = self.call("execute_plan", {"plan_id": plan["plan_id"], "rationale": "execute"})
            if res.get("goal_complete") or res.get("status") in ("trip", "stopped"):
                break
            if "anomaly" in res:
                if not self.adapt:
                    continue
                self.investigate(res["anomaly"])
        return self.call("finish", {"summary": "Scripted protocol finished."})

    def investigate(self, anomaly: dict):
        lab = self.lab
        onset = anomaly.get("onset_estimate_t") or lab.rig.now()
        sc = self.call("look_at_scene", {"reason": "anomaly: check whether the setup changed"})
        fan_changed = bool(sc.get("changed_vs_reference"))
        h_fan = self.call("record_hypothesis", {
            "statement": "The fan was moved or turned, so only the fan coupling k1 changed.",
            "prediction": "With the fan off, the old k0 and b still predict the response; with the fan on, cooling is weaker than before.",
            "falsified_if": "The fan-off step also diverges from the old model."})["hypothesis_id"]
        h_heat = self.call("record_hypothesis", {
            "statement": "The heat input changed (heater power), so b*q changed.",
            "prediction": "Even with the fan off, the object runs warmer than the old model predicts.",
            "falsified_if": "The fan-off step matches the old model."})["hypothesis_id"]
        ev = self.call("evaluate_experiments", {"candidates": [
            {"name": "discriminate: fan off, full, then 60%", "steps": [
                {"fan_duty": 0.0, "heater_on": True, "duration_s": 180},
                {"fan_duty": 1.0, "heater_on": True, "duration_s": 150},
                {"fan_duty": 0.6, "heater_on": True, "duration_s": 150}]}]})
        cid = ev["options"][0].get("candidate_id")
        if not cid:
            return
        r = self.call("run_experiment", {"candidate_id": cid, "hypothesis_id": h_fan,
                                         "rationale": "fan-off isolates k0 and b; full fan measures the new coupling"})
        steps = r.get("per_step") or []
        off = steps[0] if steps else {}
        on = steps[1] if len(steps) > 1 else {}
        fan_only = bool(off.get("matched_prediction")) and not on.get("matched_prediction", True)
        nothing = bool(off.get("matched_prediction")) and bool(on.get("matched_prediction"))
        evidence = (f"fan-off step: mean residual {off.get('mean_residual_K')} K, band coverage {off.get('coverage_90pct_band')}; "
                    f"full-fan step: mean residual {on.get('mean_residual_K')} K, coverage {on.get('coverage_90pct_band')}; "
                    f"camera change={fan_changed}")
        if nothing:
            self.call("fit_model", {"rationale": "no physical change found; refine the model with the new data", "since_t": onset})
            for h in (h_fan, h_heat):
                self.call("conclude", {"hypothesis_id": h, "verdict": "inconclusive",
                                       "evidence": "both steps matched the current model; the divergence was model error, not a change in the rig. " + evidence})
        elif fan_only:
            self.call("fit_model", {"rationale": "only the fan coupling changed: hold k0 and b at their trusted values",
                                    "since_t": onset, "hold_params": ["k0", "b"]})
            self.call("conclude", {"hypothesis_id": h_fan, "verdict": "supported", "evidence": evidence})
            self.call("conclude", {"hypothesis_id": h_heat, "verdict": "refuted", "evidence": evidence})
        else:
            self.call("fit_model", {"rationale": "heat balance changed as well: refit all parameters on post-change data",
                                    "since_t": onset})
            self.call("conclude", {"hypothesis_id": h_fan, "verdict": "refuted", "evidence": evidence})
            self.call("conclude", {"hypothesis_id": h_heat, "verdict": "supported" if not fan_changed else "inconclusive",
                                   "evidence": evidence})
