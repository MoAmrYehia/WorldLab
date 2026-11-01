# Provenance of the benchmark v2 runs

Each manifest records the commit it was planned at (`source_commit`), whether the `worldlab/` tree had uncommitted
changes (`source_dirty`), and the SHA-256 of the system prompt and the tool schema the scientist saw.

| runs | condition | source_commit | source_dirty | prompt / tool-schema hashes |
|---|---|---|---|---|
| 25 | Muse Spark, Meta perception | `5498e84` | **true** | `3cbd1503…` / `c2604653…` |
| 25 | scripted + RL, Meta perception | `5498e84` | **true** | same |
| 25 | scripted + RL, simulator truth | `53e41d7` | false | same |
| 30 | Muse Spark ablations (none, SAM only, vision only) | `53e41d7` | false | same |

## The 50 runs marked dirty

These finished between 06:58 and 08:28 UTC on 1 November; the batch was planned from commit `5498e84` plus uncommitted work, before that work was committed as `f3406ee` (06:58:43 UTC). The exact dirty tree
was not archived, so these runs are **provenance-limited**: the named commit alone does not reproduce them. They are not
relabelled as running at a later commit.

What can be established, and how:

1. **The uncommitted work was committed while the batch ran.** `bench2.py` and `benchscore.py`, which the
   batch itself ran, do not exist at `5498e84`; they first appear in `f3406ee` (committed 06:58 UTC). So the batch ran
   a working tree that included at least those files.
2. **No code the runs execute changed after that commit.** `git diff f3406ee 53e41d7` over `worldlab/farm`,
   `worldlab/agent.py`, `worldlab/lab.py`, `worldlab/perception.py`, `worldlab/llm.py`, `worldlab/bench2.py` and
   `worldlab/benchscore.py` is empty. The changes between those commits are in the server, the web app and the evidence
   bundle.
3. **The prompt and tool schema are identical** to the clean runs (hashes above).
4. **Behaviour check:** the scripted protocol is deterministic for a farm seed. All 25 dirty scripted runs match their
   clean reruns at `53e41d7` exactly, in people fed and in the full event score. (Scripted decisions do not depend on
   perception, so the clean reruns used simulator truth.)

The Muse Spark runs can't be checked the same way, because model sampling varies between runs. Treat the 25 Spark runs
with Meta perception as provenance-limited: the prompt, tools and run-relevant code are very probably those of
`f3406ee`/`53e41d7`, but not verified byte for byte.

## Scoring versions

All runs were rescored from their archived ledgers with scorer 2.1 (`scripts/rescore.py`). Each ledger is checked
against its manifest hash before rescoring, and the score each run was first published with is kept in the manifest as
`score_v2_0`. Scorer 2.1 changes four things:

- evidence must come before diagnosis credit;
- premature claims count as wrong;
- too little follow-up is reported as censored rather than as success;
- alarms are attributed by signal.

The unidentifiable case is now scored as an escalation, not a diagnosis. The v2 headline numbers did not change.
