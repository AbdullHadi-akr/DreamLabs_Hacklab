"""Evaluates strategy-comparison campaigns (robustness mode "compare") across prompts.

python measurements/analyze.py <out.md> <campaign id> [<campaign id> ...]

Per prompt and strategy: success (Wilson 95 % interval), progress, position errors (closest reach, final distance to the
container), time to success, Dream-1 requests and round-trip time, simulated and wall seconds, speed and jitter.
Pooled over all prompts: every strategy against the full chunk, pair by pair (McNemar exact, bootstrap interval of the
progress difference). Data checks: errors, invalid trials, missing pairs, round trips and wall times far off the rest.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "out" / "extensions" / "robustness"
sys.path.insert(0, str(ROOT))

from dashboard.extensions.robustness.analysis import wilson  # noqa: E402
from dashboard.extensions.robustness.compare import bootstrap_mean, mcnemar_exact  # noqa: E402

def cut_short(r, budget_steps=800):
    """Ended by the wall clock before the simulated budget was used up, without success (a hung request, a sleeping
    machine): `wall_timeout` since 22.11.2026, before that a `timeout` with fewer steps than the budget."""
    reason = r.get("stop_reason") or ""
    return not r.get("success") and (reason == "wall_timeout" or (reason == "timeout" and r.get("steps", budget_steps) < budget_steps))


SCORED = lambda r: r.get("outcome") not in ("invalid", "aborted", None) and not cut_short(r)  # noqa: E731


def load(cid):
    return json.loads((DATA / cid / "result.json").read_text(encoding="utf-8"))


def med(values, digits=1):
    values = [v for v in values if v is not None]
    return None if not values else round(float(np.median(values)), digits)


def mean(values, digits=2):
    values = [v for v in values if v is not None]
    return None if not values else round(float(np.mean(values)), digits)


def fmt(v, unit=""):
    return "–" if v is None else f"{v}{unit}"


def strategy_rows(rows):
    scored = [r for r in rows if SCORED(r)]
    k, n = sum(r["success"] for r in scored), len(scored)
    ci = wilson(k, n)
    m = lambda key: [r.get("metrics", {}).get(key) for r in scored]  # noqa: E731
    c = lambda key: [(r.get("commands") or {}).get(key) for r in scored]  # noqa: E731
    return {
        "n": n, "k": k, "rate": None if not n else k / n, "ci": ci,
        "progress": mean([r["progress"] for r in scored]),
        "reach_cm": med(m("min_reach_cm")), "final_to_container_cm": med(m("final_to_container_cm")),
        "time_to_success_s": med(m("time_to_success_s")),
        "requests": mean([r.get("requests") for r in scored], 1),
        "rtt_s": mean([r.get("mean_rtt_s") for r in scored]),
        "sim_s": mean([r.get("steps", 0) / 20 for r in scored], 1), "wall_s": mean([r.get("seconds") for r in scored], 1),
        "speed": mean(m("joint_speed"), 3), "jitter": mean(m("joint_jitter"), 3), "seam_ratio": mean(c("seam_ratio")),
        "released": sum(1 for r in scored if (r.get("metrics", {}).get("drop") or {}).get("cause") == "released"),
        "slipped": sum(1 for r in scored if (r.get("metrics", {}).get("drop") or {}).get("cause") == "slipped"),
        "drop_known": any("drops" in r.get("metrics", {}) for r in scored),
        "outcomes": {o: sum(r.get("outcome") == o for r in rows) for o in sorted({r.get("outcome") for r in rows})},
    }


def data_checks(result):
    rows = result["rows"]
    issues = []
    for r in rows:
        if r.get("stop_reason", "").startswith("error"):
            issues.append(f"trial {r['index']} ({r.get('strategy')}): {r['stop_reason'][:120]}")
        if r.get("outcome") in ("invalid", "aborted"):
            issues.append(f"trial {r['index']} ({r.get('strategy')}): {r.get('outcome')} {r.get('note', '')}")
    rtts = [r.get("mean_rtt_s") for r in rows if r.get("mean_rtt_s")]
    if rtts:
        q1, q3 = np.percentile(rtts, [25, 75])
        for r in rows:
            v = r.get("mean_rtt_s")
            if v and v > q3 + 3 * (q3 - q1) and v > 1.0:
                issues.append(f"trial {r['index']} ({r.get('strategy')}): round trip {v} s, far above the rest (median {np.median(rtts):.2f} s)")
    for s in {r.get("strategy") for r in rows}:
        walls = [r["seconds"] for r in rows if r.get("strategy") == s and r.get("seconds")]
        if len(walls) >= 3:
            m = np.median(walls)
            for r in rows:
                if r.get("strategy") == s and r.get("seconds", 0) > 2.5 * m:
                    issues.append(f"trial {r['index']} ({s}): {r['seconds']} s wall time, {m:.0f} s typical")
    pairs = {}
    for r in rows:
        pairs.setdefault(r["trial"], set()).add(r.get("strategy"))
    full = max((len(v) for v in pairs.values()), default=0)
    missing = [t for t, v in pairs.items() if len(v) < full]
    if missing:
        issues.append(f"incomplete pairs: {missing}")
    return issues


def pooled(results, baseline="chunk"):
    """Pairs (same prompt, same seed) pooled over all campaigns: each strategy vs the baseline."""
    by = {}
    for res in results:
        for r in res["rows"]:
            if SCORED(r):
                by[(res["id"], r["trial"], r["strategy"])] = r
    strategies = sorted({k[2] for k in by} - {baseline})
    out = []
    for s in strategies:
        both = [(by[(c, t, baseline)], by[(c, t, s)]) for (c, t, st) in by if st == s and (c, t, baseline) in by]
        b = sum(a["success"] and not o["success"] for a, o in both)
        c = sum(o["success"] and not a["success"] for a, o in both)
        diffs = [o["progress"] - a["progress"] for a, o in both if o.get("progress") is not None and a.get("progress") is not None]
        fin = [(o.get("metrics", {}).get("final_to_container_cm"), a.get("metrics", {}).get("final_to_container_cm")) for a, o in both]
        fin = [x - y for x, y in fin if x is not None and y is not None]
        out.append({"strategy": s, "pairs": len(both), "only_baseline": b, "only_this": c,
                    "base_rate": None if not both else sum(a["success"] for a, _ in both) / len(both),
                    "rate": None if not both else sum(o["success"] for _, o in both) / len(both),
                    "p": mcnemar_exact(b, c), "progress_diff": mean(diffs, 3), "progress_ci": bootstrap_mean(diffs),
                    "final_dist_diff_cm": med(fin)})
    return out


def pct(x):
    return "–" if x is None else f"{round(100 * x)}%"


def report(ids):
    results = [load(i) for i in ids]
    lines = []
    for res in results:
        cfg = res["config"]
        lines += [f"### “{cfg['task']}” — {res['id']}",
                  f"{res['done']}/{res['total']} trials, {cfg['trials']} pairs, {cfg['seconds']} s simulated per trial, "
                  f"perturbation {cfg.get('perturbation')}, seed {cfg.get('seed')}, state {res['state']}.", "",
                  "| Strategy | Success | 95% CI | Progress | Closest reach | Final dist. to container | Time to success | "
                  "Requests | RTT | Sim s | Wall s | Speed | Jitter | Seam/step | Drops released/slipped | Outcomes |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in res["strategies"]:
            st = strategy_rows([r for r in res["rows"] if r.get("strategy") == s["id"]])
            ci = st["ci"]
            lines.append(f"| {s['id']} | {st['k']}/{st['n']} | {'–' if not ci else f'{pct(ci[0])}–{pct(ci[1])}'} | "
                         f"{fmt(st['progress'])} | {fmt(st['reach_cm'], ' cm')} | {fmt(st['final_to_container_cm'], ' cm')} | "
                         f"{fmt(st['time_to_success_s'], ' s')} | {fmt(st['requests'])} | {fmt(st['rtt_s'], ' s')} | "
                         f"{fmt(st['sim_s'])} | {fmt(st['wall_s'])} | {fmt(st['speed'])} | {pct(st['jitter'])} | {fmt(st['seam_ratio'])} | "
                         f"{(str(st['released']) + '/' + str(st['slipped'])) if st['drop_known'] else '–'} | "
                         f"{', '.join(f'{k} {v}' for k, v in st['outcomes'].items() if v)} |")
        checks = data_checks(res)
        lines += ["", "Data checks: " + ("none found." if not checks else ""), *[f"- {c}" for c in checks], ""]
    lines += ["### Pooled over all prompts (pairs with the same prompt and seed)", "",
              "| Strategy | Pairs | Chunk success | Its success | Only chunk | Only it | McNemar p | Δ progress (95% CI) | "
              "Δ final distance (median) |", "|---|---|---|---|---|---|---|---|---|"]
    for p in pooled(results):
        ci = p["progress_ci"]
        lines.append(f"| {p['strategy']} | {p['pairs']} | {pct(p['base_rate'])} | {pct(p['rate'])} | {p['only_baseline']} | "
                     f"{p['only_this']} | {'–' if p['p'] is None else f'{p[chr(112)]:.3f}'} | {fmt(p['progress_diff'])} "
                     f"{'' if not ci else f'[{ci[0]:+.2f}, {ci[1]:+.2f}]'} | {fmt(p['final_dist_diff_cm'], ' cm')} |")
    return "\n".join(lines) + "\n", results


if __name__ == "__main__":
    text, _ = report(sys.argv[2:])
    Path(sys.argv[1]).write_text(text, encoding="utf-8")
    print(text.encode("ascii", "replace").decode())
