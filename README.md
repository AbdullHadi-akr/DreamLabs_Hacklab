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
    │   ├── events.py       event bus: any thread → every open browser tab
    │   ├── episodes.py     teaching loop: records runs as LeRobot episodes, export for a fine-tune
    │   ├── credits.py      cost per run, balance, monthly limit   lab_db.py  the SQLite records (out/lab.db)
    │   ├── multiplayer.py  guests on a second laptop (public link, access code, one arm each)
    │   ├── brain.py        writes runs, campaigns and exports into brain/raw/
    │   ├── extensions/     ← new features go HERE (one folder each)
    │   │   ├── scene_inspector/   tool "Scene": object positions, success zones, debug placement
    │   │   ├── teleop/            tool "Control": move the grippers with mouse and keyboard (inverse kinematics)
    │   │   ├── objects/           tool "Objects": drag, lift and turn the objects
    │   │   ├── camera_check/      tool "Cameras": do the images reach Dream-1 correctly?
    │   │   ├── xray/              tool "X-Ray": why Dream-1 does what it does
    │   │   ├── brain/             tool "Brain": the second brain as a 3D view
    │   │   ├── test_suite/        the Test Suite workspace: campaigns, evaluation, reports, Fork Here
    │   │   ├── robustness/        robustness tests in the Test Suite: perturb scene/vision/physics/prompt
    │   │   └── _template/         template to copy
    │   ├── static/         core UI: index.html, app.js, style.css, tutorial.js (guided tours),
    │   │                   credits.js, episodes.js, players.js, join.html/js (guests), lib/ (api, log, overlay)
    │   └── EXTENSIONS.md   guide: writing your own extension
    ├── start.py          starts the dashboard
    ├── dreamtool/
    │   ├── sim.py        locates the simulator, re-exports YamEnv + request helpers
    │   ├── runner.py     Dream-1 ↔ sim control loop, with hooks for your tool
    │   ├── inference.py  inference strategies: how Dream-1's action chunks are executed (chunk/receding/ensemble/crossfade)
    │   ├── camcheck.py   camera check: sent frames vs. rendered truth, fault injection, does the model use them
    │   ├── xray.py       Model X-Ray: planned gripper paths, RISE heatmaps, language probe on a frozen moment
    │   ├── xray_fake.py  scripted stand-in for Dream-1 (DREAM_XRAY_FAKE=1): try X-Ray without credits
    │   ├── scene.py      object positions + success detection for many task types ("apple in bowl", "lift the apple" …)
    │   └── recorder.py   MP4 recording of the 3 cameras (for the demo)
    ├── brain/            the second brain: raw/ (written by the dashboard) → wiki/ (build_wiki.py)
    ├── docs/             architecture diagrams, Fork Here, demo checklist, limitations (see Documentation)
    ├── measurements/     scripts and results of the measurement night (22.11.2026)
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

- **Center:** 3D view of the sim (drag = orbit, right-drag or Shift-drag = pan, Alt + wheel = zoom,
  double-click = reset), the three robot cameras below it (click one to show it on the big screen), and the prompt
  bar with **Settings** (model, duration, execution strategy).
- **Left:** the **Tools** menu: Scene, Control, Objects, Cameras, X-Ray, Brain, Episodes, Credits, Players.
  **Right:** the last run, the response-time chart and the application log. Both side panels fold away (‹ / ›).
