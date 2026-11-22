<!-- made by brain/build_wiki.py: do not edit by hand, the script rewrites this page -->
# Task: apple into the bowl

This page shows how often the task "apple into the bowl" succeeded, with which model, and what it cost.

*Made by the script `brain/build_wiki.py` from `brain/raw/`. Changes by hand are lost at the next build.*

## Measured

- Dream-1 runs: 10; with a success check: 10; successes: 0 (0 %)
- Dream-1 calls: 52; cost: $0.0728; cost per success: -
- Last run: 2026-11-22 11:17:40

## Per model

| Model | Runs | Successes | Success rate | Calls | Cost | Cost per success |
|---|---|---|---|---|---|---|
| [[models/dreamlabs-dream-1-beta|dreamlabs/dream-1-beta]] | 10 | 0 | 0 % | 52 | $0.0728 | - |

## Wordings

The same goal, said in different ways (the task text of each run).

| Wording | Runs | Successes | Success rate |
|---|---|---|---|
| put apple into the bowl | 9 | 0 | 0 % |
| put the apple into the bowl | 1 | 0 | 0 % |

## Why the runs stopped

| Stop reason | Runs |
|---|---|
| timeout | 10 |

## Robustness campaigns

- 20261122-111934-target_shift: Robust up to 4 cm, breaks at 6 cm (success rate at half the baseline or below)
- 20261122-112001-compare: No difference so far: every strategy succeeded 4/4.
- 20261122-112150-target_shift: “Success” breaks at ≈ 4.1 cm (80 % interval 2.3–6.1 cm) — still uncertain, more trials would narrow it
- 20261122-112244-random: Most harmful: Move target object (ρ = -0.81 with progress) — only 10 trials, treat as a hint
- 20261122-112521-target_shift: No trials yet.

## Sources

- `raw/robustness/20261122-111934-target_shift.md`
- `raw/robustness/20261122-112001-compare.md`
- `raw/robustness/20261122-112150-target_shift.md`
- `raw/robustness/20261122-112244-random.md`
- `raw/robustness/20261122-112521-target_shift.md`
- `raw/runs/2026-11-22.md`
