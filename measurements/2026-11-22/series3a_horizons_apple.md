### “put the apple into the bowl” — 20261122-011305-compare
32/32 trials, 8 pairs, 40.0 s simulated per trial, perturbation none, seed 51, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 1/8 | 2%–47% | 0.34 | 2.7 cm | 20.5 cm | 16.9 s | 15.9 | 0.56 s | 37.1 | 47.8 | 0.099 | 40% | 2.75 | 0/0 | no_grasp 7, success 1 |
| receding-24 | 2/8 | 7%–59% | 0.59 | 2.1 cm | 17.8 cm | 21.8 s | 30.2 | 0.54 s | 35.4 | 53.7 | 0.109 | 34% | 1.97 | 0/2 | carry_failed 1, missed_container 2, no_grasp 3, success 2 |
| receding-30 | 3/8 | 14%–69% | 0.72 | 2.1 cm | 11.6 cm | 25.1 s | 23.4 | 0.53 s | 34.5 | 48.8 | 0.102 | 37% | 2.81 | 0/6 | carry_failed 4, missed_container 1, success 3 |
| crossfade-30 | 3/8 | 14%–69% | 0.75 | 2.2 cm | 11.3 cm | 24.0 s | 22.5 | 0.53 s | 32.9 | 46.5 | 0.108 | 45% | 1.17 | 0/5 | carry_failed 3, missed_container 2, success 3 |

Data checks: none found.

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-30 | 8 | 12% | 38% | 0 | 2 | 0.500 | 0.406 [+0.25, +0.56] | -8.8 cm |
| receding-24 | 8 | 12% | 25% | 1 | 2 | 1.000 | 0.25 [-0.09, +0.53] | -2.4 cm |
| receding-30 | 8 | 12% | 38% | 1 | 3 | 0.625 | 0.375 [+0.12, +0.62] | -9.2 cm |
