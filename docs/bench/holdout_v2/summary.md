Scorer 2.1. Outcomes are over completed runs; 'attempted' counts every run.

| condition | attempted | completed | people fed, mean | within limits | diagnosed (with evidence) | precision | justified interventions | correct guesses without evidence | median days to diagnosis | no re-alarm in 30 days | unrelated alarms | wrong findings/actions (premature) | unidentifiable cause escalated | calm when nothing wrong | trait error (all crops) | cost/season (list price) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted-rl/meta (new code) | 8 | 8 | 565.5 | 8/8 | 5/6 | 5/5 | 5/6 | 0 | 14.0 | 3/3 observed | 0 | 0 (0) | 1/1 | 2/2 | 0.568 | $0.03 |
| spark/meta (new code) | 8 | 8 | 550.2 | 8/8 | 4/6 | 4/4 | 4/6 | 0 | 13.0 | 2/2 observed | 0 | 0 (0) | 1/1 | 2/2 | 0.516 | $1.16 |
| spark/meta (old code) | 8 | 8 | 547.0 | 8/8 | 4/6 | 4/6 | 4/6 | 0 | 13.0 | 3/3 observed | 3 | 2 (0) | 1/1 | 2/2 | 0.52 | $1.17 |

Matched differences in people fed against `scripted-rl/meta (new code)` (same farm seed and hidden events; 95% interval from resampling farm seeds):

| condition | pairs | farm seeds | same realized events | event landed elsewhere | mean difference | 95% interval | ahead in |
|---|---|---|---|---|---|---|---|
| spark/meta (new code) | 8 | 8 | 6 | 2 | -15.3 | [-34.0, 5.6] | 2/8 |
| spark/meta (old code) | 8 | 8 | 7 | 1 | -18.5 | [-41.7, 3.2] | 2/8 |

A hidden event's field is chosen from the fields growing a crop on that day, so it can depend on the scientist's plan: 'event landed elsewhere' pairs are matched by farm, scenario and onset, not by the exact field.
