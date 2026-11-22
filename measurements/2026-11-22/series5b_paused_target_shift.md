### “put the apple into the bowl” — 20261122-025758-compare
48/48 trials, 8 pairs, 40.0 s simulated per trial, perturbation target_shift, seed 71, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 3/8 | 14%–69% | 0.5 | 3.0 cm | 18.8 cm | 17.0 s | 14.4 | 0.58 s | 33.1 | 42.8 | 0.101 | 40% | 2.7 | 0/0 | no_grasp 4, no_reach 1, success 3 |
| receding-8 | 0/8 | 0%–32% | 0.31 | 2.4 cm | 16.2 cm | – | 100.0 | 0.45 s | 40.0 | 89.2 | 0.059 | 51% | 3.28 | 0/2 | carry_failed 2, pushed 6 |
| receding-16 | 0/8 | 0%–32% | 0.41 | 3.0 cm | 19.2 cm | – | 50.0 | 0.48 s | 40.0 | 66.6 | 0.078 | 36% | 2.13 | 0/3 | carry_failed 1, missed_container 2, no_grasp 4, pushed 1 |
| receding-24 | 2/8 | 7%–59% | 0.78 | 2.5 cm | 15.4 cm | 26.5 s | 31.1 | 0.5 s | 36.6 | 54.2 | 0.083 | 38% | 1.68 | 0/7 | carry_failed 1, missed_container 5, success 2 |
| receding-30 | 3/8 | 14%–69% | 0.66 | 2.4 cm | 12.1 cm | 27.9 s | 23.8 | 0.52 s | 34.9 | 49.3 | 0.091 | 40% | 2.69 | 0/4 | carry_failed 2, missed_container 1, no_grasp 2, success 3 |
| crossfade-24 | 2/8 | 7%–59% | 0.72 | 2.1 cm | 17.0 cm | 26.5 s | 31.2 | 0.5 s | 36.6 | 54.5 | 0.086 | 38% | 1.42 | 0/5 | carry_failed 1, missed_container 4, no_grasp 1, success 2 |

Data checks: none found.

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-24 | 8 | 38% | 25% | 2 | 1 | 1.000 | 0.219 [-0.03, +0.47] | -1.1 cm |
| receding-16 | 8 | 38% | 0% | 3 | 0 | 0.250 | -0.094 [-0.41, +0.19] | -1.0 cm |
| receding-24 | 8 | 38% | 25% | 3 | 2 | 1.000 | 0.281 [-0.06, +0.59] | -1.8 cm |
| receding-30 | 8 | 38% | 38% | 2 | 2 | 1.000 | 0.156 [-0.22, +0.50] | -3.7 cm |
| receding-8 | 8 | 38% | 0% | 3 | 0 | 0.250 | -0.188 [-0.47, +0.06] | -0.5 cm |
