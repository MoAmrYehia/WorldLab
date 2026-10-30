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


class RLTests(unittest.TestCase):
    PLAN = [dict(crop="maize", sow=40, density=1, irr=0.9, desal=0.0, nfert=200, mulch=1),
            dict(crop="sweet_potato", sow=0, density=1, irr=0.9, desal=0.5, nfert=90, mulch=1)]

    def envs(self, E, seed):
        from worldlab.farm import rl
        b = {c: CropBelief(c) for c in CROPS}
        return rl.Envs(self.PLAN, [0, 1], b, E, seed=seed, quota_m3=20000, energy_kwh=30000)

    def test_untrained_policy_is_exactly_the_rule(self):
        from worldlab.farm import rl
        e = self.envs(3, 1)
        r = rl.rollout(e, np.vstack([np.zeros(rl.N_PARAMS), rl.init_params(5)]), seed=3)
        np.testing.assert_allclose(r["people"][0], r["people"][1])
        np.testing.assert_allclose(r["water"][0], r["water"][1])

    def test_training_never_returns_worse_than_the_rule_on_validation(self):
        from worldlab.farm import rl
        tr = rl.train(self.envs(4, 2), iters=6, pairs=4, val_envs=self.envs(4, 3), val_every=3)
        rv = rl.rollout(self.envs(4, 3), np.vstack([np.zeros(rl.N_PARAMS), tr["theta"]]), seed=99)
        self.assertGreaterEqual(rv["reward"][1].mean() + 1e-9, rv["reward"][0].mean())
        pol = rl.Policy(tr["theta"], rl.crop_meta(self.PLAN, None, 4.5), [0, 1])
        mult, desal = pol.act(60, np.array([0.3, 0.4]), np.array([0.4, 0.5]), np.array([[0.15, 0.14]] * 2),
                              np.array([3.0, 4.0]), 6.0, 0.3, 0.3)
        self.assertTrue(np.all((mult >= 0.54) & (mult <= 1.83)) and np.all((desal >= 0) & (desal <= 1)))

    def test_lab_trains_and_deploys_a_policy(self):
        lab = Lab(Farm(seed=11), perception=None)
        p = lab.plan_season("plan")
        self.assertIn("refused", lab.start_season(p["plan_id"], "x", controller="rl_policy"))
        t = lab.train_irrigation_policy(p["plan_id"], "learn irrigation", iterations=10)
        self.assertIn(t["recommend"], ("rule", "rl_policy"))
        self.assertTrue(lab.bus.snapshot["rl_train"] and lab.bus.snapshot["rl"])
        lab.start_season(p["plan_id"], "go", controller="rl_policy")
        while lab.phase == "season":
            r = lab.advance(60)
            if r.get("anomaly"):
                lab.dismiss_anomaly("test")
        self.assertEqual(lab.controller, "rl_policy")
        self.assertTrue(lab.policy_trace)
        day = lab.bus.snapshot["days"][-1]
        self.assertEqual(len(day["world"]), len(FIELDS))
        self.assertLessEqual(lab.water_used, lab.limits.water_quota_m3 * 1.05)


class AccountTests(unittest.TestCase):
    def test_signup_login_and_sessions(self):
        from worldlab.accounts import Accounts, AuthError
        acc = Accounts(":memory:")
        u = acc.signup("Mo@Example.com", "longenough1", "Mo")
        self.assertEqual(u["email"], "mo@example.com")
        with self.assertRaises(AuthError):
            acc.signup("mo@example.com", "longenough1", "Mo again")
        with self.assertRaises(AuthError):
            acc.signup("x@example.com", "short", "X")
        with self.assertRaises(AuthError):
            acc.login("mo@example.com", "wrong-password")
        self.assertEqual(acc.login("mo@example.com", "longenough1")["id"], u["id"])
        tok = acc.new_session(u["id"])
        self.assertEqual(acc.user_for(tok)["name"], "Mo")
        stored = acc.db.execute("SELECT token FROM sessions").fetchone()[0]
        self.assertNotEqual(stored, tok)                      # only a digest is stored
        acc.end_session(tok)
        self.assertIsNone(acc.user_for(tok))


