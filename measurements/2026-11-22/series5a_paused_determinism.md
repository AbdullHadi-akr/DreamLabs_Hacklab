### “put the apple into the bowl” — 20261122-024427-compare
16/16 trials, 4 pairs, 40.0 s simulated per trial, perturbation none, seed 51, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 1/4 | 5%–70% | 0.44 | 2.8 cm | 16.8 cm | 14.7 s | 14.5 | 0.61 s | 33.7 | 43.8 | 0.096 | 41% | 3.0 | 0/0 | no_grasp 2, pushed 1, success 1 |
| receding-24 | 1/4 | 5%–70% | 0.75 | 2.4 cm | 14.8 cm | 33.7 s | 32.8 | 0.59 s | 38.4 | 60.2 | 0.087 | 37% | 1.67 | 0/4 | carry_failed 1, missed_container 2, success 1 |
| receding-30 | 2/4 | 15%–85% | 0.81 | 2.2 cm | 8.9 cm | 28.6 s | 23.5 | 0.52 s | 34.3 | 48.2 | 0.085 | 43% | 2.88 | 0/2 | carry_failed 1, missed_container 1, success 2 |
| crossfade-30 | 2/4 | 15%–85% | 0.81 | 2.5 cm | 8.5 cm | 26.4 s | 22.8 | 0.51 s | 33.2 | 46.9 | 0.1 | 51% | 1.16 | 0/2 | carry_failed 1, missed_container 1, success 2 |

Data checks: none found.

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-30 | 4 | 25% | 50% | 0 | 1 | 1.000 | 0.375 [+0.12, +0.62] | -2.7 cm |
| receding-24 | 4 | 25% | 25% | 1 | 1 | 1.000 | 0.312 [-0.25, +0.69] | 0.6 cm |
| receding-30 | 4 | 25% | 50% | 0 | 1 | 1.000 | 0.375 [+0.12, +0.62] | -4.2 cm |
