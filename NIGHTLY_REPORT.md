# Nightly Report – 21/22 Nov 2026

Measured on branch `feature/inference-strategies` (now merged into `main`). Every run used real Dream-1
(`dreamlabs/dream-1-beta`) in the MuJoCo YAM simulator. Raw data, plans, logs and analyses are in
[`measurements/2026-11-22/`](measurements/2026-11-22/). The full campaigns (one row per trial with all metrics) are in
`measurements/2026-11-22/campaigns/`.

Scope:
- 23 campaigns with 397 trials. 16 of them are paired strategy comparisons, and 14 of those are fully analysed.
- Camera self-tests, a determinism test and three X-Ray analyses (about 700 further Dream-1 requests in total).
- Time window: 00:09–07:30.

## Summary

1. **The camera pipeline is correct.** The new camera check ("Cameras" tab) compares every image sent to Dream-1 with
   the rendered ground truth. On real Dream-1:
   - It caught 8 of 8 injected faults: swapped wrists, duplicate camera, upside down, BGR, frozen, 600 ms delay, black,
     zoom.
   - Clean runs raised no false alarm (lag median 0 ms, 5.0 fps).
   - Dream-1 uses the cameras. Blanking one moves the plan by up to 9.5 cm (overhead) or 5.9 cm (wrists). How much
     each camera matters depends on the moment (right wrist 0.7–5.6 cm).
2. **A measurement error in the simulator loop was found and fixed** (artificial latency, I3). The Dream client replaced
   the first ~11 rows of every new chunk with the old plan, because it assumes the robot keeps moving during a request;
   in the simulator, physics pauses. Two further measurement errors were fixed as well (I8, I9).
3. **Chunk vs. crossfade/receding – a clear result:**
   - On identical scenes, `crossfade-30` beats the full 48-row chunk in **21 pairs, the chunk wins only 3** (55 pairs,
     exact McNemar **p ≈ 0.0003**; Δ progress **+0.35 [+0.26, +0.44]**).
   - Apple, unpaired: chunk 12/68 (18 %), crossfade-30 20/40 (50 %).
   - The full chunk almost always fails **before the grasp**: 46 of 68 apple trials were "not grasped".
   - The result held up in every confirmation run:

     | Condition | chunk | crossfade-30 |
     |---|---|---|
     | Fresh scenes (series 6) | 0/12 | 6/12 |
     | Dimmed light | 1/8 | 4/8 |
     | Moved bowl | 2/8 | 5/8 |
     | Banana, which never succeeded before | 0/7 | 3/8 |

   - `receding-24` is better too (+0.30 [+0.19, +0.40], 62 pairs). Short horizons (8, 16) and the ensemble are the same
     or worse.
   - → **New dashboard default: `crossfade-30`** (I7).
4. **Most important methodological finding:** repeats of the same scene are *not* identical.
   - Cause: GPU render noise. About 0.01 % of the pixels differ by one grey level between renders.
   - Dream-1 itself is deterministic (same request → identical plan), but it reacts to this invisible noise with up to
     0.03 rad in its first plan. After that the runs diverge chaotically.
   - Consequence: a single scene is often a coin flip, so never optimise on single trials (which is how everything here
     was evaluated).
5. **Main open problems:**
   - The orange never succeeds in any configuration (0/50), and the banana only with crossfade-30 (3/8). Otherwise the
     object slips out of the closed gripper ("slipped", not "released").
   - With crossfade/receding the main remaining failure is "placed next to the container".

## What was built

| Feature | Files | Purpose |
|---|---|---|
| Inference strategies | `dreamtool/inference.py`, runner, dashboard "Execution" | chunk, receding-N, ensemble-N (ACT weights), crossfade-N; the gripper always follows the newest plan |
| Strategy A/B | `dashboard/extensions/robustness/compare.py` | paired comparison on identical scenes: exact McNemar, bootstrap CI, jitter share, seam ratio |
| Drop analysis | `robustness/monitor.py` | tells "released" (gripper opens) from "slipped out" |
| Model X-Ray | `dreamtool/xray.py`, "X-Ray" tab | planned paths (FK), intent text, RISE heatmaps against a chance level, language probe |
| Camera check | `dreamtool/camcheck.py`, "Cameras" tab | live check of every image sent, self-test with 8 faults, "does Dream-1 use the camera?" |
| Retry at capacity | `dreamtool/runner.py` | DA-2000 `pool_full` is waited out for up to 180 s instead of ending the run |
| Latency fix | `dreamtool/runner.py` (`latency="paused"`) | see I3 |
| Measurement tools | `measurements/analyze.py`, `measurements/pool.py` | tables per campaign / across all campaigns |

