# Dream‑1 Lab engineering handoff

> **Snapshot** of the overnight stabilisation sprint (21.–22.11.2026), kept as it was written. Several points are outdated since: the dashboard now has credit limits that stop runs, the Take over → Save episode → Discard workflow with LeRobot recording, and a guided tutorial. The current state is in the [README](../README.md) and [known-limitations.md](known-limitations.md).

## Executive summary

Dashboard execution now has a single admission decision for concurrent Run, Home, Stop and Reset requests. A run stays busy during the queue-to-worker handoff. The demo workflow continues to use the existing renderer, Test Suite and saved reports.

## Repository status

Local branch `codex/overnight-stabilization`. The latest implementation commit is `0bbab74`, following `062d326`. Changes cover `dashboard/app.py`, `dashboard/simulation.py`, `tests/test_dashboard.py` and the new `tests/test_dashboard_admission.py`. The follow-up documentation commit adds the six files under `docs/`. Incoming campaign-recovery edits remain in the working tree, including the existing changes under Robustness.

## Bugs fixed

- Concurrent Dashboard requests could both pass the idle check before either queued a run. The HTTP control routes now serialize that decision and respect campaign ownership when the recovery coordinator is present. The concurrent HTTP test admitted exactly one of 16 requests.
- A dequeued run briefly disappeared from the busy check before the worker announced it as current. The worker now tracks outstanding run futures until completion or cancellation. A test explicitly dequeues a run before attempting a second submission.
- Reset reported completion as soon as it was queued. Logging now follows the simulator reset call, failures are logged separately, and new Dashboard starts wait while reset is pending. The HTTP test exercises the pending and completed paths.
- Whitespace-only task and model values could pass length checks. Validation trims inputs before checking their bounds, and execution routes reject requests when the simulator is unavailable.
- The simulator reported readiness before rendering its first frame. Startup now publishes the initial frames first, and the snapshot test requests the JPEG immediately after startup.

## Automated testing

See [test results](overnight-test-results.md) for the baseline, final verification, browser smoke and skipped matrices.

## Real robot benchmark

Skipped both live placement benchmarks. The app can count requests but cannot enforce the sprint’s $5 cap in dollars. The sprint used zero live inference calls.

## Performance

After 100 sequential mocked completions, the worker queue and outstanding work were empty. No rendering or memory improvements were quantified.

## Training readiness

Camera recordings, reports and model replies are useful review artifacts. A verified synchronized training trajectory is still required. [Training-readiness assessment](training-readiness.md)

## Remaining issues

- P0 — A live unattended benchmark needs an enforceable financial budget.
- P1 — The full rerun hit two Robustness replay deadlines and one Teleop settling failure. Live provider execution and physical outcomes remain unmeasured.
- P2 — Complete the six-resolution browser matrix, console capture and memory profiling.
- P3 — Leave cosmetic refinements behind the demo-critical checks.

## Demo readiness

The running local service served the dashboard and a simulator frame. Waterfox opened a saved campaign report. Use the [demo checklist](demo-checklist.md) for a credit-free demonstration and the [audit](overnight-audit.md) for architecture details.

## Recommended next actions

1. Rehearse the offline dashboard and saved report workflow at the presentation resolution.
2. Keep one saved report with clear placement evidence ready for the report and export walkthrough.
3. Confirm the provider’s billing limit before any live demo run.
