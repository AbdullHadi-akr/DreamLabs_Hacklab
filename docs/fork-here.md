# Fork Here

Fork Here compares two simulator continuations for **banana to plate**. The baseline executes the returned full action chunks. The guarded continuation blocks the acting gripper’s first command to open outside the plate region and asks once for a new plan. It stops if the next plan tries another early release or if the verified grasp is lost before an allowed release. MuJoCo contact, position and stability observations determine the outcome.

## Run the offline demo

From the feature worktree, point `DREAM_SIM_DIR` at the documented YAM simulator example and use the project's Python environment. The following command reuses the dependencies from the original checkout on this Mac:

```sh
cd /private/tmp/dream1-fork-here
project=/Users/moritz/Documents/DreamLabs_Hacklab
DREAM_SIM_DIR="$project/dreamlabs/dream_library/examples/yam_mujoco" \
DREAM_LAB_DB="$PWD/out/fork-demo-v2.db" \
DREAM_BRAIN_DIR="$PWD/out/fork-brain" \
"$project/.venv/bin/python" start.py --port 8012 --no-browser
```

1. Open `http://localhost:8012/` and choose **Test Suite → Build → Run Fork Here demo (offline)**. This resets the demo scene and opens its campaign report.
2. Wait for the report to record Run 1. In **Individual run analysis**, the snapshot timeline shows visual evidence of pickup. Open **Fork here**.
3. Check that the pair's API request limit and cost are both zero. Select **Start comparison** and wait for Baseline and Release guard.
4. Compare the two cards. Both should verify the same saved start. The baseline drops the banana outside the plate. The guard blocks that command, requests one scripted replan, and places and releases the banana on the plate.

Run data and snapshots are stored under this checkout’s ignored `out/extensions/test_suite` directory. Comparison results are separate JSON files under the original campaign’s `comparisons` directory. The origin report stays intact. **Stop comparison** cancels at the next control boundary or after the outstanding request returns.

## Supported boundary and limits

- One post-pickup checkpoint per eligible banana-to-plate Quick Test. The executor uses full chunks and pauses physics during requests. Crossfades, ensembles, other tasks and ordinary dry runs have no restorable checkpoint. Existing reports and snapshots remain readable.
- The checkpoint stores MuJoCo integration state, the most recent commands, scene fingerprint, task, model, evaluator progress, camera JPEG history and order, observation hash, and remaining time and request budget. Restoration checks the scene fingerprint, physics and controller state, and the reconstructed observation before the first request.
- Both live branches use fresh SDK sessions. Identical saved inputs do not restore remote session memory or guarantee identical replies. The guard supplies a fresh camera tick and current state at intervention. An individual live pair illustrates behavior. Estimating a reliability difference requires multiple independent pairs.
- Each branch has a 160-step continuation ceiling, the remaining origin wall-clock time and a conservative request cap. One additional request is available to the guarded branch after intervention. Live launch requires a known model price, sufficient local credit and monthly headroom, a configured key and explicit confirmation. Failed requests count in the run ledger. No paid comparison was used for verification.

To run the focused integration tests, use the same `DREAM_SIM_DIR` with `python -m pytest -q tests/test_fork_here.py`. The tests use real MuJoCo physics, deterministic camera fixtures and a fake policy for the live admission and failed-request paths.
