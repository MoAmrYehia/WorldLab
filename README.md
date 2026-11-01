<p align="center"><img src="docs/screens/banner.jpg" alt="WorldLab: Green Frontier. Grow the future. Outsmart the desert." width="100%"></p>

# WorldLab: Green Frontier

*Grow the future. Outsmart the desert.*

**An AI scientist that runs a desert farm in 3D. You choose the crops; it plants trial plots, learns how the crops really behave, trains its own irrigation policy, and finds and fixes what goes wrong in the field. Every decision is on the record.**

**[Open the website](https://moamryehia.github.io/WorldLab/)** · **[Watch a recorded season](https://moamryehia.github.io/WorldLab/app/?demo)** (no account needed) · Built for the Meta Global AI Developer Hackathon, theme *Push the Frontier*

| | |
|---|---|
| ![The landing page: a 3D flyover of the farm at golden hour](docs/screens/landing.jpg) | ![Six crop fields, palms, tanks, the greenhouse and trial plots in 3D](docs/screens/fields.jpg) |
| **Landing page.** A live 3D flyover of the farm, replaying a recorded season. | **The farm.** Six fields, ten crops that grow with the simulation, trial plots, and the infrastructure that waters them. |
| ![Incident close-up: a clogged drip line in red, an alarm ring and the drone scanning](docs/screens/incident.jpg) | ![Salinity overlay with readings in dS/m on each field](docs/screens/overlay.jpg) |
| **An incident.** Salinity in F4 leaves the model's band; the camera flies in, the drone scans, the investigation panel lists hypotheses, tests and the repair. | **Scientific overlays.** Crop health, soil moisture, salinity and irrigation, with units, from the latest sensor readings. |
| ![The Agent tab: the agent loop and every tool call with its reason and result](docs/screens/agent.jpg) | ![The farm at night with lamps and field lights](docs/screens/night.jpg) |
| **The agent.** Its observe, hypothesize, experiment, decide, act, learn loop and every tool call with its reason, result and engine. | **Time of day.** Morning, noon, golden hour and night, with lights that switch on after dark. |

## What you can do

- **Plan a season.** Pick crops for six fields across three sowing seasons. Each crop card shows a picture rendered from its 3D model, the sowing window, days to harvest, the needs it covers, its salt limit and the expected yield on every field; your picks appear as 3D previews in the fields.
- **Watch the AI scientist work.** Five chapters (Discover, Strategize, Survive, Recover, Harvest) with objectives that tick off only when the audit ledger shows they happened.
- **Follow the agent.** The Agent tab shows each tool call it makes and why, and a table of every AI component and whether it is active.
- **See through the drone.** The Drone feed shows the drone's live camera in the 3D farm beside the frames it captures on survey and inspection flights.
- **Investigate incidents.** When measurements leave the model's predicted band, the season pauses and the investigation panel shows the competing hypotheses, the evidence and the fix.
- **Choose a scenario and edit the farm.** Seven scenarios from a baseline season to a compound one (drip fault, pest outbreak, heat at flowering, water scarcity, saline start), plus the farm seed, water quota, energy budget and starting salinity, all validated by the server.
- **Make the decisions yourself.** In human decision mode the season pauses at each alarm so you choose the first test, and the scientist asks before every repair or pest control. Your choices and the scientist's own choice are both in the ledger.
- **Run controlled experiments.** Rerun any finished season with one change (irrigation controller, hidden events, a field's crop, the farm seed or who decides) and compare the two side by side, or start the next season on the soil the last one left.
- **Read the weather.** Observed temperature, ET₀ and rain, the latest 7-day forecast and the heat limits of crops now flowering.
- **Price the season yourself.** Enter your own electricity, fertiliser and other prices and a grid emission factor; WorldLab turns the season's actual quantities into a cost and emissions per person fed. No prices are shipped.
- **Share a report.** Download a self-contained HTML report, or publish a read-only link to a season (only seasons you choose to share are public).
- **Earn achievements.** First Sprout, Water Steward, Scientific Detective, Resilience Architect, Harvest Guardian, Adaptive Intelligence and Diverse Farm, each backed by ledger evidence. With an account, progress is saved and rewards can't be farmed by replaying.

## The challenge

The farm is 12 hectares near Al Ain in the UAE: six fields with different soils, some already saline, irrigated by drip from brackish groundwater that can be blended with desalinated water. Water and energy are capped. The agent chooses among ten food-security crops: wheat, rice, maize, potatoes, cassava, soybeans, sorghum, millet, common beans and sweet potatoes.

The local varieties don't behave quite like the published values, and the agent isn't told how. To do well it has to:

1. **Run trials.** Design trial plots that expose the traits that matter: a saline plot reveals salt tolerance, a late sowing reveals heat tolerance at flowering.
2. **Calibrate.** Infer each crop's hidden traits from drone imagery and harvests.
3. **Plan for a bad year.** Choose which crop goes on which field, with sowing date, irrigation, water blend and nitrogen, to maximise the people fed in a bad year. Someone counts as fed only when calories, protein *and* vitamin A are all covered.
4. **Learn a policy.** Train a daily irrigation and water-blend policy by reinforcement learning inside its own calibrated model of the farm, and use it only if it beats the fixed rule on held-out imagined seasons.
5. **Run the season and stay honest.** Run the season day by day against its own predictions. When a field drifts out of the predicted band, it forms hypotheses, runs the field test that tells them apart, fixes the cause, corrects its model and re-plans its water.

Every hypothesis, prediction, trial, test, decision and result is written to a hash-chained ledger and shown live in the web app: a dark command-centre interface over an interactive 3D farm at golden hour. Everything in the 3D world is real geometry driven by the simulation, not a picture: ten botanically distinct crops that grow through their stages, wilt under water stress, pale under salt and heat, show pest damage and sway with the measured wind; soil that darkens around wet emitters and crusts with salt; drip lines that turn red when clogged; dust, clouds and rain driven by the weather record; a drone that flies out to scan a field; a service truck that drives out to repair a line; an alarm ring on the field whose measurements left the model's predicted band. Orbit, zoom and pan, click a field to inspect it, or switch to scientific overlays of crop health, soil moisture, salinity and irrigation (with units).


**The recorded season** (the demo on the website): Muse Spark (`muse-spark-1.3`, Meta Model API) is the scientist, and SAM 3.1 and Muse Spark vision read the drone photos; hard water and energy budget, farm 7. Before sowing it writes a hypothesis that the local varieties match the published values, plants 12 trial plots and refutes it: local sorghum collapses in the spring heat (1.08 t/ha against 6.44 predicted), so it drops sorghum, re-plans and trains an irrigation policy by reinforcement learning (322 parameters, 39,000 imagined seasons in 52 s; +13.7% people fed in a bad year on held-out imagined seasons), which it deploys. On 4 January a drip line in field F4 is silently clogged; the water meter can't see it and the scientist isn't told. On the measurement of 24 January the soil is drier than its model's 90% band. Muse Spark sends the drone: compared with the view its own model expects, the photo shows white salt crust between the rows (SAM 3.1 segments 13 patches). It writes two competing hypotheses, a clogged line or saltier groundwater, runs both tests (emitter flow 46% of design; groundwater 4.35 dS/m against an assumed 4.5), supports the first and refutes the second, repairs the line, teaches its model the delivered fraction since the onset, switches irrigation back to the rule (the policy was trained on a fault-free farm) and re-plans the water. The harvest feeds 506 people (modelled person-years, above the farm goal of 500), using 57,650 m³ of a 60,000 m³ groundwater quota and 87,888 kWh of a 90,000 kWh energy budget. The whole season took 34 Muse Spark calls and 54 perception calls, under a dollar of API credit.

**Check the recorded season yourself, offline.** The replay omits some large entries, so its complete raw ledger is published separately as an evidence bundle: [`worldlab-evidence.zip`](https://moamryehia.github.io/WorldLab/app/evidence/worldlab-evidence.zip) (also in `worldlab/dashboard/evidence/`, and linked from Agent › Audit ledger). It holds the ledger (124 entries, gzipped), a manifest (source commit, prompt and tool-schema hashes, model IDs, farm seed and hidden event, perception mode, timestamps, completion status, token usage, file hashes and the final ledger hash `bebff05dda831edf…`) and a verifier that needs only Python's standard library:

```bash
unzip worldlab-evidence.zip && cd worldlab-evidence && python verify_evidence.py .
# VERIFIED ok: 124 entries, chain intact, final hash bebff05dda831edf… matches the manifest
```

Editing, removing or reordering any entry, or cutting entries off the end, makes it fail (tests in `EvidenceBundleTests`). The hash chain proves the ledger wasn't changed after it was written; it does not by itself prove a model was called or that the agronomy is right.

![The drone analysis in the recorded season: the view F4's model expects, the drone photo with salt crust, and SAM 3.1's plant boxes on F6](docs/screens/drone.jpg)



### The website

| Page | What it does |
|---|---|
| `/` | Landing page: a cinematic 3D flyover of the farm replaying a season, numbers from that season, how a season runs, the sowing calendar, benchmark results |
| `/signup`, `/login` | Accounts. Each account gets its own farm, its own runs and a history of past seasons |
| `/app` | Your farm. **Plan a new season** opens the season planner with 3D previews of your crops; missions, field gauges, the incident investigation, the research lab and the results screen follow the run live |
| `/demo` | A recorded season, no account needed |

**Choosing crops by season.** The growing year runs from 1 October to 30 June; open fields rest through the summer. The planner has three sowing seasons:

| Season | Sowing dates | Crops that can be sown |
|---|---|---|
| Autumn sowing | 1 Oct to 15 Nov | maize, cassava, sweet potatoes, potatoes, common beans, wheat |
| Winter sowing | 16 Nov to 31 Dec | wheat, potatoes, common beans |
| Late-winter sowing | 25 Jan to 15 Mar | rice, soybeans, sorghum, millet |

For each of the six fields you pick a season and a crop, leave it fallow, or let the scientist decide. Each crop card shows its sowing window, days to harvest, the needs it covers (calories, protein, vitamin A), its salt limit, and the yield the crop model expects on every field. The scientist still runs trial plots, then plans sowing day, irrigation, water blend and nitrogen for your crops and chooses crops for the fields you left open. It also reports how many people its own free choice would feed, so you can see what your picks cost or gain.

**Missions and progression.** Each objective is required (decides the chapter), optional (a choice such as picking your own crops or training a policy, which never blocks progress), a stretch goal (feeding 500 people) or not applicable (Recover in a fault-free season). A season that reaches harvest is complete even if a stretch goal is missed, and the outcome says so. A season runs through five chapters: Discover (trial plots), Strategize (plan within the water and energy limits), Survive (run the season), Recover (detect, diagnose and repair hidden faults) and Harvest. Objectives, achievements and experience are computed from the run's audit ledger by `worldlab/progression.py`, the same code for live seasons and recorded replays, so nothing is awarded that the ledger doesn't show. Achievements: First Sprout, Diverse Farm, Adaptive Intelligence, Scientific Detective, Resilience Architect, Water Steward and Harvest Guardian. Progress is saved per account; season experience counts once per farm and crop choice, replays earn nothing, and beating your best on the same scenario earns only the difference.

**Navigation.** Six destinations, in the top bar on desktop and a bottom bar on tablets and phones, each with its own address (`#plan`, `#research/trials`, `#incidents`, `#agent/ledger`, `#results`) so Back works and views can be linked: **Farm** (3D or 2D view, field gauges, inspector), **Plan** (season plan and plan history, crop planner), **Research** (trial plots, crop traits with units, irrigation policy and its deployment criterion), **Incidents** (every investigation from divergence to observed recovery), **Agent** (decision record, AI components with their state, searchable audit ledger) and **Results** (harvest report with exports, your seasons). A run header always shows recorded or live, who decides, what reads the drone images and what controls irrigation; the transport bar plays, pauses, steps between events and scrubs by season date. Without WebGL the farm appears as an interactive 2D field map.

**Controls and performance.** Drag to orbit, scroll or pinch to zoom, right-drag to pan, arrow keys to move. Keys: `1`–`6` fly to a field, `O` overview, `D` follow the drone, `I` close-up, `R` reset, `V` cycle overlays, space play or pause a replay, `Esc` close a panel. Settings offer Low, Medium, High and Ultra quality or automatic (it steps down when the measured frame rate drops), time of day (morning, noon, golden hour, night) and 3D labels; the measured frame rate is shown there. Crops and palms are instanced, geometry is shared and disposed on quality changes, and reduced-motion settings stop the camera flights. Camera flights to events can be turned off in settings. Without WebGL the farm is drawn as a 2D map with the same selection, overlays and alarms.

**Experiments and seasons over time.** *Compare* in Results types every comparison and shows its configuration diff, what the scientist did differently, what can be inferred, and the run IDs and ledger hashes (`experiments.json`, built by `scripts/build_experiments.py`):

| comparison | type | result (person-years) |
|---|---|---|
| Effect of the hidden clog, scripted scientist | single factor: identical ledgers until 4 January, verified | 492.0 without the clog, 485.1 with it: the clog's total effect including the response is 6.9 on this farm |
| Investigating alarms, scripted scientist, fixed rule | single factor: identical ledgers until the alarm, verified | 464.9 investigating, 457.3 ignoring alarms |
| Muse Spark against the scripted scientist | system comparison: scientist, perception and irrigation learning all differ | 506.4 against 485.1 on this farm; not a general result (see the benchmark) |
| Muse Spark with and without the hidden fault | illustrative: one input differs, but Muse Spark's choices vary between runs | 506.4 with, 535.5 without; one run each |
| A second season on the soil the first left | system comparison: starting soil and the hidden fault both differ | 475.2 in season 2 |

All are single farms and single weather years. Exact mid-season checkpoints aren't stored, so pairs are full reruns from 1 October; with the deterministic scripted scientist the reruns are verified identical until the treatment takes effect, which makes them exact branches. With an account, any finished season can be rerun with one change and compared with its parent. Salt carries over between seasons: the simulated soil state at the end of season 1 is exactly the state season 2 starts from (the sensor reading of it differs by measurement noise); soil water and nitrogen start fresh.

**Accounts** are stored in SQLite (`WORLDLAB_DATA`, default `./data`). Passwords are hashed with scrypt and a per-user salt; sessions are random tokens in an HttpOnly cookie, stored only as SHA-256 digests; cross-site POSTs are refused and repeated failed logins are throttled.

**Hosting: GitHub Pages for the website, Hugging Face for the server.** `docs/` is a static copy of the whole site (landing page, log in, sign up, and the farm app in `docs/app/`). GitHub Pages serves it; accounts, crop planning and live seasons call the Python server, which runs on a Hugging Face Space. The address of that server is set in `docs/config.js`. If the server can't be reached, the Pages site still shows the landing page and a recorded season. See [Deploy](#deploy-github-pages--hugging-face) below.

Built for the Meta Global AI Developer Hackathon, theme **Push the Frontier** (agriculture, food security).

---

## How Meta's models are used

| Model | Role |
|---|---|
| **Muse Spark** (`muse-spark-1.3`, Meta Model API) | The scientist. It drives everything through **tool calling**: it records hypotheses, designs trials, decides when beliefs are good enough to plan, chooses which field test to run, interprets results, acts and concludes. Every call carries a written rationale that lands in the ledger. |
| **SAM 3.1** (`sam-3.1`, Meta Model API) | Reads the drone photos. It counts plants by segmenting "plant" on 16 overlapping tiles of each frame (a plant counts once, in the tile that holds its centre) and segments white salt crust ("white patch") on the whole frame. Each count is scored afterwards against what the frame really shows: in testing it counted 120 of 120, 165 of 167 and 158 of 159 separate plants; a closed maize canopy is undercounted. |
| **Muse Spark** vision + **structured output** | Compares the drone photo with a view rendered from the scientist's own model (same plant positions, the predicted canopy, no faults) and returns a structured diagnosis with evidence: healthy, water stress, pest damage, salt damage or a sparse stand. Given only the photo it confused narrow maize leaves with drought; with the expected view it got 12 of 12 test frames right. |
| **Muse Glimmer** (open weights, Apache 2.0) | A drop-in scientist running on your own GPU or any OpenAI-compatible host. It gets the same tools and prompt, so the two can be benchmarked head to head. |

The language model never acts on the farm directly. It decides, numerical code does the agronomy, and budgets bound every action: trial plots, field tests, the groundwater quota and the energy budget.

## All the AI components

WorldLab is an agent. Its loop: **observe** the farm, write a testable **hypothesis**, run the **experiment** that tells explanations apart, **decide**, **act** through bounded tools, and **learn** by correcting its own model. The app's **Agent** tab shows that loop and every tool call with its reason, result and the engine that ran it; the same tab lists the components below with whether each is active in the season on screen.

| Component | Kind | What it does | How it works | In the recorded demo |
|---|---|---|---|---|
| Muse Spark | Meta model | The scientist: chooses every next step | Function calling over 19 tools (`worldlab/agent.py`) | Decides the recorded season |
| Muse Glimmer | Meta open weights | The same scientist on your own GPU | Any OpenAI-compatible endpoint, same tools and prompt | Not used |
| SAM 3.1 | Meta model | Reads drone photos | Counts plants tile by tile and segments salt crust by text prompt (`perception.py`); scored against what each frame shows | Found the salt crust in F4; counted 175 of 176 plants in F6 |
| Muse Spark vision | Meta model | Compares the photo with what the model expects | Two images in, structured diagnosis with evidence out | Saw the salt crust the model didn't expect |
| Scripted protocol | Rules | Baseline and fallback scientist | A fixed sequence over the same tools | Compared with Muse Spark in Results |
| Experiment design | Numerical | Picks the trial plots worth planting | Expected information about the traits that move the plan (`farm/belief.py`) | Used |
| Bayesian calibration | Numerical | Learns each crop's hidden traits | MAP fit of four traits per crop from trials and drone canopy (`farm/belief.py`) | Used |
| Digital twin | Numerical | Predicts every field with uncertainty | Ensemble of the crop and soil model run beside the farm (`farm/sim.py`) | Used |
| Anomaly detector | Numerical | Notices when reality leaves the prediction | CUSUM on measured minus predicted moisture, salinity and canopy (`lab.py`) | Caught the F4 clog |
| Robust planner | Numerical | Plans crops, sowing, irrigation, blend and nitrogen | Maximises people fed in a bad year within the limits (`farm/optimize.py`) | Used |
| Reinforcement learning | Numerical | Learns a daily irrigation policy | Evolution strategies inside the agent's model; deployed only if it beats the rule (`farm/rl.py`) | Deployed |
| Audit ledger | Integrity | Makes every step checkable | Hash-chained log; missions and achievements are scored from it (`ledger.py`, `progression.py`) | Used |

**Drone photos.** The drone frames are photorealistic top-down images drawn from the simulator's true state: textured soil and raised beds, wet soil around working emitters (a clogged line shows dry emitters), crops with their own leaf shapes and shadows, leaves that roll and fire under drought, white salt efflorescence on dry ridges and at the edge of the wetted zone, brown lesions and holes from pests. The renderer also records what it drew, so the image models can be scored; the scientist never sees that record. In the field inspector, click a drone photo to enlarge it and switch between the photo, the view the model expected and SAM 3.1's segments. **Drone feed.** The Drone feed tab shows two things side by side and labels them: the drone's live camera in the 3D farm, and the frames the drone captures. Survey frames are taken every 12 days from the farm simulator's true state (the canopy figure beside each is the drone's noisy measurement); inspection frames are the images the scientist asked for, with the image analysis that went into its decision.

**Crop pictures.** Every crop name in the planner, the field gauges, the inspector and the results comes with a picture rendered from the same 3D model that grows in the field, at the growth stage the field is in.

## The science inside

- **Resource limits.** Planning and execution are separate. The planner keeps the 90th-percentile water and energy use of its plan within the quota and budget (a probabilistic constraint). Execution enforces hard limits: each day, before the farm advances, the controller's proposed irrigation is cut back so the day's water and energy fit what remains (`cap_to_budget` in `farm/sim.py`). When demand exceeds what remains every field is scaled by the same factor; the first curtailment is written to the ledger and the curtailed volume is reported, so any yield loss that follows is counted. The same rule applies to the fixed rule and the RL policy, and to the imagined seasons the policy is trained and compared in. Desalinated water is made from the same brackish groundwater by reverse osmosis, so every applied cubic metre counts against the groundwater quota; RO recovery losses are not modelled. Runs record their `budget_mode`; benchmark results recorded before this change are labelled as soft-budget.

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

## Built during the hackathon

Everything in this repository was written during the Meta Global AI Developer Hackathon build period (first commit 29 October 2026): the farm and crop simulator, the scientist's tools and protocol, the Muse Spark, SAM 3.1 and Muse Glimmer integrations, the experiment design, calibration, planning and reinforcement-learning code, the photoreal drone renderer, the audit ledger, the server and accounts, the 3D web app and the website. The commit history shows the order it was built in. Third-party code is used only as libraries: NumPy, SciPy and Pillow on the server, Three.js in the browser.

## Quick start

Needs Python 3.10+ with `numpy` and `scipy` (Anaconda has both). No other packages are required.

```bash
git clone https://github.com/MoAmrYehia/WorldLab.git
cd WorldLab
python -m worldlab serve --open
```

Open http://127.0.0.1:8765, create an account, and the season planner opens. Pick crops for any fields (or leave them all to the scientist) and press **Start the season**. Drag to orbit the farm, scroll to zoom, and click a plot to see its charts. Once the season starts:

1. Select a field.
2. Choose **Change the farm** to clog its drip line, release pests, make the groundwater saltier or send a heat wave.
3. Watch the agent notice, investigate and recover.

The dock at the bottom opens the trial plots, beliefs, season plan, RL policy, audit ledger and your past seasons (each can be replayed). The previous 2D dashboard is still at `/classic.html`.

The 3D view loads three.js from cdn.jsdelivr.net, so the browser needs internet access; the panels work without it. Without an API key, the agent falls back to the **scripted scientist with RL** and drone perception to a labelled **simulated perception**. Everything else is identical.

### Deploy: GitHub Pages + Hugging Face

**The website** is published automatically. The workflow `.github/workflows/pages.yml` copies `docs/` to the `gh-pages` branch on every push to `main`, and GitHub Pages serves it at https://moamryehia.github.io/WorldLab/. (If Pages is ever switched off: **Settings → Pages → Deploy from a branch → `gh-pages`**, folder `/`.)

**The server** (accounts, crop planning, live seasons) runs on a Hugging Face Space, deployed by `.github/workflows/huggingface.yml`:

1. Create a Hugging Face token with **write** access (huggingface.co → Settings → Access Tokens).
2. In this GitHub repository, add it as the secret `HF_TOKEN` under **Settings → Secrets and variables → Actions**.
3. Run **Deploy server to Hugging Face** from the **Actions** tab. It creates the Space `<your Hugging Face user>/worldlab` with the `Dockerfile`, and redeploys on every push.
4. If your Hugging Face user name isn't `moamryehia`, add the repository variable `HF_SPACE` (for example `yourname/worldlab`) and re-run **Publish website**, so the site points at your Space.

Optional: add the Space secret `MODEL_API_KEY` so Muse Spark runs the farm, and turn on persistent storage with the variable `WORLDLAB_DATA=/data` so accounts survive restarts (on free hardware they reset when the Space restarts).

The server only accepts browser calls from the sites in `WORLDLAB_ALLOWED_ORIGINS` (set to `https://moamryehia.github.io` in the Dockerfile). From another site the session token travels in an `Authorization` header, so login works even where third-party cookies are blocked. `WORLDLAB_MAX_RUNS` (default 3) caps how many seasons run at once.

### Search and sharing

Every public page has a title, a description, a canonical URL, Open Graph and Twitter card tags with a 1200 x 630 share image (`og-image.jpg`), and the landing page carries schema.org `WebApplication` data. The build writes `sitemap.xml` and `robots.txt` into `docs/`; log-in and sign-up pages are `noindex`. Icons: `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png` and `site.webmanifest`. To speed up Google indexing, add the site in [Google Search Console](https://search.google.com/search-console) as a URL-prefix property (`https://moamryehia.github.io/WorldLab/`), verify it with the HTML-tag method (paste the `google-site-verification` meta tag into `worldlab/site/index.html` and rebuild), then submit `https://moamryehia.github.io/WorldLab/sitemap.xml`.

### Record a replay

```bash
export MODEL_API_KEY=...                                   # the recorded demo uses Muse Spark and SAM 3.1
python scripts/build_experiments.py --spark                # demo season + paired experiments -> replay.json, experiments.json
python scripts/build_experiments.py                        # the same without an API key (scripted scientist)
python -m worldlab run --agent spark --seed 7 --perturb clog@95 --perception meta    # or record any single run
python -m worldlab export-replay runs/<run> --out worldlab/dashboard/replay.json --note "What this run shows"
python scripts/build_site_data.py                          # refresh the landing page's season calendar
python scripts/build_artifact.py docs                      # refresh the static site in docs/
```

### Muse Spark (Meta Model API)

```bash
export MODEL_API_KEY=...                 # Windows PowerShell: $env:MODEL_API_KEY="..."
python -m worldlab serve --agent spark --open
```

Optional settings: `WORLDLAB_SPARK_MODEL` (default `muse-spark-1.3`) and `WORLDLAB_REASONING` (default `medium`). With the key set, `--perception meta` (the default when a key is present) sends drone photos to SAM 3.1 and Muse Spark vision. A full season used about 600,000 input tokens (mostly cached), 7,000 output tokens and 54 perception calls; at the published prices that is under US$1.

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
python -m pytest -q tests/                                         # Python tests, no network needed
python scripts/build_artifact.py docs && python -m http.server -d docs 8811 &
node tests/browser/smoke.js http://127.0.0.1:8811                  # browser checks (needs playwright)
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

Results across 25 farm-scenarios per agent: 5 random farm seeds × 5 scenarios, for 4 scripted agents, 100 runs in all, recorded before the hard water and energy budget was added (soft budget) (`python -m worldlab bench --farms 5 --agents scripted,scripted-rl,scripted-noadapt,scripted-notrials`; raw runs in `docs/bench/runs.json`). The oracle plans with the true traits and suffers no faults.

| agent | scenario | runs | people_fed | pct_of_oracle | detected | detect_days_median | diagnosis_ok | false_alarms | within_limits | trait_error |
|---|---|---|---|---|---|---|---|---|---|---|
| scripted | none | 5 | 439.1 | 99.7 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted | clog | 5 | 429.1 | 97.2 | 5/5 | 20.0 | 5/5 | 0 | 5/5 | 0.4 |
| scripted | pest | 5 | 436.9 | 98.9 | 5/5 | 13.0 | 5/5 | 0 | 5/5 | 0.4 |
| scripted | salinity | 5 | 383.6 | 86.5 | 5/5 | 14.0 | 5/5 | 0 | 4/5 | 0.4 |
| scripted | heatwave | 5 | 419.2 | 95.2 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted-rl | none | 5 | 440.9 | 100.0 | – | – | 5/5 | 0 | 5/5 | 0.4 |
| scripted-rl | clog | 5 | 431.3 | 97.7 | 5/5 | 19.0 | 5/5 | 0 | 5/5 | 0.4 |
| scripted-rl | pest | 5 | 436.6 | 98.9 | 5/5 | 13.0 | 5/5 | 0 | 5/5 | 0.4 |
| scripted-rl | salinity | 5 | 387.3 | 86.9 | 5/5 | 16.0 | 5/5 | 0 | 4/5 | 0.4 |
| scripted-rl | heatwave | 5 | 420.7 | 95.5 | – | – | 5/5 | 0 | 5/5 | 0.4 |
| scripted-noadapt | none | 5 | 439.1 | 99.7 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted-noadapt | clog | 5 | 421.4 | 95.5 | 5/5 | 20.0 | 0/5 | 0 | 4/5 | 0.4 |
| scripted-noadapt | pest | 5 | 419.7 | 95.2 | 5/5 | 13.0 | 0/5 | 0 | 5/5 | 0.4 |
| scripted-noadapt | salinity | 5 | 370.8 | 83.4 | 5/5 | 14.0 | 0/5 | 0 | 4/5 | 0.4 |
| scripted-noadapt | heatwave | 5 | 419.2 | 95.2 | – | – | 5/5 | 0 | 4/5 | 0.4 |
| scripted-notrials | none | 5 | 384.2 | 88.1 | – | – | 5/5 | 1 | 4/5 | 0.9 |
| scripted-notrials | clog | 5 | 379.3 | 87.2 | 5/5 | 16.0 | 5/5 | 0 | 5/5 | 0.9 |
| scripted-notrials | pest | 5 | 379.8 | 87.4 | 5/5 | 17.0 | 5/5 | 0 | 4/5 | 0.9 |
| scripted-notrials | salinity | 5 | 343.7 | 78.5 | 5/5 | 14.0 | 5/5 | 0 | 4/5 | 0.9 |
| scripted-notrials | heatwave | 5 | 374.1 | 85.9 | – | – | 5/5 | 0 | 4/5 | 0.9 |

The four agents:

- **scripted:** the full protocol: trials, calibration, planning, monitoring, diagnosis and repair, with the plan's fixed irrigation rule.
- **scripted-rl:** the same, plus an irrigation policy trained by reinforcement learning in its calibrated model, deployed when its reward beats the rule on held-out imagined seasons (it did in all 25 farm-scenarios).
- **scripted-noadapt:** the full protocol, but it ignores alarms.
- **scripted-notrials:** plans on published values and never experiments.

What the numbers say:

- **Experimenting pays.** With trials, the harvest reaches 99.7% of the oracle; without them, 88.1%. That is about 55 more people fed for a year from the same land and water. Trait error halves (0.4 against 0.9 prior standard deviations).
- **Every hidden fault was detected**, at a median of 13–20 days, with no false alarms during the season. The cause was named correctly in every case:
  - a clogged line, by emitter flow test,
  - pests, by leaf inspection,
  - saltier groundwater, by water test.
- **Acting on the diagnosis helps**: 429 vs 421 people with a clog, 437 vs 420 with pests, 384 vs 371 with salty groundwater.
- **A forecast heat wave** raises no alarm. It is already in the forecast, so the model accounts for it.
- **The learned irrigation policy used less to feed as many (soft budget).** Across all 25 farm-scenarios, the RL agent fed slightly more people than the same agent with the fixed rule (423.4 against 421.6 on average), with 4% less groundwater (53,830 against 56,208 m³) and 8% less energy (76,843 against 83,413 kWh). It stayed within both limits in 24 of 25 runs, against 22 of 25 for the rule. The policy never saw the real farm: it was trained only in the agent's own model.
- **Limits.** These runs predate the hard budget. With the fixed rule, water and energy held in 22 of 25 runs; on farm 204 the actual year was drier than the planner's 90th-percentile assumption, and use overran by up to 2%. Execution now enforces a hard cut-off (see Resource limits above), so new runs cannot overrun; the hard-budget rerun is below.

An earlier version of this benchmark caught a real gap. A clogged line first shows up as *rising soil salinity* (less water means less leaching), not as dry soil. The scripted agent only tested the groundwater, so it never found the clog. It now tests both causes, and clog diagnosis went from 2/5 to 5/5.

### Hard-budget rerun

After the hard water and energy budget was added, the two headline agents were rerun on the same 5 farm seeds × 5 scenarios (`python -m worldlab bench --farms 5 --agents scripted,scripted-rl`; raw runs in `docs/bench/hard/runs.json`, table in `docs/bench/hard/summary.md`).

| scripted agent, hard budget | runs | people fed, mean | groundwater m³, mean | energy kWh, mean | within both limits | faults detected and diagnosed |
|---|---|---|---|---|---|---|
| with the learned irrigation policy | 25 | 471.3 | 57,580 | 85,501 | 25/25 | 15/15 |
| with the fixed irrigation rule | 25 | 421.6 | 56,108 | 83,284 | 25/25 | 15/15 |

No run exceeded a limit. Trained and compared under the same cap, the policy learned to use more of the allowance (about 3% more water and energy) and fed 12% more people on average; the policy was deployed in all 25 farm-scenarios. The oracle (true traits, fixed rule, no faults) averages 441 people, so the policy's gain comes from irrigation timing, not from knowing the traits. These remain scripted-agent results on simulated farms; the soft-budget table above is kept as the historical record.

### Muse Spark on the same 25 farm-scenarios

Muse Spark (`muse-spark-1.3`) ran the same 5 farm seeds × 5 scenarios under the hard budget, with SAM 3.1 and Muse Spark vision reading its drone photos (`WORLDLAB_BENCH_PERCEPTION=meta python -m worldlab bench --farms 5 --agents spark`; raw runs in `docs/bench/spark/runs.json`, table in `docs/bench/spark/summary.md`). Each pair below shares the farm seed, weather year and hidden change.

| scientist, hard budget | people fed, mean | groundwater m³ | energy kWh | within both limits | faults diagnosed | false alarms | trait error | drone looks per season |
|---|---|---|---|---|---|---|---|---|
| Muse Spark + SAM 3.1 + Muse Spark vision | 455.9 | 57,411 | 86,635 | 25/25 | 15/15 | 0 | 0.3 | 4.6 |
| scripted protocol + learned irrigation policy | 471.3 | 57,580 | 85,501 | 25/25 | 15/15 | 0 | 0.4 | 1 per alarm |
| scripted protocol + fixed rule | 421.6 | 56,108 | 83,284 | 25/25 | 15/15 | 0 | 0.4 | 1 per alarm |

| scenario | Muse Spark | scripted + policy | Muse Spark ahead in |
|---|---|---|---|
| none | 472.5 | 499.7 | 2 of 5 |
| clog | 453.6 | 478.4 | 2 of 5 |
| pest | 470.6 | 483.4 | 2 of 5 |
| salinity | 425.3 | 416.6 | 3 of 5 |
| heat wave | 457.7 | 478.6 | 1 of 5 |

What this shows:

- **Muse Spark is a sound scientist.** It found the cause of every hidden fault, with no false alarms, and learned the hidden crop traits more accurately than the protocol (0.3 against 0.4 prior standard deviations). It detected saltier groundwater sooner (median 11 days against 14) and fed more people in that scenario. In one pest run it found the outbreak on a routine drone look before any sensor alarm (so 14 of 15 faults raised an alarm, and all 15 were found).
- **The hand-tuned protocol still feeds more on average** (3% more people). Muse Spark beats the plain fixed-rule protocol by 8% and wins 10 of 25 paired runs against the protocol with its learned policy. Its choices vary between runs, so these are single outcomes, not averages over repeats.
- **Diagnosis is scored on what the scientist did**: the cause it wrote into its model (`update_model`) or treated (repair, pest control), with no wrong cause. The first Muse Spark run of the pest scenarios was scored by keywords in its hypotheses and marked 0/5 because it wrote "pest damage", not "pests"; those five scenarios were rerun with the structured score (5/5), and the rerun is what the table reports.
- **Cost:** about 680,000 input tokens (mostly cached), 8,500 output tokens and 34 scientist calls per season, plus about 18 SAM 3.1 calls and one Muse Spark vision call per drone look.


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
  farm/seasons.py    sowing seasons, which crops fit each, and the crop guide shown in the planner
  accounts.py        accounts, sessions and run history (SQLite, scrypt)
  server.py          website and API server (standard library, server-sent events), one farm per account
  replay.py          turns a recorded run into a static replay
  site/              landing, log-in and sign-up pages (index.html, login.html, signup.html, site.css, site.js, hero.js)
  progression.py     missions, achievements and experience, computed from ledger events
  dashboard/         the farm app (index.html, app.js, style.css), replay.json, classic 2D dashboard
  dashboard/scene.js 3D facade: sky and time of day, cameras, picking, overlays, adaptive quality
  dashboard/engine/  procedural 3D assets: textures, terrain, flora, ten crops, fields and infrastructure, effects
docs/                static copy of the landing page, with the replay app in docs/app/ (GitHub Pages)
Dockerfile           Hugging Face Spaces / container deployment
tests/               unit tests, including the agent loop against a mock OpenAI-compatible endpoint
```

## License

MIT. See [LICENSE](LICENSE).
