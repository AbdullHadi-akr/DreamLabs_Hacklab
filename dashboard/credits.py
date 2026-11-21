"""Credits: what Dream-1 calls cost, what is left, and the limits that protect the balance.

The Dream Labs API does not report the balance, so the dashboard counts: every run row in the lab database holds
calls x price. Balance = the starting balance (typed in by a person, in Settings of the Credits panel) minus
everything counted. Runs made outside this dashboard are not counted: correct the starting balance when needed.

Protection, in this order:
    estimate      before a run: about how many calls, and what they cost
    confirm       a run whose estimate is above "confirm above" needs a second click
    monthly limit a run is refused when this month's spending plus its estimate would pass the limit, and a running
                  run is stopped when the limit is reached (this also covers robustness campaigns)
"""

from __future__ import annotations

import time

from .lab_db import PRICE_PER_CALL_USD

## Settings a person may change, with their defaults.
DEFAULTS = {"start_balance_usd": 150.0, "monthly_limit_usd": 100.0, "confirm_above_usd": 0.10}

## A Dream-1 reply holds up to 48 arm moves, executed at 20 per second: at most 2.4 simulated seconds per call.
SECONDS_PER_CALL_MIN = 48 / 20

## Models the dashboard offers in its model list. A model not listed here may still be typed in; its cost is unknown.
MODELS = [{"id": model, "price_usd": price} for model, price in PRICE_PER_CALL_USD.items()]


def price(model: str) -> float | None:
    return PRICE_PER_CALL_USD.get(model)


def settings(db) -> dict:
    stored = {row["key"]: row["value"] for row in db.query("SELECT key, value FROM settings")}
    return {key: float(stored.get(key, default)) for key, default in DEFAULTS.items()}


def save_settings(db, **values) -> dict:
    for key, value in values.items():
        if key in DEFAULTS and value is not None:
            if value < 0:
                raise ValueError(f"{key} cannot be below zero.")
            db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(float(value))))
    return settings(db)


def _since(db, start: float) -> float:
    return db.query("SELECT COALESCE(SUM(cost_usd), 0) AS v FROM runs WHERE started_at >= ?", (start,))[0]["v"]


def _day_start(now=None) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _month_start(now=None) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def spent_month(db) -> float:
    return _since(db, _month_start())


def estimate(db, model: str, seconds: float) -> dict:
    """About how many calls a run makes and what they cost. Based on earlier runs of the same model when there are
    some (calls per simulated second), else on the most calls a run can make (one per 2.4 simulated seconds)."""
    p = price(model)
    past = db.query("SELECT SUM(calls) AS calls, SUM(seconds) AS seconds, COUNT(*) AS n FROM runs "
                    "WHERE model = ? AND calls > 0 AND seconds > 0", (model,))[0]
    most = int(seconds / SECONDS_PER_CALL_MIN) + 1
    if past["n"] and past["n"] >= 3:
        calls, basis = min(most, max(1, round(past["calls"] / past["seconds"] * seconds))), f"{past['n']} earlier runs"
    else:
        calls, basis = most, "the most calls a run of this length can make"
    return {"model": model, "seconds": seconds, "calls": calls, "most_calls": most, "basis": basis,
            "price_usd": p, "usd": None if p is None else round(calls * p, 4),
            "most_usd": None if p is None else round(most * p, 4)}


def check_run(db, model: str, seconds: float) -> dict:
    """Before a run: the estimate, and a refusal text when the run could pass the monthly limit or the balance."""
    est = estimate(db, model, seconds)
    s = settings(db)
    est["needs_confirm"] = est["usd"] is not None and est["usd"] > s["confirm_above_usd"]
    est["refusal"] = None
    if est["usd"] is not None:
        month = spent_month(db)
        if month + est["usd"] > s["monthly_limit_usd"]:
            est["refusal"] = (f"This run could cost about ${est['usd']:.2f}. This month ${month:.2f} of the "
                              f"${s['monthly_limit_usd']:.2f} limit is spent. Raise the limit in Credits, or shorten "
                              "the time limit.")
        elif summary(db)["balance_usd"] < est["usd"]:
            est["refusal"] = "The balance is lower than this run's estimate. Correct the starting balance in Credits."
    return est


def summary(db) -> dict:
    s = settings(db)
    total = db.query("SELECT COALESCE(SUM(cost_usd), 0) AS v, COUNT(*) AS n FROM runs WHERE cost_usd IS NOT NULL")[0]
    last = db.query("SELECT id, task, model, calls, cost_usd, success, started_at FROM runs "
                    "WHERE cost_usd IS NOT NULL ORDER BY id DESC LIMIT 1")
    days = db.query(
        "SELECT date(started_at, 'unixepoch', 'localtime') AS day, ROUND(SUM(cost_usd), 4) AS usd, "
        "SUM(calls) AS calls, COUNT(*) AS runs FROM runs WHERE cost_usd IS NOT NULL AND started_at >= ? "
        "GROUP BY day ORDER BY day", (time.time() - 30 * 86400,))
    unknown = db.query("SELECT COUNT(*) AS n, COALESCE(SUM(calls), 0) AS calls FROM runs "
                       "WHERE cost_usd IS NULL AND calls > 0")[0]
    month = spent_month(db)
    return {
        **s,
        "spent_total_usd": round(total["v"], 4),
        "balance_usd": round(s["start_balance_usd"] - total["v"], 4),
        "spent_today_usd": round(_since(db, _day_start()), 4),
        "spent_month_usd": round(month, 4),
        "month_left_usd": round(max(0.0, s["monthly_limit_usd"] - month), 4),
        "last_run": last[0] if last else None,
        "days": days,
        "models": MODELS,
        "unpriced_runs": unknown["n"], "unpriced_calls": unknown["calls"],
    }
