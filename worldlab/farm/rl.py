"""Reinforcement learning: a daily irrigation and water-blend policy, trained
inside the agent's own learned model of the farm.

Method: evolution strategies (Salimans et al., 2017) with antithetic
sampling, centred-rank fitness shaping and Adam. ES suits this simulator:
thousands of field-seasons run in one vectorised batch, and no gradients
through the crop model are needed.

What is learned: one small neural network shared by all fields. Every day,
for every planted field, it reads only what the farm's sensors show (crop
stage, drone canopy cover, soil moisture and salinity in the top 50 cm,
yesterday's ET0, the farm's water and energy use so far against the quota,
the crop's published characteristics, the plan's settings) and outputs
  - an irrigation multiplier on the plan's drip schedule (0.55x to 1.8x)
  - a change to the desalinated-water fraction (plus or minus 0.5)
At initialisation the network outputs exactly the plan (multiplier 1, no
change), so training starts from the rule-based controller and moves away
from it only where the model says that pays.

Where it is learned: entirely in imagination. Each episode is a whole farm
season whose crop traits are drawn from the agent's calibrated beliefs and
whose weather is drawn from the stochastic climate, never from the hidden
farm (model-based RL with domain randomisation). The trained policy is then
deployed on the real farm through the same sensors.

Reward per farm-season: people fed (the scarcest of calories, protein and
vitamin A across all fields), minus steep penalties for going over the water
quota or the energy budget, plus a small credit for water and energy left
unused.
"""
from __future__ import annotations

import math

import numpy as np

from . import weather as WX
from .crops import CROPS, NEEDS, NUTRIENTS, TRAIT_IDS
from .sim import Sim, crop_arrays, soil_arrays, DRIP_EFF_NOMINAL, cap_to_budget
from .world import FIELDS, FIELD_HA, EC_GROUNDWATER

D = WX.SEASON_DAYS
FEATURES = ["sown", "stage", "canopy", "moisture_rel", "salinity_rel", "et0", "days_left",
            "water_used", "energy_used", "kcb", "p", "salt_slope", "salt_thr", "ec_groundwater",
            "plan_irr", "plan_desal", "bias"]
K = len(FEATURES)
HIDDEN = 16
N_PARAMS = K * HIDDEN + HIDDEN + HIDDEN * 2 + 2
MULT_RANGE = 0.6          # irrigation multiplier = exp(0.6 * out), out in [-1, 1] -> 0.55 .. 1.82
DESAL_RANGE = 0.5
PENALTY_WATER = 0.05      # people per m3 over quota (about 6x the farm's average water productivity)
PENALTY_ENERGY = 0.02     # people per kWh over budget
CREDIT_WATER = 0.0005     # people per m3 left unused
CREDIT_ENERGY = 0.0002


def unpack(theta: np.ndarray):
    i = 0
    W1 = theta[..., i:i + K * HIDDEN].reshape(theta.shape[:-1] + (K, HIDDEN)); i += K * HIDDEN
    b1 = theta[..., i:i + HIDDEN]; i += HIDDEN
    W2 = theta[..., i:i + HIDDEN * 2].reshape(theta.shape[:-1] + (HIDDEN, 2)); i += HIDDEN * 2
    b2 = theta[..., i:i + 2]
    return W1, b1, W2, b2


def init_params(seed: int = 0) -> np.ndarray:
    """Random first layer, zero output layer: the initial policy is exactly the plan."""
    r = np.random.default_rng(seed)
    th = np.zeros(N_PARAMS)
    th[:K * HIDDEN] = r.normal(0, 1 / math.sqrt(K), K * HIDDEN)
    return th


def forward(theta_groups: np.ndarray, obs: np.ndarray) -> np.ndarray:
    """theta_groups (P, N_PARAMS), obs (P, E, K) -> outputs (P, E, 2) in [-1, 1]."""
    W1, b1, W2, b2 = unpack(theta_groups)
    h = np.tanh(np.einsum("pek,pkh->peh", obs, W1) + b1[:, None, :])
    return np.tanh(np.einsum("peh,pho->peo", h, W2) + b2[:, None, :])


