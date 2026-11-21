"""Stored campaigns: listing, CSV export, ZIP bundles and the cross-campaign robustness map.

Every campaign lives in out/extensions/robustness/<id>/ (result.json + trial-NNN.mp4). Everything here only reads
those folders, so results from earlier sessions (or copied in from a teammate) show up too.
"""

from __future__ import annotations

import csv
import io
import json
import math
import time
import zipfile
from pathlib import Path

from .analysis import wilson
from .monitor import OUTCOMES
from .perturbations import GROUPS, REGISTRY

METRICS = ("min_reach_cm", "max_lift_cm", "target_moved_cm", "final_to_container_cm", "others_moved_cm",
           "time_to_success_s")
BASE_FIELDS = ("campaign", "started", "mode", "task", "policy", "perturbation", "strength", "trial_index", "trial",
               "prompt", "outcome", "outcome_label", "counted", "success", "progress")
TAIL_FIELDS = ("stop_reason", "seconds", "calls", "cost_usd", "steps", "mean_rtt_s", "redraws", "note", "applied", "video")
SCORED = lambda r: r.get("outcome") not in ("invalid", "aborted", None)  # noqa: E731

## Columns of the robustness map: strength as a share of the perturbation's maximum.
BINS = ["Baseline", "≤ 25 %", "≤ 50 %", "≤ 75 %", "≤ 100 %", "> max"]


def load_all(data_dir: Path) -> list[dict]:
    results = []
    for path in sorted(data_dir.glob("*/result.json"), reverse=True):
        try:
            results.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return results


def policy_key(result: dict) -> str:
    return "dry run" if result["config"]["dry_run"] else result["config"]["model"]


def run_info(result: dict, folder: Path) -> dict:
    rows = result.get("rows", [])
    scored = [r for r in rows if SCORED(r)]
    k = sum(1 for r in scored if r["success"])
    progress = [r["progress"] for r in scored if r.get("progress") is not None]
    videos = list(folder.glob("trial-*.mp4"))
    return {
        "id": result["id"], "mode": result["mode"], "state": result["state"], "started": result.get("started"),
        "task": result["config"]["task"], "policy": policy_key(result), "dry_run": result["config"]["dry_run"],
        "label": result.get("perturbation", {}).get("label") or "Random mix",
        "perturbation": result.get("perturbation", {}).get("id"),
        "factors": [f["label"] for f in result.get("factors", [])],
        "done": result["done"], "total": result["total"], "scored": len(scored), "successes": k,
        "rate": k / len(scored) if scored else None,
        "progress": round(sum(progress) / len(progress), 3) if progress else None,
        "verdict": result["analysis"]["verdict"]["text"],
        "videos": len(videos), "bytes": sum(p.stat().st_size for p in [folder / "result.json", *videos]),
    }


def matches(result: dict, task: str | None, policy: str | None) -> bool:
    return (not task or result["config"]["task"] == task) and (not policy or policy_key(result) == policy)


# ---------- CSV ----------

def trial_records(result: dict) -> list[dict]:
    """One flat dict per trial, ready for a spreadsheet or pandas."""
    started = result.get("started")
    out = []
    for r in result.get("rows", []):
        rec = {
            "campaign": result["id"],
            "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)) if started else "",
            "mode": result["mode"], "task": result["config"]["task"], "policy": policy_key(result),
            "perturbation": result.get("perturbation", {}).get("id", ""),
            "strength": r.get("value", ""),
            "trial_index": r["index"], "trial": r["trial"], "prompt": r.get("prompt", ""),
            "outcome": r.get("outcome", ""), "outcome_label": OUTCOMES.get(r.get("outcome"), ""),
            "counted": SCORED(r), "success": bool(r.get("success")), "progress": r.get("progress"),
        }
        for pid, value in (r.get("params") or {}).items():
            rec[f"p_{pid}"] = value
        metrics = r.get("metrics") or {}
        for name in METRICS:
            rec[name] = metrics.get(name)
        rec.update(stop_reason=r.get("stop_reason", ""), seconds=r.get("seconds"), calls=r.get("calls"),
                   cost_usd=r.get("cost_usd"), steps=r.get("steps"),
                   mean_rtt_s=r.get("mean_rtt_s"), redraws=r.get("redraws"), note=r.get("note", ""),
                   applied=json.dumps(r.get("info") or {}, ensure_ascii=False), video=r.get("video") or "")
        out.append(rec)
    return out


