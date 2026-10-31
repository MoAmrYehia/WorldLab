# Audit response checklist (30 October 2026)

Response to the detailed audit of snapshot `ec95a56`. **Tested** means an automated check (Python suite in `tests/test_worldlab.py`, browser checks in `tests/browser/smoke.js`, both run in CI before publishing). **Seen** means inspected in screenshots of the generated site in a headless browser without WebGL (2D fallback). **Unverified** means not exercised in this round.

| ID | Finding | Status | Evidence |
|---|---|---|---|
| F01 | Landing results empty without WebGL | Done | Results load before the renderer; scene errors fall back to a still image. Tested (smoke: landing numbers), seen. |
| F02 | Features unreachable on narrow screens | Done | Bottom navigation below 1020 px; transport metrics replace the impact panel below 760 px; overlay selector in settings. Tested at 1440, 768 and 390 px; seen at 360 and 1024 px. |
| F03 | Planner offers "Start" when it can't run | Done | Preview banner before any choice; button says "Save draft" or "Sign up to run this plan"; drafts in local storage. Tested (banner, draft survives reload). |
| F04 | Plan and ledger screens unreachable | Done | Plan destination (season plan, plan history), Agent > Audit ledger with search, paging and payloads. Tested (all destinations open). |
| F05 | "25 farms" overstates the sample | Done | "25 farm-scenarios (5 farm seeds × 5 scenarios)", scripted-agent identity, links to method and raw runs; README and landing. Seen. |
| F06 | No execution-level budget cut-off | Done | `cap_to_budget` (proportional curtailment) in the real farm, both controllers and RL imagined seasons; curtailment logged; `budget_mode` on runs; benchmark rerun under hard budget (25/25 within limits per agent). Tested (`HardBudgetTests`). |
| F07 | 27/28 January discrepancy | Done | One calendar; anomalies dated by measurement day, actions by action day, both labelled. Tested (smoke: investigation and activity agree). |
| F08 | "Crop health 101%" during a salinity alarm | Done | Renamed "Canopy vs model"; salinity-over-threshold and alarm warnings stay visible on every metric. Seen. |
| F09 | Strategize/Harvest incomplete for a finished season | Done | Required, optional, stretch and not-applicable objectives; outcome line. Tested (`test_delegated_and_fault_free_seasons_complete_coherently`). |
| F10 | 0.0 yields without explanation | Done | `<0.1` formatting; field soil and starting salinity; warnings with computed reasons (heat at flowering, root-zone salinity) and better fits; "salinity threshold" wording. Tested (maize on F6 warning). |
| F11 | RL "beats the rule" oversimplified | Done | Reward, deployment criterion, sample counts and seeds shown; tradeoff sentence built from the actual comparison; lifecycle status. Seen. |
| F12 | Results not reopenable | Done | Harvest report in Results and in the transport bar; opens on direct seek to the end. Tested (report after seek and after closing). |
| F13 | Undated evidence; "Live" during replay | Done | Capture dates and age on drone images and diagnoses, "historical evidence" label; camera labelled "3D camera at replay time" or "Live simulated camera". Seen. |
| F14 | Deploy without tests | Done | Publish job runs the Python tests, regenerates `docs/` from canonical sources, runs browser checks, then publishes; server deploy runs the tests first. |

## Screens

