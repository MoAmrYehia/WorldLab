"""Event-level scoring of one run from its ledger and the hidden events (benchmark v2). Scorer version 2.1.

Each hidden event is an identity: cause, field (or all fields), onset day and an allowed response window (60 days).

Identifiable faults (clog, pest, saltier groundwater, biased sensor) are scored on:

  first evidence          the first sign the scientist had: an alarm on that field in a signal the cause can move
                          (CAUSE_SIGNALS), a test on that field that reads abnormal for that cause, or a drone look whose
                          diagnosis names the cause
  supported diagnosis     the scientist wrote the true cause into its model (update_model finding) for that field, or
                          concluded a hypothesis naming it, inside the window AND on or after the first evidence. The
                          same claim made with no evidence yet is labelled a correct guess, and earns nothing
  justified intervention  the matching physical action on that field on or after a supported diagnosis: repair (clog),
                          pest control (pest), more desalinated water or a water re-plan (salinity), recalibration (sensor)
  no re-alarm (30 days)   after the intervention, no new alarm on that field in a signal the cause can move, for 30 days.
                          If the field was harvested or the season ended less than 30 days after the intervention, this is
                          None (censored): too little follow-up to say. No re-alarm is not physical recovery.

The unidentifiable case (blight, a root disease no available test can show) is scored separately as an escalation: a
review request for that field inside the window, after evidence, with no false cause named or treated on that field.
It is not counted as a diagnosis.

Across the whole run it counts what went wrong: alarms that no hidden event explains (by field, window and signal),
findings and actions that name a cause that wasn't there, including a true cause claimed BEFORE it happened (premature).
With no hidden fault (or a forecast heat wave), the right answer is to stay calm: no fault findings and no interventions.

Changes from 2.0 (archived runs keep their 2.0 score as score_v2_0): evidence must precede diagnosis credit; premature
claims count as wrong; follow-up is censored when there is too little of it; alarms are attributed by signal;
the unidentifiable case is an escalation, not a diagnosis.
"""
from __future__ import annotations

SCORER_VERSION = "2.1"
FINDING = {"clog": "drip_delivery", "pest": "pest", "salinity": "groundwater_ec", "sensor_bias": None, "blight": "canopy_loss_unexplained"}
TEST = {"clog": "emitter_flow", "pest": "leaf_inspection", "salinity": "water_test", "sensor_bias": "sensor_check", "blight": None}
# which monitored signals each cause can move (sw soil moisture, cc canopy cover, ec soil salinity)
CAUSE_SIGNALS = {"clog": {"sw", "ec", "cc"}, "pest": {"cc", "sw"}, "salinity": {"ec", "cc"}, "sensor_bias": {"sw"},
                 "blight": {"cc", "sw"}}
WINDOW = 60          # days after onset in which a diagnosis or intervention counts for that event
FOLLOW_UP = 30
D = 273
FAULTS = tuple(FINDING)
IDENTIFIABLE = ("clog", "pest", "salinity", "sensor_bias")


def _abnormal(test: dict) -> str | None:
    """Which cause a field test reading points to, if any."""
    t = test.get("test")
    if t == "emitter_flow" and (test.get("delivered_vs_design") or 1) < 0.7:
        return "clog"
    if t == "leaf_inspection" and test.get("pest_damage_seen"):
        return "pest"
    if t == "water_test" and (test.get("groundwater_ec_dS_m") or 0) > 6:
        return "salinity"
    if t == "sensor_check" and abs(test.get("sensor_minus_reference") or 0) > 0.025:
        return "sensor_bias"
    return None


def _diag_cause(d: dict | None) -> str | None:
    if not d:
        return None
    if d.get("pest_damage_visible") or d.get("condition") == "pest_damage":
        return "pest"
    return None                                   # salt crust or dry soil can follow from several causes: not a diagnosis


def _matches(ev: dict, field: str | None) -> bool:
    return ev["field"] in (None, "all") or field in (None, ev["field"]) or ev["kind"] == "salinity"


def _signal_ok(ev: dict, alarm: dict) -> bool:
    return alarm.get("signal") in CAUSE_SIGNALS.get(ev["kind"], set())


