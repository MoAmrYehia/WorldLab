"""The scientist: an LLM (Muse Spark or Muse Glimmer) that runs the farm through
tool calls, plus a scripted baseline that follows a fixed protocol.

The LLM decides what to test, what to believe and what to do; the lab does the
numbers and enforces the budgets. Every tool call and its rationale is written
to the ledger.
"""
from __future__ import annotations

import json
import time
import traceback

from .lab import Lab, StopRequested
from .llm import LLMClient, LLMConfig, APIError

SYSTEM_PROMPT = """You are WorldLab, an AI agronomist-scientist running a 12-hectare farm near Al Ain in the UAE: six 2-hectare fields with different soils (some already saline), drip irrigation from brackish groundwater (4.5 dS/m) that can be blended with desalinated water (less salt, much more energy), a fixed groundwater quota and energy budget, soil moisture and salinity sensors, a weather station, drone imagery and field tests on request.

Goal: feed as many people as possible from one season (1 October to 30 June). A person counts as fed only when calories, protein AND vitamin A are all covered (the scarcest one counts), and plans are judged by a bad year (the 10th percentile), not an average one. The ten candidate crops are wheat, rice, maize, potatoes, cassava, soybeans, sorghum, millet, common beans and sweet potatoes.

The local varieties differ from published values in four hidden traits: water productivity, canopy growth rate, heat tolerance at flowering and salt tolerance. You learn them from trial plots before the season, then plan, then run the season and keep the model honest.

Method:
1. Orient with observe. Make a first plan_season on published values: it tells you which crops matter and what uncertainty costs (cost_of_uncertainty_people).
2. Before trials, record_hypothesis with a numeric prediction and a falsification condition.
3. evaluate_trials (pass your own designs or an empty list for a menu). Choose plots that cut the uncertainty that matters for the plan (production_yield_sd_cut_pct), not just bits. A trait is only learned if a plot exposes it: saline plots expose salt tolerance; sowing late so flowering hits the spring heat exposes heat tolerance. Budget: 16 plots in total.
4. run_trials, then fit_crop_models, then conclude your hypothesis citing predicted vs measured yields.
   If observe shows farmer_choices, the farmer picked the crop (and sowing season) for those fields: plan_season keeps them, so make sure your trials cover those crops, and tell the farmer honestly how their choice compares with yours (plan_season reports scientist_choice).
5. plan_season again. If it relies on crops you never trialled (untested_crops), consider trialling them first.
   Then consider train_irrigation_policy for the final plan: reinforcement learning (evolution strategies) inside your calibrated model learns a daily irrigation and water-blend policy from the sensors, and reports it against the plan's fixed rule on held-out imagined seasons. Start the season with controller rl_policy only if it is recommended; remember it was trained in your model, not on the real farm.
   Then start_season.
6. During the season, advance in steps (up to 60 days), and about once a month look_at_field on a field or two to check your model against the crop itself. The lab runs your model alongside the farm and stops when measurements leave the predicted band. Then investigate instead of guessing:
   - Soil drier than predicted: a clogged or leaking drip line (emitter_flow test) or the crop using more water than modelled.
   - Canopy lower or soil wetter than predicted: pests (leaf_inspection, look_at_field) or salt damage (water_test, soil_sample).
   - Soil salinity higher than predicted: saltier irrigation water (water_test), or less water reaching the roots so less salt is leached (a clogged drip line: emitter_flow). Test both before dismissing.
   - Look before you test: look_at_field sends the drone over the field. Muse Spark compares the photo with the view your own model expects (same plants, predicted canopy, no faults) and SAM 3.1 counts plants and segments salt crust. Use what it sees to shape your hypotheses; a photo is evidence, not proof, so confirm with a field test.
   - Record competing hypotheses, run the test that tells them apart, conclude.
   - Act on what you found (adjust_field: repair_drip, pest_control, more desalinated water), then update_model with the measured value and the onset day so predictions match reality again. Use dismiss_anomaly only if the tests show nothing changed.
   - After a fault that cost water or yield, rebalance_water to re-plan irrigation for the rest of the season within the remaining quota.
   - The policy was trained on a fault-free farm. If you diagnose a fault, you may set_irrigation_controller back to rule.
7. Keep advancing to the end of the season (30 June), then finish with an honest summary: what you learned about the varieties, what went wrong, what it cost, how many people the farm feeds.

Style: keep messages to one or two sentences. Put reasoning in each tool's rationale argument; it is recorded in the audit ledger and shown on the dashboard."""

