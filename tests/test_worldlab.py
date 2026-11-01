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
        refused = [e for e in lab.ledger.entries if e["kind"] == "agent_step" and "invalid arguments" in str(e["data"])]
        self.assertEqual(refused, [])                                   # the protocol's own calls pass validation
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
            self.assertEqual(lab.run_status, "completed")                 # a normal run still completes
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
        lab.start_season(p["plan_id"], "go", controller="rl_policy", accept_nutrient_risk="test")
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
            with urllib.request.urlopen(base + "/api/capabilities") as r:      # no account needed
                capd = json.loads(r.read())
            self.assertEqual(capd["service"], "ok")
            self.assertTrue(capd["agents"]["scripted"])
            self.assertEqual(capd["budget_mode"], "hard")
            for name in ("favicon.ico", "og-image.jpg", "site.webmanifest", "hero-still.jpg"):
                self.assertEqual(urllib.request.urlopen(f"{base}/{name}").status, 200)
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

    def test_frames_report_what_they_show_and_sam_is_scored(self):
        from worldlab.farm.world import render_field
        t = {}
        render_field("maize", 0.6, 0.8, 0.9, 11.0, 0.01, False, seed=3, truth=t)
        self.assertGreater(t["plants"], 50)
        self.assertGreater(t["salt_patches"], 0)
        self.assertGreater(t["damaged_plants"], 0)
        clean = {}
        render_field("maize", 0.6, 1.0, 1.0, 2.0, 0.0, False, seed=3, truth=clean)
        self.assertEqual((clean["salt_patches"], clean["damaged_plants"]), (0, 0))
        lab = Lab(Farm(seed=7), run_dir=tempfile.mkdtemp(), perception=SimPerception())
        self.assertIsNone(lab.perception_summary())                 # simulated perception isn't scored
        t["crop"], clean["crop"] = "maize", "maize"
        t["separate_plants"] = clean["separate_plants"] = True
        lab.perception_checks = [{"day": 100, "field": "F1", "drawn": t, "sam": {"plants": t["plants"] - 10, "salt_patches": 2}, "diagnosis": {"pest_damage_visible": True}},
                                 {"day": 100, "field": "F2", "drawn": clean, "sam": {"plants": clean["plants"], "salt_patches": 0}, "diagnosis": {"pest_damage_visible": False}}]
        ps = lab.perception_summary()
        self.assertEqual((ps["salt_frames_detected_by_sam"], ps["salt_false_alarms_by_sam"]), ("1/1", "0/1"))
        self.assertEqual((ps["pest_frames_flagged_by_spark"], ps["pest_false_alarms_by_spark"]), ("1/1", "0/1"))
        self.assertLess(ps["plant_count_ratio_pct"], 100)

    def test_drone_image_is_a_png(self):
        farm = Farm(seed=7)
        farm.start_season([{"crop": "wheat", **mg("wheat")}] + [{"crop": None, "sow": 0, "density": 1, "irr": 0, "desal": 0, "nfert": 0, "mulch": 0}] * 5)
        for d in range(80):
            farm.step(farm.sim.irrigation_demand(d))
        img = farm.image(0)
        self.assertIn(img[:2], (b"\xff\xd8", b"\x89P"))                 # JPEG (or PNG without Pillow)
        from worldlab.perception import image_size
        self.assertEqual(image_size(img), (960, 600))


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

    def test_delegated_and_fault_free_seasons_complete_coherently(self):
        from worldlab.progression import evaluate
        ev = evaluate(self.lab.ledger.entries, list(self.farm.events), self.lab.result)
        ch = {c["id"]: c for c in ev["chapters"]}
        # the farmer left every crop to the scientist and the farm goal may be missed: chapters still complete
        self.assertEqual(ch["strategize"]["status"], "done")
        self.assertEqual(ch["harvest"]["status"], "done")
        self.assertTrue(ev["outcome"].startswith("Season complete"))
        kinds = {o["label"]: o["kind"] for c in ev["chapters"] for o in c["objectives"]}
        self.assertEqual(kinds["Choose your own crops"], "optional")
        self.assertEqual(kinds["Farm goal: feed 500 people"], "stretch")
        clean = evaluate(self.lab.ledger.entries, [], self.lab.result)          # no hidden fault
        self.assertEqual({c["id"]: c for c in clean["chapters"]}["recover"]["status"], "na")
        self.assertEqual(len(ev["catalog"]), 7)
        self.assertTrue(all(c["about"] for c in ev["catalog"]))

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
        frames = [m["data"] for m in data["messages"] if m["kind"] == "drone_frame"]
        self.assertTrue(frames)
        self.assertTrue(frames[0]["image"].startswith(("data:image/jpeg;base64,", "data:image/png;base64,")))
        self.assertIn("canopy_cover_measured", frames[0])
        calls = [m["data"]["data"] for m in data["messages"] if m["kind"] == "ledger" and m["data"]["kind"] == "agent_step"]
        self.assertTrue(any(c["role"] == "tool_call" for c in calls))
        self.assertTrue(any(c["role"] == "tool_result" for c in calls))


class HardBudgetTests(unittest.TestCase):
    """Execution never exceeds the remaining water or energy, for the real farm and imagined seasons."""

    def test_allocation_rule(self):
        from worldlab.farm.sim import cap_to_budget, KWH_PUMP
        g = np.array([10.0, 20.0, 0.0])
        out, f = cap_to_budget(g, np.zeros(3), 1e9, 1e9, 2.0)
        self.assertTrue(np.allclose(out, g)) and self.assertEqual(float(f), 1.0)
        out, f = cap_to_budget(g, np.zeros(3), 300.0, 1e9, 2.0)          # demand 600 m3, 300 left
        self.assertAlmostEqual(float((out * 10 * 2.0).sum()), 300.0, places=6)
        self.assertTrue(np.allclose(out / g[:2].sum() * g[:2].sum(), out))
        self.assertAlmostEqual(out[0] / out[1], 0.5)                       # proportional
        out, f = cap_to_budget(g, np.zeros(3), 0.0, 1e9, 2.0)
        self.assertTrue(np.all(out == 0))
        out, f = cap_to_budget(g, np.zeros(3), -50.0, -1.0, 2.0)           # overdrawn: nothing, never negative
        self.assertTrue(np.all(out == 0))
        out, f = cap_to_budget(g, np.zeros(3), 1e9, 600 * KWH_PUMP / 2, 2.0)   # energy binds
        self.assertAlmostEqual(float((out * 10 * 2.0).sum()), 300.0, places=6)
        out, f = cap_to_budget(np.zeros(3), np.zeros(3), 0.0, 0.0, 2.0)    # no demand, no budget: no divide by zero
        self.assertTrue(np.all(out == 0)) and self.assertEqual(float(f), 1.0)

    def test_farm_stops_at_the_quota(self):
        farm = Farm(seed=7)
        lab = Lab(farm, run_dir=tempfile.mkdtemp(), perception=SimPerception())
        plan = lab.plan_season("test")
        lab.start_season(plan["plan_id"], "test", "rule", accept_nutrient_risk="test")
        lab.advance(40, "test")
        lab.limits.water_quota_m3 = lab.water_used + 400.0          # almost nothing left
        for _ in range(8):
            if lab.done or lab.phase == "harvested":
                break
            r = lab.advance(60, "test")
            if lab.anomaly:
                lab.dismiss_anomaly("test")
        self.assertLessEqual(lab.water_used, lab.limits.water_quota_m3 + 1e-6)
        self.assertGreater(lab.curtailed_m3, 0)
        self.assertTrue(any(e["kind"] == "curtailment" for e in lab.ledger.entries))

    def test_imagined_seasons_obey_the_same_cap(self):
        from worldlab.farm import rl as RL
        farm = Farm(seed=7)
        lab = Lab(farm, run_dir=tempfile.mkdtemp(), perception=SimPerception())
        plan = lab.plan_season("test")
        rows = [i for i, f in enumerate(lab.plans[plan["plan_id"]]["fields"]) if f["crop"]]
        fp = [{"crop": f["crop"], **f["mgmt"]} for f in (lab.plans[plan["plan_id"]]["fields"][i] for i in rows)]
        envs = RL.Envs(fp, rows, lab.beliefs, 4, seed=1, quota_m3=15000, energy_kwh=90000, hard_budget=True)
        res = RL.rollout(envs, np.zeros((2, RL.N_PARAMS)))
        self.assertTrue(np.all(res["water"] <= 15000 + 1e-6))
        soft = RL.Envs(fp, rows, lab.beliefs, 4, seed=1, quota_m3=15000, energy_kwh=90000, hard_budget=False)
        self.assertTrue(np.any(RL.rollout(soft, np.zeros((2, RL.N_PARAMS)))["water"] > 15000))


