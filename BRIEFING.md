# Technical briefing: DreamLab-Rat

Presentation prep: model output and execution strategies, how Dream-1 uses the cameras, how the robustness tests
work, and the measured results. Sources: [NIGHTLY_REPORT.md](NIGHTLY_REPORT.md), [TEST_OVERVIEW.md](TEST_OVERVIEW.md),
[`measurements/2026-11-22/`](measurements/2026-11-22/).

## 1. What Dream-1 receives and returns

**Input per request**
- **Three camera windows:**
  - `video.overhead` (top camera), `video.wrist_l` and `video.wrist_r` (wrist cameras).
  - Each window holds 9 frames, 0.2 s apart: 5 frames per second over 1.6 s. Dream-1 sees a short history of motion,
    not a single still image.
  - Rendered at 640×480, cropped to 640×360 (as on the real YAM station), and sent as 320×176 JPEG at quality 85.
- **Joint state:** `state.left_arm` / `right_arm` (6 joints each) plus both grippers.
- **Prompt:** the task text.
- **Timestamps:** in simulated time, not wall-clock time. So the frames in the window are exactly 0.2 s apart, however
  fast or slow the machine is.

**Output:**
- One **chunk** per arm: `q_l_chunk` and `q_r_chunk`, each **48×7** (6 joint targets plus the gripper;
  1 = open, 0 = closed).
- At a 20 Hz control rate, 48 rows = **2.4 s of planned motion**.
- Round trip: about 0.5–0.6 s per request.

**The simulation pauses** during every request. That is the key difference from the real robot, which keeps moving in
that time.

**The Dream client's smoothing:** the client always smooths each new chunk onto the previous one (`dream.smoothing`).
- It assumes the robot kept moving during the request, so it replaces the first `round(RTT × 20 Hz)` rows (≈ 11) with
  the rest of the old plan.
- Then it applies a Savitzky-Golay filter and a 16-row transition.
- In the paused simulator this was an **artificial, random delay**. Our fix (`latency="paused"`) sets
  `action_hz = 1e-3`, so 0 rows are replaced.
- The evidence: receding-8 never executed a new plan, because 8 rows are fewer than the ~11 being replaced.

## 2. The execution strategies (`dreamtool/inference.py`)

Dream-1 always returns 48 rows. We decide **how much of it is executed and how consecutive plans are joined**. Cost:
about 48/N times as many requests.

| Strategy | How it works | Strength | Weakness |
|---|---|---|---|
| **chunk** | execute all 48 rows, then ask again | few requests; the model's plain output | runs 2.4 s without correction; a jump at every plan change |
| **receding-N** | execute only the first N rows, drop the rest, ask again | reacts faster to new images | each new plan may start elsewhere, which causes jumps |
| **ensemble-N** | ask every N steps; average all plans covering a moment, weighted `exp(−0.05·steps ahead)` (as in ACT) | averages out noise | follows new plans with a lag, slows the arm down |
| **crossfade-N** | ask every N steps; blend linearly from the old plan to the new one over N rows | no jump; fully on the new plan after N steps | during the blend the arm follows a mix of two plans |

**The gripper is never blended**; it always follows the newest plan. Reason: an averaged gripper command sits between
open and closed and delays closing. Measured: ensemble-16 dropped 3 of 4 apples that way.

**Default:** the dashboard now uses **crossfade-30**. The library function `run_task()` keeps `chunk`, so it still
returns the model's plain output.

## 3. How Dream-1 uses the cameras

**Camera check: do the right images arrive?**
- **Ground truth:** at every simulation step, a small reference image of each camera is stored.
- **Matching:** every image sent is compared by normalised correlation against all cameras, all moments and all
  distortions: upright, upside down, mirrored, flipped vertically, red/blue swapped.
- **Result per camera:**
  - which camera the image really shows (match ≥ 0.95);
  - which distortion is present;
  - delay (warning above 250 ms);
  - frozen (grey-level change compared on both sides);
  - frame rate.
- **Self-test:** 8 injected faults, all 8 detected on real Dream-1: swapped wrists, duplicate camera, upside down,
  BGR, frozen, 600 ms delay, black, zoom. Clean runs: 0 ms delay, 5 frames/s, match ≥ 0.998.
- **Perturbations:** with a tilted camera, dimmed light, image noise and a moved camera, the images still arrived
  correctly.

