# Training readiness

Updated 22.11.2026.

**Episodes for a fine-tune.** Every Dream-1 run started with **Run** on the Dashboard is recorded as an episode
(`dashboard/episodes.py`): a LeRobot v2.1 folder with the three camera videos at 640 × 360, 10 frames per second, and
per frame the measured joint state and the commanded action (the targets the arms were sent right after that frame),
right arm first, as Dream Labs lays out the YAM body. A person can take over and finish the task with the Control
tool; the recording continues. **Export** (tool Episodes) copies the successful, unused episodes of one task into
`out/exports/<name>/` and runs Dream Labs' own dataset check (`dream.datasets.validate_dataset`). An episode with a
take-over goes in cut, from the take-over on, so training does not learn Dream-1's mistake. Nothing is uploaded.

**Other artifacts** are review material, not training data: Test Suite reports (prompt, model, timing, initial and
final state, evidence frames, optional MP4s, saved reply chunks) and robustness videos. A saved reply chunk does not
say which of its rows actually ran after an interruption, clipping or validation.

**Before a fine-tune:**

- Recording consent and the task text per episode are the team's responsibility.
- Episodes shorter than Dream Labs' minimum (17 frames at 10 per second, 1.7 s) are marked and left out of an export.
- Upload and fine-tuning are separate steps (Dream Labs' client: `upload_dataset`, `finetune`); no dataset has been
  uploaded or trained on from this tool so far.
