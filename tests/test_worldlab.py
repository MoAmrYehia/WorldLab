"""Run with:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from worldlab.farm import weather as WX
from worldlab.farm.belief import CropBelief, calibrate
from worldlab.farm.crops import CROPS, TRAIT_IDS
from worldlab.farm.optimize import evaluate, optimise
from worldlab.farm.sim import run_batch
from worldlab.farm.world import Farm, FIELDS
from worldlab.agent import LLMScientist, ScriptedScientist
from worldlab.lab import Lab
from worldlab.ledger import verify
from worldlab.llm import LLMConfig
from worldlab.perception import SimPerception, parse_sam_boxes
from mock_openai import MockServer


def mg(crop, **kw):
    d = {"sow": sum(CROPS[crop]["sow"]) // 2, "density": 1.0, "irr": 1.0, "desal": 0.0, "nfert": CROPS[crop]["nreq"], "mulch": 1.0}
    d.update(kw)
    return d


class CropModelTests(unittest.TestCase):
    def test_weather_and_et0_are_plausible_for_the_uae(self):
        wx = WX.generate(3, seed=1)
        self.assertTrue(2.5 < wx["et0"][:, 80:110].mean() < 4.5)    # winter
        self.assertTrue(7.0 < wx["et0"][:, 220:260].mean() < 12.0)  # May/June
        self.assertLess(wx["rain"].sum(axis=1).mean(), 200)

    def _run(self, crops, mgs, fields):
        wx = WX.generate(1, seed=3)
        m = {k: np.array([x[k] for x in mgs], float) for k in mgs[0]}
        return run_batch(crops, None, m, fields, wx, np.zeros(len(crops), int), np.full(len(crops), 4.5))

    def test_wheat_yield_and_water_in_published_range(self):
        s = self._run(["wheat"], [mg("wheat")], [FIELDS[1]])
        self.assertTrue(3.0 < s.fresh_yield()[0] < 7.0)
        self.assertTrue(2500 < s.water_m3_ha()[0] < 8000)

    def test_salt_and_water_stress_reduce_yield(self):
        s = self._run(["beans", "beans", "maize", "maize"],
                      [mg("beans"), mg("beans"), mg("maize", irr=1.0), mg("maize", irr=0.5)],
                      [FIELDS[1], FIELDS[5], FIELDS[1], FIELDS[1]])
        y = s.fresh_yield()
        self.assertLess(y[1], 0.5 * y[0])     # salt-sensitive beans on the sabkha rim
        self.assertLess(y[3], 0.85 * y[2])    # deficit irrigation

    def test_calibration_recovers_hidden_traits(self):
        farm = Farm(seed=7)
        crop = "wheat"
        trials = [{"crop": crop, "sow": s, "plot": p, "density": 1.0, "irr": 1.0, "desal": 0.0, "nfert": 180, "mulch": 1}
                  for s in (30, 75, 110) for p in ("normal", "saline")]
        res = farm.run_trials(trials)
        b = CropBelief(crop)
        prior = (b.mean.copy(), b.cov.copy())
        calibrate(b, prior, trials, res["plots"], [res["weather"]] * len(trials))
        truth = farm.traits[crop]
        self.assertLess(abs(b.mean[0] - truth["wp"]), 0.08)
        self.assertLess(abs(b.mean[1] - truth["cgc"]), 0.08)
        self.assertLess(b.sd()[3], 0.6)                       # salt tolerance learned from saline plots

    def test_optimiser_respects_the_water_quota(self):
        beliefs = {c: CropBelief(c) for c in CROPS}
        plan = optimise(evaluate(beliefs, S=12, seed=5), 45000, 90000, restarts=4)
        self.assertLessEqual(plan["water_p90_m3"], 45000 * 1.01)
        self.assertTrue(any(f["crop"] for f in plan["fields"]))


class FarmLabTests(unittest.TestCase):
    def run_scripted(self, kind, adapt=True):
        farm = Farm(seed=7)
        if kind:
            farm.schedule(kind, 90)
        d = tempfile.mkdtemp()
        lab = Lab(farm, run_dir=d, perception=SimPerception())
        ScriptedScientist(lab, adapt=adapt).run()
        return lab, farm, Path(d)

    def test_clog_is_detected_diagnosed_and_repaired(self):
        lab, farm, d = self.run_scripted("clog")
        self.assertTrue(lab.anomalies)
        a = lab.anomalies[0]
        self.assertEqual(a["field"], farm.events[0]["field"])
        self.assertLess(a["detected_day"] - 90, 40)
        sup = [h["statement"] for h in lab.hyps.values() if h["status"] == "supported" and h["phase"] == "season"]
        self.assertTrue(any("drip line" in s for s in sup))
        self.assertTrue(farm.repairs and farm.repairs[0]["was_faulty"])
        self.assertTrue(lab.result["within_quota"])
        ok, _ = verify(d / "ledger.jsonl")
        self.assertTrue(ok)

    def test_adapting_beats_ignoring_a_fault(self):
        lab1, _, _ = self.run_scripted("clog")
        lab2, _, _ = self.run_scripted("clog", adapt=False)
        self.assertGreater(lab1.result["people_fed"], lab2.result["people_fed"])

    def test_ledger_detects_tampering(self):
        farm = Farm(seed=3)
        d = Path(tempfile.mkdtemp())
        lab = Lab(farm, run_dir=d)
        lab.record_hypothesis("a", "b", "c")
        lab.plan_season("x")
        p = d / "ledger.jsonl"
        lines = p.read_text().splitlines()
        e = json.loads(lines[1])
        e["data"]["statement"] = "edited"
        lines[1] = json.dumps(e)
        p.write_text("\n".join(lines) + "\n")
        ok, msg = verify(p)
        self.assertFalse(ok)

    def test_budgets_are_enforced(self):
        lab = Lab(Farm(seed=3))
        h = lab.record_hypothesis("a", "b", "c")["hypothesis_id"]
        ev = lab.evaluate_trials([{"crop": "wheat", "sow": 40, "plot": "normal"}] * 12)
        ids = [o["candidate_id"] for o in ev["options"]]
        self.assertIn("refused", lab.run_trials(ids, h, "too many"))
        self.assertIn("refused", lab.run_trials(ids[:2], "H99", "no hypothesis"))
        self.assertIn("refused", lab.advance(10))


class LLMLoopTests(unittest.TestCase):
    def test_agent_loop_against_mock_endpoint(self):
        srv = MockServer().start()
        try:
            farm = Farm(seed=7)
            farm.schedule("clog", 90)
            lab = Lab(farm, perception=SimPerception())
            cfg = LLMConfig(base_url=srv.base_url, api_key="test", model="muse-spark-1.3", reasoning_effort="medium", label="mock")
            LLMScientist(lab, cfg, max_turns=60).run()
            self.assertEqual(srv.errors, [])
            self.assertTrue(lab.done)
            self.assertEqual(lab.plots_used, 4)
            self.assertIsNotNone(lab.result)
            self.assertEqual(srv.requests[0]["reasoning_effort"], "medium")
        finally:
            srv.stop()


class PerceptionTests(unittest.TestCase):
    def test_parse_sam_output(self):
        text = ("<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.96|><|mask;x=0;y=0;data=27,60,!!!!M|>"
                ",1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,48,!!!!!J|>")
        b = parse_sam_boxes(text)
        self.assertEqual(len(b), 2)
        self.assertEqual(b[0]["box"], [211, 228, 271, 255])

    def test_drone_image_is_a_png(self):
        farm = Farm(seed=7)
        farm.start_season([{"crop": "wheat", **mg("wheat")}] + [{"crop": None, "sow": 0, "density": 1, "irr": 0, "desal": 0, "nfert": 0, "mulch": 0}] * 5)
        for d in range(80):
            farm.step(farm.sim.irrigation_demand(d))
        self.assertEqual(farm.image(0)[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