**"Does Dream-1 use the cameras?"**
- A moment is frozen and Dream-1 is asked again: once unchanged, then with each camera blacked out, and once with the
  wrist cameras swapped.
- Measured: how much the planned gripper path changes (forward kinematics of the 48 joint targets).
- Threshold: 3× the noise, at least 1 cm.
- **Result:**
  - Blanking the top camera moves the plan by up to **9.5 cm**; the wrists by up to **5.9 cm**.
  - The top camera and the left wrist (the grasping arm) always matter.
  - The right wrist matters only at some moments (0.7–5.6 cm).

**Model X-Ray: what does Dream-1 look at?**
- **Intent:**
  - Forward kinematics of the chunk, on a copy of the MuJoCo state, gives the gripper paths.
  - It detects the gripper closing and opening.
  - The target is the object within 8 cm of where the gripper closes; without a grasp, the object the path gets at
    least 2 cm closer to.
- **Noise:** the same request three times gives **0.0 cm**. Dream-1 is exactly deterministic for identical input.
- **RISE heatmap:**
  - Random smooth masks grey out parts of the camera that matters most (a quarter hidden per mask).
  - Importance per cell = mean plan change when hidden, minus mean plan change when visible.
  - A permutation test gives the chance level (95th percentile); only cells above it are coloured.
  - **Result at 78 s:** it marks the **bowl** (the next target; the gripper is already at the apple) and the gripper
    tip. This is the first signal above chance on real Dream-1.
  - With masks on all three cameras at once there was no signal: every mask hid half of every camera.
- **Language probe:**
  - The object word in the prompt is swapped (banana, orange, bottle, made-up word "blicket").
  - Measured: whether the path gets closer to the named object than with the original prompt, and by more than to any
    other object.
  - **Result:** shortly before and during the grasp, **0 of 3**. Dream-1 stays with the apple; at that point the image
    decides, not the word.

**Invisible noise is enough for different outcomes:**
- The GPU renders minimally differently: 0.001–0.02 % of the pixels differ by exactly one grey level.
- That already changes the first plan by up to 0.03 rad; after that, the trials diverge chaotically.
- Consequence: **the same scene is not an identical trial.** A single scene is often a coin flip, which is why we only
  evaluate over many pairs.

## 4. How the robustness tests work

**One trial:**
- 40 s of **simulated** time = 800 control steps. Network time doesn't count, so results are the same on every
  machine.
- The wall clock is only a guard against hanging requests. A trial it cuts short is not counted.

**Outcome classes and progress:**

| Outcome | Meaning | Progress |
|---|---|---|
| no_reach / wrong_object | never reached the object, or moved the wrong one | 0 |
| pushed / no_grasp | reached it, but pushed it or did not grasp it | 0.25 |
| carry_failed | lifted, then lost on the way | 0.5 |
| missed_container | carried to the container, but placed next to it | 0.75 |
| success | in the container | 1 |
| invalid / aborted | unstable physics, an error or a stop | **not counted** |

- **Drop analysis:** tells "released" (the gripper opens) from "slipped" (the object slides out of the closed
  gripper).

**Perturbations (15):**
- **Scene:** move target object, rotate target object, move container, move other objects.
- **Visual:** shift camera, tilt camera, dim light, table colour, object colour, image noise.
- **Physics:** heavier object, slippery gripper pads.
- **Language:** typos, rewording.
- **Dynamic:** move the object while it is being grasped.

**Four modes:**
- **Sweep:** fixed strengths plus a baseline.
  - Breaking point = the first strength where the success rate falls to half the baseline.
  - If the baseline never succeeds, progress is used instead.
- **Breaking Point (adaptive):** Bayesian search using the psi method (Kontsevich & Tyler, 1999).
  - Model: `P = eps + (1−2eps)·base·sigmoid((θ−s)/width)`.
  - Each next trial goes where it tells us most about θ.
  - Output: θ with an 80 % interval, e.g. "breaks at ≈ 4.1 cm (2.3–6.1 cm)".
- **Perturbation Mix:** random combinations. The rank correlation ρ of each perturbation with progress shows the most
  harmful one.
- **Strategy A/B:** same scene, same seed, each strategy once.

**Statistics:**
- **Exact McNemar test** for success; only the pairs where exactly one strategy wins count.
- **Bootstrap confidence interval** for the difference in progress.
- **Wilson interval** for success rates.
- **Smoothness:** the jump at a plan change relative to a normal step, and the jitter share (motion left after a 0.45 s
  moving average). Not absolute jerk, because that mostly measures speed.