CROP_ENUM = ["wheat", "rice", "maize", "potato", "cassava", "soybean", "sorghum", "millet", "beans", "sweet_potato"]
TRIAL_SPEC = {"type": "object", "properties": {
    "crop": {"type": "string", "enum": CROP_ENUM},
    "sow": {"type": "integer", "description": "sowing day, 0 = 1 October, up to 200"},
    "plot": {"type": "string", "enum": ["normal", "saline"]},
    "irr": {"type": "number", "description": "irrigation as a fraction of crop water demand, 0.4-1.3"},
    "desal": {"type": "number", "description": "fraction of desalinated water, 0-1"},
    "nfert": {"type": "number", "description": "nitrogen, kg/ha"}},
    "required": ["crop", "sow", "plot"]}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}
TOOLS = [
    {"name": "observe", "description": "Phase, date, fields, budgets, forecast, latest projection of people fed, and any open anomaly.",
     "parameters": _obj({}, [])},
    {"name": "get_beliefs", "description": "Current belief about each crop's four local-variety traits (mean and sd) and how many trial plots inform it.",
     "parameters": _obj({"crops": {"type": "array", "items": S}}, [])},
    {"name": "record_hypothesis", "description": "Record a testable hypothesis before testing it.",
     "parameters": _obj({"statement": S, "prediction": S, "falsified_if": S}, ["statement", "prediction", "falsified_if"])},
    {"name": "conclude", "description": "Mark a hypothesis supported, refuted or inconclusive, citing evidence.",
     "parameters": _obj({"hypothesis_id": S, "verdict": {"type": "string", "enum": ["supported", "refuted", "inconclusive"]},
                         "evidence": S}, ["hypothesis_id", "verdict", "evidence"])},
    {"name": "evaluate_trials", "description": "Score candidate trial plots: predicted yield, expected information, and how much each cuts the yield uncertainty that matters for the plan. Empty list = a menu built from the current plan's crops. Returns candidate_ids.",
     "parameters": _obj({"candidates": {"type": "array", "items": TRIAL_SPEC}}, ["candidates"])},
    {"name": "run_trials", "description": "Grow the chosen trial plots for one season and compare each harvest with the prediction made beforehand.",
     "parameters": _obj({"candidate_ids": {"type": "array", "items": S}, "hypothesis_id": S, "rationale": S},
                        ["candidate_ids", "hypothesis_id", "rationale"])},
    {"name": "fit_crop_models", "description": "Calibrate each trialled crop's traits from all its plots (Bayesian, starting from the published prior).",
     "parameters": _obj({"rationale": S, "crops": {"type": "array", "items": S}}, ["rationale"])},
    {"name": "plan_season", "description": "Choose crop, sowing day, irrigation level, desal blend and nitrogen for each field to maximise people fed in a bad year within the water quota and energy budget.",
     "parameters": _obj({"rationale": S}, ["rationale"])},
    {"name": "train_irrigation_policy", "description": "Reinforcement learning: train a daily irrigation and desal-blend policy for a plan by evolution strategies inside your calibrated model (crop traits from your beliefs, weather from the climate). Takes about a minute. Returns the policy against the plan's fixed rule on held-out imagined seasons, and a recommendation.",
     "parameters": _obj({"plan_id": S, "rationale": S, "iterations": {"type": "integer", "description": "10-120, default 50"}},
                        ["plan_id", "rationale"])},
    {"name": "start_season", "description": "Sow according to a plan. No more trials after this. controller: rule (the plan's fixed irrigation levels) or rl_policy (the trained policy for this plan).",
     "parameters": _obj({"plan_id": S, "rationale": S, "controller": {"type": "string", "enum": ["rule", "rl_policy"]}},
                        ["plan_id", "rationale"])},
    {"name": "set_irrigation_controller", "description": "Switch daily irrigation between the plan's rule and the trained RL policy from today.",
     "parameters": _obj({"controller": {"type": "string", "enum": ["rule", "rl_policy"]}, "rationale": S}, ["controller", "rationale"])},
    {"name": "advance", "description": "Run the season forward up to 60 days. Stops early if measurements leave the model's predicted band.",
     "parameters": _obj({"days": {"type": "integer"}, "rationale": S}, ["days", "rationale"])},
    {"name": "look_at_field", "description": "Fly the drone over a field. SAM 3.1 counts plants (on image tiles) and segments white salt crust; Muse Spark compares the photo with the view your model expects and diagnoses stress, pests or salt; also measured vs predicted canopy cover.",
     "parameters": _obj({"field": S, "reason": S}, ["field", "reason"])},
    {"name": "field_test", "description": "Run a field test: emitter_flow (drip delivery vs design), soil_sample (salinity by layer vs model), water_test (groundwater salinity vs model), leaf_inspection (pests).",
     "parameters": _obj({"field": S, "test": {"type": "string", "enum": ["emitter_flow", "soil_sample", "water_test", "leaf_inspection"]},
                         "rationale": S}, ["field", "test", "rationale"])},
    {"name": "adjust_field", "description": "Change a field from today: irrigation level, desal blend, repair the drip line, or apply pest control.",
     "parameters": _obj({"field": S, "rationale": S, "irr": {"type": "number"}, "desal": {"type": "number"},
                         "repair_drip": {"type": "boolean"}, "pest_control": {"type": "boolean"}}, ["field", "rationale"])},
    {"name": "update_model", "description": "Teach the model a diagnosed fact so its predictions match reality again: drip_delivery (measured delivered fraction), pest (daily canopy loss fraction, e.g. 0.03) or groundwater_ec (dS/m), from since_day.",
     "parameters": _obj({"rationale": S, "finding": {"type": "string", "enum": ["drip_delivery", "pest", "groundwater_ec"]},
                         "value": {"type": "number"}, "since_day": {"type": "integer"}, "field": S},
                        ["rationale", "finding", "value", "since_day"])},
    {"name": "dismiss_anomaly", "description": "Close an anomaly when tests show nothing physical changed.",
     "parameters": _obj({"rationale": S}, ["rationale"])},
    {"name": "rebalance_water", "description": "Re-plan irrigation level and desal blend per field for the rest of the season within the remaining quota and energy.",
     "parameters": _obj({"rationale": S}, ["rationale"])},
    {"name": "finish", "description": "End the run with an honest summary.",
     "parameters": _obj({"summary": S}, ["summary"])},
]