Tests: 188 pass on `main` (`python -m pytest`).

## Method

- **Metrics per trial:**
  - Success (simulator check).
  - Progress 0–1: reached 0.25 / grasped 0.5 / carried 0.75 / placed 1.
  - Closest reach, final distance object–container, time to success (simulated time).
  - Number of requests, RTT, simulated and wall time.
  - Joint speed, jitter share (residual after a 9-step mean), seam ratio (jump at chunk boundaries / typical step).
  - Drops, outcome class.
- **Budget:** 40 s of simulated time per trial (800 control steps of 50 ms), independent of network time.
- **Pairing:** in compare mode every strategy runs on exactly the same scene (same seed, same perturbation).
  Statistics: exact McNemar for success, bootstrap CI for Δ progress, Wilson CI for rates.
- **Data check after every series:** `analyze.py` flags error trials (e.g. pool_full), incomplete pairs and
  implausible values. Error trials are never counted as model failures.
- **Sequential:** after the `pool_full` aborts of the first hour, all measurements run one after another in one
  session.

## Experiments and results

### Camera pipeline

| Test | Result |
|---|---|
| Self-test on real Dream-1 (8 faults) | 8/8 detected, camera and fault type named correctly; delay measured as 525 ms and 600 ms |
| Clean run | all three cameras "ok", match ≥ 0.998, lag median 0 ms, 5.0 fps |
| camera_tilt 0/4/8°, light_dim 0/50/75 %, image_noise 0/10/20 σ, camera_shift 0/4 cm | pipeline correct under every condition (match ≥ 0.998, lag 0). The only false alarm was "frozen" at 75 % dimming → fixed (I1); repeat 2×0 % and 2×75 %: all ok |
| Under strategies chunk / receding-8 / crossfade-8 | nothing unusual |
| "Does Dream-1 use the cameras?" (apple, three moments) | Blanking top 4.13 / 2.88 / 9.45 cm, left 5.87 / 5.94 / 3.50 cm, right 1.46 / 5.56 / 0.70 cm; swapping the wrists 2.81 / 6.56 / 2.02 cm. Overhead and left wrist (the grasping arm) always matter; the right wrist only at some moments |

Robustness of the *model* to the perturbations, from 1–2 trials each (hints only): tilting the camera by 8° and moving
it by 4 cm break the apple task; dimming and image noise up to 20 σ show no clear effect.

### Series 1 – baseline (before the latency fix), 3 prompts × 4 strategies × 6 pairs

[`series1_baseline_n16.md`](measurements/2026-11-22/series1_baseline_n16.md)

| Prompt | chunk | receding-16 | ensemble-16 | crossfade-16 |
|---|---|---|---|---|
| apple → bowl | 2/6 | 2/6 | 0/6 | 0/6 |
| banana → plate | 0/6 | 0/6 | 0/6 | 0/6 |
| orange → plate | 0/5 | 0/5 | 0/4 | 0/4 |

The orange campaign was stopped by pool_full; the affected trial is not counted.

Banana and orange fail almost only at `carry_failed` (object lifted, then lost). crossfade-16 has the lowest jitter
(24–25 % vs. 40–47 %) and the smallest seams, but no success advantage.

### Series 2 – chunk sizes (apple, 6 pairs)

[`series2_chunk_sizes.md`](measurements/2026-11-22/series2_chunk_sizes.md):

| Strategy | chunk | receding-8 | receding-24 | crossfade-8 | crossfade-24 |
|---|---|---|---|---|---|
| Success | 1/6 | 0/6 | 4/6 | 0/6 | 3/6 |

- Δ progress of the 24-row variants: +0.5 (CI excludes 0).
- All drops were "slipped".
- receding-8 never executed a new plan, because 8 rows are fewer than the ~11 rows the client replaces. This led to I3.

### Series 3 – horizons 24/30 (8 pairs)

