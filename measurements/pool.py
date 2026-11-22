"""Pools every strategy-comparison campaign of a night: per prompt and strategy, all trials together.

python measurements/pool.py <out.md> <campaign id> ...

Unpaired totals (Wilson 95 % intervals) plus the paired comparison against the full chunk where both ran on the same
seed. Trials that ended in an error or an invalid setup are counted separately and never as failures of the model.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze import SCORED, load, pct, pooled  # noqa: E402
from dashboard.extensions.robustness.analysis import wilson  # noqa: E402


def main(out, ids):
    results = [load(i) for i in ids]
    cells = defaultdict(list)
    errors = defaultdict(int)
    for res in results:
        task = res["config"]["task"]
        for r in res["rows"]:
            key = (task, r.get("strategy") or res["config"].get("strategy", "chunk"))
            if SCORED(r):
                cells[key].append(r)
            else:
                errors[key] += 1
    lines = ["| Prompt | Strategy | Trials | Success | 95% CI | Progress | No grasp | Lifted, lost | Placed next to | "
             "Final dist. (median) | Time to success (median) | Not counted |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (task, strategy) in sorted(cells, key=lambda k: (k[0], ["chunk"].count(k[1]) == 0, k[1])):
        rows = cells[(task, strategy)]
        k, n = sum(r["success"] for r in rows), len(rows)
        ci = wilson(k, n)
        out_ = lambda o: sum(r["outcome"] == o for r in rows)  # noqa: E731
        fin = [r["metrics"].get("final_to_container_cm") for r in rows if r["metrics"].get("final_to_container_cm") is not None]
        tts = [r["metrics"].get("time_to_success_s") for r in rows if r["metrics"].get("time_to_success_s") is not None]
        lines.append(f"| {task} | {strategy} | {n} | {k}/{n} ({pct(k / n if n else None)}) | {pct(ci[0])}–{pct(ci[1])} | "
                     f"{np.mean([r['progress'] for r in rows]):.2f} | {out_('no_grasp') + out_('no_reach')} | "
                     f"{out_('carry_failed')} | {out_('missed_container')} | "
                     f"{'–' if not fin else f'{np.median(fin):.1f} cm'} | {'–' if not tts else f'{np.median(tts):.1f} s'} | "
                     f"{errors[(task, strategy)]} |")
    lines += ["", "Paired against the full chunk (same prompt and seed, all campaigns):", "",
              "| Strategy | Pairs | Chunk | It | Only chunk | Only it | McNemar p | Δ progress (95% CI) |", "|---|---|---|---|---|---|---|---|"]
    for p in pooled(results):
        ci = p["progress_ci"]
        lines.append(f"| {p['strategy']} | {p['pairs']} | {pct(p['base_rate'])} | {pct(p['rate'])} | {p['only_baseline']} | "
                     f"{p['only_this']} | {'–' if p['p'] is None else f'{p[chr(112)]:.3f}'} | {p['progress_diff']} "
                     f"{'' if not ci else f'[{ci[0]:+.2f}, {ci[1]:+.2f}]'} |")
    text = "\n".join(lines) + "\n"
    Path(out).write_text(text, encoding="utf-8")
    print(text.encode("ascii", "replace").decode())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
