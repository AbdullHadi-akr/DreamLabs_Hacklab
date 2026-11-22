# Test overview – night of 21/22 Nov 2026

A short summary of all tests with real Dream-1 in the simulator. Details, method and raw data:
[NIGHTLY_REPORT.md](NIGHTLY_REPORT.md) and [`measurements/2026-11-22/`](measurements/2026-11-22/). As a page:
[test-overview.html](test-overview.html).

**Scope:** 397 trials in 23 campaigns, plus camera self-tests, a determinism test and X-Ray analyses. Every comparison
is **paired**: each strategy ran on exactly the same scene. Every trial had 40 s of simulated time.

---

## 1. The strategies

| Strategy | What it does |
|---|---|
| **chunk** | Dream-1 returns 48 steps (2.4 s); all of them are executed, then the next request is sent (previous default) |
| **receding-N** | execute only the first N steps, then ask again |
| **crossfade-N** | ask again every N steps and blend smoothly from the old plan to the new one |
| **ensemble-N** | average all plans that cover a moment, weighted |

---

## 2. Main result: chunk against the others

All campaigns of the night together, only pairs on the same scene.

| Strategy | Pairs | chunk success | Strategy success | Only chunk wins | Only strategy wins | Verdict |
|---|---|---|---|---|---|---|
| **crossfade-30** | 55 | 9 % | **42 %** | 3 | **21** | ✅ **significantly better (p ≈ 0.0003)** |
| receding-24 | 62 | 16 % | 29 % | 8 | 16 | better, not significant (p = 0.15) |
| crossfade-24 | 14 | 29 % | 36 % | 2 | 3 | slightly better, too few pairs |
| receding-30 | 28 | 18 % | 29 % | 3 | 6 | slightly better |
| receding-16 | 33 | 18 % | 9 % | 6 | 3 | ❌ not better |
| crossfade-16 | 16 | 12 % | 0 % | 2 | 0 | ❌ worse |
| ensemble-16 | 16 | 12 % | 0 % | 2 | 0 | ❌ worse |
| receding-8 | 14 | 29 % | 0 % | 4 | 0 | ❌ clearly worse |

**Progress** (0 = nothing achieved, 1 = placed): on average crossfade-30 gets **+0.35** further than chunk (95 %
confidence interval +0.26 to +0.44).

### Apple into the bowl (all trials)

| Strategy | Successes | Rate | Most common failure |
|---|---|---|---|
| chunk | 12 / 68 | 18 % | **not grasped** (46×) |
| receding-24 | 16 / 46 | 35 % | placed next to the bowl (15×) |
| receding-30 | 8 / 20 | 40 % | grasped, then lost (7×) |
| **crossfade-30** | **20 / 40** | **50 %** | placed next to the bowl (11×) |

**Why?** chunk drives 2.4 s without correcting – exactly during the approach, where a correction is needed. That is why
it mostly misses the grasp. crossfade-30 replans every 1.5 s and blends over without a jump.

---

## 3. Confirmation under new conditions (crossfade-30 vs. chunk)

| Condition | chunk | crossfade-30 |
|---|---|---|
| New scenes, apple moved by 2 cm (12 pairs) | 0 / 12 | **6 / 12** |
| Light dimmed by 50 % | 1 / 8 | **4 / 8** |
| Bowl moved by 3 cm | 2 / 8 | **5 / 8** |
| Banana onto the plate | 0 / 7 | **3 / 8** (the only banana successes of the night) |

➡️ **crossfade-30 is now the default in the dashboard.** The 8- and 16-step variants were removed from the menu
because they measured worse; they can still be used by name.

---

## 3a. Joint movement: how smoothly do the arms move?

Medians over all paired trials of the night.

- **Jump:** how much the arm jumps when it switches to a new plan.
- **Jump / step:** the same jump relative to a normal movement step.
- **Jitter:** the share of the movement left over after smoothing over 0.45 s.

| Strategy | Trials | Jump (rad) | Largest jump (rad) | Jump / step | Jitter | Speed (rad/s) | Requests per run |
|---|---|---|---|---|---|---|---|
| **chunk** | 104 | 0.026 | 0.045 | **2.7×** | 42 % | 0.092 | 17 |
| **crossfade-30** | 56 | **0.010** | **0.018** | **1.2×** | 49 % | 0.106 | 27 |
| crossfade-24 | 14 | 0.012 | 0.034 | 1.5× | 35 % | 0.089 | 34 |
| receding-24 | 62 | 0.016 | 0.040 | 1.8× | 36 % | 0.095 | 34 |
| receding-30 | 28 | 0.024 | 0.081 | 2.7× | 40 % | 0.090 | 27 |
| receding-16 | 32 | 0.019 | 0.078 | 2.1× | 35 % | 0.107 | 50 |
| crossfade-16 | 16 | 0.011 | 0.065 | 1.7× | **23 %** | 0.108 | 50 |
| ensemble-16 | 16 | 0.014 | 0.047 | 2.1× | 29 % | 0.088 | 50 |
| receding-8 | 15 | 0.013 | 0.079 | 2.9× | 53 % | 0.060 | 100 |

