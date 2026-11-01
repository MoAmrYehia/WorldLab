"""What the agent believes about each crop's local variety, and how it learns.

Each crop has four uncertain traits (water productivity, canopy growth rate,
heat tolerance at flowering, salt tolerance) with a Gaussian belief. Trials
update it by maximum a posteriori fitting of the crop model to the observed
canopy cover (drone, weekly) and harvest yield, with a Laplace approximation
for the posterior covariance. The same Jacobians give the expected
information of a trial before it is run.
"""
from __future__ import annotations

import math

import numpy as np

from .crops import CROPS, TRAITS, TRAIT_IDS
from .sim import Sim, crop_arrays, soil_arrays
from .world import TRIAL_PLOTS, EC_GROUNDWATER, FIELDS
from . import weather as WX

SIG_CC = 0.035          # drone canopy cover noise + model error
SIG_LOGY = 0.08         # harvest weighing noise + model error (log scale)
MG_KEYS = ("sow", "density", "irr", "desal", "nfert", "mulch")
LO = np.array([TRAITS[k]["lo"] for k in TRAIT_IDS])
HI = np.array([TRAITS[k]["hi"] for k in TRAIT_IDS])


class CropBelief:
    def __init__(self, crop: str):
        self.crop = crop
        self.mean = np.array([TRAITS[k]["prior"] for k in TRAIT_IDS], float)
        self.cov = np.diag([TRAITS[k]["sd"] ** 2 for k in TRAIT_IDS])
        self.n_plots = 0
        self.rmse_cc = None
        self.yield_err = None

    def sd(self) -> np.ndarray:
        return np.sqrt(np.clip(np.diag(self.cov), 0, None))

    def sample(self, S: int, rng: np.random.Generator) -> dict:
        x = rng.multivariate_normal(self.mean, self.cov, size=S, method="eigh")
        x = np.clip(x, LO, HI)
        return {k: x[:, i] for i, k in enumerate(TRAIT_IDS)}

    def to_json(self) -> dict:
        sd = self.sd()
        return {"crop": self.crop, "label": CROPS[self.crop]["label"], "plots": self.n_plots,
                "traits": {k: {"mean": round(float(self.mean[i]), 3), "sd": round(float(sd[i]), 3),
                               "prior_sd": TRAITS[k]["sd"]} for i, k in enumerate(TRAIT_IDS)},
                "fit_cc_rmse": self.rmse_cc, "fit_yield_err_pct": self.yield_err}


WX_KEYS = ("tmax", "tmin", "rh", "u2", "rs", "rain", "et0", "doy")


def _stack_wx(wxs: list[dict]) -> dict:
    """Weather years given as 1-D (D,) arrays -> (W, D)."""
    return {k: np.stack([np.ravel(w[k]) for w in wxs]) for k in WX_KEYS}


def predict_trials(crop: str, thetas: np.ndarray, trials: list[dict], wxs: list[dict], record=True):
    """Simulate every trial under every theta row. Returns sim with batch index
    (theta_index * n_trials + trial_index)."""
    K, T = len(thetas), len(trials)
    crops = [crop] * (K * T)
    traits = {k: np.repeat(thetas[:, i], T) for i, k in enumerate(TRAIT_IDS)}
    mg = {k: np.tile(np.array([float(t[k]) for t in trials]), K) for k in MG_KEYS}
    wx = _stack_wx(wxs)
    soils = [TRIAL_PLOTS[t.get("plot", "normal")] for t in trials] * K
    sim = Sim(crop_arrays(crops, traits), mg, soil_arrays(soils), wx,
              np.tile(np.arange(T), K), np.full(K * T, EC_GROUNDWATER), eff=0.9, record=record)
    return sim.run()


def _residuals(sim, K, T, obs: list[dict]):
    tr = sim.traces()["cc"]
    y = sim.fresh_yield()
    out = []
    for k in range(K):
        r = []
        for t in range(T):
            i = k * T + t
            days = np.array(obs[t]["days"])
            r.append((np.array(obs[t]["cc_obs"]) - tr[i, days]) / SIG_CC)
            yo = max(obs[t]["yield_t_ha"], 0.05)
            r.append(np.array([(math.log(yo) - math.log(max(y[i], 0.05))) / SIG_LOGY]))
        out.append(np.concatenate(r))
    return np.stack(out)


