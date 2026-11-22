### “put the apple into the bowl” — 20261122-051003-compare
16/16 trials, 8 pairs, 40.0 s simulated per trial, perturbation light_dim, seed 111, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 1/8 | 2%–47% | 0.41 | 2.9 cm | 19.9 cm | 38.5 s | 17.0 | 0.58 s | 39.8 | 51.7 | 0.096 | 41% | 2.65 | 0/1 | missed_container 1, no_grasp 4, pushed 2, success 1 |
| crossfade-30 | 4/8 | 22%–78% | 0.84 | 2.2 cm | 9.1 cm | 30.8 s | 24.0 | 0.58 s | 35.4 | 51.5 | 0.108 | 52% | 1.14 | 0/6 | carry_failed 1, missed_container 3, success 4 |

Data checks: none found.

### “put the apple into the bowl” — 20261122-052404-compare
16/16 trials, 8 pairs, 40.0 s simulated per trial, perturbation container_shift, seed 121, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 2/8 | 7%–59% | 0.56 | 2.4 cm | 18.6 cm | 22.9 s | 15.4 | 0.56 s | 35.7 | 46.2 | 0.096 | 41% | 2.9 | 0/2 | missed_container 2, no_grasp 4, success 2 |
| crossfade-30 | 5/8 | 31%–86% | 0.88 | 2.3 cm | 6.7 cm | 22.6 s | 18.9 | 0.55 s | 27.5 | 39.2 | 0.123 | 50% | 1.13 | 0/3 | carry_failed 1, missed_container 2, success 5 |

Data checks: none found.

### “put the banana on the plate” — 20261122-053534-compare
16/16 trials, 8 pairs, 40.0 s simulated per trial, perturbation target_shift, seed 101, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 0/7 | 0%–35% | 0.46 | 2.6 cm | 16.5 cm | – | 17.0 | 0.57 s | 40.0 | 53.0 | 0.084 | 47% | 2.88 | 0/4 | carry_failed 6, no_grasp 1, pushed 1 |
| crossfade-30 | 3/8 | 14%–69% | 0.69 | 2.6 cm | 20.0 cm | 31.5 s | 24.5 | 0.55 s | 36.3 | 54.5 | 0.103 | 49% | 1.23 | 0/2 | carry_failed 5, success 3 |

Data checks: 
- trial 11 (chunk): round trip 853.73 s, far above the rest (median 0.57 s)
- trial 11 (chunk): 5142.2 s wall time, 52 s typical

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-30 | 23 | 13% | 52% | 3 | 12 | 0.035 | 0.337 [+0.18, +0.48] | -10.0 cm |
