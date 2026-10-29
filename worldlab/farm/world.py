"""The hidden farm: what is really true, and what the agent can observe or do.

Hidden from the agent: the local varieties' true traits, each drip system's
real delivery efficiency, this year's weather beyond a short forecast, and
any faults (a clogged drip line, a pest outbreak, groundwater turning saltier).

Observable: a weather station, soil-moisture and soil-salinity (EC) sensors in
three layers per field, the irrigation water meter (what was pumped, not what reached the
roots), drone imagery, harvest weights, and field tests on request
(emitter flow test, soil sample, water test, leaf inspection).
"""
from __future__ import annotations

import math
import threading

import numpy as np

from . import weather as WX
from .crops import CROPS, TRAITS, TRAIT_IDS, nutrients_per_ha
from .sim import Sim, crop_arrays, soil_arrays, LEACH_FRACTION, DRIP_EFF_NOMINAL, PRE_IRRIGATION_MM
from ..pngio import encode_png

FIELDS = [
    {"id": "F1", "name": "North",      "layers": ["loamy_sand"] * 3,                     "ece": [2.0, 2.5, 3.0], "soil_n": 25, "theta0": 0.4},
    {"id": "F2", "name": "Palm edge",  "layers": ["sandy_loam"] * 3,                     "ece": [1.5, 2.0, 2.5], "soil_n": 40, "theta0": 0.5},
    {"id": "F3", "name": "Dune",       "layers": ["sand"] * 3,                           "ece": [1.0, 1.5, 2.0], "soil_n": 15, "theta0": 0.3},
    {"id": "F4", "name": "Old wadi",   "layers": ["sandy_loam", "sandy_loam", "loam"],   "ece": [5.0, 6.0, 7.0], "soil_n": 35, "theta0": 0.5},
    {"id": "F5", "name": "Loam block", "layers": ["loam"] * 3,                           "ece": [3.0, 3.5, 4.0], "soil_n": 50, "theta0": 0.5},
    {"id": "F6", "name": "Sabkha rim", "layers": ["loamy_sand", "loamy_sand", "sandy_loam"], "ece": [7.0, 8.0, 9.0], "soil_n": 20, "theta0": 0.4},
]
FIELD_HA = 2.0
TRIAL_FIELD = {"id": "T", "name": "Trial plots", "layers": ["sandy_loam"] * 3, "ece": [2.5, 3.0, 3.5], "soil_n": 30, "theta0": 0.5}
TRIAL_PLOTS = {
    "normal": TRIAL_FIELD,
    "saline": {"id": "TS", "name": "Saline trial plots", "layers": ["sandy_loam"] * 3, "ece": [7.5, 8.5, 9.5], "soil_n": 30, "theta0": 0.5},
}
TRIAL_PLOT_HA = 0.01
EC_GROUNDWATER = 4.5


