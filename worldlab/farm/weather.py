"""Daily weather for an inland UAE farm (Al Ain area, 24.2 N, ~290 m) and
FAO-56 Penman-Monteith reference evapotranspiration.

The growing season runs 1 October to 30 June (273 days). Each weather year is
a stochastic draw around monthly climatology: autocorrelated temperature
anomalies, occasional spring heat waves, sparse winter rain.
"""
from __future__ import annotations

import math

import numpy as np

LAT_DEG = 24.2
ELEV_M = 290.0
SEASON_START_DOY = 274          # 1 October
SEASON_DAYS = 273               # to 30 June
MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun"]

# Monthly climatology, Jan..Dec: Tmax, Tmin (C), RH (%), wind at 2 m (m/s),
# solar radiation (MJ/m2/day), rain (mm/month). Approximate inland UAE values.
CLIM = np.array([
    [24.0, 12.5, 60, 2.6, 15.5, 12],
    [26.5, 14.0, 55, 2.9, 18.5, 18],
    [30.5, 17.0, 48, 3.1, 21.5, 14],
    [35.5, 21.0, 38, 3.2, 24.5, 6],
    [40.5, 25.0, 30, 3.2, 26.5, 1],
    [43.0, 28.0, 32, 3.5, 27.0, 0],
    [44.0, 30.0, 38, 3.6, 25.5, 1],
    [43.5, 29.5, 42, 3.4, 24.5, 1],
    [40.5, 26.5, 45, 2.9, 22.5, 0],
    [36.5, 22.0, 48, 2.5, 19.5, 1],
    [30.5, 17.5, 55, 2.4, 16.5, 3],
    [26.0, 14.0, 60, 2.5, 14.5, 9],
])


def _clim_daily(doy: np.ndarray) -> np.ndarray:
    """Interpolate monthly climatology to days of year (mid-month anchors)."""
    mid = np.array([15, 45, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349], float)
    x = np.concatenate([mid - 365, mid, mid + 365])
    out = np.empty((len(doy), CLIM.shape[1]))
    for j in range(CLIM.shape[1]):
        y = np.concatenate([CLIM[:, j]] * 3)
        out[:, j] = np.interp(doy, x, y)
    return out


def season_doys() -> np.ndarray:
    return ((SEASON_START_DOY - 1 + np.arange(SEASON_DAYS)) % 365) + 1


def day_label(d: int) -> str:
    import datetime
    base = datetime.date(2026, 10, 1)
    return (base + datetime.timedelta(days=int(d))).strftime("%d %b")


def et0_pm(tmax, tmin, rh, u2, rs, doy, lat_deg=LAT_DEG, z=ELEV_M):
    """FAO-56 Penman-Monteith reference ET (mm/day). Arrays broadcast."""
    tmean = (tmax + tmin) / 2
    e = lambda T: 0.6108 * np.exp(17.27 * T / (T + 237.3))
    es = (e(tmax) + e(tmin)) / 2
    ea = es * rh / 100.0
    delta = 4098 * e(tmean) / (tmean + 237.3) ** 2
    P = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26
    gamma = 0.000665 * P
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    Ra = 24 * 60 / np.pi * 0.0820 * dr * (ws * np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.sin(ws))
    Rso = (0.75 + 2e-5 * z) * Ra
    Rns = 0.77 * rs
    sigma = 4.903e-9
    Rnl = sigma * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0.01))) \
        * (1.35 * np.clip(rs / np.maximum(Rso, 1e-6), 0.25, 1.0) - 0.35)
    Rn = Rns - Rnl
    num = 0.408 * delta * Rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)
    return np.maximum(num / (delta + gamma * (1 + 0.34 * u2)), 0.3)


def daylength(doy, lat_deg=LAT_DEG):
    phi = math.radians(lat_deg)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    return 24 / np.pi * np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))


def generate(n_years: int, seed: int, heatwave_rate: float = 1.0) -> dict:
    """n_years weather years for the season. Returns arrays shaped (W, D)."""
    rng = np.random.default_rng(seed)
    doy = season_doys()
    D = len(doy)
    c = _clim_daily(doy)
    W = n_years
    # temperature anomalies: AR(1), shared between tmax and tmin
    a = np.zeros((W, D))
    eps = rng.normal(0, 1.6, (W, D))
    for d in range(1, D):
        a[:, d] = 0.8 * a[:, d - 1] + eps[:, d] * math.sqrt(1 - 0.64)
    a = a * 1.0 + rng.normal(0, 0.6, (W, 1))  # warm and cool years
    # heat waves: mostly March to June
    hw = np.zeros((W, D))
    for w in range(W):
        n = rng.poisson(2.2 * heatwave_rate)
        for _ in range(n):
            start = int(rng.integers(150, D - 6))
            length = int(rng.integers(3, 8))
            hw[w, start:start + length] += rng.uniform(3.5, 6.5)
    tmax = c[:, 0] + a + hw
    tmin = c[:, 1] + 0.8 * a + 0.5 * hw
    rh = np.clip(c[:, 2] + rng.normal(0, 7, (W, D)) - 1.5 * hw, 12, 95)
    u2 = np.clip(c[:, 3] * rng.lognormal(0, 0.25, (W, D)), 0.5, 9)
    # rain: wet days with exponential depths, matched to monthly totals
    p_wet = np.clip(c[:, 5] / 30 / 6.0, 0, 0.5)
    wet = rng.random((W, D)) < p_wet
    rain = np.where(wet, rng.exponential(6.0, (W, D)), 0.0)
    rs = c[:, 4] * np.where(wet, 0.55, 1.0) * rng.uniform(0.92, 1.03, (W, D))
    et0 = et0_pm(tmax, tmin, rh, u2, rs, doy)
    return {"tmax": tmax, "tmin": tmin, "rh": rh, "u2": u2, "rs": rs, "rain": rain, "et0": et0,
            "doy": np.broadcast_to(doy, (W, D)).copy(), "heatwave": hw > 0}


def heat_wave_inject(wx: dict, w: int, start: int, length: int = 6, delta: float = 6.0) -> None:
    """Add a heat wave to one weather year in place (used by the world's 'heat wave' event)."""
    sl = slice(start, min(start + length, wx["tmax"].shape[1]))
    wx["tmax"][w, sl] += delta
    wx["tmin"][w, sl] += 0.5 * delta
    wx["rh"][w, sl] = np.clip(wx["rh"][w, sl] - 8, 10, 95)
    wx["heatwave"][w, sl] = True
    wx["et0"][w] = et0_pm(wx["tmax"][w], wx["tmin"][w], wx["rh"][w], wx["u2"][w], wx["rs"][w], wx["doy"][w])
