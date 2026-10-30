"""Daily crop + soil simulation, vectorised over a batch of field-seasons.

One batch element = one crop on one field under one management plan in one
weather year with one set of crop traits. The hidden farm uses this code
with the true traits and faults; the agent's model uses it with sampled
beliefs. Same physics, different knowledge.

Per day:
  phenology       growing degree days (base Tb, capped at Tu) -> fraction of cycle
  canopy          logistic growth to CCx (density, nitrogen, stand), senescence, pests
  water           3 soil layers (0-20, 20-50, 50-100 cm): rain + drip irrigation in,
                  drainage cascade, root uptake by layer, soil evaporation (mulch halves it)
  stress          water (FAO-56 depletion with ET-adjusted p), salinity (Maas-Hoffman on
                  root-zone ECe), nitrogen (saturating supply), extreme heat
  salt            salt mass per layer, carried by irrigation and drainage (leaching)
  biomass         AquaCrop normalised water productivity: dB = WP* x Tr/ET0
  yield           HI x biomass, cut by heat and drought during flowering, stand loss
                  and immaturity at season end
"""
from __future__ import annotations

import numpy as np

from .crops import CROPS, cgc_default, TRAITS
from .weather import SEASON_DAYS

LAYER_THICK = np.array([0.20, 0.30, 0.50])          # m
LAYER_TOP = np.array([0.0, 0.20, 0.50])
ROOT_WEIGHT = np.array([1.0, 0.7, 0.45])
SOILS = {
    "sand":       dict(fc=0.12, wp=0.05, sat=0.38, kd=0.80),
    "loamy_sand": dict(fc=0.16, wp=0.07, sat=0.40, kd=0.60),
    "sandy_loam": dict(fc=0.22, wp=0.10, sat=0.42, kd=0.45),
    "loam":       dict(fc=0.30, wp=0.14, sat=0.46, kd=0.30),
}
EC_DESAL = 0.4          # dS/m, RO product water
KWH_PUMP = 0.6          # kWh per m3 to pump and pressurise groundwater
KWH_DESAL = 3.5         # extra kWh per m3 for reverse osmosis
LEACH_FRACTION = 0.15
DRIP_EFF_NOMINAL = 0.90
PRE_IRRIGATION_MM = 30.0


def crop_arrays(crops: list[str | None], traits: dict[str, np.ndarray] | None = None) -> dict:
    """Parameter arrays for a batch. crops[i] None = fallow. traits are the four
    local-variety deviations (multipliers for wp and cgc, shifts for heat and salt)."""
    B = len(crops)
    t = {k: np.full(B, v["prior"], float) for k, v in TRAITS.items()}
    if traits:
        for k, v in traits.items():
            t[k] = np.broadcast_to(np.asarray(v, float), (B,)).copy()
    keys = ["Tb", "Tu", "gdd", "heat", "wp", "hi", "ccx", "kcb", "zr", "p", "salt", "slope", "nreq", "dry"]
    out = {k: np.zeros(B) for k in keys}
    out["f0"], out["f1"], out["cgc"] = np.zeros(B), np.zeros(B), np.zeros(B)
    out["legume"] = np.zeros(B, bool)
    out["active"] = np.array([c is not None for c in crops])
    for i, c in enumerate(crops):
        if c is None:
            c = "wheat"  # placeholder values; inactive
        p = CROPS[c]
        for k in keys:
            out[k][i] = p[k]
        out["f0"][i], out["f1"][i] = p["flower"]
        out["cgc"][i] = cgc_default(c)
        out["legume"][i] = p["legume"]
    out["wp"] = out["wp"] * t["wp"]
    out["cgc"] = out["cgc"] * t["cgc"]
    out["heat"] = out["heat"] + t["heat"]
    out["salt"] = np.maximum(out["salt"] + t["salt"], 0.2)
    return out


def soil_arrays(fields: list[dict]) -> dict:
    """fields[i]: {'layers': [texture x3], 'ece': [x3], 'soil_n': kg/ha, 'theta0': fraction of FC}"""
    B = len(fields)
    out = {k: np.zeros((B, 3)) for k in ("fc", "wpt", "sat", "kd", "ece0", "theta0")}
    out["soil_n"] = np.zeros(B)
    for i, f in enumerate(fields):
        for l, tex in enumerate(f["layers"]):
            s = SOILS[tex]
            out["fc"][i, l], out["wpt"][i, l], out["sat"][i, l], out["kd"][i, l] = s["fc"], s["wp"], s["sat"], s["kd"]
        out["ece0"][i] = f["ece"]
        out["theta0"][i] = out["wpt"][i] + f.get("theta0", 0.5) * (out["fc"][i] - out["wpt"][i])
        out["soil_n"][i] = f["soil_n"]
    for k in ("fc", "wpt", "sat", "kd"):
        if "adj_" + k in fields[0]:
            pass
    return out


