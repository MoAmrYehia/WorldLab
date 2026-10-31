"""Photorealistic top-down drone frames of a drip-irrigated field, drawn from the simulator state.

Everything that a model could detect is driven by the simulation: canopy size from canopy cover, gaps
from stand loss, yellowing and leaf rolling from water stress, leaf-margin scorch and white salt
efflorescence from root-zone salinity, necrotic lesions and holes from pests, dry emitters from a
clogged drip line, darker wet soil from topsoil moisture. The renderer also reports what it drew
(plants, damaged plants, salt patches, dry emitters) so image models can be scored against it; the
agent never sees that record.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

try:                                     # JPEG keeps a photo-like frame near 100 kB; PNG is the fallback
    from PIL import Image as _PIL
except ImportError:                      # pragma: no cover
    _PIL = None

IW, IH = 960, 600
ROW_DY = 75                    # drip line (bed) spacing in pixels
ROW_Y0 = 40
EMITTER_DX = 30
_YY, _XX = np.mgrid[0:IH, 0:IW].astype(np.float32)

GRASS = {"wheat", "rice", "millet"}
STRAP = {"maize", "sorghum"}
PALMATE = {"cassava"}
BROAD = {"potato", "sweet_potato", "beans", "soybean"}

# leaf colour (sunlit), per crop: wheat is bluish green, maize deep green, potato mid green ...
LEAF = {"wheat": (92, 132, 70), "rice": (98, 140, 62), "millet": (104, 136, 64), "maize": (84, 136, 60),
        "sorghum": (88, 134, 62), "cassava": (66, 112, 52), "potato": (88, 138, 66),
        "sweet_potato": (82, 132, 64), "beans": (84, 130, 58), "soybean": (88, 128, 56)}
STRAW = np.array([196, 170, 118], np.float32)


def _upsample(a: np.ndarray, shape) -> np.ndarray:
    return ndimage.zoom(a, (shape[0] / a.shape[0], shape[1] / a.shape[1]), order=3, mode="reflect")[:shape[0], :shape[1]]


def fbm(rng, shape=(IH, IW), base=6, octaves=5, gain=0.55) -> np.ndarray:
    """Fractal value noise in about [-1, 1]."""
    out = np.zeros(shape, np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        g = rng.standard_normal((max(2, int(n * shape[0] / shape[1])) + 2, n + 2)).astype(np.float32)
        out += amp * _upsample(g, shape)
        tot += amp
        amp *= gain
    return out / tot


def _blend(img, color, alpha):
    a = alpha[..., None]
    img *= 1 - a
    img += a * np.asarray(color, np.float32)


def render(crop, cc, stand, ksw, ece_top, pest, done, wet=0.5, deliver=1.0, seed=1, stage=0.5,
           truth: dict | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = {"plants": 0, "damaged_plants": 0, "salt_patches": 0, "salt_cover_pct": 0.0, "dry_emitters": 0, "emitters": 0}

    # ---------------------------------------------------------------- soil: sandy loam with relief
    n1, n2 = fbm(rng, base=5), fbm(rng, base=24, octaves=3)
    grain = rng.standard_normal((IH, IW)).astype(np.float32)
    sand = np.array([186, 156, 116], np.float32)
    img = np.empty((IH, IW, 3), np.float32)
    img[:] = sand
    img += (14 * n1 + 7 * n2)[..., None] * np.array([1.0, 0.95, 0.85])
    img += (5 * grain)[..., None]
    # raised beds along the drip lines, lit from the upper left
    rows = np.arange(ROW_Y0, IH, ROW_DY, dtype=np.float32)
    phase = ((_YY - ROW_Y0) % ROW_DY) / ROW_DY                     # 0 at a drip line
    relief = np.cos(2 * math.pi * phase)                            # 1 on the bed, -1 in the furrow
    img *= (1 + 0.05 * relief - 0.05 * np.sin(2 * math.pi * phase))[..., None]
    # fine crumb texture and a few small stones with highlights
    crumb = fbm(rng, base=140, octaves=2)
    img += (6 * crumb)[..., None]
    k = int(260 + 200 * rng.random())
    px, py = rng.uniform(0, IW, k), rng.uniform(0, IH, k)
    pr = rng.gamma(1.6, 0.7, k) + 0.5
    pc = rng.uniform(-22, 26, k)
    for x, y, r, c in zip(px, py, pr, pc):
        x0, x1, y0, y1 = int(max(x - r - 3, 0)), int(min(x + r + 4, IW)), int(max(y - r - 3, 0)), int(min(y + r + 4, IH))
        if x1 <= x0 or y1 <= y0:
            continue
        X, Y = _XX[y0:y1, x0:x1] - x, _YY[y0:y1, x0:x1] - y
        d = np.hypot(X * 1.3, Y)
        sh = np.hypot((X - 1.0) * 1.3, Y - 1.0)
        img[y0:y1, x0:x1] *= (1 - 0.18 * np.clip(r + 0.6 - sh, 0, 1))[..., None]
        m = np.clip(r + 0.4 - d, 0, 1)
        img[y0:y1, x0:x1] += ((c + 10 * np.clip(-(X + Y) / (r + 1e-3), 0, 1)) * m)[..., None]

    # ---------------------------------------------------------------- moisture around emitters
    wetmask = np.zeros((IH, IW), np.float32)
    clogged_rng = np.random.default_rng(seed + 17)
    wobble = {}
    for ry in rows:
        w = 2.2 * np.sin(_XX[0] * 0.011 + ry) + 1.2 * np.sin(_XX[0] * 0.037 + 2 * ry)
        wobble[float(ry)] = w
        for ex in np.arange(12 + (ry * 7) % EMITTER_DX, IW, EMITTER_DX):
            t["emitters"] += 1
            if clogged_rng.random() > deliver:
                t["dry_emitters"] += 1
                continue
            r = (9 + 16 * wet) * rng.uniform(0.8, 1.2)
            y = ry + w[int(min(ex, IW - 1))]
            x0, x1, y0, y1 = int(max(ex - 2 * r, 0)), int(min(ex + 2 * r, IW)), int(max(y - 1.6 * r, 0)), int(min(y + 1.6 * r, IH))
            d = ((_XX[y0:y1, x0:x1] - ex) / (1.25 * r)) ** 2 + ((_YY[y0:y1, x0:x1] - y) / r) ** 2
            wetmask[y0:y1, x0:x1] = np.maximum(wetmask[y0:y1, x0:x1], np.clip(1.25 - d, 0, 1))
    wetmask = ndimage.gaussian_filter(wetmask, 2.5) * (0.35 + 0.65 * wet)
    wet_n = fbm(rng, base=30, octaves=2)
    img *= (1 - (0.55 + 0.08 * wet_n) * wetmask)[..., None]
    img[..., 2] *= 1 + 0.05 * wetmask                               # wet soil is slightly cooler

    # ---------------------------------------------------------------- salt efflorescence
    if ece_top > 4.0:
        k = float(np.clip((ece_top - 4.0) / 8.0, 0, 1))
        ridge = np.clip(-relief, 0, 1) ** 0.7                      # salt collects on the dry ridges between beds
        front = np.clip(1 - np.abs(wetmask - 0.18) / 0.14, 0, 1)    # and as a ring at the edge of the wetted zone
        s = fbm(rng, base=11, octaves=5) + 0.45 * ridge + 0.55 * front - 1.1 * wetmask - (1.2 - 1.0 * k)
        grain_s = np.clip(0.55 + 0.6 * fbm(rng, base=180, octaves=2), 0, 1)
        crust = np.clip(s * 2.6, 0, 1) * grain_s
        lab, n = ndimage.label(ndimage.gaussian_filter(crust, 1.5) > 0.3)
        if n:
            sizes = ndimage.sum(np.ones_like(crust), lab, range(1, n + 1))
            big = sizes >= 80
            t["salt_patches"] = int(big.sum())
            t["salt_cover_pct"] = round(float(100 * np.isin(lab, 1 + np.flatnonzero(big)).mean()), 1)
        _blend(img, (234, 231, 220), np.clip(0.75 * crust, 0, 0.75))
        _blend(img, (250, 249, 244), np.clip(crust - 0.7, 0, 1) * 0.6)  # bright crystalline flecks

    # ---------------------------------------------------------------- drip lines (black PE tube)
    for ry in rows:
        w = wobble[float(ry)]
        yline = ry + w[None, :]
        d = np.abs(_YY - yline)
        tube = np.clip(2.6 - d, 0, 1)
        img *= (1 - 0.30 * np.clip(3.8 - np.abs(_YY - yline - 2.5), 0, 1) * (1 - tube))[..., None]   # shadow
        _blend(img, (34, 34, 36), tube)
        _blend(img, (92, 92, 96), np.clip(0.9 - np.abs(_YY - yline + 1.0), 0, 1) * 0.6)                  # highlight

    # ---------------------------------------------------------------- plants
    t["separate_plants"] = bool(crop and not done and crop not in GRASS and 0.004 < cc < 0.3)   # countable one by one
    if crop and done:
        _stubble(img, rng, crop, rows, wobble)
    elif crop and cc > 0.004:
        _plants(img, rng, crop, cc, stand, ksw, ece_top, pest, rows, wobble, stage, t)

    # ---------------------------------------------------------------- camera: light falloff, softness, noise
    vign = 1 - 0.10 * (((_XX - IW / 2) / (IW / 2)) ** 2 + ((_YY - IH / 2) / (IH / 2)) ** 2)
    img *= (vign * (1.03 - 0.06 * (_XX + _YY) / (IW + IH)))[..., None]
    img = ndimage.gaussian_filter(img, (0.55, 0.55, 0))
    img += rng.normal(0, 1.6, img.shape).astype(np.float32)
    img = 255 * (np.clip(img, 0, 255) / 255) ** 0.96               # gentle tone curve
    if truth is not None:
        truth.update(t)
    return np.clip(img, 0, 255).astype(np.uint8)


def _stubble(img, rng, crop, rows, wobble):
    grass = crop in GRASS or crop in STRAP
    for ry in rows:
        w = wobble[float(ry)]
        for x in np.arange(10, IW, 11 if grass else 40):
            y = ry + w[int(min(x, IW - 1))] + rng.normal(0, 2)
            if grass:
                for _ in range(4):
                    a = rng.uniform(0, math.pi)
                    _leaf(img, x + rng.normal(0, 3), y + rng.normal(0, 3), rng.uniform(3, 7), 0.9, a, STRAW * rng.uniform(0.85, 1.05), "strap")
            else:
                _leaf(img, x, y, rng.uniform(6, 11), 4, rng.uniform(0, math.pi), np.array([120, 100, 74]) * rng.uniform(0.85, 1.1), "oval")


def _leaf(img, cx, cy, length, width, ang, color, shape, holes=None, lesions=None, scorch=0.0, alpha=1.0, base_dark=0.25,
          bend=0.0, veins=0.0, lift=1.0):
    """One leaf from (cx, cy) outward along `ang`: soft edges, midrib highlight, darker base."""
    reach = length + width + 2
    x0, x1 = int(max(cx - reach, 0)), int(min(cx + reach + 1, IW))
    y0, y1 = int(max(cy - reach, 0)), int(min(cy + reach + 1, IH))
    if x1 <= x0 or y1 <= y0:
        return
    X, Y = _XX[y0:y1, x0:x1] - cx, _YY[y0:y1, x0:x1] - cy
    ca, sa = math.cos(ang), math.sin(ang)
    u, v = X * ca + Y * sa, -X * sa + Y * ca                        # along, across
    s = np.clip(u / max(length, 1e-3), 0, 1)
    v = v - bend * length * s ** 2                                  # leaves arch and curve
    if shape == "strap":                                            # long ribbon: narrow sheath, widest a third out, long taper
        half = width * np.clip(0.35 + 1.9 * s, 0, 1) * np.clip((1 - s) / 0.62, 0, 1) ** 0.8
    elif shape == "oval":                                           # ovate, widest near the base
        half = width * np.sqrt(np.clip(1 - (2 * s - 0.8) ** 2 / 1.44, 0, 1))
    else:                                                           # lanceolate lobe
        half = width * np.sin(math.pi * s) ** 0.8
    inside = (u >= 0) & (u <= length)
    edge = np.clip((half - np.abs(v)) / 0.9, 0, 1) * inside
    if not edge.any():
        return
    a = edge * alpha
    rel = v / (half + 1e-3)
    sun = -(ca * 0.6 + sa * 0.8)                                    # which side of the midrib faces the sun
    shade = lift * (1 - base_dark * (1 - s) - 0.14 * np.abs(rel) + 0.10 * np.sign(sun) * rel)
    shade += 0.14 * np.clip(1 - np.abs(v) / 0.8, 0, 1) * inside      # midrib catches the light
    if veins:                                                       # parallel (grasses) or pinnate (broad leaves) veins
        if shape == "strap":
            shade += veins * 0.05 * np.sin(np.abs(v) * 3.1)
        else:
            shade -= veins * 0.07 * np.clip(np.sin((u - 1.6 * np.abs(v)) * 0.9), 0, 1) * (np.abs(rel) > 0.12)
    shade *= 1 + 0.04 * np.sin(u * 0.7 + v * 1.3)                   # small undulations
    col = np.asarray(color, np.float32)[None, None, :] * shade[..., None]
    if scorch > 0:                                                  # brown, dry tips and margins
        sc = np.clip((s - (1 - scorch)) / max(scorch, 1e-3), 0, 1) + np.clip(np.abs(v) / (half + 1e-3) - 0.75, 0, 1) * scorch
        col = col * (1 - sc[..., None]) + np.array([150, 112, 62], np.float32) * sc[..., None]
    if lesions:
        for (lu, lv, lr) in lesions:
            ly, lx = cy + lu * length * sa + lv * half.max() * ca, cx + lu * length * ca - lv * half.max() * sa
            d = np.hypot(_XX[y0:y1, x0:x1] - lx, _YY[y0:y1, x0:x1] - ly)
            m = np.clip(lr - d, 0, 1)
            ring = np.clip(lr + 0.9 - d, 0, 1) - m
            ring = np.clip(lr + 1.1 - d, 0, 1) - m
            col = col * (1 - m[..., None]) + np.array([84, 52, 28], np.float32) * m[..., None]
            col = col * (1 - 0.75 * ring[..., None]) + np.array([188, 170, 72], np.float32) * 0.75 * ring[..., None]
    if holes:
        for (hu, hv, hr) in holes:
            hy, hx = cy + hu * length * sa + hv * half.max() * ca, cx + hu * length * ca - hv * half.max() * sa
            a = a * np.clip(np.hypot(_XX[y0:y1, x0:x1] - hx, _YY[y0:y1, x0:x1] - hy) - hr, 0, 1)
    region = img[y0:y1, x0:x1]
    region *= 1 - a[..., None]
    region += a[..., None] * col


def _shadow(shadow, cx, cy, r):
    x0, x1, y0, y1 = int(max(cx - r, 0)), int(min(cx + r + 1, IW)), int(max(cy - r, 0)), int(min(cy + r + 1, IH))
    if x1 > x0 and y1 > y0:
        d = np.hypot(_XX[y0:y1, x0:x1] - cx, _YY[y0:y1, x0:x1] - cy) / r
        shadow[y0:y1, x0:x1] = np.maximum(shadow[y0:y1, x0:x1], np.clip(1.15 - d, 0, 1))


def _blades(img, shadow, rng, n, bx, by, ang, L, w, col, curv, hitmask=None):
    """Many grass blades at once: each blade is sampled along its length and splatted (painter's
    order, last write wins), so a drilled wheat row becomes a dense, fine-textured band."""
    m = 14
    tt = np.linspace(0, 1, m, dtype=np.float32)[None, :]
    dx, dy = np.cos(ang)[:, None], np.sin(ang)[:, None]
    px = bx[:, None] + dx * L[:, None] * tt - dy * curv[:, None] * L[:, None] * tt ** 2
    py = by[:, None] + dy * L[:, None] * tt + dx * curv[:, None] * L[:, None] * tt ** 2
    bright = (0.72 + 0.38 * tt) * (1 + 0.08 * np.sign(-(dx * 0.6 + dy * 0.8)))      # base in shade, tips lit
    c = col[:, None, :] * bright[..., None]
    if hitmask is not None:                                          # brown lesions on attacked blades
        les = (rng.random(px.shape) < 0.22) & hitmask[:, None]
        c[les] = np.array([104, 70, 38], np.float32)
    for off in (-0.5, 0.5) if w > 1.2 else (0.0,):
        xs = np.clip(np.rint(px - dy * off), 0, IW - 1).astype(np.int32).ravel()
        ys = np.clip(np.rint(py + dx * off), 0, IH - 1).astype(np.int32).ravel()
        img[ys, xs] = c.reshape(-1, 3)


def _plants(img, rng, crop, cc, stand, ksw, ece_top, pest, rows, wobble, stage, t):
    stress = float(np.clip(1 - ksw, 0, 1))
    salt = float(np.clip((ece_top - 6.0) / 8.0, 0, 1))
    base = np.array(LEAF.get(crop, (76, 124, 58)), np.float32)
    yellow = np.array([172, 162, 80], np.float32)
    ripen = float(np.clip((stage - 0.8) / 0.2, 0, 1))              # grain crops turn golden at the end
    drought = np.array([150, 150, 96], np.float32)                  # rolled leaves show their dull, grey-green undersides
    leaf_col = base * (1 - 0.85 * stress) + (0.5 * yellow + 0.5 * drought) * 0.85 * stress
    if crop in GRASS or crop in STRAP:
        leaf_col = leaf_col * (1 - 0.8 * ripen) + np.array([192, 170, 98], np.float32) * 0.8 * ripen
    grass, strap = crop in GRASS, crop in STRAP
    size = math.sqrt(max(cc, 0.0))
    roll = 1 - 0.45 * stress                                        # water-stressed leaves roll and narrow
    shadow = np.zeros((IH, IW), np.float32)
    hit_p = min(0.95, 0.35 + 25 * pest) if pest > 0.004 else 0.0

    if grass:                                                        # drilled in three rows per bed, tufts every few cm
        tufts = []
        for ry in rows:
            w = wobble[float(ry)]
            for sub in (-13, 0, 13):
                for px in np.arange(rng.uniform(0, 8), IW, 9.0):
                    if rng.random() > stand:
                        continue
                    y = ry + w[int(min(px, IW - 1))] + sub + rng.normal(0, 1.6)
                    tufts.append((px + rng.normal(0, 2), y, rng.random() < hit_p))
        tufts = np.array(tufts, np.float32).reshape(-1, 3)
        n_t = len(tufts)
        t["plants"] = int(n_t)
        t["damaged_plants"] = int(tufts[:, 2].sum()) if n_t else 0
        per = int(4 + 7 * size)
        idx = np.repeat(np.arange(n_t), per)
        rng.shuffle(idx)
        bx = tufts[idx, 0] + rng.normal(0, 1.2, len(idx))
        by = tufts[idx, 1] + rng.normal(0, 1.2, len(idx))
        ang = rng.uniform(0, 2 * np.pi, len(idx)).astype(np.float32)
        L = ((3 + 13 * size) * rng.uniform(0.5, 1.15, len(idx))).astype(np.float32)
        curv = rng.normal(0, 0.25, len(idx)).astype(np.float32)
        col = (leaf_col[None, :] * rng.uniform(0.82, 1.14, (len(idx), 1)) * rng.uniform(0.96, 1.04, (len(idx), 3))).astype(np.float32)
        if salt > 0:                                                 # scorched, straw-coloured tips on salty ground
            dry = rng.random(len(idx)) < 0.5 * salt
            col[dry] = col[dry] * 0.5 + np.array([176, 150, 96], np.float32) * 0.5
        rr = 3 + 12 * size
        for x, y, _ in tufts:
            _shadow(shadow, x + 0.4 * rr, y + 0.35 * rr, rr)
        shadow = ndimage.gaussian_filter(shadow, 2.5)
        img *= (1 - 0.40 * shadow)[..., None]
        _blades(img, shadow, rng, len(idx), bx, by, ang, L, 1.3 * roll + 0.2, col, curv, tufts[idx, 2] > 0)
        return

    spacing = 44
    plants = []
    for ry in rows:
        w = wobble[float(ry)]
        for px in np.arange(spacing / 2 + rng.uniform(0, 6), IW + spacing, spacing):
            if rng.random() > stand:
                continue
            cx = px + rng.normal(0, 2.5)
            cy = ry + w[int(np.clip(cx, 0, IW - 1))] + rng.normal(0, 2.0) - 2
            plants.append((cx, cy, rng.uniform(0.8, 1.15), rng.random() < hit_p))
    for cx, cy, vigor, _ in plants:                                  # soft shadows, sun from the upper left
        r = (6 + 30 * size) * vigor
        _shadow(shadow, cx + 0.35 * r, cy + 0.3 * r, r * 0.95)
    shadow = ndimage.gaussian_filter(shadow, 3.0)
    img *= (1 - 0.45 * shadow)[..., None]
    for cx, cy, vigor, hit in plants:
        if 0 <= cx < IW:
            t["plants"] += 1
            t["damaged_plants"] += int(hit)
        tone = leaf_col * rng.uniform(0.9, 1.08) * np.array([rng.uniform(0.96, 1.04), 1, rng.uniform(0.95, 1.05)])
        if strap:                                                    # maize, sorghum: long arching ribbon leaves
            nle = int(6 + 7 * size)
            a0 = rng.uniform(0, 2 * math.pi)
            leaves = []
            for j in range(nle):
                a = a0 + j * math.pi + rng.normal(0, 0.45) + 0.18 * j  # two-ranked, slowly twisting
                L = (10 + 74 * size) * vigor * rng.uniform(0.75, 1.1) * (1 - 0.45 * j / nle)
                leaves.append((L, a, j))
            for L, a, j in sorted(leaves, reverse=True):              # lower, longer leaves first and darker
                lift = 0.8 + 0.28 * (j / max(nle - 1, 1))
                old = j < nle * 0.4                                   # drought "fires" the oldest leaves from the tip
                _leaf(img, cx, cy, L, (1.4 + 3.0 * size) * roll, a, tone * rng.uniform(0.9, 1.1), "strap",
                      scorch=max(0.4 * salt, 0.6 * max(stress - 0.35, 0) / 0.65 if old else 0.0), base_dark=0.3, bend=rng.choice([-1, 1]) * rng.uniform(0.08, 0.26), veins=1.0, lift=lift,
                      lesions=[(rng.uniform(.2, .9), rng.uniform(-.5, .5), rng.uniform(1.8, 3.2)) for _ in range(rng.integers(4, 9))] if hit else None,
                      holes=[(rng.uniform(.2, .8), rng.uniform(-.3, .3), rng.uniform(2.0, 3.4)) for _ in range(rng.integers(2, 5))] if hit else None)
            _leaf(img, cx - 1, cy - 1, 4 + 6 * size, 1.6, a0, tone * 1.15, "strap", lift=1.05)   # the whorl
        else:                                                        # broad-leaved crops: overlapping leaves, upper ones lit
            nle = int((12 + 22 * size) * (0.55 if crop in PALMATE else 1))
            reach = (4 + 22 * size) * vigor
            leaves = []
            for j in range(nle):
                a = rng.uniform(0, 2 * math.pi)
                rr = reach * math.sqrt(rng.uniform(0.02, 1.0))
                leaves.append((rr, a))
            for rr, a in sorted(leaves, reverse=True):               # outer, lower leaves first
                lift = 0.84 + 0.24 * (1 - rr / (reach + 1e-3))
                lx, ly = cx + rr * math.cos(a), cy + rr * math.sin(a)
                L = (6 + 13 * size) * vigor * rng.uniform(0.75, 1.15) * (0.85 + 0.15 * roll)
                W = L * (0.52 if crop != "sweet_potato" else 0.66) * roll
                sev = min(1.0, 30 * pest)
                les = [(rng.uniform(.15, .9), rng.uniform(-.6, .6), rng.uniform(1.4, 3.0) * (0.5 + 0.7 * sev)) for _ in range(rng.integers(2, 6))] if hit and rng.random() < .85 else None
                hol = [(rng.uniform(.25, .8), rng.uniform(-.4, .4), rng.uniform(1.6, 3.2) * (0.5 + 0.7 * sev)) for _ in range(rng.integers(1, 3))] if hit and rng.random() < .7 else None
                if crop in PALMATE:                                  # cassava: 5-7 narrow lobes
                    for lb in range(int(rng.integers(5, 8))):
                        _leaf(img, lx, ly, L * 1.2, W * 0.22, a + (lb - 3) * 0.42, tone * rng.uniform(0.88, 1.1), "lobe",
                              scorch=0.4 * salt, lesions=les, holes=hol, lift=lift, veins=0.5, bend=rng.normal(0, 0.08))
                else:
                    _leaf(img, lx - 0.5 * L * math.cos(a), ly - 0.5 * L * math.sin(a), L, W, a,
                          tone * rng.uniform(0.88, 1.14), "oval", scorch=0.4 * salt, lesions=les, holes=hol,
                          lift=lift, veins=1.0, bend=rng.normal(0, 0.06), base_dark=0.12)
            if crop in PALMATE:                                      # the upper leaves cover the stem
                for lb in range(7):
                    _leaf(img, cx, cy, (5 + 12 * size) * vigor, (5 + 12 * size) * 0.2, rng.uniform(0, 2 * math.pi),
                          tone * rng.uniform(1.0, 1.12), "lobe", lift=1.05, veins=0.5)


def encode(img: np.ndarray, quality: int = 86) -> tuple[bytes, str]:
    """Frame bytes and their MIME type: JPEG when Pillow is installed, otherwise PNG."""
    if _PIL is not None:
        import io
        buf = io.BytesIO()
        _PIL.fromarray(img).save(buf, "JPEG", quality=quality, optimize=True)
        return buf.getvalue(), "image/jpeg"
    from ..pngio import encode_png
    return encode_png(img), "image/png"
