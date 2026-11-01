Scorer 2.1. Outcomes are over completed runs; 'attempted' counts every run.

| condition | attempted | completed | people fed, mean | within limits | diagnosed (with evidence) | precision | justified interventions | correct guesses without evidence | median days to diagnosis | no re-alarm in 30 days | unrelated alarms | wrong findings/actions (premature) | unidentifiable cause escalated | calm when nothing wrong | trait error (all crops) | cost/season (list price) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted-rl/meta | 8 | 8 | 483.1 | 8/8 | 4/6 | 4/5 | 4/6 | 0 | 13.5 | 3/4 observed | 7 | 1 (0) | 1/1 | 2/2 | 0.606 | $0.08 |
| spark/meta | 8 | 8 | 474.4 | 8/8 | 4/6 | 4/7 | 4/6 | 0 | 13.5 | 4/4 observed | 2 | 3 (0) | 1/1 | 2/2 | 0.543 | $1.25 |

Matched differences in people fed against `scripted-rl/meta` (same farm seed and hidden events; 95% interval from resampling farm seeds):

| condition | pairs | farm seeds | same realized events | event landed elsewhere | mean difference | 95% interval | ahead in |
|---|---|---|---|---|---|---|---|
| spark/meta | 8 | 8 | 7 | 1 | -8.7 | [-31.8, 11.2] | 3/8 |

A hidden event's field is chosen from the fields growing a crop on that day, so it can depend on the scientist's plan: 'event landed elsewhere' pairs are matched by farm, scenario and onset, not by the exact field.
