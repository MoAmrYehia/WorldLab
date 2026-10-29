"""Simulated rig: a finned heatsink with a 10 W resistor, cooled by a PWM fan,
watched by a top-down camera.

The agent never sees anything in this file except what the rig interface
exposes: sensor samples and camera frames. The physics here is the hidden
"world" it has to discover. Fan placement is real geometry: moving the fan
changes both the camera image and how well the airflow couples to the
heatsink, so visual and thermal evidence stay consistent.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field, asdict

import numpy as np

from .base import Rig, Sample, Capabilities, fan_power_model
from ..pngio import encode_png


@dataclass
class World:
    k0: float = 0.0027          # natural convection + radiation, 1/s
    k_fan: float = 0.0115       # forced-convection rate at full duty, perfect aim
    u_stall: float = 0.12       # fan does not turn below this duty
    n: float = 0.8              # airflow exponent (h ~ v^0.8, turbulent)
    C: float = 92.0             # heat capacity of block + resistor, J/K
    heater_w: float = 10.0
    Ta: float = 24.0
    Ta_drift: float = 0.25      # slow ambient wander amplitude, K
    sensor_sigma: float = 0.05
    power_scale: float = 1.0
    # geometry (camera pixels, 640x400 frame)
    sink_xy: tuple = (420.0, 200.0)
    fan_xy: tuple = (250.0, 200.0)
    fan_aim_deg: float = 0.0    # 0 = pointing +x, i.e. at the heatsink
    seed: int = 7

    @staticmethod
    def randomized(seed: int) -> "World":
        r = np.random.default_rng(seed)
        return World(
            k0=float(r.uniform(0.0018, 0.0035)), k_fan=float(r.uniform(0.008, 0.016)),
            u_stall=float(r.uniform(0.05, 0.2)), n=float(r.uniform(0.6, 1.1)),
            C=float(r.uniform(70, 130)), heater_w=10.0, Ta=float(r.uniform(20, 30)),
            power_scale=float(r.uniform(0.8, 1.25)), seed=seed,
        )


def coupling(world: World) -> float:
    """Fraction of the fan's airflow that reaches the heatsink fins."""
    sx, sy = world.sink_xy
    fx, fy = world.fan_xy
    dx, dy = sx - fx, sy - fy
    dist = math.hypot(dx, dy)
    bearing = math.degrees(math.atan2(dy, dx))
    off = math.radians((world.fan_aim_deg - bearing + 180) % 360 - 180)
    aim = max(0.0, math.cos(off)) ** 2
    reach = min(1.0, 170.0 / max(dist, 1.0)) ** 1.2
    return aim * reach


