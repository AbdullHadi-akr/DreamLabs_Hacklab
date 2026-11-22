# Overnight test results

> **Snapshot** of the overnight stabilisation sprint (21.–22.11.2026), kept as it was written. Several points are outdated since: the dashboard now has credit limits that stop runs, the Take over → Save episode → Discard workflow with LeRobot recording, and a guided tutorial. The current state is in the [README](../README.md) and [known-limitations.md](known-limitations.md).

| Check | Result |
| --- | --- |
| Baseline full Python suite | 127 passed before the sprint changes, including both offline Robustness integrations. |
| Full Python rerun after admission fix | 124 passed, 4 failed. Failures were the first JPEG snapshot returning 404, the dry sweep and adaptive integrations exceeding their 60- and 120-second deadlines, and the keyboard jog showing no measured movement within its settling check. |
| Focused final Python suite | 40 passed. Covers admission, placement evaluation, managed-run timeout and provider limits, recovery, report assets and exports. |
| Final Dashboard integration subset and new admission test | 8 passed, with the two longer Robustness cases deselected in this subset. |
| Startup regression | 2 passed after the first-frame fix. The snapshot integration test no longer sleeps before requesting a JPEG. |
| Isolated Teleop keyboard jog rerun | 1 passed, 9 deselected. The full-suite failure did not reproduce in isolation. |
| Frontend regression harness | Passed. Covers report navigation, per-run analysis, print return, and offline response-time display. |
| Waterfox smoke | Opened the running localhost Test Suite, saw the simulation viewport, and loaded a saved campaign and its export controls. |
| HTTP smoke | Dashboard HTML, main simulator JPEG and backend health responded successfully on port 8000. |
| Static checks | Python compilation and Git whitespace checks passed. No configured type checker or linter was found. |

The stress test admitted one request from a burst of 16 and rejected the other 15 with HTTP 409. It then exercised 100 sequential mock completions through the actual HTTP admission route and queue. The queue and outstanding work were empty afterward. It checked repeated Stop, reset completion, whitespace-only form fields and controls during campaign ownership. It used mocked execution and did not establish a robot success rate.

The existing browser harness uses a simulated DOM. The full six-resolution layout matrix, browser-console sweep, malformed-response stress matrix and memory profiling remain open. The normal backend on port 8000 predates the sprint commit. The newer code was exercised by the integration test process.

The startup-frame fix was applied after the full rerun reproduced the JPEG failure. The final focused Dashboard group passed with that fix. The two Robustness timeouts have also occurred in earlier verification, and this sprint left the Robustness execution algorithms alone.

Zero live inference calls were made. The published account balance could not establish an enforceable per-run spending bound, so both live placement benchmarks were skipped.
