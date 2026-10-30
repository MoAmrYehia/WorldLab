"""The farm lab: everything the agent can do, with numbers attached.

The agent (Muse Spark, Muse Glimmer, or the scripted baseline) decides; this
module executes. It runs trial plots, calibrates beliefs, plans the season,
runs it day by day with a monitoring ensemble, performs field tests and
corrections, and writes every step to the hash-chained ledger.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import queue
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

from .farm import weather as WX
from .farm.belief import CropBelief, calibrate, trial_information, typical_year, predict_trials
from .farm.crops import CROPS, CROP_IDS, NUTRIENTS, NEEDS, TRAITS, TRAIT_IDS, nutrients_per_ha, people_fed
from .farm.optimize import evaluate, optimise, allowed_options, MG_KEYS
from .farm import seasons as SEASONS
from .farm.sim import Sim, crop_arrays, soil_arrays, DRIP_EFF_NOMINAL, LEACH_FRACTION, PRE_IRRIGATION_MM, KWH_PUMP, KWH_DESAL
from .farm.world import Farm, FIELDS, FIELD_HA, EC_GROUNDWATER
from .farm import rl as RL
from .ledger import Ledger

D = WX.SEASON_DAYS
NF = len(FIELDS)
TESTS = ("emitter_flow", "soil_sample", "water_test", "leaf_inspection")


@dataclass
class Limits:
    trial_plots: int = 16
    plots_per_round: int = 10
    field_tests: int = 30
    water_quota_m3: float = 60000.0
    energy_kwh: float = 90000.0
    max_advance_days: int = 60


# ---------------------------------------------------------------------- bus

class Bus:
    """Fan-out of live events to dashboard clients, plus a snapshot for late joiners."""
    LISTS = ("days", "events", "agent", "perturbations", "beliefs_hist", "projections", "trials", "rl_train")

    def __init__(self):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._rec = None
        self.reset()

    def record_to(self, path: str | Path | None):
        """Append every published message, with its time, to a JSON-lines file for replay."""
        with self._lock:
            if self._rec:
                self._rec.close()
            self._rec = open(path, "a", encoding="utf-8") if path else None
            self._t0 = time.time()

    def reset(self):
        self._t0 = time.time()
        self.snapshot = {k: [] for k in self.LISTS}
        self.snapshot.update({"scene": {}, "plan": None, "status": {}, "beliefs": None, "fields": None, "rl": None})

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=5000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, kind: str, payload):
        s = self.snapshot
        if kind == "day":
            s["days"].append(payload)
        elif kind == "ledger":
            s["events"].append(payload)
        elif kind == "agent":
            s["agent"].append(payload)
        elif kind == "perturbation":
            s["perturbations"].append(payload)
        elif kind == "beliefs":
            s["beliefs"] = payload
            s["beliefs_hist"].append(payload)
        elif kind == "projection":
            s["projections"].append(payload)
        elif kind == "trials":
            s["trials"].append(payload)
        elif kind == "rl_train":
            s["rl_train"].append(payload)
        elif kind == "scene":
            s["scene"][payload.get("field", "?")] = payload
        elif kind in ("plan", "status", "fields", "rl"):
            s[kind] = payload
        msg = {"kind": kind, "data": payload}
        with self._lock:
            if self._rec:
                try:
                    from .server import dumps
                    self._rec.write(dumps({"t": round(time.time() - self._t0, 3), **msg}) + "\n")
                    self._rec.flush()
                except (OSError, ValueError):
                    pass
            for q in list(self._subs):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


class StopRequested(Exception):
    pass


class Lab:
    def __init__(self, farm: Farm, limits: Limits | None = None, run_dir: str | Path | None = None,
                 perception=None, bus: Bus | None = None, speed: float = 0.0):
        self.farm = farm
        self.limits = limits or Limits()
        self.bus = bus or Bus()
        self.perception = perception
        self.speed = speed                         # dashboard pacing, simulated days per second (0 = flat out)
        self.run_dir = Path(run_dir) if run_dir else None
        if self.run_dir:
            (self.run_dir / "images").mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.run_dir / "ledger.jsonl" if self.run_dir else None)
        self.beliefs = {c: CropBelief(c) for c in CROP_IDS}
        self.priors = {c: (b.mean.copy(), b.cov.copy()) for c, b in self.beliefs.items()}
        self.trial_data: dict[str, list] = {c: [] for c in CROP_IDS}
        self.plots_used = 0
        self.trial_rounds = 0
        self.candidates: dict[str, dict] = {}
        self.plans: dict[str, dict] = {}
        self.hyps: dict[str, dict] = {}
        self.tests_used = 0
        self.phase = "trials"
        self.day = 0
        self.anomaly: dict | None = None
        self.anomalies: list[dict] = []
        self.done = False
        self.stop_flag = threading.Event()
        self._ids = {"H": 0, "C": 0, "P": 0, "R": 0}
        self.wx_typ = typical_year()
        self.water_used = 0.0
        self.energy_used = 0.0
        self.harvest: dict[str, dict] = {}
        self.season_plan = None
        self.result = None
        self.policy: dict | None = None            # trained irrigation policy (RL), for one plan
        self.controller = "rule"
        self.run_plan_id = None
        self.policy_trace: list[dict] = []
        self.crop_choices: list[dict | None] = [None] * NF   # the farmer's picks per field
        self._log("run_start", {"limits": asdict(self.limits), "fields": [
            {k: f[k] for k in ("id", "name", "layers", "ece", "soil_n")} for f in FIELDS],
            "goal": "maximise people fed (scarcest of calories, protein, vitamin A) in a bad year (P10), "
                    f"within {self.limits.water_quota_m3:.0f} m3 groundwater and {self.limits.energy_kwh:.0f} kWh"})
        self._publish_beliefs()
        self._status()

    # ============================================================ plumbing
    def _id(self, p):
        self._ids[p] += 1
        return f"{p}{self._ids[p]}"

    def _log(self, kind: str, data: dict) -> dict:
        e = self.ledger.append(kind, data, t_rig=self.day)
        self.bus.publish("ledger", e)
        return e

    def agent_note(self, role: str, text: str, extra: dict | None = None):
        item = {"t": self.day, "role": role, "text": text, **(extra or {})}
        self.bus.publish("agent", item)
        self._log("agent_step", item)

    def _check_stop(self):
        if self.stop_flag.is_set():
            raise StopRequested()

    def _status(self):
        self.bus.publish("status", {
            "phase": self.phase, "day": self.day, "date": WX.day_label(min(self.day, D - 1)),
            "plots_used": self.plots_used, "plots_budget": self.limits.trial_plots,
            "tests_used": self.tests_used, "tests_budget": self.limits.field_tests,
            "water_used_m3": round(self.water_used), "water_quota_m3": self.limits.water_quota_m3,
            "energy_used_kwh": round(self.energy_used), "energy_kwh": self.limits.energy_kwh,
            "anomaly": self.anomaly, "done": self.done, "hypotheses": list(self.hyps.values()),
            "harvest": self.harvest, "result": self.result, "controller": self.controller,
        })

    def _publish_beliefs(self):
        self.bus.publish("beliefs", {"day": self.day, "phase": self.phase,
                                     "crops": [self.beliefs[c].to_json() for c in CROP_IDS]})

    def _fi(self, field):
        for i, f in enumerate(FIELDS):
            if str(field).upper() in (f["id"], f["name"].upper()):
                return i
        return None

    # ============================================================ shared tools
    def record_hypothesis(self, statement: str, prediction: str, falsified_if: str) -> dict:
        hid = self._id("H")
        h = {"id": hid, "statement": statement, "prediction": prediction, "falsified_if": falsified_if,
             "status": "open", "created_day": self.day, "phase": self.phase, "evidence": []}
        self.hyps[hid] = h
        self._log("hypothesis", h)
        self._status()
        return {"hypothesis_id": hid, "recorded": True}

    def conclude(self, hypothesis_id: str, verdict: str, evidence: str) -> dict:
        h = self.hyps.get(hypothesis_id)
        if not h:
            return {"error": f"unknown hypothesis {hypothesis_id}"}
        if verdict not in ("supported", "refuted", "inconclusive"):
            return {"error": "verdict must be supported, refuted or inconclusive"}
        h["status"] = verdict
        h["evidence"].append({"day": self.day, "text": evidence})
        self._log("conclusion", {"hypothesis_id": hypothesis_id, "verdict": verdict, "evidence": evidence})
        self._status()
        return {"ok": True, "hypothesis": h}

    def get_beliefs(self, crops: list[str] | None = None) -> dict:
        crops = [c for c in (crops or CROP_IDS) if c in CROPS]
        out = []
        for c in crops:
            b = self.beliefs[c].to_json()
            b["trial_plots"] = len(self.trial_data[c])
            out.append(b)
        return {"crops": out, "trait_meaning": {k: v["about"] for k, v in TRAITS.items()}}

    # ============================================================ trial phase
    def default_trial_menu(self) -> list[dict]:
        """Three designs per crop in the current plan (or common candidates): a normal
        plot in the sowing window, a saline plot (exposes salt tolerance) and a late
        sowing (flowering in the spring heat, exposes heat tolerance)."""
        crops = [f["crop"] for f in (self.season_plan or {}).get("fields", []) if f.get("crop")] or \
            ["wheat", "maize", "potato", "sorghum", "sweet_potato", "beans"]
        menu = []
        for c in dict.fromkeys(crops):
            a, b = CROPS[c]["sow"]
            base = {"crop": c, "density": 1.0, "irr": 1.0, "desal": 0.0, "nfert": CROPS[c]["nreq"], "mulch": 1}
            menu.append({**base, "sow": (a + b) // 2, "plot": "normal"})
            menu.append({**base, "sow": (a + b) // 2, "plot": "saline"})
            menu.append({**base, "sow": min(b + 35, 200), "plot": "normal"})
        return menu

    def _reference_use(self, crop: str):
        for f in (self.season_plan or {}).get("fields", []):
            if f.get("crop") == crop:
                return {"field": f["field_index"], "mgmt": f["mgmt"]}
        return None

    def _norm_trial(self, c: dict):
        if c.get("crop") not in CROPS:
            return f"unknown crop {c.get('crop')}"
        crop = c["crop"]
        try:
            t = {"crop": crop, "sow": int(c.get("sow", sum(CROPS[crop]["sow"]) // 2)),
                 "density": float(c.get("density", 1.0)), "irr": float(c.get("irr", 1.0)),
                 "desal": float(c.get("desal", 0.0)), "nfert": float(c.get("nfert", CROPS[crop]["nreq"])),
                 "mulch": float(c.get("mulch", 1)), "plot": c.get("plot", "normal")}
        except (TypeError, ValueError):
            return "bad numbers in trial spec"
        if not 0 <= t["sow"] <= 200 or not 0.4 <= t["irr"] <= 1.3 or not 0 <= t["desal"] <= 1 or t["plot"] not in ("normal", "saline"):
            return "sow 0-200, irr 0.4-1.3, desal 0-1, plot normal|saline"
        return t

    def evaluate_trials(self, candidates: list[dict] | None = None) -> dict:
        if self.phase not in ("trials", "planning"):
            return {"refused": "trials can only be run before the season starts"}
        candidates = candidates or self.default_trial_menu()
        out = []
        for c in candidates[:24]:
            t = self._norm_trial(c)
            if isinstance(t, str):
                out.append({"rejected": t, "spec": c})
                continue
            info = trial_information(self.beliefs[t["crop"]], t, self.wx_typ, self._reference_use(t["crop"]))
            cid = self._id("C")
            rec = {"candidate_id": cid, "spec": t, "predicted_yield_t_ha": round(info["pred_yield"], 2),
                   "expected_information_bits": round(info["bits"], 2),
                   "production_yield_sd_t_ha_before_after": [round(info["ref_sd_before"], 3), round(info["ref_sd_after"], 3)],
                   "production_yield_sd_cut_pct": round(100 * (1 - info["ref_sd_after"] / max(info["ref_sd_before"], 1e-9)), 1),
                   "trait_sd_after": info["trait_sd_after"]}
            self.candidates[cid] = rec
            out.append(rec)
        self._log("trial_options", {"options": out})
        return {"options": out, "plots_left": self.limits.trial_plots - self.plots_used,
                "note": "information is linearised at the current belief; 'production_yield_sd' is the uncertainty in "
                        "this crop's yield where the plan would grow it (or on a normal and a saline field if unplanned)"}

    def run_trials(self, candidate_ids: list[str], hypothesis_id: str, rationale: str) -> dict:
        self._check_stop()
        if self.phase not in ("trials", "planning"):
            return {"refused": "the season has started; no more trials"}
        if hypothesis_id not in self.hyps:
            return {"refused": f"record a hypothesis first (unknown id {hypothesis_id})"}
        specs = []
        for cid in candidate_ids:
            c = self.candidates.get(cid)
            if not c:
                return {"refused": f"unknown candidate {cid}; call evaluate_trials first"}
            specs.append(c["spec"])
        left = self.limits.trial_plots - self.plots_used
        if not specs:
            return {"refused": "no candidates given"}
        if len(specs) > min(left, self.limits.plots_per_round):
            return {"refused": f"{len(specs)} plots requested; {left} left in the budget, at most {self.limits.plots_per_round} per round"}
        rid = self._id("R")
        self._log("trial_start", {"round": rid, "plots": specs, "hypothesis_id": hypothesis_id, "rationale": rationale})
        res = self.farm.run_trials(specs)
        self.plots_used += len(specs)
        self.trial_rounds += 1
        out = []
        rng = np.random.default_rng(self.trial_rounds)
        for t, o in zip(specs, res["plots"]):
            # the prediction is made with the belief held *before* this result, using this year's actual weather
            b = self.beliefs[t["crop"]]
            S = 40
            smp = b.sample(S, rng)
            th = np.stack([smp[k] for k in TRAIT_IDS], axis=1)
            sim = predict_trials(t["crop"], th, [t], [res["weather"]])
            y = sim.fresh_yield()
            ccp = sim.traces()["cc"]
            days = np.array(o["days"])
            lo, hi = np.percentile(y, 5), np.percentile(y, 95)
            inside = lo * 0.95 <= o["yield_t_ha"] <= hi * 1.05
            cc_lo = np.percentile(ccp[:, days], 5, axis=0) - 0.03
            cc_hi = np.percentile(ccp[:, days], 95, axis=0) + 0.03
            cc_cov = float(np.mean((np.array(o["cc_obs"]) >= cc_lo) & (np.array(o["cc_obs"]) <= cc_hi)))
            self.trial_data[t["crop"]].append((t, o, res["weather"]))
            r = {"crop": t["crop"], "plot": t["plot"], "sow": t["sow"], "irr": t["irr"], "desal": t["desal"],
                 "measured_yield_t_ha": o["yield_t_ha"], "predicted_yield_90pct": [round(lo, 2), round(hi, 2)],
                 "predicted_yield_median": round(float(np.median(y)), 2),
                 "canopy_inside_band_pct": round(100 * cc_cov), "prediction_held": bool(inside and cc_cov >= 0.7),
                 "harvest_day": o["harvest_day"], "water_m3_ha": o["water_m3_ha"]}
            out.append(r)
            self.bus.publish("trials", {"round": rid, **r, "days": o["days"], "cc_obs": o["cc_obs"],
                                        "cc_pred_lo": np.clip(cc_lo, 0, 1).round(3).tolist(),
                                        "cc_pred_hi": np.clip(cc_hi, 0, 1).round(3).tolist(),
                                        "cc_pred_med": np.median(ccp[:, days], axis=0).round(3).tolist()})
        digest = hashlib.sha256(json.dumps(res["plots"], sort_keys=True).encode()).hexdigest()
        result = {"round": rid, "plots": out, "plots_left": self.limits.trial_plots - self.plots_used,
                  "trial_year": {"days_above_38C": int(np.sum(res["weather"]["tmax"] > 38)),
                                 "season_et0_mm": round(float(res["weather"]["et0"].sum())),
                                 "rain_mm": round(float(res["weather"]["rain"].sum()))},
                  "data_sha256": digest}
        self._log("trial_result", result)
        self._status()
        result["next"] = "call fit_crop_models to learn from these plots, then conclude the hypothesis"
        return result

    def fit_crop_models(self, rationale: str, crops: list[str] | None = None) -> dict:
        crops = [c for c in (crops or CROP_IDS) if self.trial_data.get(c)]
        if not crops:
            return {"error": "no trial data yet"}
        table = []
        for c in crops:
            b = self.beliefs[c]
            before = b.to_json()
            data = self.trial_data[c]
            b.mean, b.cov = self.priors[c][0].copy(), self.priors[c][1].copy()
            fit = calibrate(b, self.priors[c], [d[0] for d in data], [d[1] for d in data], [d[2] for d in data])
            after = b.to_json()
            table.append({"crop": c, "plots": len(data), "cc_rmse": fit["cc_rmse"], "yield_err_pct": fit["yield_err_pct"],
                          "traits": {k: {"mean": after["traits"][k]["mean"], "sd": after["traits"][k]["sd"],
                                         "sd_before": before["traits"][k]["sd"]} for k in TRAIT_IDS}})
        self._log("model_update", {"rationale": rationale, "crops": table})
        self._publish_beliefs()
        return {"updated": table, "note": "traits: wp and cgc are multipliers (1 = published value), heat and salt are "
                                          "shifts in C and dS/m (0 = published value). sd shrinks only for traits a trial exposed."}

    # ============================================================ planning
    def plan_season(self, rationale: str, seed: int = 99) -> dict:
        self._check_stop()
        if self.phase in ("season", "harvested"):
            return {"refused": "the season has started; use rebalance_water to change irrigation"}
        L = self.limits
        chosen = self._choice_specs()
        extra = {ch["crop"]: ch["sows"] for ch in chosen if ch and ch.get("crop")}
        ev = evaluate(self.beliefs, S=24, seed=seed, extra_sows=extra)
        allowed = allowed_options(ev, chosen) if any(chosen) else None
        plan = optimise(ev, L.water_quota_m3, L.energy_kwh, allowed=allowed)
        # what certainty would be worth: same weather years, traits fixed at their means
        sure = {c: CropBelief(c) for c in CROP_IDS}
        for c in CROP_IDS:
            sure[c].mean = self.beliefs[c].mean.copy()
            sure[c].cov = np.eye(4) * 1e-10
        ev2 = evaluate(sure, S=24, seed=seed, extra_sows=extra)
        plan2 = optimise(ev2, L.water_quota_m3, L.energy_kwh, allowed=allowed_options(ev2, chosen) if allowed else None)
        free = optimise(ev, L.water_quota_m3, L.energy_kwh) if allowed else None
        if free and free["people_p10"] < plan["people_p10"]:
            free = plan              # its search found nothing better than the farmer's picks
        pid = self._id("P")
        untested = sorted({f["crop"] for f in plan["fields"] if f.get("crop") and not self.trial_data[f["crop"]]})
        rec = {"plan_id": pid, **{k: v for k, v in plan.items() if k != "fed_samples"},
               "people_p10_if_traits_known": plan2["people_p10"],
               "cost_of_uncertainty_people": round(plan2["people_p10"] - plan["people_p10"], 1),
               "untested_crops": untested, "rationale": rationale}
        if allowed:
            for f in rec["fields"]:
                f["farmer_choice"] = f["field_index"] in allowed
            rec["farmer_choices"] = self.choices_summary()
            rec["scientist_choice"] = {"people_p10": free["people_p10"],
                                       "fields": [{"field": f["field"], "crop": f["crop"]} for f in free["fields"]]}
            rec["note_on_choices"] = (f"The farmer chose the crops on {len(allowed)} field(s); this plan keeps them and sets "
                                      f"sowing day, irrigation, water blend and nitrogen. " +
                                      (f"With a free choice the scientist would feed {free['people_p10']} people in a bad year, "
                                       f"against {plan['people_p10']} here." if free["people_p10"] > plan["people_p10"] else
                                       "The scientist found no crop mix that does better than these picks."))
        if untested:
            rec["note"] = (f"the plan relies on crops never trialled on this farm: {', '.join(untested)}; their predictions "
                           "rest on published values only. Consider trialling them before committing.")
        self.plans[pid] = rec
        self.season_plan = rec
        if self.phase == "trials":
            self.phase = "planning"
        self.bus.publish("plan", {**rec, "day": self.day, "fed_samples": plan["fed_samples"]})
        self._log("plan", rec)
        self._status()
        return rec

    # ============================================================ season
    def start_season(self, plan_id: str, rationale: str, controller: str = "rule") -> dict:
        p = self.plans.get(plan_id)
        if not p:
            return {"refused": f"unknown plan {plan_id}"}
        if self.phase in ("season", "harvested"):
            return {"refused": "already started"}
        if controller not in ("rule", "rl_policy"):
            return {"refused": "controller must be rule or rl_policy"}
        if controller == "rl_policy" and not (self.policy and self.policy["plan_id"] == plan_id):
            return {"refused": f"no irrigation policy trained for {plan_id}; call train_irrigation_policy first"}
        self.controller = controller
        self.run_plan_id = plan_id
        fields = []
        for f in p["fields"]:
            if f.get("crop"):
                fields.append({"crop": f["crop"], **f["mgmt"]})
            else:
                fields.append({"crop": None, "sow": 0, "density": 1, "irr": 0, "desal": 0, "nfert": 0, "mulch": 0})
        self.run_plan = fields
        self.farm.start_season(fields)
        self.phase = "season"
        self.day = 0
        self.gross_hist = np.zeros((NF, D))
        self.irr_hist = np.tile(np.array([f["irr"] for f in fields], float)[:, None], (1, D))
        self.desal_hist = np.tile(np.array([f["desal"] for f in fields], float)[:, None], (1, D))
        self.deliver_est = np.ones((NF, D))
        self.pest_est = np.zeros((NF, D))
        self.ecgw_est = np.full((NF, D), EC_GROUNDWATER)
        self.wx_obs = {k: np.zeros((1, D)) for k in ("tmax", "tmin", "rh", "u2", "rs", "rain", "et0", "doy")}
        self.wx_obs["doy"][0] = WX.season_doys()
        self.theta_obs = np.full((NF, D, 3), np.nan)
        self.ec_last = np.array([np.mean(f["ece"][:2]) for f in FIELDS])
        self.cc_obs = {i: [] for i in range(NF)}
        self.cc_last = np.zeros(NF)
        self.harvested = np.zeros(NF, bool)
        self.policy_trace = []
        self.S_mon = 30
        self._build_ensemble()
        self._reset_monitor()
        self._log("season_start", {"plan_id": plan_id, "fields": fields, "controller": controller, "rationale": rationale})
        self.bus.publish("fields", self._fields_static())
        self._status()
        self.project()
        return {"started": True, "date": WX.day_label(0), "controller": controller, "fields": [
            {"field": FIELDS[i]["id"], "crop": f["crop"], "sow_date": WX.day_label(int(f["sow"])) if f["crop"] else None}
            for i, f in enumerate(fields)]}

    def _fields_static(self):
        return [{"id": FIELDS[i]["id"], "name": FIELDS[i]["name"], "crop": f["crop"],
                 "label": CROPS[f["crop"]]["label"] if f["crop"] else "Fallow", "sow": int(f["sow"]),
                 "irr": f["irr"], "desal": f["desal"], "nfert": f["nfert"],
                 "layers": FIELDS[i]["layers"], "ece": FIELDS[i]["ece"]} for i, f in enumerate(self.run_plan)]

    def _trait_samples(self, S: int, rng):
        crops, tr = [], {k: [] for k in TRAIT_IDS}
        for f in self.run_plan:
            c = f["crop"]
            smp = self.beliefs[c].sample(S, rng) if c else {k: np.zeros(S) for k in TRAIT_IDS}
            crops += [c] * S
            for k in TRAIT_IDS:
                tr[k].append(smp[k])
        return crops, {k: np.concatenate(v) for k, v in tr.items()}

    def _build_ensemble(self):
        """(Re)build the monitoring ensemble and replay the season so far."""
        S = self.S_mon
        crops, tr = self._trait_samples(S, np.random.default_rng(17))
        mg = {k: np.repeat(np.array([float(f[k]) for f in self.run_plan]), S) for k in MG_KEYS}
        mg["irr"] = np.repeat(self.irr_hist, S, axis=0)
        mg["desal"] = np.repeat(self.desal_hist, S, axis=0)
        self.ens = Sim(crop_arrays(crops, tr), mg, soil_arrays([f for f in FIELDS for _ in range(S)]), self.wx_obs,
                       np.zeros(NF * S, int), np.repeat(self.ecgw_est, S, axis=0), eff=DRIP_EFF_NOMINAL,
                       deliver=np.repeat(self.deliver_est, S, axis=0), pest=np.repeat(self.pest_est, S, axis=0))
        for d in range(self.day):
            self.ens.step(np.repeat(self.gross_hist[:, d], S))

    def _reset_monitor(self):
        self.cus = {f"{s}_{k}": (np.zeros(NF) if k != "zero" else np.full(NF, self.day))
                    for s in ("sw", "cc", "ec") for k in ("p", "n", "zero")}
        self.mon_from = np.array([max(self.day + 5, int(f["sow"]) + 5) for f in self.run_plan])

    def _controller(self, d: int) -> np.ndarray:
        """Daily drip irrigation from observable data: last drone canopy cover and yesterday's ET0."""
        et0 = self.wx_obs["et0"][0, d - 1] if d > 0 else 5.0
        g = np.zeros(NF)
        for i, f in enumerate(self.run_plan):
            c = f["crop"]
            if not c or d < f["sow"] or self.harvested[i]:
                continue
            cc = self.cc_last[i]
            etc = (CROPS[c]["kcb"] * cc + 0.3 * (1 - cc) * (1 - 0.5 * f["mulch"])) * et0
            g[i] = self.irr_hist[i, d] * etc * (1 + LEACH_FRACTION) / DRIP_EFF_NOMINAL
            if d == f["sow"]:
                g[i] += PRE_IRRIGATION_MM
        if self.controller == "rl_policy" and self.policy:
            g = self._policy_adjust(d, g)
        return g

    def _policy_adjust(self, d: int, g: np.ndarray) -> np.ndarray:
        """The trained policy scales the rule's drip schedule and sets today's
        water blend, from the same sensor readings the agent sees."""
        pol: RL.Policy = self.policy["policy"]
        rows = pol.rows
        S = self.S_mon
        frac = self.ens.frac().reshape(NF, S).mean(1)[rows]
        ens_th = (self.ens.W / self.ens.th)[:, :2].reshape(NF, S, 2).mean(1)[rows]
        th = self.theta_obs[rows, d - 1, :2] if d > 0 else ens_th
        th = np.where(np.isnan(th), ens_th, th)
        et0 = self.wx_obs["et0"][0, d - 1] if d > 0 else 5.0
        mult, desal = pol.act(d, frac, self.cc_last[rows], th, self.ec_last[rows], et0,
                              self.water_used / self.limits.water_quota_m3, self.energy_used / self.limits.energy_kwh)
        out = g.copy()
        for j, i in enumerate(rows):
            if g[i] <= 0 or self.harvested[i]:
                continue
            out[i] = g[i] * float(mult[j])
            dz = round(float(desal[j]), 3)
            if dz != self.desal_hist[i, d]:
                self.desal_hist[i, d:] = dz
                self.farm.set_management(i, desal=dz)
                self.ens.m["desal"][i * S:(i + 1) * S, d:] = dz
        self.policy_trace.append({"day": d, "mult": [round(float(m), 3) for m in mult],
                                  "desal": [round(float(x), 3) for x in desal]})
        return out

    # ------------------------------------------------------------ RL
    def train_irrigation_policy(self, plan_id: str, rationale: str, iterations: int = 50) -> dict:
        """Train a daily irrigation and water-blend policy for a plan, by
        evolution strategies inside the agent's own calibrated model: crop
        traits are drawn from the current beliefs, weather from the climate.
        Returns the trained policy against the plan's rule on held-out
        imagined seasons."""
        self._check_stop()
        p = self.plans.get(plan_id)
        if not p:
            return {"refused": f"unknown plan {plan_id}"}
        if self.phase in ("season", "harvested"):
            return {"refused": "train before the season starts; switch controllers with set_irrigation_controller"}
        iterations = int(max(10, min(iterations, 120)))
        fp, rows = [], []
        for i, f in enumerate(p["fields"]):
            if f.get("crop"):
                fp.append({"crop": f["crop"], **f["mgmt"]})
                rows.append(i)
        L = self.limits
        seed = 300 + self._ids["P"]
        mk = lambda E, s: RL.Envs(fp, rows, self.beliefs, E, seed=s, quota_m3=L.water_quota_m3, energy_kwh=L.energy_kwh)
        envs, val, test = mk(12, seed), mk(16, seed + 1), mk(40, seed + 2)
        self._log("rl_train_start", {"plan_id": plan_id, "iterations": iterations, "rationale": rationale,
                                     "method": "evolution strategies (32 antithetic pairs, Adam) inside the belief model"})
        self.bus.publish("rl_train", {"plan_id": plan_id, "iter": -1, "reset": True})

        def cb(rec):
            self._check_stop()
            self.bus.publish("rl_train", {"plan_id": plan_id, **rec})

        t0 = time.time()
        tr = RL.train(envs, iters=iterations, seed=seed, callback=cb, val_envs=val)
        cmp = RL.compare(test, tr["theta"])
        better = tr["best_iter"] > 0 and cmp["policy"]["reward"] > cmp["rule"]["reward"]
        meta = RL.crop_meta(fp, self.beliefs, EC_GROUNDWATER)
        self.policy = {"plan_id": plan_id, "policy": RL.Policy(tr["theta"], meta, rows), "best_iter": tr["best_iter"],
                       "comparison": cmp, "recommended": better}
        rec = {"plan_id": plan_id, "trained_seconds": round(time.time() - t0, 1), "iterations": iterations,
               "best_checkpoint_iter": tr["best_iter"], "policy_parameters": RL.N_PARAMS,
               "imagined_farm_seasons": iterations * (2 * 32 + 1) * envs.E,
               "held_out_comparison": {k: v for k, v in cmp.items() if not k.endswith("_by_week")},
               "policy_irrigation_multiplier_by_week": cmp["irrigation_multiplier_by_week"],
               "policy_desal_fraction_by_week": cmp["desal_fraction_by_week"],
               "recommend": "rl_policy" if better else "rule",
               "note": ("held-out seasons come from the agent's own model of the farm; the real farm may differ, "
                        "and the monitoring keeps checking" if better else
                        "the policy did not beat the plan's rule on held-out seasons; keep the rule")}
        self.bus.publish("rl", {**rec, "history": tr["history"], "validation": tr["validation"]})
        self._log("rl_policy", rec)
        return rec

    def set_irrigation_controller(self, controller: str, rationale: str) -> dict:
        if controller not in ("rule", "rl_policy"):
            return {"refused": "controller must be rule or rl_policy"}
        if controller == "rl_policy":
            if not self.policy:
                return {"refused": "no policy trained"}
            if self.phase == "season" and self.policy["plan_id"] != self.run_plan_id:
                return {"refused": "the trained policy belongs to a different plan"}
        self.controller = controller
        self._log("controller", {"controller": controller, "day": self.day, "rationale": rationale})
        self._status()
        return {"controller": controller, "from_day": self.day}

    def advance(self, days: int, rationale: str = "") -> dict:
        """Run the season forward day by day; stops early on an anomaly or at season end."""
        if self.phase != "season":
            return {"refused": "start the season first" if self.phase in ("trials", "planning") else "the season is over"}
        if self.anomaly:
            return {"refused": "an anomaly is open: investigate, then update_model with what you found, or "
                               "dismiss_anomaly if it was noise", "anomaly": self.anomaly}
        days = int(max(1, min(days, self.limits.max_advance_days)))
        self._log("advance", {"days": days, "from_day": self.day, "rationale": rationale})
        stop_reason = "days elapsed"
        for _ in range(days):
            self._check_stop()
            if self.day >= D:
                break
            alarm = self._one_day()
            if self.speed > 0:
                time.sleep(1.0 / self.speed)
            if alarm:
                stop_reason = "anomaly"
                break
            if self.day % 14 == 0 and self.day < D:
                self.project()
        if self.day >= D and self.phase == "season":
            self._season_end()
            stop_reason = "season over"
        self._status()
        out = {"stopped_because": stop_reason, "day": self.day, "date": WX.day_label(min(self.day, D - 1)),
               "water_used_m3": round(self.water_used), "energy_used_kwh": round(self.energy_used),
               "fields": self._field_summary()}
        if self.anomaly:
            out["anomaly"] = self.anomaly
        if self.result:
            out["result"] = self.result
        return out

    def _one_day(self):
        d = self.day
        g = self._controller(d)
        obs = self.farm.step(g)
        for k, v in obs["weather"].items():
            self.wx_obs[k][0, d] = v
        self.gross_hist[:, d] = g
        vol = g * 10 * FIELD_HA
        self.water_used += float(vol.sum())
        self.energy_used += float((vol * (KWH_PUMP + KWH_DESAL * self.desal_hist[:, d])).sum())
        self.theta_obs[:, d] = obs["theta"]
        ec_obs = obs["ece"]
        self.ec_last = ec_obs[:, :2].mean(1)
        S = self.S_mon
        self.ens.step(np.repeat(g, S))
        self.day = d + 1
        drone_day = d % 4 == 3
        rec = {"day": d, "date": WX.day_label(d), "tmax": round(obs["weather"]["tmax"], 1),
               "et0": round(obs["weather"]["et0"], 2), "rain": round(obs["weather"]["rain"], 1), "fields": []}
        alarm = None
        ens_theta = (self.ens.W / self.ens.th)[:, :2].mean(1).reshape(NF, S)
        ens_cc = self.ens.cc.reshape(NF, S)
        ens_ec = self.ens.ece_layers()[:, :2].mean(1).reshape(NF, S)
        for i, f in enumerate(self.run_plan):
            fr = {"irr_mm": round(float(g[i]), 2), "desal": round(float(self.desal_hist[i, d]), 2)}
            th_o = float(np.mean(obs["theta"][i, :2]))
            mu, sd_e = float(ens_theta[i].mean()), float(ens_theta[i].std())
            fr.update({"sw_obs": round(th_o, 4), "sw_pred": round(mu, 4),
                       "sw_lo": round(float(np.percentile(ens_theta[i], 5)) - 0.013, 4),
                       "sw_hi": round(float(np.percentile(ens_theta[i], 95)) + 0.013, 4)})
            ec_o = float(np.mean(ec_obs[i, :2]))
            ec_mu, ec_sd = float(ens_ec[i].mean()), float(ens_ec[i].std())
            fr.update({"ec_obs": round(ec_o, 3), "ec_pred": round(ec_mu, 3),
                       "ec_lo": round(float(np.percentile(ens_ec[i], 5)) * 0.9, 3),
                       "ec_hi": round(float(np.percentile(ens_ec[i], 95)) * 1.1, 3)})
            if f["crop"] and obs["harvested"][i] and not self.harvested[i]:
                self.harvested[i] = True
                self._record_harvest(i)
            active = bool(f["crop"]) and not self.harvested[i] and d >= f["sow"]
            cc_mu, cc_sd = float(ens_cc[i].mean()), float(ens_cc[i].std())
            fr.update({"cc_pred": round(cc_mu, 4), "cc_lo": round(max(float(np.percentile(ens_cc[i], 5)) - 0.03, 0), 4),
                       "cc_hi": round(min(float(np.percentile(ens_cc[i], 95)) + 0.03, 1), 4)})
            if drone_day and active:
                dr = self.farm.drone(i)
                self.cc_last[i] = dr["cc"]
                self.cc_obs[i].append((d, dr["cc"]))
                fr["cc_obs"] = dr["cc"]
            if active and d >= self.mon_from[i]:
                a = self._cusum(i, "sw", th_o - mu, math.sqrt(sd_e ** 2 + 0.008 ** 2 + 0.012 ** 2), 0.015, 1.5, 10, d)
                a = a or self._cusum(i, "ec", ec_o - ec_mu, math.sqrt(ec_sd ** 2 + (0.08 * ec_mu) ** 2 + 0.3 ** 2),
                                     max(0.8, 0.15 * ec_mu), 1.0, 8, d)
                if "cc_obs" in fr and fr["cc_obs"] > 0.04:
                    a = a or self._cusum(i, "cc", fr["cc_obs"] - cc_mu, math.sqrt(cc_sd ** 2 + 0.025 ** 2 + 0.03 ** 2), 0.06, 1.0, 6, d)
                if a and not alarm:
                    alarm = a
            rec["fields"].append(fr)
        rec["world"] = self.farm.world_state()
        rec["controller"] = self.controller
        rec["water_used_m3"] = round(self.water_used)
        rec["energy_used_kwh"] = round(self.energy_used)
        self.bus.publish("day", rec)
        if alarm:
            self.anomaly = alarm
            self.anomalies.append(alarm)
            self._log("anomaly", alarm)
        return alarm

    def _cusum(self, i, sig, resid, sd, effect, k, h, d):
        z = resid / sd if abs(resid) >= effect else 0.0
        P, N, Z = self.cus[sig + "_p"], self.cus[sig + "_n"], self.cus[sig + "_zero"]
        P[i] = max(0.0, P[i] + z - k)
        N[i] = max(0.0, N[i] - z - k)
        if P[i] == 0 and N[i] == 0:
            Z[i] = d
        if P[i] > h or N[i] > h:
            label = {"sw": "soil moisture", "cc": "canopy cover", "ec": "soil salinity"}[sig]
            hi = P[i] > h
            direction = ("wetter" if hi else "drier") if sig == "sw" else ("higher" if hi else "lower")
            return {"field": FIELDS[i]["id"], "field_index": i, "signal": sig, "signal_label": label,
                    "direction": f"{direction} than predicted", "residual": round(resid, 3),
                    "onset_day": int(Z[i]), "detected_day": d, "crop": self.run_plan[i]["crop"]}
        return None

    def _record_harvest(self, i):
        y_true = float(self.farm.sim.fresh_yield()[i])
        y = round(y_true * float(self.farm.rng.lognormal(0, 0.03)), 2)
        c = self.run_plan[i]["crop"]
        nut = nutrients_per_ha(c, y * FIELD_HA)
        self.harvest[FIELDS[i]["id"]] = {"crop": c, "day": self.day, "yield_t_ha": y,
                                         "people": {n: round(nut[n] / (NEEDS[n] * 365), 1) for n in NUTRIENTS}}
        self._log("harvest", {"field": FIELDS[i]["id"], **self.harvest[FIELDS[i]["id"]]})

    def _season_end(self):
        tot = {n: 0.0 for n in NUTRIENTS}
        for h in self.harvest.values():
            nut = nutrients_per_ha(h["crop"], h["yield_t_ha"] * FIELD_HA)
            for n in NUTRIENTS:
                tot[n] += nut[n]
        pf = people_fed(tot)
        self.result = {"people_fed": round(pf["people"], 1), "limiting": pf["limiting"],
                       "by_nutrient": {n: round(pf[n], 1) for n in NUTRIENTS},
                       "water_used_m3": round(self.water_used), "energy_used_kwh": round(self.energy_used),
                       "within_quota": self.water_used <= self.limits.water_quota_m3 * 1.001,
                       "within_energy": self.energy_used <= self.limits.energy_kwh * 1.001}
        self.phase = "harvested"
        self._log("season_result", self.result)
        self._status()

    def _field_summary(self):
        out = []
        frac = np.minimum(self.ens.frac().reshape(NF, self.S_mon).mean(1), 1)
        for i, f in enumerate(self.run_plan):
            if not f["crop"]:
                out.append({"field": FIELDS[i]["id"], "crop": None})
                continue
            th = self.theta_obs[i, max(self.day - 1, 0)]
            dd = min(self.day, D - 1)
            out.append({"field": FIELDS[i]["id"], "crop": f["crop"],
                        "stage_pct": round(100 * float(frac[i])) if self.day > f["sow"] else 0,
                        "harvested": bool(self.harvested[i]),
                        "canopy_cover_last_drone": round(float(self.cc_last[i]), 3),
                        "soil_moisture_0_50cm": None if np.isnan(th).any() else round(float(th[:2].mean()), 3),
                        "soil_salinity_ece_0_50cm": round(float(self.ec_last[i]), 2),
                        "irrigation_level": round(float(self.irr_hist[i, dd]), 2),
                        "desal_fraction": round(float(self.desal_hist[i, dd]), 2)})
        return out

    def set_crop_choices(self, choices: list) -> list:
        """choices: one entry per field (F1..F6): None or {"mode": "scientist"} (the scientist decides),
        {"mode": "fallow"}, or {"mode": "crop", "crop": c, "season": season id}."""
        out = normalize_choices(choices)
        self.crop_choices = out
        if any(out):
            self._log("farmer_choices", {"fields": self.choices_summary()})
        return out

    def _choice_specs(self) -> list[dict | None]:
        specs = []
        for ch in self.crop_choices:
            if not ch:
                specs.append(None)
            elif ch["mode"] == "fallow":
                specs.append({"fallow": True})
            else:
                specs.append({"crop": ch["crop"], "sows": SEASONS.sow_days(ch["crop"], ch["season"])})
        return specs

    def choices_summary(self) -> list[dict]:
        out = []
        for i, ch in enumerate(self.crop_choices):
            if not ch:
                out.append({"field": FIELDS[i]["id"], "choice": "scientist decides"})
            elif ch["mode"] == "fallow":
                out.append({"field": FIELDS[i]["id"], "choice": "fallow"})
            else:
                out.append({"field": FIELDS[i]["id"], "choice": CROPS[ch["crop"]]["label"],
                            "crop": ch["crop"], "season": SEASONS.season(ch["season"])["label"]})
        return out

    def observe(self) -> dict:
        out = {"phase": self.phase, "day": self.day, "date": WX.day_label(min(self.day, D - 1)),
               "trial_plots_left": self.limits.trial_plots - self.plots_used,
               "field_tests_left": self.limits.field_tests - self.tests_used,
               "water_used_m3": round(self.water_used), "water_quota_m3": self.limits.water_quota_m3,
               "energy_used_kwh": round(self.energy_used), "energy_budget_kwh": self.limits.energy_kwh,
               "active_anomaly": self.anomaly,
               "goal": "maximise people fed in a bad year (P10): the scarcest of calories, protein and vitamin A"}
        if self.phase in ("season", "harvested"):
            out["fields"] = self._field_summary()
            if self.day < D:
                out["forecast_7d"] = self.farm.forecast(7)
            out["last_projection"] = self.bus.snapshot["projections"][-1] if self.bus.snapshot["projections"] else None
            if self.result:
                out["result"] = self.result
        else:
            out["fields"] = [{"field": f["id"], "name": f["name"], "soil": f["layers"], "ece_dS_m": f["ece"],
                              "soil_n_kg_ha": f["soil_n"]} for f in FIELDS]
            out["crops"] = [{"crop": c, "label": CROPS[c]["label"], "trial_plots": len(self.trial_data[c])} for c in CROP_IDS]
            if any(self.crop_choices):
                out["farmer_choices"] = self.choices_summary()
                out["note"] = ("The farmer chose crops for some fields. plan_season keeps those crops and their sowing season; "
                               "you set management there and choose crops for the other fields. Trial the farmer's crops too.")
        return out

    # ---------------------------------------------------------- in-season tools
    def look_at_field(self, field: str, reason: str = "") -> dict:
        i = self._fi(field)
        if i is None:
            return {"error": f"unknown field {field}"}
        if self.phase not in ("season", "harvested"):
            return {"error": "nothing is growing yet"}
        img = self.farm.image(i)
        res = self.perception.analyze(img, "image/png", self.farm, i) if self.perception else {"source": "none"}
        fname = None
        if self.run_dir:
            fname = f"images/{FIELDS[i]['id']}_day{self.day:03d}.png"
            (self.run_dir / fname).write_bytes(img)
        dr = self.farm.drone(i)
        ccp = self.ens.cc.reshape(NF, self.S_mon)[i]
        out = {"field": FIELDS[i]["id"], "crop": self.run_plan[i]["crop"], "day": self.day,
               "canopy_cover_measured": dr["cc"], "canopy_cover_predicted": round(float(ccp.mean()), 3),
               "canopy_cover_predicted_90pct": [round(float(np.percentile(ccp, 5)), 3), round(float(np.percentile(ccp, 95)), 3)],
               **{k: v for k, v in res.items() if k != "objects"}}
        self.bus.publish("scene", {**out, "objects": res.get("objects", [])[:60], "image_size": [640, 400],
                                   "image": "data:image/png;base64," + base64.b64encode(img).decode(), "reason": reason})
        self._log("look", {"reason": reason, "frame": fname, **out})
        return out

    def field_test(self, field: str, test: str, rationale: str) -> dict:
        i = self._fi(field)
        if i is None or test not in TESTS:
            return {"error": f"field F1-F6 and test one of {TESTS}"}
        if self.phase != "season":
            return {"error": "field tests run during the season"}
        if self.tests_used >= self.limits.field_tests:
            return {"refused": "field-test budget used up"}
        self.tests_used += 1
        r = self.farm.field_test(i, test)
        r.update({"field": FIELDS[i]["id"], "day": self.day})
        if test == "emitter_flow":
            r["expected_if_healthy"] = round(float(self.deliver_est[i, max(self.day - 1, 0)]), 2)
        if test == "water_test":
            r["assumed_by_model"] = round(float(self.ecgw_est[i, max(self.day - 1, 0)]), 2)
        if test == "soil_sample":
            ece = self.ens.ece_layers().reshape(NF, self.S_mon, 3)[i]
            r["model_predicted_ece_by_layer"] = ece.mean(0).round(2).tolist()
        self._log("field_test", {"rationale": rationale, **r})
        self._status()
        return r

    def adjust_field(self, field: str, rationale: str, irr: float | None = None, desal: float | None = None,
                     repair_drip: bool = False, pest_control: bool = False) -> dict:
        i = self._fi(field)
        if i is None or self.phase != "season":
            return {"error": "unknown field or season not running"}
        d = self.day
        out = {"field": FIELDS[i]["id"], "day": d}
        if irr is not None:
            if not 0.3 <= irr <= 1.4:
                return {"refused": "irr must be 0.3-1.4"}
            self.irr_hist[i, d:] = irr
            out["irr"] = irr
        if desal is not None:
            if not 0 <= desal <= 1:
                return {"refused": "desal must be 0-1"}
            self.desal_hist[i, d:] = desal
            self.farm.set_management(i, desal=desal)
            out["desal"] = desal
        if repair_drip:
            out["repair"] = self.farm.repair_drip(i)
            self.deliver_est[i, d:] = 1.0
        if pest_control:
            out["pest_control"] = self.farm.pest_control(i)
            self.pest_est[i, d:] = np.minimum(self.pest_est[i, d:], 0.001)
        self._build_ensemble()
        self._log("adjust", {"rationale": rationale, **out})
        return out

    def update_model(self, rationale: str, finding: str, value: float, since_day: int, field: str | None = None) -> dict:
        """Teach the model a diagnosed fact, then rebuild the monitoring ensemble from day 0."""
        since = int(np.clip(since_day, 0, self.day))
        d = self.day
        if finding == "groundwater_ec":
            self.ecgw_est[:, since:] = float(value)
            fid = "all"
        else:
            i = self._fi(field)
            if i is None:
                return {"error": "unknown field"}
            fid = FIELDS[i]["id"]
            if finding == "drip_delivery":
                repaired = any(r["field"] == fid and r["day"] >= since for r in self.farm.repairs)
                end = max((r["day"] for r in self.farm.repairs if r["field"] == fid and r["day"] >= since), default=D)
                self.deliver_est[i, since:min(end, D)] = float(value)
            elif finding == "pest":
                # past damage at the diagnosed rate; the future keeps whatever treatment already set
                self.pest_est[i, since:d] = float(value)
                if not np.all(self.pest_est[i, d:] <= 0.001):
                    self.pest_est[i, d:] = float(value)
            else:
                return {"error": "finding must be drip_delivery, pest or groundwater_ec"}
        resolved = self.anomaly
        self.anomaly = None
        self._build_ensemble()
        self._reset_monitor()
        self._log("model_update", {"rationale": rationale, "finding": finding, "field": fid,
                                   "value": value, "since_day": since, "resolved_anomaly": resolved})
        self._status()
        out = {"ok": True, "resolved_anomaly": resolved, "note": "monitoring ensemble rebuilt with the finding"}
        if self.policy and finding == "groundwater_ec":
            self.policy["policy"].meta["ecgw"][:] = float(value)
            if self.controller == "rl_policy" and abs(float(value) - EC_GROUNDWATER) > 1.0:
                out["rl_policy_warning"] = (f"the irrigation policy was trained with groundwater at {EC_GROUNDWATER} dS/m; "
                                            f"{value} dS/m is outside what it has seen. Consider set_irrigation_controller rule.")
        return out

    def dismiss_anomaly(self, rationale: str) -> dict:
        resolved = self.anomaly
        self.anomaly = None
        self._reset_monitor()
        self._log("anomaly_dismissed", {"rationale": rationale, "anomaly": resolved})
        self._status()
        return {"ok": True}

    # ---------------------------------------------------------- projection and rebalancing
    def _future_wx(self, S: int, seed: int):
        """Observed weather up to today, scenario years after."""
        fut = WX.generate(S, seed)
        wx = {}
        for k in self.wx_obs:
            a = fut[k].copy()
            a[:, :self.day] = self.wx_obs[k][0, :self.day]
            wx[k] = a
        return wx

    def _season_batch(self, opts: list[tuple[np.ndarray, np.ndarray]], S: int, seed: int):
        """Each field under each option (irr per field, desal per field) for the rest of the
        season, replaying the recorded irrigation so far. Returns arrays shaped (F, O, S)."""
        O = len(opts)
        crops, tr = self._trait_samples(S, np.random.default_rng(seed))
        B = NF * O * S
        crop_list = []
        trb = {k: np.zeros(B) for k in TRAIT_IDS}
        mg = {k: np.zeros(B) for k in MG_KEYS}
        mg["irr"], mg["desal"] = np.zeros((B, D)), np.zeros((B, D))
        soils, widx = [], np.zeros(B, int)
        deliver, pest, ecgw = np.zeros((B, D)), np.zeros((B, D)), np.zeros((B, D))
        j = 0
        for i, f in enumerate(self.run_plan):
            for o in range(O):
                sl = slice(j, j + S)
                crop_list += [f["crop"]] * S
                for k in TRAIT_IDS:
                    trb[k][sl] = tr[k][i * S:(i + 1) * S]
                for k in MG_KEYS:
                    if k not in ("irr", "desal"):
                        mg[k][sl] = f[k]
                ir, de = self.irr_hist[i].copy(), self.desal_hist[i].copy()
                ir[self.day:] = opts[o][0][i]
                de[self.day:] = opts[o][1][i]
                mg["irr"][sl], mg["desal"][sl] = ir, de
                soils += [FIELDS[i]] * S
                widx[sl] = np.arange(S)
                deliver[sl], pest[sl], ecgw[sl] = self.deliver_est[i], self.pest_est[i], self.ecgw_est[i]
                j += S
        sim = Sim(crop_arrays(crop_list, trb), mg, soil_arrays(soils), self._future_wx(S, seed), widx, ecgw,
                  eff=DRIP_EFF_NOMINAL, deliver=deliver, pest=pest)
        rep = np.repeat(self.gross_hist, O * S, axis=0)
        for d in range(self.day):
            sim.step(rep[:, d])
        past_mm = sim.gross_mm.copy()
        past_kwh = sim.kwh_ha.copy()
        sim.run()
        y = sim.fresh_yield().reshape(NF, O, S)
        fw = ((sim.gross_mm - past_mm) * 10 * FIELD_HA).reshape(NF, O, S)
        fe = ((sim.kwh_ha - past_kwh) * FIELD_HA).reshape(NF, O, S)
        return y, fw, fe

    def _people_arrays(self, y):
        """y (F, O, S) fresh t/ha -> person-years per nutrient (F, O, S, 3); harvested fields use actual yields."""
        need = np.array([NEEDS[n] * 365.0 for n in NUTRIENTS])
        out = np.zeros(y.shape + (3,))
        for i, f in enumerate(self.run_plan):
            c = f["crop"]
            if not c:
                continue
            yy = y[i]
            if FIELDS[i]["id"] in self.harvest:
                yy = np.full_like(yy, self.harvest[FIELDS[i]["id"]]["yield_t_ha"])
            per = np.array([CROPS[c]["kcal"], CROPS[c]["prot"], CROPS[c]["vita"]], float)
            out[i] = yy[..., None] * 1000 * FIELD_HA * per / need
        return out

    def project(self, publish: bool = True) -> dict:
        if self.phase != "season":
            return {"error": "no season running"}
        dd = min(self.day, D - 1)
        y, w, e = self._season_batch([(self.irr_hist[:, dd], self.desal_hist[:, dd])], 20, seed=500 + self.day)
        P = self._people_arrays(y)[:, 0]
        fed = P.sum(0).min(-1)
        water = self.water_used + w[:, 0].sum(0)
        out = {"day": self.day, "people_p10": round(float(np.percentile(fed, 10)), 1),
               "people_p50": round(float(np.median(fed)), 1),
               "by_nutrient_p50": {n: round(float(np.median(P.sum(0)[:, j])), 1) for j, n in enumerate(NUTRIENTS)},
               "water_total_p90_m3": round(float(np.percentile(water, 90))),
               "field_yield_p50": {FIELDS[i]["id"]: round(float(np.median(y[i, 0])), 2) for i in range(NF) if self.run_plan[i]["crop"]}}
        if publish:
            self.bus.publish("projection", out)
        return out

    def rebalance_water(self, rationale: str) -> dict:
        """Re-optimise irrigation level and desal blend per field for the rest of the season."""
        if self.phase != "season":
            return {"refused": "no season running"}
        levels = [(a, b) for a in (0.5, 0.7, 0.85, 1.0, 1.15) for b in (0.0, 0.5, 0.8)]
        S = 16
        y, w, e = self._season_batch([(np.full(NF, a), np.full(NF, b)) for a, b in levels], S, seed=700 + self.day)
        P = self._people_arrays(y)
        quota_left = self.limits.water_quota_m3 - self.water_used
        energy_left = self.limits.energy_kwh - self.energy_used
        dd = min(self.day, D - 1)
        cur = np.array([int(np.argmin([abs(a - self.irr_hist[i, dd]) + abs(b - self.desal_hist[i, dd]) for a, b in levels]))
                        for i in range(NF)])
        active = [i for i, f in enumerate(self.run_plan) if f["crop"] and not self.harvested[i]]
        choice = cur.copy()
        for _ in range(6):
            changed = False
            for i in active:
                others = [g for g in range(NF) if g != i]
                tp = sum(P[g, choice[g]] for g in others)
                tw = sum(w[g, choice[g]] for g in others)
                te = sum(e[g, choice[g]] for g in others)
                fed = (tp[None] + P[i]).min(-1)
                p10 = np.percentile(fed, 10, axis=1)
                w90 = np.percentile(tw[None] + w[i], 90, axis=1)
                e90 = np.percentile(te[None] + e[i], 90, axis=1)
                score = p10 - 1e3 * (np.maximum(w90 - quota_left, 0) / max(quota_left, 1)
                                     + np.maximum(e90 - energy_left, 0) / max(energy_left, 1))
                k = int(np.argmax(score))
                if k != choice[i]:
                    choice[i], changed = k, True
            if not changed:
                break
        before = P[np.arange(NF), cur].sum(0).min(-1)
        after = P[np.arange(NF), choice].sum(0).min(-1)
        changes = []
        for i in active:
            a, b = levels[choice[i]]
            if choice[i] != cur[i]:
                self.irr_hist[i, self.day:] = a
                self.desal_hist[i, self.day:] = b
                self.farm.set_management(i, desal=b)
            changes.append({"field": FIELDS[i]["id"], "crop": self.run_plan[i]["crop"], "irr": a, "desal": b,
                            "changed": bool(choice[i] != cur[i])})
        self._build_ensemble()
        out = {"fields": changes, "people_p10_before": round(float(np.percentile(before, 10)), 1),
               "people_p10_after": round(float(np.percentile(after, 10)), 1), "water_left_m3": round(quota_left),
               "future_water_p90_m3": round(float(np.percentile(sum(w[g, choice[g]] for g in range(NF)), 90)))}
        self._log("rebalance", {"rationale": rationale, **out})
        self.project()
        return out

    def finish(self, summary: str) -> dict:
        if self.phase == "season":
            while self.day < D and not self.stop_flag.is_set():
                self._one_day()
                self.anomaly = None
            if self.phase == "season":
                self._season_end()
        self.done = True
        out = {"summary": summary, "result": self.result, "anomalies": len(self.anomalies),
               "plots_used": self.plots_used, "tests_used": self.tests_used,
               "hypotheses": {h["id"]: h["status"] for h in self.hyps.values()}}
        self._log("run_end", out)
        self._status()
        return out