- **Apple** ([`series3a`](measurements/2026-11-22/series3a_horizons_apple.md)):

  | Strategy | chunk | receding-24 | receding-30 | crossfade-30 |
  |---|---|---|---|---|
  | Success | 1/8 (7× not grasped) | 2/8 | 3/8 | 3/8 |

  Δ progress: receding-30 +0.375 [+0.12, +0.62], crossfade-30 +0.406 [+0.25, +0.56].
- **Orange** ([`series3b`](measurements/2026-11-22/series3b_horizons_orange.md)): all 0/8. Progress: chunk 0.38,
  receding-24 0.50 (CI +0.03…+0.25), crossfade-30 0.47, receding-30 0.28.

### Series 4 – prompt variants (apple, 3 trials per variant, before the latency fix)

[`series4_prompts.md`](measurements/2026-11-22/series4_prompts.md)

| Prompt | chunk | receding-24 |
|---|---|---|
| put the apple into the bowl | 0/3 | 2/3 |
| place the apple in the bowl | 3/3 | 1/3 |
| could you please pick up the apple and put it into the bowl? | 1/3 | 0/3 |
| apple -> bowl | 0/3 | 0/3 |
| put the red fruit into the bowl | 0/3 | 1/3 |

No variant is consistently better across both strategies. With receding-24 every prompt reaches progress ≥ 0.5 (chunk
partly 0.25). The 3/3 of "place the apple in the bowl" with chunk was re-checked on new scenes in series 6b.

### Series 5 – after the latency fix

- **5a Determinism** (no perturbation, 4 repeats of the same scene,
  [`series5a`](measurements/2026-11-22/series5a_paused_determinism.md)):
  - Results: chunk 1/4, receding-24 1/4, receding-30 2/4, crossfade-30 2/4. Repeats are *not* identical.
  - Cause, isolated with [`determinism.py`](measurements/2026-11-22/determinism.py): same start pose and same joint
    state, but the images already differ at request 0. The first plan then differs by up to 0.029 rad, later by up to
    0.13 rad ([`determinism_render_noise.json`](measurements/2026-11-22/determinism_render_noise.json)).
  - Two renders of the same state differ in 0.001–0.02 % of the pixels by exactly one grey level (GPU rasterisation).
- **5b Horizons, target_shift 2 cm** (8 pairs, [`series5b`](measurements/2026-11-22/series5b_paused_target_shift.md)):

  | Strategy | Success | Progress | Requests | Jitter | Seam/step | Most common failure |
  |---|---|---|---|---|---|---|
  | chunk | 3/8 | 0.50 | 14 | 40 % | 2.70 | not grasped (4) |
  | receding-8 | 0/8 | 0.31 | 100 | 51 % | 3.28 | pushed (6) |
  | receding-16 | 0/8 | 0.41 | 50 | 36 % | 2.13 | not grasped (4) |
  | receding-24 | 2/8 | 0.78 | 31 | 38 % | 1.68 | placed next to it (5) |
  | receding-30 | 3/8 | 0.66 | 24 | 40 % | 2.69 | carried, lost (2) |
  | crossfade-24 | 2/8 | 0.72 | 31 | 38 % | 1.42 | placed next to it (4) |

- **5c Same scenes with the old client latency** ([`series5c`](measurements/2026-11-22/series5c_client_target_shift.md)):
  - Results: chunk 1/8, receding-16 1/8, receding-24 2/8.
  - Paired per scene against 5b, results scatter in both directions. At this N the fix has no measurable effect on
    success.
  - The fix is still correct: it removes a demonstrably wrong assumption (see I3), and only with it do receding-8/16
    really execute new plans.

### Series 6 – confirmation on new scenes (target_shift 2 cm, seed 91)

[`series6_confirmation.md`](measurements/2026-11-22/series6_confirmation.md)

| Prompt | Strategy | Success | Progress | Final distance | Most common failure |
|---|---|---|---|---|---|
| put the apple into the bowl (12 pairs) | chunk | 0/12 | 0.27 | 19.9 cm | not grasped (10) |
| | receding-24 | 5/12 | 0.67 | 11.9 cm | carried, lost (3) / not grasped (3) |
| | crossfade-30 | **6/12** (McNemar p = 0.03) | 0.77 | 9.2 cm | placed next to it (3) |
| place the apple in the bowl (8 pairs) | chunk | 3/8 | 0.53 | 17.8 cm | not grasped (5) |
| | receding-24 | 2/8 | 0.62 | 11.2 cm | carried, lost (4) |

