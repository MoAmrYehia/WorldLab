"""Snapshot the season calendar for the landing page (works on static hosts too)."""
import json
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from pathlib import Path
from statistics import median

from worldlab.farm import seasons as SZ
from worldlab.farm.crops import CROPS

rows = {}
guides = {}
for s in SZ.SEASONS:
    guides[s["id"]] = SZ.crop_guide(s["id"])
    for c in guides[s["id"]]["crops"]:
        r = rows.setdefault(c["crop"], {"crop": c["crop"], "label": c["label"], "good_for": c["good_for"],
                                        "salt_threshold_ds_m": c["salt_threshold_ds_m"], "windows": []})
        r["windows"].append({"season": s["id"], "sow": c["sow_window"], "cycle_days": c["cycle_days"],
                             "yield_t_ha_p50": round(median(f["yield_t_ha_p50"] for f in c["fields"]), 1)})
from worldlab.farm.world import FIELDS, FIELD_HA, EC_GROUNDWATER
from worldlab.farm.sim import EC_DESAL
SOIL = {"loamy_sand": "loamy sand", "sandy_loam": "sandy loam", "sand": "sand", "loam": "loam"}
fields = [{"id": f["id"], "name": f["name"], "soil": SOIL.get(f["layers"][0], f["layers"][0]), "area_ha": FIELD_HA,
           "ece_top": f["ece"][0], "ece_layers": f["ece"]} for f in FIELDS]
assumptions = {"irrigation_water_ec_ds_m": EC_GROUNDWATER, "desal_water_ec_ds_m": EC_DESAL,
               "management": "Previews use published crop values (no local calibration), sowing mid-window, irrigation at 90% of crop demand, "
                             "groundwater only (no desalinated blend), the crop's recommended nitrogen and mulch. The scientist's plan can change all of these.",
               "yield_basis": "fresh weight, t/ha, median of 10 simulated weather years (10th to 90th percentile in brackets)"}
out = {"seasons": SZ.SEASONS, "summer": SZ.SUMMER, "crops": list(rows.values()), "guides": guides,
       "fields": fields, "assumptions": assumptions}
p = Path(__file__).resolve().parent.parent / "worldlab" / "site" / "seasons.json"
p.write_text(json.dumps(out, indent=1))
print(p, len(rows), "crops")
