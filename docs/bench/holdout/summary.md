| condition | attempted | completed | people fed, mean | within limits | diagnosis recall | precision | justified interventions | median days to diagnosis | unrelated alarms | wrong findings/actions | calm when nothing wrong | trait error (all crops) | cost/season (list price) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted-rl/meta | 8 | 8 | 483.1 | 8/8 | 5/7 | 5/6 | 5/7 | 15.0 | 7 | 1 | 2/2 | 0.606 | $0.10 |
| spark/meta | 8 | 8 | 474.4 | 8/8 | 5/7 | 5/8 | 5/7 | 15.0 | 2 | 3 | 2/2 | 0.543 | $1.20 |

Matched differences in people fed against `scripted-rl/meta` (same farm seed and hidden events; 95% interval from resampling farm seeds):

| condition | pairs | farm seeds | mean difference | 95% interval | ahead in |
|---|---|---|---|---|---|
| spark/meta | 8 | 8 | -8.7 | [-31.8, 11.2] | 3/8 |
