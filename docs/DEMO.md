# Three-minute demo script

Working length: about three minutes. **Check the actual limit in the signed-in submission portal before recording**; this
repository has not verified it from the participant-only instructions.

The video has two clearly labelled parts: a **recorded evidence segment** (a full Muse Spark season, replayed exactly as
logged) and a **live segment** (a fresh season on the hosted server, started on camera). Label both on screen. When
playback is accelerated, keep the date and the playback speed visible (the run header shows both).

Record at 1440×900. The 3D farm needs WebGL; on a machine without it the 2D map shows the same evidence.

| Time | Segment | On screen | Say |
|---|---|---|---|
| 0:00–0:20 | Who and why | Landing page, then the farm | "Agronomy teams working on water-limited farms have to choose crops and irrigation under a hard water and energy budget, then work out what went wrong when the field stops behaving as expected. WorldLab is an AI scientist for that loop: predict, test, act, and keep a record. This farm near Al Ain has salty soils, brackish groundwater, a 60,000 m³ quota and a 90,000 kWh budget." |
| 0:20–0:50 | **Recorded**: prediction, experiment, corrected belief | Open the recorded season, press **Walkthrough**. Step 1 shows the hypothesis and the trial plots with their predicted ranges | "This is a recorded season, replayed exactly as logged. The scientist is Muse Spark, through the Meta Model API. Before planting, it predicted a yield range for every trial plot. Sorghum came in at 1.08 t/ha against 6.44 predicted, so it refuted its own hypothesis and corrected its belief about the local sorghum's heat tolerance." |
| 0:50–1:35 | **Recorded**: hidden incident | Walkthrough steps 2–5: the alarm, the drone photo against the model's expected view (enlarge it), the two hypotheses, the two tests, the repair and re-plan | "A drip line in F4 was clogged on 4 January without anyone telling the scientist. The water meter can't see it. The soil readings left the model's band 20 days later, on 24 January: that's the detection delay, not instant. Muse Spark sent the drone. SAM 3.1 segmented salt crust, and Muse Spark compared the photo with the view its own model expected. It wrote two competing explanations, a clog or saltier groundwater, and ran the test that separates them: emitters at 46% of design flow, groundwater normal. Then it repaired the line, updated its model and re-planned the water, all within the hard budget." |
| 1:35–2:05 | **Live**: a fresh, unfamiliar case | On the website, press **Try a live season (no account)**. In the planner, choose **Unknown challenge** and start. Show the run header: *Live · Muse Spark* and the date advancing | "This one is live. The server has just drawn a hidden challenge at random: a fault, two faults, a faulty sensor, a disease no test can identify, or nothing at all. Neither of us knows which. Watch the scientist decide." (If the server is asleep or Muse Spark is unavailable, say so: the run header shows it. Cut to the frozen holdout runs instead, and label that cut.) |
| 2:05–2:35 | Fair comparison and its limits | **Results › Compare**, then the benchmark table in the README | "One season is a showcase, not a benchmark. Across the full benchmark, every run on the same farms and hidden events, here's how Muse Spark compares with our scripted protocol, including where it does worse. On the frozen holdout of eight unfamiliar farms, here is what it got right, what it missed, and when it asked a person instead of guessing." (Read the numbers from `docs/bench/v2/summary.md` and `docs/bench/holdout/summary.md`; don't round them up.) |
| 2:35–3:00 | Boundaries and next step | **Agent › AI components** (what is Meta, what is code), **Audit ledger** with *Download the evidence bundle*, then **Results › What is real** | "Meta's models decide and see; the crop model, the budget checks and the ledger are code. The whole recorded run downloads as an evidence bundle that verifies offline in one command. What's real so far is the weather: a season can run on NASA POWER's record for Al Ain in 2024–25. The next step is one real farm, its own sensors and an agronomist approving each action." |

## Don'ts

- Don't call the recorded season's 506.4 people fed against 485.1 a general win: it is one farm and one fault.
- Don't say detection is instant or real time: in the recorded season the clog started 20 days before the alarm.
- Don't show Muse Glimmer as working: an endpoint adapter exists, but it has not been run or benchmarked.
- Don't describe drone photos as real: they are renders of the simulator's state.

## Before recording

- Open the replay once so the drone images are cached.
- Keyboard: space plays or pauses, `]` steps to the next event, `1`–`6` select a field, `Esc` closes panels and the
  enlarged photo.
- Wake the live server a few minutes before (open the website and wait for *Live*), and check that the run header says
  Muse Spark. Guest seasons are limited to 3 per session.
- The hosted server runs on Render's free plan (0.1 CPU), so a live season moves about ten times slower than on a laptop:
  film its start (the guest session, the Unknown challenge, the first Muse Spark tool calls), not the whole season.
- Say "built during the hackathon" once. Keep `worldlab/agent.py` and `worldlab/perception.py` on screen for a second,
  so judges can see what was built during the event.

## The captioned cut

A 3-minute cut of this script exists with burnt-in captions: the recorded season (labelled *RECORDED · simulated
dates*), three live scenes from the public site and the hosted server (labelled *LIVE*), the benchmark and holdout
results, and what is real. The video file is kept outside the repository; its narration follows the table above.