def dispatch(lab: Lab, name: str, a: dict):
    if name == "observe":
        return lab.observe()
    if name == "get_beliefs":
        return lab.get_beliefs(a.get("crops"))
    if name == "record_hypothesis":
        return lab.record_hypothesis(a["statement"], a["prediction"], a["falsified_if"])
    if name == "conclude":
        return lab.conclude(a["hypothesis_id"], a["verdict"], a["evidence"])
    if name == "evaluate_trials":
        return lab.evaluate_trials(a.get("candidates") or None)
    if name == "run_trials":
        return lab.run_trials(a.get("candidate_ids", []), a.get("hypothesis_id", ""), a.get("rationale", ""))
    if name == "fit_crop_models":
        return lab.fit_crop_models(a.get("rationale", ""), a.get("crops"))
    if name == "plan_season":
        return lab.plan_season(a.get("rationale", ""))
    if name == "train_irrigation_policy":
        return lab.train_irrigation_policy(a.get("plan_id", ""), a.get("rationale", ""), int(a.get("iterations") or 50))
    if name == "start_season":
        return lab.start_season(a.get("plan_id", ""), a.get("rationale", ""), a.get("controller") or "rule")
    if name == "set_irrigation_controller":
        return lab.set_irrigation_controller(a.get("controller", ""), a.get("rationale", ""))
    if name == "advance":
        return lab.advance(int(a.get("days", 30)), a.get("rationale", ""))
    if name == "look_at_field":
        return lab.look_at_field(a.get("field", ""), a.get("reason", ""))
    if name == "field_test":
        return lab.field_test(a.get("field", ""), a.get("test", ""), a.get("rationale", ""))
    if name == "adjust_field":
        return lab.adjust_field(a.get("field", ""), a.get("rationale", ""), irr=a.get("irr"), desal=a.get("desal"),
                                repair_drip=bool(a.get("repair_drip")), pest_control=bool(a.get("pest_control")))
    if name == "update_model":
        return lab.update_model(a.get("rationale", ""), a.get("finding", ""), float(a.get("value", 0)),
                                int(a.get("since_day", lab.day)), a.get("field"))
    if name == "dismiss_anomaly":
        return lab.dismiss_anomaly(a.get("rationale", ""))
    if name == "rebalance_water":
        return lab.rebalance_water(a.get("rationale", ""))
    if name == "finish":
        return lab.finish(a.get("summary", ""))
    return {"error": f"unknown tool {name}"}


