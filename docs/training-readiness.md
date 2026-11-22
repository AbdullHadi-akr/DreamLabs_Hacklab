# Training readiness

Standard Test Suite reports contain prompt and model metadata, run timing, initial and final state, result evidence and references to optional camera MP4s. Some runs also retain action replies and timestamped milestone frames in separate files. Robustness can record composite camera video alongside trial metadata.

These artifacts support evaluation and debugging. The audited recorder does not establish a synchronized sequence of observations, measured joint states, commanded/executed actions, camera calibration, and timestamps at every control step. Saved policy reply chunks do not establish which actions actually ran after interruption, clipping, or validation.

For training, first confirm the SDK dataset schema and validate a purpose-recorded trajectory with aligned observations and executed action/state samples, task text, embodiment, timing, and recording consent. Keep the source records intact. No datasets were converted, uploaded, or used for training during this sprint.
