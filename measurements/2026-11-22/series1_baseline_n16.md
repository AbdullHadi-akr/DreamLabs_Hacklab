### “put the banana on the plate” — 20261122-000909-compare
24/24 trials, 6 pairs, 40.0 s simulated per trial, perturbation none, seed 11, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 0/6 | 0%–39% | 0.46 | 2.9 cm | 17.6 cm | – | 17.0 | 0.67 s | 40.0 | 53.8 | 0.093 | 44% | 2.66 | – | carry_failed 5, no_grasp 1 |
| receding-16 | 0/6 | 0%–39% | 0.5 | 2.7 cm | 19.2 cm | – | 50.0 | 0.54 s | 40.0 | 69.8 | 0.124 | 34% | 2.1 | – | carry_failed 6 |
| ensemble-16 | 0/6 | 0%–39% | 0.5 | 2.7 cm | 19.0 cm | – | 50.0 | 0.53 s | 40.0 | 69.8 | 0.1 | 30% | 1.97 | – | carry_failed 6 |
| crossfade-16 | 0/6 | 0%–39% | 0.54 | 2.8 cm | 21.6 cm | – | 50.0 | 0.51 s | 40.0 | 68.4 | 0.109 | 25% | 1.74 | – | carry_failed 5, missed_container 1 |

Data checks: none found.

### “put the apple into the bowl” — 20261122-003526-compare
24/24 trials, 6 pairs, 40.0 s simulated per trial, perturbation none, seed 12, state done.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 2/6 | 10%–70% | 0.71 | 2.5 cm | 11.4 cm | 29.3 s | 15.7 | 0.61 s | 36.4 | 47.8 | 0.096 | 40% | 2.65 | – | carry_failed 1, missed_container 2, no_grasp 1, success 2 |
| receding-16 | 2/6 | 10%–70% | 0.62 | 2.2 cm | 13.3 cm | 35.8 s | 48.5 | 0.58 s | 38.6 | 69.0 | 0.122 | 35% | 2.24 | – | carry_failed 3, pushed 1, success 2 |
| ensemble-16 | 0/6 | 0%–39% | 0.54 | 2.6 cm | 16.2 cm | – | 50.0 | 0.56 s | 40.0 | 70.4 | 0.09 | 29% | 2.31 | – | carry_failed 5, missed_container 1 |
| crossfade-16 | 0/6 | 0%–39% | 0.42 | 2.3 cm | 13.4 cm | – | 50.0 | 0.58 s | 40.0 | 71.2 | 0.102 | 24% | 1.66 | – | carry_failed 4, no_grasp 1, pushed 1 |

Data checks: none found.

### “put the orange on the plate” — 20261122-010128-compare
18/24 trials, 6 pairs, 40.0 s simulated per trial, perturbation none, seed 13, state stopped.

| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chunk | 0/5 | 0%–43% | 0.35 | 3.1 cm | 28.7 cm | – | 17.0 | 0.59 s | 40.0 | 51.8 | 0.084 | 47% | 2.56 | – | carry_failed 2, no_grasp 3 |
| receding-16 | 0/5 | 0%–43% | 0.3 | 2.7 cm | 23.3 cm | – | 40.0 | 0.52 s | 32.0 | 54.5 | 0.121 | 36% | 2.05 | – | carry_failed 3, no_reach 2 |
| ensemble-16 | 0/4 | 0%–49% | 0.19 | 2.8 cm | 28.8 cm | – | 50.0 | 0.53 s | 40.0 | 68.9 | 0.088 | 32% | 2.04 | – | no_grasp 2, pushed 1, wrong_object 1 |
| crossfade-16 | 0/4 | 0%–49% | 0.5 | 2.2 cm | 23.8 cm | – | 50.0 | 0.54 s | 40.0 | 69.2 | 0.102 | 25% | 1.58 | – | carry_failed 4 |

Data checks: 
- trial 18 (receding-16): error: DreamServerError: DreamAPI refused the inference request: DA-2000 NO_CAPACITY (pool_full): Dream-1 is at max capa
- incomplete pairs: [5]

### Pooled over all prompts (pairs with the same prompt and seed)

| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | Δ final distance (median) |
|---|---|---|---|---|---|---|---|---|
| crossfade-16 | 16 | 12% | 0% | 2 | 0 | 0.500 | -0.047 [-0.20, +0.09] | 1.6 cm |
| ensemble-16 | 16 | 12% | 0% | 2 | 0 | 0.500 | -0.094 [-0.20, +0.00] | 1.3 cm |
| receding-16 | 17 | 12% | 12% | 2 | 2 | 1.000 | -0.029 [-0.19, +0.13] | -0.6 cm |