def actions(out: np.ndarray, plan_desal: np.ndarray):
    mult = np.exp(MULT_RANGE * out[..., 0])
    desal = np.clip(plan_desal + DESAL_RANGE * out[..., 1], 0.0, 1.0)
    return mult, desal


def build_obs(d, frac, cc, rel, ece, et0, water_frac, energy_frac, meta) -> np.ndarray:
    B = len(frac)
    sown = (d >= meta["sow"]).astype(float)
    return np.stack([
        sown, np.clip(frac, 0, 1) * sown, np.clip(cc, 0, 1), np.clip(rel, -0.5, 2.0),
        np.clip(ece / meta["salt_thr"], 0, 6) / 3.0, et0 / 10.0, np.full(B, (D - d) / D),
        np.clip(water_frac, 0, 1.5), np.clip(energy_frac, 0, 1.5),
        meta["kcb"], meta["p"], meta["slope"] / 20.0, meta["salt_thr"] / 10.0,
        meta["ecgw"] / 10.0, meta["plan_irr"], meta["plan_desal"], np.ones(B)], axis=1)


def crop_meta(fields_plan: list[dict], beliefs: dict, ecgw) -> dict:
    """Per-field published crop features, with the agent's belief about salt tolerance."""
    keys = ("sow", "kcb", "p", "slope", "salt_thr", "plan_irr", "plan_desal", "ecgw")
    m = {k: [] for k in keys}
    ecgw = np.broadcast_to(np.asarray(ecgw, float), (len(fields_plan),))
    for f, e in zip(fields_plan, ecgw):
        c = CROPS[f["crop"]]
        m["sow"].append(f["sow"])
        m["kcb"].append(c["kcb"])
        m["p"].append(c["p"])
        m["slope"].append(c["slope"])
        shift = float(beliefs[f["crop"]].mean[TRAIT_IDS.index("salt")]) if beliefs else 0.0
        m["salt_thr"].append(max(c["salt"] + shift, 0.3))
        m["plan_irr"].append(f["irr"])
        m["plan_desal"].append(f["desal"])
        m["ecgw"].append(e)
    return {k: np.array(v, float) for k, v in m.items()}


def moisture_rel(theta_top2: np.ndarray, field_idx: list[int]) -> np.ndarray:
    """Relative available water (0 = wilting point, 1 = field capacity), top two layers."""
    sa = soil_arrays([FIELDS[i] for i in field_idx])
    wpt, fc = sa["wpt"][:, :2], sa["fc"][:, :2]
    return ((theta_top2 - wpt) / np.maximum(fc - wpt, 1e-6)).mean(-1)


