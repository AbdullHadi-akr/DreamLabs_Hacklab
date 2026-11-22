<!-- made by brain/build_wiki.py: do not edit by hand, the script rewrites this page -->
# Robustness campaigns

This page lists every robustness campaign: a series of Dream-1 runs where the dashboard changes the scene step by step to find where Dream-1 starts to fail.

*Made by the script `brain/build_wiki.py` from `brain/raw/`. Changes by hand are lost at the next build.*

| Campaign | Task | Mode | Policy | State | Cost | Verdict |
|---|---|---|---|---|---|---|
| 20261122-111934-target_shift | [[tasks/put-apple-into-the-bowl|put apple into the bowl]] | sweep, perturbation: Move target object | scripted blind replay (dry run) | done, 5 of 5 trials | $0.0000 | Robust up to 4 cm, breaks at 6 cm (success rate at half the baseline or below) |
| 20261122-112001-compare | [[tasks/put-apple-into-the-bowl|put apple into the bowl]] | compare | scripted replay in noisy chunks (dry run) | done, 12 of 12 trials | $0.0000 | No difference so far: every strategy succeeded 4/4. |
| 20261122-112150-target_shift | [[tasks/put-apple-into-the-bowl|put apple into the bowl]] | adaptive | scripted blind replay (dry run) | done, 8 of 8 trials | $0.0000 | “Success” breaks at ≈ 4.1 cm (80 % interval 2.3–6.1 cm) — still uncertain, more trials would narrow it |
| 20261122-112244-random | [[tasks/put-apple-into-the-bowl|put apple into the bowl]] | random | scripted blind replay (dry run) | done, 10 of 10 trials | $0.0000 | Most harmful: Move target object (ρ = -0.81 with progress) — only 10 trials, treat as a hint |
| 20261122-112521-target_shift | [[tasks/put-the-apple-into-the-bowl|put the apple into the bowl]] | sweep, perturbation: Move target object | scripted blind replay (dry run) | stopped, 0 of 15 trials | $0.0000 | No trials yet. |

## Sources

- `raw/robustness/20261122-111934-target_shift.md`
- `raw/robustness/20261122-112001-compare.md`
- `raw/robustness/20261122-112150-target_shift.md`
- `raw/robustness/20261122-112244-random.md`
- `raw/robustness/20261122-112521-target_shift.md`
