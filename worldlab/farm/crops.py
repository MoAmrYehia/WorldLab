"""The ten food-security crops: growth parameters (AquaCrop-style, approximate
published values for warm, dry conditions) and nutrition of the harvested
product (approximate USDA FoodData Central values).

These are the agent's *priors*. The farm's actual local varieties differ in
four traits the agent has to discover from trials: water productivity,
canopy growth rate, heat tolerance at flowering, and salt tolerance.

Day indices count from 1 October (season day 0).
"""
from __future__ import annotations

import math

# Daily needs used to convert harvests into "people fed for a year".
NEEDS = {"kcal": 2100.0, "protein_g": 50.0, "vitA_ug": 600.0}
NUTRIENTS = list(NEEDS)

CROPS: dict[str, dict] = {
    # rank, label, type, Tb, Tu (C), GDD to maturity, flowering window (fraction of cycle),
    # heat threshold at flowering (Tmax C), WP* (g/m2), HI, CCx, Kcb, max root depth (m),
    # p (depletion fraction before stress), salt threshold ECe (dS/m), slope (% yield per dS/m),
    # N requirement (kg/ha for full growth), legume, product dry fraction,
    # kcal/kg, protein g/kg, vitamin A ug RAE/kg (product as harvested), sowing window (days)
    "wheat":        dict(rank=1, label="Wheat", c4=False, Tb=0.0, Tu=26.0, gdd=1900, flower=(0.50, 0.65), heat=31.0,
                         wp=15.0, hi=0.45, ccx=0.95, kcb=1.10, zr=1.2, p=0.55, salt=6.0, slope=7.1, nreq=180,
                         legume=False, dry=0.87, kcal=3400, prot=126, vita=0, sow=(30, 75)),
    "rice":         dict(rank=2, label="Rice", c4=False, Tb=10.0, Tu=34.0, gdd=1750, flower=(0.55, 0.70), heat=36.0,
                         wp=19.0, hi=0.42, ccx=0.95, kcb=1.20, zr=0.6, p=0.20, salt=3.0, slope=12.0, nreq=140,
                         legume=False, dry=0.88, kcal=3600, prot=70, vita=0, sow=(130, 160)),
    "maize":        dict(rank=3, label="Maize", c4=True, Tb=8.0, Tu=30.0, gdd=1650, flower=(0.48, 0.60), heat=36.0,
                         wp=33.0, hi=0.48, ccx=0.96, kcb=1.15, zr=1.5, p=0.50, salt=1.7, slope=12.0, nreq=200,
                         legume=False, dry=0.88, kcal=3650, prot=94, vita=110, sow=(0, 40)),
    "potato":       dict(rank=4, label="Potato", c4=False, Tb=2.0, Tu=26.0, gdd=1450, flower=(0.35, 0.60), heat=30.0,
                         wp=18.0, hi=0.75, ccx=0.92, kcb=1.10, zr=0.6, p=0.35, salt=1.7, slope=12.0, nreq=170,
                         legume=False, dry=0.21, kcal=770, prot=20, vita=0, sow=(15, 60)),
    "cassava":      dict(rank=5, label="Cassava", c4=False, Tb=12.0, Tu=35.0, gdd=3000, flower=(0.45, 0.80), heat=40.0,
                         wp=16.0, hi=0.60, ccx=0.90, kcb=0.95, zr=1.0, p=0.60, salt=2.0, slope=10.0, nreq=110,
                         legume=False, dry=0.35, kcal=1600, prot=14, vita=10, sow=(0, 20)),
    "soybean":      dict(rank=6, label="Soybeans", c4=False, Tb=8.0, Tu=32.0, gdd=1500, flower=(0.45, 0.65), heat=35.0,
                         wp=15.0, hi=0.38, ccx=0.95, kcb=1.10, zr=1.0, p=0.50, salt=5.0, slope=20.0, nreq=40,
                         legume=True, dry=0.88, kcal=4460, prot=360, vita=10, sow=(120, 160)),
    "sorghum":      dict(rank=7, label="Sorghum", c4=True, Tb=9.0, Tu=38.0, gdd=1750, flower=(0.50, 0.62), heat=40.0,
                         wp=33.0, hi=0.42, ccx=0.92, kcb=1.05, zr=1.6, p=0.55, salt=6.8, slope=16.0, nreq=140,
                         legume=False, dry=0.88, kcal=3290, prot=110, vita=0, sow=(120, 165)),
    "millet":       dict(rank=8, label="Millet", c4=True, Tb=10.0, Tu=38.0, gdd=1500, flower=(0.48, 0.60), heat=41.0,
                         wp=30.0, hi=0.30, ccx=0.88, kcb=1.00, zr=1.6, p=0.60, salt=6.0, slope=10.0, nreq=100,
                         legume=False, dry=0.88, kcal=3780, prot=110, vita=0, sow=(120, 165)),
    "beans":        dict(rank=9, label="Common beans", c4=False, Tb=8.0, Tu=30.0, gdd=1200, flower=(0.40, 0.60), heat=32.0,
                         wp=15.0, hi=0.40, ccx=0.92, kcb=1.10, zr=0.8, p=0.45, salt=1.0, slope=19.0, nreq=40,
                         legume=True, dry=0.88, kcal=3330, prot=220, vita=0, sow=(15, 60)),
    "sweet_potato": dict(rank=10, label="Sweet potatoes", c4=False, Tb=12.0, Tu=35.0, gdd=2000, flower=(0.40, 0.70), heat=38.0,
                         wp=18.0, hi=0.70, ccx=0.92, kcb=1.10, zr=1.0, p=0.65, salt=1.5, slope=11.0, nreq=90,
                         legume=False, dry=0.30, kcal=860, prot=16, vita=7090, sow=(0, 40)),
}
CROP_IDS = list(CROPS)

# The four traits that differ in the farm's local varieties, with the agent's prior uncertainty.
TRAITS = {
    "wp":    {"prior": 1.0, "sd": 0.12, "lo": 0.6, "hi": 1.5, "about": "water productivity (multiplier)"},
    "cgc":   {"prior": 1.0, "sd": 0.15, "lo": 0.6, "hi": 1.6, "about": "canopy growth rate (multiplier)"},
    "heat":  {"prior": 0.0, "sd": 1.5, "lo": -6, "hi": 6, "about": "heat tolerance at flowering (C shift)"},
    "salt":  {"prior": 0.0, "sd": 1.0, "lo": -3, "hi": 4, "about": "salt tolerance threshold (dS/m shift)"},
}
TRAIT_IDS = list(TRAITS)


def sow_options(crop: str) -> list[int]:
    a, b = CROPS[crop]["sow"]
    return sorted({a, (a + b) // 2, b})


def cgc_default(crop: str) -> float:
    """Canopy growth coefficient (per GDD) that closes the canopy in ~30% of the cycle."""
    return math.log(0.9 / 0.1 * 99) / (0.30 * CROPS[crop]["gdd"])


def nutrients_per_ha(crop: str, fresh_t_ha):
    """Nutrients from a harvest of fresh_t_ha tonnes per hectare."""
    c = CROPS[crop]
    kg = fresh_t_ha * 1000.0
    return {"kcal": kg * c["kcal"], "protein_g": kg * c["prot"], "vitA_ug": kg * c["vita"]}


def people_fed(totals: dict) -> dict:
    """Person-years of each need covered, and the binding one."""
    out = {n: totals[n] / (NEEDS[n] * 365.0) for n in NUTRIENTS}
    out["people"] = min(out[n] for n in NUTRIENTS)
    out["limiting"] = min(NUTRIENTS, key=lambda n: out[n])
    return out