class SimRig(Rig):
    def __init__(self, world: World | None = None, speed: float = 0.0, sample_period: float = 1.0):
        """speed: real-time pacing factor (0 = as fast as possible, 20 = 20x)."""
        self.w = world or World()
        self.speed = speed
        self.caps = Capabilities(simulated=True, has_heater=True, heater_w=self.w.heater_w,
                                 has_camera=True, has_power_meter=True,
                                 sample_period_s=sample_period)
        self.rng = np.random.default_rng(self.w.seed)
        self._t = 0.0
        self._T = self.w.Ta
        self._duty = 0.0
        self._heater = False
        self._heater_factor = 1.0      # hidden; perturbation "heater_drift"
        self._Ta_offset = 0.0          # measured; perturbation "ambient_step"
        self._pending: list[Sample] = []
        self._lock = threading.RLock()
        self.perturbations: list[dict] = []
        self._scheduled: list[tuple[float, str]] = []
        self.on_perturb = None  # callback(info), set by the session for the dashboard
        self._initial_geometry = (self.w.fan_xy, self.w.fan_aim_deg)

    # ------------------------------------------------------------ controls
    def now(self) -> float:
        return self._t

    def set_fan(self, duty: float) -> None:
        with self._lock:
            self._duty = float(min(max(duty, 0.0), 1.0))

    def set_heater(self, on: bool) -> None:
        with self._lock:
            self._heater = bool(on)

    def safe_state(self) -> None:
        self.set_heater(False)
        self.set_fan(1.0)

    # ------------------------------------------------------------- physics
    def _Ta(self, t: float) -> float:
        return self.w.Ta + self._Ta_offset + self.w.Ta_drift * math.sin(2 * math.pi * t / 1800.0)

    def _k(self, duty: float) -> float:
        v = max(0.0, duty - self.w.u_stall) / (1 - self.w.u_stall)
        return self.w.k0 + self.w.k_fan * coupling(self.w) * v ** self.w.n

    def _step(self, h: float) -> None:
        k = self._k(self._duty)
        q = self.w.heater_w * self._heater_factor if self._heater else 0.0
        Ta = self._Ta(self._t)
        Teq = Ta + q / (self.w.C * k)
        self._T = Teq + (self._T - Teq) * math.exp(-k * h)
        self._t += h

    def _sample(self) -> Sample:
        q = self.w.heater_w if self._heater else 0.0
        T_meas = self._T + self.rng.normal(0, self.w.sensor_sigma)
        T_meas = round(T_meas / 0.0625) * 0.0625     # DS18B20 12-bit quantisation
        Ta_meas = round((self._Ta(self._t) + self.rng.normal(0, self.w.sensor_sigma)) / 0.0625) * 0.0625
        p = fan_power_model(self._duty) * self.w.power_scale
        p = max(0.0, p + (self.rng.normal(0, 0.01) if p > 0 else 0.0))
        return Sample(t=round(self._t, 3), T_obj=T_meas, T_amb=Ta_meas, fan_duty=self._duty,
                      heater_w=q, fan_power_w=p)

    def advance(self, seconds: float) -> list[Sample]:
        out = []
        period = self.caps.sample_period_s
        n = max(1, int(round(seconds / period)))
        for _ in range(n):
            for at, kind in list(self._scheduled):
                if self._t >= at:
                    self._scheduled.remove((at, kind))
                    self.perturb(kind)
            with self._lock:
                for _ in range(4):
                    self._step(period / 4)
                s = self._sample()
                self._pending.append(s)
            out.append(s)
            if self.speed > 0:
                time.sleep(period / self.speed)
        with self._lock:
            self._pending.clear()
        return out

    def drain(self) -> list[Sample]:
        with self._lock:
            out, self._pending = self._pending, []
        return out

    # -------------------------------------------------------- perturbations
    def perturb(self, kind: str) -> dict:
        """Physical change the agent is not told about (the demo button)."""
        with self._lock:
            if kind == "fan_moved":
                # someone nudges the fan back and turns it off-axis
                self.w.fan_xy = (195.0, 275.0)
                self.w.fan_aim_deg = -48.0
                info = {"kind": kind, "coupling_now": round(coupling(self.w), 3)}
            elif kind == "fan_restored":
                self.w.fan_xy, self.w.fan_aim_deg = self._initial_geometry
                info = {"kind": kind, "coupling_now": round(coupling(self.w), 3)}
            elif kind == "ambient_step":
                self._Ta_offset += 3.0
                info = {"kind": kind, "note": "room warms by 3 K (measured by ambient sensor)"}
            elif kind == "heater_drift":
                self._heater_factor = 1.3
                info = {"kind": kind, "note": "heater delivers 30% more than commanded (hidden)"}
            else:
                raise ValueError(f"unknown perturbation {kind}")
            info["t"] = round(self._t, 1)
            self.perturbations.append(info)
        if self.on_perturb:
            self.on_perturb(info)
        return info

    def schedule(self, kind: str, at_t: float) -> None:
        """Apply a perturbation when rig time reaches at_t (benchmarks, tests)."""
        self._scheduled.append((float(at_t), kind))

    def truth(self) -> dict:
        """Hidden ground truth, for benchmarks only (never shown to the agent)."""
        d = asdict(self.w)
        d["coupling"] = coupling(self.w)
        d["heater_factor"] = self._heater_factor
        d["T_true"] = self._T
        return d

    def true_k(self, duty: float) -> float:
        return self._k(duty)

    # --------------------------------------------------------------- camera
    def capture_frame(self) -> bytes | None:
        with self._lock:
            img = render_scene(self.w, self._duty, self._t, self._heater, self._T)
        return encode_png(img)


# ------------------------------------------------------------------ renderer

W_IMG, H_IMG = 640, 400
_YY, _XX = np.mgrid[0:H_IMG, 0:W_IMG].astype(np.float32)