def normalize_choices(choices) -> list:
    """Validate the farmer's per-field picks; raises ValueError with a message for the farmer."""
    out: list[dict | None] = [None] * NF
    if not isinstance(choices, list):
        raise ValueError("choices must be a list, one entry per field")
    for i, ch in enumerate(choices[:NF]):
        if ch is not None and not isinstance(ch, dict):
            raise ValueError("each field choice must be an object")
        if not ch or ch.get("mode", "scientist") == "scientist":
            continue
        if ch.get("mode") == "fallow":
            out[i] = {"mode": "fallow"}
            continue
        if ch.get("mode") != "crop":
            raise ValueError("a field choice's mode must be scientist, fallow or crop")
        c, sid = ch.get("crop"), ch.get("season")
        if c not in CROPS:
            raise ValueError(f"unknown crop {c!r}")
        if sid not in SEASONS.SEASON_IDS:
            raise ValueError(f"unknown season {sid!r}")
        if not SEASONS.in_season(c, sid):
            ok = ", ".join(SEASONS.season(x)["label"].lower() for x in SEASONS.seasons_for(c))
            raise ValueError(f"{CROPS[c]['label']} is not sown in {SEASONS.season(sid)['label'].lower()}; choose {ok}")
        out[i] = {"mode": "crop", "crop": c, "season": sid}
    return out
