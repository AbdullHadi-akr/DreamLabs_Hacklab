### “put the apple into the bowl” — 20261122-003735-compare
30/30 trials, 6 pairs, 40.0 s simulated per trial, perturbation none, seed 21, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 1/6 | 3%–56% | 0.33 | 2.6 cm | 20.1 cm | 17.0 s | 15.5 | 0.57 s | 36.2 | 46.5 | 0.094 | 41% | 2.75 | 0/0 | no_grasp 4, no_reach 1, success 1 |
| receding-8 | 0/6 | 0%–39% | 0.12 | 13.6 cm | 20.7 cm | – | 100.0 | 0.55 s | 40.0 | 98.5 | 0.054 | 72% | 2.48 | 0/0 | no_grasp 3, no_reach 3 |
| receding-24 | 4/6 | 30%–90% | 0.83 | 1.9 cm | 5.8 cm | 17.8 s | 23.7 | 0.6 s | 27.5 | 43.1 | 0.106 | 35% | 1.99 | 0/2 | missed_container 1, no_grasp 1, success 4 |
| crossfade-8 | 0/6 | 0%–39% | 0.38 | 2.6 cm | 18.8 cm | – | 100.0 | 0.56 s | 40.0 | 99.2 | 0.082 | 27% | 1.64 | 0/2 | carry_failed 1, missed_container 1, no_grasp 4 |
| crossfade-24 | 3/6 | 19%–81% | 0.83 | 2.1 cm | 9.2 cm | 33.7 s | 29.3 | 0.6 s | 34.4 | 53.6 | 0.107 | 28% | 1.57 | 0/3 | carry_failed 1, missed_container 2, success 3 |

Data checks: none found.

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-24 | 6 | 17% | 50% | 0 | 2 | 0.500 | 0.5 [+0.29, +0.67] | -8.2 cm |
| crossfade-8 | 6 | 17% | 0% | 1 | 0 | 1.000 | 0.042 [-0.29, +0.33] | -1.3 cm |
| receding-24 | 6 | 17% | 67% | 0 | 3 | 0.250 | 0.5 [+0.21, +0.79] | -11.3 cm |
| receding-8 | 6 | 17% | 0% | 1 | 0 | 1.000 | -0.208 [-0.54, +0.00] | 0.2 cm |
