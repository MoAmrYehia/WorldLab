"""Sowing seasons on the Al Ain farm, and a crop guide for choosing what to sow.

The growing year runs from 1 October to 30 June (day 0 = 1 October). Open
fields rest through the summer: from July to September daytime highs pass
45 °C and no field crop here is worth the water.
"""
from __future__ import annotations

import functools

import numpy as np

from . import weather as WX
from .crops import CROPS, CROP_IDS, NEEDS, NUTRIENTS, TRAIT_IDS

SEASONS = [
    {"id": "autumn", "label": "Autumn sowing", "start": 0, "end": 45,
     "about": "Sow from 1 October to 15 November, as the heat breaks. Warm-season crops finish before the spring heat."},
    {"id": "winter", "label": "Winter sowing", "start": 46, "end": 91,
     "about": "Sow from 16 November to 31 December. The coolest months suit wheat, potatoes and beans."},
    {"id": "late_winter", "label": "Late-winter sowing", "start": 116, "end": 165,
     "about": "Sow from 25 January to 15 March. Heat-loving crops grow into the spring and are harvested by June."},
]
SUMMER = {"id": "summer", "label": "Summer", "about": "July to September: fields rest. Daytime highs above 45 °C make open-field crops a poor use of water."}
SEASON_IDS = [s["id"] for s in SEASONS]


def season(sid: str) -> dict:
    for s in SEASONS:
        if s["id"] == sid:
            return s
    raise ValueError(f"unknown season {sid}")


def window(crop: str, sid: str) -> tuple[int, int] | None:
    """The part of the crop's sowing window that falls in the season, or None."""
    a, b = CROPS[crop]["sow"]
    s = season(sid)
    lo, hi = max(a, s["start"]), min(b, s["end"])
    return (lo, hi) if lo <= hi else None


def in_season(crop: str, sid: str) -> bool:
    return window(crop, sid) is not None


def sow_days(crop: str, sid: str) -> list[int]:
    w = window(crop, sid)
    if not w:
        return []
    lo, hi = w
    return sorted({lo, (lo + hi) // 2, hi})


def crops_for(sid: str) -> list[str]:
    return [c for c in CROP_IDS if in_season(c, sid)]


def seasons_for(crop: str) -> list[str]:
    return [s["id"] for s in SEASONS if in_season(crop, s["id"])]


def _good_for(crop: str) -> list[str]:
    """Which needs a hectare of this crop covers best, relative to the other crops."""
    c = CROPS[crop]
    out = []
    per_kg = {"kcal": c["kcal"] / NEEDS["kcal"], "protein_g": c["prot"] / NEEDS["protein_g"], "vitA_ug": c["vita"] / NEEDS["vitA_ug"]}
    ref = {n: max(CROPS[k][key] / NEEDS[n] for k in CROP_IDS) for n, key in (("kcal", "kcal"), ("protein_g", "prot"), ("vitA_ug", "vita"))}
    names = {"kcal": "calories", "protein_g": "protein", "vitA_ug": "vitamin A"}
    for n in NUTRIENTS:
        if per_kg[n] >= 0.3 * ref[n] and per_kg[n] > 0:
            out.append(names[n])
    return out or ["calories"]


@functools.lru_cache(maxsize=8)
def crop_guide(sid: str, S: int = 10, seed: int = 5) -> dict:
    """For every crop in season: what it needs and what it gives, with a model
    preview on each field at the middle of its in-season window (published
    values, typical management)."""
    from .belief import CropBelief
    from .sim import Sim, crop_arrays, soil_arrays
    from .world import FIELDS, FIELD_HA, EC_GROUNDWATER
    s = season(sid)
    crops = crops_for(sid)
    wx = WX.generate(S, seed)
    rng = np.random.default_rng(seed)
    rows, crop_list, tr, mg, soils = [], [], {k: [] for k in TRAIT_IDS}, {k: [] for k in ("sow", "density", "irr", "desal", "nfert", "mulch")}, []
    for c in crops:
        lo, hi = window(c, sid)
        sow = (lo + hi) // 2
        smp = CropBelief(c).sample(S, rng)
        for fi, f in enumerate(FIELDS):
            crop_list += [c] * S
            for k in TRAIT_IDS:
                tr[k].append(smp[k])
            for k, v in (("sow", sow), ("density", 1.0), ("irr", 0.9), ("desal", 0.0), ("nfert", CROPS[c]["nreq"]), ("mulch", 1.0)):
                mg[k].append(np.full(S, float(v)))
            soils += [f] * S
    if crop_list:
        B = len(crop_list)
        sim = Sim(crop_arrays(crop_list, {k: np.concatenate(v) for k, v in tr.items()}),
                  {k: np.concatenate(v) for k, v in mg.items()}, soil_arrays(soils), wx,
                  np.tile(np.arange(S), B // S), np.full(B, EC_GROUNDWATER), eff=0.9, record=False).run()
        y = sim.fresh_yield().reshape(len(crops), len(FIELDS), S)
        water = (sim.water_m3_ha() * FIELD_HA).reshape(len(crops), len(FIELDS), S)
        hd = sim.harvest_day.reshape(len(crops), len(FIELDS), S)
        heat = sim.hi_heat.reshape(len(crops), len(FIELDS), S)                       # 1 = no heat loss at flowering
        ece = sim.ece_layers()[:, :2].mean(1).reshape(len(crops), len(FIELDS), S)  # root-zone salinity at season end
    for ci, c in enumerate(crops):
        k = CROPS[c]
        lo, hi = window(c, sid)
        sow = (lo + hi) // 2
        fields = []
        for fi, f in enumerate(FIELDS):
            yy = float(np.median(y[ci, fi]))
            kg = yy * 1000 * FIELD_HA
            fields.append({"field": f["id"], "yield_t_ha_p50": round(yy, 2),
                           "yield_t_ha_p10": round(float(np.percentile(y[ci, fi], 10)), 2),
                           "yield_t_ha_p90": round(float(np.percentile(y[ci, fi], 90)), 2),
                           "heat_factor": round(float(np.median(heat[ci, fi])), 2),
                           "ece_root_zone_end": round(float(np.median(ece[ci, fi])), 1),
                           "water_m3_p50": round(float(np.median(water[ci, fi]))),
                           "people_by_need_p50": {"calories": round(kg * k["kcal"] / (NEEDS["kcal"] * 365), 1),
                                                  "protein": round(kg * k["prot"] / (NEEDS["protein_g"] * 365), 1),
                                                  "vitamin A": round(kg * k["vita"] / (NEEDS["vitA_ug"] * 365), 1)}})
        days = hd[ci][hd[ci] > 0]
        cycle = int(np.median(days) - sow) if days.size else None
        rows.append({"crop": c, "label": k["label"], "sow_window": [lo, hi],
                     "sow_window_label": f"{WX.day_label(lo).lstrip('0')} to {WX.day_label(hi).lstrip('0')}",
                     "cycle_days": cycle, "harvest_label": WX.day_label(min(sow + cycle, WX.SEASON_DAYS - 1)).lstrip("0") if cycle else None,
                     "heat_limit_c": k["heat"], "salt_threshold_ds_m": k["salt"], "good_for": _good_for(c),
                     "fields": fields})
    return {"season": s, "crops": rows}


def all_seasons() -> dict:
    return {"seasons": SEASONS, "summer": SUMMER,
            "crops": [{"crop": c, "label": CROPS[c]["label"], "seasons": seasons_for(c),
                       "sow_window": list(CROPS[c]["sow"])} for c in CROP_IDS]}