def to_csv(records: list[dict], excel: bool = False) -> str:
    """CSV text. `excel=True`: semicolons and decimal commas, which German Excel opens correctly by double-click."""
    if not records:
        return ""
    params = [f"p_{pid}" for pid in REGISTRY if any(f"p_{pid}" in rec for rec in records)]
    fields = [*BASE_FIELDS, *params, *METRICS, *TAIL_FIELDS]

    def fmt(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            text = f"{value:.4g}" if abs(value) < 1e4 else f"{value:.0f}"
            return text.replace(".", ",") if excel else text
        return value

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=";" if excel else ",", extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for rec in records:
        writer.writerow({k: fmt(rec.get(k)) for k in fields})
    return "﻿" + buffer.getvalue()  # BOM: Excel then reads UTF-8 (°, σ, ×) correctly


def write_bundle(result: dict, folder: Path, target: Path) -> None:
    """ZIP with result.json, trials.csv and all trial videos (stored, MP4 does not compress further)."""
    with zipfile.ZipFile(target, "w") as z:
        z.writestr(f"{result['id']}/result.json", json.dumps(result, indent=2), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(f"{result['id']}/trials.csv", to_csv(trial_records(result)), compress_type=zipfile.ZIP_DEFLATED)
        for video in sorted(folder.glob("trial-*.mp4")):
            z.write(video, f"{result['id']}/{video.name}", compress_type=zipfile.ZIP_STORED)


# ---------- robustness map ----------

def strength_bin(value: float, p) -> int:
    if value == p.neutral:
        return 0
    span = (p.max - p.neutral) or 1.0
    share = (value - p.neutral) / span
    if share > 1.0001:
        return 5
    return max(1, min(4, math.ceil(share * 4 - 1e-9)))


def robustness_map(results: list[dict]) -> dict:
    """Pools all sweep and adaptive-search trials per perturbation and strength bin: one row per perturbation, one cell per bin.

    Random-mix trials change several things at once, so they cannot be attributed to one cell and are left out.
    """
    cells: dict[tuple[str, int], dict] = {}
    campaigns: dict[str, set] = {}
    for result in results:
        if result["mode"] not in ("sweep", "adaptive"):  # both test one perturbation at a time
            continue
        pid = result["perturbation"]["id"]
        p = REGISTRY.get(pid)
        if p is None:
            continue
        campaigns.setdefault(pid, set()).add(result["id"])
        for r in result.get("rows", []):
            if not SCORED(r) or "value" not in r:
                continue
            cell = cells.setdefault((pid, strength_bin(r["value"], p)),
                                    {"n": 0, "k": 0, "progress": 0.0, "values": set(), "outcomes": {}})
            cell["n"] += 1
            cell["k"] += int(bool(r["success"]))
            cell["progress"] += r.get("progress") or 0.0
            cell["values"].add(r["value"])
            cell["outcomes"][r["outcome"]] = cell["outcomes"].get(r["outcome"], 0) + 1

    rows = []
    for p in REGISTRY.values():
        row_cells = []
        for b in range(len(BINS)):
            c = cells.get((p.id, b))
            if not c:
                row_cells.append(None)
                continue
            row_cells.append({
                "n": c["n"], "successes": c["k"], "rate": c["k"] / c["n"], "ci": wilson(c["k"], c["n"]),
                "progress": round(c["progress"] / c["n"], 3), "values": sorted(c["values"]),
                "outcomes": c["outcomes"],
            })
        rows.append({"id": p.id, "label": p.label, "unit": p.unit, "group": p.group, "group_label": GROUPS[p.group],
                     "neutral": p.neutral, "max": p.max, "campaigns": sorted(campaigns.get(p.id, [])),
                     "cells": row_cells})
    return {"bins": BINS, "rows": rows, "outcome_labels": OUTCOMES,
            "excluded_random": sum(1 for r in results if r["mode"] == "random")}