def _poly_mask(pts: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon on the pixel grid."""
    x, y = _XX + 0.5, _YY + 0.5
    inside = np.zeros((H_IMG, W_IMG), bool)
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cond = (y1 > y) != (y2 > y)
        xi = (x2 - x1) * (y - y1) / ((y2 - y1) + 1e-9) + x1
        inside ^= cond & (x < xi)
    return inside


def _rot(pts, cx, cy, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    P = np.asarray(pts, float)
    return np.stack([cx + P[:, 0] * c - P[:, 1] * s, cy + P[:, 0] * s + P[:, 1] * c], axis=1)


def _paint(img, mask, rgb, alpha=1.0):
    col = np.array(rgb, np.float32)
    img[mask] = img[mask] * (1 - alpha) + col * alpha


def render_scene(w: World, duty: float, t: float, heater_on: bool, T: float) -> np.ndarray:
    rng = np.random.default_rng(1234)
    # wooden bench: warm base with grain
    grain = (np.sin(_YY * 0.09 + np.sin(_XX * 0.013) * 3.0) * 0.5 + 0.5)
    base = np.stack([150 + 30 * grain, 108 + 22 * grain, 70 + 14 * grain], axis=-1)
    noise = rng.normal(0, 4, (H_IMG, W_IMG, 1))
    img = (base + noise).astype(np.float32)

    sx, sy = w.sink_xy
    # heatsink shadow, body and fins (fins run along x so the airflow passes through)
    _paint(img, _poly_mask(np.array([[sx - 58, sy - 52], [sx + 72, sy - 52], [sx + 72, sy + 66], [sx - 58, sy + 66]])), (40, 30, 20), 0.35)
    _paint(img, _poly_mask(np.array([[sx - 65, sy - 60], [sx + 65, sy - 60], [sx + 65, sy + 60], [sx - 65, sy + 60]])), (168, 172, 178))
    for k in range(-5, 6):
        y0 = sy + k * 10.5
        _paint(img, _poly_mask(np.array([[sx - 63, y0 - 2.2], [sx + 63, y0 - 2.2], [sx + 63, y0 + 2.2], [sx - 63, y0 + 2.2]])), (205, 208, 214))
    # resistor on top, glowing a little when hot
    glow = float(np.clip((T - 30) / 40, 0, 1))
    _paint(img, _poly_mask(np.array([[sx - 22, sy - 9], [sx + 22, sy - 9], [sx + 22, sy + 9], [sx - 22, sy + 9]])),
           (60 + 150 * glow, 70, 75 - 30 * glow))
    # temperature probe wire
    for i in range(40):
        px, py = sx + 30 + i * 4, sy + 40 + math.sin(i * 0.4) * 6
        _paint(img, (np.abs(_XX - px) < 2) & (np.abs(_YY - py) < 2), (30, 30, 35))

    # fan: square frame with circular opening and blades, rotated to its aim
    fx, fy = w.fan_xy
    aim = w.fan_aim_deg
    _paint(img, _poly_mask(_rot([[-12, -62], [28, -62], [28, 70], [-12, 70]], fx + 6, fy + 6, aim)), (40, 30, 20), 0.35)
    frame = _rot([[-14, -60], [14, -60], [14, 60], [-14, 60]], fx, fy, aim)
    _paint(img, _poly_mask(frame), (28, 28, 32))
    # the fan is seen from above, side-on: show the housing depth and a hub
    hub = _rot([[-9, -14], [9, -14], [9, 14], [-9, 14]], fx, fy, aim)
    _paint(img, _poly_mask(hub), (70, 70, 78))
    phase = (t * duty * 8.0) % 1.0
    for b in range(5):
        off = -48 + b * 24 + phase * 24
        if -52 < off < 52:
            blade = _rot([[-11, off - 3], [11, off + 3], [11, off + 6], [-11, off]], fx, fy, aim)
            _paint(img, _poly_mask(blade), (95, 95, 105))
    # cable from fan to the controller box
    cx, cy = 60, 340
    for i in range(60):
        a = i / 59
        px, py = fx + (cx - fx) * a, fy + (cy - fy) * a + math.sin(a * 6) * 8
        _paint(img, (np.abs(_XX - px) < 2) & (np.abs(_YY - py) < 2), (20, 20, 22))
    _paint(img, _poly_mask(np.array([[20, 315], [110, 315], [110, 380], [20, 380]])), (25, 90, 140))
    # airflow streaks when spinning
    if duty > w.u_stall + 0.02:
        a = math.radians(aim)
        for j in range(-3, 4):
            for i in range(10):
                d = 30 + i * 12 + (t * 40 * duty) % 12
                px = fx + math.cos(a) * d - math.sin(a) * j * 12
                py = fy + math.sin(a) * d + math.cos(a) * j * 12
                _paint(img, (np.abs(_XX - px) < 3) & (np.abs(_YY - py) < 1), (230, 240, 255), 0.25 * duty)
    return np.clip(img, 0, 255).astype(np.uint8)
