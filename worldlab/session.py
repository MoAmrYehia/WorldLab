"""Build a farm + lab + agent from settings, and run it on a thread."""
from __future__ import annotations

import os
import threading
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .lab import Lab, Limits, Bus, StopRequested
from .agent import LLMScientist, ScriptedScientist
from .llm import LLMConfig
from .farm.world import Farm


@dataclass
class Settings:
    agent: str = "auto"            # auto | spark | glimmer | scripted | scripted-noadapt
    seed: int = 7                  # which farm (hidden variety traits, drip efficiencies, weather year)
    speed: float = 12.0            # season pacing for the dashboard, simulated days per second (0 = flat out)
    perturb: list = field(default_factory=list)   # ["clog@80", "pest@100:F2", "salinity@60", "heatwave@170"]
    perception: str = "auto"       # auto | meta | sim | none
    runs_dir: str = "runs"
    limits: dict = field(default_factory=dict)

    def resolved_agent(self) -> str:
        if self.agent != "auto":
            return self.agent
        return "spark" if os.environ.get("MODEL_API_KEY") else "scripted"


def parse_perturb(spec: str):
    """'clog@80:F3' -> ('clog', 80, field index or None)"""
    kind, _, rest = spec.partition("@")
    day, _, fld = rest.partition(":")
    fi = None
    if fld:
        from .farm.world import FIELDS
        fi = next((i for i, f in enumerate(FIELDS) if f["id"] == fld.upper()), None)
    return kind, int(day or 80), fi


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
        self.farm = Farm(seed=settings.seed)
        self.farm.on_event = lambda info: self.bus.publish("perturbation", info)
        for spec in settings.perturb:
            kind, day, fi = parse_perturb(spec)
            self.farm.schedule(kind, day, field=fi)
        perception = self._make_perception()
        self.lab = Lab(self.farm, limits=Limits(**settings.limits), run_dir=self.run_dir,
                       perception=perception, bus=self.bus, speed=settings.speed)
        self.lab._log("session", {"agent": self.agent_kind, "farm_seed": settings.seed,
                                  "perception": type(perception).__name__ if perception else None})

    def _make_perception(self):
        mode = self.settings.perception
        if mode == "none":
            return None
        if mode == "auto":
            mode = "meta" if os.environ.get("MODEL_API_KEY") else "sim"
        if mode == "meta":
            from .perception import MetaPerception
            return MetaPerception()
        from .perception import SimPerception
        return SimPerception()

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

    def stop(self):
        self.lab.stop_flag.set()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())
