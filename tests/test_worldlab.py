"""Run with:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from worldlab import model as M
from worldlab.agent import LLMScientist, ScriptedScientist
from worldlab.lab import Lab
from worldlab.ledger import verify
from worldlab.llm import LLMConfig
from worldlab.perception import SimPerception, parse_sam_boxes, image_size
from worldlab.rig.sim import SimRig, World
from mock_openai import MockServer


class ModelTests(unittest.TestCase):
    def test_fit_recovers_hidden_physics(self):
        r = SimRig(World())
        S = []
        r.set_heater(True)
        r.set_fan(0)
        S += r.advance(600)
        for d, dur in [(1.0, 240), (0.35, 240), (0.6, 180), (0.15, 240)]:
            r.set_fan(d)
            S += r.advance(dur)
        fits = M.fit_all(M.Data.from_samples([s.to_dict() for s in S]))
        best = fits[0]
        self.assertEqual(best.structure, "stall_power")
        for u in (0.0, 0.4, 1.0):
            k_fit = float(M.cooling_rate(best.structure, best.params(), u))
            self.assertLess(abs(k_fit - r.true_k(u)) / r.true_k(u), 0.05)

    def test_unexplored_parameters_keep_prior_uncertainty(self):
        r = SimRig(World())
        r.set_heater(True)
        S = r.advance(600)  # fan never used: k1 must stay uncertain
        f = M.fit("power", M.Data.from_samples([s.to_dict() for s in S]))
        self.assertGreater(f.sd()["k1"] / f.params()["k1"], 0.3)


class LabTests(unittest.TestCase):
    def run_scripted(self, kind, cam=True, world=None):
        r = SimRig(world or World())
        d = tempfile.mkdtemp()
        lab = Lab(r, run_dir=d, perception=SimPerception(r) if cam else None)
        if kind:
            r.schedule(kind, 2400)
        ScriptedScientist(lab).run()
        return lab, r, Path(d)

    def test_no_change_no_false_alarm(self):
        lab, r, d = self.run_scripted(None)
        self.assertEqual(len(lab.anomalies), 0)
        self.assertGreaterEqual(lab.hold_ok_s / lab.hold_done_s, 0.95)
        self.assertTrue(verify(d / "ledger.jsonl")[0])

    def test_fan_moved_detected_and_explained(self):
        lab, r, d = self.run_scripted("fan_moved")
        self.assertGreaterEqual(len(lab.anomalies), 1)
        first = lab.anomalies[0]
        self.assertLess(first["t_detected"] - r.perturbations[0]["t"], 150)
        verdicts = [e["data"] for e in lab.ledger.entries if e["kind"] == "conclusion"]
        fan = [v for v in verdicts if "fan was moved" in lab.hyps[v["hypothesis_id"]]["statement"]]
        self.assertEqual(fan[0]["verdict"], "supported")
        self.assertGreaterEqual(lab.hold_done_s, lab.goal.hold_s - 1)
        self.assertGreaterEqual(lab.hold_ok_s / lab.hold_done_s, 0.9)

    def test_heater_drift_attributed_to_heat_input(self):
        lab, r, d = self.run_scripted("heater_drift", cam=False)
        verdicts = [e["data"] for e in lab.ledger.entries if e["kind"] == "conclusion"]
        heat = [v for v in verdicts if "heat input" in lab.hyps[v["hypothesis_id"]]["statement"]]
        self.assertEqual(heat[0]["verdict"], "supported")

    def test_ambient_change_handled_by_feedback(self):
        lab, r, d = self.run_scripted("ambient_step", cam=False)
        self.assertEqual(len(lab.anomalies), 0)
        self.assertGreaterEqual(lab.hold_ok_s / lab.hold_done_s, 0.95)

    def test_ledger_detects_tampering(self):
        lab, r, d = self.run_scripted(None, cam=False)
        p = d / "ledger.jsonl"
        lines = p.read_text().splitlines()
        e = json.loads(lines[5])
        e["data"]["tampered"] = True
        lines[5] = json.dumps(e)
        p.write_text("\n".join(lines) + "\n")
        ok, msg = verify(p)
        self.assertFalse(ok)
        self.assertIn("line 6", msg)

    def test_governor_refuses_unsafe_and_over_budget(self):
        r = SimRig(World())
        lab = Lab(r)
        h = lab.record_hypothesis("a", "b", "c")["hypothesis_id"]
        out = lab.run_experiment(h, "x", steps=[{"fan_duty": 1.5, "heater_on": True, "duration_s": 60}])
        self.assertIn("refused", out)
        lab.limits.exploration_budget_J = 10
        out = lab.run_experiment(h, "x", steps=[{"fan_duty": 1.0, "heater_on": True, "duration_s": 300}])
        self.assertIn("refused", out)
        out = lab.run_experiment("H99", "x", steps=[{"fan_duty": 0.0, "heater_on": True, "duration_s": 60}])
        self.assertIn("refused", out)


class LLMLoopTests(unittest.TestCase):
    def test_agent_loop_against_mock_endpoint(self):
        srv = MockServer().start()
        try:
            r = SimRig(World())
            lab = Lab(r, perception=SimPerception(r))
            cfg = LLMConfig(base_url=srv.base_url, api_key="test", model="muse-spark-1.3",
                            reasoning_effort="medium", label="mock")
            out = LLMScientist(lab, cfg, max_turns=30).run()
            self.assertEqual(srv.errors, [])
            self.assertTrue(lab.done)
            self.assertGreaterEqual(len(lab.experiments), 2)
            self.assertTrue(any(e["kind"] == "plan_result" for e in lab.ledger.entries))
            self.assertEqual(srv.requests[0]["reasoning_effort"], "medium")
        finally:
            srv.stop()


class PerceptionTests(unittest.TestCase):
    def test_parse_sam_output(self):
        text = ("<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.9609375|><|mask;x=0;y=0;c=0.96;data=27,60,~!!!!M!0c|>"
                ",1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,48,!!!!!J|>")
        b = parse_sam_boxes(text)
        self.assertEqual(len(b), 2)
        self.assertEqual(b[0]["box"], [211, 228, 271, 255])
        self.assertAlmostEqual(b[0]["score"], 0.9609375)

    def test_png_size(self):
        r = SimRig(World())
        self.assertEqual(image_size(r.capture_frame()), (640, 400))


if __name__ == "__main__":
    unittest.main()
