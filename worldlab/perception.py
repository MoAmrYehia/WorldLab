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

# How SAM 3.1 is used on the drone frames (chosen by testing against what each frame shows):
# - plants: the frame is cut into overlapping tiles and SAM is prompted with "plant" on each, because a
#   whole frame of dense rows is mostly segmented as one canopy; a plant counts once, in the tile that
#   holds its centre. Separate plants are counted well; a closed canopy is undercounted.
# - salt: "white patch" on the whole frame finds the white salt efflorescence on the soil.
# Pest and water stress are left to Muse Spark's image diagnosis ("brown spot" also fires on soil shadows).
CONCEPTS = {"plant": "plant", "salt": "white patch"}
TILE_W, TILE_H, TILE_PAD = 240, 150, 30
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
    if data[:2] == b"\xff\xd8":                       # JPEG: read the frame header
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker, ln = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return int(w), int(h)
            i += 2 + ln
    return None


class MalformedOutput(ValueError):
    """The model answered, but not in the format we can read; never treated as 'nothing found'."""


def parse_sam_strict(text: str) -> list[dict]:
    """Like parse_sam_boxes, but an answer with content and no readable box is malformed, not a valid zero."""
    boxes = parse_sam_boxes(text or "")
    if (text or "").strip() and not boxes:
        raise MalformedOutput(f"unreadable segmentation output: {text.strip()[:80]!r}")
    return boxes


