# Submission: status, evidence and the owner's checklist

Each item is placed in exactly one column, by the strongest check it has actually passed:

- **Implemented:** in the source.
- **Locally tested:** passed the unit tests (90) or the browser checks, run against a local build.
- **Deployed and tested:** checked on the public site or the hosted server.
- **Owner confirmation required:** only the owner can do it or confirm it.

## Release and live demo

| Item | Implemented | Locally tested | Deployed and tested | Owner confirmation required |
|---|---|---|---|---|
| Static site, judge walkthrough, limitations card, evidence download, CSP | | | ✓ Public site: the walkthrough ran with 3D on a real GPU, no CSP errors, and the evidence bundle downloaded and verified | |
| One release pipeline: tested once, both surfaces from one build, newest commit only, required server deploy | | | ✓ Release run 41320205503 (commit `c35e96d`): tests, build, browser checks, website, server live check all passed | |
| Release SHA in `/api/ready` and in View settings | | | ✓ The Render server reports the commit it runs (`RENDER_GIT_COMMIT`); the release waits for it to match | |
| Live check: release, CORS, real progress, reconnect, cancellation, bounded Spark start | | | ✓ Passed against Render from GitHub Actions: guest session from the website's origin, the season progressed (6 → 35 ledger entries), the stream reconnected, stop cancelled the run (88 s), Muse Spark made a tool call and the lab ran it | |
| Hosted server (guest seasons, Unknown challenge, live Muse Spark) | | | ✓ Render free plan, `https://worldlab-4b9q.onrender.com`. A guest started a Muse Spark season on the Unknown challenge from the public site | ✓ The free plan has 0.1 CPU: a season runs about ten times slower than on a laptop, and the server sleeps after 15 idle minutes (about a minute to wake). A paid plan is the owner's choice |

## Evidence and evaluation

| Item | Implemented | Locally tested | Deployed and tested | Owner confirmation required |
|---|---|---|---|---|
| Benchmark v2: 105 runs, scorer 2.1, ledgers, provenance note | | ✓ All ledgers checked against their manifest hashes and rescored | The summaries are published in the repo | |
| Holdout v1 (8 farms) and holdout v2 (8 farms, pre-registered criteria, old vs new code) | | ✓ 16 + 24 runs, all completed | Published in the repo | |
| Scorer 2.1: evidence first, premature claims, censored follow-up, signal attribution, escalation | | ✓ `ScorerV21Tests`, `BenchScoreTests`, the review's four probes | | |
| Planning-loss fix: multi-start calibration, nutrient-risk gate and backup, escalation | | ✓ `PlanningLossTests` (regression from the archived farm-204 run); development rerun 26.4 → 407.8 | No measured improvement on holdout v2 (no catastrophic season either way) | |
| Measured benefit from Muse Spark | | ✓ Tested by holdout v2 criterion C2: **no measured benefit** (−15.3, 95% interval −34.0 to +5.6; 4/6 against 5/6 diagnosed; 0 wrong calls each) | | |
| Offline evidence bundle for the recorded season | | ✓ Tamper, omission, reorder and truncation tests | ✓ Downloaded from the public site; verifies | |
| Real data: NASA POWER 2024–25 weather, pinned by hash; ET0 against FAO-56 example 18 (−3%) | | ✓ `RealWeatherTests` | | |
| Practitioner review | | | | ✓ None yet; the model card says so |

## Judging criteria → where to look

The weights below come from the hackathon page as read during the build. Confirm them in the portal.

| Criterion | Where to look |
|---|---|
| **Impact (30%)** | README *For reviewers*; [`model-card.md`](model-card.md) covers the user, what is real, the limits and the next pilot. |
| **Use of Meta AI (25%)** | Muse Spark chooses every step through tool calls; SAM 3.1 and Spark vision read the drone photos. See [`bench/v2`](bench/v2/) and [`bench/holdout_v2`](bench/holdout_v2/). The image models showed no diagnosis gain on the tested clog and pest cases. Spark showed no measured benefit over the scripted protocol on holdout v2. Muse Glimmer: adapter only, not run. |
| **Demo (25%)** | The recorded walkthrough is public, and live guest seasons run on the hosted server (slowly, on a free plan). Script: [`DEMO.md`](DEMO.md). |
| **Technical depth (20%)** | Event-level scoring with a versioned scorer; frozen holdouts with criteria written before the runs; a before/after comparison against the old code; offline-verifiable ledgers; honest run states; budgets and atomic admission. |

**What we don't claim:**
- that Muse Spark farms better (v2: −30.3; holdout v2: −15.3);
- that the planning fix is proven on held-out farms (one development case);
- that the image models help diagnosis in the tested cases;
- that any part is field-validated.

## Owner's checklist

Confirm every required field in the signed-in portal; this list is not a substitute for it.

- [x] **Live server:** deployed on Render (free plan) from `render.yaml`; `MODEL_API_KEY` is set in Render, and the GitHub variables `SERVER_DEPLOY=render` and `WORLDLAB_SERVER` point the release at it. The release's live check passes, including the bounded Muse Spark check.
  - Optional: a full Muse Spark season on the hosted server, with its result and model cost recorded here.
- [ ] **History:** keep `main` as it is. Its history supports the build timeline and the holdouts' freeze-before-run provenance. Rewriting it is a separate decision, not a submission step.
- [ ] **Video:** a 3-minute cut with burnt-in captions and a narration script is made (recorded season plus a live segment). Confirm the **actual length limit** in the portal, record the narration, and upload it.
- [ ] **Theme and track:** *Push the Frontier* is the theme; the **track** (Indie Developer or Startup) is a separate portal choice.
- [ ] **Owner-only declarations:** eligibility and affiliation, team, rights, final terms.
- [ ] **Submission is done only when the portal shows a receipt.**
- [ ] **After 4 November:** rotate the Meta Model API key.
- [ ] **Optional:** one practitioner review, recorded in `model-card.md` as received.
