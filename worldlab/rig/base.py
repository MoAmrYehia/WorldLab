"""Rig interface shared by the simulator and the serial hardware driver."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict


@dataclass
class Sample:
    t: float            # rig time, seconds since rig start
    T_obj: float        # object (heatsink) temperature, C
    T_amb: float        # ambient temperature, C
    fan_duty: float     # commanded fan duty actually applied, 0..1
    heater_w: float     # heater power actually applied, W
    fan_power_w: float  # measured (or estimated) fan electrical power, W

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


@dataclass
class Capabilities:
    simulated: bool
    has_heater: bool
    heater_w: float
    has_camera: bool
    has_power_meter: bool
    sample_period_s: float


class Rig(ABC):
    caps: Capabilities

    @abstractmethod
    def now(self) -> float: ...

    @abstractmethod
    def set_fan(self, duty: float) -> None: ...

    @abstractmethod
    def set_heater(self, on: bool) -> None: ...

    @abstractmethod
    def advance(self, seconds: float) -> list[Sample]:
        """Let time pass (really, or simulated) and return every sample taken."""

    @abstractmethod
    def drain(self) -> list[Sample]:
        """Return samples collected since the last call without waiting."""

    def capture_frame(self) -> bytes | None:
        """PNG/JPEG bytes from the rig camera, or None."""
        return None

    def frame_mime(self) -> str:
        return "image/png"

    @abstractmethod
    def safe_state(self) -> None:
        """Heater off, fan to full: the state that can never overheat anything."""

    def close(self) -> None:
        pass


def fan_power_model(duty: float) -> float:
    """Typical 12 V 120 mm PWM fan: electronics overhead plus near-cubic
    aerodynamic load (fan affinity laws). Used when no power meter is fitted."""
    if duty <= 0.01:
        return 0.0
    return 0.18 + 2.3 * duty ** 2.7