class Farm:
    def __init__(self, seed: int = 7, randomize_traits: bool = True):
        self.seed = seed
        r = np.random.default_rng(seed)
        self.rng = np.random.default_rng(seed + 1000)
        # true local-variety traits (hidden)
        self.traits = {}
        for c in CROPS:
            t = {}
            for k, spec in TRAITS.items():
                v = r.normal(spec["prior"], spec["sd"]) if randomize_traits else spec["prior"]
                t[k] = float(np.clip(v, spec["lo"] * 0.9 if spec["lo"] > 0 else spec["lo"], spec["hi"]))
            self.traits[c] = t
        self.eff = r.uniform(0.84, 0.95, len(FIELDS))      # true drip efficiency per field (hidden)
        self.ecgw_base = EC_GROUNDWATER
        self.trial_seed = seed * 100 + 1
        self.year_wx = WX.generate(1, seed * 7 + 3)        # this season's actual weather (hidden ahead)
        self.lock = threading.RLock()
        self.sim: Sim | None = None
        self.plan = None
        self.day = 0
        self.events: list[dict] = []
        self.scheduled: list[tuple[int, str, dict]] = []
        self.on_event = None
        self.repairs: list[dict] = []

    # ------------------------------------------------------------ trials
    def run_trials(self, trials: list[dict]) -> dict:
        """Run trial plots for one season (a previous year). Each trial:
        {crop, sow, density, irr, desal, nfert, mulch}. Returns observations."""
        wx = WX.generate(1, self.trial_seed)
        self.trial_seed += 1
        crops = [t["crop"] for t in trials]
        traits = {k: np.array([self.traits[c][k] for c in crops]) for k in TRAIT_IDS}
        mg = {k: np.array([float(t[k]) for t in trials]) for k in ("sow", "density", "irr", "desal", "nfert", "mulch")}
        soil = soil_arrays([TRIAL_PLOTS[t.get("plot", "normal")] for t in trials])
        sim = Sim(crop_arrays(crops, traits), mg, soil, wx, np.zeros(len(trials), int),
                  np.full(len(trials), self.ecgw_base), eff=0.9, record=True).run()
        tr = sim.traces()
        n = self.rng
        days = np.arange(7, WX.SEASON_DAYS, 7)
        obs = []
        for i, t in enumerate(trials):
            cc = np.clip(tr["cc"][i, days] + n.normal(0, 0.025, len(days)), 0, 1)
            theta = tr["theta"][i][days] + n.normal(0, 0.008, (len(days), 3))
            y = float(sim.fresh_yield()[i] * n.lognormal(0, 0.04))
            obs.append({"trial": t, "days": days.tolist(), "cc_obs": cc.round(3).tolist(),
                        "theta_obs": theta.round(3).tolist(), "yield_t_ha": round(y, 3),
                        "harvest_day": int(sim.harvest_day[i]),
                        "water_m3_ha": round(float(sim.water_m3_ha()[i]), 1)})
        return {"weather": {k: wx[k][0] for k in ("tmax", "tmin", "rh", "u2", "rs", "rain", "et0", "doy")},
                "plots": obs}

    # --------------------------------------------------------- production
    def start_season(self, plan: list[dict]):
        """plan: one dict per field {crop or None, sow, density, irr, desal, nfert, mulch}."""
        with self.lock:
            self.plan = plan
            crops = [p["crop"] for p in plan]
            traits = {k: np.array([self.traits[c][k] if c else 0.0 for c in crops]) for k in TRAIT_IDS}
            mg = {k: np.array([float(p[k]) for p in plan]) for k in ("sow", "density", "irr", "desal", "nfert", "mulch")}
            D = WX.SEASON_DAYS
            self.deliver = np.ones((len(FIELDS), D))
            self.pest = np.zeros((len(FIELDS), D))
            self.ecgw = np.full((len(FIELDS), D), self.ecgw_base)
            self.sim = Sim(crop_arrays(crops, traits), mg, soil_arrays(FIELDS), self.year_wx,
                           np.zeros(len(FIELDS), int), self.ecgw, eff=self.eff,
                           deliver=self.deliver, pest=self.pest, record=True)
            self.day = 0

    def step(self, gross_mm: np.ndarray) -> dict:
        """Advance one day with the controller's commanded irrigation."""
        with self.lock:
            for at, kind, kw in list(self.scheduled):
                if self.day >= at:
                    self.scheduled.remove((at, kind, kw))
                    self.perturb(kind, **kw)
            d = self.day
            self.sim.step(gross_mm)
            self.day += 1
            n = self.rng
            theta = self.sim.W / self.sim.th + n.normal(0, 0.008, (len(FIELDS), 3))
            ece = self.sim.ece_layers() * n.lognormal(0, 0.08, (len(FIELDS), 3))
            wx = {k: float(self.year_wx[k][0, d]) for k in ("tmax", "tmin", "rh", "u2", "rs", "rain", "et0")}
            return {"day": d, "weather": wx, "theta": np.clip(theta, 0.01, 0.5), "ece": ece,
                    "harvested": self.sim.done.copy(), "harvest_day": self.sim.harvest_day.copy()}

    def forecast(self, days: int = 7) -> dict:
        """Short forecast: the coming days with forecast error growing with lead time."""
        d0 = self.day
        d1 = min(d0 + days, WX.SEASON_DAYS)
        lead = np.arange(1, d1 - d0 + 1)
        err = self.rng.normal(0, 1, len(lead)) * 0.6 * np.sqrt(lead)
        return {"days": list(range(d0, d1)),
                "tmax": (self.year_wx["tmax"][0, d0:d1] + err).round(1).tolist(),
                "et0": (self.year_wx["et0"][0, d0:d1] * (1 + 0.04 * err)).round(2).tolist(),
                "rain": self.year_wx["rain"][0, d0:d1].round(1).tolist()}

    def drone(self, f: int) -> dict:
        with self.lock:
            cc = float(np.clip(self.sim.cc[f] + self.rng.normal(0, 0.025), 0, 1))
            return {"cc": round(cc, 3), "frac": float(min(self.sim.frac()[f], 1.0)),
                    "harvested": bool(self.sim.done[f])}

    def field_test(self, f: int, kind: str) -> dict:
        with self.lock:
            d = max(self.day - 1, 0)
            if kind == "emitter_flow":
                v = self.eff[f] * self.deliver[f, d] / DRIP_EFF_NOMINAL
                return {"test": kind, "delivered_vs_design": round(float(v * self.rng.normal(1, 0.03)), 3),
                        "note": "catch-can test along three drip lines; 1.0 = emitters deliver the design flow"}
            if kind == "soil_sample":
                ece = self.sim.ece_layers()[f] * self.rng.normal(1, 0.05, 3)
                return {"test": kind, "ece_dS_m_by_layer": ece.round(2).tolist(), "layers_cm": ["0-20", "20-50", "50-100"]}
            if kind == "water_test":
                return {"test": kind, "groundwater_ec_dS_m": round(float(self.ecgw[f, d] * self.rng.normal(1, 0.02)), 2)}
            if kind == "leaf_inspection":
                p = float(self.pest[f, d])
                return {"test": kind, "pest_damage_seen": bool(p > 0.004),
                        "severity": "heavy" if p > 0.02 else ("light" if p > 0.004 else "none"),
                        "insects_per_leaf": round(float(p * 400 * self.rng.uniform(0.7, 1.3)), 1)}
            raise ValueError(kind)

    # --------------------------------------------------------- actions
    def set_management(self, f: int, **kw):
        with self.lock:
            for k, v in kw.items():
                self.sim.m[k][f] = float(v)

    def repair_drip(self, f: int) -> dict:
        with self.lock:
            fixed = bool(self.deliver[f, self.day - 1] < 0.95) if self.day else False
            self.deliver[f, self.day:] = 1.0
            self.repairs.append({"field": FIELDS[f]["id"], "day": self.day, "was_faulty": fixed})
            return {"repaired": True, "found_clogged_emitters": fixed}

    def pest_control(self, f: int) -> dict:
        with self.lock:
            had = bool(self.pest[f, self.day - 1] > 0.004) if self.day else False
            self.pest[f, self.day:] = np.minimum(self.pest[f, self.day:], 0.001)
            return {"treated": True, "pests_present": had}

    # --------------------------------------------------------- perturbations
    def perturb(self, kind: str, field: int | None = None) -> dict:
        """A change in the world the agent is not told about."""
        with self.lock:
            d = self.day
            sown = [i for i, p in enumerate(self.plan or []) if p["crop"] and d >= p["sow"] and not self.sim.done[i]]
            f = field if field is not None else (sown[len(sown) // 2] if sown else 2)
            if kind == "clog":
                self.deliver[f, d:] = 0.45
                info = {"kind": kind, "field": FIELDS[f]["id"], "note": "drip emitters clogged: 45% of water delivered (hidden)"}
            elif kind == "pest":
                self.pest[f, d:] = 0.03
                info = {"kind": kind, "field": FIELDS[f]["id"], "note": "pest outbreak eating 3% of the canopy a day"}
            elif kind == "salinity":
                self.ecgw[:, d:] = 9.0
                info = {"kind": kind, "field": "all", "note": "groundwater salinity rises from 4.5 to 9 dS/m (hidden)"}
            elif kind == "heatwave":
                WX.heat_wave_inject(self.year_wx, 0, min(d + 3, WX.SEASON_DAYS - 1), 6, 6.5)
                info = {"kind": kind, "field": "all", "note": "a heat wave arrives in 3 days (in the forecast)"}
            else:
                raise ValueError(kind)
            info["day"] = d
            self.events.append(info)
        if self.on_event:
            self.on_event(info)
        return info

    def schedule(self, kind: str, day: int, **kw):
        self.scheduled.append((int(day), kind, kw))

    def world_state(self) -> list[dict]:
        """What a camera would show, for the 3D view only (never given to the agent)."""
        with self.lock:
            s = self.sim
            if s is None:
                return []
            d = max(self.day - 1, 0)
            frac = np.clip(s.frac(), 0, 1)
            ece = s.ece_layers()[:, 0]
            out = []
            for i, p in enumerate(self.plan or []):
                out.append({"crop": p["crop"], "cc": round(float(s.cc[i]), 3), "stage": round(float(frac[i]), 3),
                            "stand": round(float(s.stand[i]), 3), "ksw": round(float(s.ks_w[i]), 3),
                            "ece_top": round(float(ece[i]), 2), "deliver": round(float(self.deliver[i, d]), 2),
                            "pest": round(float(self.pest[i, d]), 3), "done": bool(s.done[i]),
                            "theta_top": round(float((s.W / s.th)[i, 0]), 3),
                            "sown": bool(p["crop"]) and self.day >= p["sow"]})
            return out

    def truth(self) -> dict:
        return {"traits": self.traits, "eff": self.eff.round(3).tolist(), "events": self.events}

    # --------------------------------------------------------- imagery
    def image(self, f: int) -> bytes:
        with self.lock:
            s = self.sim
            crop = self.plan[f]["crop"] if self.plan else None
            cc = float(s.cc[f]) if s else 0.0
            stand = float(s.stand[f]) if s else 1.0
            ksw = float(s.ks_w[f]) if s else 1.0
            ece_top = float(s.ece_layers()[f, 0]) if s else 2.0
            pest = float(self.pest[f, max(self.day - 1, 0)]) if s else 0.0
            done = bool(s.done[f]) if s else False
        return encode_png(render_field(crop, cc, stand, ksw, ece_top, pest, done, seed=f * 31 + 5))


# ---------------------------------------------------------------- renderer
IW, IH = 640, 400
_YY, _XX = np.mgrid[0:IH, 0:IW].astype(np.float32)


def render_field(crop, cc, stand, ksw, ece_top, pest, done, seed=1) -> np.ndarray:
    """Top-down drone view: sandy soil, drip lines, plants sized by canopy cover,
    yellowing with drought, white salt crust, brown pest damage, gaps for lost plants."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 6, (IH, IW, 1))
    base = np.array([196, 164, 118], np.float32)
    img = (base + noise + 8 * np.sin(_XX[..., None] * 0.02 + _YY[..., None] * 0.013)).astype(np.float32)
    # salt crust patches
    if ece_top > 5:
        k = min((ece_top - 5) / 8, 1.0)
        for _ in range(int(14 * k) + 1):
            cx, cy, r = rng.uniform(0, IW), rng.uniform(0, IH), rng.uniform(15, 45)
            m = (_XX - cx) ** 2 + (_YY - cy) ** 2 < r * r
            img[m] = img[m] * (1 - 0.55 * k) + np.array([238, 236, 228]) * 0.55 * k
    rows = np.arange(30, IH, 42)
    for ry in rows:  # drip lines
        img[(np.abs(_YY - ry - 12) < 1.2)] = [40, 40, 44]
    if crop is None or cc <= 0.005 or done:
        if done and crop:
            for ry in rows:
                for px in np.arange(20, IW, 36):
                    m = ((_XX - px) ** 2 / 9 + (_YY - ry) ** 2 / 4) < 6
                    img[m] = [150, 128, 90]
        return np.clip(img, 0, 255).astype(np.uint8)
    leafy = crop in ("potato", "sweet_potato", "cassava", "beans", "soybean")
    green = np.array([58, 128, 52], np.float32)
    yellow = np.array([170, 165, 70], np.float32)
    stress = float(np.clip(1 - ksw, 0, 1))
    col = green * (1 - 0.8 * stress) + yellow * 0.8 * stress
    radius = 4 + 17 * math.sqrt(cc)
    spacing = 36
    for ry in rows:
        for px in np.arange(20, IW, spacing):
            if rng.random() > stand:
                continue
            jx, jy = rng.normal(0, 2, 2)
            cx, cy = px + jx, ry + jy
            if leafy:
                m = (_XX - cx) ** 2 + (_YY - cy) ** 2 < radius ** 2
            else:
                m = ((_XX - cx) ** 2 / (radius * 0.55) ** 2 + (_YY - cy) ** 2 / (radius * 1.0) ** 2) < 1
            shade = rng.uniform(0.85, 1.1)
            img[m] = col * shade
            if pest > 0.004 and rng.random() < 0.6:
                for _ in range(3):
                    sx, sy = cx + rng.normal(0, radius / 2.5), cy + rng.normal(0, radius / 2.5)
                    mm = (_XX - sx) ** 2 + (_YY - sy) ** 2 < (radius * 0.28) ** 2
                    img[mm & m] = [112, 74, 40]
    return np.clip(img, 0, 255).astype(np.uint8)
