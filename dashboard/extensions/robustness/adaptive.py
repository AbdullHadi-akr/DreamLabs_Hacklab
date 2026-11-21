"""Adaptive breaking-point search: find the strength where Dream-1 breaks with as few (paid) trials as possible.

A fixed sweep spends most trials where nothing happens (far below or far above the break). This search is Bayesian
active learning in the style of the psi method from psychophysics (Kontsevich & Tyler, 1999):

  Model     P(event | strength s) = eps + (1 - 2 eps) * base * sigmoid((theta - s) / width)
              base   how often the event happens without perturbation
              theta  the breaking point: there the probability is half the baseline (same definition as the sweep)
              width  how sharp the drop is
              eps    lapse rate, so one odd trial cannot rule anything out completely
  Belief    a grid posterior over (theta, width, base), recomputed from all trials so far
  Next      the candidate strength with the largest expected information gain about theta
            (expected drop in the entropy of theta's posterior after seeing the outcome)
  Stop      when the 80 % credible interval of theta is narrow enough, when the model is clearly robust in the
            whole range, or when the trial budget is used up

The "event" is success by default. Dream-1 rarely succeeds unperturbed, so a weaker event can be chosen instead
(carried to the container, lifted, reached): the search then finds where that stage breaks.

Assumption: stronger perturbation never helps (monotone). That is why categorical perturbations (prompt wordings)
cannot be searched this way.
"""

from __future__ import annotations

import numpy as np

MEASURES = {
    "success": (1.0, "Success"),
    "carried": (0.75, "Carried to the container"),
    "lifted": (0.5, "Lifted the target"),
    "reached": (0.25, "Reached the target"),
}
EPS = 0.02
CANDIDATES = 21  # strengths the search may pick: 5 % steps of the range
CI_MASS = 0.8
PRECISE = 0.15  # stop when the 80 % interval is narrower than this share of the range
ROBUST = 0.9  # stop when P(break beyond the range) reaches this
MIN_ADAPTIVE = 3  # trials after the baseline before an early stop is allowed


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40, 40)))


def _entropy(p):
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def _quantile(grid, mass, q):
    cdf = np.cumsum(mass)
    return float(np.interp(q, cdf, grid))


def event(row: dict, level: float) -> bool | None:
    """Whether a trial reached the measured stage; None for trials that do not count."""
    if row.get("outcome") in ("invalid", "aborted", None) or row.get("progress") is None:
        return None
    return row["progress"] >= level - 1e-9