def calibrate(belief: CropBelief, prior: tuple[np.ndarray, np.ndarray], trials: list[dict],
              obs: list[dict], wxs: list[dict], iters: int = 12, starts: list[np.ndarray] | None = None) -> dict:
    """MAP fit of the four traits to all trials of this crop: damped Gauss-Newton from several starting points
    (the belief's current mean, the prior mean and any given starts), keeping the fit with the lowest total cost.
    A single start can stall in a poor local optimum: on farm 204 (benchmark v2) one start put sweet potato's salt
    shift at +0.26 dS/m with a cost 13 times higher than near the truth (-1.42), and the plan then trusted it."""
    cands = [belief.mean.copy(), prior[0].copy()] + [np.asarray(x, float).copy() for x in (starts or [])]
    uniq = []
    for c in cands:
        if not any(np.allclose(c, u) for u in uniq):
            uniq.append(c)
    best = None
    for c in uniq:
        b = CropBelief(belief.crop)
        b.mean, b.cov = c, prior[1].copy()
        r = _calibrate_once(b, prior, trials, obs, wxs, iters)
        if best is None or r["cost"] < best[1]["cost"]:
            best = (b, r)
    b, r = best
    belief.mean, belief.cov, belief.n_plots, belief.rmse_cc, belief.yield_err = b.mean, b.cov, b.n_plots, b.rmse_cc, b.yield_err
    r["starts"] = len(uniq)
    return r


def _calibrate_once(belief: CropBelief, prior: tuple[np.ndarray, np.ndarray], trials: list[dict],
                    obs: list[dict], wxs: list[dict], iters: int = 12) -> dict:
    """Damped Gauss-Newton MAP fit from the belief's current mean."""
    mu0, cov0 = prior
    L = np.linalg.cholesky(np.linalg.inv(cov0))
    h = np.array([0.02, 0.03, 0.25, 0.2])
    T = len(trials)

    def evaluate(th):
        thetas = np.vstack([th] + [th + np.eye(4)[i] * h[i] for i in range(4)])
        R = _residuals(predict_trials(belief.crop, thetas, trials, wxs), 5, T, obs)
        return R[0], ((R[1:] - R[0]) / h[:, None]).T

    def total(th, r0):
        rp = L.T @ (th - mu0)
        return float(r0 @ r0 + rp @ rp)

    th = belief.mean.copy()
    r0, J = evaluate(th)
    cost = total(th, r0)
    lam = 1e-2
    for _ in range(iters):
        g = J.T @ r0 + L @ (L.T @ (th - mu0))
        H = J.T @ J + L @ L.T
        step = -np.linalg.solve(H + lam * np.diag(np.diag(H)), g)
        cand = np.clip(th + step, LO, HI)
        r1, J1 = evaluate(cand)
        c1 = total(cand, r1)
        if c1 < cost:
            th, r0, J, cost = cand, r1, J1, c1
            lam = max(lam / 3, 1e-4)
            if np.max(np.abs(step) / h) < 0.05:
                break
        else:
            lam *= 8
    n = len(r0)
    chi2 = float(r0 @ r0) / max(n - 4, 1)
    c = max(1.0, chi2)
    post = np.linalg.inv(J.T @ J / c + np.linalg.inv(cov0))
    belief.mean, belief.cov = th, post
    belief.n_plots = T
    sim = predict_trials(belief.crop, th[None, :], trials, wxs)
    tr = sim.traces()["cc"]
    errs = [float(np.sqrt(np.mean((np.array(o["cc_obs"]) - tr[i, np.array(o["days"])]) ** 2))) for i, o in enumerate(obs)]
    yerr = [float(sim.fresh_yield()[i] / max(o["yield_t_ha"], 0.05) - 1) for i, o in enumerate(obs)]
    belief.rmse_cc = round(float(np.mean(errs)), 4)
    belief.yield_err = round(100 * float(np.mean(np.abs(yerr))), 1)
    return {"crop": belief.crop, "chi2": round(chi2, 2), "cc_rmse": belief.rmse_cc, "yield_err_pct": belief.yield_err,
            "cost": round(cost, 3)}


