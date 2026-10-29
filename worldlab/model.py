"""Grey-box thermal model of the rig, with fitting, uncertainty and prediction.

The rig is a heated object (a heatsink with a power resistor, standing in for a
chip) cooled by a fan. We model it as a single lumped thermal mass:

    dT/dt = -k(u) * (T - Ta) + b * q

    T   object temperature (C)           Ta  ambient temperature (C, measured)
    u   fan duty, 0..1                   q   heater power (W, known command)
    b   1 / heat capacity (K per J)      k(u) cooling rate (1/s)

The agent does not know the form of k(u). It chooses among candidate
structures, each a different physical hypothesis about how airflow scales with
duty:

    linear       k = k0 + k1*u
    sqrt         k = k0 + k1*sqrt(u)          (laminar forced convection)
    power        k = k0 + k1*u**n
    stall_power  k = k0 + k1*max(0, u-u0)**n  (fan does not spin below u0)

Between samples the inputs are piecewise constant, so we integrate exactly:
    T[i+1] = Teq + (T[i] - Teq) * exp(-k dt),   Teq = Ta + b q / k
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

SENSOR_SIGMA = 0.07  # K, DS18B20-class sensor noise incl. 0.0625 K quantisation

STRUCTURES: dict[str, dict] = {
    "linear": {
        "params": ["k0", "k1", "b"],
        "lo": [1e-5, 0.0, 1e-4], "hi": [0.05, 0.2, 0.2],
        "about": "cooling rate rises linearly with fan duty",
    },
    "sqrt": {
        "params": ["k0", "k1", "b"],
        "lo": [1e-5, 0.0, 1e-4], "hi": [0.05, 0.2, 0.2],
        "about": "cooling rate rises with the square root of duty (laminar boundary layer)",
    },
    "power": {
        "params": ["k0", "k1", "n", "b"],
        "lo": [1e-5, 0.0, 0.2, 1e-4], "hi": [0.05, 0.2, 2.5, 0.2],
        "about": "cooling rate rises as a power law of duty",
    },
    "stall_power": {
        "params": ["k0", "k1", "u0", "n", "b"],
        "lo": [1e-5, 0.0, 0.0, 0.2, 1e-4], "hi": [0.05, 0.2, 0.5, 2.5, 0.2],
        "about": "fan does not move air below a stall duty u0, then a power law",
    },
}

# Weak prior used before any data exists (broad, physically plausible).
PRIOR_MEAN = {"k0": 0.003, "k1": 0.01, "n": 1.0, "u0": 0.05, "b": 0.01}
PRIOR_REL_SD = {"k0": 0.6, "k1": 0.6, "n": 0.4, "u0": 1.0, "b": 0.5}


def airflow(structure: str, p: dict, u):
    u = np.clip(np.asarray(u, dtype=float), 0.0, 1.0)
    if structure == "linear":
        return u
    if structure == "sqrt":
        return np.sqrt(u)
    if structure == "power":
        return u ** p["n"]
    if structure == "stall_power":
        span = np.maximum(1e-6, 1.0 - p["u0"])
        return (np.clip(u - p["u0"], 0.0, None) / span) ** p["n"]
    raise ValueError(structure)


def cooling_rate(structure: str, p: dict, u):
    return p["k0"] + p["k1"] * airflow(structure, p, u)


def simulate(structure: str, p: dict, T0: float, dt, u, q, Ta) -> np.ndarray:
    """Exact piecewise-constant integration. dt,u,q,Ta are arrays of len N
    (inputs held during interval i, which has length dt[i]). Returns N+1 temps."""
    k = cooling_rate(structure, p, u)
    k = np.maximum(k, 1e-7)
    Teq = np.asarray(Ta) + p["b"] * np.asarray(q) / k
    decay = np.exp(-k * np.asarray(dt))
    out = np.empty(len(dt) + 1)
    out[0] = T0
    T = T0
    for i in range(len(dt)):
        T = Teq[i] + (T - Teq[i]) * decay[i]
        out[i + 1] = T
    return out


def simulate_many(structure: str, P: dict[str, np.ndarray], T0, dt, u, q, Ta) -> np.ndarray:
    """Vectorised over parameter samples. P values are arrays of shape (S,).
    Returns array (S, N+1)."""
    S = len(next(iter(P.values())))
    u = np.asarray(u, float)
    dt = np.asarray(dt, float)
    q = np.asarray(q, float)
    Ta = np.asarray(Ta, float)
    out = np.empty((S, len(dt) + 1))
    T = np.full(S, float(T0)) if np.isscalar(T0) else np.asarray(T0, float)
    out[:, 0] = T
    # k depends on u (per step) and params (per sample): broadcast to (S, N)
    Pc = {name: np.asarray(v, float)[:, None] for name, v in P.items()}
    k = np.maximum(np.broadcast_to(cooling_rate(structure, Pc, u[None, :]), (S, len(dt))), 1e-7)
    Teq = Ta[None, :] + P["b"][:, None] * q[None, :] / k
    decay = np.exp(-k * dt[None, :])
    for i in range(len(dt)):
        T = Teq[:, i] + (T - Teq[:, i]) * decay[:, i]
        out[:, i + 1] = T
    return out


@dataclass
class Data:
    """Time series used for fitting. seg marks contiguous segments; the
    simulation restarts from the measured temperature at each segment start."""
    t: np.ndarray
    T: np.ndarray
    Ta: np.ndarray
    u: np.ndarray
    q: np.ndarray
    seg: np.ndarray

    @staticmethod
    def from_samples(samples: list[dict], since: float | None = None, gap: float = 6.0,
                     decimate: float = 5.0) -> "Data":
        rows = [s for s in samples if since is None or s["t"] >= since]
        # decimate to ~decimate seconds (keeps fitting fast; time constants >> 5 s)
        kept, last = [], -1e9
        for s in rows:
            if s["t"] - last >= decimate - 1e-9:
                kept.append(s)
                last = s["t"]
        if not kept:
            z = np.zeros(0)
            return Data(z, z, z, z, z, z.astype(int))
        t = np.array([s["t"] for s in kept])
        seg = np.zeros(len(t), int)
        sid = 0
        for i in range(1, len(t)):
            if t[i] - t[i - 1] > gap + decimate:
                sid += 1
            seg[i] = sid
        return Data(
            t=t,
            T=np.array([s["T_obj"] for s in kept]),
            Ta=np.array([s["T_amb"] for s in kept]),
            u=np.array([s["fan_duty"] for s in kept]),
            q=np.array([s["heater_w"] for s in kept]),
            seg=seg,
        )

    def __len__(self):
        return len(self.t)

    def segments(self):
        for sid in np.unique(self.seg):
            idx = np.nonzero(self.seg == sid)[0]
            if len(idx) >= 3:
                yield idx


@dataclass
class Fit:
    structure: str
    names: list[str]
    mean: np.ndarray
    cov: np.ndarray
    rmse: float
    n_points: int
    n_eff: float
    aic: float
    fixed: dict = field(default_factory=dict)
    since: float | None = None

    def params(self) -> dict:
        d = dict(self.fixed)
        d.update({n: float(v) for n, v in zip(self.names, self.mean)})
        return d

    def sd(self) -> dict:
        return {n: float(math.sqrt(max(self.cov[i, i], 0.0))) for i, n in enumerate(self.names)}

    def sample(self, S: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
        spec = STRUCTURES[self.structure]
        lo = dict(zip(spec["params"], spec["lo"]))
        hi = dict(zip(spec["params"], spec["hi"]))
        try:
            draws = rng.multivariate_normal(self.mean, self.cov, size=S, method="eigh")
        except Exception:
            draws = self.mean + rng.standard_normal((S, len(self.mean))) * np.sqrt(np.diag(self.cov))
        out = {}
        for i, n in enumerate(self.names):
            out[n] = np.clip(draws[:, i], lo[n], hi[n])
        for n, v in self.fixed.items():
            out[n] = np.full(S, v)
        return out

    def to_json(self) -> dict:
        p, sd = self.params(), self.sd()
        return {
            "structure": self.structure,
            "about": STRUCTURES[self.structure]["about"],
            "params": {n: {"value": p[n], "sd": sd.get(n, 0.0), "fixed": n in self.fixed} for n in p},
            "rmse_K": round(self.rmse, 4),
            "n_points": self.n_points,
            "n_effective": round(self.n_eff, 1),
            "aic": round(self.aic, 2),
            "fit_since_t": self.since,
        }


def prior_fit(structure: str = "power") -> Fit:
    names = STRUCTURES[structure]["params"]
    mean = np.array([PRIOR_MEAN[n] for n in names])
    sd = np.array([PRIOR_MEAN[n] * PRIOR_REL_SD[n] for n in names])
    return Fit(structure, names, mean, np.diag(sd ** 2), rmse=float("nan"), n_points=0,
               n_eff=0, aic=float("nan"))


def _residuals(x, names, fixed, structure, data: Data):
    p = dict(fixed)
    p.update(dict(zip(names, x)))
    res = []
    for idx in data.segments():
        dt = np.diff(data.t[idx])
        T0 = float(np.mean(data.T[idx[:2]]))
        pred = simulate(structure, p, T0, dt, data.u[idx[:-1]], data.q[idx[:-1]], data.Ta[idx[:-1]])
        res.append(pred - data.T[idx])
    return np.concatenate(res) if res else np.zeros(0)


DATA_EFF = 0.35     # fraction of ~5 s samples counted as independent evidence
DATA_SIGMA = 0.1    # K, typical residual (sensor noise plus small model error)


def default_prior(names) -> dict:
    return {n: (PRIOR_MEAN[n], PRIOR_MEAN[n] * PRIOR_REL_SD[n]) for n in names}


def fit(structure: str, data: Data, start: dict | None = None, since: float | None = None,
        fix: dict | None = None, prior: dict | None = None) -> Fit:
    """MAP fit of one structure under a Gaussian prior on its parameters.

    Parameters the data cannot pin down (fan shape before several duties have
    been tried, heater gain before the heater has been on) stay near the prior
    with the prior's uncertainty, instead of being silently treated as known.

    `fix` holds parameters exactly at given values. That is how a hypothesis
    such as "only the fan coupling changed" is tested: hold k0 and b at their
    old values and compare the AIC with a free fit.

    `prior` maps name -> (mean, sd). After an anomaly the lab passes the last
    trusted model, widened, so a refit on post-change data keeps what was
    already known about the fan curve.
    """
    spec = STRUCTURES[structure]
    names = list(spec["params"])
    lo = dict(zip(spec["params"], spec["lo"]))
    hi = dict(zip(spec["params"], spec["hi"]))
    fixed: dict = {}
    for n, v in (fix or {}).items():
        if n in names:
            fixed[n] = float(v)
            names.remove(n)
    pri = default_prior(spec["params"])
    pri.update({n: v for n, v in (prior or {}).items() if n in pri})
    mu = np.array([pri[n][0] for n in names])
    sp = np.array([max(pri[n][1], 1e-9) for n in names])
    w = math.sqrt(DATA_EFF) / DATA_SIGMA

    def resid(x):
        return np.concatenate([w * _residuals(x, names, fixed, structure, data), (x - mu) / sp])

    s = dict(start or {})
    x0 = np.array([min(max(s.get(n, pri[n][0]), lo[n] + 1e-9), hi[n] * 0.999) for n in names])
    bounds = (np.array([lo[n] for n in names]), np.array([hi[n] for n in names]))
    starts = [x0]
    if "n" in names:  # a second start helps the power-law structures
        alt = x0.copy()
        alt[names.index("n")] = 0.6
        starts.append(alt)
    best = None
    for xs in starts:
        r = least_squares(resid, xs, bounds=bounds, x_scale="jac", max_nfev=300)
        if best is None or r.cost < best.cost:
            best = r
    r = best
    N, P = len(data_res := _residuals(r.x, names, fixed, structure, data)), len(names)
    ssr = float(np.sum(data_res ** 2))
    Jd, Jp = r.jac[:N], r.jac[N:]
    # If the data scatter more than DATA_SIGMA explains, trust them less.
    chi2 = float(np.sum((w * data_res) ** 2)) / max(DATA_EFF * N - P, 1.0)
    c = max(1.0, chi2)
    try:
        cov = np.linalg.inv(Jd.T @ Jd / c + Jp.T @ Jp)
    except np.linalg.LinAlgError:
        cov = np.diag(sp ** 2)
    rho = 0.0
    if N > 3:
        a, b_ = data_res[:-1] - data_res.mean(), data_res[1:] - data_res.mean()
        denom = math.sqrt(float(np.sum(a * a) * np.sum(b_ * b_))) or 1.0
        rho = float(np.clip(np.sum(a * b_) / denom, 0.0, 0.98))
    n_eff = max(N * (1 - rho) / (1 + rho), P + 1)
    # AIC uses the same effective sample size for every fit of the same data,
    # so held and free fits, and different structures, are comparable.
    aic = DATA_EFF * N * math.log(max(ssr / max(N, 1), 1e-12)) + 2 * P
    return Fit(structure, names, r.x, cov, rmse=math.sqrt(ssr / max(N, 1)), n_points=N,
               n_eff=n_eff, aic=aic, fixed=fixed, since=since)


def fit_all(data: Data, structures=None, start: dict | None = None, since=None,
            fix: dict | None = None, prior: dict | None = None) -> list[Fit]:
    structures = structures or list(STRUCTURES)
    fits = [fit(s, data, start=start, since=since, fix=fix, prior=prior) for s in structures]
    return sorted(fits, key=lambda f: f.aic)


# ---------------------------------------------------------------- prediction

@dataclass
class Prediction:
    t: np.ndarray          # absolute times (N+1)
    mean: np.ndarray
    lo: np.ndarray         # 5th percentile incl. sensor noise
    hi: np.ndarray         # 95th percentile incl. sensor noise
    sd: np.ndarray         # total predictive sd (params + sensor)

    def at(self, t: float) -> tuple[float, float, float, float]:
        i = int(np.clip(np.searchsorted(self.t, t), 0, len(self.t) - 1))
        if i > 0 and abs(self.t[i - 1] - t) < abs(self.t[i] - t):
            i -= 1
        return float(self.mean[i]), float(self.lo[i]), float(self.hi[i]), float(self.sd[i])

    def to_json(self, every: int = 1) -> dict:
        sl = slice(None, None, every)
        return {"t": self.t[sl].round(2).tolist(), "mean": self.mean[sl].round(3).tolist(),
                "lo": self.lo[sl].round(3).tolist(), "hi": self.hi[sl].round(3).tolist()}


def schedule_arrays(steps: list[dict], heater_w: float, Ta: float, dt: float = 5.0):
    """Expand experiment steps [{fan_duty, heater_on, duration_s}] into arrays."""
    u, q, d = [], [], []
    for st in steps:
        n = max(1, int(round(st["duration_s"] / dt)))
        u += [float(st["fan_duty"])] * n
        q += [heater_w if st.get("heater_on", True) else 0.0] * n
        d += [st["duration_s"] / n] * n
    return np.array(d), np.array(u), np.array(q), np.full(len(d), Ta)


def predict(f: Fit, T0: float, t0: float, dt, u, q, Ta, S: int = 300, seed: int = 0) -> Prediction:
    rng = np.random.default_rng(seed)
    P = f.sample(S, rng)
    sims = simulate_many(f.structure, P, T0, dt, u, q, Ta)
    mean = sims.mean(axis=0)
    psd = sims.std(axis=0)
    sd = np.sqrt(psd ** 2 + SENSOR_SIGMA ** 2)
    lo = np.percentile(sims, 5, axis=0) - 1.645 * SENSOR_SIGMA
    hi = np.percentile(sims, 95, axis=0) + 1.645 * SENSOR_SIGMA
    t = t0 + np.concatenate([[0.0], np.cumsum(dt)])
    return Prediction(t, mean, lo, hi, sd)


def info_gain(f: Fit, T0: float, dt, u, q, Ta) -> dict:
    """Expected effect of an experiment on parameter uncertainty (linearised
    Fisher information). Returns bits of information and the posterior fit."""
    p = f.params()
    names = f.names
    base = simulate(f.structure, p, T0, dt, u, q, Ta)[1:]
    J = np.zeros((len(base), len(names)))
    for i, n in enumerate(names):
        h = max(abs(p[n]) * 1e-3, 1e-7)
        p2 = dict(p)
        p2[n] = p[n] + h
        J[:, i] = (simulate(f.structure, p2, T0, dt, u, q, Ta)[1:] - base) / h
    # Samples are ~5 s apart and autocorrelated; count them conservatively.
    eff = 0.35
    info = eff * (J.T @ J) / SENSOR_SIGMA ** 2
    prior_cov = f.cov + np.eye(len(names)) * 1e-14
    post_cov = np.linalg.inv(np.linalg.inv(prior_cov) + info)
    s0, ld0 = np.linalg.slogdet(prior_cov)
    s1, ld1 = np.linalg.slogdet(post_cov)
    bits = 0.5 * (ld0 - ld1) / math.log(2) if s0 > 0 and s1 > 0 else 0.0
    post = Fit(f.structure, names, f.mean.copy(), post_cov, f.rmse, f.n_points, f.n_eff, f.aic,
               dict(f.fixed), f.since)
    return {"bits": float(max(bits, 0.0)), "posterior": post}


def steady_state(f_params: dict, structure: str, u: float, q: float, Ta: float) -> float:
    return Ta + f_params["b"] * q / max(float(cooling_rate(structure, f_params, u)), 1e-7)


# ------------------------------------------------------- structural uncertainty

GENERAL = "stall_power"   # every structure is a special case of this one


def to_general(structure: str, P: dict) -> dict:
    """Express any structure's parameters (scalars or arrays) in stall_power form."""
    out = {"k0": P["k0"], "k1": P["k1"], "b": P["b"]}
    like = np.zeros_like(np.asarray(P["k0"], float))
    if structure == "linear":
        out["u0"], out["n"] = like + 0.0, like + 1.0
    elif structure == "sqrt":
        out["u0"], out["n"] = like + 0.0, like + 0.5
    elif structure == "power":
        out["u0"], out["n"] = like + 0.0, np.asarray(P["n"], float) + like
    else:
        out["u0"], out["n"] = np.asarray(P["u0"], float) + like, np.asarray(P["n"], float) + like
    if np.ndim(like) == 0:
        out = {k: float(v) for k, v in out.items()}
    return out


