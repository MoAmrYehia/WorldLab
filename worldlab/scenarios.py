"""Scenario library: named starting conditions and hidden events for a season.

A scenario sets the farm's limits, its starting soil and the hidden changes made during the season
(the scientist is never told about them). Everything else, including the tools and their budgets,
stays the same, so seasons under different scenarios can be compared fairly.
"""
from __future__ import annotations

SCENARIOS = [
    {"id": "baseline", "title": "Baseline season", "difficulty": "Standard",
     "about": "The standard farm and limits, no hidden faults. A good first season.",
     "perturb": [], "limits": {}, "salinity_scale": 1.0},
    {"id": "drip_fault", "title": "Drip fault", "difficulty": "Standard",
     "about": "A drip line clogs in early January. The water meter can't see it.",
     "perturb": ["clog@95"], "limits": {}, "salinity_scale": 1.0},
    {"id": "pest_outbreak", "title": "Pest outbreak", "difficulty": "Standard",
     "about": "Pests arrive in one field in mid January and eat the canopy.",
     "perturb": ["pest@105"], "limits": {}, "salinity_scale": 1.0},
    {"id": "hot_flowering", "title": "Hot flowering", "difficulty": "Standard",
     "about": "A heat wave arrives in early March, when many crops flower. It is in the forecast.",
     "perturb": ["heatwave@155"], "limits": {}, "salinity_scale": 1.0},
    {"id": "water_scarcity", "title": "Water scarcity", "difficulty": "Hard",
     "about": "The groundwater quota is cut by a quarter, to 45,000 m³.",
     "perturb": [], "limits": {"water_quota_m3": 45000.0}, "salinity_scale": 1.0},
    {"id": "saline_start", "title": "Elevated salinity", "difficulty": "Hard",
     "about": "Every field starts the season with half as much salt again in its soil.",
     "perturb": [], "limits": {}, "salinity_scale": 1.5},
    {"id": "compound", "title": "Compound events", "difficulty": "Expert",
     "about": "A clogged drip line, then saltier groundwater, then a heat wave, with a 10% smaller water quota.",
     "perturb": ["clog@90", "salinity@120", "heatwave@160"], "limits": {"water_quota_m3": 54000.0}, "salinity_scale": 1.0},
]
BY_ID = {s["id"]: s for s in SCENARIOS}

# What a person may change in the farm editor, and the allowed ranges (validated on the server).
EDITOR_RANGES = {"seed": (1, 999), "water_quota_m3": (30000.0, 90000.0), "energy_kwh": (40000.0, 150000.0),
                 "salinity_scale": (0.5, 2.0)}


def public() -> list[dict]:
    """The library as shown to people: no hidden event schedule, only what kind of season it is."""
    return [{k: s[k] for k in ("id", "title", "difficulty", "about")} | {"limits": s["limits"], "salinity_scale": s["salinity_scale"],
             "hidden_events": len(s["perturb"])} for s in SCENARIOS]


def clamp(name: str, value) -> float:
    lo, hi = EDITOR_RANGES[name]
    v = float(value)
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return v
