# WorldLab Crops

**An AI agronomist that learns a desert farm by experiment, trains its own irrigation policy by reinforcement learning, runs a season to feed as many people as possible, and notices when something in the field goes wrong. Watch it in a 3D web app.**

The farm is 12 hectares near Al Ain in the UAE: six fields with different soils, some already saline, irrigated by drip from brackish groundwater that can be blended with desalinated water. Water and energy are capped. The agent chooses among ten food-security crops: wheat, rice, maize, potatoes, cassava, soybeans, sorghum, millet, common beans and sweet potatoes.

The local varieties don't behave quite like the published values, and the agent isn't told how. To do well it has to:

1. **Run trials.** Design trial plots that expose the traits that matter: a saline plot reveals salt tolerance, a late sowing reveals heat tolerance at flowering.
2. **Calibrate.** Infer each crop's hidden traits from drone imagery and harvests.
3. **Plan for a bad year.** Choose which crop goes on which field, with sowing date, irrigation, water blend and nitrogen, to maximise the people fed in a bad year. Someone counts as fed only when calories, protein *and* vitamin A are all covered.
4. **Learn a policy.** Train a daily irrigation and water-blend policy by reinforcement learning inside its own calibrated model of the farm, and use it only if it beats the fixed rule on held-out imagined seasons.
5. **Run the season and stay honest.** Run the season day by day against its own predictions. When a field drifts out of the predicted band, it forms hypotheses, runs the field test that tells them apart, fixes the cause, corrects its model and re-plans its water.

Every hypothesis, prediction, trial, test, decision and result is written to a hash-chained ledger and shown live in the web app: a stylized low-poly 3D farm where plants grow with the simulation, soil darkens when wet and crusts white with salt, water glows through the drip lines (red when clogged), a drone flies out to inspect, and an alarm ring marks the field whose measurements left the model's predicted band.

