# Three-minute demo script

The hackathon asks for a three-minute video showing the features, code and functionality built during the event. Judges score Impact (30%), Use of Meta AI tooling (25%), Demo (25%) and Technical depth (20%).

Record at 1440×900 on a machine with a GPU (the 3D farm needs WebGL). Use the recorded season, so nothing waits on the network: <https://moamryehia.github.io/WorldLab/app/?demo>. Everything below is in that recording: Muse Spark decided it, and SAM 3.1 and Muse Spark vision read its drone photos.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Landing page: the 3D flyover of the farm at golden hour | "This is WorldLab. An AI scientist runs a twelve-hectare farm near Al Ain, in the UAE: salty soils, brackish groundwater, a fixed water quota and energy budget. Its goal is to feed as many people as possible in a bad year. Someone only counts if their calories, protein and vitamin A are all covered." |
| 0:15 | Click **Watch a recorded season**. Point at the run header: "Muse Spark · SAM 3.1 + Muse Spark" | "The scientist is Muse Spark, through the Meta Model API. It never touches the farm directly: it calls nineteen tools, and every call carries a written reason." |
| 0:25 | **Agent** tab: the loop and the first tool calls | "First it plans on published crop values. Its own plan says not knowing these local varieties costs about seventy people. So it writes a hypothesis: the local varieties behave as published." |
| 0:40 | **Research › Trials**: plots with predicted ranges; the sorghum plot marked as a missed prediction | "It plants twelve trial plots, each with a prediction before it is sown. Sorghum collapses: one ton per hectare against six predicted. Hypothesis refuted. It learns that local sorghum can't take the spring heat, drops it and re-plans." |
| 0:58 | **Research › Irrigation policy**: training curve and the comparison | "Then it trains an irrigation policy by reinforcement learning, thirty-nine thousand imagined seasons inside its own model. It deploys it only because it beats the fixed rule on seasons it never trained on." |
| 1:12 | Play. The season runs; open the **Weather** tab for a moment | "Now the season runs. The scientist's model runs beside the farm and predicts every sensor, with a band of uncertainty." |
| 1:22 | Click **Incident**. F4's alarm ring; the investigation panel | "On the fourth of January a drip line in field F4 clogs. Nobody tells the scientist, and the water meter can't see it. Three weeks later the soil reads drier than the model's band. The season stops." |
| 1:35 | Press **4**, then **]** until the drone photo appears. Click it to enlarge; switch **Model expected** ↔ **Drone photo** | "Muse Spark sends the drone. It gets two images: the photo, and the view its own model expected. Same plants, same rows, but the real field has white salt crust between the rows. Less water is reaching the roots, so less salt is washed down." |
| 1:55 | Investigation panel: two hypotheses, two tests | "It writes two competing hypotheses, a clogged line or saltier groundwater, and runs the test that separates them. Emitters deliver forty-six percent of their design flow; the groundwater is normal. Clog supported, salt water refuted." |
| 2:10 | **Agent › Decision record** filtered to F4: repair, model update, controller back to rule, re-plan | "It repairs the line, tells its model what happened since the onset, switches irrigation back to the rule because the policy was trained on a healthy farm, and re-plans the rest of the season's water." |
| 2:22 | Enlarge F6's drone photo and click **SAM 3.1** | "SAM 3.1 counts the plants: one hundred seventy-five of one hundred seventy-six. Every count is checked afterwards against what the frame really shows." |
| 2:32 | Click **Harvest**, then the harvest report | "Five hundred and six people fed, inside both limits." |
| 2:38 | **Results › Compare** | "Same farm, same weather, same fault: the scripted scientist feeds four hundred eighty-five, and one that ignores its alarms four hundred fifty-seven." |
| 2:46 | **Agent › Audit ledger** | "Every hypothesis, prediction, test and decision is in a hash-chained ledger, and the missions and achievements are scored from it." |
| 2:53 | Back to the landing page | "WorldLab: an AI that learns how a farm really behaves by running experiments, and keeps itself honest when the world changes." |

## Before recording

- Open the replay once so the drone images are cached; turn on **Settings › Follow events**.
- Keyboard: space plays or pauses, `]` steps to the next event, `1`–`6` select a field, `Esc` closes panels and the enlarged photo.
- Say "built during the hackathon" once, and keep the code on screen for a second (`worldlab/agent.py`, `worldlab/perception.py`) if time allows: judges must be able to tell what was built during the event.
