# Benchmark v2

Every run is kept with its complete raw ledger (`runs/<scientist>__<perception>/<case>/ledger.jsonl.gz`) and a manifest.
The manifest records:

- source commit, prompt and tool-schema hashes, model IDs and perception mode;
- the hidden events, as scheduled and as applied;
- run status and harvest;
- the event-level score;
- token and call usage;
- the ledger's head hash.

`summary.md` and `summary.json` are computed from the manifests alone (`python -m worldlab bench2-summary`). `cases.md` lists every run.

## Design

- **Farms and scenarios:** 5 farm seeds (200–204) × 5 scenarios. On day 90 one hidden change happens:
  - *none:* nothing changes;
  - *clog:* a drip line drops to 45% delivery;
  - *pest:* an outbreak eats 3% of the canopy a day;
  - *salinity:* groundwater goes from 4.5 to 9 dS/m;
  - *heatwave:* a heat wave that appears in the forecast.
- **Fault field:** the affected field is the middle one among those growing a crop.
- **Scientists:** Muse Spark (`muse-spark-1.3`), and the scripted protocol with its learned irrigation policy as reference. They have the same tools, budgets and hard water and energy limits. Runs were recorded at source commit `5498e84` (prompt hash `3cbd1503…`, the same prompt as the recorded demo season).
- **Perception conditions:**
  - *meta:* SAM 3.1 plus Muse Spark vision;
  - *meta-sam:* SAM only;
  - *meta-vision:* Spark vision only;
  - *none:* drone canopy cover only, no image analysis;
  - *sim:* the simulator's own truth, as an upper bound.
- **Ablations:** run for Muse Spark on the clog and pest scenarios (10 cases each).
- **Scoring:** event by event (`worldlab/benchscore.py`). For each hidden event the score records:
  - first evidence;
  - correct diagnosis;
  - a justified action after the diagnosis;
  - no re-alarm within 30 days.

  Over the whole run it also counts alarms no hidden event explains, wrong findings and wrong actions.
- **Matched differences:** comparisons are paired by farm seed and case. The 95% intervals come from resampling farm seeds, because scenarios are clustered within a farm.

## Results

105 runs were attempted and 105 completed: no failures, timeouts or cancellations.

| scientist / perception | runs | people fed, mean | diagnosed | precision | justified actions | median days to diagnosis | unexplained alarms | wrong findings or actions | calm when nothing wrong | cost/season |
|---|---|---|---|---|---|---|---|---|---|---|
| scripted protocol + RL / meta | 25 | 471.3 | 15/15 | 15/15 | 15/15 | 15 | 1 | 0 | 10/10 | $0.02 |
| scripted protocol + RL / sim | 25 | 471.3 | 15/15 | 15/15 | 15/15 | 15 | 1 | 0 | 10/10 | $0 |
| Muse Spark / meta | 25 | 441.1 | 14/15 | 14/14 | 14/15 | 14 | 18 | 0 | 10/10 | $1.11 |

**Muse Spark minus the scripted protocol, people fed: −30.3** (95% interval −59.3 to −1.9). Spark was ahead in 9 of the 25 pairs.

- **By farm:** +18.9, −33.0, −49.9, −7.6 and −79.7.
- **By scenario (Spark against scripted, wins out of 5):**

| scenario | Muse Spark | scripted | Spark wins |
|---|---|---|---|
| none | 485.9 | 499.7 | 2 |
| clog | 472.3 | 478.4 | 2 |
| pest | 448.0 | 483.4 | 2 |
| salinity | 407.1 | 416.6 | 2 |
| heat wave | 391.9 | 478.6 | 1 |

### Perception ablation (Muse Spark, clog and pest, 10 cases each)

| perception | people fed, mean | diagnosed | median days to diagnosis | drone looks per season | field tests per season |
|---|---|---|---|---|---|
| SAM 3.1 + Spark vision | 460.2 | 9/10 | 14 | 4.1 | 1.4 |
| SAM 3.1 only | 453.2 | 9/10 | 14 | 4.0 | 1.5 |
| Spark vision only | 463.2 | 9/10 | 14 | 4.0 | 1.9 |
| no image analysis | 457.2 | 9/10 | 14 | 4.4 | 1.6 |
| *scripted protocol + RL, same cases* | *480.9* | *10/10* | *16.5* | *1.0* | *1.4* |

## What this shows

- **Muse Spark diagnoses as accurately as the protocol and makes no wrong calls**, but it does not farm better. It found 14 of 15 hidden faults, made no wrong findings or actions, and stayed calm on every no-fault and heat-wave farm. Over the season it fed significantly fewer people (−30.3).
- **The harvest gap comes from planning, not diagnosis.** The largest loss is farm 204 under the heat wave, where Spark fed 26.4 people:
  - Its plan put sweet potato, its only vitamin-A crop, on F6, the saltiest field (soil ECe about 7 dS/m against a crop threshold of 1.5).
  - The canopy alarm fired 15 times. Spark switched that field to fully desalinated water but never re-planned or replaced the crop.
  - F6 yielded 0.05 t/ha, and vitamin A became the limiting nutrient.
  - The farm grew enough energy for about 270 people. The "people fed" index takes the smallest of three nutrients, so a single failed crop can dominate it.
- **More alarms that no fault explains:** 18 against 1. Sixteen of them are the repeated canopy alarms on farm 204's failing sweet potato field described above; the other two are single alarms on farms 203 and 204.
- **The missed fault:** the clog on farm 201 raised no alarm under any of Spark's four perception conditions. Spark's plan watered that field at 110% of demand; the extra water hid the clog, and the maize still yielded 13.2 t/ha. The scripted plan watered at 90%, saw the alarm on day 109 and repaired the line. Generous irrigation hides clogs; the frozen holdout found the same thing on sandy fields.
- **The perception models don't change these outcomes.** On the clog and pest cases, removing SAM 3.1, Spark vision or both left diagnosis (9/10), time to diagnosis (14 days) and harvest within run-to-run noise. Here the decisive evidence is the field test that separates the hypotheses. The drone photo shapes the hypotheses but does not decide them.
- **The scripted protocol doesn't use perception at all:** its results are identical with Meta perception and with the simulator's truth. Its decisions follow from alarms and field tests only.
- **Cost:** about $1.11 per Spark season at list price. That covers about 35 scientist calls and roughly 600,000 prompt tokens, mostly re-sent context, plus perception calls. The scripted protocol costs $0.02, only for perception during investigations.

## Losses and unknowns

- **Repeats:** one run per case and condition. Spark's sampling variation is not measured.
- **Ablation coverage:** only the clog and pest scenarios.
- **Holdout:** the frozen holdout on new farms and new fault families is reported separately in [`../holdout/`](../holdout/).
- **Earlier benchmark:** benchmark v1 (`../spark/`, `../hard/`) scored the same 25 farm-scenarios with an earlier, run-level score: Muse Spark 455.9 against 471.3. That result was a different Spark run of the same cases; v2 supersedes it.

## Reproduce

```bash
MODEL_API_KEY=... python -m worldlab bench2 --agents spark,scripted-rl --perception meta --farms 5 --out runs/bench_v2
python -m worldlab bench2 --agents scripted-rl --perception sim --farms 5 --out runs/bench_v2
MODEL_API_KEY=... python -m worldlab bench2 --agents spark --perception none,meta-sam,meta-vision --farms 5 --scenarios clog,pest --out runs/bench_v2
python -m worldlab bench2-summary runs/bench_v2 --out docs/bench/v2 --reference scripted-rl/meta
```
