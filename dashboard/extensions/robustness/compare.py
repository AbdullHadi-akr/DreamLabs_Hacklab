"""Strategy A/B: the same trials under different inference strategies, compared pair by pair.

Trial i runs under every strategy with the same seed, so the same scene, the same perturbation draw and (dry run) the
same simulated plan noise. That makes it a paired design: instead of comparing two success rates (which needs many
trials), only the pairs where the strategies disagree carry information.

  success   McNemar's exact test on the discordant pairs (b = only the baseline succeeded, c = only the other one).
            With few trials it is honest about it: 3 of 3 discordant pairs going one way is still p = 0.25.
  progress  mean paired difference of the progress score (0 / .25 / .5 / .75 / 1) with a 95 % bootstrap interval.
  smoothness  seam jump relative to a normal step, and the jitter share of the measured joints (inference.Smoothness),
            relative to the baseline. Absolute jerk is reported but not used for verdicts: it mostly measures speed,
            so a strategy that slows the arm would look "smooth". Speed is reported separately, and the price: API
            requests per trial.
"""

from __future__ import annotations

import math

import numpy as np

from .analysis import _mean, group_stats

SCORED = lambda r: r.get("outcome") not in ("invalid", "aborted", None)  # noqa: E731


def mcnemar_exact(b: int, c: int) -> float | None:
    """Two-sided exact McNemar p-value: binomial test of min(b, c) out of b + c discordant pairs at p = 0.5."""
    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_mean(values: list[float], resamples: int = 2000, seed: int = 0) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    x = np.asarray(values, float)
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), (resamples, len(x)))].mean(axis=1)
    return round(float(np.percentile(means, 2.5)), 3), round(float(np.percentile(means, 97.5)), 3)


def _change(value, base):
    if value is None or base is None or base == 0:
        return None
    return round((value - base) / base, 3)


def strategy_stats(rows: list[dict]) -> dict:
    scored = [r for r in rows if SCORED(r)]
    stats = group_stats(rows)
    commands = lambda key: _mean([(r.get("commands") or {}).get(key) for r in scored])  # noqa: E731
    stats.update(
        requests=_mean([r.get("requests") for r in scored]),
        seam_jump_rad=commands("seam_jump_rad"),
        seam_ratio=commands("seam_ratio"),
        command_jerk=commands("command_jerk"),
        command_jitter=commands("command_jitter"),
        joint_speed=_mean([(r.get("metrics") or {}).get("joint_speed") for r in scored]),
        joint_jerk=_mean([(r.get("metrics") or {}).get("joint_jerk") for r in scored]),
        joint_jitter=_mean([(r.get("metrics") or {}).get("joint_jitter") for r in scored]),
        sim_seconds=_mean([r.get("steps", 0) / 20 for r in scored]),
        wall_seconds=_mean([r.get("seconds") for r in scored]),
    )
    return stats


def compare_summary(strategies: list[dict], rows: list[dict]) -> dict:
    """`strategies`: described strategies (inference.Strategy.describe()), the first one is the baseline."""
    per = [{"id": s["id"], "label": s["label"], **strategy_stats([r for r in rows if r.get("strategy") == s["id"]])}
           for s in strategies]
    base = per[0] if per else None
    by_key = {(r["trial"], r["strategy"]): r for r in rows if SCORED(r)}
    trials = sorted({r["trial"] for r in rows})
    pairs = []
    for s in per[1:]:
        both = [(by_key[(t, base["id"])], by_key[(t, s["id"])]) for t in trials
                if (t, base["id"]) in by_key and (t, s["id"]) in by_key]
        only_base = sum(1 for a, o in both if a["success"] and not o["success"])
        only_this = sum(1 for a, o in both if o["success"] and not a["success"])
        diffs = [o["progress"] - a["progress"] for a, o in both
                 if o.get("progress") is not None and a.get("progress") is not None]
        pairs.append({
            "id": s["id"], "label": s["label"], "n": len(both),
            "only_baseline": only_base, "only_this": only_this, "both": sum(1 for a, o in both if a["success"] and o["success"]),
            "p_value": None if not both else (lambda p: None if p is None else round(p, 3))(mcnemar_exact(only_base, only_this)),
            "success_diff": round((only_this - only_base) / len(both), 3) if both else None,
            "progress_diff": round(float(np.mean(diffs)), 3) if diffs else None,
            "progress_ci": bootstrap_mean(diffs),
            "seam_change": _change(s["seam_ratio"], base["seam_ratio"]),
            "jitter_change": _change(s["joint_jitter"], base["joint_jitter"]),
            "speed_change": _change(s["joint_speed"], base["joint_speed"]),
            "command_jerk_change": _change(s["command_jerk"], base["command_jerk"]),
            "joint_jerk_change": _change(s["joint_jerk"], base["joint_jerk"]),
            "requests_factor": round(s["requests"] / base["requests"], 1) if s["requests"] and base["requests"] else None,
        })
    return {"per_strategy": per, "baseline": base["id"] if base else None, "pairs": pairs,
            "verdict": _verdict(per, pairs)}


