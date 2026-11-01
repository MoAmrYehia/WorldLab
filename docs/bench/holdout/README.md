# Frozen holdout challenge v1

Eight unfamiliar cases, generated once and committed **before any run**, so nothing was tuned against them.

- **The suite:** `holdout_v1.json` (cases SHA-256 `3f80955a…dfccf321d`).
- **Generator:** `scripts/make_holdout.py`, seed 20261101, run at commit `43f4299`.
- **Frozen at:** commit `9ab1c57`.
- **Prompt and tools:** the prompt and tool-schema hashes are recorded in the suite file and in every run's manifest.

## Protocol (as frozen)

- **Farms:** new farm seeds 401–408, never used before, one per case.
- **Cases:** one per family:
  - clean control;
  - forecast heat wave;
  - clogged drip line;
  - pest outbreak;
  - saltier groundwater;
  - compound (a clog, then pests in another field);
  - a biased soil-moisture sensor;
  - a root disease that no available test can detect. For that case the right answer is "cause not established, ask a person".
- **Randomisation:**
  - Onset day is drawn from 75–150 (heat wave 120–170), severity from each family's range.
  - The affected field is picked at random among the fields growing a crop on that day. So it depends on the scientist's own plan, and the two scientists can face the fault on different fields.
- **Scientists:** two, with the same tools, test budget, trial budget and hard water and energy limits:
  - **Muse Spark** (`muse-spark-1.3`), with SAM 3.1 and Muse Spark vision as perception;
  - **the scripted protocol with RL**, with the same perception.
- **Runs:** one run each; every run is kept.
- **Agent-visible information:** hidden event schedules and simulator truth are never in any tool response. `HoldoutTests.test_agent_tools_never_see_hidden_events` checks this.
- **Scoring:** event by event (`worldlab/benchscore.py`). For each hidden event the score records:
  - first evidence;
  - correct diagnosis (for the root disease: a review request on that field);
  - a justified action;
  - no re-alarm within 30 days.

  Over the whole run it also counts unexplained alarms, wrong findings and wrong actions.

## Results

`summary.md` has the full table; `cases.md` lists every run. Raw ledgers and manifests are in `runs/`.

| | Muse Spark | Scripted protocol + RL |
|---|---|---|
| Completed | 8/8 | 8/8 |
| People fed, mean (simulated index) | 474.4 | 483.1 |
| Hidden faults diagnosed | 5/7 | 5/7 |
| Diagnosis precision (correct diagnoses ÷ all fault findings) | 5/8 | 5/6 |
| Justified interventions | 5/7 | 5/7 |
| Median days from onset to diagnosis | 15 | 15 |
| Unexplained alarms | 2 | 7 |
| Wrong findings or actions | 3 | 1 |
| Stayed calm when nothing was wrong (control, heat wave) | 2/2 | 2/2 |
| Unidentifiable cause escalated to a person, no false cause | yes | yes |
| Cost per season at list price | $1.25 | $0.08 (perception only) |

**Matched difference, people fed:** Muse Spark minus scripted is **−8.7** (95% interval −31.8 to +11.2, from resampling the eight farms). Spark was ahead on 3 of 8 farms.

- **Biggest loss:** −75.0 on the compound case.
- **Biggest win:** +41.0 on the heat-wave case.

With eight cases the interval spans zero. **This holdout does not show either scientist farming better.**

## What it shows

- **Both scientists generalised to the new families.**
  - Both found the biased sensor 3 days after it started, with a reference-probe check, and recalibrated it rather than acting on the soil.
  - Both handled the undetectable root disease honestly: they followed the decline, called the cause inconclusive, asked for a review, and treated nothing.
  - Both stayed calm on the control and heat-wave farms.
- **Neither caught a clog on sandy soil.**
  - Two of the seven hidden faults were clogs (h402, and the first fault of h403). On the sand field (F3), watered at 110% of demand, a clog at 59–62% delivery moved root-zone moisture by at most about 0.02 m³/m³. That is around the monitor's minimum effect size (0.015) and sensor noise (±0.008), so no alarm fired before harvest. In h402 under the scripted plan, the clog landed on F6 and was also missed.
  - **This is a detection limit of the simulated sensors and monitor, not a reasoning failure.** A routine emitter-flow test, or an alarm on yield shortfall, would be needed to catch it.
- **Muse Spark made more wrong findings.**
  - **h402:** it wrote a drip-delivery fault of 91.7% into its model for F6. That reading is within normal emitter variation and there was no clog there.
  - **h404:** before the salinity change began, it recorded "unexplained canopy loss" on F1, then set that loss back to zero. Both updates count as findings with no fault behind them.
  - The scripted protocol made one similar finding on F1 of the same farm.
  - Spark had fewer unexplained alarms (2 against 7); all seven of the scripted protocol's were on h404.
- **Harvest differences come mostly from planning, not diagnosis.**
  - On h403 both scientists diagnosed the same fault (the pests) and missed the same clog. Yet Spark's plan fed 75 fewer people.
  - On the heat-wave farm, Spark's plan fed 41 more.

## Losses and unknowns

- One run per scientist and case. Model sampling variation is not measured; repeated Spark runs are the next step.
- Eight cases is a small sample: the people-fed comparison is inconclusive.
- Clogs on sandy, generously watered fields were invisible to both scientists. The suite has no case that tests a clog on loam, where earlier benchmarks show both detect it.
- The scripted baseline was given the same two new moves as Spark (a sensor check, and escalating an unknown cause). The comparison is about using the tools, not about knowing the tools exist.
- The prompt names the new tools and one general rule ("instruments can be wrong; if you can't establish a cause, say so and ask"). It does not list the new fault families.

## Reproduce

```bash
python -m worldlab bench2 --agents spark,scripted-rl --perception meta \
    --holdout docs/bench/holdout/holdout_v1.json --out runs/holdout_v1 --workers 4
python -m worldlab bench2-summary runs/holdout_v1 --out docs/bench/holdout --reference scripted-rl/meta
```

Muse Spark and SAM 3.1 need `MODEL_API_KEY`. A judge can also start an unfamiliar case live: choose **Unknown challenge** in the planner. The server draws one of these families at random and reveals it only after the season.
