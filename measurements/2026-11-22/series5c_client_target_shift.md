### “put the apple into the bowl” — 20261122-034547-compare
24/24 trials, 8 pairs, 40.0 s simulated per trial, perturbation target_shift, seed 71, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 1/8 | 2%–47% | 0.31 | 3.0 cm | 20.4 cm | 35.7 s | 16.8 | 0.62 s | 39.5 | 51.6 | 0.098 | 40% | 2.67 | 0/0 | no_grasp 6, no_reach 1, success 1 |
| receding-16 | 1/8 | 2%–47% | 0.53 | 2.2 cm | 12.6 cm | 29.6 s | 48.5 | 0.61 s | 38.7 | 70.7 | 0.107 | 36% | 2.36 | 0/5 | carry_failed 4, missed_container 1, no_grasp 1, pushed 1, success 1 |
| receding-24 | 2/8 | 7%–59% | 0.75 | 2.2 cm | 12.7 cm | 13.7 s | 28.4 | 0.57 s | 33.4 | 51.5 | 0.114 | 34% | 2.11 | 0/5 | carry_failed 2, missed_container 4, success 2 |

Data checks: none found.

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| receding-16 | 8 | 12% | 12% | 1 | 1 | 1.000 | 0.219 [-0.09, +0.47] | -8.3 cm |
| receding-24 | 8 | 12% | 25% | 1 | 2 | 1.000 | 0.438 [+0.22, +0.66] | -5.9 cm |