def score(entries: list[dict], events: list[dict], scenario: str) -> dict:
    """entries: ledger entries (kind, t, data). events: the hidden events as applied ({kind, field, day})."""
    L = [e for e in entries if isinstance(e, dict)]
    kinds = lambda k: [e for e in L if e.get("kind") == k]
    faults = [e for e in events if e["kind"] in FAULTS]
    anomalies = kinds("anomaly")
    tests = kinds("field_test")
    looks = kinds("look")
    updates = [e for e in kinds("model_update") if e["data"].get("finding")]
    adjusts = kinds("adjust")
    concl = {e["data"].get("hypothesis_id"): e for e in kinds("conclusion")}
    hyps = {e["data"].get("id"): e["data"] for e in kinds("hypothesis")}
    rebalances = kinds("rebalance")
    reviews = kinds("review_requested")
    harvest_day = {}
    for e in kinds("harvest"):
        harvest_day.setdefault(e["data"].get("field"), e["data"].get("day", e["t"]))
    end_day = max([e["t"] or 0 for e in L if e.get("kind") in ("season_result", "advance", "harvest")] + [0])

    out_events, explained = [], set()
    for ev in faults:
        d0, cause = ev["day"], ev["kind"]
        inwin = lambda t: d0 <= (t or 0) <= d0 + WINDOW
        alarms_here = [e for e in anomalies if inwin(e["data"].get("detected_day")) and _matches(ev, e["data"].get("field")) and _signal_ok(ev, e["data"])]
        for e in alarms_here:
            explained.add(id(e))
        evid = [e["data"].get("detected_day", e["t"]) for e in alarms_here]
        evid += [e["t"] for e in tests if inwin(e["t"]) and _matches(ev, e["data"].get("field")) and _abnormal(e["data"]) == cause]
        evid += [e["t"] for e in looks if inwin(e["t"]) and _matches(ev, e["data"].get("field")) and _diag_cause(e["data"].get("diagnosis")) == cause]
        first_ev = min(evid) if evid else None
        if cause == "blight":
            claims = [e["t"] for e in reviews if inwin(e["t"]) and _matches(ev, e["data"].get("field"))]
        else:
            claims = [e["t"] for e in updates if inwin(e["t"]) and FINDING[cause] and e["data"]["finding"] == FINDING[cause] and _matches(ev, e["data"].get("field"))]
            words = {"clog": ("clog", "drip", "emitter"), "pest": ("pest", "insect"), "salinity": ("saltier", "groundwater"),
                     "sensor_bias": ("sensor", "calibrat", "probe")}[cause]
            for hid, c in concl.items():
                st = (hyps.get(hid) or {}).get("statement", "").lower()
                if c["data"].get("verdict") == "supported" and inwin(c["t"]) and any(w in st for w in words) and (cause == "salinity" or ev["field"].lower() in st or ev["field"] in st):
                    claims.append(c["t"])
            if cause == "sensor_bias":            # recalibrating after a sensor check that showed the offset is the diagnosis
                claims += [e["t"] for e in adjusts if inwin(e["t"]) and _matches(ev, e["data"].get("field")) and e["data"].get("recalibrate_sensor")]
        supported = [t for t in claims if first_ev is not None and t >= first_ev]
        first_claim = min(claims) if claims else None
        first_diag = min(supported) if supported else None
        act = []
        for e in adjusts:
            if not inwin(e["t"]) or not _matches(ev, e["data"].get("field")):
                continue
            if (cause == "clog" and e["data"].get("repair")) or (cause == "pest" and e["data"].get("pest_control")) or \
               (cause == "salinity" and (e["data"].get("desal") or 0) > 0) or (cause == "sensor_bias" and e["data"].get("recalibrate_sensor")):
                act.append(e["t"])
        if cause == "salinity":
            act += [e["t"] for e in rebalances if inwin(e["t"])]
        if cause == "blight":                      # nothing to repair: the review request is the response
            act = list(supported)
        after = [t for t in act if first_diag is not None and t >= first_diag]
        first_act = min(after) if after else (min(act) if act else None)
        justified = bool(after)
        realarm = None
        if first_act is not None:
            f = ev["field"]
            last_obs = min(harvest_day.get(f, D), end_day or D) if f not in (None, "all") else (end_day or D)
            if last_obs - first_act < FOLLOW_UP:
                realarm = None                     # censored: not enough follow-up to say
            else:
                realarm = any(first_act < (e["data"].get("detected_day") or 0) <= first_act + FOLLOW_UP and _matches(ev, e["data"].get("field"))
                              and _signal_ok(ev, e["data"]) for e in anomalies)
        no_realarm = None if (first_act is None or realarm is None) else (not realarm)
        row = {"kind": cause, "field": ev["field"], "onset": d0, "severity": ev.get("severity"),
               "first_evidence_day": first_ev,
               "correct_claim_day": first_claim,
               "correct_guess": bool(first_claim is not None and first_diag is None),
               "intervention_day": first_act, "justified_intervention": justified,
               "no_realarm_30d": no_realarm, "follow_up_censored": bool(first_act is not None and realarm is None)}
        if cause == "blight":
            row["escalated_day"] = first_diag
            row["correct_diagnosis_day"] = None
            row["days_to_diagnosis"] = None
        else:
            row["correct_diagnosis_day"] = first_diag
            row["days_to_diagnosis"] = (first_diag - d0) if first_diag is not None else None
        out_events.append(row)

    # what it got wrong, over the whole run
    unrelated = [e["data"] for e in anomalies if id(e) not in explained]
    def true_at(finding: str, field: str | None, t: float) -> bool:
        for ev in faults:
            ok_field = ev["field"] in (None, "all") or field in (None, "all", ev["field"]) or ev["kind"] == "salinity"
            if not ok_field or (t or 0) < ev["day"]:
                continue                           # a cause claimed before it happened is a wrong claim
            if FINDING[ev["kind"]] == finding or (finding == "canopy_loss_unexplained" and ev["kind"] in ("pest", "blight")):
                return True
        return False
    wrong_findings = [{**e["data"], "t": e["t"]} for e in updates if not true_at(e["data"]["finding"], e["data"].get("field"), e["t"])]
    premature = [w for w in wrong_findings if any(FINDING[ev["kind"]] == w["finding"] and _matches(ev, w.get("field")) and w["t"] < ev["day"] for ev in faults)]
    wrong_actions = []
    for e in adjusts:
        f, d = e["data"].get("field"), e["t"] or 0
        if e["data"].get("repair") and not any(ev["kind"] == "clog" and ev["field"] == f and d >= ev["day"] for ev in faults):
            wrong_actions.append({"day": d, "field": f, "action": "repair"})
        if e["data"].get("pest_control") and not any(ev["kind"] == "pest" and ev["field"] == f and d >= ev["day"] for ev in faults):
            wrong_actions.append({"day": d, "field": f, "action": "pest control"})
        if e["data"].get("recalibrate_sensor") and not any(ev["kind"] == "sensor_bias" and ev["field"] == f and d >= ev["day"] for ev in faults):
            wrong_actions.append({"day": d, "field": f, "action": "sensor recalibration"})
    tests_total = len(tests)
    tests_useful = sum(1 for e in tests if any(_matches(ev, e["data"].get("field")) and e["t"] >= ev["day"] and
                                               (TEST[ev["kind"]] == e["data"].get("test") or ev["kind"] == "blight") for ev in faults))
    calm = None
    if not faults:                                # no fault (or a forecast heat wave): the right answer is no fault action
        calm = not wrong_findings and not wrong_actions
    ident = [e for e in out_events if e["kind"] in IDENTIFIABLE]
    blight = [e for e in out_events if e["kind"] == "blight"]
    return {"scorer_version": SCORER_VERSION, "events": out_events, "faults": len(ident),
            "faults_with_evidence": sum(e["first_evidence_day"] is not None for e in ident),
            "faults_diagnosed": sum(e["correct_diagnosis_day"] is not None for e in ident),
            "correct_guesses": sum(e["correct_guess"] for e in ident),
            "faults_justified_intervention": sum(e["justified_intervention"] for e in ident),
            "follow_up_censored": sum(e["follow_up_censored"] for e in ident),
            "unrelated_alarms": len(unrelated), "wrong_findings": len(wrong_findings), "premature_claims": len(premature),
            "wrong_interventions": len(wrong_actions),
            "unnecessary_tests": tests_total - tests_useful if faults else tests_total, "tests": tests_total,
            "appropriate_non_intervention": calm,
            # the unidentifiable case: escalated to a person after evidence, and no false cause named or treated there
            "unidentifiable_events": len(blight),
            "unidentifiable_handled": [bool(e["escalated_day"] is not None and
                                            not any(w["field"] == e["field"] for w in wrong_actions) and
                                            not any(x.get("field") == e["field"] for x in wrong_findings))
                                       for e in blight] or None,
            "reviews_requested": len(reviews)}
