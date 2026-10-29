"""Build a rig + lab + agent from settings, and run it on a thread."""
from __future__ import annotations

import os
import threading
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .lab import Lab, Goal, Limits, Bus, StopRequested
from .agent import LLMScientist, ScriptedScientist
from .llm import LLMConfig


@dataclass
class Settings:
    agent: str = "auto"            # auto | spark | glimmer | scripted | scripted-noadapt
    rig: str = "sim"               # sim | serial
    serial_port: str = ""
    camera_index: int = -1         # serial rig: OpenCV camera index, -1 = none
    speed: float = 20.0            # sim pacing (x real time); 0 = flat out
    seed: int = 7
    randomize: bool = False
    perturb: list = field(default_factory=list)   # ["fan_moved@2400", ...] (sim)
    perception: str = "auto"       # auto | meta | sim | none
    runs_dir: str = "runs"
    goal: dict = field(default_factory=dict)
    limits: dict = field(default_factory=dict)

    def resolved_agent(self) -> str:
        if self.agent != "auto":
            return self.agent
        return "spark" if os.environ.get("MODEL_API_KEY") else "scripted"


class Session:
    def __init__(self, settings: Settings, bus: Bus | None = None):
        self.settings = settings
        self.bus = bus or Bus()
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.result: dict | None = None
        self.agent_kind = settings.resolved_agent()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.run_dir = Path(settings.runs_dir) / f"{stamp}-{self.agent_kind}"
        self.rig = self._make_rig()
        if hasattr(self.rig, "on_perturb"):
            self.rig.on_perturb = lambda info: self.bus.publish("perturbation", info)
        perception = self._make_perception()
        self.lab = Lab(self.rig, goal=Goal(**settings.goal), limits=Limits(**settings.limits),
                       run_dir=self.run_dir, perception=perception, bus=self.bus)
        self.lab._log("session", {"agent": self.agent_kind, "rig": settings.rig,
                                  "perception": type(perception).__name__ if perception else None,
                                  "settings": {k: v for k, v in asdict(settings).items() if k != "goal"}})

    def _make_rig(self):
        s = self.settings
        if s.rig == "sim":
            from .rig.sim import SimRig, World
            world = World.randomized(s.seed) if s.randomize else World(seed=s.seed)
            rig = SimRig(world, speed=s.speed)
            for spec in s.perturb:
                kind, _, at = spec.partition("@")
                rig.schedule(kind, float(at or 2400))
            return rig
        if s.rig == "serial":
            from .rig.serial_rig import SerialRig
            return SerialRig(s.serial_port, camera_index=s.camera_index)
        raise ValueError(f"unknown rig {s.rig}")

    def _make_perception(self):
        mode = self.settings.perception
        if mode == "none":
            return None
        if mode == "auto":
            mode = "meta" if os.environ.get("MODEL_API_KEY") else ("sim" if self.settings.rig == "sim" else "none")
        if mode == "meta":
            from .perception import MetaPerception
            return MetaPerception()
        if mode == "sim" and self.settings.rig == "sim":
            from .perception import SimPerception
            return SimPerception(self.rig)
        return None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="worldlab-agent")
        self.thread.start()
        return self

    def _run(self):
        try:
            if self.agent_kind in ("spark", "glimmer"):
                self.result = LLMScientist(self.lab, LLMConfig.for_agent(self.agent_kind)).run()
            elif self.agent_kind == "scripted-noadapt":
                self.result = ScriptedScientist(self.lab, adapt=False).run()
            else:
                self.result = ScriptedScientist(self.lab).run()
        except StopRequested:
            self.lab.agent_note("system", "stopped by operator")
        except Exception:
            self.error = traceback.format_exc()
            self.lab.agent_note("error", self.error)
        finally:
            try:
                self.rig.safe_state() if not self.lab.done else None
                if not self.lab.done:
                    self.lab.finish("Run ended early: " + ("stopped by operator" if self.lab.stop_flag.is_set() else "error"))
            except Exception:
                pass

    def stop(self):
        self.lab.stop_flag.set()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())
