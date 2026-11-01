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
    {"id": "real_weather", "title": "Real 2024–25 weather", "difficulty": "Standard",
     "about": "The season runs on the weather Al Ain actually had from October 2024 to June 2025 (NASA POWER daily data): "
              "hotter and drier than the simulator's usual climate. Soils, crop traits and faults stay simulated.",
     "perturb": [], "limits": {}, "salinity_scale": 1.0, "weather": "nasa_power_2024_25"},
    {"id": "mystery", "title": "Unknown challenge", "difficulty": "Expert",
     "about": "A hidden challenge drawn at random when the season starts, from the same families as the frozen holdout: "
              "possibly nothing, a fault, two faults, a faulty instrument, or a cause no test can establish. Revealed after the season.",
     "perturb": "drawn at start", "limits": {}, "salinity_scale": 1.0},
]

# The challenge families (frozen holdout, docs/bench/holdout). Days are season days (0 = 1 October). A field is picked
# at random among those growing a crop on the day; severities are drawn from the ranges below.
FAMILIES = ("none", "heatwave", "clog", "pest", "salinity", "compound", "sensor_bias", "blight")


def draw_challenge(rng, family: str | None = None) -> tuple[str, list[str]]:
    """One random challenge as perturbation specs. rng: random.Random (or SystemRandom for a live season)."""
    fam = family or rng.choice(FAMILIES)
    day = lambda: rng.randint(75, 150)
    pick = lambda: rng.randint(0, 99)
    if fam == "none":
        return fam, []
    if fam == "heatwave":
        return fam, [f"heatwave@{rng.randint(120, 170)}"]
    if fam == "clog":
        return fam, [f"clog@{day()}:#{pick()}:{rng.uniform(0.3, 0.65):.2f}"]
    if fam == "pest":
        return fam, [f"pest@{day()}:#{pick()}:{rng.uniform(0.015, 0.04):.3f}"]
    if fam == "salinity":
        return fam, [f"salinity@{day()}::{rng.uniform(7.0, 10.0):.1f}"]
    if fam == "compound":
        a, b = sorted(rng.sample(range(75, 160), 2))
        k = pick()
        return fam, [f"clog@{a}:#{k}:{rng.uniform(0.3, 0.65):.2f}", f"pest@{b}:#{k + 1}:{rng.uniform(0.015, 0.04):.3f}"]
    if fam == "sensor_bias":
        return fam, [f"sensor_bias@{day()}:#{pick()}:{rng.choice((-1, 1)) * rng.uniform(0.05, 0.08):.3f}"]
    if fam == "blight":
        return fam, [f"blight@{day()}:#{pick()}:{rng.uniform(0.012, 0.03):.3f}"]
    raise ValueError(fam)
BY_ID = {s["id"]: s for s in SCENARIOS}

# What a person may change in the farm editor, and the allowed ranges (validated on the server).
EDITOR_RANGES = {"seed": (1, 999), "water_quota_m3": (30000.0, 90000.0), "energy_kwh": (40000.0, 150000.0),
                 "salinity_scale": (0.5, 2.0)}


def public() -> list[dict]:
    """The library as shown to people: no hidden event schedule, only what kind of season it is."""
    return [{k: s[k] for k in ("id", "title", "difficulty", "about")} | {"limits": s["limits"], "salinity_scale": s["salinity_scale"],
             "hidden_events": len(s["perturb"]) if isinstance(s["perturb"], list) else "unknown"} for s in SCENARIOS]


def clamp(name: str, value) -> float:
    lo, hi = EDITOR_RANGES[name]
    v = float(value)
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return v