**Dry run:** a pick-and-place motion planned once replays "blind". It costs no credits and tests the pipeline, not the
model.

## 5. Results (night of 21/22 Nov, 397 trials)

**Main result, paired on identical scenes:**

| Strategy | Pairs | chunk success | Strategy success | Only chunk wins | Only strategy wins | p | Δ progress |
|---|---|---|---|---|---|---|---|
| **crossfade-30** | 55 | 9 % | **42 %** | 3 | **21** | **0.0003** | **+0.35 [+0.26, +0.44]** |
| receding-24 | 62 | 16 % | 29 % | 8 | 16 | 0.15 | +0.30 [+0.19, +0.40] |
| receding-30 | 28 | 18 % | 29 % | 3 | 6 | 0.51 | +0.18 |
| receding-16 | 33 | 18 % | 9 % | 6 | 3 | 0.51 | +0.02 |
| ensemble-16 / crossfade-16 | 16 | 12 % | 0 % | 2 | 0 | 0.50 | −0.09 / −0.05 |
| receding-8 | 14 | 29 % | 0 % | 4 | 0 | 0.13 | −0.20 |

**Why:**
- chunk fails **before the grasp**: 46 of 68 apple trials never grasped the apple. It runs 2.4 s without correction,
  exactly during the approach.
- crossfade-30 replans every 1.5 s and blends over without a jump.
- Apple overall: chunk 12/68 (18 %), crossfade-30 20/40 (50 %).

**Confirmation under new conditions (crossfade-30 vs. chunk):**

| Condition | chunk | crossfade-30 |
|---|---|---|
| New scenes | 0/12 | 6/12 |
| Dimmed light | 1/8 | 4/8 |
| Bowl moved | 2/8 | 5/8 |
| Banana | 0/7 | 3/8 |

Across these three conditions together: p = 0.035.

**Joint movement (medians):**

| | Jump at plan change | Jump / normal step | Jitter | Speed |
|---|---|---|---|---|
| chunk | 0.026 rad | 2.7× | 42 % | 0.092 rad/s |
| crossfade-30 | 0.010 rad | 1.2× | 49 % | 0.106 rad/s |
| crossfade-16 | 0.011 rad | 1.7× | **23 %** | 0.108 rad/s |

- With crossfade-30, the jolt at a plan change is 60 % smaller and the arm is 15 % faster.
- It jitters slightly more, because during the blend the arm follows a mix of two plans.
- **Smooth is not the same as successful:** crossfade-16 is the smoothest, but no more successful than chunk.

**Other results:**
- **Prompts:** no wording is consistently better. "place the apple in the bowl" reached 3/3, but only 3/8 on new
  scenes.
- **Orange and banana:**
  - Orange: 0/50.
  - Banana: only crossfade-30 succeeded (3/8), otherwise 0/31.
  - Cause: "slipped"; the fruit slides out of the closed gripper. That is physics or grasp position, not a strategy
    problem.
- **Robustness of the model** (hints from few trials): tilting the camera by 8° or moving it by 4 cm breaks the apple
  task. Dimming and noise up to 20 σ show no clear effect.
- **Measurement errors fixed:**
  - the artificial latency;
  - trials aborted at the capacity limit (now it waits instead);
  - a false "frozen" alarm in the dark;
  - a trial that hung in standby and counted as a failure.

## 6. Likely questions and short answers

- **"Isn't that luck?"** No. 21:3 discordant pairs on identical scenes gives p ≈ 0.0003. Confirmed on new scenes and
  under three more conditions.
- **"Why not just ask more often?"** receding-8 and -16 ask far more often and do worse. What matters is a horizon
  around 24–30 steps plus a smooth transition.
- **"Does this hold on the real robot?"** Open. There the robot keeps moving during a request, which is what the
  client's smoothing is built for. The strategies carry over; the numbers would have to be measured again.
- **"How do you know the camera images are right?"** Every image sent is checked against the rendered ground truth,
  the self-test caught 8/8 faults, and blanking a camera changes the plan measurably.
- **"Why can't you reproduce the same scene?"** GPU render noise. We kept it on purpose: it acts like real sensor
  noise, so every repeat is a genuine sample.
- **"What's still missing?"**
  - receding-24 directly against crossfade-30 (so far 5/12 vs. 6/12).
  - Whether Dream-1 uses the object word early in the approach.
  - The grasp problem with the orange and banana.