def trial_information(belief: CropBelief, trial: dict, wx_typ: dict, reference: dict | None = None) -> dict:
    """Expected effect of one trial plot on this crop's belief (linearised).
    `reference` is a production use of the crop {field_index, mgmt}; the
    decision-relevant number is how much the trial shrinks uncertainty in that
    use's predicted yield."""
    th = belief.mean
    h = np.array([0.02, 0.03, 0.25, 0.2])
    thetas = np.vstack([th] + [th + np.eye(4)[i] * h[i] for i in range(4)])
    sim = predict_trials(belief.crop, thetas, [trial], [wx_typ])
    tr = sim.traces()["cc"]
    days = np.arange(7, WX.SEASON_DAYS, 7)
    obs_vec = np.stack([np.concatenate([tr[k, days] / SIG_CC, [math.log(max(sim.fresh_yield()[k], 0.05)) / SIG_LOGY]])
                        for k in range(5)])
    J = ((obs_vec[1:] - obs_vec[0]) / h[:, None]).T
    eff = 0.5  # weekly observations are correlated; count them conservatively
    post = np.linalg.inv(np.linalg.inv(belief.cov) + eff * J.T @ J)
    s0, ld0 = np.linalg.slogdet(belief.cov)
    s1, ld1 = np.linalg.slogdet(post)
    bits = max(0.0, 0.5 * (ld0 - ld1) / math.log(2))
    y_trial = float(sim.fresh_yield()[0])
    refs = [reference] if reference else [
        {"field": 1, "mgmt": {"sow": int(np.mean(CROPS[belief.crop]["sow"])), "density": 1.0, "irr": 1.0, "desal": 0.0,
                              "nfert": CROPS[belief.crop]["nreq"], "mulch": 1.0}},
        {"field": 3, "mgmt": {"sow": int(np.mean(CROPS[belief.crop]["sow"])), "density": 1.0, "irr": 1.0, "desal": 0.0,
                              "nfert": CROPS[belief.crop]["nreq"], "mulch": 1.0}}]
    v0 = v1 = y0 = 0.0
    for ref in refs:
        g, y = production_gradient(belief.crop, th, ref, wx_typ, h)
        v0 += max(g @ belief.cov @ g, 0) / len(refs)
        v1 += max(g @ post @ g, 0) / len(refs)
        y0 += y / len(refs)
    sd_trait = np.sqrt(np.diag(post))
    return {"bits": bits, "pred_yield": y_trial, "ref_yield": y0, "ref_sd_before": math.sqrt(v0),
            "ref_sd_after": math.sqrt(v1),
            "trait_sd_after": {k: round(float(sd_trait[i]), 3) for i, k in enumerate(TRAIT_IDS)}}


def production_gradient(crop, th, ref, wx_typ, h):
    thetas = np.vstack([th] + [th + np.eye(4)[i] * h[i] for i in range(4)])
    K = 5
    mg = {k: np.full(K, float(ref["mgmt"][k])) for k in MG_KEYS}
    traits = {k: thetas[:, i] for i, k in enumerate(TRAIT_IDS)}
    sim = Sim(crop_arrays([crop] * K, traits), mg, soil_arrays([FIELDS[ref["field"]]] * K), _stack_wx([wx_typ]),
              np.zeros(K, int), np.full(K, EC_GROUNDWATER), eff=0.9).run()
    y = sim.fresh_yield()
    return (y[1:] - y[0]) / h, float(y[0])


def typical_year(seed: int = 4242) -> dict:
    """A representative weather year (median of a few draws, day by day)."""
    w = WX.generate(9, seed)
    out = {k: (np.median(w[k], axis=0) if k != "rain" else w[k][0]) for k in WX_KEYS}
    out["et0"] = WX.et0_pm(out["tmax"], out["tmin"], out["rh"], out["u2"], out["rs"], out["doy"])
    return out