| Screen | Implemented | Tested | Unverified |
|---|---|---|---|
| Landing | Results first, still-image fallback, primary demo action, provenance, five linked steps with method details, "What can I control?", people-fed definition, calendar table with dates, corrected benchmark | Numbers, demo link | 3D flyover after these changes on a real GPU |
| Navigation and layout | Six destinations with URL state and Back, run header, transport bar, bottom navigation, focus return, tab semantics | All destinations at three widths, Back | Screen readers |
| Farm (3D/2D) | 2D field map without WebGL, follow-events setting, disabled camera controls in 2D | 2D path | 3D rendering, frame rate, touch gestures on devices |
| Planner | Preview mode, drafts, undo, clear, suitability, summary, capability-aware agent list | Preview banner, warning, draft | Live start with an account (needs the hosted server) |
| Missions | Objective kinds, outcome, links to views | Mission outcomes in Python | — |
| Impact | Planned/projected/realised, nutrient breakdown, used/remaining/forecast, budget notes | — | Live forecast updates |
| Field analytics and inspector | Canopy vs model, warnings, latest reading with band, thresholds, keyboard charts, CSV export, dated drone evidence | — | Depth selector and field comparison (not built) |
| Timeline and activity | Event marks as buttons, measurement/action dates, previous/next event, jump to incident/harvest, date scrubber | Date consistency, no future leak on seek back | Activity filters (not built) |
| Drone feed | Replay/live labels, unavailable state, dated frames with age, full retained history strip | — | Segmentation layers (not built) |
| Research | Trial summary and expandable rows, trait values with units and identification, RL criterion and tradeoff | — | User-proposed experiments (not built) |
| Incidents | List with status, connected steps, recovery check and chart, hidden-cause reveal after the season; human decision mode | Human decision logic (Python) | Human decision panel in a live browser session |
| Agent | Decision record with filters and raw calls, component lifecycle, developer note, searchable ledger | — | Ledger verification for replays (recordings omit entries; verify live runs) |
| Results | Verdict, coverage, planned vs realised, soil start and end, story with links, next steps, JSON/CSV/HTML export, compare, costs and emissions, branch, next season, share | Report reachability, compare, costs | Branch and share buttons from a live browser session |
| Accounts | Capability check with timeouts, draft survives redirects | Capabilities endpoint (Python) | Password reset, account export and deletion (not built) |

## P2 features (31 October 2026)

| Feature | Status | Evidence |
|---|---|---|
| Weather and forecast workspace | Done | Weather tab in the dock: observed max/min temperature, ET₀ and rain, the latest 7-day forecast (dashed, with issue date), heat limits of crops flowering now and forecast heat risks. Forecasts are published weekly and are deterministic per issue day. Tested (smoke: weather tab). |
| Branch a season into a controlled experiment | Done | `POST /api/runs/ID/branch` reruns a finished season with one change (controller, hidden events, a field's crop, farm seed, decision mode), linked to its parent; Results > Compare pairs them. The recorded season ships four paired experiments (`experiments.json`, built by `scripts/build_experiments.py`). Full reruns, not mid-season checkpoints. Tested (`P2Tests`, smoke: compare). |
| Scenario library and difficulty | Done | Seven scenarios in `worldlab/scenarios.py`; the public list hides the event schedule. Tested. |
| Human decision mode | Done | Pauses at each alarm to choose the first test and asks before repairs and pest control; 15-minute timeout falls back to the scientist's choice; requests and answers are ledger entries with override flags. Tested (validation, timeout, ledger chain). Live use unverified in a browser. |
| Multi-season soil carryover | Done (salt only) | `POST /api/runs/ID/next` starts from the true end-of-season soil salinity; soil water and nitrogen start fresh and this is stated. Tested (settings carry the saved soil; recorded experiment matches end and start). |
| Economics and sustainability | Done | Results > Costs and emissions: blank, editable prices and emission factor kept in the browser; cost and CO₂ per person fed from the season's actual quantities (`result.quantities`). No prices shipped. Tested (smoke: unpriced start, priced total). |
| Farm/scenario editor | Done | Planner > Farm and scenario: seed, water quota, energy budget, starting salinity; server-side bounds (`EDITOR_RANGES`); clients can't set soil or parent runs. Tested. |
| Shareable scientific report | Done | Self-contained HTML report download; `POST /api/runs/ID/share` creates an opt-in public read-only link (`?shared=TOKEN`). Tested (share, public fetch, bad token). |

## Not done in this round (P2 or later)

Branching from exact mid-season checkpoints, nitrogen carryover, password recovery, soil-depth selector, field comparison view, activity filters, segmentation layers, signed ledger checkpoints, and a move from bearer tokens to same-origin cookies for a public deployment.