- **Top bar:** **Dashboard** / **Test Suite** workspaces, **Tutorial** (guided tours, see below), Fullscreen, Rotate.
- **Control tool:** move the grippers yourself between runs. Drag the colored ball at a gripper (Shift = up/down),
  or use W A S D / E Q (directions as the robot's overhead camera sees them, switchable to the 3D view);
  Z / X or Alt + wheel on the ball rotates the gripper, R / F tilts it; Space
  opens/closes it, 1/2 picks the arm. The tool center point coordinates, rotation and tilt are shown next to each
  gripper; a colored line shows the direction the fingers open in. Costs no credits.
- **Offline demo**, **Home**, **Reset** and the **dry run** of the robustness tests cost no credits.
  The **run** button and sweeps without dry run call Dream-1.
- The server only listens locally (127.0.0.1); other laptops reach it only through the public link (see Multiplayer). Ctrl+C stops it.

### Tutorial (guided tours)

**Tutorial** in the top bar opens a list of short tours; pick one and it walks you through that part of the page step
by step: each step highlights one element and explains it in a small card (**Next** / **Back**, the arrow keys,
**Esc** to close). Tours only switch views and point at things: they never start a run, move an arm or spend credits.

| Tour | Steps | What it shows |
| --- | --- | --- |
| Dashboard basics | 9 | 3D view, robot cameras, prompt bar, free scene controls, Tools, run panel |
| Your first run with Dream-1 | 7 | writing a task, Settings, Offline demo, Run and its cost check, the result, Credits |
| Move the arms yourself | 4 | the Control tool: dragging the grippers, arm cards, keyboard |
| Teach Dream-1: episodes | 4 | recording, Take over, Save / Discard, exporting for a fine-tune |
| Test Suite and robustness | 7 | test types, task and settings, dry run, Test execution, Reports |
| Look inside Dream-1 | 4 | Camera check, Model X-Ray, live intent, the second brain |

On the first visit a small "New here?" note under the button offers the basics tour. A tour can also be opened by
address, handy for a demo: `http://localhost:8000/?tour=basics` (ids: `basics`, `first-run`, `control`, `teach`,
`test-suite`, `insight`). Guests on a second laptop see only the tours that apply to them. The tours live in
`dashboard/static/tutorial.js`; a new tour is one entry in `TOURS` (a step names a CSS selector, a title, a text and
optionally what to open first).

### Validation Test Suite

Open **Test Suite** next to **Dashboard**. Quick Test takes a single run from the current scene. Repeated Runs samples one scene per repetition, Parameter Sweep enumerates explicit combinations, and Safety Stress Test applies selected reach and visibility disturbances. A/B Comparison restores matched scenes for both prompts. Failure Reproduction restores the recorded scene settings and, for newly recorded runs, the initial MuJoCo physics state. Dream-1 inference can vary between otherwise identical runs.

Placement outcomes use simulated contact, release, and stability evidence. Reports include the last observed stage and flag new contacts between opposite arms and modeled joint-limit violations. Workspace boundaries and contact force limits require additional safety definitions. API errors and unsupported goals can leave a run unevaluated. Dry runs exercise the workflow without live inference.

### Robustness test

**Test Suite → Build → Test type**, group Robustness (Robustness Sweep, Breaking Point, Perturbation Mix,
Strategy A/B):
change the world on purpose and see how and when Dream-1 fails. The full report appears under **Report**.

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
- **Report page** with chart, tables, Dream-1 calls and cost per trial, and an MP4 of every trial when
  "Record video" is on (off by default: videos cost disk space and time). **Report (one file)** downloads the whole
  report as one HTML file that opens without the dashboard; **Report with videos** puts the videos inside it too.
  Results live in `out/extensions/robustness/<campaign>/`. The time limit counts simulated seconds.
- **All runs, heatmap & downloads** (`/ext/robustness/runs.html`, linked in the robustness panel): every stored run, a
  **robustness map** (heatmap: perturbation × strength, colored by success rate or progress score, filtered by task
  and policy so dry runs and Dream-1 are never pooled) and downloads per run (CSV, Excel CSV, JSON, ZIP with videos)
  or for all filtered trials at once. The report page adds a trial × strength grid (sweep) or a two-factor heatmap
  (random mix).
- **Dry run** (default) replays a scripted pick-and-place planned once on the unperturbed scene: no credits, and a
  reference for a policy that does not look (it breaks at ~2 cm and ignores all visual changes).

### Camera check (do the images reach Dream-1 correctly?)

Tool **Cameras**. Dream Labs' own tools show the frames to a person who types "yes" (`python -m dream.check`,
`dream.DebugView`); the only automatic check there is the frame rate. Here every frame Dream-1 was **actually sent**
(`DreamClient.on_round_trip`: the request as it left) is compared with the truth: the simulation renders every camera on
its own at every step. Each sent frame is matched (normalised correlation, 80 × 44 pixels) against every camera, the last
6 s of steps and every orientation. Per camera that gives:

- the right camera on the right key (a swapped or duplicated key shows up as the wrong camera / the same picture twice),
- upright and in natural colours (upside down, mirrored, red and blue swapped),
- current: lag behind the robot (> 250 ms is reported; frames are taken every 200 ms), frozen frames, order, frame rate,
- a real picture: blank or blown out, or one that matches no camera (cropped, zoomed, another source).

