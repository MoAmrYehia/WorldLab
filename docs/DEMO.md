# Two-minute demo script

Record at 1440×900. Two options:

- **Live:** `python -m worldlab serve --agent spark --open`. Model calls during trials take a minute or two; cut the waiting in the edit. Set the speed slider to about 4 days per second for the fault, then speed up.
- **Replay:** open `docs/app/index.html` from any static host (or the published replay). It plays a recorded run with no server and no API key.

| Time | On screen | Say |
|---|---|---|
| 0:00 | The camera flies in over the dunes to the farm: six plots, palms, the pump house and desalination unit | "Twelve hectares near Al Ain. Six fields, some already salty, brackish groundwater, a fixed water quota and energy budget. The goal: feed as many people as possible, in a bad year, counting someone only when calories, protein and vitamin A are all covered." |
| 0:12 | First plan appears; the KPI shows people fed in a bad year | "Muse Spark runs the farm through tool calls. Its first plan uses published crop values, and it tells us that not knowing these local varieties costs about 70 people." |
| 0:22 | Trial plots grow in the strip behind the farm; some get an orange "Prediction missed" tag. Open **Trials** | "So it experiments first. Each plot gets a predicted yield range before it is planted. A saline plot to learn salt tolerance, a late sowing so flowering hits the spring heat. Some predictions miss. That is the point." |
| 0:38 | **Beliefs** drawer: violet intervals narrow only for exposed traits | "Each miss updates its beliefs, and only for traits a plot actually exposed." |
| 0:48 | **RL policy** drawer: training curve, then rule vs policy | "Before sowing, it trains an irrigation policy by reinforcement learning, inside its own model of the farm: thousands of imagined seasons with crop traits drawn from its beliefs. The policy reads the sensors each day and scales the drip schedule and water blend. It keeps the farm inside the water quota in every imagined year, where the fixed rule overran in almost one in five." |
| 1:02 | Season runs: plants grow, drip lines glow; select a field | "Now the season, with the policy in charge of the water." |
| 1:08 | Clog appears (live: **Change the farm → Clog the drip line**); the drip lines in that plot turn red and dim | "A drip line clogs. The scientist isn't told, and the water meter can't see it." |
| 1:16 | Red ring and alarm; soil salinity leaves the violet band | "Soil salinity rises out of its predicted band. Less water reaching the roots means less salt is leached. That's the alarm." |
| 1:26 | Drone flies to the plot with a scan cone; notebook shows the water test, then the emitter flow test | "Two explanations: saltier groundwater, or a clogged line. The water test is normal. The emitter test reads 45 percent." |
| 1:40 | Repair, model update, water re-plan; alarm clears | "It repairs the line, tells its model what happened since the onset, and re-plans the rest of the season." |
| 1:50 | Season ends; plots harvested; KPI shows people fed; **Ledger** | "Harvest: about 460 people fed, inside the water and energy limits. Every hypothesis, prediction and decision is in a hash-chained ledger anyone can verify." |
| 2:00 | Benchmark table | "Across random farms with hidden faults, it catches and correctly diagnoses every clog, pest outbreak and salt problem, and the RL policy uses less water than the fixed rule." |