class CropChoiceTests(unittest.TestCase):
    def test_plan_keeps_the_farmers_crops_and_reports_the_alternative(self):
        lab = Lab(Farm(seed=7))
        lab.set_crop_choices([{"mode": "crop", "crop": "wheat", "season": "winter"}, {"mode": "fallow"}, None,
                              {"mode": "crop", "crop": "sorghum", "season": "late_winter"}, None, None])
        p = lab.plan_season("test")
        f = {x["field"]: x for x in p["fields"]}
        self.assertEqual(f["F1"]["crop"], "wheat")
        self.assertGreaterEqual(f["F1"]["mgmt"]["sow"], 46)
        self.assertIsNone(f["F2"]["crop"])
        self.assertEqual(f["F4"]["crop"], "sorghum")
        self.assertGreaterEqual(p["scientist_choice"]["people_p10"], p["people_p10"] - 1e-6)

    def test_out_of_season_crop_is_refused(self):
        from worldlab.lab import normalize_choices
        with self.assertRaises(ValueError):
            normalize_choices([{"mode": "crop", "crop": "rice", "season": "autumn"}])
        from worldlab.farm.seasons import crops_for
        self.assertIn("wheat", crops_for("winter"))
        self.assertNotIn("rice", crops_for("winter"))


class ServerTests(unittest.TestCase):
    def test_accounts_pages_and_a_run_over_http(self):
        import http.cookiejar
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from worldlab.server import App, make_handler
        from worldlab.session import Settings
        app = App(Settings(agent="scripted", speed=0, perception="sim"), tempfile.mkdtemp())
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        def post(path, body, headers=None):
            req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
            try:
                with op.open(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.build_opener(NoRedirect).open(base + "/app")
            self.assertEqual(cm.exception.code, 302)
            self.assertEqual(urllib.request.urlopen(base + "/").status, 200)
            self.assertEqual(post("/api/start", {})[0], 401)
            st, d = post("/api/auth/signup", {"name": "Mo", "email": "mo@example.com", "password": "longenough1"})
            self.assertEqual(st, 200, d)
            self.assertEqual(post("/api/start", {}, {"Origin": "http://evil.example"})[0], 403)
            st, d = post("/api/start", {"agent": "scripted", "choices": [{"mode": "crop", "crop": "rice", "season": "autumn"}]})
            self.assertEqual(st, 400)
            st, d = post("/api/start", {"agent": "scripted", "speed": 60, "choices": [{"mode": "crop", "crop": "maize", "season": "autumn"}]})
            self.assertEqual(st, 200, d)
            app.slot(1).session.thread.join(timeout=600)
            with op.open(base + "/api/runs") as r:
                runs = json.loads(r.read())["runs"]
            self.assertEqual(runs[0]["result"]["people_fed"] > 0, True)
            self.assertEqual(runs[0]["choices"][0]["crop"], "maize")
            with op.open(base + f"/api/runs/{runs[0]['id']}/replay") as r:
                self.assertTrue(json.loads(r.read())["messages"])
        finally:
            httpd.shutdown()


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


class ProgressionTests(unittest.TestCase):
    """Missions and achievements come only from ledger events; rewards can't be farmed by replaying."""

    @classmethod
    def setUpClass(cls):
        from worldlab.session import Session, Settings
        sess = Session(Settings(agent="scripted", seed=7, speed=0, perturb=["clog@90"], perception="sim",
                                runs_dir=tempfile.mkdtemp()))
        sess.start()
        sess.thread.join(600)
        assert sess.error is None, sess.error
        cls.lab, cls.farm, cls.dir = sess.lab, sess.farm, sess.run_dir

    def test_missions_follow_the_ledger(self):
        from worldlab.progression import evaluate
        ev = evaluate(self.lab.ledger.entries, list(self.farm.events), self.lab.result)
        self.assertEqual([c["id"] for c in ev["chapters"]], ["discover", "strategize", "survive", "recover", "harvest"])
        self.assertTrue(ev["complete"])
        ids = {a["id"] for a in ev["achievements"]}
        self.assertTrue({"first_sprout", "scientific_detective", "resilience_architect", "harvest_guardian"} <= ids)
        fault = ev["metrics"]["faults"][0]
        self.assertTrue(fault["detected"] and fault["diagnosed"] and fault["recovered"])
        for a in ev["achievements"]:
            self.assertTrue(a["evidence"])
        # before anything happens nothing is earned
        empty = evaluate([], [], None)
        self.assertEqual(empty["achievements"], [])
        self.assertEqual(empty["current_chapter"], "discover")
        self.assertFalse(empty["complete"])

    def test_an_undetected_fault_earns_no_detective_badge(self):
        from worldlab.progression import evaluate
        entries = [e for e in self.lab.ledger.entries if e["kind"] not in ("anomaly", "field_test", "look", "conclusion", "adjust", "model_update")]
        ev = evaluate(entries, list(self.farm.events), self.lab.result)
        ids = {a["id"] for a in ev["achievements"]}
        self.assertNotIn("scientific_detective", ids)
        self.assertNotIn("resilience_architect", ids)
        self.assertFalse(ev["metrics"]["faults"][0]["detected"])

    def test_award_is_once_per_scenario(self):
        from worldlab.progression import evaluate, award, scenario_key, level_for
        ev = evaluate(self.lab.ledger.entries, list(self.farm.events), self.lab.result)
        key = scenario_key(7, [])
        first = award({}, ev, key)
        self.assertGreater(first["gained"], 0)
        self.assertEqual(len(first["new_achievements"]), len(ev["achievements"]))
        again = award(first["progress"], ev, key)
        self.assertEqual(again["gained"], 0)
        self.assertEqual(again["new_achievements"], [])
        self.assertEqual(again["progress"]["xp"], first["progress"]["xp"])
        # a different scenario earns season XP again, but no repeated achievements
        other = award(first["progress"], ev, scenario_key(8, []))
        self.assertGreater(other["gained"], 0)
        self.assertEqual(other["new_achievements"], [])
        self.assertEqual(level_for(0)["level"], 1)
        self.assertEqual(level_for(100)["level"], 2)
        self.assertEqual(level_for(399)["level"], 2)

    def test_account_progress_persists(self):
        from worldlab.accounts import Accounts
        from worldlab.progression import evaluate, award, scenario_key
        acc = Accounts(Path(tempfile.mkdtemp()) / "a.db")
        uid = acc.signup("ada@example.com", "a long passphrase", "Ada")["id"]
        ev = evaluate(self.lab.ledger.entries, list(self.farm.events), self.lab.result)
        r = award(acc.progress(uid), ev, scenario_key(7, []))
        acc.save_progress(uid, r["progress"])
        self.assertEqual(acc.progress(uid)["xp"], r["progress"]["xp"])
        self.assertEqual(set(acc.progress(uid)["achievements"]), {a["id"] for a in ev["achievements"]})

    def test_replay_carries_mission_events(self):
        from worldlab.replay import build
        data = build(self.dir)
        kinds = [m["kind"] for m in data["messages"]]
        self.assertIn("mission", kinds)
        last = [m for m in data["messages"] if m["kind"] == "mission"][-1]["data"]
        self.assertTrue(last["complete"])
        day = next(m["data"] for m in data["messages"] if m["kind"] == "day")
        for k in ("u2", "clearness", "world", "water_used_m3", "energy_used_kwh"):
            self.assertIn(k, day)
        self.assertTrue(0 <= day["clearness"] <= 1)


if __name__ == "__main__":
    unittest.main()
