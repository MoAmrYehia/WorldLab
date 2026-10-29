# Two-minute demo script

Record the dashboard at 1440×900 with `python -m worldlab serve --agent spark --speed 20 --open`.
At 20× a full run takes about 3–4 minutes; cut the waiting in the edit.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Dashboard, empty | "WorldLab is an AI scientist. Its job: keep this heatsink, a stand-in for a chip, under 42 °C for 20 minutes with as little fan energy as possible. It knows nothing about this rig yet." |
| 0:10 | Press **Start run**. Camera panel fills in | "Muse Spark drives everything through tool calls. First it looks: SAM 3.1 finds the fan and the heatsink." |
| 0:20 | Hypotheses panel shows H1; blue band appears, very wide | "Before any experiment it writes down a hypothesis and a prediction. The blue band is its prediction; it is wide because it knows almost nothing." |
| 0:35 | Heat-up experiment; band narrows; staircase experiment | "Each experiment is chosen for how much it reduces the uncertainty that drives energy use, per joule. Watch the band shrink as evidence comes in." |
| 0:50 | Cooling-curve panel and ranking table | "It compares four physical explanations for how airflow scales with fan speed and keeps the one the evidence supports." |
| 1:00 | Plan starts; "Cost of uncertainty" figure | "Now it plans the cheapest fan schedule that is still safe at the 95th percentile, and tells us how many joules its remaining uncertainty is costing." |
| 1:10 | Press **Move the fan**. Dotted line appears | "Now I move the fan. The agent is not told." |
| 1:15 | Orange leaves the blue band; "camera saw a change" or "prediction failed"; status turns red | "Its predictions fail, and the camera sees the fan turned away. It stops trusting its model." |
| 1:25 | Hypotheses H2 and H3; discriminating experiment runs | "Two explanations: the fan moved, or the heater changed. A fan-off step separates them: if the old model still explains fan-off, only the fan changed." |
| 1:40 | H2 supported, H3 refuted; cooling curve shows "before the change" vs now | "Fan-off matches, fan-on doesn't. It refits only the fan's coupling, keeping everything else it knew." |
| 1:50 | Plan resumes; figures; press **Verify ledger** | "It finishes the task. Every hypothesis, prediction and result is in a hash-chained ledger you can verify." |
| 2:00 | Benchmark table from the README | "Across randomised worlds, it catches every moved fan and names the cause, at close to oracle energy." |

Tips: use the **Agent reasoning** filter in the notebook to show Muse Spark's own words; switch to dark mode with **Theme** if it reads better on video.
