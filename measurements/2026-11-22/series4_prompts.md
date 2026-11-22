### Series 4: prompt variants (apple, no perturbation, latency client = before the fix)

Campaigns 20261122-021455-prompt_paraphrase (chunk) and 20261122-022626-prompt_paraphrase (receding-24); 3 trials per prompt, identical scene in every trial (variance from render noise and the client smoother).

| Strategy | Prompt | Trials | Success | Progress (mean) | Outcomes |
|---|---|---|---|---|---|
| chunk | put the apple into the bowl | 3 | 0/3 | 0.25 | no_grasp 3 |
| chunk | place the apple in the bowl | 3 | 3/3 | 1.00 | success 3 |
| chunk | could you please pick up the apple and put it into the bowl? | 3 | 1/3 | 0.58 | no_grasp 1, carry_failed 1, success 1 |
| chunk | apple -> bowl | 3 | 0/3 | 0.25 | no_grasp 3 |
| chunk | put the red fruit into the bowl | 3 | 0/3 | 0.42 | missed_container 1, no_grasp 2 |
| receding-24 | put the apple into the bowl | 3 | 2/3 | 0.83 | success 2, carry_failed 1 |
| receding-24 | place the apple in the bowl | 3 | 1/3 | 0.58 | carry_failed 1, success 1, no_grasp 1 |
| receding-24 | could you please pick up the apple and put it into the bowl? | 3 | 0/3 | 0.58 | missed_container 1, carry_failed 2 |
| receding-24 | apple -> bowl | 3 | 0/3 | 0.50 | pushed 1, missed_container 1, carry_failed 1 |
| receding-24 | put the red fruit into the bowl | 3 | 1/3 | 0.75 | carry_failed 1, missed_container 1, success 1 |
