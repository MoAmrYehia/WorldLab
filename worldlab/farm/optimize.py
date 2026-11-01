"""Season planning: which crop on which field, with what management, to feed
the most people in a bad year.

For every field x crop x management option, the crop model is run over an
ensemble that pairs samples of the agent's trait beliefs with different
weather years. Each option then has a distribution of calories, protein,
vitamin A, water and energy. A coordinate-ascent search picks one option per
field to maximise the 10th percentile (a bad year) of people fed, where
people fed = the scarcest of the three needs, subject to the 90th-percentile
water use staying within the groundwater quota and energy within budget.
"""
from __future__ import annotations

import itertools

import numpy as np

from .crops import CROPS, CROP_IDS, NEEDS, NUTRIENTS, sow_options, TRAIT_IDS
from .sim import Sim, crop_arrays, soil_arrays
from .world import FIELDS, FIELD_HA, EC_GROUNDWATER
from . import weather as WX

MG_KEYS = ("sow", "density", "irr", "desal", "nfert", "mulch")


def options_for(crop: str, extra_sows=()) -> list[dict]:
    c = CROPS[crop]
    nf = [round(0.25 * c["nreq"])] if c["legume"] else [round(0.6 * c["nreq"]), c["nreq"]]
    out = []
    sows = sorted(set(sow_options(crop)) | set(int(x) for x in extra_sows))
    for sow, irr, desal, n in itertools.product(sows, (0.7, 0.9, 1.1), (0.0, 0.5), nf):
        out.append({"crop": crop, "sow": sow, "density": 1.0, "irr": irr, "desal": desal, "nfert": n, "mulch": 1.0})
    return out


def evaluate(beliefs: dict, S: int = 24, seed: int = 99, crops=None, ecgw: float = EC_GROUNDWATER,
             fields=None, field_idx=None, extra_sows: dict | None = None) -> dict:
    """Simulate every (field, crop, option) under S belief/weather samples."""
    crops = crops or CROP_IDS
    fields = fields or FIELDS
    field_idx = field_idx if field_idx is not None else list(range(len(fields)))
    rng = np.random.default_rng(seed)
    wx = WX.generate(S, seed)
    samples = {c: beliefs[c].sample(S, rng) for c in crops}
    extra_sows = extra_sows or {}
    opts = [(c, o) for c in crops for o in options_for(c, extra_sows.get(c, ()))]
    F, O = len(field_idx), len(opts)
    B = F * O * S
    crop_list, tr = [], {k: np.zeros(B) for k in TRAIT_IDS}
    mg = {k: np.zeros(B) for k in MG_KEYS}
    soils = []
    i = 0
    for fi in field_idx:
        for c, o in opts:
            sl = slice(i, i + S)
            crop_list += [c] * S
            for k in TRAIT_IDS:
                tr[k][sl] = samples[c][k]
            for k in MG_KEYS:
                mg[k][sl] = o[k]
            soils += [fields[fi]] * S
            i += S
    sim = Sim(crop_arrays(crop_list, tr), mg, soil_arrays(soils), wx, np.tile(np.arange(S), F * O),
              np.full(B, ecgw), eff=0.9).run()
    y = sim.fresh_yield().reshape(F, O, S)
    water = (sim.water_m3_ha() * FIELD_HA).reshape(F, O, S)
    energy = (sim.kwh_ha * FIELD_HA).reshape(F, O, S)
    per_kg = np.array([[CROPS[c]["kcal"], CROPS[c]["prot"], CROPS[c]["vita"]] for c, _ in opts])     # (O, 3)
    need = np.array([NEEDS[n] * 365.0 for n in NUTRIENTS])
    # person-years of each nutrient per field option: t/ha * 1000 kg * ha * per-kg / annual need
    people = y[..., None] * 1000.0 * FIELD_HA * per_kg[None, :, None, :] / need[None, None, None, :]   # (F, O, S, 3)
    return {"opts": opts, "field_idx": field_idx, "yield": y, "water": water, "energy": energy,
            "people": people, "S": S}


def _score(people_tot, water_tot, energy_tot, quota, ebudget, q=10, fed=None):
    """people_tot (..., S, 3) -> P10 of min nutrient; penalised for P90 overuse. fed overrides the people measure."""
    fed = people_tot.min(axis=-1) if fed is None else fed
    p = np.percentile(fed, q, axis=-1)
    w90 = np.percentile(water_tot, 90, axis=-1)
    e90 = np.percentile(energy_tot, 90, axis=-1)
    pen = 400 * (np.maximum(w90 / quota - 1, 0) + np.maximum(e90 / ebudget - 1, 0))
    return p - pen * (1 + np.abs(p)), p, w90, e90


