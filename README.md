# dream-tool – Dream Labs Track

Our project for the **"Build a Tool for Dream-1 Users"** track: a tool that real Dream-1 users would pick up and use,
built on [dreamlabs-co/dreamlabs](https://github.com/dreamlabs-co/dreamlabs) and tested in the simulator.

**Judging (100 points):** Real-user value 25 · Robustness 25 · Technical difficulty 20 · Demo quality 20 ·
Presentation 10. Sunday: 3-minute live demo + 2 minutes of questions.

## Folder layout

```
Hacklab/
├── .venv/              Python 3.12 with dreamlabs + dreamlabs-client (installed from the clone)
├── dreamlabs/          clone of the official repo (read-only, do not edit)
│   └── dream_library/examples/yam_mujoco/   ← the simulator (2 YAM arms, 3 cameras, fruit, bowl, plate)
└── dream-tool/         ← OUR project (this repo)
    ├── dashboard/        ← local web app (FastAPI + plain JS), sim in the middle
    │   ├── app.py          HTTP API, MJPEG streams, WebSocket events
    │   ├── simulation.py   sim thread: owns physics + rendering, executes runs
    │   ├── extension.py    Extension base class + loader + 3D overlay helpers
    │   ├── extensions/     ← new features go HERE (one folder each)
    │   │   ├── scene_inspector/   object positions, success zones, debug placement
    │   │   ├── robustness/        robustness test: perturb scene/vision/physics/prompt, find where Dream-1 breaks
    │   │   └── _template/         template to copy
    │   ├── static/         core UI (index.html, app.js, style.css, lib/api.js)
    │   └── EXTENSIONS.md   guide: writing your own extension
    ├── start.py          starts the dashboard
    ├── dreamtool/
    │   ├── sim.py        locates the simulator, re-exports YamEnv + request helpers
    │   ├── runner.py     Dream-1 ↔ sim control loop, with hooks for your tool
    │   ├── inference.py  inference strategies: how Dream-1's action chunks are executed (chunk/receding/ensemble/crossfade)
    │   ├── scene.py      object positions + simple success detection ("apple in bowl")
    │   └── recorder.py   MP4 recording of the 3 cameras (for the demo)
    ├── run.py            CLI: run a task, optionally record it
    ├── check_setup.py    checks that everything works
    ├── tests/            offline tests (no API key needed)
    └── setup.ps1         setup for team members
```

## Setup

Requirements: Windows, Python 3.12 and git.

```powershell
git clone https://github.com/AbdullHadi-akr/DreamLabs_Hacklab.git Hacklab\dream-tool
cd Hacklab\dream-tool
powershell -ExecutionPolicy Bypass -File setup.ps1
```

The script clones `dreamlabs/` next to this repo, creates `..\.venv`, installs everything and runs `check_setup.py`.
Activate the environment in every new shell:

```powershell
..\.venv\Scripts\Activate.ps1
```

### API key

Create a key at [platform.dreamlabs.ai/api-keys](https://platform.dreamlabs.ai/api-keys) (it is shown only once).
Then do **one** of these:

- `$env:DREAM_API_KEY = "dl_live_..."` (current shell only)
- create `%USERPROFILE%\.dreamlabs\credentials` with these four lines:

```
DREAM_GATEWAY_URL=https://api.dreamlabs.ai
DREAM_API_URL=https://platform.dreamlabs.ai
DREAM_DATA_URL=https://data.dreamlabs.ai
DREAM_API_KEY=dl_live_...
```

Every Dream-1 run uses credits on the account.

## Dashboard

```powershell
python start.py                      # or: python -m dashboard   → opens http://localhost:8000
```

- **Center:** 3D view of the sim (drag = orbit, right/Shift = pan, wheel = zoom, double-click = reset),
  with the prompt bar and the three robot cameras below.
- **Left:** extension tabs (Scene, Robustness, …). **Right:** current run, RTT chart, log.
- **Teleop tab:** move the grippers yourself between runs. Drag the colored ball at a gripper (Shift = up/down),
  or use W A S D / E Q (directions as the robot's overhead camera sees them, switchable to the 3D view);
  Z / X or the mouse wheel on the ball rotates the gripper, R / F tilts it; Space
  opens/closes it, 1/2 picks the arm. The tool center point coordinates, rotation and tilt are shown next to each
  gripper; a colored line shows the direction the fingers open in. Costs no credits.
- **Offline demo**, **Home**, **Reset** and the **dry run** of the robustness tests cost no credits.
  The **run** button and sweeps without dry run call Dream-1.
- The server only listens locally (127.0.0.1). Ctrl+C stops it.

### Validation Test Suite

Open **Test Suite** next to **Dashboard**. Quick Test takes a single run from the current scene. Repeated Runs samples one scene per repetition, Parameter Sweep enumerates explicit combinations, and Safety Stress Test applies selected reach and visibility disturbances. A/B Comparison restores matched scenes for both prompts. Failure Reproduction restores the recorded scene settings and, for newly recorded runs, the initial MuJoCo physics state. Dream-1 inference can vary between otherwise identical runs.

Placement outcomes use simulated contact, release, and stability evidence. Reports include the last observed stage and flag new contacts between opposite arms and modeled joint-limit violations. Workspace boundaries and contact force limits require additional safety definitions. API errors and unsupported goals can leave a run unevaluated. Dry runs exercise the workflow without live inference.

### Robustness test

**Test Suite → Robustness** (four tiles in the Test Builder: Robustness Sweep, Breaking Point, Perturbation Mix,
Strategy A/B):
change the world on purpose and see how and when Dream-1 fails. The full report appears in the Test Report area.

- **Sweep:** one perturbation at increasing strength (e.g. move the apple 0/2/4/6/8 cm) → success rate with a 95 %
  interval per strength, progress score, and the **breaking point** (first strength at half the baseline or below).
  The unperturbed baseline is always included; trial *i* uses the same random draw at every strength.
- **Breaking point (adaptive search):** Bayesian active learning (psi method): after a few baseline trials,
  every next strength is the one with the largest expected information gain about the breaking point θ; stops when
  θ is pinned down (80 % interval), when nothing breaks in the range, or at the budget. The measured stage can be
  success, carried, lifted or reached (useful when Dream-1 rarely succeeds unperturbed). In simulation with known
  breaking points: ~30 % smaller error than a fixed 5 × 3 sweep with the same 15 trials, and it stops after ~6
  trials when nothing breaks.
- **Random mix:** every trial draws random strengths for several perturbations → which factor hurts most
  (rank correlation with the progress score).
- **Strategy A/B:** the same trials under different inference strategies (see below), optionally under one fixed
  perturbation. Paired design (pair *i* = same seed for every strategy) → McNemar's exact test on the pairs that
  disagree, a bootstrap interval for the progress difference, and motion/cost per strategy (speed, seam jump relative
  to a normal step, jitter share of the measured joint motion, requests per trial).
- **Budget in simulated time:** `seconds` limits simulated motion (20 steps/s); waiting for Dream-1 does not count, so
  a strategy that asks more often is not punished by network latency.
- **15 perturbations** in five groups: scene layout (target/container/other objects moved, target rotated), vision
  (camera shifted/tilted, dimmer light, table/target recolored, sensor noise), physics (heavier target, slippery
  gripper pads), language (typos, rewordings) and during the run (target moved the moment the gripper arrives).
- **How it failed**, not just whether: every trial is classified (never reached, no grasp, pushed away, wrong object,
  lost on the way, placed next to the container, knocked off the table) with a progress score 0 / .25 / .5 / .75 / 1.
  That gives a readable curve with only a few (expensive) trials.
- **Task wording:** success is measured from the task, so it must name one object and the goal container
  (e.g. "Pick up the banana and put it on the green plate", "move the apple from the plate to the bowl", also
  German "Leg den Apfel in die Schüssel"). The exact wording still goes to Dream-1 unchanged.
- **Fair trials only:** each setup is checked (on the table, in reach, no overlaps, not already solved) and re-drawn
  if needed; a trial that ends with the target on the floor stops early to save credits.
- **Report page** with chart, tables and an MP4 of every trial (overhead + wrist cameras = what Dream-1 saw).
  Results live in `out/extensions/robustness/<campaign>/`.
- **All runs, heatmap & downloads** (`/ext/robustness/runs.html`, linked in the robustness panel): every stored run, a
  **robustness map** (heatmap: perturbation × strength, colored by success rate or progress score, filtered by task
  and policy so dry runs and Dream-1 are never pooled) and downloads per run (CSV, Excel CSV, JSON, ZIP with videos)
  or for all filtered trials at once. The report page adds a trial × strength grid (sweep) or a two-factor heatmap
  (random mix).
- **Dry run** (default) replays a scripted pick-and-place planned once on the unperturbed scene: no credits, and a
  reference for a policy that does not look (it breaks at ~2 cm and ignores all visual changes).

### Inference strategies (better behaviour without fine-tuning)

Dream-1 returns 48 joint targets per arm (2.4 s) per request. How much of that is executed before asking again, and how
consecutive plans are combined, is our choice (`dreamtool/inference.py`):

| Strategy | What it does | Trade-off |
| --- | --- | --- |
| `chunk` (default) | execute all 48 rows, then ask again | open loop for 2.4 s; visible jump at every seam |
| `receding-N` | execute the first N rows, discard the rest, ask again | reacts faster to what the cameras see, but every new plan may start elsewhere |
| `ensemble-N` | ask every N steps, average the arm joints of all plans covering a step (weight `exp(-0.05·steps ahead)`, as in ACT) | averages out plan-to-plan noise, follows a new plan with lag and can slow the arm down |
| `crossfade-N` | ask every N steps, fade the arm joints linearly from the old plan to the new one over N rows | no seam jumps and fully on the new plan after N steps |

Blends never touch the gripper: it always follows the newest plan. (A first Dream-1 comparison averaged the gripper
too; `ensemble-16` then lifted the apple and lost it on the way in 3 of 4 trials.)

All of them cost about 48/N times the requests. Pick one in the dashboard's prompt bar (**Execution**), per robustness
campaign, with `python run.py "..." --strategy ensemble-16`, or compare them with **Strategy A/B**. Every run reports
`commands` (seam jump relative to a normal step, speed, jerk, jitter) next to the result. Smoothness is judged by the
**jitter share** (the part of the joint motion left over after a 0.45 s moving average), not by absolute jerk: absolute
jerk mostly measures speed, so a strategy that just slows the arm down would look smooth.

Deliberately left out: latency (the sim pauses physics while waiting for Dream-1, so delays change nothing) and
joint-encoder noise (real encoders are precise; the noise would also leak into the hold commands).

**Building a new feature:** copy `dashboard/extensions/_template` → see
[dashboard/EXTENSIONS.md](dashboard/EXTENSIONS.md).

## Getting started (CLI)

```powershell
python check_setup.py --online       # all green? (--online checks the key against the API)
python -m pytest -q                  # offline tests
python run.py --offline --record out/offline.mp4   # sim without the API, video as proof
python run.py "put apple into the bowl"            # Dream-1 drives the arms, 3D viewer opens
python run.py "put banana on the plate" --headless --record out/banana.mp4 --seconds 90
```

The official interactive simulator (with task terminal, `/reset`, `/model` …):

```powershell
cd ..\dreamlabs\dream_library\examples\yam_mujoco
python yam_mujoco.py
```

> **Windows notes:** `dreamcli` does not run on Windows (it uses `fcntl`), but the sim does not need it.
> `yam_mujoco.py` needs a real console (PowerShell / Windows Terminal), not Git Bash.

## Plugging in your tool

All logic enters the loop through **hooks**, so you never have to touch the control loop:

```python
from dreamtool import Hooks, run_task, scene

class MyTool(Hooks):
    def on_start(self, env, task, model): ...           # before the first request
    def on_reply(self, env, reply, rtt_s): ...          # every action chunk: reply["q_l_chunk"], ["q_r_chunk"], each [H, 7]
    def on_step(self, env, step, images): ...           # every 50 ms: env.state(), images["top"|"left"|"right"]
    def should_stop(self, env): return None             # return a reason string → the run stops
    def on_end(self, env, result): ...                  # RunResult: success, stop_reason, rtts_s, steps …

result = run_task("put apple into the bowl", hooks=[MyTool()], viewer=False, seconds=60)
```

Useful: `scene.positions(env)`, `scene.is_in(env, "apple", "bowl")`, `env.state()` (joints in rad +
gripper 0–1), `env.reset()`, `sim.home_path(env.state())`. Test offline without credits: `run_scripted(env, targets, hooks)`.

**Model facts:** `dreamlabs/dream-1-beta`, 20 Hz control, up to 48 actions per reply, input = 9 frames each
(320×176 JPEG, 0.2 s apart) from 3 cameras + joint states + text prompt. The simulator does **not** detect task
success by itself. According to the docs: apple/orange → bowl works sometimes, banana → plate is unreliable.

## Ideas (mapped to the judging criteria)

1. **Eval / benchmark runner** – N runs per prompt, automatic success detection (extend `scene.py`), success rate,
   latency stats, video per trial → HTML report. Answers every user's question: *"Which prompt / model / fine-tune
   actually works?"* (real-user value + robustness)
2. **Safety guard** – pre-simulate each action chunk in a copy of the physics before executing it; stop or slow down
   on collisions, crossing arms or leaving the workspace. Transfers to real robots.
3. **Run debugger** – visualize planned vs. executed trajectories, RTT timeline, seam jumps between chunks.
4. **Prompt optimizer** – automatically try variants of a task and find the best wording.
5. **Dataset recorder** – export successful sim runs as a fine-tuning dataset (`client.validate_dataset`).

Demo tip: record runs beforehand with `--record` as a backup in case the API or Wi-Fi acts up live.

## Links

- Docs: <https://platform.dreamlabs.ai/api-documentation>
- Client reference: `../dreamlabs/dream_library/dream_client/README.md`
- Simulator: `../dreamlabs/dream_library/examples/yam_mujoco/README.md`
- Discord: <https://discord.gg/UAPxxH6tTg>
