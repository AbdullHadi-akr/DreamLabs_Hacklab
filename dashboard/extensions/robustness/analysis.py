"""Statistics for robustness campaigns. Kept honest on purpose: few trials -> wide intervals -> say so.

Sweep (one perturbation, increasing strength):
  per strength: success k/n with a 95 % Wilson interval, mean progress score, outcome counts.
  breaking point: the first strength where the success rate falls to half the baseline or below. If the baseline itself
  never succeeds, the progress score (reach/lift/carry) is used instead, so a weak model still gets a readable curve.

Random mix (several perturbations at random strengths per trial):
  per factor: Spearman correlation between strength and progress score, and the success rate in the weak vs. strong
  half of its range. The most negative correlation is the factor that hurts most.
"""

from __future__ import annotations

import math

import numpy as np

from .monitor import OUTCOMES


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def _mean(values):
    values = [v for v in values if v is not None]
    return round(float(np.mean(values)), 3) if values else None


def group_stats(rows: list[dict]) -> dict:
    scored = [r for r in rows if r.get("outcome") not in ("invalid", "aborted", None)]
    k = sum(1 for r in scored if r["success"])
    n = len(scored)
    counts = {key: 0 for key in OUTCOMES}
    for r in rows:
        if r.get("outcome"):
            counts[r["outcome"]] += 1
    return {
        "n": n, "done": len(rows), "successes": k,
        "rate": k / n if n else None, "ci": wilson(k, n),
        "progress": _mean([r.get("progress") for r in scored]),
        "outcomes": {key: v for key, v in counts.items() if v},
        "min_reach_cm": _mean([r.get("metrics", {}).get("min_reach_cm") for r in scored]),
        "max_lift_cm": _mean([r.get("metrics", {}).get("max_lift_cm") for r in scored]),
        "time_to_success_s": _mean([r.get("metrics", {}).get("time_to_success_s") for r in scored]),
    }


def sweep_summary(values: list[float], rows: list[dict], neutral: float, unit: str, discrete: bool = False) -> dict:
    per_value = [{"value": v, **group_stats([r for r in rows if r["value"] == v])} for v in values]
    base = next((p for p in per_value if p["value"] == neutral), per_value[0] if per_value else None)
    verdict = {"breaking_point": None, "metric": None, "confident": False, "text": "No trials yet."}
    if base and base["n"]:
        use_rate = base["rate"] and base["rate"] > 0
        metric = "success" if use_rate else "progress"
        base_value = base["rate"] if use_rate else base["progress"]
        verdict["metric"] = metric
        for p in per_value:
            if p is base or not p["n"]:
                continue
            value = p["rate"] if use_rate else p["progress"]
            if value is not None and base_value and value <= 0.5 * base_value:
                verdict["breaking_point"] = p["value"]
                # Only "confident" if the interval at that strength lies completely below the baseline's estimate.
                verdict["confident"] = bool(use_rate and p["ci"] and p["ci"][1] < base_value)
                break
        tested = [p for p in per_value if p["n"]]
        if not base_value:
            verdict["text"] = (f"Fails even without perturbation (baseline {base['successes']}/{base['n']}, "
                               "progress 0) — nothing to measure robustness against.")
        elif verdict["breaking_point"] is not None:
            bp = verdict["breaking_point"]
            prev = [p["value"] for p in tested if p["value"] != neutral and p["value"] < bp]
            robust_to = f"robust up to {max(prev):g} {unit}, " if prev else ""
            what = "success rate" if use_rate else "progress score"
            verdict["text"] = (f"{robust_to}breaks at {bp:g} {unit} ({what} at half the baseline or below)"
                               + ("" if verdict["confident"] else " — few trials, treat as a hint"))
            verdict["text"] = verdict["text"][0].upper() + verdict["text"][1:]
        elif len(tested) > 1:
            verdict["text"] = f"No clear drop up to {max(p['value'] for p in tested):g} {unit}."
        else:
            verdict["text"] = "Baseline measured; waiting for perturbed trials."
        if discrete and base_value:
            # Categorical variants (e.g. prompt wordings): no order, so list every variant that falls to half.
            weak = [p["value"] for p in tested if p is not base
                    and ((p["rate"] if use_rate else p["progress"]) or 0) <= 0.5 * base_value]
            verdict["breaking_point"] = weak[0] if weak else None
            verdict["text"] = (f"Fails on variant{'s' if len(weak) > 1 else ''} {', '.join(f'{w:g}' for w in weak)}"
                               if weak else f"All {len(tested) - 1} variants hold up against the original.")
        if not use_rate and base_value:
            verdict["text"] += " (Baseline never succeeds, so this uses the progress score.)"
    return {"per_value": per_value, "baseline": base, "verdict": verdict}


def _ranks(x):
    x = np.asarray(x, float)
    order = x.argsort()
    ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x))
    for value in np.unique(x):  # average ranks for ties
        same = x == value
        ranks[same] = ranks[same].mean()
    return ranks


def spearman(x, y) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return round(float(np.corrcoef(rx, ry)[0, 1]), 2)


def random_summary(factors: dict[str, float], neutral: dict[str, float], rows: list[dict],
                   labels: dict[str, str] | None = None) -> dict:
    scored = [r for r in rows if r.get("outcome") not in ("invalid", "aborted", None)]
    per_factor = []
    for fid, top in factors.items():
        strengths = [r["params"][fid] for r in scored]
        progress = [r["progress"] for r in scored]
        middle = (neutral[fid] + top) / 2
        weak = [r for r in scored if r["params"][fid] <= middle]
        strong = [r for r in scored if r["params"][fid] > middle]
        ok = [r["params"][fid] for r in scored if r["success"]]
        bad = [r["params"][fid] for r in scored if not r["success"]]
        per_factor.append({
            "id": fid, "max": top, "rho": spearman(strengths, progress),
            "weak": group_stats(weak), "strong": group_stats(strong),
            "mean_success": None if not ok else round(float(np.mean(ok)), 1),
            "mean_failure": None if not bad else round(float(np.mean(bad)), 1),
        })
    ranked = sorted([f for f in per_factor if f["rho"] is not None], key=lambda f: f["rho"])
    if len(scored) < 3:
        text = "Need at least 3 finished trials for an analysis."
    elif not ranked:
        text = "No variation in outcomes yet — every trial ended the same way."
    elif ranked[0]["rho"] <= -0.3:
        name = (labels or {}).get(ranked[0]["id"], ranked[0]["id"])
        text = f"Most harmful: {name} (ρ = {ranked[0]['rho']:+.2f} with progress)"
        if len(scored) < 15:
            text += f" — only {len(scored)} trials, treat as a hint"
    else:
        text = "No factor stands out (all |ρ| < 0.3)."
    return {"per_factor": per_factor, "overall": group_stats(rows), "verdict": {"text": text,
            "most_harmful": ranked[0]["id"] if ranked and ranked[0]["rho"] <= -0.3 else None}}
