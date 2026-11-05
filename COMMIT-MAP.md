# Commit map: IDs before and after the 6 Nov 2026 history rewrite

On 6 November 2026 the history of `main` was rewritten to remove co-author lines from commit messages. The rewrite changed
messages only: every commit's files are identical (the final tree is the same object), so the source-tree hashes recorded in
the evidence bundle still match.

Because a commit ID covers its message and its parents, every commit got a new ID. Records written before the rewrite keep
the original IDs on purpose, because they are evidence of what ran:

- the run manifests and `manifests.json` files under `docs/bench/`;
- the frozen holdout files (`holdout_v1.json`, `holdout_v2.json`);
- the evidence bundle's manifest.

Use this table to find the current commit for an original ID. The prose docs now cite the current IDs.

| date | original ID | current ID | commit |
|---|---|---|---|
| 2026-10-29 | `a38fb1e` | `121c77e` | Core lab: grey-box thermal model, simulator, safety governor, anomaly monitor, ledger, agents |
| 2026-10-29 | `480f94f` | `696ee41` | Dashboard server and live dashboard; CLI |
| 2026-10-29 | `12bed4b` | `cc30723` | Benchmark harness; structural uncertainty, trust-region validation, proportionate anomaly response |
| 2026-10-29 | `9773f56` | `49a1ba4` | Serial rig driver and Arduino firmware, README, benchmark results, demo script |
| 2026-10-29 | `5988e0e` | `26601ea` | Pivot to crop management: WorldLab Crops |
| 2026-10-29 | `dd7729d` | `cb0dcda` | Farm dashboard, tests, benchmark results, README, demo script |
| 2026-10-29 | `0bf8b9c` | `b67aa25` | Add RL irrigation policy, 3D web app, replay mode and Docker deployment |
| 2026-10-29 | `6849803` | `8732f81` | Water flows along drip lines, README screenshot, static app refresh |
| 2026-10-29 | `78b7db4` | `62489b2` | Benchmark with the RL agent; README results |
| 2026-10-30 | `80c5b8c` | `44e2131` | Website: landing page, sign up and log in, per-account farms, season-based crop planner |
| 2026-10-30 | `e4be732` | `b3a9aff` | Serve docs/ on GitHub Pages without Jekyll |
| 2026-10-30 | `edd8780` | `1180efa` | Host the website on GitHub Pages with the server on Hugging Face |
| 2026-10-30 | `90b4570` | `888198f` | Publish the website to gh-pages automatically; create the Hugging Face Space on first deploy |
| 2026-10-30 | `94acb9b` | `2910bf1` | 3D view sways instead of orbiting; alarm tags hidden until an alarm; hero text scrim |
| 2026-10-30 | `8f8b743` | `1b35974` | Lighter fog and closer hero camera; versioned asset links on static hosts |
| 2026-10-30 | `94e95ba` | `82b6f89` | Keep the hero farm clear of the headline on mid-width screens |
| 2026-10-30 | `2660b02` | `1eb60e0` | New procedural 3D engine: sky, terrain with Jebel Hafeet, palms and ghaf trees, ten crop species with growth stages, irrigated soil, infrastructure, drone, weather |
| 2026-10-30 | `e1452df` | `585f028` | Version static assets by content hash |
| 2026-10-30 | `6352dfd` | `2001e29` | Green Frontier interface: missions, investigation, planner previews, dark landing |
| 2026-10-30 | `0f6aa3e` | `9403ae9` | Compact unplanned field tags, lamp lights only at night, calmer sand ripples |
| 2026-10-30 | `772dab5` | `ebfa295` | Crop pictures, drone feed, agent view and AI components table |
| 2026-10-30 | `ec95a56` | `07125ef` | New icons, search and share metadata, refreshed README |
| 2026-10-30 | `750185e` | `eb8912b` | Act on the WorldLab audit: access, correctness and a coherent journey |
| 2026-10-30 | `4378db8` | `0362943` | Hard-budget benchmark rerun; bounded, WebGL-free browser checks in CI |
| 2026-10-30 | `0120a1b` | `26df18c` | Add the audit response checklist |
| 2026-10-31 | `c1a1ecc` | `9c99ac3` | P2: weather workspace, scenarios and farm editor, human decisions, paired experiments, soil carryover, costs, shareable reports |
| 2026-10-31 | `5b49eac` | `54d35af` | Muse Spark runs the recorded season; SAM 3.1 and Muse Spark vision read photoreal drone frames |
| 2026-11-01 | `5498e84` | `a802c01` | Honest run status, typed perception, verified comparisons |
| 2026-11-01 | `f3406ee` | `d7b9696` | Live judge path: readiness, guest sessions, atomic admission, budgets, deploy check |
| 2026-11-01 | `53e41d7` | `c17df38` | Judge walkthrough, spoiler-free replays, offline evidence bundle, tighter sessions |
| 2026-11-01 | `43f4299` | `296a6a8` | Holdout families (sensor bias, root disease, compound, random fields), real 2024-25 weather from NASA POWER |
| 2026-11-01 | `9ab1c57` | `59505eb` | Freeze holdout challenge v1 (8 cases, seeds 401-408) before any run |
| 2026-11-01 | `3b493fc` | `1cd9828` | Model card and What-is-real tab; scoring unit tests; new families in the app and missions |
| 2026-11-01 | `41c6ba9` | `78b5c82` | Demo script with live and recorded segments; site rebuilt; browser check for the limitations card |
| 2026-11-01 | `7e365a6` | `e2e785c` | Holdout v1 results: 16 runs, summary, every ledger and manifest, failure analysis |
| 2026-11-01 | `716e7a9` | `bc14527` | Benchmark cost: mean over all runs, three decimals (was rounded to zero) |
| 2026-11-01 | `7a79cec` | `beb2746` | README: short reviewer section (user, capability, try it, Meta roles, measured comparison, limits, reproduce) |
| 2026-11-01 | `a687f88` | `078875e` | Benchmark v2 results: 105 runs with ledgers and manifests, summary, per-case list, ablation and failure analysis |
| 2026-11-01 | `f575f45` | `980553b` | README, landing page and walkthrough: benchmark v2 and holdout results; Glimmer marked unbenchmarked; v1 kept as the earlier run |
| 2026-11-01 | `6532f35` | `bff3b68` | Rebuild the static site with the walkthrough, limitations card and new results |
| 2026-11-01 | `7d09e11` | `90c8000` | Track the NASA POWER weather extract (data/ ignore now applies to the root accounts folder only) |
| 2026-11-01 | `7a5bce1` | `db72b7e` | Publish benchmark v2 and holdout run ledgers and manifests (runs/ ignore now applies to the root only) |
| 2026-11-01 | `fdcf833` | `97dbab1` | Submission checklist: criteria to evidence, brief task status, owner's portal checklist |
| 2026-11-01 | `8c15a7e` | `f23b324` | Browser checks: poll with evaluate instead of waitForFunction (the pages' CSP forbids eval) |
| 2026-11-01 | `3fc82b8` | `95151a3` | One release pipeline: tested once, both surfaces from the same build, newest commit only, required server deploy (or explicit SERVER_DEPLOY=skip), release stamped into /api/ready and the app; live check requires real progress, reconnect, cancellation and a bounded Muse Spark start |
| 2026-11-01 | `15d627f` | `96b6e16` | Planning loss fix: multi-start calibration with an instability guard, nutrient-risk report and backup allocation before sowing, explicit escalation after repeated unresolved alarms; scripted baseline gets fixed rules for both; regression tests from the archived farm-204 run |
| 2026-11-01 | `7055907` | `2af4922` | Scorer 2.1 (evidence before credit, premature claims, censored follow-up, signal attribution, escalation not diagnosis); all 121 archived runs rescored from their ledgers with the 2.0 score kept; realized event identity and same/changed-field pairs; provenance note for the 50 dirty-source runs |
| 2026-11-01 | `a5000ae` | `571f3b4` | Docs: exact diagnosis counts instead of 'as accurately', no broad claim about image models, theme vs track, keep history (no rewrite step), holdout numbers under scorer 2.1 |
| 2026-11-01 | `4246152` | `2e5e932` | Holdout v2 pre-registered criteria; generator parameterised (v1 reproduces byte for byte); adaptation test asserts the repair, not a yield order |
| 2026-11-01 | `b4144b8` | `31a2f50` | Freeze holdout v2 (8 cases, seeds 601-608) before any run |
| 2026-11-01 | `b2a852d` | `158a35e` | App: nutrient risk in the plan view, risk decisions and escalations in the activity log; the sown plan is the one shown |
| 2026-11-01 | `5f6b54a` | `31cf91d` | Achievement test: thresholds follow the harvest instead of assuming one |
| 2026-11-01 | `79a5cbd` | `742eee7` | Holdout v2 results against the pre-registered criteria (24 runs: Spark new code, Spark old code, scripted); README, landing, walkthrough and submission table updated; site rebuilt |
| 2026-11-01 | `032b545` | `6a7328d` | Hosting without Hugging Face PRO: Render blueprint, PORT-aware container, release SHA from the host's build commit, explicit SERVER_DEPLOY=render mode that waits for the release and runs the live check |
| 2026-11-01 | `e9f3fdf` | `f804e8b` | Release: point the site's security policy at the configured server; read live-check headers case-insensitively |
| 2026-11-01 | `44d7f0e` | `0044074` | Live check: allow a slow host more time to show progress |
| 2026-11-01 | `c35e96d` | `35c2c62` | Live check: give a stop the same slow-host allowance, and report how long it took |
| 2026-11-01 | `e42a972` | `d677ec6` | Status after the first passing release; a mission panel that claims nothing definite mid-season |
| 2026-11-02 | `c860f68` | `ed39fff` | Faster live seasons on a small host |
