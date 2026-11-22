# Fine-tuning: our four questions, answered from Dream Labs' documentation and code

We did not send the four questions to Dream Labs. Most answers are in Dream Labs' own documentation
(https://platform.dreamlabs.ai/docs/fine-tuning/, /docs/control-loop/, /docs/examples/yam-mujoco/, read on
22 November 2026) and in their dataset checks (`dreamlabs/shared/datasets/validation.py`, `content_checks.py`). Where
neither says it, the answer is our own assumption and is marked so.

## 1. Is simulated data accepted?

- Their checks do not tell simulated recordings from real ones: a LeRobot v2.1 folder that passes `validate_dataset`
  can be uploaded. Our exports already pass it.
- But the tutorial says: "Fine-tuning is for new robots, not for automating a task. It teaches Dream-1 your robot's
  body." Dream-1 already runs on the YAM arms without training. A fine-tune on our simulated YAM to make one task
  work is outside what Dream Labs says fine-tuning is for. For task automation they name deployments@dreamlabs.co.

## 2. What does one training job cost?

- $0.20 per training step at the time of writing: $100 for the smallest job (500 steps), $200 for the default
  1,000 steps, $2,000 for 10,000. The price is held from the credits when the job is queued.
- A fine-tuned model then costs $0.0028 per call, twice the base model.
- Time: about 7 to 8 hours for 1,000 steps, plus up to 1 hour for the first start of the new model.
- Our dashboard has a monthly limit of $100 and started with $150 of credit: the smallest job uses the whole monthly
  limit.

## 3. The whole episode, or only the part after the take-over?

- Not in their documentation. Training learns every frame it gets the same way; the format has no way to mark a part.
- Our assumption: frames where Dream-1 went wrong would teach the mistake, so an episode with a take-over is exported
  from the take-over to the end only. Episodes Dream-1 finished alone go in whole.

## 4. Is recording at 10 frames per second right?

- Yes. Training runs at 30 fps and takes 30, 15, 10 or 5 (it brings the slower ones up to 30). Our simulation steps
  20 times per second, so 10 is every second step; 15 and 30 do not divide 20, and 20 is not taken.
- The shortest episode is 1.6 s from the first frame to the last: 17 frames at 10 fps. Our limit was 16; corrected.

## Also answered: 20 or 30 rows per second?

- The model learned its 48 rows 1/30 s apart (1.6 s). Dream Labs' own control loop plays them 20 per second
  (`action_hz` 20, `execution_horizon` 30 rows), so a chunk takes 2.4 s. Our simulation does the same, so this is not
  a mistake on our side.

## For a fine-tune later (what the tutorial needs)

- Register our robot body once with `client.add_embodiment(name, config)`; our `YAM_CONFIG` in
  `dashboard/episodes.py` already has the tutorial's shape (state, action, video, head_camera "overhead").
- `client.validate_dataset`, `client.upload_dataset`, `client.get_dataset_status`, `client.finetune`,
  `client.get_finetuning_status`; the model id is `dream-1-ft:<account>-<suffix>`.
- Running the fine-tune needs the body's own keys (`state.right_arm`, `video.overhead` ...), not the YAM station keys
  the base model gets, and `obs_fps` = recording fps / 6.

Decision: Our 4 questions to Dream Labs are answered from their documentation and code; we do not send them.
Decision: Episodes with a take-over are exported from the take-over to the end only; episodes Dream-1 finished alone go in whole.
Decision: We keep recording at 10 frames per second; the shortest episode we export is 17 frames (1.7 s).
Open question (Hasnat decides): do we start a fine-tune at all? Dream Labs says fine-tuning is for new robots, not for
one task, and the smallest job costs $100, our whole monthly limit.