def _short(obj, limit=7000) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= limit else s[:limit] + '..."(truncated)"'


def _brief(name: str, r) -> dict:
    if not isinstance(r, dict):
        return {"value": str(r)[:200]}
    keep = {
        "run_trials": ["round", "plots_left", "refused"],
        "fit_crop_models": ["error"],
        "plan_season": ["plan_id", "people_p10", "people_p50", "limiting", "cost_of_uncertainty_people", "untested_crops", "refused"],
        "advance": ["stopped_because", "day", "date", "anomaly", "result", "refused"],
        "field_test": None,
        "look_at_field": ["field", "canopy_cover_measured", "canopy_cover_predicted", "plants_counted", "salt_crust_patches", "diagnosis", "source"],
        "rebalance_water": ["people_p10_before", "people_p10_after"],
        "train_irrigation_policy": ["recommend", "trained_seconds", "best_checkpoint_iter", "held_out_comparison", "refused"],
        "record_hypothesis": ["hypothesis_id"], "update_model": ["ok", "error"],
    }.get(name, list(r)[:5])
    return dict(r) if keep is None else {k: r[k] for k in keep if k in r}


class LLMScientist:
    def __init__(self, lab: Lab, cfg: LLMConfig, max_turns: int = 120):
        self.lab, self.cfg = lab, cfg
        self.client = LLMClient(cfg)
        self.max_turns = max_turns

    def run(self) -> dict:
        lab = self.lab
        tools = [{"type": "function", "function": t} for t in TOOLS]
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "Begin. Current state:\n" + _short(lab.observe())}]
        lab.agent_note("system", f"agent: {self.cfg.label} · model {self.cfg.model}")
        nudges = 0
        turn = 0
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
                messages.append({"role": "user", "content": "Continue by calling a tool. When the season is over, call finish."})
                continue
            messages.append({"role": "assistant", "content": text, "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments") or "{}"}} for c in calls]})
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
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}
                    lab.agent_note("error", traceback.format_exc(limit=2))
                lab.agent_note("tool_result", name, {"result": _brief(name, result)})
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": _short(result)})
        if not lab.done:
            lab.finish("Run ended without the agent calling finish (turn limit, stop, or API error).")
        return {"turns": turn + 1, "api_calls": self.client.calls, "usage": self.client.usage}


# ------------------------------------------------------------ scripted baseline

