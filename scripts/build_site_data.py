"""Snapshot the season calendar for the landing page (works on static hosts too)."""
import json
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from pathlib import Path
from statistics import median

from worldlab.farm import seasons as SZ
from worldlab.farm.crops import CROPS

rows = {}
for s in SZ.SEASONS:
    for c in SZ.crop_guide(s["id"])["crops"]:
        r = rows.setdefault(c["crop"], {"crop": c["crop"], "label": c["label"], "good_for": c["good_for"],
                                        "salt_threshold_ds_m": c["salt_threshold_ds_m"], "windows": []})
        r["windows"].append({"season": s["id"], "sow": c["sow_window"], "cycle_days": c["cycle_days"],
                             "yield_t_ha_p50": round(median(f["yield_t_ha_p50"] for f in c["fields"]), 1)})
out = {"seasons": SZ.SEASONS, "summer": SZ.SUMMER, "crops": list(rows.values())}
p = Path(__file__).resolve().parent.parent / "worldlab" / "site" / "seasons.json"
p.write_text(json.dumps(out, indent=1))
print(p, len(rows), "crops")
