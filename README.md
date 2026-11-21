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
- **Offline demo**, **Home**, **Reset** and the **dry run** in the Robustness tab cost no credits.
  The **run** button and sweeps without dry run call Dream-1.
- The server only listens locally (127.0.0.1); other laptops reach it only through the public link (see Multiplayer). Ctrl+C stops it.

### Robustness test

Tab **Robustness**: change the world on purpose and see how and when Dream-1 fails.

- **Sweep:** one perturbation at increasing strength (e.g. move the apple 0/2/4/6/8 cm) → success rate with a 95 %
  interval per strength, progress score, and the **breaking point** (first strength at half the baseline or below).
  The unperturbed baseline is always included; trial *i* uses the same random draw at every strength.
- **Random mix:** every trial draws random strengths for several perturbations → which factor hurts most
  (rank correlation with the progress score).
- **15 perturbations** in five groups: scene layout (target/container/other objects moved, target rotated), vision
  (camera shifted/tilted, dimmer light, table/target recolored, sensor noise), physics (heavier target, slippery
  gripper pads), language (typos, rewordings) and during the run (target moved the moment the gripper arrives).
- **How it failed**, not just whether: every trial is classified (never reached, no grasp, pushed away, wrong object,
  lost on the way, placed next to the container, knocked off the table) with a progress score 0 / .25 / .5 / .75 / 1.
  That gives a readable curve with only a few (expensive) trials.
- **Fair trials only:** each setup is checked (on the table, in reach, no overlaps, not already solved) and re-drawn
  if needed; a trial that ends with the target on the floor stops early to save credits.
- **Report page** with chart, tables, Dream-1 calls and cost per trial, and an MP4 of every trial when
  "Record video" is on (off by default: videos cost disk space and time). **Report (one file)** downloads the whole
  report as one HTML file that opens without the dashboard; **Report with videos** puts the videos inside it too.
  Results live in `out/extensions/robustness/<campaign>/`. The time limit counts simulated seconds.
- **All runs, heatmap & downloads** (`/ext/robustness/runs.html`, linked in the tab): every stored run, a
  **robustness map** (heatmap: perturbation × strength, colored by success rate or progress score, filtered by task
  and policy so dry runs and Dream-1 are never pooled) and downloads per run (CSV, Excel CSV, JSON, ZIP with videos)
  or for all filtered trials at once. The report page adds a trial × strength grid (sweep) or a two-factor heatmap
  (random mix).
- **Dry run** (default) replays a scripted pick-and-place planned once on the unperturbed scene: no credits, and a
  reference for a policy that does not look (it breaks at ~2 cm and ignores all visual changes).

Deliberately left out: latency (the sim pauses physics while waiting for Dream-1, so delays change nothing) and
joint-encoder noise (real encoders are precise; the noise would also leak into the hold commands).

### Teaching loop: Take over and episodes

Every Dream-1 run started with **Run** is recorded as an episode (LeRobot v2.1, the format Dream Labs checks before a
fine-tune: 3 camera videos at 640 x 360, 10 frames per second, arm values right arm first).

1. Run a task. If Dream-1 fails, or while it works, press **Take over**: Dream-1 stops, the scene stays as it is.
2. Finish the task with **Control**. Recording continues.
3. **Save episode**: the success check marks it. **Discard** deletes it.
4. Menu **Episodes**: what is ready for a fine-tune, success and cost per model, where a person took over.
   **Export** copies all unused successful episodes of one task into `out/exports/<name>/` and runs Dream Labs' own
   dataset check. Nothing is uploaded.

Records live in `out/lab.db` (SQLite: one file, no server; not in git) and `out/episodes/`.

**Success check:** the task types it understands are listed in Episodes, for example "put the banana on the plate",
"lift the apple", "push the orange left", "put the apple next to the bowl", "stack the orange on the apple",
"take the apple out of the bowl", "stand the bottle upright", "put all fruit in the bowl", and two of them joined by
"then". A new task type is one entry in `RULES` in `dreamtool/scene.py`.

### Credits

The top bar shows the balance left; menu **Credits** shows today, this month, the last run, a chart of the last 30
days, the price per call, the model and the time limit. The Dream Labs API does not report the balance, so the
dashboard counts calls x price from a starting balance typed in by a person (default $150).

- Before a run: an estimate. Above "Ask before a run that costs more than" (default $0.10) Run needs a second click.
- Monthly limit (default $100): a run that could pass it is refused, and a running run (also a robustness campaign)
  stops when the limit is reached.
- The time limit counts simulated seconds: waiting for Dream-1 and a slow laptop do not use it up.

### Multiplayer: a second person controls one arm

One laptop, the host, runs everything; the other person only needs a web browser.

Setup on the host laptop (once):

```bash
mkdir -p ~/Hacklab/bin && cd ~/Hacklab/bin
curl -fsSL -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared
```

Each session:

1. Start the dashboard on the host laptop.
2. Menu **Players** → **Open a public link**. After a few seconds a link like
   `https://<words>.trycloudflare.com` appears, with the **access code** (new at every start of the dashboard).
3. Send both to the other person. They open the link, type the code and a name, take an arm in **Players**, and move
   it in **Control**.

What a guest can do: watch (the main view smaller, 12 pictures per second, to save bandwidth), and move the one arm
they took. Run, Stop, Reset, robustness, episodes and credits stay with the host. The host can move every arm no
guest holds, and can free an arm. A quick link needs no Cloudflare account; it changes every time it opens.

### Second brain

`brain/` is the team's shared memory, after Andrej Karpathy's "LLM wiki" idea: the dashboard writes every Dream-1
run, robustness campaign and export into `brain/raw/` by itself (plus a daily summary from the lab database); an AI
agent reads `brain/AGENTS.md` and keeps `brain/wiki/` up to date (write `ingest` to it); people read the wiki, for
example in Obsidian. See [brain/README.md](brain/README.md).

### Architecture diagrams

[docs/architecture/Dream-1-Lab-architecture.docx](docs/architecture/Dream-1-Lab-architecture.docx) (Word) holds the
deployment diagram, the C4 diagrams (levels 1 to 3), the layers and the teaching loop, with a table for each. The
pictures are also in [docs/architecture/png/](docs/architecture/png/). After a change to the system, update
`docs/architecture/diagrams.py` and `make_docx.py` and run:

```bash
python docs/architecture/diagrams.py docs/architecture/png
python docs/architecture/make_docx.py docs/architecture/png docs/architecture/Dream-1-Lab-architecture.docx
```

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