**Self-test:** a clean Dream-1 run plus one per fault injected on purpose between cameras and model (swapped wrists,
duplicate key, upside down, BGR, frozen, 0.6 s delay, black, zoomed). First real run: **8 of 8 caught, clean run clean**.
**Does Dream-1 use them?** freezes the scene and asks Dream-1 with each camera blanked and with the wrists swapped
(7 calls): which cameras the plan reacts to, against Dream-1's own noise.

Only a person may record Dream Labs' input check (`python -m dream.input_check`, "never an agent"); this check gives that
person the evidence. On a real robot the comparison with the truth is not available; the generic checks (key count,
size, blank, duplicates, frozen) still are.

### Model X-Ray (why Dream-1 does what it does)

Tool **X-Ray**. The robustness test shows *when* the model fails; the X-Ray shows *why*. It freezes one moment (the
camera windows Dream-1 sees, the joint state, the MuJoCo state) and asks Dream-1 about that same moment again, each time
with one thing changed. The simulation does not move meanwhile; what is measured is how the planned motion changes.

- **Live intent:** every reply of a Dream-1 run becomes gripper paths (forward kinematics of the 48 joint targets on a
  scratch copy of the MuJoCo state), drawn into the 3D view: orange = planned path of the acting arm, red dot = where
  the gripper closes, yellow = the object it heads for. Every moment of the run can be frozen afterwards.
- **1 · Intent** (3 calls): the plan for the frozen moment, asked three times. The spread between identical questions
  is the **noise floor** every other number is read against (Dream-1 is not necessarily deterministic).
- **2 · Where it looks** (masks + 6 calls): first **camera reliance**, the change when one camera is blanked
  completely. If no camera moves the plan by more than max(3 × noise, 1 cm), the masks are skipped (the heatmap would
  only show noise). Otherwise **RISE** on the camera whose blanking matters most, the other two left as they are: random
  smooth masks grey out a quarter of its window; per cell, importance = mean path change when it was hidden − when it
  was visible (cm). A permutation test gives the **chance level**; only cells above it are coloured. (Masking all
  three cameras at once, `camera="all"`, gave no signal on real Dream-1 even with 200 masks.)
- **3 · Does it follow the words?** (6 × repeats calls): same images, the original prompt and then only the object
  word swapped (apple, banana, orange, bottle, the made-up "blicket"). Per word: how much nearer the gripper paths get
  to the named object than with the original prompt; it "follows" when that is more than max(3 × noise, 1 cm) and more
  than towards any other object. This needs no grasp or clear approach in the plan, so it answers at any moment.

Results live in `out/extensions/xray/<moment>/`. `DREAM_XRAY_FAKE=1` swaps Dream-1 for a scripted stand-in
(`dreamtool/xray_fake.py`) to try the tool without credits; the panel then says so.

### Latency in the simulator (found in the night measurements, 22.11.)

The Dream client smooths every new chunk onto the old one (`dream.smoothing`, always on). It assumes the robot kept
moving while the request was in flight and replaces the first `round(round trip × action_hz)` rows of every new chunk
with the rest of the old plan (about 11 rows at 0.55 s). The simulator pauses physics during every request, so that is
an artificial reaction delay, and a random one because the round trip varies: with an identical scene and a
deterministic Dream-1, "repeated" trials still came out differently, and re-planning every 8 rows never executed a
single row of a new plan. The runner now tells the client that no rows run during a request (`latency="paused"`,
`action_hz` ≈ 0, so the hand-over starts at row 0). `latency="client"` restores the old behaviour for comparison;
results recorded before the fix are marked "client latency" in the run list. Details: `NIGHTLY_REPORT.md`.

### Inference strategies (better behaviour without fine-tuning)

Dream-1 returns 48 joint targets per arm (2.4 s) per request. How much of that is executed before asking again, and how
consecutive plans are combined, is our choice (`dreamtool/inference.py`):

| Strategy | What it does | Trade-off |
| --- | --- | --- |
| `chunk` | execute all 48 rows, then ask again | open loop for 2.4 s; visible jump at every seam |
| `receding-N` | execute the first N rows, discard the rest, ask again | reacts faster to what the cameras see, but every new plan may start elsewhere |
| `ensemble-N` | ask every N steps, average the arm joints of all plans covering a step (weight `exp(-0.05·steps ahead)`, as in ACT) | averages out plan-to-plan noise, follows a new plan with lag and can slow the arm down |
| `crossfade-N` | ask every N steps, fade the arm joints linearly from the old plan to the new one over N rows | no seam jumps and fully on the new plan after N steps |