The 3/3 of "place the apple in the bowl" from series 4 does not hold on new scenes (3/8). It was an effect of a single
scene, not of the prompt.

### Series 7 – the new default under other conditions (8 pairs per condition)

[`series7_default_conditions.md`](measurements/2026-11-22/series7_default_conditions.md)

| Condition | chunk | crossfade-30 | Progress chunk → crossfade-30 |
|---|---|---|---|
| Apple, light dimmed by 50 % | 1/8 | **4/8** | 0.41 → 0.84 |
| Apple, bowl moved by 3 cm | 2/8 | **5/8** | 0.56 → 0.88 |
| Banana → plate, target_shift 2 cm | 0/7 (1 trial not counted, I9) | **3/8** | 0.46 → 0.69 |

Pooled over the three conditions: 12:3 discordant pairs, McNemar p = 0.035, Δ progress +0.34 [+0.18, +0.48].

### Pooled over the whole night

[`pooled_all_night.md`](measurements/2026-11-22/pooled_all_night.md). All 14 compare campaigns; pairs only on the same
scene and prompt; trials that are not counted are excluded.

| Strategy | Pairs | chunk success | Strategy success | Only chunk | Only strategy | McNemar p | Δ progress (95 % CI) |
|---|---|---|---|---|---|---|---|
| **crossfade-30** | 55 | 9 % | 42 % | 3 | 21 | **0.0003** | **+0.35 [+0.26, +0.44]** |
| crossfade-24 | 14 | 29 % | 36 % | 2 | 3 | 1.00 | +0.34 [+0.16, +0.52] |
| receding-24 | 62 | 16 % | 29 % | 8 | 16 | 0.15 | +0.30 [+0.19, +0.40] |
| receding-30 | 28 | 18 % | 29 % | 3 | 6 | 0.51 | +0.18 [+0.03, +0.33] |
| receding-16 | 33 | 18 % | 9 % | 6 | 3 | 0.51 | +0.02 [−0.12, +0.15] |
| crossfade-16 | 16 | 12 % | 0 % | 2 | 0 | 0.50 | −0.05 [−0.20, +0.09] |
| ensemble-16 | 16 | 12 % | 0 % | 2 | 0 | 0.50 | −0.09 [−0.20, 0.00] |
| receding-8 | 14 | 29 % | 0 % | 4 | 0 | 0.13 | −0.20 [−0.41, 0.00] |

Unpaired, apple: chunk 12/68 (18 %, 46× not grasped), crossfade-30 20/40 (50 %), receding-24 16/46 (35 %), receding-30
8/20 (40 %).

Why does it help? The full chunk runs 2.4 s blind, right during the approach to the object, where a correction is
needed. crossfade-30 replans after 1.5 s and blends over without a jump (seam/step 1.1–1.2 instead of 2.7–2.9).

### Joint movement

Medians over all paired trials; details in [TEST_OVERVIEW.md](TEST_OVERVIEW.md).

- **Seams:** crossfade-30 has the smallest seams. The jump at a plan change is 0.010 rad vs. 0.026 rad for the chunk,
  i.e. 1.2× a normal step instead of 2.7×.
- **Speed:** crossfade-30 runs about 15 % faster.
- **Jitter:** crossfade-30 jitters slightly more (49 % vs. 42 %), because it follows a mix of two plans during the
  blend.
- The smoothest strategy is crossfade-16 (23 % jitter), but it is not more successful than the chunk.

### Model X-Ray on real Dream-1

[`xray_real/`](measurements/2026-11-22/xray_real/), moment at 78 s (apple):