**crossfade-30 vs. chunk:**

- **Much smoother transitions:** the jump at a plan change is about 60 % smaller. chunk jerks at every boundary (every
  2.4 s) by almost three times a normal step; crossfade-30 by hardly more than a normal step.
- **Slightly more jitter** (49 % vs. 42 %): during the blend the arm follows a mix of two plans.
- **About 15 % faster**, because the arm moves more directly to the target.

**Smoothness and success do not automatically go together.** The smoothest strategy is crossfade-16 (23 % jitter), but
it is not more successful than chunk. Success comes from replanning more often; smoothness comes from the blend.
receding-24 is a compromise: less jitter, smaller transitions and 35 % success.

---

## 4. Prompt variants (apple, 3 trials each)

| Prompt | chunk | receding-24 |
|---|---|---|
| put the apple into the bowl | 0 / 3 | 2 / 3 |
| place the apple in the bowl | 3 / 3 | 1 / 3 |
| could you please pick up the apple and put it into the bowl? | 1 / 3 | 0 / 3 |
| apple -> bowl | 0 / 3 | 0 / 3 |
| put the red fruit into the bowl | 0 / 3 | 1 / 3 |

Re-checked on new scenes: "place the apple in the bowl" with chunk only reached **3 / 8**. No wording is consistently
better; the 3/3 was luck of a single scene.

---

## 5. Other fruit

| Task | Result | Cause |
|---|---|---|
| Orange onto the plate | **0 / 50** with every strategy | slips out of the closed gripper |
| Banana onto the plate | 0 / 31 without crossfade-30, **3 / 8 with crossfade-30** | mostly slips out as well |

This is a physics or grasping problem, not purely a strategy problem.

---

## 6. Camera pipeline

| Test | Result |
|---|---|
| 8 deliberately injected faults (cameras swapped, upside down, colours swapped, frozen, 600 ms delay, black, zoom, duplicate) | ✅ **8 / 8 detected**, with the right camera and fault type |
| Clean runs | ✅ no false alarm, delay 0 ms, 5 frames/s |
| Camera tilted, light dimmed, image noise, camera moved | ✅ images reach the model correctly |
| Does Dream-1 use the cameras? | ✅ yes: blanking one moves the plan by up to 9.5 cm (top) or 5.9 cm (wrists) |

---

## 7. Model X-Ray (why Dream-1 acts as it does)

| Analysis | Result |
|---|---|
| Same request several times | Dream-1 is exactly deterministic (0.0 cm difference) |
| Heatmap "where does it look?" | 78 s, gripper at the apple: the **bowl** and the gripper tip are marked – the first heatmap above chance level. At the second moment (4.5 s) it is still at chance |
| Does it follow the word in the prompt? | shortly before and during the grasp, **no** (0 of 3): it stays with the apple whether the prompt says "banana", "orange" or "bottle" |

---

## 8. Findings and measurement errors fixed

1. **Same scene does not mean same result.** The GPU renders minimally differently (about 0.01 % of the pixels by one
   grey level), and Dream-1 reacts to that. A single trial says little, so every comparison used many pairs.
2. **Artificial delay fixed:** the Dream client replaced the first ~11 steps of every new plan with the old one, even
   though physics pauses during the request.
3. **A hung trial is no longer counted:** one trial hung for about 14 minutes in standby and was wrongly counted as a
   failure. Such trials are now excluded; only this one was affected.
4. **Capacity errors:** when Dream-1 is full, the tool now waits instead of ending the run.
5. **Camera check:** the false "frozen" alarm in dim light is fixed.

---

## 9. Open points

- The **orange** never works, the **banana** only with crossfade-30. Probably friction or grasp position.
- **"Placed next to the bowl"** is the most common remaining failure with crossfade-30.
- **receding-24 vs. crossfade-30** directly has barely been measured (5/12 vs. 6/12). Both are clearly better than chunk.
- Whether Dream-1 uses the object word **early in the approach** is still open.
- The **Dream input check** has to be run by a person (not an agent): `python -m dream.input_check 4932209e541e`
