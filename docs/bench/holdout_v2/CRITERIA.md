# Holdout v2: pre-registered criteria (written before any run)

This suite has eight new farms (seeds 601–608), one hidden challenge each, drawn from the same families as holdout v1
with a new generator seed (20261102). It was frozen after the second-review fixes and before any run on these farms.

## Conditions

All three conditions use Meta perception (SAM 3.1 and Muse Spark vision), the same tools, the same budgets and the same
hard limits. Each runs once per farm.

1. **Muse Spark, new code.** The release under test: multi-start calibration, the nutrient-risk report with a backup
   plan, and escalation after repeated alarms.
2. **Muse Spark, old code.** Commit `8c15a7e`, before those fixes, run from a separate checkout of that commit. Its
   manifests name that commit.
3. **Scripted protocol with RL, new code.** It has fixed rules for the nutrient-risk gate (take the backup if it keeps at
   least 95% of the bad-year result, otherwise accept and record why) and for escalation (re-plan the water first, then
   state the loss).

## Criteria and decision rules

Every number is reported, whichever way it goes. Farms are counted separately from model repeats: here there are 8
farms and 1 repeat each.

**C1. Does the planning fix remove catastrophic seasons?**

- A season is catastrophic when people fed is below 50% of the scripted protocol's result on the same farm.
- Report how many seasons are catastrophic for Spark-old and for Spark-new.
- Report the matched difference in people fed, Spark-new minus Spark-old, with a 95% interval from resampling farms.
- Claim the fix helped only if Spark-new has fewer catastrophic seasons, or the interval is entirely above zero.
  Otherwise report "no measured improvement".

**C2. Is there a measured benefit from Muse Spark over the scripted protocol?** Both run the new code.

Claim an advantage only on one of these:

- the people-fed interval (Spark minus scripted) is entirely above zero;
- strictly fewer wrong findings or actions, with identifiable-fault diagnosis recall not lower;
- strictly more identifiable faults diagnosed with evidence, with wrong findings or actions not higher.

Otherwise report "no measured benefit on this suite". Name the comparator and the sample size with any claim.

**C3. Risk and escalation decisions.**

- For each run, report whether the nutrient-risk gate triggered.
- Report whether the scientist took the backup or accepted the risk, and its stated evidence.
- Report whether the accepted field later failed (yield below 20% of the field's planned P50).
- Report every escalation, with its decision and stated cause.

**Scoring:** scorer 2.1. Diagnosis needs evidence first; premature claims are wrong; follow-up shorter than 30 days is
censored; the unidentifiable case is an escalation.