if __name__ == "__main__":
    unittest.main()


class P2Tests(unittest.TestCase):
    """Scenario library, farm editor, human decisions, branching, next season, sharing."""

    def test_scenario_library_hides_the_schedule_and_editor_bounds(self):
        from worldlab import scenarios as SC
        pub = SC.public()
        self.assertEqual({s["id"] for s in pub}, set(SC.BY_ID))
        for s in pub:
            self.assertNotIn("perturb", s)
        self.assertEqual(SC.clamp("seed", 12), 12.0)
        for name, bad in (("seed", 0), ("water_quota_m3", 10), ("salinity_scale", 9)):
            with self.assertRaises(ValueError):
                SC.clamp(name, bad)

    def test_fields_override_changes_the_soil_and_forecasts_are_deterministic(self):
        import copy
        f = copy.deepcopy(FIELDS)
        for x in f:
            x["ece"] = [v * 1.5 for v in x["ece"]]
        a, b = Farm(seed=7), Farm(seed=7, fields=f)
        self.assertAlmostEqual(b.fields[0]["ece"][0], 1.5 * a.fields[0]["ece"][0])
        self.assertEqual(FIELDS[0]["ece"][0], a.fields[0]["ece"][0])            # the standard farm is untouched
        f1, f2 = Farm(seed=7).forecast(), Farm(seed=7).forecast()
        self.assertEqual(json.dumps(f1, default=float), json.dumps(f2, default=float))

    def test_human_decisions_are_validated_and_logged(self):
        import threading
        d = tempfile.mkdtemp()
        lab = Lab(Farm(seed=7), run_dir=d, perception=SimPerception())
        opts = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
        self.assertEqual(lab.ask_human("k", "Q?", opts, "a"), "a")           # mode off: the scientist's choice, no pause
        lab.human = True
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("c", lab.ask_human("k", "Q?", opts, "a")))
        t.start()
        for _ in range(100):
            if lab._decision:
                break
            __import__("time").sleep(0.02)
        self.assertFalse(lab.answer_decision("D9", "b")["ok"])                # wrong request
        self.assertFalse(lab.answer_decision("D1", "zzz")["ok"])              # not an offered option
        self.assertTrue(lab.answer_decision("D1", "b")["ok"])
        t.join(5)
        self.assertEqual(out["c"], "b")
        rec = [e for e in lab.ledger.entries if e["kind"] == "human_decision"][-1]["data"]
        self.assertEqual((rec["by"], rec["override"], rec["scientist_default"]), ("you", True, "a"))
        self.assertEqual(lab.ask_human("k", "Q?", opts, "a", timeout_s=0.1), "a")   # no answer: default, logged as such
        rec = [e for e in lab.ledger.entries if e["kind"] == "human_decision"][-1]["data"]
        self.assertIn("no answer", rec["by"])
        ok, _ = verify(Path(d) / "ledger.jsonl")
        self.assertTrue(ok)

    def test_recorded_experiments_are_typed_and_shipped(self):
        root = Path(__file__).resolve().parents[1] / "worldlab" / "dashboard"
        x = json.loads((root / "experiments.json").read_text())
        self.assertEqual(x["schema"], 2)
        for p in x["pairs"]:
            self.assertIn(p["kind"], ("single_factor", "illustrative", "system"))
            keys = p["treatment_inputs"]
            if p["kind"] in ("single_factor", "illustrative"):
                self.assertEqual(len(keys), 1, p["title"])
            if p["kind"] == "single_factor":
                self.assertTrue(p["pre_event_identical"])
            for side in (p["baseline"], p["treatment"]):
                r = x["runs"][side]
                self.assertTrue(r["artifacts"]["ledger_sha256"] and r["artifacts"]["ledger_head"])
        for c in x["soil_carryover"]:                   # like-for-like: simulated state end == next start
            self.assertEqual(c["end_of_season_1_true"], c["start_of_season_2_true"])
        rep = json.loads((root / "replay.json").read_text())
        self.assertTrue(any(m["kind"] == "forecast" for m in rep["messages"]))
        self.assertNotIn("clog", rep["meta"]["note"].lower())          # the recording doesn't reveal the hidden cause up front

    def test_pair_labels_are_checked(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("bx", Path(__file__).resolve().parents[1] / "scripts" / "build_experiments.py")
        bx = importlib.util.module_from_spec(spec); spec.loader.exec_module(bx)
        cfg = {"scientist": "scripted protocol", "irrigation_learning": "none", "investigation": "fixed protocol",
               "perception": "direct", "hidden_fault": "clog@95", "starting_soil": "standard", "farm_seed": 7, "weather_year": "seed 7"}
        a = {"label": "A", "config": cfg, "faults": []}
        b = {"label": "B", "config": {**cfg, "hidden_fault": "none", "perception": "images"}, "faults": []}
        with self.assertRaises(ValueError):                              # two treatment changes can't be "single factor"
            bx.pair("x", "single_factor", a, b, Path("."), Path("."))
        c = {"label": "C", "config": {**cfg, "scientist": "Muse Spark (muse-spark-1.3)", "hidden_fault": "none"}, "faults": []}
        with self.assertRaises(ValueError):
            bx.pair("x", "illustrative", a, c, Path("."), Path("."))
        self.assertEqual(bx.pair("x", "system", a, b, Path("."), Path("."))["kind"], "system")

    def test_branch_next_season_and_share_over_http(self):
        import threading
        import urllib.error
        import urllib.request
        import http.cookiejar
        from http.server import ThreadingHTTPServer
        from worldlab.server import App, make_handler
        from worldlab.session import Settings
        app = App(Settings(agent="scripted", speed=0, perception="sim"), tempfile.mkdtemp())
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def call(path, body=None):
            req = urllib.request.Request(base + path, None if body is None else json.dumps(body).encode(), {"Content-Type": "application/json"})
            try:
                with op.open(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        def wait():
            app.slot(1).session.thread.join(timeout=600)
            return call("/api/runs")[1]["runs"]
        try:
            with urllib.request.urlopen(base + "/api/scenarios") as r:
                self.assertTrue(all("perturb" not in s for s in json.loads(r.read())["scenarios"]))
            self.assertEqual(call("/api/auth/signup", {"name": "Mo", "email": "mo@example.com", "password": "longenough1"})[0], 200)
            st, d = call("/api/start", {"agent": "scripted", "scenario": "nope"})
            self.assertEqual(st, 400)
            st, d = call("/api/start", {"agent": "scripted", "farm": {"water_quota_m3": 5}})
            self.assertEqual(st, 400)
            # a client can't plant its own soil or claim a parent run
            st, d = call("/api/start", {"agent": "scripted", "speed": 60, "scenario": "saline_start", "farm": {"seed": 11},
                                        "soil": [[99, 99, 99]] * 6, "parent_run": 42})
            self.assertEqual(st, 200, d)
            s = app.slot(1).session.settings
            self.assertEqual((s.soil, s.parent_run, s.seed, s.salinity_scale), (None, None, 11, 1.5))
            r1 = wait()[0]
            self.assertEqual(r1["settings"]["scenario"], "saline_start")
            # share: only the owner can, the snapshot is public and read-only
            st, d = call(f"/api/runs/{r1['id']}/share", {})
            self.assertEqual(st, 200, d)
            with urllib.request.urlopen(f"{base}/api/shared/{d['token']}") as r:
                self.assertTrue(json.loads(r.read())["messages"])
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(f"{base}/api/shared/not-a-token")
            # branch: one change, same everything else, linked to the parent (checked at start, then stopped)
            def started():
                sess = app.slot(1).session
                st_ = sess.settings
                sess.stop(); sess.thread.join(timeout=60)
                return st_
            st, d = call(f"/api/runs/{r1['id']}/branch", {"change": {"kind": "seed", "value": 12}})
            self.assertEqual(st, 200, d)
            s2 = started()
            self.assertEqual((s2.parent_run, s2.seed, s2.scenario, s2.salinity_scale), (r1["id"], 12, "saline_start", 1.5))
            self.assertEqual(s2.change["kind"], "seed")
            self.assertEqual(call("/api/runs")[1]["runs"][0]["parent"], r1["id"])
            msgs = call(f"/api/runs/{r1['id']}/replay")[1]["messages"]   # the next season doesn't leak into this log
            self.assertFalse([m for m in msgs[1:] if m["kind"] == "reset"])
            self.assertTrue(msgs[-1]["kind"] != "reset" and any(m["kind"] == "status" and m["data"].get("result") for m in msgs))
            self.assertEqual(call(f"/api/runs/{r1['id']}/branch", {"change": {"kind": "weather"}})[0], 400)
            # next season on the soil the first one left
            st, d = call(f"/api/runs/{r1['id']}/next", {})
            self.assertEqual(st, 200, d)
            s3 = started()
            end = json.loads((Path(app.accounts.run(1, r1["id"])["run_dir"]) / "soil_end.json").read_text())
            self.assertEqual(s3.soil, end)
            self.assertEqual(s3.parent_run, r1["id"])
        finally:
            httpd.shutdown()


class RunStatusTests(unittest.TestCase):
    """A model failure never turns into a successful autonomous harvest (P0.2)."""

    def run_mock(self, mode=None, after=0, max_turns=60, stop_after=None, limits=None):
        srv = MockServer(mode, after).start()
        try:
            farm = Farm(seed=7)
            farm.schedule("clog", 90)
            lab = Lab(farm, limits=limits, perception=SimPerception())
            cfg = LLMConfig(base_url=srv.base_url, api_key="test", model="muse-spark-1.3", reasoning_effort="medium", label="mock")
            sci = LLMScientist(lab, cfg, max_turns=max_turns)
            sci.client.retry_delay = 0.01
            if stop_after is not None:
                orig = sci.client.chat

                def chat(*a, **k):
                    if sci.client.calls >= stop_after:
                        lab.stop_flag.set()
                    return orig(*a, **k)
                sci.client.chat = chat
            out = sci.run()
            return lab, out, srv
        finally:
            srv.stop()

    def assert_stopped(self, lab, status):
        from worldlab.progression import evaluate
        self.assertTrue(lab.done)
        self.assertEqual(lab.run_status, status)
        self.assertIsNone(lab.result)                                   # no harvest the model didn't reach
        self.assertFalse(any(e["kind"] == "season_result" for e in lab.ledger.entries))
        ev = evaluate(lab.ledger.entries, [], None)
        self.assertFalse(ev["complete"])
        self.assertEqual(ev["achievements"], [])
        self.assertIn(status, ev["outcome"])
        end = [e for e in lab.ledger.entries if e["kind"] == "run_end"][-1]["data"]
        self.assertEqual(end["status"], status)
        self.assertTrue(end["reason"])

    def test_auth_error_fails_without_harvest(self):
        lab, out, _ = self.run_mock("status:401", after=3)
        self.assert_stopped(lab, "failed")
        self.assertIn("401", lab.run_end_reason)

    def test_repeated_server_errors_fail(self):
        lab, out, _ = self.run_mock("status:503", after=3)
        self.assert_stopped(lab, "failed")
        self.assertGreater(out["attempts"], out["api_calls"])                # retries are counted

    def test_rate_limit_fails_after_bounded_retries(self):
        lab, out, _ = self.run_mock("status:429", after=3)
        self.assert_stopped(lab, "failed")

    def test_malformed_responses_fail(self):
        lab, _, _ = self.run_mock("malformed", after=3)
        self.assert_stopped(lab, "failed")

    def test_model_that_stops_calling_tools_fails(self):
        lab, _, _ = self.run_mock("silent", after=3)
        self.assert_stopped(lab, "failed")
        self.assertIn("stopped calling tools", lab.run_end_reason)

    def test_turn_limit_fails(self):
        lab, _, _ = self.run_mock(max_turns=4)
        self.assert_stopped(lab, "failed")
        self.assertIn("turn limit", lab.run_end_reason)

    def test_cancellation(self):
        lab, _, _ = self.run_mock(stop_after=3)
        self.assert_stopped(lab, "cancelled")

    def test_invalid_and_out_of_range_arguments_are_refused(self):
        lab, _, _ = self.run_mock("badargs", after=3, max_turns=8)
        refused = [e for e in lab.ledger.entries if e["kind"] == "agent_step" and "invalid arguments" in str(e["data"].get("result", ""))]
        self.assertTrue(refused)
        self.assertTrue(lab.day < 273 and lab.run_status == "failed")   # the 100000-day advance never ran; the turn limit ended it
        lab2, _, _ = self.run_mock("badjson", after=3, max_turns=8)
        self.assertTrue(any("not valid JSON" in str(e["data"].get("result", "")) for e in lab2.ledger.entries if e["kind"] == "agent_step"))
        from worldlab.agent import validate_args, TOOL_SCHEMA
        self.assertTrue(validate_args(TOOL_SCHEMA["update_model"], {"rationale": "r", "finding": "drip_delivery", "value": float("nan"), "since_day": 3}))
        self.assertTrue(validate_args(TOOL_SCHEMA["field_test"], {"field": "F9", "test": "water_test", "rationale": "r"}))
        self.assertEqual(validate_args(TOOL_SCHEMA["advance"], {"days": 30, "rationale": "r"}), [])

    def test_finish_cannot_skip_the_season(self):
        lab = Lab(Farm(seed=7), perception=SimPerception())
        plan = lab.plan_season("t")
        lab.start_season(plan["plan_id"], "t", "rule", accept_nutrient_risk="test")
        lab.advance(20, "t")
        out = lab.finish("done early")
        self.assertIn("refused", out)
        self.assertFalse(lab.done)
        self.assertIsNone(lab.result)

    def test_handover_is_recorded_as_mixed(self):
        from worldlab.agent import ScriptedScientist
        from worldlab.progression import evaluate
        lab, _, _ = self.run_mock("status:503", after=13)
        if lab.phase != "season":
            self.skipTest("mock failed before sowing")
        ScriptedScientist(lab).resume("failed: test")
        self.assertEqual(lab.run_status, "degraded")
        self.assertIsNotNone(lab.result)
        self.assertEqual(lab.result["decided_by"], "mixed (handover)")
        ev = evaluate(lab.ledger.entries, [], None)
        self.assertFalse(ev["complete"])
        self.assertEqual(ev["achievements"], [])
        self.assertTrue(any(e["kind"] == "handover" for e in lab.ledger.entries))

    def test_image_budget_counts_failed_calls(self):
        from worldlab.lab import Limits

        class Client:
            attempts = 400

        class P(SimPerception):
            client = Client()
        lab = Lab(Farm(seed=7), limits=Limits(max_image_calls=400), perception=P())
        plan = lab.plan_season("t")
        lab.start_season(plan["plan_id"], "t", "rule", accept_nutrient_risk="test")
        lab.advance(40, "t")
        self.assertIn("refused", lab.look_at_field("F1", "check"))


class PerceptionStatusTests(unittest.TestCase):
    """An API failure can never read as 'no plants' or 'no salt' (P0.5)."""

    class FakeClient:
        def __init__(self, sam, diag):
            self.sam, self.diag, self.attempts, self.calls = sam, diag, 0, 0

        def responses_stream_text(self, body):
            self.attempts += 1
            r = self.sam(body["input"][0]["content"][0]["text"], self.attempts)
            if isinstance(r, Exception):
                raise r
            return r

        def chat(self, messages, **k):
            self.attempts += 1
            if isinstance(self.diag, Exception):
                raise self.diag
            return {"content": self.diag}

    GOOD = json.dumps({"condition": "healthy", "pest_damage_visible": False, "salt_crust_visible": False,
                       "wilting_or_yellowing": False, "gaps_in_stand": False, "evidence": "uniform green rows"})
    BOX = "<0f>0<|box;x1=10;y1=10;x2=30;y2=30;w=300;h=210|><|mask;x=0;y=0;data=1,1,!|>"

    def analyze(self, sam, diag=None):
        from worldlab.farm.drone_render import render, encode
        from worldlab.perception import MetaPerception
        frame, mime = encode(render("maize", 0.2, 1.0, 1.0, 2.0, 0.0, False, seed=3))
        mp = MetaPerception(self.FakeClient(sam, self.GOOD if diag is None else diag))
        return mp.analyze(frame, mime)

    def test_valid_zero_is_a_zero(self):
        r = self.analyze(lambda phrase, n: "")
        self.assertEqual((r["plants_counted"], r["plant_count_status"], r["salt_crust_patches"]), (0, "valid", 0))
        self.assertEqual(r["perception_status"], "complete")
        self.assertEqual(r["errors"], [])

    def test_unavailable_is_not_zero(self):
        from worldlab.llm import APIError
        r = self.analyze(lambda phrase, n: APIError(503, "down"))
        self.assertIsNone(r["plants_counted"])
        self.assertIsNone(r["salt_crust_patches"])
        self.assertEqual((r["plant_count_status"], r["salt_status"]), ("unavailable", "unavailable"))
        self.assertEqual(r["perception_status"], "partial")                  # the diagnosis still arrived
        self.assertNotIn("SAM", r["source"])
        self.assertTrue(r["errors"])

    def test_partial_tiles_are_a_lower_bound(self):
        from worldlab.llm import APIError
        r = self.analyze(lambda phrase, n: APIError(503, "down") if (phrase == "plant" and n % 4 == 0) else self.BOX)
        self.assertEqual(r["plant_count_status"], "partial")
        self.assertIn("lower bound", r["counting_note"])
        self.assertEqual(r["perception_status"], "partial")

    def test_malformed_outputs(self):
        r = self.analyze(lambda phrase, n: "I see some plants", diag='{"condition": "great"}')
        self.assertEqual((r["plant_count_status"], r["salt_status"], r["diagnosis_status"]), ("malformed", "malformed", "malformed"))
        self.assertIsNone(r["diagnosis"])
        self.assertEqual(r["perception_status"], "unavailable")
        self.assertEqual(r["source"], "perception unavailable")

    def test_errors_belong_to_this_frame(self):
        from worldlab.llm import APIError
        from worldlab.farm.drone_render import render, encode
        from worldlab.perception import MetaPerception
        frame, mime = encode(render("maize", 0.2, 1.0, 1.0, 2.0, 0.0, False, seed=3))
        fc = self.FakeClient(lambda p, n: APIError(503, "down"), self.GOOD)
        mp = MetaPerception(fc)
        self.assertTrue(mp.analyze(frame, mime)["errors"])
        fc.sam = lambda p, n: ""
        self.assertEqual(mp.analyze(frame, mime)["errors"], [])               # yesterday's failure isn't today's status

    def test_unavailable_answers_are_not_scored(self):
        lab = Lab(Farm(seed=7), perception=SimPerception())
        lab.perception_checks = [{"day": 100, "field": "F1", "drawn": {"crop": "maize", "plants": 150, "salt_patches": 9, "damaged_plants": 0},
                                  "sam": {"plants": None, "salt_patches": None}, "diagnosis": None, "status": "unavailable"}]
        ps = lab.perception_summary()
        self.assertEqual((ps["plants_drawn"], ps["salt_frames_detected_by_sam"], ps["frames_not_complete"]), (0, "0/0", 1))


class LiveAccessTests(unittest.TestCase):
    """Readiness, guest sessions and admission limits (P0.1, P1.5)."""

    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        from worldlab.server import App, make_handler
        from worldlab.session import Settings
        self.app = App(Settings(agent="scripted", speed=0, perception="sim"), tempfile.mkdtemp(), max_runs=1)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        for sl in self.app.slots.values():
            if sl.session:
                sl.session.stop()
        self.httpd.shutdown()

    def call(self, path, body=None, token=None):
        import urllib.error
        import urllib.request
        h = {"Content-Type": "application/json", "Origin": self.base}
        if token:
            h["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, None if body is None else json.dumps(body).encode(), h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_ready_discloses_no_secrets(self):
        import os
        os.environ["MODEL_API_KEY"] = "secret-test-key"
        try:
            st, d = self.call("/api/ready")
        finally:
            del os.environ["MODEL_API_KEY"]
        self.assertEqual(st, 200)
        self.assertTrue(d["ready"] and d["models"]["muse_spark"])
        self.assertNotIn("secret-test-key", json.dumps(d))

    def test_guest_session_limits(self):
        st, g = self.call("/api/auth/guest", {})
        self.assertEqual(st, 200, g)
        tok = g["token"]
        self.assertTrue(g["user"]["email"].endswith("@guest.worldlab"))
        self.app.guest_runs = 1
        st, d = self.call("/api/start", {"agent": "scripted", "speed": 60}, tok)
        self.assertEqual(st, 200, d)
        self.app.slot(g["user"]["id"]).session.stop()
        self.app.slot(g["user"]["id"]).session.thread.join(60)
        st, d = self.call("/api/start", {"agent": "scripted", "speed": 60}, tok)
        self.assertEqual(st, 429)                                     # the guest's season allowance is used
        st, d = self.call("/api/auth/signup", {"name": "x", "email": "guest-zz@guest.worldlab", "password": "longenough1"})
        self.assertEqual(st, 400)                                     # nobody can sign up with a guest address
        for _ in range(5):
            self.call("/api/auth/guest", {})
        self.assertEqual(self.call("/api/auth/guest", {})[0], 429)     # guest creation is rate-limited

    def test_admission_is_atomic(self):
        import threading
        toks = [self.call("/api/auth/guest", {})[1]["token"] for _ in range(4)]
        codes = []
        th = [threading.Thread(target=lambda t=t: codes.append(self.call("/api/start", {"agent": "scripted", "speed": 1}, t)[0])) for t in toks]
        [x.start() for x in th]
        [x.join(60) for x in th]
        self.assertEqual(codes.count(200), 1, codes)                  # capacity 1: exactly one start admitted
        self.assertEqual(self.app.reserved, set())                    # reservations released

    def test_spark_daily_budget(self):
        import os
        os.environ["MODEL_API_KEY"] = "x"
        try:
            self.app.spark_daily = 0
            tok = self.call("/api/auth/guest", {})[1]["token"]
            st, d = self.call("/api/start", {"agent": "spark"}, tok)
            self.assertEqual(st, 429)
            self.assertIn("budget", d["error"])
        finally:
            del os.environ["MODEL_API_KEY"]

    def test_runs_are_private(self):
        a = self.call("/api/auth/guest", {})[1]["token"]
        b = self.call("/api/auth/guest", {})[1]["token"]
        st, d = self.call("/api/start", {"agent": "scripted", "speed": 60}, a)
        rid = d["run_id"]
        self.assertEqual(self.call(f"/api/runs/{rid}/replay", None, b)[0], 404)
        self.assertEqual(self.call(f"/api/runs/{rid}/share", {}, b)[0], 400)


    def test_cancellation_releases_capacity(self):
        a = self.call("/api/auth/guest", {})[1]["token"]
        b = self.call("/api/auth/guest", {})[1]["token"]
        self.assertEqual(self.call("/api/start", {"agent": "scripted", "speed": 1}, a)[0], 200)
        self.assertEqual(self.call("/api/start", {"agent": "scripted", "speed": 1}, b)[0], 429)     # capacity 1 is taken
        self.assertEqual(self.call("/api/stop", {}, a)[0], 200)
        for sl in self.app.slots.values():
            if sl.session and sl.session.thread:
                sl.session.thread.join(60)
        self.assertEqual(self.app.active_runs(), 0)
        self.assertEqual(self.call("/api/start", {"agent": "scripted", "speed": 60}, b)[0], 200)    # the slot was released

    def test_cross_origin_logins_get_short_sessions_and_pages_a_policy(self):
        import urllib.request
        from worldlab.accounts import BEARER_SESSION_S
        import os
        os.environ["WORLDLAB_ALLOWED_ORIGINS"] = "https://moamryehia.github.io"
        self.addCleanup(os.environ.pop, "WORLDLAB_ALLOWED_ORIGINS", None)
        self.call("/api/auth/signup", {"name": "x", "email": "x@example.com", "password": "longenough1"})
        req = urllib.request.Request(self.base + "/api/auth/login", json.dumps({"email": "x@example.com", "password": "longenough1"}).encode(),
                                     {"Content-Type": "application/json", "Origin": "https://moamryehia.github.io"})
        with urllib.request.urlopen(req) as r:
            d = json.loads(r.read())
        self.assertEqual(d["expires_in_s"], BEARER_SESSION_S)
        st, d = self.call("/api/auth/login", {"email": "x@example.com", "password": "longenough1"})
        self.assertGreater(d["expires_in_s"], BEARER_SESSION_S)                                       # same-origin cookie session
        with urllib.request.urlopen(self.base + "/demo") as r:
            csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self' https://cdn.jsdelivr.net 'sha256-", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'self'", csp)


class EvidenceBundleTests(unittest.TestCase):
    """The recorded season's evidence verifies offline; edits, omissions and reordering fail (P1.4)."""

    def bundle(self):
        import shutil
        src = Path(__file__).resolve().parents[1] / "worldlab" / "dashboard" / "evidence"
        d = Path(tempfile.mkdtemp()) / "b"
        shutil.copytree(src, d)
        return d

    def verify(self, d):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ve", Path(__file__).resolve().parents[1] / "scripts" / "verify_evidence.py")
        ve = importlib.util.module_from_spec(spec); spec.loader.exec_module(ve)
        return ve.verify(d)

    def rewrite(self, d, fn, fix_manifest=True):
        import gzip
        import hashlib
        lines = gzip.decompress((d / "ledger.jsonl.gz").read_bytes()).decode().splitlines()
        new = fn(lines)
        self.assertNotEqual(new, lines, "the tamper must change the ledger")
        lines = new
        raw = ("\n".join(lines) + "\n").encode()
        gz = gzip.compress(raw, mtime=0)
        (d / "ledger.jsonl.gz").write_bytes(gz)
        if fix_manifest:                                   # an attacker who also rewrites the file hashes in the manifest
            m = json.loads((d / "manifest.json").read_text())
            m["artifacts"]["ledger.jsonl.gz"]["sha256_gz"] = hashlib.sha256(gz).hexdigest()
            m["artifacts"]["ledger.jsonl.gz"]["sha256"] = hashlib.sha256(raw).hexdigest()
            (d / "manifest.json").write_text(json.dumps(m))

    def test_untouched_bundle_verifies(self):
        ok, msg = self.verify(self.bundle())
        self.assertTrue(ok, msg)

    def test_edit_fails(self):
        d = self.bundle()
        self.rewrite(d, lambda ls: [ls[0]] + [ls[1].replace('"farm_seed":7', '"farm_seed":8', 1)] + ls[2:])
        self.assertFalse(self.verify(d)[0])

    def test_edit_without_fixing_the_manifest_fails(self):
        d = self.bundle()
        self.rewrite(d, lambda ls: ls[:-1] + [ls[-1].replace('"scientist_calls":34', '"scientist_calls":3', 1)], fix_manifest=False)
        self.assertFalse(self.verify(d)[0])

    def test_omission_and_reordering_fail(self):
        d = self.bundle()
        self.rewrite(d, lambda ls: ls[:10] + ls[11:])
        self.assertFalse(self.verify(d)[0])
        d = self.bundle()
        self.rewrite(d, lambda ls: ls[:5] + [ls[6], ls[5]] + ls[7:])
        self.assertFalse(self.verify(d)[0])
        d = self.bundle()
        self.rewrite(d, lambda ls: ls[:-3])                 # cut off the end: only the recorded final hash catches this
        ok, msg = self.verify(d)
        self.assertFalse(ok)
        self.assertRegex(msg, "entries|final hash")

    def test_manifest_has_provenance_and_no_secrets(self):
        m = json.loads((self.bundle() / "manifest.json").read_text())
        for k in ("source", "scientist", "perception", "farm", "timestamps", "status", "usage", "artifacts", "guarantee"):
            self.assertIn(k, m)
        self.assertEqual(m["scientist"]["model"], "muse-spark-1.3")
        self.assertNotRegex(json.dumps(m), r"LLM_|Bearer |/home/|@gmail")


class EvidenceServedTests(unittest.TestCase):
    def test_server_serves_the_bundle(self):
        from worldlab import server
        for n in ("manifest.json", "ledger.jsonl.gz", "verify_evidence.py", "worldlab-evidence.zip"):
            self.assertTrue(server.STATIC[f"evidence/{n}"].is_file(), n)
        self.assertEqual(server.TYPES[".zip"], "application/zip")

    def test_zip_holds_the_same_ledger(self):
        import zipfile
        d = Path(__file__).resolve().parents[1] / "worldlab" / "dashboard" / "evidence"
        z = zipfile.ZipFile(d / "worldlab-evidence.zip")
        self.assertEqual(z.read("worldlab-evidence/ledger.jsonl.gz"), (d / "ledger.jsonl.gz").read_bytes())
        self.assertEqual(z.read("worldlab-evidence/manifest.json"), (d / "manifest.json").read_bytes())


class HoldoutTests(unittest.TestCase):
    """New hidden-event families for the frozen holdout (P1.1), what the agent can and can't see, and their scoring."""

    def season(self, kind, sev, field=0):
        farm = Farm(seed=7)
        farm.start_season([{"crop": "wheat", **mg("wheat")}] * 6)
        if kind:
            farm.schedule(kind, 70, field=field, severity=sev)
        for d in range(90):
            farm.step(farm.sim.irrigation_demand(d))
        return farm

    def test_sensor_bias_shows_in_readings_and_the_sensor_check_only(self):
        farm = self.season("sensor_bias", -0.06)
        obs = farm.step(farm.sim.irrigation_demand(90))
        true = (farm.sim.W / farm.sim.th)[0]
        self.assertLess(float(np.mean(obs["theta"][0] - true)), -0.04)                      # the sensor reads drier
        sc = farm.field_test(0, "sensor_check")
        self.assertLess(sc["sensor_minus_reference"], -0.04)
        self.assertAlmostEqual(farm.field_test(1, "sensor_check")["sensor_minus_reference"], 0, delta=0.025)
        self.assertGreater(farm.field_test(0, "emitter_flow")["delivered_vs_design"], 0.85)  # delivery is fine
        r = farm.recalibrate_sensor(0)
        self.assertLess(r["offset_found_m3m3"], -0.04)
        obs = farm.step(farm.sim.irrigation_demand(91))
        self.assertLess(abs(float(np.mean(obs["theta"][0] - (farm.sim.W / farm.sim.th)[0]))), 0.02)

    def test_root_disease_lowers_canopy_but_no_test_shows_it(self):
        sick, healthy = self.season("blight", 0.025, field=2), self.season(None, None)
        self.assertLess(sick.sim.cc[2], healthy.sim.cc[2] - 0.05)
        self.assertFalse(sick.field_test(2, "leaf_inspection")["pest_damage_seen"])
        self.assertGreater(sick.field_test(2, "emitter_flow")["delivered_vs_design"], 0.85)
        self.assertLess(sick.field_test(2, "water_test")["groundwater_ec_dS_m"], 5.5)
        self.assertAlmostEqual(sick.field_test(2, "sensor_check")["sensor_minus_reference"], 0, delta=0.025)
        self.assertTrue(sick.pest_control(2)["treated"])
        self.assertLess(sick.sim.cc[2], healthy.sim.cc[2])                                    # pest control can't cure it

    def test_random_field_pick_lands_on_a_growing_crop(self):
        farm = Farm(seed=7)
        farm.start_season([{"crop": None, "sow": 0, "density": 1, "irr": 0, "desal": 0, "nfert": 0, "mulch": 0}] * 3 +
                          [{"crop": "wheat", **mg("wheat")}] * 3)
        farm.schedule("clog", 70, pick=4)
        for d in range(72):
            farm.step(farm.sim.irrigation_demand(d))
        self.assertIn(farm.events[0]["field"], ("F4", "F5", "F6"))

    def test_agent_tools_never_see_hidden_events(self):
        from worldlab.agent import dispatch
        farm = Farm(seed=7)
        farm.schedule("blight", 60, pick=1, severity=0.02)
        farm.schedule("sensor_bias", 61, pick=2, severity=0.07)
        lab = Lab(farm, run_dir=tempfile.mkdtemp(), perception=SimPerception())
        plan = lab.plan_season("go")
        lab.start_season(plan["plan_id"], "go", "rule", accept_nutrient_risk="test")
        seen = []
        for _ in range(4):
            r = dispatch(lab, "advance", {"days": 30, "rationale": "x"})
            seen.append(json.dumps(r, default=str))
            if lab.anomaly:
                seen.append(json.dumps(dispatch(lab, "dismiss_anomaly", {"rationale": "x"}), default=str))
        seen.append(json.dumps(dispatch(lab, "observe", {}), default=str))
        text = " ".join(seen).lower()
        self.assertTrue(farm.events)                                                           # both events happened
        for word in ("blight", "sensor_bias", "root disease", "hidden", "scheduled", "reads +"):
            self.assertNotIn(word, text)

    def test_scoring_of_the_new_families(self):
        from worldlab.benchscore import score
        E = lambda t, kind, **d: {"t": t, "kind": kind, "data": d}
        ev = [{"kind": "sensor_bias", "field": "F3", "day": 100}]
        good = [E(110, "anomaly", field="F3", detected_day=110, signal="sw"),
                E(111, "field_test", field="F3", test="emitter_flow", delivered_vs_design=0.98),
                E(111, "field_test", field="F3", test="sensor_check", sensor_minus_reference=-0.06),
                E(111, "adjust", field="F3", recalibrate_sensor={"recalibrated": True})]
        s = score(good, ev, "sensor_bias")
        self.assertEqual((s["faults_diagnosed"], s["faults_justified_intervention"], s["wrong_interventions"]), (1, 1, 0))
        bad = good[:2] + [E(111, "adjust", field="F3", irr=1.3), E(112, "adjust", field="F3", repair={"repaired": True})]
        s = score(bad, ev, "sensor_bias")
        self.assertEqual((s["faults_diagnosed"], s["wrong_interventions"]), (0, 1))            # repaired a line that wasn't clogged
        ev = [{"kind": "blight", "field": "F5", "day": 100}]
        honest = [E(120, "anomaly", field="F5", detected_day=120, signal="cc"),
                  E(121, "field_test", field="F5", test="leaf_inspection", pest_damage_seen=False),
                  E(121, "model_update", finding="canopy_loss_unexplained", field="F5", value=0.02),
                  E(121, "review_requested", field="F5", question="?")]
        s = score(honest, ev, "blight")
        self.assertEqual(s["unidentifiable_handled"], [True])
        self.assertEqual(s["wrong_findings"], 0)
        guess = honest[:2] + [E(121, "model_update", finding="pest", field="F5", value=0.02), E(121, "adjust", field="F5", pest_control={"treated": True})]
        s = score(guess, ev, "blight")
        self.assertEqual(s["unidentifiable_handled"], [False])
        self.assertEqual((s["wrong_findings"], s["wrong_interventions"]), (1, 1))
        calm = score([E(130, "anomaly", field="F1", detected_day=130, signal="sw")], [], "none")
        self.assertEqual((calm["unrelated_alarms"], calm["appropriate_non_intervention"]), (1, True))

    def test_unknown_challenge_draws_every_family(self):
        import random
        from worldlab import scenarios as SC
        from worldlab.session import parse_perturb, perturb_extras
        rng = random.Random(1)
        fams = set()
        for _ in range(200):
            fam, specs = SC.draw_challenge(rng)
            fams.add(fam)
            for sp in specs:
                kind, day, _ = parse_perturb(sp)
                self.assertTrue(75 <= day <= 170)
                Farm(seed=1).schedule(kind, day, **perturb_extras(sp))
        self.assertEqual(fams, set(SC.FAMILIES))
        self.assertEqual(next(s for s in SC.public() if s["id"] == "mystery")["hidden_events"], "unknown")


class RealWeatherTests(unittest.TestCase):
    """The NASA POWER import (P1.2): pinned file, units, gaps, ET0 against FAO-56's worked example."""

    def test_import_is_complete_and_pinned(self):
        from worldlab.farm import observed as O
        wx, rep = O.load()
        self.assertEqual(rep["rows"], 273)
        self.assertEqual((rep["first_day"], rep["last_day"]), ("20241001", "20250630"))
        self.assertEqual(sum(rep["missing"].values()), 0)
        self.assertEqual(wx["tmax"].shape, (1, 273))
        self.assertAlmostEqual(float(wx["tmax"][0, 0]), 37.83)              # 1 Oct 2024 as published
        self.assertTrue(1500 < float(wx["et0"].sum()) < 2100)               # a plausible season total for inland UAE, mm

    def test_gaps_are_filled_and_reported(self):
        from worldlab.farm import observed as O
        lines = O.FILE.read_text().splitlines()
        cells = lines[11].split(","); cells[1] = "-999"; lines[11] = ",".join(cells)          # one missing day: interpolated
        for k in range(50, 56):                                                              # six missing days: climatology
            cells = lines[k].split(","); cells[3] = ""; lines[k] = ",".join(cells)
        p = Path(tempfile.mkdtemp()) / "w.csv"
        p.write_text("\n".join(lines) + "\n")
        with self.assertRaises(ValueError):
            O.load(p)                                                                        # the pinned hash refuses edits
        wx, rep = O.load(p, check_hash=False)
        self.assertEqual((rep["filled_by_interpolation"]["tmax"], rep["filled_from_climatology"]["rh"]), (1, 6))
        self.assertFalse(np.isnan(wx["et0"]).any())

    def test_et0_matches_the_fao56_worked_example(self):
        # FAO Irrigation and Drainage Paper 56, Example 18 (Brussels, 6 July): ET0 = 3.9 mm/day. The example uses
        # RHmax 84% and RHmin 63%; WorldLab takes daily mean RH (73.5%), so a small difference is expected.
        et0 = float(WX.et0_pm(np.array(21.5), np.array(12.3), np.array(73.5), np.array(2.078), np.array(22.07),
                              np.array(187), lat_deg=50.8, z=100.0))
        self.assertAlmostEqual(et0, 3.9, delta=0.25)

    def test_a_farm_runs_on_real_weather(self):
        farm = Farm(seed=7, weather="nasa_power_2024_25")
        self.assertEqual(farm.weather_source["sha256"], "c66ae08853e3f9c40bfad490f8811464c1ba85619f8858f6ae358089c1a8d63d")
        farm.start_season([{"crop": "wheat", **mg("wheat")}] * 6)
        obs = farm.step(farm.sim.irrigation_demand(0))
        self.assertAlmostEqual(obs["weather"]["tmax"], 37.83)


class BenchScoreTests(unittest.TestCase):
    """Event-level scoring (P0.3): evidence, diagnosis, justified action, re-alarms, and what went wrong."""

    E = staticmethod(lambda t, kind, **d: {"t": t, "kind": kind, "data": d})

    def test_clog_found_and_fixed(self):
        from worldlab.benchscore import score
        E = self.E
        ev = [{"kind": "clog", "field": "F4", "day": 95}]
        L = [E(115, "anomaly", field="F4", detected_day=115, signal="sw"),
             E(116, "field_test", field="F4", test="emitter_flow", delivered_vs_design=0.46),
             E(116, "adjust", field="F4", repair={"repaired": True}),
             E(116, "model_update", finding="drip_delivery", field="F4", value=0.46)]
        s = score(L, ev, "clog")
        e = s["events"][0]
        self.assertEqual((e["first_evidence_day"], e["correct_diagnosis_day"], e["days_to_diagnosis"]), (115, 116, 21))
        self.assertTrue(e["justified_intervention"] and e["no_realarm_30d"])
        self.assertEqual((s["wrong_findings"], s["wrong_interventions"], s["unnecessary_tests"]), (0, 0, 0))

    def test_acting_before_diagnosis_is_not_justified_and_wrong_field_is_wrong(self):
        from worldlab.benchscore import score
        E = self.E
        ev = [{"kind": "clog", "field": "F4", "day": 95}]
        L = [E(100, "adjust", field="F4", repair={"repaired": True}),                       # a lucky guess, no evidence
             E(110, "model_update", finding="drip_delivery", field="F4", value=0.5),
             E(111, "adjust", field="F2", repair={"repaired": True})]
        s = score(L, ev, "clog")
        self.assertFalse(s["events"][0]["justified_intervention"])
        self.assertEqual(s["wrong_interventions"], 1)

    def test_salinity_is_farm_wide_and_answered_by_desal_or_replan(self):
        from worldlab.benchscore import score
        E = self.E
        ev = [{"kind": "salinity", "field": "all", "day": 90}]
        L = [E(120, "anomaly", field="F2", detected_day=120, signal="ec"),
             E(121, "field_test", field="F2", test="water_test", groundwater_ec_dS_m=8.9),
             E(121, "model_update", finding="groundwater_ec", field="all", value=8.9),
             E(121, "rebalance", rationale="x")]
        s = score(L, ev, "salinity")
        self.assertEqual((s["faults_diagnosed"], s["faults_justified_intervention"], s["unrelated_alarms"]), (1, 1, 0))

    def test_a_late_realarm_and_an_unexplained_alarm_are_counted(self):
        from worldlab.benchscore import score
        E = self.E
        ev = [{"kind": "pest", "field": "F1", "day": 100}]
        L = [E(110, "anomaly", field="F1", detected_day=110, signal="cc"),
             E(111, "field_test", field="F1", test="leaf_inspection", pest_damage_seen=True),
             E(111, "adjust", field="F1", pest_control={"treated": True}),
             E(111, "model_update", finding="pest", field="F1", value=0.03),
             E(125, "anomaly", field="F1", detected_day=125, signal="cc"),
             E(60, "anomaly", field="F3", detected_day=60, signal="sw")]
        s = score(L, ev, "pest")
        self.assertFalse(s["events"][0]["no_realarm_30d"])
        self.assertEqual(s["unrelated_alarms"], 1)


class PlanningLossTests(unittest.TestCase):
    """The v2 farm-204 heat-wave loss (26.4 people): calibration, nutrient risk and alarm escalation (second review)."""

    @classmethod
    def setUpClass(cls):
        # the same trial plots Muse Spark grew on farm 204 (docs/bench/v2/runs/spark__meta/s204-heatwave)
        import gzip
        led = Path(__file__).resolve().parents[1] / "docs/bench/v2/runs/spark__meta/s204-heatwave/ledger.jsonl.gz"
        cls.L = [json.loads(x) for x in gzip.decompress(led.read_bytes()).decode().splitlines()]
        farm = Farm(seed=204)
        lab = Lab(farm, run_dir=tempfile.mkdtemp())
        h = lab.record_hypothesis("a", "b", "c")["hypothesis_id"]
        for st in [e["data"] for e in cls.L if e["kind"] == "trial_start"]:
            specs = [{k: p[k] for k in ("crop", "sow", "plot", "irr", "desal", "nfert", "density", "mulch") if k in p} for p in st["plots"]]
            ev = lab.evaluate_trials(specs)
            lab.run_trials([o["candidate_id"] for o in ev["options"]][:len(specs)], h, "x")
            lab.fit_crop_models("x")
        cls.lab, cls.farm = lab, farm

    def test_recorded_failure_is_what_the_old_code_logged(self):
        # the archived run: after the heat plots, a single-start fit put sweet potato's salt shift at +0.26 dS/m
        fits = [c for e in self.L if e["kind"] == "model_update" and e["data"].get("crops") for c in e["data"]["crops"] if c["crop"] == "sweet_potato"]
        self.assertAlmostEqual(fits[-1]["traits"]["salt"]["mean"], 0.262, places=3)
        self.assertEqual([e["data"]["people_fed"] for e in self.L if e["kind"] == "season_result"], [26.4])

    def test_multistart_calibration_recovers_the_salt_trait(self):
        b = self.lab.beliefs["sweet_potato"]
        true = self.farm.traits["sweet_potato"]["salt"]                      # -1.42
        self.assertLess(abs(b.mean[3] - true), 0.5)
        self.assertLess(b.mean[3], -0.8)                                   # not the +0.26 the single-start fit found

    def test_nutrient_risk_flags_the_bad_plan_and_offers_a_backup(self):
        # rebuild the beliefs the old run planned with (salt +0.26) and plan: vitamin A hangs on one field
        lab = Lab(Farm(seed=204), run_dir=tempfile.mkdtemp())
        rows = [e["data"]["crops"] for e in self.L if e["kind"] == "model_update" and e["data"].get("crops")]
        last = {}
        for table in rows:
            for c in table:
                last[c["crop"]] = c
        for c, row in last.items():
            b = lab.beliefs[c]
            b.mean = np.array([row["traits"][k]["mean"] for k in TRAIT_IDS])
            b.cov = np.diag([row["traits"][k]["sd"] ** 2 for k in TRAIT_IDS])
            lab.trial_data[c] = self.lab.trial_data[c]
        lab.phase = "planning"
        p = lab.plan_season("replan as in the archived run")
        risk = p["nutrient_risk"]
        self.assertIn(risk["level"], ("high", "watch"))
        self.assertLess(risk["if_worst_field_fails_p10"], p["people_p10"])
        vit = risk["by_nutrient"]["vitA_ug"]
        if risk["level"] == "high":
            self.assertIn("backup_plan_id", risk)
            self.assertGreater(risk["backup"]["if_worst_field_fails_p10"], risk["if_worst_field_fails_p10"])
            r = lab.start_season(p["plan_id"], "go")
            self.assertIn("refused", r)                                   # a decision is required
            self.assertIn("refused", lab.start_season(p["plan_id"], "go", accept_nutrient_risk="  "))
        self.assertGreater(vit["largest_share"], 0.5)

    def test_repeated_alarms_require_an_escalation_not_a_dismiss_loop(self):
        farm = Farm(seed=7)
        farm.schedule("blight", 60, pick=0, severity=0.03)
        lab = Lab(farm, run_dir=tempfile.mkdtemp(), perception=SimPerception())
        lab.start_season(lab.plan_season("go")["plan_id"], "go", "rule", accept_nutrient_risk="test")
        seen, refused = [], None
        for _ in range(30):
            r = lab.advance(60, "x")
            if r.get("escalation_required"):
                refused = r
                break
            if lab.anomaly:
                seen.append((lab.anomaly["field"], lab.anomaly["signal"]))
                lab.dismiss_anomaly("noise")
            if lab.phase != "season":
                break
        self.assertIsNotNone(refused, f"alarms seen: {seen}")
        e = refused["escalation_required"]
        self.assertGreaterEqual(e["alarms"], Lab.ESCALATE_AFTER)
        self.assertIn("error", lab.escalate(e["field"], "ignore", "unknown", "x"))
        lab.escalate(e["field"], "more_evidence", "unknown", "check it")
        self.assertIn("refused", lab.advance(10, "x"))                   # the evidence must come first
        lab.field_test(e["field"], "leaf_inspection", "x")
        self.assertNotIn("refused", lab.advance(5, "x"))
        kinds = [x["kind"] for x in lab.ledger.entries]
        self.assertIn("escalation", kinds)

    def test_accepting_a_loss_states_it_and_stops_the_loop(self):
        lab = Lab(Farm(seed=7), run_dir=tempfile.mkdtemp())
        lab.start_season(lab.plan_season("go")["plan_id"], "go", "rule", accept_nutrient_risk="test")
        lab.escalation_needed = {"field": "F2", "signal": "cc", "alarms": 3}
        r = lab.escalate("F2", "accept_loss", "model_limitation", "the crop is failing on this soil; nothing left to fix")
        self.assertTrue(r["ok"])
        self.assertIn(("F2", "cc"), lab.muted)
        self.assertIsNone(lab.escalation_needed)


class ScorerV21Tests(unittest.TestCase):
    """The four scoring probes from the second review: premature claims, unsupported guesses, censored follow-up,
    and signal attribution."""

    E = staticmethod(lambda t, kind, **d: {"t": t, "kind": kind, "data": d})

    def test_a_premature_claim_is_wrong(self):
        from worldlab.benchscore import score
        s = score([self.E(50, "model_update", finding="drip_delivery", field="F1", value=0.5)],
                  [{"kind": "clog", "field": "F1", "day": 90}], "clog")
        self.assertEqual((s["wrong_findings"], s["premature_claims"], s["faults_diagnosed"]), (1, 1, 0))

    def test_a_correct_guess_without_evidence_earns_no_diagnosis_or_justified_action(self):
        from worldlab.benchscore import score
        s = score([self.E(95, "model_update", finding="drip_delivery", field="F1", value=0.5),
                   self.E(96, "adjust", field="F1", repair={"repaired": True})], [{"kind": "clog", "field": "F1", "day": 90}], "clog")
        self.assertEqual((s["faults_diagnosed"], s["correct_guesses"], s["faults_justified_intervention"]), (0, 1, 0))

    def test_missing_follow_up_is_censored_not_a_success(self):
        from worldlab.benchscore import score
        E = self.E
        L = [E(100, "anomaly", field="F1", detected_day=100, signal="sw"), E(100, "model_update", finding="drip_delivery", field="F1", value=0.5),
             E(100, "adjust", field="F1", repair={"repaired": True}), E(110, "harvest", field="F1", day=110, crop="maize")]
        s = score(L, [{"kind": "clog", "field": "F1", "day": 90}], "clog")
        self.assertIsNone(s["events"][0]["no_realarm_30d"])
        self.assertEqual(s["follow_up_censored"], 1)

    def test_an_alarm_in_a_signal_the_cause_cannot_move_is_unexplained(self):
        from worldlab.benchscore import score
        s = score([self.E(100, "anomaly", field="F1", detected_day=100, signal="ec")], [{"kind": "sensor_bias", "field": "F1", "day": 90}], "sensor_bias")
        self.assertEqual(s["unrelated_alarms"], 1)

    def test_escalation_is_not_a_diagnosis(self):
        from worldlab.benchscore import score
        E = self.E
        L = [E(120, "anomaly", field="F5", detected_day=120, signal="cc"), E(121, "review_requested", field="F5", question="?")]
        s = score(L, [{"kind": "blight", "field": "F5", "day": 100}], "blight")
        self.assertEqual((s["faults"], s["faults_diagnosed"], s["unidentifiable_events"], s["unidentifiable_handled"]), (0, 0, 1, [True]))
