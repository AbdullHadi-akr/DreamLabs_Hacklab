### “put the orange on the plate” — 20261122-014508-compare
32/32 trials, 8 pairs, 40.0 s simulated per trial, perturbation none, seed 52, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 0/8 | 0%–32% | 0.38 | 3.0 cm | 27.8 cm | – | 17.0 | 0.56 s | 40.0 | 51.3 | 0.083 | 47% | 2.75 | 0/4 | carry_failed 4, no_grasp 4 |
| receding-24 | 0/8 | 0%–32% | 0.5 | 2.1 cm | 22.0 cm | – | 34.0 | 0.51 s | 40.0 | 59.6 | 0.107 | 36% | 2.1 | 0/7 | carry_failed 6, missed_container 1, no_grasp 1 |
| receding-30 | 0/8 | 0%–32% | 0.28 | 2.8 cm | 29.5 cm | – | 27.0 | 0.52 s | 40.0 | 56.0 | 0.091 | 41% | 2.46 | 0/2 | carry_failed 2, no_grasp 3, pushed 2, wrong_object 1 |
| crossfade-30 | 0/8 | 0%–32% | 0.47 | 2.8 cm | 22.4 cm | – | 26.5 | 0.52 s | 39.3 | 55.3 | 0.11 | 41% | 1.29 | 0/7 | carry_failed 6, off_table 1, pushed 1 |

Data checks: none found.

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-30 | 8 | 0% | 0% | 0 | 0 | – | 0.094 [+0.00, +0.19] | -5.3 cm |
| receding-24 | 8 | 0% | 0% | 0 | 0 | – | 0.125 [+0.03, +0.25] | -3.7 cm |
| receding-30 | 8 | 0% | 0% | 0 | 0 | – | -0.094 [-0.22, +0.03] | 1.0 cm |