def allowed_options(ev: dict, choices: list[dict | None]) -> dict:
    """Farmer choices per field position -> {field_pos: [option indices]} ([] = fallow).
    A choice is None (the scientist decides), {"fallow": True}, or {"crop": c, "sows": [days]}."""
    out = {}
    for f, ch in enumerate(choices):
        if not ch:
            continue
        if ch.get("fallow"):
            out[f] = []
            continue
        sows = set(ch.get("sows") or [])
        out[f] = [k for k, (c, o) in enumerate(ev["opts"]) if c == ch["crop"] and (not sows or o["sow"] in sows)]
        if not out[f]:
            raise ValueError(f"no planning option for {ch['crop']} on field {f + 1} in that season")
    return out


def single_field_loss(contribs: list[np.ndarray]) -> np.ndarray:
    """contribs: per field (S, 3) person-years. Returns (S,) people fed if the worst single field produced nothing."""
    tot = sum(contribs)
    return np.min([(tot - c).min(axis=-1) for c in contribs], axis=0) if contribs else np.zeros(1)


def optimise(ev: dict, quota_m3: float, energy_kwh: float, restarts: int = 10, seed: int = 0,
             fixed: dict | None = None, allowed: dict | None = None, robust: float = 0.0) -> dict:
    """Pick one option (or fallow, -1) per field. fixed: {field_pos: option index} kept as is.
    allowed: {field_pos: [option indices]} restricts a field to those options ([] = fallow only).
    robust (0-1): weight on the harvest if the worst single field fails (a crop lost to salt, heat or a fault), so the
    plan does not hang a whole nutrient on one field. 0 = the usual objective."""
    F = len(ev["field_idx"])
    P, Wt, E = ev["people"], ev["water"], ev["energy"]
    S = ev["S"]
    zeroP, zeroW = np.zeros((S, 3)), np.zeros(S)
    rng = np.random.default_rng(seed)
    best = None
    fixed = fixed or {}
    allowed = allowed or {}
    masks = {}
    for f, ks in allowed.items():
        m = np.full(len(ev["opts"]) + 1, -np.inf)
        if ks:
            m[np.array(ks) + 1] = 0.0
        else:
            m[0] = 0.0
        masks[f] = m
    for r in range(restarts):
        if r == 0:
            choice = np.full(F, -1)
        else:
            choice = rng.integers(-1, len(ev["opts"]), F)
        for f, ks in allowed.items():
            choice[f] = rng.choice(ks) if ks else -1
        for f, o in fixed.items():
            choice[f] = o
        for _ in range(8):
            changed = False
            for f in range(F):
                if f in fixed:
                    continue
                tp = sum((P[g, choice[g]] if choice[g] >= 0 else zeroP) for g in range(F) if g != f)
                tw = sum((Wt[g, choice[g]] if choice[g] >= 0 else zeroW) for g in range(F) if g != f)
                te = sum((E[g, choice[g]] if choice[g] >= 0 else zeroW) for g in range(F) if g != f)
                candP = np.concatenate([tp[None], tp[None] + P[f]], axis=0)          # (1+O, S, 3)
                candW = np.concatenate([tw[None], tw[None] + Wt[f]], axis=0)
                candE = np.concatenate([te[None], te[None] + E[f]], axis=0)
                fed = None
                if robust > 0:
                    n1 = np.broadcast_to(tp.min(axis=-1)[None], candP.shape[:2]).copy()     # field f lost
                    for g in range(F):
                        if g != f and choice[g] >= 0:
                            n1 = np.minimum(n1, (candP - P[g, choice[g]][None]).min(axis=-1))
                    fed = (1 - robust) * candP.min(axis=-1) + robust * n1
                sc, _, _, _ = _score(candP, candW, candE, quota_m3, energy_kwh, fed=fed)
                if f in masks:
                    sc = sc + masks[f]
                k = int(np.argmax(sc)) - 1
                if k != choice[f]:
                    choice[f], changed = k, True
            if not changed:
                break
        tp = sum((P[g, choice[g]] if choice[g] >= 0 else zeroP) for g in range(F))
        tw = sum((Wt[g, choice[g]] if choice[g] >= 0 else zeroW) for g in range(F))
        te = sum((E[g, choice[g]] if choice[g] >= 0 else zeroW) for g in range(F))
        fed = None
        if robust > 0:
            cs = [P[g, choice[g]] for g in range(F) if choice[g] >= 0]
            fed = ((1 - robust) * tp.min(axis=-1) + robust * single_field_loss(cs))[None]
        sc, p10, w90, e90 = _score(tp[None], tw[None], te[None], quota_m3, energy_kwh, fed=fed)
        if best is None or sc[0] > best[0]:
            best = (float(sc[0]), choice.copy(), tp, tw, te)
    _, choice, tp, tw, te = best
    fed = tp.min(axis=-1)
    lim_idx = np.argmin(tp, axis=-1)
    limiting = NUTRIENTS[int(np.bincount(lim_idx, minlength=3).argmax())]
    fields = []
    for f in range(F):
        fi = ev["field_idx"][f]
        if choice[f] < 0:
            fields.append({"field": FIELDS[fi]["id"], "field_index": fi, "crop": None})
            continue
        c, o = ev["opts"][choice[f]]
        y = ev["yield"][f, choice[f]]
        fields.append({"field": FIELDS[fi]["id"], "field_index": fi, "crop": c, "option": int(choice[f]),
                       "mgmt": {k: o[k] for k in MG_KEYS},
                       "yield_t_ha_p10_p50_p90": [round(float(np.percentile(y, q)), 2) for q in (10, 50, 90)],
                       "water_m3_p50": round(float(np.median(Wt[f, choice[f]]))),
                       "people_p50": {n: round(float(np.median(P[f, choice[f], :, j])), 1) for j, n in enumerate(NUTRIENTS)}})
    return {"fields": fields, "people_p10": round(float(np.percentile(fed, 10)), 1),
            "people_p50": round(float(np.median(fed)), 1),
            "by_nutrient_p50": {n: round(float(np.median(tp[:, j])), 1) for j, n in enumerate(NUTRIENTS)},
            "limiting": limiting,
            "water_p90_m3": round(float(np.percentile(tw, 90))), "water_p50_m3": round(float(np.median(tw))),
            "energy_p90_kwh": round(float(np.percentile(te, 90))),
            "within_limits": bool(np.percentile(tw, 90) <= quota_m3 * 1.001 and np.percentile(te, 90) <= energy_kwh * 1.001),
            "fed_samples": fed.round(1).tolist(), "robust_weight": robust}