class BreakpointSearch:
    def __init__(self, neutral: float, top: float):
        self.neutral, self.top = float(neutral), float(top)
        span = self.top - self.neutral
        self.span = span
        # theta up to 1.5x the range: the mass beyond `top` is "does not break in the tested range"
        self.theta = np.linspace(self.neutral, self.neutral + 1.5 * span, 61)
        self.width = np.array([0.03, 0.07, 0.15, 0.3]) * span
        self.base = np.linspace(0.05, 0.98, 20)
        self.T, self.W, self.B = np.meshgrid(self.theta, self.width, self.base, indexing="ij")
        self.candidates = np.round(np.linspace(self.neutral, self.top, CANDIDATES), 4)
        self.post = np.full(self.T.shape, 1.0 / self.T.size)
        self.observations: list[tuple[float, bool]] = []

    def p_event(self, s):
        return EPS + (1 - 2 * EPS) * self.B * _sigmoid((self.T - s) / self.W)

    def fit(self, observations: list[tuple[float, bool]]) -> None:
        log_post = np.zeros(self.T.shape)
        for s, y in observations:
            p = self.p_event(s)
            log_post += np.log(p if y else 1 - p)
        weights = np.exp(log_post - log_post.max())
        self.post = weights / weights.sum()
        self.observations = list(observations)

    def theta_mass(self, post=None):
        return (self.post if post is None else post).sum(axis=(1, 2))

    def next_strength(self) -> tuple[float, float]:
        """(strength, expected information gain in nats) of the most informative next trial."""
        h0 = _entropy(self.theta_mass())
        best = (self.candidates[0], -1.0)
        for s in self.candidates:
            p = self.p_event(s)
            joint1 = self.post * p
            p1 = joint1.sum()
            joint0 = self.post - joint1
            h = p1 * _entropy(self.theta_mass(joint1) / p1) + (1 - p1) * _entropy(self.theta_mass(joint0) / (1 - p1))
            gain = h0 - h
            if gain > best[1] + 1e-9:
                best = (float(s), float(gain))
        return best

    def estimate(self) -> dict:
        mass = self.theta_mass()
        lo, med, hi = (_quantile(self.theta, mass, q) for q in ((1 - CI_MASS) / 2, 0.5, (1 + CI_MASS) / 2))
        beyond = float(mass[self.theta > self.top + 1e-9].sum())
        return {"estimate": med, "ci": [lo, hi], "p_beyond": beyond, "base": float((self.post * self.B).sum()),
                "ci_share": (hi - lo) / self.span if self.span else None}

    def curve(self, points: int = 41) -> dict:
        """Posterior mean and 80 % band of P(event) over the tested range (without the lapse rate)."""
        xs = np.linspace(self.neutral, self.top, points)
        weights = self.post.ravel()
        mean, lo, hi = [], [], []
        for s in xs:
            values = (self.B * _sigmoid((self.T - s) / self.W)).ravel()
            order = values.argsort()
            cdf = np.cumsum(weights[order])
            mean.append(float((weights * values).sum()))
            lo.append(float(values[order][np.searchsorted(cdf, (1 - CI_MASS) / 2)]))
            hi.append(float(values[order][min(np.searchsorted(cdf, (1 + CI_MASS) / 2), len(cdf) - 1)]))
        return {"s": xs.round(4).tolist(), "mean": mean, "lo": lo, "hi": hi}

    def stop_reason(self, adaptive_trials: int) -> str | None:
        if adaptive_trials < MIN_ADAPTIVE:
            return None
        est = self.estimate()
        if est["p_beyond"] >= ROBUST:
            return "robust in the whole range"
        if est["p_beyond"] < 0.2 and est["ci_share"] is not None and est["ci_share"] <= PRECISE:
            return "breaking point pinned down"
        return None


def summarize(rows: list[dict], neutral: float, top: float, unit: str, measure: str, budget: int,
              stopped_because: str | None = None) -> dict:
    """Analysis block for an adaptive campaign; recomputed from the trial rows, so a saved run reloads the same."""
    level, label = MEASURES[measure]
    search = BreakpointSearch(neutral, top)
    observations = [(r["value"], y) for r in rows if (y := event(r, level)) is not None]
    search.fit(observations)
    est = search.estimate()
    base_rows = [y for s, y in observations if s == neutral]

    def fmt(v):
        return f">{top:g}" if v > top + 1e-9 else f"{v:.2g}"

    verdict = {"breaking_point": None, "confident": False}
    if not observations:
        verdict["text"] = "No trials yet."
    elif base_rows and not any(base_rows) and len(base_rows) >= 3:
        verdict["text"] = (f"“{label}” never happens even without perturbation ({len(base_rows)} baseline trials). "
                           "Pick a weaker measure (e.g. lifted or reached) to find where the model breaks.")
    elif est["p_beyond"] >= 0.8:
        verdict["text"] = (f"No break up to {top:g} {unit} for “{label}” "
                           f"(P = {est['p_beyond']:.0%} that the break lies beyond the range).")
    else:
        lo, hi = est["ci"]
        verdict.update(breaking_point=round(est["estimate"], 3), confident=bool(est["ci_share"] <= PRECISE))
        verdict["text"] = (f"“{label}” breaks at ≈ {est['estimate']:.2g} {unit} (80 % interval {fmt(lo)}–{fmt(hi)} {unit})"
                           + ("" if verdict["confident"] else " — still uncertain, more trials would narrow it"))
    next_s, gain = search.next_strength() if observations else (neutral, None)
    return {
        "measure": {"id": measure, "level": level, "label": label},
        "estimate": est, "curve": search.curve(),
        "theta": {"s": search.theta.round(4).tolist(), "mass": search.theta_mass().round(6).tolist()},
        "observations": [{"s": s, "y": y} for s, y in observations],
        "next": {"s": next_s, "gain": gain}, "budget": budget, "stopped_because": stopped_because,
        "verdict": verdict,
    }
