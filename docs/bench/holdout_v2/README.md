# Holdout v2: results against the pre-registered criteria

**Setup**
- **Suite:** eight new farms (seeds 601–608), frozen in `holdout_v2.json` (cases SHA-256 `bf86e4fd…5e5938a82`).
- **Criteria:** written in [`CRITERIA.md`](CRITERIA.md) before any run.
- **Freeze:** commit `b4144b8`.
- **Conditions:** three, each run once per farm, all with Meta perception (SAM 3.1 and Muse Spark vision):
  - Muse Spark on the new code;
  - Muse Spark on the code before the second-review fixes (`8c15a7e`, run from a separate checkout of that commit);
  - the scripted protocol with RL on the new code.
- **Runs:** all 24 completed. Every ledger and manifest is in `runs/`.
- **Scoring:** scorer 2.1. `summary.md` has the full table and `cases.md` lists every run.

| case | scripted (new) | Spark (new) | Spark (old) |
|---|---|---|---|
| h601 clog | 585.0 | 532.2 | 562.2 |
| h602 sensor bias | 678.4 | 723.2 | 663.2 |
| h603 saltier groundwater | 525.5 | 493.0 | 512.9 |
| h604 no fault | 435.5 | 442.2 | 449.3 |
| h605 root disease (no test shows it) | 648.0 | 610.8 | 571.0 |
| h606 compound (clog, then pests) | 486.7 | 471.2 | 482.3 |
| h607 pests | 524.0 | 489.4 | 465.7 |
| h608 heat wave | 640.9 | 639.7 | 669.4 |
| **mean people fed (simulated index)** | **565.5** | **550.2** | **547.0** |

| | scripted (new) | Spark (new) | Spark (old) |
|---|---|---|---|
| identifiable faults diagnosed, evidence first | 5/6 | 4/6 | 4/6 |
| wrong findings or actions | 0 | 0 | 2 |
| alarms no hidden event explains | 0 | 0 | 3 |
| root disease escalated to a person, no false cause | 1/1 | 1/1 | 1/1 |
| stayed calm when nothing was wrong | 2/2 | 2/2 | 2/2 |
| cost per season (list price) | $0.03 | $1.16 | $1.17 |

## C1. Did the planning fix remove catastrophic seasons? No measured improvement on this suite

- **Catastrophic seasons:** none in any condition. No season fell below 50% of the scripted result on its farm, with the
  old code or the new.
- **Spark new code minus old code:** +3.2 people fed (95% interval −17.1 to +25.8). The new code was ahead on 3 of 8
  farms.
- **What the evidence for the fix is:** these eight farms did not reproduce the failure the fix targets. So the evidence
  for the fix remains the development case it was built from: farm 204 under the heat wave, where Spark fed 26.4 people
  before the fix and 407.8 after (the scripted protocol fed 405.9), plus the regression tests (`PlanningLossTests`).
  That is one development case, not a held-out measurement.
- **Not a pre-registered criterion:** the old code made 2 wrong findings and raised 3 unexplained alarms; the new code
  made none. This is reported, not claimed.

## C2. Is there a measured benefit from Muse Spark over the scripted protocol? No measured benefit on this suite

None of the three pre-registered conditions was met:

- **People fed:** Spark (new) minus scripted (new) is **−15.3** (95% interval −34.0 to +5.6). Spark was ahead on 2 of 8
  farms.
- **Wrong findings or actions:** 0 against 0. Not fewer.
- **Identifiable faults diagnosed with evidence:** 4/6 against 5/6. Lower.

Comparator: the scripted protocol with RL. Sample: 8 farms, 1 run each.

## C3. Risk and escalation decisions

- **The nutrient-risk gate triggered on all 16 new-code seasons.** In every plan, vitamin A comes almost entirely from
  one sweet-potato field. If that field failed, 23–57 people would be fed in a bad year (Spark's plans).
- **No scientist took the backup.**
  - Spark accepted the risk every time and cited its evidence: the field's salinity against the fitted salt threshold
    and its 2-sd range, its trial yields, and the desalinated-water blend.
  - The scripted protocol accepted by its rule, because the backup cost more than 5% of the bad-year result.
- **No accepted field failed.** Every concentrated field yielded more than 20% of its planned median.
- **What the gate does and doesn't do:** it made every acceptance explicit and recorded, but it changed no plan. As
  calibrated, it fires whenever one crop supplies a nutrient, which in this crop set is always. A gate that fires only
  when the concentrated field's salt or heat margin is thin would be more informative. That is a next step, not done
  here.
- **Escalations:** one. On h605 (the root disease), Spark had already asked for a human review on F1. When the alarm
  repeated, it escalated with `accept_loss` and cause `model_limitation`, and kept modelling the measured decline. The
  scripted protocol needed no escalation on this suite.

## What this means

On unfamiliar farms, the second-review fixes made no measurable difference to harvest. Neither condition had a
catastrophic season, and the new code made no wrong calls where the old code made two. Muse Spark did not outperform
the scripted protocol on harvest, diagnosis or wrong calls.

The honest positioning stands: WorldLab is a transparent testbed for an experimental AI scientist. It shows what the
model decides, why, and how that compares with a strong hand-written protocol under the same tools and budgets. It does
not show that Muse Spark farms better.

## Reproduce

```bash
H=docs/bench/holdout_v2/holdout_v2.json
python -m worldlab bench2 --agents spark,scripted-rl --perception meta --holdout $H --out runs/holdout_v2/new
git worktree add ../wl-old 8c15a7e && (cd ../wl-old && python -m worldlab bench2 --agents spark --perception meta --holdout ../worldlab/$H --out ../worldlab/runs/holdout_v2/old)
python scripts/rescore.py docs/bench/holdout_v2/runs
python -m worldlab bench2-summary docs/bench/holdout_v2/runs --out docs/bench/holdout_v2 --reference "scripted-rl/meta (new code)"
```
