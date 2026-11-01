Scorer 2.1. Outcomes are over completed runs; 'attempted' counts every run.

| condition | attempted | completed | people fed, mean | within limits | diagnosed (with evidence) | precision | justified interventions | correct guesses without evidence | median days to diagnosis | no re-alarm in 30 days | unrelated alarms | wrong findings/actions (premature) | unidentifiable cause escalated | calm when nothing wrong | trait error (all crops) | cost/season (list price) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted-rl/meta | 25 | 25 | 471.3 | 25/25 | 15/15 | 15/15 | 15/15 | 0 | 15.0 | 15/15 observed | 1 | 0 (0) | – | 10/10 | 0.699 | $0.02 |
| scripted-rl/sim | 25 | 25 | 471.3 | 25/25 | 15/15 | 15/15 | 15/15 | 0 | 15.0 | 15/15 observed | 1 | 0 (0) | – | 10/10 | 0.699 | $0.00 |
| spark/meta | 25 | 25 | 441.1 | 25/25 | 14/15 | 14/14 | 14/15 | 0 | 14.0 | 14/14 observed | 18 | 0 (0) | – | 10/10 | 0.635 | $1.11 |
| spark/meta-sam | 10 | 10 | 453.2 | 10/10 | 9/10 | 9/9 | 9/10 | 0 | 14.0 | 9/9 observed | 0 | 0 (0) | – | 0/0 | 0.64 | $1.24 |
| spark/meta-vision | 10 | 10 | 463.2 | 10/10 | 9/10 | 9/9 | 9/10 | 0 | 14.0 | 7/8 observed | 0 | 0 (0) | – | 0/0 | 0.613 | $1.07 |
| spark/none | 10 | 10 | 457.2 | 10/10 | 9/10 | 9/9 | 9/10 | 0 | 14.0 | 9/9 observed | 0 | 0 (0) | – | 0/0 | 0.621 | $1.01 |

Matched differences in people fed against `scripted-rl/meta` (same farm seed and hidden events; 95% interval from resampling farm seeds):

| condition | pairs | farm seeds | same realized events | event landed elsewhere | mean difference | 95% interval | ahead in |
|---|---|---|---|---|---|---|---|
| scripted-rl/sim | 25 | 5 | 25 | 0 | +0.0 | [0.0, 0.0] | 0/25 |
| spark/meta | 25 | 5 | 23 | 2 | -30.3 | [-59.3, -1.9] | 9/25 |
| spark/meta-sam | 10 | 5 | 7 | 3 | -27.7 | [-51.6, -3.7] | 3/10 |
| spark/meta-vision | 10 | 5 | 7 | 3 | -17.7 | [-36.4, -0.3] | 3/10 |
| spark/none | 10 | 5 | 7 | 3 | -23.7 | [-45.3, -4.9] | 3/10 |

A hidden event's field is chosen from the fields growing a crop on that day, so it can depend on the scientist's plan: 'event landed elsewhere' pairs are matched by farm, scenario and onset, not by the exact field.