class Sim:
    def __init__(self, crop: dict, mgmt: dict, soil: dict, wx: dict, widx, ecgw,
                 eff=DRIP_EFF_NOMINAL, deliver=None, pest=None, record: bool = False):
        """mgmt arrays (B,): sow (day), density, irr (fraction of ETc), desal (0..1),
        nfert (kg N/ha), mulch (0/1). wx: weather dict of (W, D) arrays; widx (B,).
        ecgw: groundwater salinity (B,) or (B, D). deliver: (B, D) delivered fraction
        (faults), pest: (B, D) daily canopy loss fraction. Both truth-only."""
        self.c, self.m, self.s = crop, mgmt, soil
        B = len(crop["Tb"])
        self.B = B
        self.wx = wx
        self.widx = np.asarray(widx, int)
        self.ecgw = np.asarray(ecgw, float)
        self.eff = np.broadcast_to(np.asarray(eff, float), (B,)).copy()
        self.deliver = deliver
        self.pest = pest
        self.record = record
        th = LAYER_THICK[None, :] * 1000.0                  # mm
        self.th = th
        self.FC = soil["fc"] * th
        self.WP = soil["wpt"] * th
        self.SAT = soil["sat"] * th
        self.kd = soil["kd"]
        # state
        self.W = soil["theta0"] * th                         # mm per layer
        self.salt = soil["ece0"] * LAYER_THICK[None, :] * soil["sat"]   # EC * m
        self.gdd = np.zeros(B)
        self.cc = np.zeros(B)
        self.bio = np.zeros(B)                               # g/m2
        self.stand = np.ones(B)
        self.hi_heat = np.ones(B)
        self.ws_fl_sum = np.zeros(B)
        self.ws_fl_n = np.zeros(B)
        self.done = np.zeros(B, bool)
        self.harvest_day = np.full(B, -1)
        self.yield_dry = np.zeros(B)
        self.gross_mm = np.zeros(B)
        self.deep_mm = np.zeros(B)
        self.tr_mm = np.zeros(B)
        self.es_mm = np.zeros(B)
        self.kwh_ha = np.zeros(B)
        self.ks_w = np.ones(B)
        self.ks_s = np.ones(B)
        self.day = 0
        dens = np.asarray(mgmt["density"], float)
        self.dens_factor = (1 - np.exp(-2.5 * dens)) / (1 - np.exp(-2.5))
        r = (soil["soil_n"] + 0.6 * np.asarray(mgmt["nfert"], float) + crop["legume"] * 0.8 * crop["nreq"]) / crop["nreq"]
        self.ks_n = np.minimum((1 - np.exp(-3 * r)) / (1 - np.exp(-3)), 1.0)
        self.trace: dict[str, list] = {k: [] for k in ("cc", "theta", "ece", "bio", "ksw", "gross", "frac")} if record else {}

    # -------------------------------------------------------------- helpers
    def ece_layers(self):
        return self.salt / (LAYER_THICK[None, :] * self.s["sat"])

    def root_frac(self, frac):
        zr_now = 0.15 + (self.c["zr"] - 0.15) * np.clip(frac / 0.5, 0, 1)
        return np.clip((zr_now[:, None] - LAYER_TOP[None, :]) / LAYER_THICK[None, :], 0, 1)

    def frac(self):
        return self.gdd / self.c["gdd"]

    def irrigation_demand(self, d: int) -> np.ndarray:
        """Gross drip irrigation (mm) the controller would apply today."""
        c, m = self.c, self.m
        et0 = self.wx["et0"][self.widx, d]
        sown = (d >= m["sow"]) & c["active"] & ~self.done
        etc = (c["kcb"] * self.cc + 0.3 * (1 - self.cc) * (1 - 0.5 * m["mulch"])) * et0
        irr = m["irr"] if np.ndim(m["irr"]) == 1 else m["irr"][:, d]
        g = np.where(sown, irr * etc * (1 + LEACH_FRACTION) / DRIP_EFF_NOMINAL, 0.0)
        g = g + np.where((d == m["sow"]) & c["active"], PRE_IRRIGATION_MM, 0.0)
        return g

    # ---------------------------------------------------------------- step
    def step(self, irrigation_mm=None):
        d = self.day
        c, m = self.c, self.m
        wi = self.widx
        tmax, tmin = self.wx["tmax"][wi, d], self.wx["tmin"][wi, d]
        et0, rain = self.wx["et0"][wi, d], self.wx["rain"][wi, d]
        sown = (d >= m["sow"]) & c["active"] & ~self.done

        # irrigation (gross is what the meter sees; delivered is what reaches the soil)
        gross = self.irrigation_demand(d) if irrigation_mm is None else np.asarray(irrigation_mm, float)
        fac = self.eff if self.deliver is None else self.eff * self.deliver[:, d]
        delivered = gross * fac
        ecgw = self.ecgw if self.ecgw.ndim == 1 else self.ecgw[:, d]
        desal = m["desal"] if np.ndim(m["desal"]) == 1 else m["desal"][:, d]
        ecw = (1 - desal) * ecgw + desal * EC_DESAL
        self.gross_mm += gross
        self.kwh_ha += gross * 10.0 * (KWH_PUMP + KWH_DESAL * desal)

        # phenology
        tmean = (tmax + tmin) / 2
        ginc = np.where(sown, np.clip(np.minimum(tmean, c["Tu"]) - c["Tb"], 0, None), 0.0)
        self.gdd += ginc
        frac = self.frac()
        emerge = sown & (frac >= 0.04) & (self.cc <= 0)
        self.cc = np.where(emerge, 0.012 * np.asarray(m["density"]), self.cc)

        # water in: rain + delivered irrigation to the top layer, salt with it
        W = self.W
        W[:, 0] += rain + delivered
        self.salt[:, 0] += delivered / 1000.0 * ecw
        # drainage cascade (excess over field capacity, faster above saturation)
        for l in range(3):
            over_sat = np.maximum(W[:, l] - self.SAT[:, l], 0)
            excess = np.maximum(W[:, l] - over_sat - self.FC[:, l], 0) * self.kd[:, l] + over_sat
            share = np.where(W[:, l] > 0, excess / np.maximum(W[:, l], 1e-9), 0)
            moved_salt = self.salt[:, l] * share
            W[:, l] -= excess
            self.salt[:, l] -= moved_salt
            if l < 2:
                W[:, l + 1] += excess
                self.salt[:, l + 1] += moved_salt
            else:
                self.deep_mm += excess

        # stresses
        rf = self.root_frac(frac)
        taw_l = np.maximum(self.FC - self.WP, 0) * rf
        aw_l = np.clip(W - self.WP, 0, None) * rf
        taw = taw_l.sum(1) + 1e-6
        aw = np.minimum(aw_l, taw_l * 1.3).sum(1)
        p_adj = np.clip(c["p"] + 0.04 * (5 - c["kcb"] * np.maximum(self.cc, 0.1) * et0), 0.1, 0.8)
        ks_w = np.clip(aw / ((1 - p_adj) * taw), 0, 1)
        wts = rf * LAYER_THICK[None, :] * ROOT_WEIGHT[None, :]
        wsum = wts.sum(1) + 1e-9
        ece_rz = (self.ece_layers() * wts).sum(1) / wsum
        ks_s = np.clip(1 - c["slope"] / 100.0 * (ece_rz - c["salt"]), 0, 1)
        heat_f = np.clip(1 - 0.04 * np.maximum(tmax - (c["Tu"] + 10), 0), 0.5, 1)

        # canopy
        ccx_eff = c["ccx"] * self.dens_factor * self.stand * (0.6 + 0.4 * self.ks_n)
        growing = sown & (frac < 0.70) & (self.cc > 0)
        dcc = c["cgc"] * ginc * self.cc * (1 - self.cc / np.maximum(ccx_eff, 1e-3)) * ks_w * np.sqrt(ks_s)
        cc = np.where(growing, self.cc + dcc, self.cc)
        sen = sown & (frac >= 0.75)
        cc = np.where(sen, cc - ccx_eff * ginc / (0.25 * c["gdd"]) * 0.9, cc)
        cc = np.where(sown & (ks_w < 0.3) & (cc > 0), cc - 0.01 * (0.3 - ks_w) / 0.3, cc)
        if self.pest is not None:
            cc = cc * (1 - self.pest[:, d])
        self.cc = np.clip(np.where(sown, cc, self.cc), 0, 1)

        # transpiration and evaporation
        tr = np.where(sown, c["kcb"] * self.cc * et0 * ks_w * np.sqrt(ks_s), 0.0)
        es_pot = 1.1 * (1 - self.cc) * et0 * (1 - 0.5 * m["mulch"])
        top_avail = np.maximum(W[:, 0] - 0.5 * self.WP[:, 0], 0)
        es = np.minimum(es_pot * np.clip(top_avail / np.maximum(self.FC[:, 0] - 0.5 * self.WP[:, 0], 1e-6), 0, 1), top_avail)
        W[:, 0] -= es
        avail = np.clip(W - self.WP, 0, None) * (rf > 0)
        share = wts / wsum[:, None]
        take = np.minimum(tr[:, None] * share, avail)
        W -= take
        tr = take.sum(1)
        self.tr_mm += tr
        self.es_mm += es

        # biomass and flowering stress
        self.bio += np.where(sown, c["wp"] * tr / np.maximum(et0, 0.5) * np.sqrt(ks_s) * self.ks_n * heat_f, 0.0)
        fl = sown & (frac >= c["f0"]) & (frac <= c["f1"])
        self.hi_heat = np.where(fl & (tmax > c["heat"]), self.hi_heat * np.clip(1 - 0.07 * (tmax - c["heat"]), 0.2, 1), self.hi_heat)
        self.ws_fl_sum += np.where(fl, ks_w, 0.0)
        self.ws_fl_n += fl
        self.stand = np.where(sown & (self.cc > 0) & ((ks_w < 0.08) | (ks_s < 0.15)), self.stand * 0.97, self.stand)
        self.ks_w, self.ks_s = ks_w, ks_s

        # maturity or end of season
        mature = sown & (frac >= 1.0)
        last = d == SEASON_DAYS - 1
        harvest = mature | (last & c["active"] & ~self.done & (d >= m["sow"]))
        if harvest.any():
            fl_ws = np.where(self.ws_fl_n > 0, self.ws_fl_sum / np.maximum(self.ws_fl_n, 1), 1.0)
            immature = np.clip((np.minimum(frac, 1) - 0.6) / 0.4, 0, 1)
            y = self.bio * c["hi"] * self.hi_heat * (0.45 + 0.55 * fl_ws) * immature * np.sqrt(self.stand) / 100.0
            self.yield_dry = np.where(harvest, y, self.yield_dry)
            self.harvest_day = np.where(harvest, d, self.harvest_day)
            self.done |= harvest
        if self.record:
            self.trace["cc"].append(self.cc.copy())
            self.trace["theta"].append((W / self.th).copy())
            self.trace["ece"].append(ece_rz.copy())
            self.trace["bio"].append(self.bio.copy())
            self.trace["ksw"].append(ks_w.copy())
            self.trace["gross"].append(gross.copy())
            self.trace["frac"].append(np.minimum(frac, 1.0).copy())
        self.day += 1
        return gross

    def run(self, until: int = SEASON_DAYS):
        while self.day < until:
            self.step()
        return self

    def fresh_yield(self):
        """Harvested product, t/ha fresh (grain at storage moisture, roots and tubers fresh)."""
        return np.where(self.c["active"], self.yield_dry / self.c["dry"], 0.0)

    def water_m3_ha(self):
        return self.gross_mm * 10.0

    def traces(self) -> dict:
        return {k: np.stack(v, axis=1) for k, v in self.trace.items() if v}


