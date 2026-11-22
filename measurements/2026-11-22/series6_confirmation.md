### “put the apple into the bowl” — 20261122-041418-compare
36/36 trials, 12 pairs, 40.0 s simulated per trial, perturbation target_shift, seed 91, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 0/12 | 0%–24% | 0.27 | 2.8 cm | 19.9 cm | – | 17.0 | 0.59 s | 40.0 | 51.8 | 0.091 | 42% | 2.68 | 0/1 | missed_container 1, no_grasp 10, no_reach 1 |
| receding-24 | 5/12 | 19%–68% | 0.67 | 2.2 cm | 11.9 cm | 22.8 s | 27.8 | 0.54 s | 32.6 | 49.3 | 0.09 | 37% | 1.72 | 0/6 | carry_failed 3, missed_container 1, no_grasp 3, success 5 |
| crossfade-30 | 6/12 | 25%–75% | 0.77 | 2.4 cm | 9.2 cm | 28.6 s | 23.0 | 0.52 s | 33.6 | 47.7 | 0.105 | 51% | 1.15 | 0/8 | carry_failed 1, missed_container 3, no_grasp 1, pushed 1, success 6 |

Data checks: none found.

### “place the apple in the bowl” — 20261122-044420-compare
16/16 trials, 8 pairs, 40.0 s simulated per trial, perturbation target_shift, seed 91, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 3/8 | 14%–69% | 0.53 | 2.5 cm | 17.8 cm | 35.8 s | 16.1 | 0.52 s | 37.7 | 47.9 | 0.091 | 43% | 2.73 | 0/0 | no_grasp 5, success 3 |
| receding-24 | 2/8 | 7%–59% | 0.62 | 1.9 cm | 11.2 cm | 29.8 s | 31.9 | 0.53 s | 37.4 | 56.4 | 0.084 | 38% | 1.74 | 0/6 | carry_failed 4, missed_container 1, pushed 1, success 2 |

Data checks: none found.

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-30 | 12 | 0% | 50% | 0 | 6 | 0.031 | 0.5 [+0.25, +0.69] | -10.6 cm |
| receding-24 | 20 | 15% | 35% | 2 | 6 | 0.289 | 0.275 [+0.09, +0.46] | -6.6 cm |