The dashboard runs **`crossfade-30`** unless told otherwise (`inference.DEFAULT`); the library's `run_task()` keeps `chunk`, the model's plain output. Measured on 22.11.2026 with real Dream-1 on the same scenes (all campaigns pooled, [NIGHTLY_REPORT.md](NIGHTLY_REPORT.md)): crossfade-30 succeeded in 9 pairs where the full chunk failed and never the other way round (32 pairs, McNemar p = 0.004, progress +0.36 [+0.24, +0.48]); receding-24 +0.30 [+0.19, +0.40] over 62 pairs. The full chunk mostly fails before the grasp (38 of 52 apple trials). Horizons of 8 and 16 rows and the ensemble were no better or worse than the chunk and are no longer in the menu (any `<kind>-<rows>` still works).

Blends never touch the gripper: it always follows the newest plan. (A first Dream-1 comparison averaged the gripper
too; `ensemble-16` then lifted the apple and lost it on the way in 3 of 4 trials.)

All of them cost about 48/N times the requests. Pick one in the dashboard's prompt bar (**Execution**), per robustness
campaign, with `python run.py "..." --strategy ensemble-16`, or compare them with **Strategy A/B**. Every run reports
`commands` (seam jump relative to a normal step, speed, jerk, jitter) next to the result. Smoothness is judged by the
**jitter share** (the part of the joint motion left over after a 0.45 s moving average), not by absolute jerk: absolute
jerk mostly measures speed, so a strategy that just slows the arm down would look smooth.

Deliberately left out: latency (the sim pauses physics while waiting for Dream-1, so delays change nothing) and
joint-encoder noise (real encoders are precise; the noise would also leak into the hold commands).

### Teaching loop: Take over and episodes

Every Dream-1 run started with **Run** is recorded as an episode (LeRobot v2.1, the format Dream Labs checks before a
fine-tune: 3 camera videos at 640 x 360, 10 frames per second, arm values right arm first).

1. Run a task. If Dream-1 fails, or while it works, press **Take over**: Dream-1 stops, the scene stays as it is.
2. Finish the task with **Control**. Recording continues.
3. **Save episode**: the success check marks it. **Discard** deletes it.
4. Tool **Episodes**: what is ready for a fine-tune, success and cost per model, where a person took over.
   **Export** copies all unused successful episodes of one task into `out/exports/<name>/` and runs Dream Labs' own
   dataset check. Nothing is uploaded.

Records live in `out/lab.db` (SQLite: one file, no server; not in git) and `out/episodes/`.

**Success check:** the task types it understands are listed in Episodes, for example "put the banana on the plate",
"lift the apple", "push the orange left", "put the apple next to the bowl", "stack the orange on the apple",
"take the apple out of the bowl", "stand the bottle upright", "put all fruit in the bowl", and two of them joined by
"then". A new task type is one entry in `RULES` in `dreamtool/scene.py`.

### Credits

When the money or the monthly limit is used up, the top bar shows it; tool **Credits** shows today, this month, the last run, a chart of the last 30
days, the price per call and the limits (model and time limit stay in the prompt bar). The Dream Labs API does not report the balance, so the
dashboard counts calls x price from a starting balance typed in by a person (default $150).

- Before a run: an estimate. Above "Ask before a run that costs more than" (default $0.10) Run needs a second click.
- Monthly limit (default $100): a run that could pass it is refused, and a running run (also a robustness campaign)
  stops when the limit is reached.
- The time limit counts simulated seconds: waiting for Dream-1 and a slow laptop do not use it up.

### Multiplayer: a second person controls one arm

One laptop, the host, runs everything; the other person only needs a web browser.

Setup on the host laptop (once): install Cloudflare's `cloudflared`. The dashboard looks for it in `$CLOUDFLARED`,
on the PATH, and in `~/Hacklab/bin/` (`cloudflared.exe` on Windows).

```powershell
winget install --id Cloudflare.cloudflared
```