def nutrient_risk(ev: dict, plan: dict, fields_meta: list[dict] | None = None, beliefs: dict | None = None) -> dict:
    """How much of each nutrient hangs on one field, and what is left if that field fails.

    For each nutrient: every field's median share, the largest share and its field. For the plan: people fed (P10)
    if the worst single field produced nothing, and which field that is. For a field carrying most of a nutrient: its
    own yield range, and its topsoil salinity against the crop's believed salt threshold (published threshold plus the
    scientist's current estimate of the local shift, with 2 sd)."""
    from .crops import CROPS
    P = ev["people"]
    rows, contribs = [], []
    for f in plan["fields"]:
        if f.get("crop") is None:
            continue
        pos = ev["field_idx"].index(f["field_index"])
        contribs.append((f, P[pos, f["option"]]))
    if not contribs:
        return {"level": "none"}
    tot = sum(c for _, c in contribs)
    fed = tot.min(axis=-1)
    by_n = {}
    for j, n in enumerate(NUTRIENTS):
        med = max(float(np.median(tot[:, j])), 1e-9)
        shares = {f["field"]: round(float(np.median(c[:, j])) / med, 3) for f, c in contribs}
        top = max(shares, key=shares.get)
        by_n[n] = {"total_p10": round(float(np.percentile(tot[:, j], 10)), 1), "largest_share": shares[top], "field": top,
                   "shares": shares}
    losses = []
    for f, c in contribs:
        left = (tot - c).min(axis=-1)
        losses.append((float(np.percentile(left, 10)), f))
    worst_p10, worst_f = min(losses, key=lambda x: x[0])
    p10 = float(np.percentile(fed, 10))
    out = {"people_p10": round(p10, 1), "if_worst_field_fails_p10": round(worst_p10, 1), "worst_field": worst_f["field"],
           "worst_field_crop": worst_f["crop"], "by_nutrient": by_n}
    conc = [(n, v) for n, v in by_n.items() if v["largest_share"] >= 0.6]
    details = []
    for n, v in conc:
        f = next(x for x, _ in contribs if x["field"] == v["field"])
        d = {"nutrient": n, "field": f["field"], "crop": f["crop"], "share": v["largest_share"],
             "field_yield_t_ha_p10_p50_p90": f.get("yield_t_ha_p10_p50_p90")}
        if fields_meta is not None and beliefs is not None:
            fm = fields_meta[f["field_index"]]
            b = beliefs[f["crop"]]
            i = 3                                   # salt shift
            thr = CROPS[f["crop"]]["salt"] + float(b.mean[i])
            sd = float(np.sqrt(b.cov[i, i]))
            d.update({"topsoil_ece_dS_m": fm["ece"][0], "believed_salt_threshold_dS_m": round(thr, 2),
                      "threshold_2sd_range": [round(thr - 2 * sd, 2), round(thr + 2 * sd, 2)],
                      "desal_blend": f["mgmt"]["desal"]})
        details.append(d)
    out["concentrated"] = details
    out["level"] = "high" if worst_p10 < 0.5 * p10 else ("watch" if conc else "low")
    out["explanation"] = (f"If {worst_f['field']} ({worst_f['crop']}) failed, the farm would feed {worst_p10:.0f} people in a bad year "
                          f"instead of {p10:.0f}." + (" " + "; ".join(f"{d['field']} carries {d['share']:.0%} of the {NUTRIENT_LABEL.get(d['nutrient'], d['nutrient'])}" for d in details) + "." if details else ""))
    return out


NUTRIENT_LABEL = {"kcal": "calories", "protein_g": "protein", "vitA_ug": "vitamin A"}
