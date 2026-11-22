# Overview

This page explains what DreamLab-Rat is and how the team uses it.

## What DreamLab-Rat is

A dashboard that runs a simulated YAM robot: two arms at a table with fruit, a bowl and a plate. Dream-1, a robot
model by Dream Labs, gets a task in words, for example "put the banana on the plate", and moves the arms. The
dashboard checks from the object positions whether the task succeeded.

## The teaching loop

1. A person gives Dream-1 a task.
2. Dream-1 tries. The dashboard records the try.
3. If Dream-1 fails, a person presses "Take over" and finishes the task by remote control.
4. The dashboard saves the episode and marks it as success or not.
5. Successful episodes of one task are exported together and checked with Dream Labs' own dataset check.
6. The export is used to fine-tune Dream-1 (train it further on our episodes).
7. The fine-tuned model tries the same task again; the lab database shows if it got better and what it cost.

## Where the facts are

- Runs, cost and success: `raw/runs/` and `raw/summaries/`.
- Robustness campaigns: `raw/robustness/`.
- Exports for fine-tuning: `raw/exports/`.
- Team notes: `raw/notes/`.