On Windows without winget, download `cloudflared-windows-amd64.exe` from
<https://github.com/cloudflare/cloudflared/releases/latest> and save it as `%USERPROFILE%\Hacklab\bin\cloudflared.exe`.
On Linux:

```bash
mkdir -p ~/Hacklab/bin && cd ~/Hacklab/bin
curl -fsSL -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared
```

Each session:

1. Start the dashboard on the host laptop.
2. Tool **Players** → **Open a public link**. After a few seconds a link like
   `https://<words>.trycloudflare.com` appears, with the **access code** (new at every start of the dashboard).
3. Send both to the other person. They open the link, type the code and a name, take an arm in **Players**, and move
   it in **Control**.

What a guest can do: watch (the main view smaller, 12 pictures per second, to save bandwidth), and move the one arm
they took. Run, Stop, Home, Reset, Take over, the Test Suite, episodes and credits stay with the host (a guest does not
see those buttons). The host can move every arm no
guest holds, and can free an arm. A quick link needs no Cloudflare account; it changes every time it opens.

### Second brain

`brain/` is the team's shared memory, after Andrej Karpathy's "LLM wiki" idea: the dashboard writes every Dream-1
run, robustness campaign and export into `brain/raw/` by itself (plus a daily summary from the lab database); the
script `brain/build_wiki.py` then makes the wiki pages in `brain/wiki/` (per task, per model, robustness, exports,
notes, decisions); people read the wiki, for example in Obsidian. Run it by hand with `python brain/build_wiki.py`.
An AI agent (rules in `brain/AGENTS.md`) is planned for later. See [brain/README.md](brain/README.md).

### Architecture diagrams

[docs/architecture/DreamLab-Rat-architecture.docx](docs/architecture/DreamLab-Rat-architecture.docx) (Word) holds the
deployment diagram, the C4 diagrams (levels 1 to 3), the layers and the teaching loop, with a table for each. The
pictures are also in [docs/architecture/png/](docs/architecture/png/). After a change to the system, update
`docs/architecture/diagrams.py` and `make_docx.py` and run:

```bash
python docs/architecture/diagrams.py docs/architecture/png
python docs/architecture/make_docx.py docs/architecture/png docs/architecture/DreamLab-Rat-architecture.docx
```

**Building a new feature:** copy `dashboard/extensions/_template` → see
[dashboard/EXTENSIONS.md](dashboard/EXTENSIONS.md).

## Documentation

| Document | What it covers |
| --- | --- |
| This README | setup, every dashboard feature, CLI, hooks |
| Tutorial button in the dashboard | guided tours of the page (see Tutorial above) |
| [dashboard/EXTENSIONS.md](dashboard/EXTENSIONS.md) | writing your own extension (backend, panel, test types) |
| [BRIEFING.md](BRIEFING.md) | technical briefing for the presentation: model I/O, strategies, cameras, results |
| [NIGHTLY_REPORT.md](NIGHTLY_REPORT.md) | the measurement night of 22.11.2026: what was measured and fixed |
| [TEST_OVERVIEW.md](TEST_OVERVIEW.md) / [test-overview.html](test-overview.html) | what the automated tests and measurements cover |
| [docs/architecture/](docs/architecture/) | deployment, C4 and layer diagrams (Word + PNG) |
| [docs/fork-here.md](docs/fork-here.md) | Fork Here: replaying a run from a checkpoint with a release guard |
| [docs/demo-checklist.md](docs/demo-checklist.md) | a credit-free demo, step by step |
| [docs/overlay-alignment.md](docs/overlay-alignment.md) | which overlay is drawn where (MuJoCo vs. browser) |
| [docs/known-limitations.md](docs/known-limitations.md) / [docs/training-readiness.md](docs/training-readiness.md) | what is not covered yet |
| [brain/README.md](brain/README.md) | the second brain (team wiki) |
| `docs/overnight-*.md` | the stabilisation sprint of 21.–22.11. (a snapshot of that time) |

Every Python module starts with a docstring that explains its part; the JavaScript files start with a comment.

## Getting started (CLI)

```powershell
python check_setup.py --online       # all green? (--online checks the key against the API)
python -m pytest -q                  # offline tests (Python, about 2 minutes)
node tests/test_tutorial_ui.mjs      # browser-side checks (also test_run_analysis_ui.mjs, test_viewer_overlay_ui.mjs)
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