class Envs:
    """A batch of imagined farm seasons: the planted fields of the plan, each
    with E samples of (crop traits from the agent's beliefs, a weather year).
    Ordering is field-major, so (P*F*E) reshapes to (P, F, E)."""

    def __init__(self, fields_plan: list[dict], field_idx: list[int], beliefs: dict, per_field: int, seed: int,
                 quota_m3: float, energy_kwh: float, ecgw: float = EC_GROUNDWATER, hard_budget: bool = True):
        rng = np.random.default_rng(seed)
        self.F = len(fields_plan)
        self.E = per_field
        self.field_idx = list(field_idx)
        self.quota, self.energy = float(quota_m3), float(energy_kwh)
        self.hard_budget = bool(hard_budget)
        self.wx = WX.generate(per_field, seed)
        crops, traits = [], {k: [] for k in TRAIT_IDS}
        mg = {k: [] for k in ("sow", "density", "irr", "desal", "nfert", "mulch")}
        soils, widx, rows = [], [], []
        for f, fi in zip(fields_plan, field_idx):
            smp = beliefs[f["crop"]].sample(per_field, rng)
            crops += [f["crop"]] * per_field
            for k in TRAIT_IDS:
                traits[k].append(smp[k])
            for k in mg:
                mg[k] += [float(f[k])] * per_field
            soils += [FIELDS[fi]] * per_field
            rows += [fi] * per_field
            widx += list(range(per_field))
        self.crops = crops
        self.rows = rows
        self.traits = {k: np.concatenate(v) for k, v in traits.items()}
        self.mg = {k: np.array(v) for k, v in mg.items()}
        self.soils = soils
        self.widx = np.array(widx)
        meta = crop_meta(fields_plan, beliefs, ecgw)
        self.meta = {k: np.repeat(v, per_field) for k, v in meta.items()}
        self.ecgw = ecgw
        self.size = len(crops)
        self.nut = np.array([[CROPS[c][k] for k in ("kcal", "prot", "vita")] for c in crops])  # per kg fresh
        self.need = np.array([NEEDS[n] * 365.0 for n in NUTRIENTS])

    def sim(self, P: int) -> Sim:
        rep = lambda a: np.tile(a, P)
        mg = {k: rep(v) for k, v in self.mg.items()}
        return Sim(crop_arrays(self.crops * P, {k: rep(v) for k, v in self.traits.items()}), mg,
                   soil_arrays(self.soils * P), self.wx, rep(self.widx), np.full(self.size * P, self.ecgw),
                   eff=DRIP_EFF_NOMINAL)

    def farm_people(self, y: np.ndarray, P: int) -> np.ndarray:
        """y (P*F*E,) fresh t/ha -> people fed per (P, E): the scarcest nutrient across fields."""
        tot = (y[:, None] * 1000 * FIELD_HA * np.tile(self.nut, (P, 1))).reshape(P, self.F, self.E, 3).sum(1)
        return (tot / self.need).min(-1)


def rollout(envs: Envs, thetas: np.ndarray, seed: int = 0) -> dict:
    """Run every policy in `thetas` (P, N_PARAMS) through every imagined season."""
    P, F, E = len(thetas), envs.F, envs.E
    sim = envs.sim(P)
    rng = np.random.default_rng(seed)
    meta = {k: np.tile(v, P) for k, v in envs.meta.items()}
    wpt, fc = sim.s["wpt"][:, :2], sim.s["fc"][:, :2]
    vol = 10 * FIELD_HA
    spread = lambda farm: np.broadcast_to(farm[:, None, :], (P, F, E)).reshape(-1)
    mults, desals = [], []
    for d in range(D):
        cc = sim.cc + rng.normal(0, 0.02, sim.B)                                  # drone noise
        theta = (sim.W / sim.th)[:, :2] + rng.normal(0, 0.008, (sim.B, 2))       # probe noise
        rel = ((theta - wpt) / np.maximum(fc - wpt, 1e-6)).mean(1)
        ece = sim.ece_layers()[:, :2].mean(1) * rng.lognormal(0, 0.08, sim.B)     # EC sensor noise
        et0 = sim.wx["et0"][sim.widx, max(d - 1, 0)]
        wfrac = spread((sim.gross_mm * vol).reshape(P, F, E).sum(1)) / envs.quota
        efrac = spread((sim.kwh_ha * FIELD_HA).reshape(P, F, E).sum(1)) / envs.energy
        obs = build_obs(d, sim.frac(), cc, rel, ece, et0, wfrac, efrac, meta).reshape(P, F * E, K)
        mult, desal = actions(forward(thetas, obs).reshape(P * F * E, 2), meta["plan_desal"])
        sim.m["desal"] = desal
        base = sim.irrigation_demand(d)
        g = base * mult
        if envs.hard_budget:          # the same actuator cap as the real farm, per imagined farm-season
            used_w = (sim.gross_mm * vol).reshape(P, F, E).sum(1)
            used_e = (sim.kwh_ha * FIELD_HA).reshape(P, F, E).sum(1)
            gf = g.reshape(P, F, E).transpose(0, 2, 1)
            df = np.broadcast_to(desal, g.shape).reshape(P, F, E).transpose(0, 2, 1)
            gf, _ = cap_to_budget(gf, df, envs.quota - used_w, envs.energy - used_e, FIELD_HA)
            g = gf.transpose(0, 2, 1).reshape(-1)
        sim.step(g)
        if d % 7 == 0:
            w = (base > 0).astype(float).reshape(P, -1)
            mults.append((mult.reshape(P, -1) * w).sum(1) / np.maximum(w.sum(1), 1))
            desals.append((desal.reshape(P, -1) * w).sum(1) / np.maximum(w.sum(1), 1))
    people = envs.farm_people(sim.fresh_yield(), P)
    water = (sim.gross_mm * vol).reshape(P, F, E).sum(1)
    kwh = (sim.kwh_ha * FIELD_HA).reshape(P, F, E).sum(1)
    reward = (people
              - PENALTY_WATER * np.maximum(water - envs.quota, 0) - PENALTY_ENERGY * np.maximum(kwh - envs.energy, 0)
              + CREDIT_WATER * np.maximum(envs.quota - water, 0) + CREDIT_ENERGY * np.maximum(envs.energy - kwh, 0))
    return {"reward": reward, "people": people, "water": water, "kwh": kwh,
            "mult_trace": np.array(mults).T, "desal_trace": np.array(desals).T}


