"""Scene perception: where are the fan and the heatsink, and is the fan aimed
at the heatsink?

MetaPerception uses SAM 3.1 (detection by noun phrase) for object boxes and
Muse Spark (image understanding with structured output) to judge the fan's
aim, which a box alone cannot show. SimPerception reads the simulator's
geometry instead; it exists so the whole system runs without an API key and
is always labelled as simulated.
"""
from __future__ import annotations

import base64
import json
import math
import re
import struct

from .llm import LLMClient, LLMConfig, responses_text, APIError

CONCEPTS = {"fan": "fan", "heatsink": "heat sink"}

_BOX = re.compile(r"(\d+)<\|box;([^|]*)\|>")


def image_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:2] == b"\xff\xd8":  # JPEG: walk segments to a SOF marker
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return int(w), int(h)
            ln = struct.unpack(">H", data[i + 2:i + 4])[0]
            i += 2 + ln
    return None


def parse_sam_boxes(text: str) -> list[dict]:
    """Parse SAM 3.1 special-token output into boxes (masks are ignored here).
    Grammar: <Nf>id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..[;c=..]|><|mask;...|>,..."""
    out = []
    for m in _BOX.finditer(text):
        fields = {}
        for kv in m.group(2).split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    fields[k.strip()] = float(v)
                except ValueError:
                    pass
        if all(k in fields for k in ("x1", "y1", "x2", "y2")):
            out.append({"id": m.group(1), "box": [fields["x1"], fields["y1"], fields["x2"] + 1, fields["y2"] + 1],
                        "score": fields.get("c")})
    return out


class MetaPerception:
    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient(LLMConfig.meta_vision())
        self.errors: list[str] = []

    def _sam(self, data_url: str, phrase: str) -> list[dict]:
        resp = self.client.responses({
            "model": "sam-3.1",
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": phrase},
                {"type": "input_image", "image_url": data_url}]}],
            "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"},
        })
        return parse_sam_boxes(responses_text(resp))

    def _spark_ground(self, data_url: str, label: str, phrase: str, size) -> dict | None:
        """Fallback: Muse Spark perception grounding on a 0-1000 grid."""
        prompt = (f'You are an object grounding expert. Provide the bounding box of "{phrase}" in the image. '
                  'Answer with x_min, y_min, x_max, y_max on a 0-1000 grid, (0,0) top-left. '
                  'Set found=false if it is not visible.')
        schema = {"type": "object", "properties": {
            "found": {"type": "boolean"}, "x_min": {"type": "integer"}, "y_min": {"type": "integer"},
            "x_max": {"type": "integer"}, "y_max": {"type": "integer"}},
            "required": ["found", "x_min", "y_min", "x_max", "y_max"]}
        msg = self.client.chat([{"role": "user", "content": [
            {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": data_url}}]}],
            response_format={"type": "json_schema", "json_schema": {"name": "Box", "schema": schema}})
        d = json.loads(msg.get("content") or "{}")
        if not d.get("found"):
            return None
        W, H = size
        return {"label": label, "box": [d["x_min"] * W / 1000, d["y_min"] * H / 1000,
                                        d["x_max"] * W / 1000, d["y_max"] * H / 1000],
                "score": None, "by": "muse-spark grounding"}

    def _aim(self, data_url: str) -> dict | None:
        schema = {"type": "object", "properties": {
            "fan_aimed_at_heatsink": {"type": "boolean"},
            "misalignment_deg_estimate": {"type": "number"},
            "description": {"type": "string"}},
            "required": ["fan_aimed_at_heatsink", "misalignment_deg_estimate", "description"]}
        msg = self.client.chat([{"role": "user", "content": [
            {"type": "text", "text": "This is a top-down camera view of a cooling experiment: a fan and a finned "
                                     "heatsink on a bench. Judge whether the fan's airflow is aimed squarely at "
                                     "the heatsink fins. Estimate the misalignment angle in degrees (0 = straight "
                                     "at it). Keep the description to one sentence."},
            {"type": "image_url", "image_url": {"url": data_url}}]}],
            response_format={"type": "json_schema", "json_schema": {"name": "Aim", "schema": schema}})
        return json.loads(msg.get("content") or "{}")

    def analyze(self, frame: bytes, mime: str) -> dict:
        size = image_size(frame) or (640, 400)
        url = f"data:{mime};base64,{base64.b64encode(frame).decode()}"
        objects, used = [], []
        for label, phrase in CONCEPTS.items():
            got = None
            try:
                boxes = self._sam(url, phrase)
                if boxes:
                    b = max(boxes, key=lambda x: (x["score"] or 0, (x["box"][2] - x["box"][0]) * (x["box"][3] - x["box"][1])))
                    got = {"label": label, "box": [round(v, 1) for v in b["box"]], "score": b["score"], "by": "sam-3.1"}
            except APIError as e:
                self.errors.append(f"sam {label}: {e}")
            if got is None:
                try:
                    got = self._spark_ground(url, label, phrase, size)
                except (APIError, json.JSONDecodeError, KeyError) as e:
                    self.errors.append(f"spark ground {label}: {e}")
            if got:
                objects.append(got)
                used.append(got["by"])
        aim = None
        try:
            aim = self._aim(url)
        except (APIError, json.JSONDecodeError) as e:
            self.errors.append(f"aim: {e}")
        return {"objects": objects, "aim": aim, "image_size": list(size),
                "source": "+".join(sorted(set(used))) or "none", "errors": self.errors[-3:]}


class SimPerception:
    """Reads the simulator's geometry, standing in for a perfect detector. Only
    used without an API key; results are labelled 'simulated perception'."""

    def __init__(self, rig):
        self.rig = rig

    def analyze(self, frame: bytes, mime: str) -> dict:
        w = self.rig.w
        fx, fy = w.fan_xy
        a = math.radians(w.fan_aim_deg)
        c, s = math.cos(a), math.sin(a)
        pts = [(fx + x * c - y * s, fy + x * s + y * c) for x, y in [(-14, -60), (14, -60), (14, 60), (-14, 60)]]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        sx, sy = w.sink_xy
        dx, dy = sx - fx, sy - fy
        bearing = math.degrees(math.atan2(dy, dx))
        off = (w.fan_aim_deg - bearing + 180) % 360 - 180
        mis = round(abs(off) / 5) * 5
        return {
            "objects": [
                {"label": "fan", "box": [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
                 "score": 0.95, "by": "simulated"},
                {"label": "heatsink", "box": [sx - 65, sy - 60, sx + 65, sy + 60], "score": 0.97, "by": "simulated"},
            ],
            "aim": {"fan_aimed_at_heatsink": mis <= 10, "misalignment_deg_estimate": mis,
                    "description": "fan points at the heatsink" if mis <= 10 else f"fan is turned about {mis} degrees away from the heatsink"},
            "image_size": [640, 400], "source": "simulated perception (no API key)",
        }