def run_batch(crops, traits, mgmt, fields, wx, widx, ecgw, **kw) -> Sim:
    sim = Sim(crop_arrays(crops, traits), {k: np.asarray(v, float) for k, v in mgmt.items()},
              soil_arrays(fields), wx, widx, ecgw, **kw)
    return sim.run()


def cap_to_budget(gross_mm: np.ndarray, desal: np.ndarray, water_left_m3, energy_left_kwh, ha: float):
    """Hard-budget allocation rule, shared by the real farm and every imagined season.

    gross_mm (..., F): today's proposed drip application per field; desal the same shape.
    water_left_m3 / energy_left_kwh (...): what remains of the season's groundwater quota and
    energy budget. Desalinated water is made from the same brackish groundwater (reverse
    osmosis), so every applied cubic metre counts against the groundwater quota; recovery
    losses in the RO plant are not modelled. If today's demand exceeds what remains, every
    field is scaled by the same factor (proportional curtailment), so no field gets more than
    the remaining budget allows and nothing goes negative. Returns (capped_mm, factor)."""
    g = np.maximum(np.asarray(gross_mm, float), 0.0)
    vol = g * 10.0 * ha
    kwh = vol * (KWH_PUMP + KWH_DESAL * np.asarray(desal, float))
    wl = np.maximum(np.asarray(water_left_m3, float), 0.0)
    el = np.maximum(np.asarray(energy_left_kwh, float), 0.0)
    need_w, need_e = vol.sum(-1), kwh.sum(-1)
    fw = np.where(need_w > 1e-9, wl / np.maximum(need_w, 1e-9), 1.0)
    fe = np.where(need_e > 1e-9, el / np.maximum(need_e, 1e-9), 1.0)
    f = np.clip(np.minimum(fw, fe), 0.0, 1.0)
    return g * np.expand_dims(f, -1), f