![WorldLab web app: the scientist's notebook, field charts and RL policy panel at the end of a season](docs/app.png)

*Panels at the end of the recorded run in `docs/app` (the 3D farm fills the middle of the screen). Violet is what the agent's model predicts; orange is what the sensors and drone measure. On 4 January a drip line in field F4 clogs. The agent isn't told, and the water meter can't see it. Soil salinity rises out of the predicted band, because less water reaching the roots leaches less salt, and the alarm fires. A water test is normal; an emitter flow test reads 45% of design flow, so the agent concludes the line is clogged. It repairs it, teaches its model what happened and re-plans irrigation. Before sowing it had trained an RL irrigation policy that, in its own model, keeps the farm inside the water quota in every imagined year (the fixed rule overran in 18%) for 1% fewer people fed. The harvest feeds 458 people within the water and energy limits.*

**No server needed to watch a run:** `docs/app/` is a static copy of the web app that replays a recorded run. Serve the folder from any static host (GitHub Pages works), or run `python -m http.server -d docs/app` and open http://localhost:8000.

Built for the Meta Global AI Developer Hackathon, theme **Push the Frontier** (agriculture, food security).

---

## How Meta's models are used

| Model | Role |
|---|---|
| **Muse Spark** (`muse-spark-1.3`, Meta Model API) | The scientist. It drives everything through **tool calling**: it records hypotheses, designs trials, decides when beliefs are good enough to plan, chooses which field test to run, interprets results, acts and concludes. Every call carries a written rationale that lands in the ledger. |
| **SAM 3.1** (`sam-3.1`, Meta Model API) | Reads drone images. It counts plants (stand loss), finds white salt crust and spots brown leaf damage by noun phrase. |
| **Muse Spark** vision + **structured output** | Gives a stress diagnosis for each drone image (healthy, water stress, pest damage, salt damage, sparse stand) with evidence. |
| **Muse Glimmer** (open weights, Apache 2.0) | A drop-in scientist running on your own GPU or any OpenAI-compatible host. It gets the same tools and prompt, so the two can be benchmarked head to head. |

The language model never acts on the farm directly. It decides, numerical code does the agronomy, and budgets bound every action: trial plots, field tests, the groundwater quota and the energy budget.

## The science inside

- **Crop and soil model.** An AquaCrop-style daily model, vectorised over tens of thousands of field-seasons at once (40,000 seasons in about 3 s):
  - growing-degree-day phenology,
  - logistic canopy growth and senescence,
  - normalised water productivity,
  - harvest index cut by heat and drought during flowering,
  - a three-layer soil (0–20, 20–50, 50–100 cm) with water, salt and nitrogen,
  - leaching, deep percolation, soil evaporation (halved by mulch),
  - Maas–Hoffman salinity response, stand loss.
- **Weather.** FAO-56 Penman–Monteith reference evapotranspiration from a stochastic Al Ain climate, with spring heat waves and sparse winter rain.
- **Learning the varieties.** Each crop has four hidden traits (water productivity, canopy growth rate, heat tolerance at flowering, salt tolerance). Trials update them by MAP fitting to weekly drone canopy cover and harvest weight, with a Laplace posterior. A trait only narrows if a plot exposed it, and the belief chart on the dashboard shows exactly that.
- **Trial design.** Each candidate plot is scored by expected information (linearised Fisher information) and by how much it would shrink the uncertainty in that crop's yield *where the plan would actually grow it*.
- **Robust planning.**
  - Every field × crop × management option is simulated under paired samples of trait beliefs and weather years.
  - A coordinate-ascent search maximises the 10th percentile of people fed, subject to the 90th-percentile groundwater use and energy staying within budget.
  - The plan reports the **cost of uncertainty**: how many more people it would feed if the traits were known. Trials visibly shrink it, from 71 to 17 people on the default farm.
- **Reinforcement learning, inside the agent's own model.** Before sowing, the agent can train a daily irrigation policy (`train_irrigation_policy`):
  - A small neural network (17 sensor features → 16 hidden units → 2 actions, 322 parameters) reads only what the farm's sensors show: crop stage, drone canopy cover, soil moisture and salinity in the top 50 cm, yesterday's ET₀, water and energy used so far against the quota, and the crop's published characteristics. Each day it scales the plan's drip schedule (0.55× to 1.8×) and shifts the desalinated-water share.
  - Training is **model-based**: every episode is a whole imagined farm season whose crop traits are drawn from the agent's calibrated beliefs and whose weather is drawn from the climate. The real farm stays hidden (domain randomisation over the posterior).
  - The optimiser is **evolution strategies** (antithetic sampling, centred ranks, Adam): 32 perturbation pairs per iteration, 50 iterations, about 40,000 imagined farm seasons in about a minute on two CPU cores, vectorised through the same crop model.
  - Reward per season: people fed (the scarcest nutrient across all fields), minus steep penalties for exceeding the water quota or energy budget, plus a small credit for what is left unused.
  - The untrained network outputs exactly the plan's fixed rule, and the best checkpoint is chosen on held-out imagined seasons, so the result is never worse than the rule there. The agent compares rule and policy on 40 more held-out seasons and decides whether to deploy it. If a later diagnosis puts the farm outside what the policy was trained on (for example, much saltier groundwater), it hands irrigation back to the rule.
- **In-season monitoring.** An ensemble of the model runs alongside the farm, fed the actual weather and the actual irrigation. Two-sided CUSUM on soil moisture, soil salinity and drone canopy cover flags sustained divergences that are large enough to matter.
- **Diagnosis and repair.**
  - Field tests separate competing causes: emitter flow, soil sample, water test, leaf inspection.
  - The agent fixes the cause: it repairs the drip line, sprays, or blends in more desalinated water.
  - It tells the model what happened: the delivered fraction, the pest damage rate or the new groundwater salinity, from the onset day. Then it re-optimises irrigation for the rest of the season within the remaining quota.
- **Auditable.** The ledger is append-only and SHA-256 hash-chained, and `python -m worldlab verify` detects any edit. Each trial result stores a digest of its raw data.

## Which variables are modelled

Built from a checklist of variables for crop simulation:

| Group | Modelled | Simplified | Not modelled (yet) |
|---|---|---|---|
| **Climate** | daily max/min temperature, humidity, rain, solar radiation, wind, ET₀ (Penman–Monteith), heat waves and their duration, year-to-year variability, a 7-day forecast | VPD (inside ET₀), CO₂ (current level, in the normalised water productivity), day length (computed; no photoperiod response) | soil temperature, frost (rare in the UAE) |
| **Soil** | texture per layer, 1 m depth in 3 layers, field capacity, wilting point, initial moisture, salinity (ECe) per layer with leaching, nitrogen | drainage rate standing in for hydraulic conductivity | bulk density, pH, organic matter, P, K, micronutrients, CEC, water table, erosion |
| **Water** | quota, daily drip amount, application efficiency (hidden per field), water salinity (brackish/desal blend), deep percolation, pumping and desalination energy | drip only | other irrigation methods, runoff, capillary rise, storage, rainwater harvesting, water temperature |
| **Crop** | 10 crops, base/upper temperatures, growing degree days, growth stages, canopy cover (for LAI), root depth and growth, water productivity, harvest index, water/heat/salt stress sensitivity, nitrogen need, planting density, cycle length | germination (an emergence threshold) | photoperiod, vernalisation |
| **Practices** | sowing date, irrigation level, water blend, nitrogen, mulch, density, pest control, harvest at maturity | | seed quality, planting depth, tillage, rotation, cover crops, pruning |
| **Biology** | pest outbreaks and control, stand loss | | diseases, weeds, pollination, soil pathogens, resistance |
| **Infrastructure** | drip system faults, energy budget, reverse-osmosis desalination, sensor-driven irrigation control (fixed rule or learned RL policy) | | greenhouses, hydroponics, vertical farms, capital cost |

Crop and nutrition values are approximate published figures (AquaCrop-style parameters; USDA FoodData Central nutrition). This is a demonstration of method, not agronomic advice.

---

## Quick start

Needs Python 3.10+ with `numpy` and `scipy` (Anaconda has both). No other packages are required.

```bash
git clone https://github.com/MoAmrYehia/WorldLab.git
cd WorldLab
python -m worldlab serve --open
```

Open http://127.0.0.1:8765, choose an agent, and press **Start run**. Drag to orbit the farm, scroll to zoom, and click a plot to see its charts. Once the season starts:

1. Select a field.
2. Choose **Change the farm** to clog its drip line, release pests, make the groundwater saltier or send a heat wave.
3. Watch the agent notice, investigate and recover.

The dock at the bottom opens the trial plots, beliefs, season plan, RL policy and audit ledger. The previous 2D dashboard is still at `/classic.html`.

The 3D view loads three.js from cdn.jsdelivr.net, so the browser needs internet access; the panels work without it. Without an API key, the agent falls back to the **scripted scientist with RL** and drone perception to a labelled **simulated perception**. Everything else is identical.

### Deploy to Hugging Face Spaces

The repository includes a `Dockerfile` that serves the app on port 7860.

1. Create a Space with the **Docker** SDK.
2. Push this repository to it, replacing the Space's `README.md` with `deploy/huggingface/README.md` (the Space card).
3. Optionally add `MODEL_API_KEY` as a Space secret so Muse Spark runs the farm.

Everyone who opens the Space watches and controls the same run.

### Record a replay

```bash
python -m worldlab run --agent scripted-rl --seed 7 --perturb clog@95 --perception sim
python -m worldlab export-replay runs/<run> --out worldlab/dashboard/replay.json --note "What this run shows"
python scripts/build_artifact.py docs/app                  # refresh the static copy
```

### Muse Spark (Meta Model API)

```bash
export MODEL_API_KEY=...                 # Windows PowerShell: $env:MODEL_API_KEY="..."
python -m worldlab serve --agent spark --open
```

Optional settings: `WORLDLAB_SPARK_MODEL` (default `muse-spark-1.3`) and `WORLDLAB_REASONING` (default `medium`).

### Muse Glimmer (open weights)

Serve Glimmer behind any OpenAI-compatible endpoint and point WorldLab at it:

```bash
llama serve -hf meta-models/Muse-Glimmer-30B-GGUF --hf-file Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf \
  -a muse-glimmer -ngl 99 -c 131072 -np 1 --host 127.0.0.1 --port 8080 --api-key local
export WORLDLAB_GLIMMER_BASE_URL=http://127.0.0.1:8080/v1 WORLDLAB_GLIMMER_API_KEY=local
python -m worldlab serve --agent glimmer --open
```

Other options:

- **Ollama:** run `ollama run muse-glimmer`, then use `http://localhost:11434/v1`.
- **vLLM:** use `--served-model-name muse-glimmer --enable-auto-tool-choice --tool-call-parser muse_glimmer`.
- **A hosted endpoint** (Fireworks, Baseten, Modal): set `WORLDLAB_GLIMMER_BASE_URL`, `WORLDLAB_GLIMMER_API_KEY` and `WORLDLAB_GLIMMER_MODEL`.

### Headless runs, benchmark, tests

```bash
python -m worldlab run --agent spark --perturb clog@90:F2         # one run, printed as it goes (day 0 = 1 Oct)
python -m worldlab bench --farms 5                                 # scripted agents across random farms
python -m worldlab bench --farms 3 --agents spark,glimmer,scripted # compare the LLM scientists
python -m worldlab verify runs/<run>/ledger.jsonl                  # check the audit chain
python -m unittest discover -s tests -v                            # tests, no network needed
```

Each run writes `runs/<time>-<agent>/` containing `ledger.jsonl` (hash-chained) and `images/` (the drone images the agent looked at).

---

## Benchmark

Each farm has its own hidden variety traits, drip efficiencies and weather year. The agent sees only sensors, drone images, harvests and test results, exactly as on a real farm. That makes it possible to score it against ground truth.

On day 90 (early January), each scenario hides one change:

- **none:** nothing changes.
- **clog:** a drip line clogs to 45% delivery.
- **pest:** an outbreak eats 3% of the canopy a day.
- **salinity:** the groundwater turns from 4.5 to 9 dS/m.
- **heatwave:** a heat wave arrives, and it is in the forecast, so it should not cause an alarm.

Results across 5 random farms × 5 scenarios × 3 agents (`python -m worldlab bench --farms 5`; raw runs in `docs/bench/runs.json`). The oracle plans with the true traits and suffers no faults.

| agent | scenario | runs | people_fed | pct_of_oracle | detected | detect_days_median | diagnosis_ok | false_alarms | within_limits | trait_error |
|---|---|---|---|---|---|---|---|---|---|---|
| scripted | none | 5 | 439.1 | 99.7 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted | clog | 5 | 429.1 | 97.2 | 5/5 | 20.0 | 5/5 | 0 | 5/5 | 0.4 |
| scripted | pest | 5 | 436.9 | 98.9 | 5/5 | 13.0 | 5/5 | 0 | 5/5 | 0.4 |
| scripted | salinity | 5 | 383.6 | 86.5 | 5/5 | 14.0 | 5/5 | 0 | 4/5 | 0.4 |
| scripted | heatwave | 5 | 419.2 | 95.2 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted-noadapt | none | 5 | 439.1 | 99.7 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted-noadapt | clog | 5 | 421.4 | 95.5 | 5/5 | 20.0 | 0/5 | 0 | 4/5 | 0.4 |
| scripted-noadapt | pest | 5 | 419.7 | 95.2 | 5/5 | 13.0 | 0/5 | 0 | 5/5 | 0.4 |
| scripted-noadapt | salinity | 5 | 370.8 | 83.4 | 5/5 | 14.0 | 0/5 | 0 | 4/5 | 0.4 |
| scripted-noadapt | heatwave | 5 | 419.2 | 95.2 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted-notrials | none | 5 | 384.2 | 88.1 | – | – | 5/5 | 1 | 4/5 | 0.9 |
| scripted-notrials | clog | 5 | 358.2 | 82.7 | 5/5 | 16.0 | 0/5 | 0 | 3/5 | 0.9 |
| scripted-notrials | pest | 5 | 379.8 | 87.4 | 5/5 | 17.0 | 5/5 | 0 | 4/5 | 0.9 |
| scripted-notrials | salinity | 5 | 343.7 | 78.5 | 5/5 | 14.0 | 5/5 | 0 | 4/5 | 0.9 |
| scripted-notrials | heatwave | 5 | 374.1 | 85.9 | – | – | 5/5 | 0 | 4/5 | 0.9 |

The three agents:

- **scripted:** the full protocol: trials, calibration, planning, monitoring, diagnosis and repair.
- **scripted-noadapt:** the same, but it ignores alarms.
- **scripted-notrials:** plans on published values and never experiments.

What the numbers say:

- **Experimenting pays.** With trials, the harvest reaches 99.7% of the oracle; without them, 88.1%. That is about 55 more people fed for a year from the same land and water. Trait error halves (0.4 against 0.9 prior standard deviations).
- **Every hidden fault was detected**, at a median of 13–20 days, with no false alarms during the season. The cause was named correctly in every case:
  - a clogged line, by emitter flow test,
  - pests, by leaf inspection,
  - saltier groundwater, by water test.
- **Acting on the diagnosis helps**: 429 vs 421 people with a clog, 437 vs 420 with pests, 384 vs 371 with salty groundwater.
- **A forecast heat wave** raises no alarm. It is already in the forecast, so the model accounts for it.
- **Water and energy limits held in 4 of 5 farms.** On farm 204 the actual year was drier than the planner's 90th-percentile assumption, and use overran by up to 2%. A hard quota cut-off is a natural next step.

An earlier version of this benchmark caught a real gap. A clogged line first shows up as *rising soil salinity* (less water means less leaching), not as dry soil. The scripted agent only tested the groundwater, so it never found the clog. It now tests both causes, and clog diagnosis went from 2/5 to 5/5.

These are scripted-agent numbers. The same harness runs Muse Spark and Muse Glimmer (`--agents spark,glimmer,scripted`) once an API key or endpoint is set.


---

## Layout

```
worldlab/
  farm/weather.py    Al Ain weather generator, FAO-56 Penman-Monteith ET0
  farm/crops.py      the ten crops: growth parameters, nutrition, hidden-trait priors
  farm/sim.py        vectorised daily crop + 3-layer soil model (water, salt, nitrogen)
  farm/world.py      the hidden farm: true traits, sensors, drone imagery, field tests, faults
  farm/belief.py     trait beliefs, MAP calibration from trials, trial information
  farm/optimize.py   robust crop-mix planner (bad-year people fed under water and energy limits)
  lab.py             the agent's tools: trials, planning, season execution, monitoring, tests, repairs
  agent.py           Muse Spark / Muse Glimmer tool-calling scientist, and the scripted baseline
  perception.py      SAM 3.1 + Muse Spark drone analysis, and simulated perception
  llm.py             stdlib client for Meta Model API and OpenAI-compatible endpoints
  ledger.py          hash-chained audit ledger and verifier
  bench.py           ground-truth benchmark across random farms and scenarios
  farm/rl.py         reinforcement learning: evolution-strategies irrigation policy trained in the belief model
  server.py          web app server (standard library, server-sent events)
  replay.py          turns a recorded run into a static replay
  dashboard/         3D web app (index.html, app.js, scene.js, style.css), replay.json, classic 2D dashboard
docs/app/            static copy of the web app that plays a recorded run without a server
Dockerfile           Hugging Face Spaces / container deployment
tests/               unit tests, including the agent loop against a mock OpenAI-compatible endpoint
```

## License

MIT. See [LICENSE](LICENSE).
