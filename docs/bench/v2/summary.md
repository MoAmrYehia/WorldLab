| condition | attempted | completed | people fed, mean | within limits | diagnosis recall | precision | justified interventions | median days to diagnosis | unrelated alarms | wrong findings/actions | calm when nothing wrong | trait error (all crops) | cost/season (list price) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scripted-rl/meta | 25 | 25 | 471.3 | 25/25 | 15/15 | 15/15 | 15/15 | 15.0 | 1 | 0 | 10/10 | 0.699 | $0.02 |
| scripted-rl/sim | 25 | 25 | 471.3 | 25/25 | 15/15 | 15/15 | 15/15 | 15.0 | 1 | 0 | 10/10 | 0.699 | $0.00 |
| spark/meta | 25 | 25 | 441.1 | 25/25 | 14/15 | 14/14 | 14/15 | 14.0 | 18 | 0 | 10/10 | 0.635 | $1.11 |
| spark/meta-sam | 10 | 10 | 453.2 | 10/10 | 9/10 | 9/9 | 9/10 | 14.0 | 0 | 0 | 0/0 | 0.64 | $1.24 |
| spark/meta-vision | 10 | 10 | 463.2 | 10/10 | 9/10 | 9/9 | 9/10 | 14.0 | 0 | 0 | 0/0 | 0.613 | $1.07 |
| spark/none | 10 | 10 | 457.2 | 10/10 | 9/10 | 9/9 | 9/10 | 14.0 | 0 | 0 | 0/0 | 0.621 | $1.01 |

Matched differences in people fed against `scripted-rl/meta` (same farm seed and hidden events; 95% interval from resampling farm seeds):

| condition | pairs | farm seeds | mean difference | 95% interval | ahead in |
|---|---|---|---|---|---|
| scripted-rl/sim | 25 | 5 | +0.0 | [0.0, 0.0] | 0/25 |
| spark/meta | 25 | 5 | -30.3 | [-59.3, -1.9] | 9/25 |
| spark/meta-sam | 10 | 5 | -27.7 | [-51.6, -3.7] | 3/10 |
| spark/meta-vision | 10 | 5 | -17.7 | [-36.4, -0.3] | 3/10 |
| spark/none | 10 | 5 | -23.7 | [-45.3, -4.9] | 3/10 |