class Mixture:
    """Belief over several model structures at once, weighted by Akaike
    weights. Behaves like a Fit for sampling-based prediction, so where the
    candidate explanations disagree (typically when extrapolating to fan duties
    that were never tried) the prediction bands widen honestly."""

    def __init__(self, fits: list[Fit], min_weight: float = 0.01):
        fits = sorted(fits, key=lambda f: f.aic)
        a0 = fits[0].aic
        w = np.array([math.exp(-0.5 * (f.aic - a0)) if math.isfinite(f.aic) else 0.0 for f in fits])
        if not np.isfinite(w).all() or w.sum() == 0:
            w = np.zeros(len(fits))
            w[0] = 1.0
        w = w / w.sum()
        keep = [i for i in range(len(fits)) if w[i] >= min_weight] or [0]
        self.members = [fits[i] for i in keep]
        self.weights = w[keep] / w[keep].sum()
        self.best = fits[0]
        self.structure = GENERAL
        self.rmse = self.best.rmse
        self.fixed: dict = {}
        self.names = STRUCTURES[GENERAL]["params"]

    def params(self) -> dict:
        return to_general(self.best.structure, self.best.params())

    def sample(self, S: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
        counts = rng.multinomial(S, self.weights)
        parts = [to_general(f.structure, f.sample(int(c), rng)) for f, c in zip(self.members, counts) if c > 0]
        return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}

    def weights_json(self) -> dict:
        return {f.structure: round(float(w), 3) for f, w in zip(self.members, self.weights)}