- Dream-1 is deterministic: three identical requests → 0.0 cm spread, target always "apple".
- The re-asked plan differs by 2.31 cm from the recorded one (the client's seam smoothing).
- Language probe: it followed the object word in 1 of 4 cases, but the moment was too late (the arm was already at the
  apple), which led to I4. With the made-up word "blicket" it still goes for the apple.
- RISE (60 masks): only the overhead camera was barely above chance (0.57 vs. 0.56 cm) → 60 masks are not enough.
- Blanking a whole camera: top 5.04, left 4.47, right 2.81 cm plan change.

Repeat after I4/I8 ([`log_xray2.jsonl`](measurements/2026-11-22/log_xray2.jsonl),
[`log_xray3.jsonl`](measurements/2026-11-22/log_xray3.jsonl), results in `xray_real/`):

| Moment | Re-ask vs. recording | Blank camera (top/left/right) | RISE | Language probe |
|---|---|---|---|---|
| 3.0 s (arm moves towards the apple) | 5.86 cm, target lost | 0.50 / 0.47 / 0.42 cm | 200 masks, all at chance (206 calls) → **I8**: now skipped after 6 calls, with a reason (confirmed on Dream-1) | no target in the plan → cannot be checked |
| 4.5 s (closes gripper 5.7 cm from the apple) | 2.68 cm, target lost | 4.06 / 5.29 / 1.47 cm | 200 masks, peaks 0.46–0.66 cm below chance 0.69–0.71 cm | no target in the plan → cannot be checked |

Findings:
- Dream-1 remains exactly deterministic for identical requests (noise 0.0 cm in every run).
- The re-asked plan differs systematically by 2.3–5.9 cm from the recorded one.
  - Cause: in a live run the client smooths every chunk onto the previous plan (Savitzky-Golay + a 16-row
    transition), while the X-Ray session starts without a previous plan.
  - The X-Ray comparisons (masks, words) are consistent with each other, because all are measured against the same
    re-ask. But it makes the target detection flip at borderline moments.
- Blanking whole cameras is informative (up to 9.5 cm). RISE with masks on all three cameras at once is not: every mask
  hides half of *every* camera, so the effect of single cells is lost in the overall effect.

Re-measured after I10/I11 (morning, [`log_xray4.jsonl`](measurements/2026-11-22/log_xray4.jsonl),
`xray_real/results_*_v2.json`), same two moments:

| Moment | RISE, most-used camera only, 200 masks (¼ hidden) | Language probe (approach to the named object vs. original prompt) |
|---|---|---|
| 78 s, gripper at the apple | overhead: peak 0.61 cm, chance 0.39 cm → **above chance** (before, with all cameras: 0.57 vs. 0.56) | banana −0.0 cm, orange −0.5 cm, bottle +0.2 cm → **0 of 3**: ignores the word, stays with the apple |
| 4.5 s, closes 5.7 cm before the apple | left wrist: 0.58 vs. 0.58 → exactly at chance | banana −0.1 cm, orange −0.2 cm, bottle −1.3 cm → **0 of 3** |

![RISE overhead, 78 s](measurements/2026-11-22/xray_real/rise_overhead_ff71.png)

The heatmap (right; orange = hiding this area changes the plan more than chance) lies mainly on:
- the **bowl**, the target of the next step, since the left gripper is already at the apple;
- the gripper tip;
- a band along the right arm;
- a small spot in the background (probably chance).

This is the first plausible RISE signal on real Dream-1. The language probe now gives an answer instead of "cannot be
checked": shortly before and during the grasp the image decides, not the word. Whether Dream-1 uses the word *earlier*
in the approach is still open (problem 6).

## Improvements (each motivated by a measurement and measured again)

| # | Weakness (measurement) | Change | Re-measurement |
|---|---|---|---|
| I1 | Camera check reported "frozen" at 75 % dimming; wrong fps | compare the grey-level change on both sides; fps from adjacent frames | 2×0 % + 2×75 % without a false alarm; the self-test still detects frozen/delay/black; regression test `test_dark_slow_scene_is_not_called_frozen` |
| I2 | Measurements running in parallel aborted with DA-2000 `pool_full` (series 1 orange at 18/24) | the runner waits out retryable refusals for up to 180 s; X-Ray/camera tests use one session; measurements run sequentially | no error trials afterwards (one orange start at 01:20 aborted before the fix after 1 trial and was repeated as `20261122-014508-compare`) |
| I3 | receding-8 never executed a new plan; trial variance depended on the RTT | `latency="paused"`: the client gets `action_hz = 1e-3`, so `round(rtt · hz) = 0` rows are replaced – the truth in a pausing simulator. `"client"` stays available for old runs and comparison | series 5b/5c; unit test with `dream.smoothing.old_motion`; old results are marked "· client latency" in the report |
| I4 | Language probe on a moment that was too late | X-Ray keeps the first 6 moments of a run (`FIRST_MOMENTS`) instead of only the last ones | see the X-Ray repeat |
| I5 | Gripper blend > 1, and blending the gripper delays closing | the gripper always follows the newest plan; only arm joints are blended | unit tests |
| I6 | The jerk index favoured slow strategies | jitter share (residual after a moving average) instead of jerk for "smoothest" | series 1 onwards |
| I7 | The full chunk mostly fails before the grasp; crossfade-30 significantly better (series 1–6) | dashboard default `inference.DEFAULT = "crossfade-30"`, menu sorted by measurement, 8/16-row variants removed from the menu (still usable by name); `run_task()` keeps `chunk` | series 7 under three new conditions: better each time, pooled p = 0.035 |
| I8 | RISE on a moment where the plan barely depends on the images: 200 masks (206 API calls), all at chance | RISE first asks unchanged + each camera blanked; if that moves the plan by ≤ max(3 × noise, 1 cm), the masks are skipped and the reason is shown | unit test; re-measured on Dream-1, see X-Ray |
| I9 | A chunk trial ended after 240 of 800 steps because requests hung for ~14 min (machine in standby), and was counted as "not grasped" (data check: RTT 854 s) | with a simulated budget, an end by the wall clock is now `wall_timeout` → outcome "aborted", never counted; `analyze.py` recognises old cases (timeout with fewer steps than the budget) | exactly this one trial was affected all night; series 7 re-analysed |
| I10 | RISE with masks on all three cameras: no signal on Dream-1 even with 200 masks | masks only on the camera whose blanking changes the plan most (the others stay unchanged), ¼ instead of ½ hidden; `camera="all"` keeps the old way | 78 s: above chance, bowl and gripper marked; 4.5 s: at chance |
| I11 | Language probe: the hard target detection (grasp ≤ 8 cm) was missing in the re-asked plan at 2 of 3 moments → "cannot be checked" | the original prompt is asked too; per word, how much closer the gripper path gets to the named object counts – more than max(3 × noise, 1 cm) and more than to any other object | both moments give an answer (0 of 3); unit test with synthetic distances |

## Open problems

1. **Orange 0/50, banana only with crossfade-30 (3/8, otherwise 0/31).** The object slips out of the closed gripper
   (drop analysis: "slipped", gripper stays closed). Probably the contact/friction parameters of the objects or the
   grasp position – not purely an inference problem.
2. **"Placed next to the container"** is the most common remaining failure with crossfade-30/receding-24 (apple: 11/40
   and 15/46).
3. **receding-24 vs. crossfade-30 directly** was only compared in series 6 (5/12 vs. 6/12). Which one is better is open;
   both are clearly better than the full chunk.
4. **Render noise.** Exactly reproducible repeats would need deterministic rendering (CPU renderer/OSMesa, or rounding
   before the JPEG). Deliberately not done: the noise acts like real sensor noise and makes repeats genuine samples.
5. **RISE** now shows a signal at one of two moments. For small plan changes (left wrist, 4.5 s), 200 masks are not
   enough. A run costs ~200 calls; more masks or a coarser grid would be the next step.
6. **Language probe.** It was only measured at moments close to the apple (0 of 3).
   - Open: does Dream-1 use the object word at the *start* of the approach? To check, freeze a moment far from all
     objects.
   - A true live warm-up (the plan before the moment as the starting point of the client's smoothing) would need the
     previous plan in the snapshot. Until then, the re-ask still differs by 2.3–5.9 cm from the recorded plan.
7. **Dream input check.** The client warns "no one has checked what the model sees …". Dream reserves the record via
   `python -m dream.input_check` for a person ("never an agent"), so please run it yourself. The camera check provides
   the evidence.
8. Moritz's Node test in the Test Suite area still fails (it did before this night).

## Reproduce

```
python measurements/analyze.py <out.md> <campaign id> ...
python measurements/pool.py <out.md> <campaign id> ...
python measurements/2026-11-22/drive.py 8001 measurements/2026-11-22/plan6.json log.jsonl   # dashboard on port 8001
```

Campaign ids are in the `log*.jsonl` files and in every table.