def centred_ranks(x: np.ndarray) -> np.ndarray:
    r = np.empty(len(x))
    r[np.argsort(x)] = np.arange(len(x))
    return r / (len(x) - 1) - 0.5


def train(envs: Envs, iters: int = 50, pairs: int = 32, sigma: float = 0.05, lr: float = 0.01,
          seed: int = 0, callback=None, val_envs: Envs | None = None, val_every: int = 10) -> dict:
    """Evolution strategies with antithetic pairs, centred ranks and Adam. Each
    iteration scores 2*pairs perturbed policies plus the current one on the
    same imagined seasons (common random numbers).

    With `val_envs`, the current policy is scored every `val_every` iterations
    on held-out imagined seasons, and the best checkpoint is returned. The
    plan's own rule (all-zero policy) is checkpoint zero, so the result is
    never worse than the rule on the validation seasons."""
    rng = np.random.default_rng(seed)
    theta = init_params(seed)
    best = {"theta": np.zeros(N_PARAMS), "iter": -1, "val_reward": None}
    val_hist = []
    if val_envs is not None:
        r0 = rollout(val_envs, np.zeros((1, N_PARAMS)), seed=99)
        best["val_reward"] = float(r0["reward"][0].mean())
        val_hist.append({"iter": 0, "val_reward": round(best["val_reward"], 2),
                         "val_people_p10": round(float(np.percentile(r0["people"][0], 10)), 1), "is_rule": True})
    m, v = np.zeros(N_PARAMS), np.zeros(N_PARAMS)
    b1, b2 = 0.9, 0.999
    history = []
    for it in range(iters):
        eps = rng.normal(0, 1, (pairs, N_PARAMS))
        thetas = np.vstack([theta[None], theta + sigma * eps, theta - sigma * eps])
        res = rollout(envs, thetas, seed=seed * 1000 + it)
        R = res["reward"].mean(1)
        fit = centred_ranks(R[1:])
        grad = ((fit[:pairs] - fit[pairs:])[:, None] * eps).sum(0) / (2 * pairs * sigma)
        grad -= 0.005 * theta                                   # weight decay keeps the policy simple
        m = b1 * m + (1 - b1) * grad
        v = b2 * v + (1 - b2) * grad ** 2
        theta = theta + lr * (m / (1 - b1 ** (it + 1))) / (np.sqrt(v / (1 - b2 ** (it + 1))) + 1e-8)
        rec = {"iter": it, "reward": round(float(R[0]), 2), "people": round(float(res["people"][0].mean()), 1),
               "people_p10": round(float(np.percentile(res["people"][0], 10)), 1),
               "water_m3": round(float(res["water"][0].mean())), "energy_kwh": round(float(res["kwh"][0].mean()))}
        if val_envs is not None and ((it + 1) % val_every == 0 or it == iters - 1):
            rv = rollout(val_envs, theta[None], seed=99)
            vr = float(rv["reward"][0].mean())
            rec["val_reward"] = round(vr, 2)
            rec["val_people_p10"] = round(float(np.percentile(rv["people"][0], 10)), 1)
            val_hist.append({"iter": it + 1, "val_reward": rec["val_reward"], "val_people_p10": rec["val_people_p10"]})
            if vr > best["val_reward"]:
                best = {"theta": theta.copy(), "iter": it + 1, "val_reward": vr}
        history.append(rec)
        if callback:
            callback(rec)
    if val_envs is None:
        best = {"theta": theta, "iter": iters, "val_reward": None}
    return {"theta": best["theta"], "best_iter": best["iter"], "history": history, "validation": val_hist}