def check_diagnosis(d) -> dict:
    """Validate a structured diagnosis locally against DIAG_SCHEMA; raises MalformedOutput."""
    if not isinstance(d, dict):
        raise MalformedOutput("diagnosis is not an object")
    props = DIAG_SCHEMA["properties"]
    for k in DIAG_SCHEMA["required"]:
        if k not in d:
            raise MalformedOutput(f"diagnosis lacks {k}")
    if d["condition"] not in props["condition"]["enum"]:
        raise MalformedOutput(f"unknown condition {d['condition']!r}")
    for k, sp in props.items():
        if sp["type"] == "boolean" and not isinstance(d[k], bool):
            raise MalformedOutput(f"{k} must be true or false")
    if not isinstance(d["evidence"], str) or not d["evidence"].strip():
        raise MalformedOutput("diagnosis has no evidence")
    return {k: d[k] for k in props}


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
        text = self.client.responses_stream_text({
            "model": "sam-3.1",
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": phrase}, {"type": "input_image", "image_url": url}]}],
            "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        })
        return parse_sam_strict(text)

    def _diagnose(self, url: str, crop: str | None, ref_url: str | None = None) -> dict | None:
        cues = ("Healthy: leaves as broad and deep-green as expected for this crop. Water stress: leaves rolled into "
                "thinner, duller grey-green or olive strips than expected, older leaves yellow or brown from the tip. "
                "Pest damage: brown lesions with yellow halos, holes or ragged leaves. Salt damage: white crust on the "
                "soil, scorched leaf margins. Sparse stand: missing plants in the rows.")
        if ref_url:
            content = [{"type": "text", "text": f"Two top-down drone photos of the same drip-irrigated {crop or 'crop'} field in the UAE, "
                                                "about 15 m across, with the same plant positions. IMAGE A is what the scientist's crop model "
                                                "expects to see today if nothing is wrong (healthy plants at the predicted canopy size). "
                                                "IMAGE B is the real drone photo. Diagnose IMAGE B by comparing it with IMAGE A. " + cues +
                                                " One sentence of evidence naming the differences."},
                       {"type": "text", "text": "IMAGE A (expected):"}, {"type": "image_url", "image_url": {"url": ref_url}},
                       {"type": "text", "text": "IMAGE B (observed):"}, {"type": "image_url", "image_url": {"url": url}}]
        else:
            content = [{"type": "text", "text": f"Top-down drone photo of a drip-irrigated {crop or 'crop'} field in the UAE, about 15 m across. "
                                                "Diagnose what you see. " + cues + " One sentence of evidence."},
                       {"type": "image_url", "image_url": {"url": url}}]
        msg = self.client.chat([{"role": "user", "content": content}],
                               response_format={"type": "json_schema", "json_schema": {"name": "FieldDiagnosis", "schema": DIAG_SCHEMA}})
        try:
            return check_diagnosis(json.loads(msg.get("content") or ""))
        except json.JSONDecodeError as e:
            raise MalformedOutput(f"diagnosis is not JSON ({e.msg})") from None

    def _tiles(self, frame: bytes):
        """Overlapping tiles of the frame as data URLs, with the core region each one owns."""
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(frame)).convert("RGB")
        W, H = im.size
        out = []
        for y0 in range(0, H, TILE_H):
            for x0 in range(0, W, TILE_W):
                bx = (max(x0 - TILE_PAD, 0), max(y0 - TILE_PAD, 0), min(x0 + TILE_W + TILE_PAD, W), min(y0 + TILE_H + TILE_PAD, H))
                buf = io.BytesIO()
                im.crop(bx).save(buf, "JPEG", quality=90)
                out.append(("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), bx,
                            (x0, y0, min(x0 + TILE_W, W), min(y0 + TILE_H, H))))
        return out

    def analyze(self, frame: bytes, mime: str, farm=None, i: int | None = None, reference: bytes | None = None) -> dict:
        """reference: the frame the scientist's model expects (same plant positions, no faults), if any."""
        url = f"data:{mime};base64,{base64.b64encode(frame).decode()}"
        ref_url = f"data:{mime};base64,{base64.b64encode(reference).decode()}" if reference else None
        size = image_size(frame) or (960, 600)
        from concurrent.futures import ThreadPoolExecutor
        errors: list[str] = []                         # this frame's problems only
        a0 = self.client.attempts

        def sam(args):
            phrase, u = args
            try:
                return "ok", self._sam(u, phrase)
            except MalformedOutput as e:
                errors.append(f"SAM 3.1 '{phrase}': {e}")
                return "malformed", []
            except APIError as e:
                errors.append(f"SAM 3.1 '{phrase}': {str(e)[:120]}")
                return "unavailable", []
        crop = farm.plan[i]["crop"] if farm is not None and farm.plan and i is not None else None
        cereal = crop in ("wheat", "rice", "millet")       # drilled cereals form rows, not countable plants
        try:
            tiles = [] if cereal else self._tiles(frame)
        except Exception as e:                              # undecodable frame: whole-frame counting only
            errors.append(f"tiling: {e}")
            tiles = [(url, (0, 0, size[0], size[1]), (0, 0, size[0], size[1]))]
        jobs = [(CONCEPTS["plant"], t[0]) for t in tiles] + [(CONCEPTS["salt"], url)]
        with ThreadPoolExecutor(8) as ex:
            found = list(ex.map(sam, jobs))
        objects = []
        tiles_ok = 0
        for (turl, (ox, oy, _, _), (cx0, cy0, cx1, cy1)), (st, boxes) in zip(tiles, found[:len(tiles)]):
            tiles_ok += st == "ok"
            for b in boxes:
                x0, y0, x1, y1 = b["box"][0] + ox, b["box"][1] + oy, b["box"][2] + ox, b["box"][3] + oy
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                if cx0 <= mx < cx1 and cy0 <= my < cy1 and (x1 - x0) * (y1 - y0) < 0.5 * TILE_W * TILE_H:
                    objects.append({"label": "plant", "box": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)], "score": b["score"]})
        salt_st, salt = found[-1]
        objects += [{"label": "salt", "box": [round(v, 1) for v in b["box"]], "score": b["score"]} for b in salt]
        n_plants = sum(o["label"] == "plant" for o in objects)
        area = sum((o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1]) for o in objects if o["label"] == "plant")
        salt_area = sum((o["box"][2] - o["box"][0]) * (o["box"][3] - o["box"][1]) for o in objects if o["label"] == "salt")
        # plant count: valid (every tile answered), partial (a lower bound), unavailable, or not counted (cereal)
        if cereal:
            plant_status, plants = "not_counted", None
        elif tiles_ok == len(tiles):
            plant_status, plants = "valid", n_plants
        elif tiles_ok:
            plant_status, plants = "partial", n_plants
        else:
            plant_status, plants = ("malformed" if any(st == "malformed" for st, _ in found[:len(tiles)]) else "unavailable"), None
        salt_status = "valid" if salt_st == "ok" else salt_st
        diag, diag_status = None, "unavailable"
        try:
            diag, diag_status = self._diagnose(url, crop, ref_url), "valid"
        except MalformedOutput as e:
            diag_status = "malformed"
            errors.append(f"Muse Spark diagnosis: {e}")
        except (APIError, KeyError, IndexError, TypeError) as e:
            errors.append(f"Muse Spark diagnosis: {str(e)[:120]}")
        parts = [plant_status if plant_status != "not_counted" else "valid", salt_status, diag_status]
        overall = "complete" if all(p == "valid" for p in parts) else "unavailable" if all(p != "valid" and p != "partial" for p in parts) else "partial"
        self.errors += errors
        models = [m for m, ok in (("SAM 3.1", plant_status in ("valid", "partial") or salt_status == "valid"), ("Muse Spark", diag_status == "valid")) if ok]
        return {"source": " + ".join(models) if models else "perception unavailable", "perception_status": overall,
                "image_provenance": "synthetic render of the simulator's state (not a real camera)",
                "plants_counted": plants, "plant_count_status": plant_status,
                "plant_tiles_answered": f"{tiles_ok}/{len(tiles)}" if tiles else None,
                "salt_crust_patches": len(salt) if salt_status == "valid" else None, "salt_status": salt_status,
                "salt_box_cover_pct": round(100 * salt_area / (size[0] * size[1]), 1) if salt_status == "valid" else None,
                "plant_box_cover_pct": round(100 * area / (size[0] * size[1]), 1) if plant_status in ("valid", "partial") else None,
                "sam_prompts": {"plant": f"'{CONCEPTS['plant']}' on {len(tiles)} tiles" if tiles else "not counted", "salt": f"'{CONCEPTS['salt']}' on the frame"},
                "counting_note": ("drilled cereal: plants are not counted one by one" if cereal else
                                  "a lower bound: some image tiles got no answer" if plant_status == "partial" else
                                  "SAM counts separate plants well; a closed canopy is undercounted"),
                "diagnosis_method": "Muse Spark compares the photo with the model's expected view" if reference else "Muse Spark, photo only",
                "diagnosis": diag, "diagnosis_status": diag_status,
                "usage": {"perception_calls": self.client.attempts - a0},
                "objects": objects, "errors": errors[:4]}


class SimPerception:
    """Stands in for SAM 3.1 + Muse Spark when no API key is set: reads the simulator."""

    def analyze(self, frame: bytes, mime: str, farm=None, i: int | None = None, reference: bytes | None = None) -> dict:
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
        return {"source": "simulated perception (no API key)", "perception_status": "complete",
                "image_provenance": "synthetic render of the simulator's state (not a real camera)",
                "plants_counted": plants,
                "salt_crust_patches": int(max(0, ece - 5) * 2), "damaged_leaf_spots": int(pest * 3000),
                "diagnosis": {"condition": cond, **flags,
                              "evidence": "read from the simulator state, standing in for SAM 3.1 and Muse Spark"},
                "objects": []}