def _verdict(per: list[dict], pairs: list[dict]) -> dict:
    tested = [s for s in per if s["n"]]
    verdict = {"best": None, "significant": False, "smoothest": None, "text": "No trials yet."}
    if not tested:
        return verdict
    if len(tested) < 2 or not pairs or not any(p["n"] for p in pairs):
        verdict["text"] = "Waiting for the first paired trials."
        return verdict
    use_rate = any(s["rate"] for s in tested)
    score = (lambda s: (s["rate"] or 0, s["progress"] or 0)) if use_rate else (lambda s: (s["progress"] or 0,))
    best = max(tested, key=score)
    base = per[0]
    verdict["best"] = best["id"]
    rate = lambda s: f"{s['successes']}/{s['n']}"  # noqa: E731
    if all(score(s) == score(tested[0]) for s in tested):
        verdict["text"] = (f"No difference so far: every strategy {'succeeded ' + rate(tested[0]) if use_rate else 'reached the same progress'}.")
        verdict["best"] = None
    elif best is base:
        runner_up = max([s for s in tested if s is not base], key=score)
        pair = next(p for p in pairs if p["id"] == runner_up["id"])
        verdict["text"] = (f"The baseline {base['label']} is best ({rate(base)} vs {rate(runner_up)} for "
                           f"{runner_up['label']})" if use_rate else
                           f"The baseline {base['label']} gets furthest (progress {base['progress']:.2f} vs "
                           f"{runner_up['progress']:.2f})")
        verdict["significant"] = _significant(pair, use_rate)
        verdict["text"] += _evidence(pair, use_rate)
    else:
        pair = next(p for p in pairs if p["id"] == best["id"])
        verdict["text"] = (f"{best['label']} wins: {rate(best)} successes vs {rate(base)} with the baseline"
                           if use_rate else
                           f"{best['label']} gets furthest: progress {best['progress']:.2f} vs {base['progress']:.2f} "
                           "(nobody succeeds yet)")
        verdict["significant"] = _significant(pair, use_rate)
        verdict["text"] += _evidence(pair, use_rate)
        smooth = []
        if pair["seam_change"] is not None:
            smooth.append(f"seams {abs(pair['seam_change']):.0%} {'smaller' if pair['seam_change'] < 0 else 'larger'}")
        if pair["speed_change"] is not None and abs(pair["speed_change"]) >= 0.15:
            smooth.append(f"arms {abs(pair['speed_change']):.0%} {'slower' if pair['speed_change'] < 0 else 'faster'}")
        if pair["requests_factor"]:
            smooth.append(f"{pair['requests_factor']:g}× the API requests")
        if smooth:
            verdict["text"] += " · " + ", ".join(smooth)
    smoothest = _smoothest(pairs)
    verdict["smoothest"] = smoothest["id"] if smoothest else None
    if smoothest and smoothest["id"] != verdict["best"]:
        verdict["text"] = verdict["text"].rstrip(".") + (
            f". Smoothest motion: {smoothest['label']} (jitter {_pct(smoothest['jitter_change'])}"
            + (f", seams {_pct(smoothest['seam_change'])}" if smoothest["seam_change"] is not None else "")
            + " vs the baseline, independent of speed).")
    return verdict


def _pct(change: float) -> str:
    return f"{'+' if change > 0 else '−'}{abs(change):.0%}"


def _smoothest(pairs: list[dict]) -> dict | None:
    """The strategy whose arms shook least (jitter share), if clearly (10 %+) below the default."""
    candidates = [p for p in pairs if p["jitter_change"] is not None and p["jitter_change"] <= -0.1]
    return min(candidates, key=lambda p: p["jitter_change"]) if candidates else None


def _significant(pair: dict, use_rate: bool) -> bool:
    if use_rate:
        return pair["p_value"] is not None and pair["p_value"] < 0.05
    ci = pair["progress_ci"]
    return bool(ci and (ci[0] > 0 or ci[1] < 0))


def _evidence(pair: dict, use_rate: bool) -> str:
    if use_rate:
        if pair["p_value"] is None:
            return " — no pair disagrees yet"
        word = "significant" if pair["p_value"] < 0.05 else "not significant yet"
        return (f" — {word} (paired McNemar p = {pair['p_value']:.2f}, {pair['only_this'] + pair['only_baseline']} "
                f"of {pair['n']} pairs disagree)")
    ci = pair["progress_ci"]
    if not ci:
        return " — too few pairs for an interval"
    word = "significant" if ci[0] > 0 or ci[1] < 0 else "not significant yet"
    return f" — {word} (paired progress difference 95 % CI {ci[0]:+.2f} … {ci[1]:+.2f})"
