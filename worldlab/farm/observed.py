"""Real weather for the season, imported from NASA POWER (the one real-data path in WorldLab).

Source: NASA Prediction Of Worldwide Energy Resources (POWER) Daily API v2.10.1, community AG, point 24.2075 N,
55.7447 E (Al Ain, elevation in the POWER grid 257.7 m), 1 October 2024 to 30 June 2025, local solar time; sources
MERRA-2 (temperature, humidity, wind, precipitation) and CERES SYN1deg (radiation). NASA POWER data are free to use;
the POWER project asks that it be acknowledged ("These data were obtained from the NASA Langley Research Center
(LaRC) POWER Project funded through the NASA Earth Science/Applied Science Program").
Request: https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M_MAX,T2M_MIN,RH2M,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR&community=AG&longitude=55.7447&latitude=24.2075&start=20241001&end=20250630&format=JSON
Retrieved 1 Nov 2026; the file's SHA-256 is pinned below so any change to it is caught.

Variables and units: T2M_MAX, T2M_MIN (°C, 2 m air temperature), RH2M (%, daily mean relative humidity at 2 m),
WS2M (m/s, wind at 2 m), ALLSKY_SFC_SW_DWN (MJ/m²/day, all-sky shortwave down), PRECTOTCORR (mm/day, bias-corrected).

These are reanalysis and satellite estimates for a ~50 km grid cell, not a station on the farm. What uses them, when a
season runs on real weather: the crop model's daily weather (growth, heat at flowering, water use), the reference ET
(FAO-56 Penman-Monteith, computed here from the observed variables), irrigation demand, and the forecasts shown to the
scientist. What stays synthetic: soils, crop traits, the hidden faults, trial-plot seasons (earlier years drawn from
the climatology) and the imagined seasons the scientist plans and trains in.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np

from . import weather as WX

FILE = Path(__file__).resolve().parent.parent / "data" / "nasa_power_alain_2024_25.csv"
SHA256 = "c66ae08853e3f9c40bfad490f8811464c1ba85619f8858f6ae358089c1a8d63d"
COLUMNS = {"T2M_MAX": "tmax", "T2M_MIN": "tmin", "RH2M": "rh", "WS2M": "u2", "ALLSKY_SFC_SW_DWN": "rs", "PRECTOTCORR": "rain"}
RANGES = {"tmax": (-10, 60), "tmin": (-15, 45), "rh": (0, 100), "u2": (0, 30), "rs": (0, 40), "rain": (0, 300)}
FILL = -999.0
SOURCE = {"name": "NASA POWER Daily API v2.10.1 (community AG)", "point": [24.2075, 55.7447], "grid_elevation_m": 257.7,
          "period": "2024-10-01 to 2025-06-30", "sources": ["MERRA-2", "CERES SYN1deg"], "sha256": SHA256,
          "acknowledgement": "These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded "
                             "through the NASA Earth Science/Applied Science Program."}


def load(path: Path = FILE, check_hash: bool = True) -> tuple[dict, dict]:
    """The season's weather as arrays shaped (1, 273), plus a report: rows, gaps filled and how, values out of range.
    Missing values (-999 or empty) and values outside physical ranges are filled: gaps of up to 3 days by linear
    interpolation, longer ones from the climatology; every fill is counted in the report."""
    raw = Path(path).read_bytes()
    if check_hash and hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError(f"{path.name} differs from the pinned NASA POWER extract (SHA-256 mismatch)")
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    if len(rows) != WX.SEASON_DAYS:
        raise ValueError(f"expected {WX.SEASON_DAYS} daily rows (1 Oct to 30 Jun), found {len(rows)}")
    import datetime
    d0 = datetime.date(int(rows[0]["date"][:4]), int(rows[0]["date"][4:6]), int(rows[0]["date"][6:]))
    if (d0.month, d0.day) != (10, 1):
        raise ValueError("the season must start on 1 October")
    for k, r in enumerate(rows):
        exp = d0 + datetime.timedelta(days=k)
        if r["date"] != exp.strftime("%Y%m%d"):
            raise ValueError(f"row {k + 1}: date {r['date']}, expected {exp:%Y%m%d} (days must be consecutive)")
    doy = WX.season_doys()
    clim = WX._clim_daily(doy)
    clim_of = {"tmax": clim[:, 0], "tmin": clim[:, 1], "rh": clim[:, 2], "u2": clim[:, 3], "rs": clim[:, 4], "rain": np.zeros(len(doy))}
    out, report = {}, {"rows": len(rows), "missing": {}, "out_of_range": {}, "filled_by_interpolation": {}, "filled_from_climatology": {}}
    for col, key in COLUMNS.items():
        v = np.array([float(r[col]) if r.get(col) not in (None, "") else np.nan for r in rows])
        v[v == FILL] = np.nan
        lo, hi = RANGES[key]
        bad = ~np.isnan(v) & ((v < lo) | (v > hi))
        report["out_of_range"][key] = int(bad.sum())
        v[bad] = np.nan
        miss = np.isnan(v)
        report["missing"][key] = int(miss.sum())
        interp = clim_fill = 0
        if miss.any():
            idx = np.arange(len(v))
            k = 0
            while k < len(v):
                if not miss[k]:
                    k += 1
                    continue
                j = k
                while j < len(v) and miss[j]:
                    j += 1
                if j - k <= 3 and k > 0 and j < len(v):
                    v[k:j] = np.interp(idx[k:j], [k - 1, j], [v[k - 1], v[j]])
                    interp += j - k
                else:
                    v[k:j] = clim_of[key][k:j]
                    clim_fill += j - k
                k = j
        report["filled_by_interpolation"][key], report["filled_from_climatology"][key] = interp, clim_fill
        out[key] = v[None, :]
    out["tmin"] = np.minimum(out["tmin"], out["tmax"] - 0.5)
    out["et0"] = WX.et0_pm(out["tmax"], out["tmin"], out["rh"], out["u2"], out["rs"], doy)
    out["doy"] = doy[None, :].copy()
    out["heatwave"] = (out["tmax"] - clim[:, 0][None, :]) > 5.0      # flagged for display only
    report["first_day"], report["last_day"] = rows[0]["date"], rows[-1]["date"]
    return out, report


def compare_with_climatology(wx: dict) -> list[dict]:
    """Monthly means of the real season against the synthetic climatology the simulator otherwise draws from."""
    doy = WX.season_doys()
    clim = WX._clim_daily(doy)
    import datetime
    months = [(datetime.date(2024, 10, 1) + datetime.timedelta(days=int(d))).strftime("%b") for d in range(len(doy))]
    syn_et0 = WX.et0_pm(clim[:, 0], clim[:, 1], clim[:, 2], clim[:, 3], clim[:, 4], doy)
    rows = []
    for m in dict.fromkeys(months):
        sl = np.array([x == m for x in months])
        rows.append({"month": m, "tmax_real": round(float(wx["tmax"][0, sl].mean()), 1), "tmax_synthetic": round(float(clim[sl, 0].mean()), 1),
                     "rs_real": round(float(wx["rs"][0, sl].mean()), 1), "rs_synthetic": round(float(clim[sl, 4].mean()), 1),
                     "et0_real_mm_day": round(float(wx["et0"][0, sl].mean()), 2), "et0_synthetic_mm_day": round(float(syn_et0[sl].mean()), 2),
                     "rain_real_mm": round(float(wx["rain"][0, sl].sum()), 1), "rain_synthetic_mm": round(float(clim[sl, 5].mean() / 30 * sl.sum()), 1)})
    return rows
