"""Drone-image perception for the farm.

MetaPerception: SAM 3.1 finds plants (stand count, canopy footprint), white salt
crust and brown damaged leaves by noun phrase; Muse Spark looks at the same
image and returns a structured stress diagnosis. SimPerception reads the
simulator's state instead, so everything runs without an API key; its output
is always labelled as simulated.
"""
from __future__ import annotations

import base64
import json
import re
import struct

from .llm import LLMClient, LLMConfig, responses_text, APIError

CONCEPTS = {"plant": "green plant", "salt": "white salt crust", "damage": "brown leaf damage"}
_BOX = re.compile(r"(\d+)<\|box;([^|]*)\|>")
DIAG_SCHEMA = {"type": "object", "properties": {
    "condition": {"type": "string", "enum": ["healthy", "water_stress", "pest_damage", "salt_damage", "sparse_stand", "mixed", "harvested_or_bare"]},
    "pest_damage_visible": {"type": "boolean"},
    "salt_crust_visible": {"type": "boolean"},
    "wilting_or_yellowing": {"type": "boolean"},
    "gaps_in_stand": {"type": "boolean"},
    "evidence": {"type": "string"}},
    "required": ["condition", "pest_damage_visible", "salt_crust_visible", "wilting_or_yellowing", "gaps_in_stand", "evidence"]}


def image_size(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    return None


def parse_sam_boxes(text: str) -> list[dict]:
    """SAM 3.1 special-token output -> boxes (masks are not needed here).
    <Nf>id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;...|>,..."""
    out = []
    for m in _BOX.finditer(text):
        f = {}
        for kv in m.group(2).split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    f[k.strip()] = float(v)
                except ValueError:
                    pass
        if all(k in f for k in ("x1", "y1", "x2", "y2")):
            out.append({"id": m.group(1), "box": [f["x1"], f["y1"], f["x2"] + 1, f["y2"] + 1], "score": f.get("c")})
    return out


class MetaPerception:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient(LLMConfig.meta_vision())
        self.errors: list[str] = []

    def _sam(self, url: str, phrase: str) -> list[dict]:
        resp = self.client.responses({
            "model": "sam-3.1",
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": phrase}, {"type": "input_image", "image_url": url}]}],
            "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        })
        return parse_sam_boxes(responses_text(resp))

    def _diagnose(self, url: str, crop: str | None) -> dict | None:
        msg = self.client.chat([{"role": "user", "content": [
            {"type": "text", "text": f"Top-down drone image of a drip-irrigated {crop or 'crop'} field in the UAE. "
                                     "Diagnose what you see: healthy canopy, water stress (yellowing, wilting), pest "
                                     "damage (brown spots, holes), salt damage (white crust on soil, scorched plants), "
                                     "or a sparse stand. One sentence of evidence."},
            {"type": "image_url", "image_url": {"url": url}}]}],
            response_format={"type": "json_schema", "json_schema": {"name": "FieldDiagnosis", "schema": DIAG_SCHEMA}})
        return json.loads(msg.get("content") or "{}")

    def analyze(self, frame: bytes, mime: str, farm=None, i: int | None = None) -> dict:
        url = f"data:{mime};base64,{base64.b64encode(frame).decode()}"
        size = image_size(frame) or (640, 400)
        objects, counts = [], {}
        for key, phrase in CONCEPTS.items():
            try:
                boxes = self._sam(url, phrase)
            except APIError as e:
                self.errors.append(f"sam {key}: {e}")
                boxes = []
            counts[key] = len(boxes)
            objects += [{"label": key, "box": [round(v, 1) for v in b["box"]], "score": b["score"]} for b in boxes]
        area = sum((o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1]) for o in objects if o["label"] == "plant")
        diag = None
        try:
            crop = farm.plan[i]["crop"] if farm is not None and farm.plan else None
            diag = self._diagnose(url, crop)
        except (APIError, json.JSONDecodeError) as e:
            self.errors.append(f"diagnosis: {e}")
        return {"source": "SAM 3.1 + Muse Spark", "plants_counted": counts.get("plant", 0),
                "salt_crust_patches": counts.get("salt", 0), "damaged_leaf_spots": counts.get("damage", 0),
                "plant_box_cover_pct": round(100 * area / (size[0] * size[1]), 1),
                "diagnosis": diag, "objects": objects, "errors": self.errors[-3:]}


class SimPerception:
    """Stands in for SAM 3.1 + Muse Spark when no API key is set: reads the simulator."""

    def analyze(self, frame: bytes, mime: str, farm=None, i: int | None = None) -> dict:
        s = farm.sim
        crop = farm.plan[i]["crop"]
        stand = float(s.stand[i])
        ksw = float(s.ks_w[i])
        ece = float(s.ece_layers()[i, 0])
        pest = float(farm.pest[i, max(farm.day - 1, 0)])
        done = bool(s.done[i])
        plants = 0 if (done or not crop or s.cc[i] <= 0.005) else int(round(150 * stand))
        flags = {"pest_damage_visible": pest > 0.004, "salt_crust_visible": ece > 5,
                 "wilting_or_yellowing": ksw < 0.6, "gaps_in_stand": stand < 0.9}
        n_true = sum(flags.values())
        cond = "harvested_or_bare" if plants == 0 else ("healthy" if n_true == 0 else "mixed" if n_true > 1 else
                {"pest_damage_visible": "pest_damage", "salt_crust_visible": "salt_damage",
                 "wilting_or_yellowing": "water_stress", "gaps_in_stand": "sparse_stand"}[next(k for k, v in flags.items() if v)])
        return {"source": "simulated perception (no API key)", "plants_counted": plants,
                "salt_crust_patches": int(max(0, ece - 5) * 2), "damaged_leaf_spots": int(pest * 3000),
                "diagnosis": {"condition": cond, **flags,
                              "evidence": "read from the simulator state, standing in for SAM 3.1 and Muse Spark"},
                "objects": []}
