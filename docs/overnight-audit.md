# Dream‑1 Lab sprint audit

The sprint started from `fix/teleop-and-campaign-progress` at `564b3ba`, with earlier campaign-recovery work already in the working tree. The sprint branch is `codex/overnight-stabilization`. The existing port 8000 backend reported a ready simulator and loaded Scene Inspector, Teleop, Robustness and Test Suite.

| Area | Entry point and observed implementation |
| --- | --- |
| Browser | `dashboard/static/index.html` and `app.js` are native HTML and ES modules. Extensions supply their own panels. |
| Server and state | `start.py` starts FastAPI/Uvicorn. `dashboard/app.py` provides routes and MJPEG streams. `events.py` provides WebSocket updates and log replay. |
| Inference | `dreamtool/runner.py` uses the Dream SDK through bundled YAM simulation helpers. The client reads its local credentials through the existing SDK loader. |
| Simulation | `dashboard/simulation.py` owns one MuJoCo worker and the free camera and wrist/overhead streams. Home moves the arms. Reset restores the scene. |
| Standard campaigns | `dashboard/extensions/test_suite` schedules runs, checks state-based placement and saves local reports and media. Repeated Runs and paired A/B comparisons are available. |
| Robustness | `dashboard/extensions/robustness` owns its separate sweep, mix and adaptive algorithms. Both runners already use a shared campaign recovery coordinator in the incoming working changes. |
| Evaluation | `evaluation.py` and `metrics.py` track destination, release, stability and verification coverage separately from execution status. |
| Billing and episodes | The core state exposes API-key presence as a boolean. The audited local dashboard has no configured dollar-spend enforcement or general-purpose Take Over → Save Episode → Discard workflow. Campaign videos are separate from training episodes. |

The main admission risk was that HTTP callers could check idle concurrently, and the worker could disappear from the queue before announcing itself as current. Reset also logged completion immediately after queuing. Prioritize these before adding new workflows. See [verification results](overnight-test-results.md) and [limitations](known-limitations.md).
