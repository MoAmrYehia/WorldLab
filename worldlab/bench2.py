"""Benchmark v2: every run is saved with its complete ledger and a manifest, and summaries are regenerated from
those manifests alone. Failed attempts stay in the denominator.

  python -m worldlab bench2 --agents spark,scripted-rl --perception meta --farms 5 --out runs/bench_v2
  python -m worldlab bench2-summary runs/bench_v2 --out docs/bench/v2

Perception conditions (the same interface for every scientist):
  meta         SAM 3.1 + Muse Spark vision on the synthetic drone images
  meta-sam     SAM 3.1 only          meta-vision   Muse Spark vision only
  none         no image analysis (telemetry and the drone's canopy measurement only)
  sim          direct simulator state: a diagnostic upper bound, not image perception
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from .agent import LLMScientist, ScriptedScientist, SYSTEM_PROMPT, TOOLS
from .benchscore import score, IDENTIFIABLE, SCORER_VERSION
from .farm.crops import CROP_IDS, TRAIT_IDS, TRAITS
from .farm.world import Farm, FIELDS
from .lab import Lab
from .llm import LLMConfig
from .perception import SimPerception

SCENARIOS = {"none": [], "clog": [("clog", 90)], "pest": [("pest", 90)], "salinity": [("salinity", 90)], "heatwave": [("heatwave", 90)]}
PRICES = {"source": "https://dev.meta.ai/docs/pricing-rate-limits (read 31 Oct 2026)",
          "muse-spark-1.3": {"input_per_m": 1.25, "cached_input_per_m": 0.15, "output_per_m": 4.25}, "sam-3.1": {"per_1000_images": 2.50}}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def provenance() -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or None
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "worldlab"], capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception:
        commit, dirty = None, None
    return {"source_commit": commit, "source_dirty": dirty, "prompt_sha256": _sha(SYSTEM_PROMPT.encode()),
            "tool_schema_sha256": _sha(json.dumps(TOOLS, sort_keys=True).encode())}


def perception_for(mode: str):
    if mode == "sim":
        return SimPerception()
    if mode == "none":
        return None
    from .perception import MetaPerception
    return MetaPerception(sam=mode in ("meta", "meta-sam"), vision=mode in ("meta", "meta-vision"))


def run_case(case: dict) -> dict:
    """case: {id, seed, agent, perception, events: [{kind, day, field?, severity?}], label, out, prov}"""
    out = Path(case["out"])
    out.mkdir(parents=True, exist_ok=True)
    farm = Farm(seed=case["seed"], weather=case.get("weather"))
    for ev in case["events"]:
        kw = {k: ev[k] for k in ("field", "severity", "pick") if ev.get(k) is not None}
        farm.schedule(ev["kind"], ev["day"], **kw)
    perc = perception_for(case["perception"])
    lab = Lab(farm, run_dir=out, perception=perc)
    t0 = time.time()
    usage, err = None, None
    try:
        a = case["agent"]
        if a == "scripted":
            ScriptedScientist(lab).run()
        elif a == "scripted-noadapt":
            ScriptedScientist(lab, adapt=False).run()
        elif a == "scripted-rl":
            ScriptedScientist(lab, rl=True).run()
        else:
            usage = LLMScientist(lab, LLMConfig.for_agent(a), max_turns=140).run()
        if not lab.done:
            lab.end_run("failed", "the scientist stopped before the season ended")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        lab.end_run("failed", f"internal error: {err[:160]}")
    wall = time.time() - t0
    entries = lab.ledger.entries
    applied = [{"kind": e["kind"], "field": e.get("field"), "day": e.get("day"), "severity": e.get("severity")} for e in farm.events]
    sc = score(entries, applied, case.get("label", ""))
    res = lab.result or {}
    # trait error on a fixed common set (all ten crops, four traits), and on the crops it planted
    common = [abs(lab.beliefs[c].mean[i] - farm.traits[c][k]) / TRAITS[k]["sd"] for c in CROP_IDS for i, k in enumerate(TRAIT_IDS)]
    planted = sorted({f["crop"] for f in getattr(lab, "run_plan", []) or [] if f.get("crop")})
    pl = [abs(lab.beliefs[c].mean[i] - farm.traits[c][k]) / TRAITS[k]["sd"] for c in planted for i, k in enumerate(TRAIT_IDS)]
    pc = getattr(perc, "client", None)
    raw = (out / "ledger.jsonl").read_bytes() if (out / "ledger.jsonl").exists() else b""
    (out / "ledger.jsonl.gz").write_bytes(gzip.compress(raw, mtime=0))
    (out / "ledger.jsonl").unlink(missing_ok=True)
    for f in ("images",):
        d = out / f
        if d.exists():
            for x in d.iterdir():
                x.unlink()
            d.rmdir()
    m = {"schema": "worldlab.bench/2", "case": case["id"], "label": case.get("label"), "seed": case["seed"], "agent": case["agent"],
         "scientist_model": LLMConfig.for_agent(case["agent"]).model if case["agent"] in ("spark", "glimmer") else None,
         "perception": case["perception"], "perception_models": {"meta": ["sam-3.1", "muse-spark-1.3"], "meta-sam": ["sam-3.1"],
                                                                 "meta-vision": ["muse-spark-1.3"]}.get(case["perception"], []),
         "hidden_events": case["events"], "applied_events": applied, **case["prov"],
         "status": lab.run_status, "status_reason": lab.run_end_reason, "error": err, "wall_seconds": round(wall, 1),
         "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "result": {"people_fed": res.get("people_fed"), "water_m3": res.get("water_used_m3"), "energy_kwh": res.get("energy_used_kwh"),
                    "within_limits": bool(res.get("within_quota") and res.get("within_energy")) if res else None,
                    "limiting": res.get("limiting")},
         "score": sc, "trait_error_common": round(float(np.mean(common)), 3), "trait_error_planted": round(float(np.mean(pl)), 3) if pl else None,
         "planted": planted, "controller": lab.controller, "plots": lab.plots_used, "tests": lab.tests_used,
         "looks": sum(1 for e in entries if e["kind"] == "look"),
         "usage": {"scientist_calls": (usage or {}).get("api_calls"), "scientist_attempts": (usage or {}).get("attempts"),
                   "scientist_tokens": (usage or {}).get("usage"), "perception_attempts": getattr(pc, "attempts", None),
                   "perception_calls": getattr(pc, "calls", None)},
         "artifacts": {"ledger.jsonl.gz": {"sha256": _sha(raw), "entries": len(entries), "head": entries[-1]["hash"] if entries else None}}}
    (out / "manifest.json").write_text(json.dumps(m, indent=1, default=str))
    return m


def plan(agents, perceptions, seeds, scenarios, out: str, holdout: list[dict] | None = None) -> list[dict]:
    prov = provenance()
    cases = []
    for ag in agents:
        for pm in perceptions:
            if ag.startswith("scripted") and pm in ("meta-sam", "meta-vision"):
                continue
            items = holdout or [{"id": f"s{s}-{sc}", "seed": s, "events": [{"kind": k, "day": d} for k, d in SCENARIOS[sc]], "label": sc}
                                for sc in scenarios for s in seeds]
            for it in items:
                cases.append({**it, "agent": ag, "perception": pm, "prov": prov,
                              "out": str(Path(out) / f"{ag}__{pm}" / it["id"])})
    return cases


def run(cases: list[dict], workers: int = 5, skip_done: bool = True):
    todo = [c for c in cases if not (skip_done and (Path(c["out"]) / "manifest.json").exists())]
    print(f"{len(cases)} cases, {len(todo)} to run", flush=True)
    with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(run_case, c): c for c in todo}
        for k, f in enumerate(as_completed(futs), 1):
            c = futs[f]
            try:
                m = f.result()
                print(f"[{k}/{len(todo)}] {c['agent']}/{c['perception']} {c['id']}: {m['status']}, {m['result']['people_fed']} people, "
                      f"diagnosed {m['score']['faults_diagnosed']}/{m['score']['faults']}, {m['wall_seconds']} s", flush=True)
            except Exception as e:                          # a crash still leaves a record
                Path(c["out"]).mkdir(parents=True, exist_ok=True)
                (Path(c["out"]) / "manifest.json").write_text(json.dumps({"schema": "worldlab.bench/2", "case": c["id"], "agent": c["agent"],
                                                                           "perception": c["perception"], "status": "failed",
                                                                           "error": f"{type(e).__name__}: {e}", "seed": c["seed"],
                                                                           "label": c.get("label"), "hidden_events": c["events"]}, indent=1))
                print(f"[{k}/{len(todo)}] {c['id']}: crashed {e}", flush=True)


# ------------------------------------------------------------------ summaries from manifests only

def load(out: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(Path(out).glob("*/*/manifest.json"))]


def _cost(m: dict) -> float | None:
    u = m.get("usage") or {}
    tok = u.get("scientist_tokens") or {}
    c = 0.0
    if tok:
        c += tok.get("prompt_tokens", 0) / 1e6 * PRICES["muse-spark-1.3"]["input_per_m"] + tok.get("completion_tokens", 0) / 1e6 * PRICES["muse-spark-1.3"]["output_per_m"]
    if u.get("perception_attempts"):
        c += u["perception_attempts"] / 1000 * PRICES["sam-3.1"]["per_1000_images"]
    return round(c, 3) if (tok or u.get("perception_attempts")) else None


def summarize(rows: list[dict], reference: str | None = None, boot: int = 2000) -> dict:
    """Per condition (agent/perception): attempts, completions, outcomes over completed runs, event-level scores,
    errors, cost; matched differences against a reference condition with a farm-seed cluster bootstrap."""
    conds = sorted({f"{m['agent']}/{m['perception']}" for m in rows})
    out = {"conditions": {}, "reference": reference, "prices": PRICES}
    by = {c: [m for m in rows if f"{m['agent']}/{m['perception']}" == c] for c in conds}
    mean = lambda v: round(float(np.mean(v)), 1) if v else None
    for c, ms in by.items():
        done = [m for m in ms if m.get("status") == "completed"]
        allev = [e for m in done for e in m["score"]["events"]]
        ev = [e for e in allev if e["kind"] in IDENTIFIABLE]               # diagnosable faults
        unid = [e for e in allev if e["kind"] == "blight"]
        clean = [m for m in done if m["score"]["faults"] == 0 and not m["score"].get("unidentifiable_events")]
        d2d = [e["days_to_diagnosis"] for e in ev if e["days_to_diagnosis"] is not None]
        wrong = sum(m["score"]["wrong_findings"] + m["score"]["wrong_interventions"] for m in done)
        made = sum(m["score"]["faults_diagnosed"] for m in done) + sum(m["score"]["wrong_findings"] for m in done)
        out["conditions"][c] = {
            "scorer_version": sorted({m["score"].get("scorer_version", "2.0") for m in done}),
            "attempted": len(ms), "completed": len(done), "status_counts": {s: sum(1 for m in ms if m.get("status") == s) for s in sorted({m.get("status") for m in ms})},
            "people_fed_mean_completed": mean([m["result"]["people_fed"] for m in done]),
            "water_m3_mean": mean([m["result"]["water_m3"] for m in done]), "energy_kwh_mean": mean([m["result"]["energy_kwh"] for m in done]),
            "within_limits": f"{sum(1 for m in done if m['result']['within_limits'])}/{len(done)}",
            "fault_events": len(ev), "events_with_evidence": sum(e["first_evidence_day"] is not None for e in ev),
            "diagnosis_recall": f"{sum(e['correct_diagnosis_day'] is not None for e in ev)}/{len(ev)}",
            "diagnosis_precision": f"{sum(m['score']['faults_diagnosed'] for m in done)}/{made}" if made else "–",
            "justified_interventions": f"{sum(e['justified_intervention'] for e in ev)}/{len(ev)}",
            "correct_guesses_without_evidence": sum(1 for e in ev if e.get("correct_guess")),
            "premature_claims": sum(m["score"].get("premature_claims", 0) for m in done),
            "follow_up_censored": sum(1 for e in ev if e.get("follow_up_censored")),
            "no_realarm_30d": f"{sum(1 for e in ev if e.get('no_realarm_30d') is True)}/{sum(1 for e in ev if e.get('no_realarm_30d') is not None)} observed",
            "unidentifiable_escalated_without_false_cause": f"{sum(sum(m['score'].get('unidentifiable_handled') or []) for m in done)}/{len(unid)}" if unid else "–",
            "note": "outcome metrics are over completed runs; attempted includes every run",
            "days_to_diagnosis_median": float(np.median(d2d)) if d2d else None,
            "unrelated_alarms": sum(m["score"]["unrelated_alarms"] for m in done),
            "wrong_findings_or_interventions": wrong,
            "unnecessary_tests": sum(m["score"]["unnecessary_tests"] for m in done),
            "calm_when_nothing_was_wrong": f"{sum(1 for m in clean if m['score']['appropriate_non_intervention'])}/{len(clean)}",
            "trait_error_common_mean": round(float(np.mean([m["trait_error_common"] for m in done])), 3) if done else None,
            "wall_seconds_median": float(np.median([m["wall_seconds"] for m in ms if m.get("wall_seconds")])) if ms else None,
            # list price: Spark scientist tokens, plus every perception call priced at SAM 3.1's per-image rate (Spark vision
            # tokens inside perception are not metered separately); runs that made no calls count as $0
            "cost_usd_list_price_mean": round(float(np.mean([_cost(m) or 0.0 for m in ms])), 3) if ms else None,
            "scientist_calls_mean": mean([m["usage"]["scientist_calls"] for m in ms if (m.get("usage") or {}).get("scientist_calls")]),
            "perception_attempts_mean": mean([m["usage"]["perception_attempts"] for m in ms if (m.get("usage") or {}).get("perception_attempts")]),
        }
    if reference and reference in by:
        ref = {(m["seed"], m["case"]): m for m in by[reference] if m.get("status") == "completed"}
        rng = np.random.default_rng(0)
        for c, ms in by.items():
            if c == reference:
                continue
            pairs = [(m["seed"], m["result"]["people_fed"] - ref[(m["seed"], m["case"])]["result"]["people_fed"])
                     for m in ms if m.get("status") == "completed" and (m["seed"], m["case"]) in ref]
            fld = lambda m: sorted((e["kind"], str(e.get("field")), e.get("day")) for e in (m.get("applied_events") or []))
            same_ev = sum(1 for m in ms if m.get("status") == "completed" and (m["seed"], m["case"]) in ref
                          and fld(m) == fld(ref[(m["seed"], m["case"])]))
            if not pairs:
                continue
            seeds = sorted({s for s, _ in pairs})
            diffs = np.array([d for _, d in pairs])
            bs = []
            for _ in range(boot):                       # resample farm seeds (scenarios are clustered within seeds)
                pick = rng.choice(seeds, len(seeds))
                bs.append(np.mean([d for s in pick for s2, d in pairs if s2 == s]))
            out["conditions"][c]["vs_reference"] = {
                "matched_pairs": len(pairs), "farm_seeds": len(seeds),
                "pairs_with_identical_realized_events": same_ev,
                "pairs_where_the_event_landed_differently": len(pairs) - same_ev, "mean_difference": round(float(diffs.mean()), 1),
                "ci95_seed_bootstrap": [round(float(np.percentile(bs, 2.5)), 1), round(float(np.percentile(bs, 97.5)), 1)],
                "ahead_in": f"{int((diffs > 0).sum())}/{len(pairs)}",
                "by_seed": {str(s): round(float(np.mean([d for s2, d in pairs if s2 == s])), 1) for s in seeds}}
    return out


def write_summary(src: str, dst: str, reference: str | None):
    rows = load(src)
    S = summarize(rows, reference)
    d = Path(dst)
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(S, indent=1))
    lines = [f"Scorer {', '.join(sorted({x for v in S['conditions'].values() for x in v['scorer_version']}))}. Outcomes are over completed runs; 'attempted' counts every run.", "",
             "| condition | attempted | completed | people fed, mean | within limits | diagnosed (with evidence) | precision | justified interventions | correct guesses without evidence | median days to diagnosis | no re-alarm in 30 days | unrelated alarms | wrong findings/actions (premature) | unidentifiable cause escalated | calm when nothing wrong | trait error (all crops) | cost/season (list price) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c, v in S["conditions"].items():
        lines.append(f"| {c} | {v['attempted']} | {v['completed']} | {v['people_fed_mean_completed']} | {v['within_limits']} | {v['diagnosis_recall']} | "
                     f"{v['diagnosis_precision']} | {v['justified_interventions']} | {v['correct_guesses_without_evidence']} | {v['days_to_diagnosis_median']} | "
                     f"{v['no_realarm_30d']} | {v['unrelated_alarms']} | {v['wrong_findings_or_interventions']} ({v['premature_claims']}) | "
                     f"{v['unidentifiable_escalated_without_false_cause']} | {v['calm_when_nothing_was_wrong']} | {v['trait_error_common_mean']} | "
                     f"{'$' + format(v['cost_usd_list_price_mean'], '.2f') if v['cost_usd_list_price_mean'] is not None else '–'} |")
    if reference:
        lines += ["", f"Matched differences in people fed against `{reference}` (same farm seed and hidden events; 95% interval from resampling farm seeds):", "",
                  "| condition | pairs | farm seeds | same realized events | event landed elsewhere | mean difference | 95% interval | ahead in |", "|---|---|---|---|---|---|---|---|"]
        for c, v in S["conditions"].items():
            r = v.get("vs_reference")
            if r:
                lines.append(f"| {c} | {r['matched_pairs']} | {r['farm_seeds']} | {r['pairs_with_identical_realized_events']} | {r['pairs_where_the_event_landed_differently']} | "
                             f"{r['mean_difference']:+} | {r['ci95_seed_bootstrap']} | {r['ahead_in']} |")
        lines += ["", "A hidden event's field is chosen from the fields growing a crop on that day, so it can depend on the scientist's plan: "
                  "'event landed elsewhere' pairs are matched by farm, scenario and onset, not by the exact field."]
    (d / "summary.md").write_text("\n".join(lines) + "\n")
    # every run, case by case: wins, losses and unknowns all listed
    cl = ["| case | scientist | status | people fed | hidden events → outcome | wrong findings/actions | unrelated alarms | reviews asked |",
          "|---|---|---|---|---|---|---|---|"]
    for m in sorted(rows, key=lambda m: (m.get("case", ""), m.get("agent", ""), m.get("perception", ""))):
        sc = m.get("score") or {}
        evs = []
        for e in sc.get("events", []):
            if e["kind"] == "blight":
                evs.append(f"{e['kind']} {e['field']} d{e['onset']}: " + ("review asked, no false cause" if (sc.get("unidentifiable_handled") or [False])[0]
                                                                         else "review asked" if e["correct_diagnosis_day"] is not None else "not escalated"))
            else:
                evs.append(f"{e['kind']} {e['field']} d{e['onset']}: " + (f"diagnosed d{e['correct_diagnosis_day']}" if e["correct_diagnosis_day"] is not None else "not diagnosed")
                           + (", justified action" if e["justified_intervention"] else ""))
        if not evs:
            evs = ["none: " + ("stayed calm" if sc.get("appropriate_non_intervention") else "acted on a fault that wasn't there")] if sc else ["–"]
        cl.append(f"| {m.get('case')} | {m.get('agent')}/{m.get('perception')} | {m.get('status')} | {(m.get('result') or {}).get('people_fed')} | "
                  f"{'; '.join(evs)} | {sc.get('wrong_findings', 0) + sc.get('wrong_interventions', 0) if sc else '–'} | {sc.get('unrelated_alarms', '–')} | {sc.get('reviews_requested', 0) if sc else '–'} |")
    (d / "cases.md").write_text("\n".join(cl) + "\n")
    # an index of the manifests, so the summary can be regenerated and checked
    (d / "manifests.json").write_text(json.dumps(rows, indent=1, default=str))
    print("\n".join(lines))
    return S
