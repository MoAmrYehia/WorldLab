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
    agent: str = "auto"            # auto | spark | glimmer | scripted | scripted-rl | scripted-noadapt
    seed: int = 7                  # which farm (hidden variety traits, drip efficiencies, weather year)
    speed: float = 12.0            # season pacing for the dashboard, simulated days per second (0 = flat out)
    perturb: list = field(default_factory=list)   # ["clog@80", "pest@100:F2", "salinity@60", "heatwave@170"]
    perception: str = "auto"       # auto | meta | sim | none
    runs_dir: str = "runs"
    limits: dict = field(default_factory=dict)
    choices: list = field(default_factory=list)   # the farmer's crop per field: see Lab.set_crop_choices
    scenario: str = ""             # a named scenario from worldlab.scenarios (sets perturb, limits, starting salt)
    salinity_scale: float = 1.0    # starting soil salinity relative to the standard farm
    soil: list | None = None       # per-field starting salt by layer [[ece x3] x6], e.g. carried over from last season
    human: bool = False            # human decision mode: pause for the person at tests and repairs
    parent_run: int | None = None  # the run this one branches from (one input changed)
    change: dict | None = None     # what was changed from the parent

    def resolved_agent(self) -> str:
        if self.agent != "auto":
            return self.agent
        return "spark" if os.environ.get("MODEL_API_KEY") else "scripted-rl"


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
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.bus.record_to(self.run_dir / "events.jsonl")
        from .farm.world import FIELDS
        fields = [dict(f, ece=[round(v * settings.salinity_scale, 2) for v in f["ece"]]) for f in FIELDS]
        if settings.soil:
            for f, ece in zip(fields, settings.soil):
                f["ece"] = [round(float(v), 2) for v in ece][:3]
        self.farm = Farm(seed=settings.seed, fields=fields)
        self.farm.on_event = lambda info: self.bus.publish("perturbation", info)
        for spec in settings.perturb:
            kind, day, fi = parse_perturb(spec)
            self.farm.schedule(kind, day, field=fi)
        perception = self._make_perception()
        self.lab = Lab(self.farm, limits=Limits(**settings.limits), run_dir=self.run_dir,
                       perception=perception, bus=self.bus, speed=settings.speed)
        self.lab.human = bool(settings.human)
        import json as _json
        (self.run_dir / "settings.json").write_text(_json.dumps(asdict(settings), default=str, indent=1))
        self.lab._log("session", {"agent": self.agent_kind, "farm_seed": settings.seed,
                                  "perception": type(perception).__name__ if perception else None,
                                  "scenario": settings.scenario or None, "salinity_scale": settings.salinity_scale,
                                  "soil_carried_over": bool(settings.soil), "human_mode": bool(settings.human),
                                  "budget_mode": "hard" if self.lab.limits.hard_budget else "soft",
                                  "parent_run": settings.parent_run, "change": settings.change})
        if settings.choices:
            self.lab.set_crop_choices(settings.choices)
        self.on_finish = None

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
            elif self.agent_kind == "scripted-rl":
                self.result = ScriptedScientist(self.lab, rl=True).run()
            else:
                self.result = ScriptedScientist(self.lab).run()
        except StopRequested:
            self.lab.agent_note("system", "stopped by operator")
        except Exception:
            self.error = traceback.format_exc()
            self.lab.agent_note("error", self.error)
        finally:
            try:                                   # the true soil at the end, for a next season on the same farm
                import json as _json
                (self.run_dir / "soil_end.json").write_text(_json.dumps([f["ece"] for f in self.farm.soil_state()]))
            except Exception:
                pass
            if self.on_finish:
                try:
                    self.on_finish(self)
                except Exception:
                    pass

    def stop(self):
        self.lab.stop_flag.set()

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())
