# Submission: criteria, evidence and the owner's checklist

Status key:
- **verified:** checked in this repository or on the public site.
- **partial:** done, with a stated gap.
- **owner:** needs the owner's action or confirmation; it can't be done from the repository.

## Judging criteria → evidence

The weights below come from the hackathon page as read during the build. Confirm them in the portal.

| Criterion | Evidence | Status |
|---|---|---|
| **Impact (30%)**: a real problem for a real user | **Problem and user:** README *For reviewers* and [`model-card.md`](model-card.md). The user is an agronomy or irrigation research team; the decision is crops and irrigation under a hard water and energy budget, then diagnosing what went wrong. | verified |
| | **One real input:** NASA POWER 2024–25 Al Ain weather (*Real 2024–25 weather* scenario). The file is pinned by SHA-256 and traceable from the `session` ledger entry. | verified |
| | **Validation:** none in the field. ET0 matches FAO-56 example 18 within 3%. No practitioner review yet. | partial |
| **Use of Meta AI (25%)** | **Muse Spark as the scientist** via tool calling (`worldlab/agent.py`). Benchmark v2: 25 Spark seasons, 14/15 faults diagnosed, 0 wrong calls ([`bench/v2`](bench/v2/)). | verified |
| | **SAM 3.1 and Spark vision on drone photos** (`worldlab/perception.py`), with typed outcomes (valid / partial / unavailable / malformed). | verified |
| | **Perception ablation:** the image models did not change diagnosis or harvest on clog and pest cases. Reported as found. | verified |
| | **Muse Glimmer:** adapter only, not run, and labelled that way. | verified (as not demonstrated) |
| **Demo (25%)** | **Recorded season with a seven-step judge walkthrough** (`app/?demo&walkthrough`): spoiler-free by default, evidence links on every step, no overlaps at desktop, laptop and phone widths (`tests/browser/smoke.js`). | verified |
| | **Live season for guests, including the *Unknown challenge*:** the code and tests are in place. **The hosted server is not deployed** because the `HF_TOKEN` secret is missing. | partial, owner |
| | **Video:** script in [`DEMO.md`](DEMO.md). It has to be recorded. | owner |
| **Technical depth (20%)** | **Event-level scoring:** every run is kept with its ledger and manifest, compared on matched farm seeds with bootstrap intervals ([`bench/v2`](bench/v2/), 105 runs). | verified |
| | **Frozen holdout:** committed before any run; 8 unfamiliar cases, including a faulty sensor and an unidentifiable cause ([`bench/holdout`](bench/holdout/)). | verified |
| | **Offline evidence bundle:** a verifier that detects edits, omissions, reordering and truncation (`EvidenceBundleTests`). | verified |
| | **Honest run states:** failed, timeout, cancelled and degraded runs are labelled, with no rewards for incomplete runs (`RunStatusTests`). Budgets and atomic admission are enforced (`LiveAccessTests`). | verified |
| **Honesty of claims** | No benchmark win is claimed: Spark −30.3 people fed against the scripted protocol (95% interval −59.3 to −1.9). The detection delay is stated (20 days in the recorded season). Drone photos are labelled synthetic, and "people fed" is defined as an index. | verified |

## The brief's tasks

| Task | Status | Where |
|---|---|---|
| P0.1 Live backend readiness and states | **partial, owner.** Readiness, guest sessions, atomic admission, budgets and `scripts/check_live.py` are built and tested. The deploy is blocked by the missing `HF_TOKEN`. | `worldlab/server.py`, `.github/workflows/huggingface.yml` |
| P0.2 Honest run status | verified | `RunStatusTests` |
| P0.3 Benchmark scoring and fair comparison | verified | `worldlab/benchscore.py`, `BenchScoreTests`, `docs/bench/v2/` |
| P0.4 Honest Compare | verified | Results › Compare, `experiments.json` schema 2 |
| P0.5 Typed perception and honest recovery | verified | `PerceptionStatusTests`, Incidents panel |
| P1.1 Frozen holdout | verified (one run per case; repeats are future work) | `docs/bench/holdout/` |
| P1.2 Real-data path and limitations | partial: real weather and the model card are done; no practitioner review yet | `worldlab/farm/observed.py`, `docs/model-card.md`, Results › What is real |
| P1.3 Judge walkthrough | verified at desktop, laptop and phone widths in headless Chromium without WebGL. **3D not yet checked on a real GPU.** | `app.js` walkthrough, `tests/browser/smoke.js` |
| P1.4 Offline evidence | verified | `worldlab/dashboard/evidence/`, `scripts/verify_evidence.py` |
| P1.5 Budgets and admission safety | verified | `LiveAccessTests`, `worldlab/csp.py` |
| P1.6 Submission package | partial: the repository side is done; the portal is the owner's | this file |

## Owner's checklist (from the portal: confirm each item there)

Do not rely on this list alone. Open the signed-in portal and check every required field.

- [ ] **Live server:** create a Hugging Face write token and add it as the GitHub Actions secret `HF_TOKEN` (optionally also `MODEL_API_KEY`). Push or re-run *Deploy server to Hugging Face*, then check `https://moamryehia-worldlab.hf.space/api/ready`.
- [ ] **Contributors:** make `main-clean` the history of `main`, either by force-pushing it or by switching the default branch on github.com.
- [ ] **Video:** record from [`DEMO.md`](DEMO.md). Confirm the **actual length limit** in the portal; the 3-minute figure is not verified from participant instructions.
- [ ] **Portal fields:** project name, description, repository link, demo link and video link; any required screenshots.
- [ ] **Track or theme:** choose it in the portal (the README says *Push the Frontier*; confirm it is an accepted track).
- [ ] **Owner-only declarations:** eligibility and affiliation, team members, rights to the submitted work, and the final terms. These are the owner's to read and accept.
- [ ] **Social post:** if required, post it from your own account.
- [ ] **Submission is done only when the portal shows a confirmation or receipt.** Pushing the repository is not submission.
- [ ] **After 4 November:** rotate the Meta Model API key used during the build.
- [ ] **Optional but valuable:** ask one agronomist or irrigation researcher to try the walkthrough. Record their actual feedback in `model-card.md`, or leave the "no review yet" line.