class ScriptedScientist:
    """A fixed protocol over the same tools: the baseline the LLM is compared
    against, and the fallback without a model endpoint. adapt=False ignores
    anomalies (the no-learning ablation); trials=False skips calibration."""

    def __init__(self, lab: Lab, adapt: bool = True, trials: bool = True, rl: bool = False):
        self.lab, self.adapt, self.trials, self.rl = lab, adapt, trials, rl

    def call(self, name, args):
        self.lab.agent_note("tool_call", name, {"args": args})
        r = dispatch(self.lab, name, args)
        self.lab.agent_note("tool_result", name, {"result": _brief(name, r)})
        return r

    def _trial_round(self, h, crops=None, n=10):
        menu = self.lab.default_trial_menu()
        if crops:
            menu = []
            for c in crops:
                from .farm.crops import CROPS
                a, b = CROPS[c]["sow"]
                base = {"crop": c, "irr": 1.0, "desal": 0.0, "nfert": CROPS[c]["nreq"]}
                menu += [{**base, "sow": (a + b) // 2, "plot": "normal"}, {**base, "sow": (a + b) // 2, "plot": "saline"},
                         {**base, "sow": min(b + 35, 200), "plot": "normal"}]
        ev = self.call("evaluate_trials", {"candidates": menu})
        opts = [o for o in ev.get("options", []) if "candidate_id" in o]
        n = min(n, ev.get("plots_left", 0), len(opts), self.lab.limits.plots_per_round)
        if n <= 0:
            return None
        opts.sort(key=lambda o: -o["production_yield_sd_cut_pct"])
        chosen, seen = [], set()
        for o in opts:                      # the most useful plot for each crop first
            if o["spec"]["crop"] not in seen:
                chosen.append(o)
                seen.add(o["spec"]["crop"])
        for o in opts:
            if len(chosen) >= n:
                break
            if o not in chosen:
                chosen.append(o)
        return self.call("run_trials", {"candidate_ids": [o["candidate_id"] for o in chosen[:n]], "hypothesis_id": h,
                                        "rationale": "plots that most cut the yield uncertainty where the plan would use each crop"})

    def _leave_policy(self, r: dict):
        if r.get("rl_policy_warning"):
            self.call("set_irrigation_controller", {"controller": "rule",
                                                    "rationale": "the farm is now outside the conditions the policy was trained on"})

    def run(self) -> dict:
        lab = self.lab
        lab.agent_note("system", "agent: scripted protocol (no LLM)" + ("" if self.adapt else ", ignores anomalies"))
        self.call("observe", {})
        p0 = self.call("plan_season", {"rationale": "first plan on published crop values, to see which crops matter"})
        p1 = p0
        if self.trials:
            h = self.call("record_hypothesis", {
                "statement": "The farm's local varieties differ from published values in ways that change the plan.",
                "prediction": f"Calibration changes the plan's bad-year outcome and cuts the cost of uncertainty ({p0['cost_of_uncertainty_people']} people now).",
                "falsified_if": "Trial yields all fall inside the published-value predictions and the plan does not change."})["hypothesis_id"]
            r1 = self._trial_round(h)
            self.call("fit_crop_models", {"rationale": "learn from the first trial round"})
            p1 = self.call("plan_season", {"rationale": "re-plan with calibrated beliefs"})
            if p1.get("untested_crops") and lab.limits.trial_plots - lab.plots_used > 0:
                self._trial_round(h, crops=p1["untested_crops"], n=lab.limits.trial_plots - lab.plots_used)
                self.call("fit_crop_models", {"rationale": "learn the crops the plan added"})
                p1 = self.call("plan_season", {"rationale": "re-plan after the second round"})
            plots = (r1 or {}).get("plots", [])
            missed = sum(1 for x in plots if not x["prediction_held"])
            self.call("conclude", {"hypothesis_id": h, "verdict": "supported" if missed or p1["people_p10"] != p0["people_p10"] else "refuted",
                                   "evidence": f"{missed} of {len(plots)} trial predictions missed; plan P10 {p0['people_p10']} -> "
                                               f"{p1['people_p10']} people; cost of uncertainty {p0['cost_of_uncertainty_people']} -> "
                                               f"{p1['cost_of_uncertainty_people']}"})
        controller = "rule"
        if self.rl:
            t = self.call("train_irrigation_policy", {"plan_id": p1["plan_id"], "rationale": "learn a sensor-driven daily irrigation policy for this plan in the calibrated model"})
            controller = t.get("recommend", "rule")
        self.call("start_season", {"plan_id": p1["plan_id"], "rationale": "best robust plan", "controller": controller})
        for _ in range(40):
            r = self.call("advance", {"days": 60, "rationale": "run the season"})
            if lab.phase != "season":
                break
            if r.get("anomaly"):
                if self.adapt:
                    self.investigate(r["anomaly"])
                    if lab.anomaly:
                        self.call("dismiss_anomaly", {"rationale": "unresolved after tests"})
                else:
                    self.call("dismiss_anomaly", {"rationale": "baseline ignores anomalies"})
        res = lab.result or {}
        return self.call("finish", {"summary": f"Scripted protocol finished: {res.get('people_fed')} people fed."})

    # ------------------------------------------------ human decision mode: the person may pick tests and approve actions
    TEST_OPTIONS = [("water_test", "Water test", "groundwater salinity against the model's assumption"),
                    ("emitter_flow", "Emitter flow test", "drip delivery against design flow"),
                    ("soil_sample", "Soil sample", "salinity in each soil layer"),
                    ("leaf_inspection", "Leaf inspection", "insects and leaf damage")]

    def _human_first_test(self, a: dict):
        if not self.lab.human:
            return
        default = "water_test" if a["signal"] == "ec" else "emitter_flow" if a["signal"] == "sw" else "leaf_inspection"
        opts = [{"id": "auto", "label": "Let the scientist choose", "detail": f"it would start with the {dict((k, l) for k, l, _ in self.TEST_OPTIONS)[default].lower()}"}]
        opts += [{"id": k, "label": l, "detail": d} for k, l, d in self.TEST_OPTIONS]
        ch = self.lab.ask_human("first_test", f"Alarm in {a['field']}: {a['signal_label']} {a['direction']}. Which test should run first?",
                                opts, "auto", {"field": a["field"], "signal": a["signal"]})
        if ch != "auto":
            self._test(a["field"], ch, "chosen by you in human decision mode")

    def _test(self, f: str, test: str, rationale: str) -> dict:
        """Run a field test once per investigation; a test you already chose is reused, not paid for twice."""
        if test not in self._tests:
            self._tests[test] = self.call("field_test", {"field": f, "test": test, "rationale": rationale})
        return self._tests[test]

    def _act(self, f: str, args: dict):
        what = "Repair the drip line" if args.get("repair_drip") else "Apply pest control" if args.get("pest_control") else "Adjust the field"
        ch = self.lab.ask_human("approve_action", f"{what} in {f}? Evidence: {args.get('rationale', '')}.",
                                [{"id": "approve", "label": "Approve", "detail": what.lower()},
                                 {"id": "decline", "label": "Decline", "detail": "leave the field as it is; the scientist still updates its model"}],
                                "approve", {"field": f})
        if ch == "approve":
            return self.call("adjust_field", {"field": f, **args})
        self.lab.agent_note("system", f"{what} in {f} declined by you")
        return {"declined": True}

    def investigate(self, a: dict):
        f, onset = a["field"], a["onset_day"]
        self._tests = {}
        self._human_first_test(a)
        self.call("look_at_field", {"field": f, "reason": f"{a['signal_label']} {a['direction']}"})
        if a["signal"] == "ec" and "higher" in a["direction"]:
            hs = self.call("record_hypothesis", {"statement": "The groundwater has become saltier than the model assumes.",
                                                 "prediction": "The water test reads well above the assumed 4.5 dS/m.",
                                                 "falsified_if": "The water test is within 1 dS/m of the assumption."})["hypothesis_id"]
            wt = self._test(f, "water_test", "saltier water would raise soil salinity")
            ec = wt.get("groundwater_ec_dS_m", 4.5)
            if ec > wt.get("assumed_by_model", 4.5) + 1.0:
                r = self.call("update_model", {"finding": "groundwater_ec", "value": ec, "since_day": onset,
                                               "rationale": f"water test {ec} dS/m"})
                self._leave_policy(r)
                self.call("conclude", {"hypothesis_id": hs, "verdict": "supported", "evidence": f"water test {ec} dS/m"})
                self.call("rebalance_water", {"rationale": "blend more desalinated water where it pays"})
                return
            self.call("conclude", {"hypothesis_id": hs, "verdict": "refuted", "evidence": f"water test {ec} dS/m"})
            hc = self.call("record_hypothesis", {"statement": f"The drip line in {f} is clogged or leaking, so less salt is leached.",
                                                 "prediction": "The emitter flow test reads well below the design flow.",
                                                 "falsified_if": "Emitters deliver at least 90% of design flow."})["hypothesis_id"]
            t = self._test(f, "emitter_flow", "under-delivery cuts leaching and concentrates salt")
            v = t.get("delivered_vs_design", 1.0)
            if v < 0.85 * t.get("expected_if_healthy", 1.0):
                self._act(f, {"repair_drip": True, "rationale": f"emitters deliver {v:.0%} of design"})
                self.call("update_model", {"finding": "drip_delivery", "value": v, "since_day": max(onset - 14, 0), "field": f,
                                           "rationale": "the salt built up because the crop received this fraction of its water"})
                self.call("conclude", {"hypothesis_id": hc, "verdict": "supported", "evidence": f"emitter flow {v:.2f} of design"})
                self.call("rebalance_water", {"rationale": "re-plan irrigation after the fault"})
            else:
                self.call("conclude", {"hypothesis_id": hc, "verdict": "refuted", "evidence": f"emitter flow {v:.2f} of design"})
                self.call("dismiss_anomaly", {"rationale": "water and delivery normal; salinity model error"})
            return
        if a["signal"] == "sw" and "drier" in a["direction"]:
            h1 = self.call("record_hypothesis", {"statement": f"The drip line in {f} is clogged or leaking.",
                                                 "prediction": "The emitter flow test reads well below the design flow.",
                                                 "falsified_if": "Emitters deliver at least 90% of design flow."})["hypothesis_id"]
            h2 = self.call("record_hypothesis", {"statement": f"The crop in {f} uses more water than the model predicts.",
                                                 "prediction": "Emitters deliver the design flow.",
                                                 "falsified_if": "Emitter flow is low."})["hypothesis_id"]
            t = self._test(f, "emitter_flow", "separates a delivery fault from crop water use")
            v = t.get("delivered_vs_design", 1.0)
            ev = f"emitter flow {v:.2f} of design"
            if v < 0.85 * t.get("expected_if_healthy", 1.0):
                self._act(f, {"repair_drip": True, "rationale": ev})
                self.call("update_model", {"finding": "drip_delivery", "value": v, "since_day": onset, "field": f,
                                           "rationale": "the crop received this fraction from the onset until the repair"})
                self.call("conclude", {"hypothesis_id": h1, "verdict": "supported", "evidence": ev})
                self.call("conclude", {"hypothesis_id": h2, "verdict": "refuted", "evidence": ev})
                self.call("rebalance_water", {"rationale": "re-plan irrigation after the fault"})
            else:
                self.call("conclude", {"hypothesis_id": h1, "verdict": "refuted", "evidence": ev})
                self.call("conclude", {"hypothesis_id": h2, "verdict": "inconclusive", "evidence": "delivery normal; likely model error"})
                self.call("dismiss_anomaly", {"rationale": "no physical fault found"})
            return
        hp = self.call("record_hypothesis", {"statement": f"Pests are eating the canopy in {f}.",
                                             "prediction": "Leaf inspection finds insects and damage.",
                                             "falsified_if": "No pests on inspection."})["hypothesis_id"]
        hs = self.call("record_hypothesis", {"statement": "The groundwater has become saltier than the model assumes.",
                                             "prediction": "The water test reads well above the assumed 4.5 dS/m.",
                                             "falsified_if": "The water test is within 1 dS/m of the assumption."})["hypothesis_id"]
        li = self._test(f, "leaf_inspection", "pests would explain lost canopy")
        if li.get("pest_damage_seen"):
            rate = 0.03 if li.get("severity") == "heavy" else 0.01
            self._act(f, {"pest_control": True, "rationale": f"{li.get('severity')} pest damage"})
            self.call("update_model", {"finding": "pest", "value": rate, "since_day": onset, "field": f,
                                       "rationale": "canopy loss rate from the onset until treatment"})
            self.call("conclude", {"hypothesis_id": hp, "verdict": "supported", "evidence": f"{li.get('insects_per_leaf')} insects per leaf"})
            self.call("conclude", {"hypothesis_id": hs, "verdict": "inconclusive", "evidence": "not needed: pests explain the loss"})
            self.call("rebalance_water", {"rationale": "re-plan after canopy loss"})
            return
        wt = self._test(f, "water_test", "salty water would stunt the canopy")
        ec = wt.get("groundwater_ec_dS_m", 4.5)
        self.call("conclude", {"hypothesis_id": hp, "verdict": "refuted", "evidence": "no pests on inspection"})
        if ec > wt.get("assumed_by_model", 4.5) + 1.0:
            r = self.call("update_model", {"finding": "groundwater_ec", "value": ec, "since_day": onset,
                                           "rationale": f"water test {ec} dS/m"})
            self._leave_policy(r)
            self.call("conclude", {"hypothesis_id": hs, "verdict": "supported", "evidence": f"water test {ec} dS/m"})
            self.call("rebalance_water", {"rationale": "blend more desalinated water where it pays"})
            return
        self.call("conclude", {"hypothesis_id": hs, "verdict": "refuted", "evidence": f"water test {ec} dS/m"})
        self.call("dismiss_anomaly", {"rationale": "no physical cause found; model error"})
