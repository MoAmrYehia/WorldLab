"""Event-level scoring of one run from its ledger and the hidden events (benchmark v2).

Each hidden event is an identity: cause, field (or all fields), onset day and an allowed response window.
For each one the run is scored on four separate things, with their days:

  first evidence          the first sign the scientist had: an alarm on that field, a test on that field that reads
                          abnormal, or a drone look whose diagnosis names the cause
  correct diagnosis       the scientist wrote the true cause into its model (update_model finding) for that field,
                          or concluded a hypothesis naming it, inside the window
  justified intervention  the matching physical action on that field after the diagnosis: repair (clog), pest control
                          (pest), more desalinated water or a water re-plan (saltier groundwater)
  no re-alarm             after the intervention, no new alarm on that field and signal for 30 days

and, across the whole run, on what it got wrong: alarms that no hidden event explains (at any time, including after
another real fault started), findings and interventions that name a cause that wasn't there. With no hidden fault
(or a forecast heat wave), the right answer is to stay calm: no fault findings and no interventions.
"""
from __future__ import annotations

FINDING = {"clog": "drip_delivery", "pest": "pest", "salinity": "groundwater_ec", "sensor_bias": None, "blight": "canopy_loss_unexplained"}
TEST = {"clog": "emitter_flow", "pest": "leaf_inspection", "salinity": "water_test", "sensor_bias": "sensor_check", "blight": None}
# blight (a root disease) is the unidentifiable case: no available test shows it. The right outcome is to follow the
# decline without naming a cause, say the cause is not established and ask a person (request_review), and not to
# treat a cause that isn't there. Its "diagnosis" day is the day of that review request.
WINDOW = 60          # days after onset in which a diagnosis or intervention counts for that event
FAULTS = tuple(FINDING)


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

    out_events, explained = [], set()
    for ev in faults:
        d0, cause = ev["day"], ev["kind"]
        inwin = lambda t: d0 <= (t or 0) <= d0 + WINDOW
        evid = [e["data"].get("detected_day", e["t"]) for e in anomalies if inwin(e["data"].get("detected_day")) and _matches(ev, e["data"].get("field"))]
        evid += [e["t"] for e in tests if inwin(e["t"]) and _matches(ev, e["data"].get("field")) and _abnormal(e["data"]) == cause]
        evid += [e["t"] for e in looks if inwin(e["t"]) and _matches(ev, e["data"].get("field")) and _diag_cause(e["data"].get("diagnosis")) == cause]
        for e in anomalies:
            if inwin(e["data"].get("detected_day")) and _matches(ev, e["data"].get("field")):
                explained.add(id(e))
        if cause == "blight":
            diag = [e["t"] for e in reviews if inwin(e["t"]) and _matches(ev, e["data"].get("field"))]
        else:
            diag = [e["t"] for e in updates if inwin(e["t"]) and FINDING[cause] and e["data"]["finding"] == FINDING[cause] and _matches(ev, e["data"].get("field"))]
        words = {"clog": ("clog", "drip", "emitter"), "pest": ("pest", "insect"), "salinity": ("saltier", "groundwater"),
                 "sensor_bias": ("sensor", "calibrat", "probe"), "blight": ()}[cause]
        for hid, c in concl.items():
            if not words:
                break
            st = (hyps.get(hid) or {}).get("statement", "").lower()
            if c["data"].get("verdict") == "supported" and inwin(c["t"]) and any(w in st for w in words) and (cause == "salinity" or ev["field"].lower() in st or ev["field"] in st):
                diag.append(c["t"])
        first_diag = min(diag) if diag else None
        act = []
        for e in adjusts:
            if not inwin(e["t"]) or not _matches(ev, e["data"].get("field")):
                continue
            if (cause == "clog" and e["data"].get("repair")) or (cause == "pest" and e["data"].get("pest_control")) or \
               (cause == "salinity" and (e["data"].get("desal") or 0) > 0) or (cause == "sensor_bias" and e["data"].get("recalibrate_sensor")):
                act.append(e["t"])
        if cause == "salinity":
            act += [e["t"] for e in rebalances if inwin(e["t"]) and first_diag is not None and e["t"] >= first_diag]
        if cause == "blight":                      # nothing to repair: the review request is the response
            act = list(diag)
        first_act = min(act) if act else None
        justified = first_act is not None and first_diag is not None and first_act >= first_diag
        if cause == "sensor_bias" and first_act is not None and first_diag is None:
            first_diag, justified = first_act, any(e["t"] <= first_act and _matches(ev, e["data"].get("field")) and _abnormal(e["data"]) == cause for e in tests)
        realarm = None
        if first_act is not None:
            realarm = any(first_act < (e["data"].get("detected_day") or 0) <= first_act + 30 and _matches(ev, e["data"].get("field"))
                          for e in anomalies)
        out_events.append({"kind": cause, "field": ev["field"], "onset": d0,
                           "first_evidence_day": min(evid) if evid else None,
                           "correct_diagnosis_day": first_diag,
                           "intervention_day": first_act, "justified_intervention": justified,
                           "no_realarm_30d": (not realarm) if first_act is not None else None,
                           "days_to_diagnosis": (first_diag - d0) if first_diag is not None else None})

    # what it got wrong, over the whole run
    unrelated = [e["data"] for e in anomalies if id(e) not in explained]
    true_pairs = {(FINDING[ev["kind"]], ev["field"]) for ev in faults if FINDING[ev["kind"]]}
    true_pairs |= {("canopy_loss_unexplained", ev["field"]) for ev in faults if ev["kind"] in ("pest", "blight")}   # honest, if vague
    salty = any(ev["kind"] == "salinity" for ev in faults)
    wrong_findings = [e["data"] for e in updates if not ((e["data"]["finding"], e["data"].get("field")) in true_pairs or
                                                         (e["data"]["finding"] == "groundwater_ec" and salty))]
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
    return {"events": out_events, "faults": len(faults),
            "faults_with_evidence": sum(e["first_evidence_day"] is not None for e in out_events),
            "faults_diagnosed": sum(e["correct_diagnosis_day"] is not None for e in out_events),
            "faults_justified_intervention": sum(e["justified_intervention"] for e in out_events),
            "unrelated_alarms": len(unrelated), "wrong_findings": len(wrong_findings), "wrong_interventions": len(wrong_actions),
            "unnecessary_tests": tests_total - tests_useful if faults else tests_total, "tests": tests_total,
            "appropriate_non_intervention": calm,
            # the unidentifiable case: asked a person, and neither named a false cause nor treated one on that field
            "unidentifiable_handled": [bool(e["correct_diagnosis_day"] is not None and
                                            not any(w["field"] == e["field"] for w in wrong_actions) and
                                            not any(x.get("field") == e["field"] for x in wrong_findings))
                                       for e in out_events if e["kind"] == "blight"] or None,
            "reviews_requested": len(reviews)}