def compare(envs: Envs, theta: np.ndarray, seed: int = 7) -> dict:
    """The plan's rule controller (zero policy) against the trained policy, on
    the same held-out imagined seasons."""
    res = rollout(envs, np.vstack([np.zeros(N_PARAMS), theta]), seed=seed)

    def summ(i):
        return {"people_mean": round(float(res["people"][i].mean()), 1),
                "people_p10": round(float(np.percentile(res["people"][i], 10)), 1),
                "water_mean_m3": round(float(res["water"][i].mean())),
                "water_p90_m3": round(float(np.percentile(res["water"][i], 90))),
                "energy_mean_kwh": round(float(res["kwh"][i].mean())),
                "energy_p90_kwh": round(float(np.percentile(res["kwh"][i], 90))),
                "years_over_quota_pct": round(100 * float((res["water"][i] > envs.quota * 1.001).mean())),
                "years_at_budget_pct": round(100 * float(((res["water"][i] >= envs.quota * 0.999) |
                                                          (res["kwh"][i] >= envs.energy * 0.999)).mean())),
                "reward": round(float(res["reward"][i].mean()), 2)}
    rule, pol = summ(0), summ(1)
    pct = lambda a, b: round(100 * (a / max(b, 1e-9) - 1), 1)
    return {"rule": rule, "policy": pol,
            "people_p10_change_pct": pct(pol["people_p10"], rule["people_p10"]),
            "people_mean_change_pct": pct(pol["people_mean"], rule["people_mean"]),
            "water_change_pct": pct(pol["water_mean_m3"], rule["water_mean_m3"]),
            "energy_change_pct": pct(pol["energy_mean_kwh"], rule["energy_mean_kwh"]),
            "irrigation_multiplier_by_week": res["mult_trace"][1].round(2).tolist(),
            "desal_fraction_by_week": res["desal_trace"][1].round(2).tolist()}


class Policy:
    """A trained policy, deployed on the real farm's sensor readings."""

    def __init__(self, theta: np.ndarray, meta: dict, field_rows: list[int]):
        self.theta = theta
        self.meta = meta
        self.rows = field_rows          # farm field index for each planted row

    def act(self, d, frac, cc, theta_top2, ece, et0, water_frac, energy_frac):
        n = len(self.rows)
        rel = moisture_rel(theta_top2, self.rows)
        obs = build_obs(d, frac, cc, rel, ece, np.full(n, et0), np.full(n, water_frac), np.full(n, energy_frac), self.meta)
        out = forward(self.theta[None], obs[None])[0]
        return actions(out, self.meta["plan_desal"])
