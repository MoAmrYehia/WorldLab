"""The lab: everything the agent can do to the world, with numbers attached.

The agent (Muse Spark, Muse Glimmer, or the scripted baseline) decides; this
module executes. Every action is bounded by the safety governor, every
prediction carries an uncertainty band, every result is compared against the
prediction made before it ran, and every step is written to the hash-chained
ledger.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
import queue
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np

from . import model as M
from .ledger import Ledger
from .rig.base import Rig, fan_power_model


# ----------------------------------------------------------------- settings

@dataclass
class Limits:
    T_abort: float = 75.0            # hard trip: heater off, fan full
    T_plan_max: float = 68.0         # predicted 95th pct must stay below this
    max_experiment_s: float = 900.0
    min_step_s: float = 30.0
    max_steps: int = 6
    exploration_budget_J: float = 2500.0


@dataclass
class Goal:
    target_C: float = 42.0           # keep the heatsink at or below this
    settle_s: float = 300.0          # time allowed to get there
    hold_s: float = 1200.0           # then hold it for this long (cumulative)
    task_budget_J: float = 1500.0    # fan energy allowed for the task
    tolerance_K: float = 0.3

    def describe(self) -> str:
        return (f"Keep the heated object at or below {self.target_C:.1f} C (tolerance "
                f"{self.tolerance_K} K) for {self.hold_s:.0f} s of cumulative hold time, reaching it within "
                f"{self.settle_s:.0f} s of starting a plan, using at most {self.task_budget_J:.0f} J of fan "
                f"energy for the task. Exploration experiments have a separate budget.")


# ---------------------------------------------------------------------- bus

class Bus:
    """Fan-out of live events to dashboard clients, plus a snapshot for late joiners."""

    def __init__(self):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.snapshot: dict = {"samples": [], "events": [], "forecasts": [], "scene": None,
                               "model": None, "plan": None, "status": {}, "agent": [], "fits": [],
                               "perturbations": []}

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
        snap = self.snapshot
        if kind == "sample":
            snap["samples"].append(payload)
        elif kind == "ledger":
            snap["events"].append(payload)
        elif kind == "forecast":
            snap["forecasts"].append(payload)
        elif kind == "agent":
            snap["agent"].append(payload)
        elif kind == "perturbation":
            snap["perturbations"].append(payload)
        elif kind == "fit":
            snap["fits"].append(payload)
            snap["model"] = payload
        elif kind in ("scene", "plan", "status"):
            snap[kind] = payload
        msg = {"kind": kind, "data": payload}
        with self._lock:
            for q in list(self._subs):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


# ------------------------------------------------------------------ monitor

class Monitor:
    """Runs the current model alongside reality, as an ensemble over the
    parameter uncertainty, driven by the *measured* inputs. Flags a sustained
    disagreement with a two-sided CUSUM on standardised residuals."""

    def __init__(self, fit: M.Fit, last: dict, S: int = 200, seed: int = 0,
                 k: float = 1.5, h: float = 12.0, warmup_s: float = 40.0, min_effect_K: float = 0.6):
        self.fit = fit
        self.P = {n: np.asarray(v, float) for n, v in fit.sample(S, np.random.default_rng(seed)).items()}
        self.state = np.full(S, last["T_obj"])
        self.last = last
        self.t0 = last["t"]
        self.floor = max(0.12, fit.rmse if math.isfinite(fit.rmse) else 0.3)
        self.k, self.h, self.warmup = k, h, warmup_s
        self.min_effect = min_effect_K
        self.sp = self.sn = 0.0
        self.since_zero = last["t"]
        self.zs: list[float] = []
        self.inside = 0
        self.count = 0
        self.alarm: dict | None = None
        self._acc = 0.0

    def update(self, s: dict) -> dict:
        dt = s["t"] - self.last["t"]
        if dt > 0:
            u, q, Ta = self.last["fan_duty"], self.last["heater_w"], self.last["T_amb"]
            k = np.maximum(M.cooling_rate(self.fit.structure, self.P, u), 1e-7)
            Teq = Ta + self.P["b"] * q / k
            self.state = Teq + (self.state - Teq) * np.exp(-k * dt)
        self.last = s
        mean = float(self.state.mean())
        sd = math.sqrt(float(self.state.var()) + M.SENSOR_SIGMA ** 2 + self.floor ** 2)
        lo, hi = float(np.percentile(self.state, 5)) - 1.645 * M.SENSOR_SIGMA, float(np.percentile(self.state, 95)) + 1.645 * M.SENSOR_SIGMA
        z = (s["T_obj"] - mean) / sd
        self.count += 1
        if lo - self.floor <= s["T_obj"] <= hi + self.floor:
            self.inside += 1
        self.zs.append(z)
        # CUSUM on ~5 s cadence so 1 Hz autocorrelated samples are not over-counted
        self._acc += dt
        if self._acc >= 5.0 and s["t"] - self.t0 >= self.warmup and self.alarm is None:
            self._acc = 0.0
            # Only a divergence big enough to matter for the goal accumulates evidence.
            zc = z if abs(s["T_obj"] - mean) >= self.min_effect else 0.0
            self.sp = max(0.0, self.sp + zc - self.k)
            self.sn = max(0.0, self.sn - zc - self.k)
            if self.sp == 0.0 and self.sn == 0.0:
                self.since_zero = s["t"]
            if self.sp > self.h or self.sn > self.h:
                self.alarm = {
                    "t_detected": s["t"], "onset_estimate_t": round(self.since_zero, 1),
                    "direction": "warmer than predicted" if self.sp > self.h else "cooler than predicted",
                    "residual_K": round(s["T_obj"] - mean, 3), "z": round(z, 2),
                }
        return {"pred": round(mean, 3), "lo": round(lo, 3), "hi": round(hi, 3), "z": round(z, 2)}

    def summary(self) -> dict:
        zs = np.array(self.zs) if self.zs else np.zeros(1)
        cov = self.inside / max(self.count, 1)
        return {"coverage_90pct_band": round(cov, 3), "mean_z": round(float(zs.mean()), 2),
                "max_abs_z": round(float(np.abs(zs).max()), 2), "n": self.count,
                "prediction_held": bool(cov >= 0.8 and abs(zs.mean()) < 1.5 and self.alarm is None)}


# ---------------------------------------------------------------------- lab

class StopRequested(Exception):
    pass


class Lab:
    def __init__(self, rig: Rig, goal: Goal | None = None, limits: Limits | None = None,
                 run_dir: str | Path | None = None, perception=None, bus: Bus | None = None,
                 scene_check_s: float = 120.0):
        self.rig = rig
        self.goal = goal or Goal()
        self.limits = limits or Limits()
        self.bus = bus or Bus()
        self.perception = perception
        self.scene_check_s = scene_check_s
        self.run_dir = Path(run_dir) if run_dir else None
        if self.run_dir:
            (self.run_dir / "frames").mkdir(parents=True, exist_ok=True)
            self._csv = (self.run_dir / "samples.csv").open("w", newline="")
            self._csvw = csv.writer(self._csv)
            self._csvw.writerow(["t", "T_obj", "T_amb", "fan_duty", "heater_w", "fan_power_w", "activity"])
        else:
            self._csv = None
        self.ledger = Ledger(self.run_dir / "ledger.jsonl" if self.run_dir else None)
        self.samples: list[dict] = []
        self.energy = {"exploration": 0.0, "task": 0.0, "idle": 0.0}
        self.fit: M.Fit = M.prior_fit("power")
        self.fits: list[M.Fit] = [self.fit]
        self.model_status = "prior"
        self.hyps: dict[str, dict] = {}
        self.candidates: dict[str, dict] = {}
        self.plans: dict[str, dict] = {}
        self.experiments: list[dict] = []
        self.anomaly: dict | None = None
        self.anomalies: list[dict] = []
        self.fit_reference: M.Fit | None = None  # last model trusted before the latest anomaly
        self.scene_ref: dict | None = None
        self.scene_last: dict | None = None
        self.hold_done_s = 0.0
        self.hold_ok_s = 0.0
        self.tripped = False
        self.done = False
        self.stop_flag = threading.Event()
        self._ids = {"H": 0, "C": 0, "P": 0, "E": 0}
        self._last_scene_t = -1e9
        self.power_scale = 1.0
        self._log("run_start", {"goal": asdict(self.goal), "limits": asdict(self.limits),
                                "rig": asdict(rig.caps)})
        self.sync()
        self._status()

    # ----------------------------------------------------------- plumbing
    @property
    def belief(self) -> M.Mixture:
        """What the lab predicts with: all fitted structures, evidence-weighted."""
        return M.Mixture(self.fits)

    def tested_duties(self, min_hold_s: float = 60.0) -> list[float]:
        """Fan duties that were actually held for a while (heater on), so the model has seen them."""
        out, start, cur = set(), None, None
        for s in self.samples:
            u = round(s["fan_duty"], 2)
            if u != cur:
                cur, start = u, s["t"]
            elif s["t"] - start >= min_hold_s and s["heater_w"] > 0:
                out.add(u)
        return sorted(out)

    def _id(self, p):
        self._ids[p] += 1
        return f"{p}{self._ids[p]}"

    def _log(self, kind: str, data: dict) -> dict:
        e = self.ledger.append(kind, data, t_rig=round(self.rig.now(), 1))
        self.bus.publish("ledger", e)
        return e

    def agent_note(self, role: str, text: str, extra: dict | None = None):
        item = {"t": round(self.rig.now(), 1), "role": role, "text": text, **(extra or {})}
        self.bus.publish("agent", item)
        self._log("agent_step", item)

    def _status(self):
        self.bus.publish("status", {
            "t": round(self.rig.now(), 1), "model_status": self.model_status,
            "energy_J": {k: round(v, 1) for k, v in self.energy.items()},
            "exploration_budget_J": self.limits.exploration_budget_J,
            "task_budget_J": self.goal.task_budget_J, "goal": asdict(self.goal),
            "hold_done_s": round(self.hold_done_s, 1), "hold_ok_s": round(self.hold_ok_s, 1),
            "anomaly": self.anomaly, "tripped": self.tripped, "done": self.done,
            "hypotheses": list(self.hyps.values()),
        })

    def latest(self) -> dict:
        return self.samples[-1]

    def _ingest(self, samples, activity: str, monitor: Monitor | None = None):
        for s in samples:
            d = s.to_dict() if hasattr(s, "to_dict") else dict(s)
            if self.samples:
                dt = max(0.0, d["t"] - self.samples[-1]["t"])
                self.energy[activity] += self.samples[-1]["fan_power_w"] * dt
            d["activity"] = activity
            if monitor is not None:
                d.update(monitor.update(d))
            self.samples.append(d)
            if self._csv:
                self._csvw.writerow([d["t"], d["T_obj"], d["T_amb"], d["fan_duty"], d["heater_w"],
                                     d["fan_power_w"], activity])
            self.bus.publish("sample", d)
            if d["T_obj"] >= self.limits.T_abort and not self.tripped:
                self.tripped = True
                self.rig.safe_state()
                self._log("safety_trip", {"T_obj": d["T_obj"], "limit": self.limits.T_abort,
                                          "action": "heater off, fan 100%"})
        if self._csv:
            self._csv.flush()

    def sync(self):
        """Pull in samples taken while the agent was thinking (real hardware)."""
        s = self.rig.drain()
        if s:
            self._ingest(s, "idle")
        if not self.samples:
            self._ingest(self.rig.advance(self.rig.caps.sample_period_s), "idle")

    def _run(self, seconds: float, activity: str, monitor: Monitor | None, scene_watch: bool = False,
             on_chunk=None, stop_on_alarm: bool = True, guard_T: float | None = None) -> str:
        """Let time pass in 5 s chunks. Returns 'ok', 'anomaly', 'scene', 'trip',
        'guard' (object reached guard_T, step ended early) or 'stopped'."""
        end = self.rig.now() + seconds
        while self.rig.now() < end - 1e-6:
            if self.stop_flag.is_set():
                return "stopped"
            chunk = min(5.0, end - self.rig.now())
            self._ingest(self.rig.advance(chunk), activity, monitor)
            if on_chunk:
                on_chunk(chunk)
            if self.tripped:
                return "trip"
            if guard_T is not None and self.latest()["T_obj"] >= guard_T:
                return "guard"
            if monitor and monitor.alarm and stop_on_alarm:
                return "anomaly"
            if scene_watch and self.perception and self.rig.now() - self._last_scene_t >= self.scene_check_s:
                sc = self.look_at_scene(reason="periodic check during plan execution")
                if sc.get("changed_vs_reference"):
                    return "scene"
            self._status()
        self._status()
        return "ok"

    def _fan_power(self, u):
        return self.power_scale * np.vectorize(fan_power_model)(np.asarray(u, float))

    def _update_power_scale(self):
        ratios = [s["fan_power_w"] / fan_power_model(s["fan_duty"]) for s in self.samples[-2000:]
                  if s["fan_duty"] > 0.05 and fan_power_model(s["fan_duty"]) > 0]
        if len(ratios) > 5:
            self.power_scale = float(np.median(ratios))

    @staticmethod
    def _digest(rows: list[dict]) -> str:
        return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()

    def _check_stop(self):
        if self.stop_flag.is_set():
            raise StopRequested()

    # ============================================================ TOOLS ==
    def observe(self) -> dict:
        self.sync()
        s = self.latest()
        recent = [x for x in self.samples if x["t"] >= s["t"] - 120]
        slope = 0.0
        if len(recent) > 5:
            tt = np.array([x["t"] for x in recent])
            TT = np.array([x["T_obj"] for x in recent])
            slope = float(np.polyfit(tt - tt[0], TT, 1)[0]) * 60
        return {
            "rig_time_s": round(s["t"], 1),
            "object_temp_C": s["T_obj"], "ambient_temp_C": s["T_amb"],
            "trend_K_per_min_last_2min": round(slope, 3),
            "fan_duty": s["fan_duty"], "heater_w": s["heater_w"], "fan_power_w": round(s["fan_power_w"], 3),
            "energy_used_J": {k: round(v, 1) for k, v in self.energy.items()},
            "exploration_budget_left_J": round(self.limits.exploration_budget_J - self.energy["exploration"], 1),
            "task_budget_left_J": round(self.goal.task_budget_J - self.energy["task"], 1),
            "goal": self.goal.describe(),
            "goal_progress": {"hold_done_s": round(self.hold_done_s, 1), "hold_required_s": self.goal.hold_s,
                              "hold_compliant_s": round(self.hold_ok_s, 1)},
            "model_status": self.model_status,
            "active_anomaly": self.anomaly,
            "safety_tripped": self.tripped,
            "rig": {"simulated": self.rig.caps.simulated, "heater_w": self.rig.caps.heater_w,
                    "camera": self.rig.caps.has_camera},
        }

    def look_at_scene(self, reason: str = "") -> dict:
        self.sync()
        self._last_scene_t = self.rig.now()
        if not self.perception or not self.rig.caps.has_camera:
            return {"available": False, "note": "no camera or perception configured"}
        frame = self.rig.capture_frame()
        if frame is None:
            return {"available": False, "note": "camera returned no frame"}
        res = self.perception.analyze(frame, self.rig.frame_mime())
        self._scene_last_raw = res
        fname = None
        if self.run_dir:
            fname = f"frames/scene_{int(self.rig.now()):06d}.png"
            (self.run_dir / fname).write_bytes(frame)
        out = {"available": True, "source": res.get("source"), "objects": res.get("objects", []),
               "aim": res.get("aim"), "image_size": res.get("image_size")}
        if self.scene_ref is None and res.get("objects"):
            self.scene_ref = res
            out["reference"] = "this view is now the reference layout"
            out["changed_vs_reference"] = False
        elif self.scene_ref is not None:
            out.update(compare_scenes(self.scene_ref, res))
        self.scene_last = out
        self.bus.publish("scene", {**out, "t": round(self.rig.now(), 1),
                                   "image": "data:%s;base64,%s" % (self.rig.frame_mime(), base64.b64encode(frame).decode())})
        self._log("scene", {"reason": reason, "frame": fname, **{k: v for k, v in out.items() if k != "objects"},
                            "objects": out.get("objects")})
        return out

    def get_model(self) -> dict:
        f = self.fit.to_json()
        s = self.latest()
        u_grid = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
        ss = []
        bel = self.belief
        P = bel.sample(300, np.random.default_rng(1))
        for u in u_grid:
            k = np.maximum(M.cooling_rate(bel.structure, P, u), 1e-7)
            Tss = s["T_amb"] + P["b"] * self.rig.caps.heater_w / k
            ss.append({"fan_duty": u, "steady_state_C_heater_on": round(float(np.median(Tss)), 2),
                       "p5_p95": [round(float(np.percentile(Tss, 5)), 2), round(float(np.percentile(Tss, 95)), 2)]})
        return {"status": self.model_status, "model": f, "steady_state_table": ss,
                "structure_weights": bel.weights_json(), "tested_duties": self.tested_duties(),
                "fan_power_scale_vs_nominal": round(self.power_scale, 3),
                "recent_fits": [x for x in self.bus.snapshot["fits"][-1:]]}

    def record_hypothesis(self, statement: str, prediction: str, falsified_if: str) -> dict:
        hid = self._id("H")
        h = {"id": hid, "statement": statement, "prediction": prediction, "falsified_if": falsified_if,
             "status": "open", "created_t": round(self.rig.now(), 1), "evidence": []}
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
        h["evidence"].append({"t": round(self.rig.now(), 1), "text": evidence})
        self._log("conclusion", {"hypothesis_id": hypothesis_id, "verdict": verdict, "evidence": evidence})
        self._status()
        return {"ok": True, "hypothesis": h}

    # ------------------------------------------------------- experiments
    def _validate_steps(self, steps) -> str | None:
        if not isinstance(steps, list) or not steps:
            return "steps must be a non-empty list"
        if len(steps) > self.limits.max_steps:
            return f"at most {self.limits.max_steps} steps"
        tot = 0.0
        for st in steps:
            try:
                u = float(st["fan_duty"])
                d = float(st["duration_s"])
            except (KeyError, TypeError, ValueError):
                return "each step needs fan_duty (0..1) and duration_s"
            if not 0.0 <= u <= 1.0:
                return f"fan_duty {u} outside 0..1"
            if d < self.limits.min_step_s:
                return f"step duration {d} s below minimum {self.limits.min_step_s} s"
            if st.get("heater_on", True) and not self.rig.caps.has_heater:
                return "this rig has no heater"
            tot += d
        if tot > self.limits.max_experiment_s:
            return f"total duration {tot} s exceeds {self.limits.max_experiment_s} s"
        return None

    def _assess(self, steps, fit: M.Fit | None = None) -> dict:
        fit = fit or self.fit
        s = self.latest()
        dt, u, q, Ta = M.schedule_arrays(steps, self.rig.caps.heater_w, s["T_amb"])
        pred = M.predict(self.belief, s["T_obj"], s["t"], dt, u, q, Ta)
        energy = float(np.sum(self._fan_power(u) * dt))
        gain = M.info_gain(fit, s["T_obj"], dt, u, q, Ta)
        g0 = self._goal_sd(fit)
        g1 = self._goal_sd(gain["posterior"])
        return {"pred": pred, "energy_J": energy, "bits": gain["bits"], "goal_sd_before": g0,
                "goal_sd_after": g1, "max_T_p95": float(pred.hi.max()), "duration_s": float(np.sum(dt)),
                "touches_duties": sorted({round(float(x), 2) for x in u})}

    def _goal_sd(self, fit: M.Fit) -> float:
        """Uncertainty (K) in steady-state temperature at the duty the model
        currently thinks meets the goal: the number that decides energy spend."""
        s = self.latest()
        p = fit.params()
        u_star = 1.0
        for u in np.linspace(0, 1, 51):
            if M.steady_state(p, fit.structure, u, self.rig.caps.heater_w, s["T_amb"]) <= self.goal.target_C:
                u_star = float(u)
                break
        P = fit.sample(300, np.random.default_rng(2))
        k = np.maximum(M.cooling_rate(fit.structure, P, u_star), 1e-7)
        return float(np.std(s["T_amb"] + P["b"] * self.rig.caps.heater_w / k))

    def structural_spread(self) -> dict:
        """How much the competing airflow hypotheses disagree about the steady
        temperature, across fan duties. Large spread = more experiments needed."""
        s = self.latest()
        out = {}
        for u in (0.1, 0.2, 0.3, 0.5, 0.8):
            vals = [M.steady_state(f.params(), f.structure, u, self.rig.caps.heater_w, s["T_amb"])
                    for f, w in zip(self.belief.members, self.belief.weights) if w >= 0.05]
            out[u] = round(max(vals) - min(vals), 2) if len(vals) > 1 else 0.0
        return out

    def standard_candidates(self) -> list[dict]:
        T = self.latest()["T_obj"]
        Ta = self.latest()["T_amb"]
        warm = T - Ta > 8
        c = []
        if not warm:
            c.append({"name": "heat-up, fan off", "steps": [{"fan_duty": 0.0, "heater_on": True, "duration_s": 600}]})
        c += [
            {"name": "fan full", "steps": [{"fan_duty": 1.0, "heater_on": True, "duration_s": 240}]},
            {"name": "fan 35%", "steps": [{"fan_duty": 0.35, "heater_on": True, "duration_s": 240}]},
            {"name": "fan 60%", "steps": [{"fan_duty": 0.6, "heater_on": True, "duration_s": 180}]},
            {"name": "fan 15% (near stall?)", "steps": [{"fan_duty": 0.15, "heater_on": True, "duration_s": 240}]},
            {"name": "fan off, heater on", "steps": [{"fan_duty": 0.0, "heater_on": True, "duration_s": 240}]},
            {"name": "staircase 100/50/25", "steps": [{"fan_duty": 1.0, "heater_on": True, "duration_s": 150},
                                                      {"fan_duty": 0.5, "heater_on": True, "duration_s": 150},
                                                      {"fan_duty": 0.25, "heater_on": True, "duration_s": 150}]},
        ]
        return c

    def evaluate_experiments(self, candidates: list[dict] | None = None) -> dict:
        self.sync()
        candidates = candidates or self.standard_candidates()
        out = []
        left = self.limits.exploration_budget_J - self.energy["exploration"]
        for c in candidates[:8]:
            steps = c.get("steps")
            err = self._validate_steps(steps)
            if err:
                out.append({"name": c.get("name"), "rejected": err})
                continue
            a = self._assess(steps)
            cid = self._id("C")
            safe = float(np.max(a["pred"].mean)) <= self.limits.T_abort - 2
            within = a["energy_J"] <= left
            rec = {"candidate_id": cid, "name": c.get("name", cid), "steps": steps,
                   "duration_s": round(a["duration_s"]), "fan_energy_J": round(a["energy_J"], 1),
                   "predicted_final_C": round(float(a["pred"].mean[-1]), 2),
                   "predicted_final_90pct": [round(float(a["pred"].lo[-1]), 2), round(float(a["pred"].hi[-1]), 2)],
                   "predicted_max_C_p95": round(a["max_T_p95"], 2),
                   "expected_information_bits": round(a["bits"], 2),
                   "goal_uncertainty_K_before_after": [round(a["goal_sd_before"], 3), round(a["goal_sd_after"], 3)],
                   "bits_per_100J": round(a["bits"] / max(a["energy_J"], 1.0) * 100, 2),
                   "safe": safe, "within_budget": within,
                   "may_hit_guard": a["max_T_p95"] > self.limits.T_plan_max}
            self.candidates[cid] = {**rec, "_pred": a["pred"]}
            out.append(rec)
        self._log("experiment_options", {"options": out, "model_structure": self.fit.structure})
        return {"options": out, "exploration_budget_left_J": round(left, 1),
                "tested_duties": self.tested_duties(),
                "structure_weights": self.belief.weights_json(),
                "structural_spread_K_by_duty": self.structural_spread(),
                "note": ("information bits are a linearised estimate for the current model structure; "
                         f"heater steps are guarded: they end early if the object reaches {self.limits.T_plan_max} C")}

    def run_experiment(self, hypothesis_id: str, rationale: str, candidate_id: str | None = None,
                       steps: list | None = None, name: str | None = None) -> dict:
        self.sync()
        if self.tripped:
            return {"refused": "safety trip active; the rig is in safe state"}
        if candidate_id:
            c = self.candidates.get(candidate_id)
            if not c:
                return {"refused": f"unknown candidate {candidate_id}; call evaluate_experiments first"}
            steps, name = c["steps"], c["name"]
        err = self._validate_steps(steps)
        if err:
            return {"refused": err}
        if hypothesis_id not in self.hyps:
            return {"refused": f"record a hypothesis first (unknown id {hypothesis_id})"}
        a = self._assess(steps)
        left = self.limits.exploration_budget_J - self.energy["exploration"]
        med_max = float(np.max(a["pred"].mean))
        if med_max > self.limits.T_abort - 2:
            self._log("safety_block", {"why": "predicted temperature too high", "median_max_C": med_max, "steps": steps})
            return {"refused": f"median predicted max temperature {med_max:.1f} C is too close to the {self.limits.T_abort} C trip"}
        if a["energy_J"] > left:
            self._log("safety_block", {"why": "exploration budget", "needed_J": a["energy_J"], "left_J": left})
            return {"refused": f"needs {a['energy_J']:.0f} J, exploration budget left {left:.0f} J"}
        eid = self._id("E")
        pred = a["pred"]
        start_t = self.latest()["t"]
        self._log("prediction", {"experiment_id": eid, "hypothesis_id": hypothesis_id,
                                 "final_C": round(float(pred.mean[-1]), 3),
                                 "final_90pct": [round(float(pred.lo[-1]), 3), round(float(pred.hi[-1]), 3)],
                                 "model": self.fit.structure, "params": self.fit.params()})
        self._log("experiment_start", {"experiment_id": eid, "name": name, "steps": steps,
                                       "hypothesis_id": hypothesis_id, "rationale": rationale})
        self.bus.publish("forecast", {"id": eid, "label": f"{eid} {name}", **pred.to_json()})
        mon = Monitor(self.belief, self.latest())
        status = "ok"
        guarded: list[float] = []
        step_stats = []
        for st in steps:
            n0 = len(self.samples)
            self.rig.set_fan(float(st["fan_duty"]))
            self.rig.set_heater(bool(st.get("heater_on", True)))
            # experiments are allowed to falsify the model, so a divergence is
            # recorded but does not interrupt the run
            status = self._run(float(st["duration_s"]), "exploration", mon, stop_on_alarm=False,
                               guard_T=self.limits.T_plan_max if st.get("heater_on", True) else None)
            if status == "guard":
                guarded.append(round(self.rig.now(), 1))
                self.rig.set_heater(False)
                self._log("safety_guard", {"experiment_id": eid, "T_obj": self.latest()["T_obj"],
                                           "guard_C": self.limits.T_plan_max, "action": "step ended early, heater off"})
                status = "ok"
            seg = [x for x in self.samples[n0:] if "pred" in x]
            if seg:
                res = np.array([x["T_obj"] - x["pred"] for x in seg])
                inside = np.mean([x["lo"] - mon.floor <= x["T_obj"] <= x["hi"] + mon.floor for x in seg])
                step_stats.append({"fan_duty": st["fan_duty"], "heater_on": st.get("heater_on", True),
                                   "mean_residual_K": round(float(res.mean()), 3),
                                   "final_residual_K": round(float(res[-1]), 3),
                                   "coverage_90pct_band": round(float(inside), 3),
                                   "matched_prediction": bool(inside >= 0.8 and abs(res.mean()) < 0.5)})
            if status in ("trip", "stopped"):
                break
        rows = [x for x in self.samples if x["t"] > start_t]
        final = rows[-1] if rows else self.latest()
        summ = mon.summary()
        if mon.alarm:
            summ["divergence"] = mon.alarm
        if guarded:
            summ["guard_stops_at_t"] = guarded
        summ["per_step"] = step_stats
        result = {
            "experiment_id": eid, "name": name, "status": status, "hypothesis_id": hypothesis_id,
            "measured_final_C": final["T_obj"],
            "predicted_final_C": round(float(pred.mean[-1]), 2),
            "predicted_final_90pct": [round(float(pred.lo[-1]), 2), round(float(pred.hi[-1]), 2)],
            "fan_energy_J": round(sum(r["fan_power_w"] for r in rows) * self.rig.caps.sample_period_s, 1),
            **summ,
            "data_sha256": self._digest(rows),
            "t_start": round(start_t, 1), "t_end": round(final["t"], 1),
        }
        self.experiments.append(result)
        self._update_power_scale()
        self._log("experiment_result", result)
        self._status()
        out = dict(result)
        out["next"] = "call fit_model to learn from this data, then conclude the hypothesis"
        return out

    # ------------------------------------------------------------ fitting
    def fit_model(self, rationale: str, structures: list[str] | None = None, since_t: float | None = None,
                  hold_params: list[str] | None = None) -> dict:
        self.sync()
        data = M.Data.from_samples(self.samples, since=since_t)
        if len(data) < 12:
            return {"error": f"only {len(data)} usable points since t={since_t}; run an experiment first"}
        fix = None
        ref = self.fit_reference or self.fit
        if hold_params:
            cur = ref.params()
            fix = {n: cur[n] for n in hold_params if n in cur}
        prior = None
        if since_t is not None and self.model_status != "prior":
            # Post-change refit: start from what was known, widened so that
            # parameters which really changed are free to move.
            sd = ref.sd()
            prior = {n: (v, max(3 * sd.get(n, 0.0), 0.25 * abs(v), 1e-6)) for n, v in ref.params().items()}
            if not structures:
                structures = [ref.structure]
        structures = [s for s in (structures or list(M.STRUCTURES)) if s in M.STRUCTURES]
        fits = M.fit_all(data, structures=structures, start=self.fit.params(), since=since_t, fix=fix,
                         prior=prior if (structures == [ref.structure]) else None)
        best = fits[0]
        self.fits = fits
        table = [{"structure": f.structure, "aic": round(f.aic, 1), "delta_aic": round(f.aic - best.aic, 1),
                  "rmse_K": round(f.rmse, 3), "params": {k: round(v, 6) for k, v in f.params().items()}}
                 for f in fits]
        prev = self.fit
        self.fit = best
        self.model_status = "fitted"
        resolved = None
        if self.anomaly:
            resolved = self.anomaly
            self.anomaly = None
            # The agent has explained the change and refit: the current camera
            # view becomes the new reference layout.
            if getattr(self, "_scene_last_raw", None) and self._scene_last_raw.get("objects"):
                self.scene_ref = self._scene_last_raw
                self._log("scene_reference", {"note": "reference layout updated after the anomaly was resolved"})
        # k(u) curve with band, for the dashboard
        bel = self.belief
        P = bel.sample(400, np.random.default_rng(3))
        ug = np.linspace(0, 1, 41)
        K = np.maximum(M.cooling_rate(bel.structure, {n: v[:, None] for n, v in P.items()}, ug[None, :]), 1e-7)
        curve = {"u": ug.round(3).tolist(), "k_med": np.median(K, 0).round(6).tolist(),
                 "k_lo": np.percentile(K, 5, 0).round(6).tolist(), "k_hi": np.percentile(K, 95, 0).round(6).tolist()}
        payload = {"t": round(self.rig.now(), 1), **best.to_json(), "ranking": table, "k_curve": curve,
                   "weights": bel.weights_json(), "tested_duties": self.tested_duties(),
                   "rationale": rationale, "held": fix or {}}
        self.bus.publish("fit", payload)
        self._log("model_update", {"rationale": rationale, "since_t": since_t, "held": fix or {},
                                   "ranking": table, "adopted": best.to_json(),
                                   "previous": prev.to_json(), "resolved_anomaly": resolved})
        self._status()
        return {"adopted": best.to_json(), "ranking": table, "structure_weights": bel.weights_json(),
                "structural_spread_K_by_duty": self.structural_spread(),
                "data_points": len(data), "since_t": since_t, "held_params": fix or {},
                "note": "lower AIC is better; a delta_aic above ~10 is strong evidence against that structure"}

    # ----------------------------------------------------------- planning
    def plan_control(self, rationale: str) -> dict:
        self.sync()
        if self.anomaly:
            return {"refused": "the model is invalidated by an unexplained anomaly; investigate and refit before planning",
                    "anomaly": self.anomaly}
        if self.model_status == "prior":
            return {"refused": "no fitted model yet; run experiments and fit_model first"}
        s = self.latest()
        remaining_hold = max(self.goal.hold_s - self.hold_done_s, 0.0)
        if remaining_hold <= 0:
            return {"refused": "goal already complete"}
        bel = self.belief
        res = plan_constant_then_hold(bel, s, self.rig.caps.heater_w, self.goal, remaining_hold,
                                      self._fan_power)
        nominal = plan_constant_then_hold(bel, s, self.rig.caps.heater_w, self.goal, remaining_hold,
                                          self._fan_power, robust=False)
        pid = self._id("P")
        left = self.goal.task_budget_J - self.energy["task"]
        plan = {"plan_id": pid, "phases": res["phases"], "feasible": res["feasible"],
                "predicted_energy_J": round(res["energy_J"], 1),
                "certainty_equivalent_energy_J": round(nominal["energy_J"], 1),
                "uncertainty_premium_J": round(res["energy_J"] - nominal["energy_J"], 1),
                "predicted_hold_max_C_p95": round(res["hold_max_p95"], 2),
                "predicted_settled_C_median": round(res["hold_med"], 2),
                "task_budget_left_J": round(left, 1),
                "within_budget": res["energy_J"] <= left,
                "remaining_hold_s": remaining_hold, "rationale": rationale,
                "model": self.fit.structure}
        if not res["feasible"]:
            plan["note"] = "no constant-duty plan keeps the 95th percentile under target; even full fan is not enough by the model"
        # Trust region: has the model ever seen the duty this plan relies on?
        u_hold = res["phases"][-1]["fan_duty"]
        tested = self.tested_duties()
        # Fan off is a different regime (no airflow), so only spinning duties count as evidence.
        near = [d for d in tested if d > 0 and abs(d - u_hold) <= max(0.05, 0.25 * u_hold)]
        plan["hold_duty"] = u_hold
        plan["tested_duties"] = tested
        plan["structure_weights"] = bel.weights_json()
        if u_hold > 0 and not near:
            plan["extrapolation"] = True
            plan["suggested_validation"] = {"name": f"validate operating point, fan {round(u_hold * 100)}%",
                                            "steps": [{"fan_duty": u_hold, "heater_on": True, "duration_s": 300}]}
            plan["note"] = (f"the hold duty {u_hold:.2f} is outside the duties tested so far {tested}; "
                            "the prediction there is an extrapolation. Consider running the suggested validation experiment first.")
        self.plans[pid] = {**plan, "_pred": res["pred"]}
        self.bus.publish("plan", {**plan, "t": round(s["t"], 1)})
        self.bus.publish("forecast", {"id": pid, "label": f"{pid} plan", **res["pred"].to_json()})
        self._log("plan", plan)
        return plan

    def execute_plan(self, plan_id: str, rationale: str) -> dict:
        self.sync()
        p = self.plans.get(plan_id)
        if not p:
            return {"refused": f"unknown plan {plan_id}"}
        if self.anomaly:
            return {"refused": "unresolved anomaly; refit the model before executing a plan"}
        if not p["within_budget"]:
            return {"refused": "plan exceeds the task energy budget"}
        self._log("plan_execute", {"plan_id": plan_id, "rationale": rationale})
        if self.perception and self.scene_ref is None:
            self.look_at_scene(reason="reference before executing plan")
        mon = Monitor(self.belief, self.latest())
        self.rig.set_heater(True)
        status = "ok"
        elapsed = 0.0
        start_t = self.latest()["t"]
        bel = self.belief
        P = bel.sample(300, np.random.default_rng(5))
        in_hold = {"on": False, "last_adj": -1e9, "adjustments": 0}

        def hold_duty(Ta: float, bias: float = 0.0) -> float:
            for u in np.round(np.arange(0, 1.0001, 0.01), 2):
                k = np.maximum(M.cooling_rate(bel.structure, P, u), 1e-7)
                if np.percentile(Ta + P["b"] * self.rig.caps.heater_w / k, 95) + bias <= self.goal.target_C - 0.1:
                    return float(u)
            return 1.0

        def recent_bias() -> float:
            """Offset-free control: the measured minus predicted temperature over
            the last minute, folded into the hold duty."""
            now = self.latest()["t"]
            r = [x["T_obj"] - x["pred"] for x in self.samples[-90:] if "pred" in x and x["t"] >= now - 60]
            return float(np.clip(np.mean(r), -1.0, 2.0)) if len(r) >= 20 else 0.0

        def count(chunk):
            nonlocal elapsed
            elapsed += chunk
            if elapsed > self.goal.settle_s:
                held = min(chunk, elapsed - self.goal.settle_s)
                self.hold_done_s += held
                if self.latest()["T_obj"] <= self.goal.target_C + self.goal.tolerance_K:
                    self.hold_ok_s += held
            # Feedback on measured conditions: the model is still trusted, but the
            # room may warm or cool. Re-derive the robust hold duty each minute.
            if in_hold["on"] and self.rig.now() - in_hold["last_adj"] >= 60:
                in_hold["last_adj"] = self.rig.now()
                s = self.latest()
                bias = recent_bias()
                u_new = hold_duty(s["T_amb"], bias)
                if abs(u_new - s["fan_duty"]) >= 0.02:
                    self.rig.set_fan(u_new)
                    in_hold["adjustments"] += 1
                    self._log("plan_adjust", {"plan_id": plan_id, "fan_duty": u_new, "was": s["fan_duty"],
                                              "measured_ambient_C": s["T_amb"], "model_bias_K": round(bias, 3),
                                              "why": "robust hold duty recomputed for the measured room temperature and model offset"})

        for i, ph in enumerate(p["phases"]):
            self.rig.set_fan(ph["fan_duty"])
            in_hold["on"] = i == len(p["phases"]) - 1
            in_hold["last_adj"] = self.rig.now()
            status = self._run(ph["duration_s"], "task", mon, scene_watch=True, on_chunk=count)
            if status != "ok":
                break
        result = {"plan_id": plan_id, "status": status, "elapsed_s": round(elapsed, 1),
                  "task_energy_used_J": round(self.energy["task"], 1),
                  "hold_done_s": round(self.hold_done_s, 1), "hold_compliant_s": round(self.hold_ok_s, 1),
                  "object_temp_C": self.latest()["T_obj"], "feedback_adjustments": in_hold["adjustments"],
                  **mon.summary()}
        if status in ("anomaly", "scene"):
            alarm = mon.alarm
            if alarm is None:
                # The camera caught it. Date the change by when measurement and
                # model started to separate, within the window since the last look.
                lo_t = self._last_scene_t - self.scene_check_s
                onset = lo_t
                for x in reversed(self.samples):
                    if x["t"] < lo_t:
                        break
                    if "pred" in x and abs(x["T_obj"] - x["pred"]) < 0.2:
                        onset = x["t"]
                        break
                alarm = {"t_detected": round(self.rig.now(), 1), "onset_estimate_t": round(onset, 1),
                         "direction": "scene changed"}
            self.anomaly = {"kind": "prediction_divergence" if status == "anomaly" else "scene_change",
                            **alarm, "during": plan_id,
                            "scene": {k: v for k, v in (self.scene_last or {}).items() if k != "objects"}}
            self.anomalies.append(self.anomaly)
            self.fit_reference = self.fit
            self.model_status = "invalidated"
            # fail toward cooling while the agent investigates
            self.rig.set_fan(1.0)
            self._log("anomaly", self.anomaly)
            result["anomaly"] = self.anomaly
            result["fallback"] = "fan set to 100% to protect the target while you investigate"
        if self.hold_done_s >= self.goal.hold_s - 1e-6:
            result["goal_complete"] = True
        self._log("plan_result", result)
        self._status()
        return result

    def set_idle(self, fan_duty: float, heater_on: bool, seconds: float, rationale: str) -> dict:
        """Hold a fixed state without an experiment (e.g. let the rig settle)."""
        if not 0 <= fan_duty <= 1 or seconds > 600 or seconds < 5:
            return {"refused": "fan_duty 0..1 and 5..600 s"}
        self.rig.set_fan(fan_duty)
        self.rig.set_heater(heater_on and self.rig.caps.has_heater)
        self._log("idle", {"fan_duty": fan_duty, "heater_on": heater_on, "seconds": seconds, "rationale": rationale})
        st = self._run(seconds, "idle", None)
        return {"status": st, **self.observe()}

    def finish(self, summary: str) -> dict:
        self.done = True
        self.rig.set_heater(False)
        self.rig.set_fan(0.4)
        verdict = {
            "summary": summary,
            "hold_done_s": round(self.hold_done_s, 1), "hold_compliant_s": round(self.hold_ok_s, 1),
            "compliance": round(self.hold_ok_s / self.hold_done_s, 3) if self.hold_done_s else None,
            "energy_J": {k: round(v, 1) for k, v in self.energy.items()},
            "experiments": len(self.experiments), "anomalies": len(self.anomalies),
            "hypotheses": {h["id"]: h["status"] for h in self.hyps.values()},
            "final_model": self.fit.to_json(),
        }
        self._log("run_end", verdict)
        self._status()
        if self._csv:
            self._csv.close()
            self._csv = None
        return verdict


# ----------------------------------------------------------------- helpers

def compare_scenes(ref: dict, cur: dict) -> dict:
    def find(res, label):
        for o in res.get("objects", []):
            if o["label"] == label:
                return o
        return None

    W, H = cur.get("image_size") or [640, 400]
    diag = math.hypot(W, H)
    out = {"changed_vs_reference": False, "changes": []}
    for label in ("fan", "heatsink"):
        a, b = find(ref, label), find(cur, label)
        if a is None or b is None:
            if a is not None and b is None:
                out["changes"].append(f"{label} no longer detected")
                out["changed_vs_reference"] = True
            continue
        ca = ((a["box"][0] + a["box"][2]) / 2, (a["box"][1] + a["box"][3]) / 2)
        cb = ((b["box"][0] + b["box"][2]) / 2, (b["box"][1] + b["box"][3]) / 2)
        shift = math.hypot(cb[0] - ca[0], cb[1] - ca[1]) / diag
        wa, ha = a["box"][2] - a["box"][0], a["box"][3] - a["box"][1]
        wb, hb = b["box"][2] - b["box"][0], b["box"][3] - b["box"][1]
        shape = abs(math.log(max(wb, 1) / max(hb, 1)) - math.log(max(wa, 1) / max(ha, 1)))
        entry = {"object": label, "centre_shift_pct_of_diag": round(shift * 100, 1),
                 "box_aspect_change": round(shape, 2)}
        out[f"{label}_motion"] = entry
        if shift > 0.04 or shape > 0.35:
            out["changed_vs_reference"] = True
            out["changes"].append(f"{label} moved {shift * 100:.1f}% of frame diagonal"
                                  + (f", box shape changed (rotation?)" if shape > 0.35 else ""))
    f_ref, s_ref, f_cur, s_cur = find(ref, "fan"), find(ref, "heatsink"), find(cur, "fan"), find(cur, "heatsink")
    if all((f_ref, s_ref, f_cur, s_cur)):
        def cdist(f, s):
            return math.hypot((f["box"][0] + f["box"][2] - s["box"][0] - s["box"][2]) / 2,
                              (f["box"][1] + f["box"][3] - s["box"][1] - s["box"][3]) / 2)
        out["fan_to_heatsink_distance_px"] = [round(cdist(f_ref, s_ref)), round(cdist(f_cur, s_cur))]
    if ref.get("aim") and cur.get("aim"):
        out["aim_reference_vs_now"] = [ref["aim"], cur["aim"]]
    return out


def plan_constant_then_hold(fit: M.Fit, s: dict, heater_w: float, goal: Goal, remaining_hold: float,
                            fan_power, robust: bool = True, S: int = 300) -> dict:
    """Pick the cheapest two-phase plan (boost, then hold) whose 95th-percentile
    temperature stays under target for the hold window. robust=False plans on
    the mean parameters only, which shows what certainty would be worth."""
    rng = np.random.default_rng(11)
    if robust:
        P = fit.sample(S, rng)
    else:
        P = {n: np.array([v]) for n, v in fit.params().items()}
    Ta, T0 = s["T_amb"], s["T_obj"]
    target = goal.target_C
    q = heater_w
    # 1) cheapest hold duty with robust steady state under target
    u_hold = None
    for u in np.round(np.arange(0, 1.0001, 0.01), 2):
        k = np.maximum(M.cooling_rate(fit.structure, P, u), 1e-7)
        Tss = Ta + P["b"] * q / k
        if np.percentile(Tss, 95) <= target - 0.1:
            u_hold = float(u)
            break
    feasible = u_hold is not None
    if u_hold is None:
        u_hold = 1.0
    horizon = goal.settle_s + remaining_hold
    best = None
    for ub in sorted({u_hold, 0.6, 0.8, 1.0}):
        if ub < u_hold:
            continue
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            tb = round(goal.settle_s * frac / 5) * 5
            if ub == u_hold and tb > 0:
                continue
            phases = ([{"fan_duty": ub, "duration_s": tb}] if tb > 0 else []) + \
                     [{"fan_duty": u_hold, "duration_s": horizon - tb}]
            steps = [{"fan_duty": p["fan_duty"], "heater_on": True, "duration_s": p["duration_s"]} for p in phases]
            dt, u, qq, TaA = M.schedule_arrays(steps, q, Ta)
            sims = M.simulate_many(fit.structure, P, T0, dt, u, qq, TaA)
            t = np.concatenate([[0], np.cumsum(dt)])
            hold = t >= goal.settle_s
            p95 = np.percentile(sims[:, hold], 95, axis=0) if robust else sims[0, hold]
            ok = bool(np.all(p95 <= target + goal.tolerance_K))
            E = float(np.sum(fan_power(u) * dt))
            cand = (not ok, E)
            if best is None or cand < best[0]:
                best = (cand, phases, sims, dt, E, p95)
    (_, phases, sims, dt, E, p95) = best
    t0 = s["t"]
    pred = M.Prediction(t=t0 + np.concatenate([[0], np.cumsum(dt)]), mean=sims.mean(0),
                        lo=np.percentile(sims, 5, 0) - 0.12, hi=np.percentile(sims, 95, 0) + 0.12,
                        sd=sims.std(0))
    return {"phases": phases, "feasible": feasible and not best[0][0], "energy_J": E,
            "hold_max_p95": float(np.max(p95)), "hold_med": float(np.median(sims[:, -1])), "pred": pred}
