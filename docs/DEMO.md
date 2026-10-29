# Two-minute demo script

Record at 1440×900 with `python -m worldlab serve --agent spark --open`. The trial phase takes a minute or two of model calls; cut the waiting in the edit. Set the season speed to 4 days/s for the fault, then speed up.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Dashboard, empty farm map | "Twelve hectares near Al Ain: six fields, some already salty, brackish groundwater, a fixed water quota. The job: feed as many people as possible, counting only people whose calories, protein and vitamin A are all covered, in a bad year." |
| 0:12 | Press **Start run**; first plan appears in the plan table | "Muse Spark runs the farm through tool calls. Its first plan uses published crop values, and it tells us that not knowing these local varieties costs about 70 people." |
| 0:25 | Hypotheses panel; trial plots appear with blue bands and orange dots | "So it experiments first. It picks trial plots for what they reveal: a saline plot to learn salt tolerance, a late sowing so flowering hits the spring heat. Each plot is predicted before it's grown." |
| 0:40 | A "Prediction failed" plot; belief chart narrows | "Some predictions fail. That's the point. Sorghum here flowers badly in the heat, nearly four degrees worse than published. Each blue interval narrows only for what a plot actually exposed." |
| 0:55 | New plan; cost of uncertainty drops | "The calibrated plan feeds more people, and the cost of uncertainty drops from about 70 to 17. Wheat goes on the saline field, sweet potato covers vitamin A, maize gives calories." |
| 1:05 | Season runs; select field F2; **Change the farm → Clog a drip line** | "Now the season. I clog a drip line in this field. The agent isn't told, and the water meter can't see it." |
| 1:15 | Soil moisture leaves the blue band; red alarm; status turns red | "The soil dries faster than its model says it should. That's the alarm." |
| 1:25 | Hypotheses: clogged line vs more water use; flow test result in the notebook | "Two explanations: a clogged line, or a thirstier crop. One test separates them. The emitters deliver 45 percent." |
| 1:40 | Notebook: repair, model update, water re-plan | "It repairs the line, tells its model what happened since the onset, and re-plans water for the rest of the season within what's left of the quota." |
| 1:50 | Season over; people fed; **Verify ledger** | "Harvest: 443 people fed, within the water budget. Every hypothesis, prediction and decision is in a hash-chained ledger anyone can verify." |
| 2:00 | Benchmark table | "Across random farms with hidden faults, it catches and correctly diagnoses clogs, pests and salty groundwater, and it beats the same agent that ignores anomalies." |
