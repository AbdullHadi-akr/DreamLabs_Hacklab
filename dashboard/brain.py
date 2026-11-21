"""Feeds the second brain (brain/ in the repository): the dashboard writes results into brain/raw/ by itself.

The second brain follows Andrej Karpathy's "LLM wiki" idea (see brain/AGENTS.md):
    brain/raw/    sources: written by the dashboard (and by people). An AI agent reads them; nobody edits them later.
    brain/wiki/   the wiki: pages the script brain/build_wiki.py makes from raw/ (later also an AI agent, see
                  brain/AGENTS.md). People read it, e.g. in Obsidian.

What the dashboard writes:
    raw/runs/<day>.md          one line per Dream-1 run (not test motions or Home)
    raw/robustness/<id>.md     one file per finished robustness campaign
    raw/exports/<name>.md      one file per export of episodes for a fine-tune
    raw/summaries/<day>.md     the day's summary from the lab database, rewritten after each run

After each of these, rebuild_wiki() runs brain/build_wiki.py, so the wiki is always current.
Nothing secret goes into these files: no API key, no access code, no personal data.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import time
from pathlib import Path

BRAIN_DIR = Path(os.environ.get("DREAM_BRAIN_DIR") or Path(__file__).resolve().parents[1] / "brain")
WIKI_SCRIPT = Path(__file__).resolve().parents[1] / "brain" / "build_wiki.py"
_lock = threading.Lock()


def rebuild_wiki() -> dict | None:
    """Runs brain/build_wiki.py on BRAIN_DIR. A failure is printed and never stops the dashboard."""
    try:
        spec = importlib.util.spec_from_file_location("build_wiki", WIKI_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with _lock:
            return module.build(BRAIN_DIR)
    except Exception as exc:  # the wiki is a convenience; a run must never fail because of it
        print(f"[brain] wiki build failed: {exc}")
        return None


def _raw(*parts) -> Path:
    path = BRAIN_DIR.joinpath("raw", *parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _day(t=None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _cell(value) -> str:
    text = "-" if value is None else str(value)
    return text.replace("|", "/").replace("\n", " ")


def _yes(value) -> str:
    return {True: "yes", False: "no", 1: "yes", 0: "no"}.get(value, "unknown")


def run_ended(info: dict, result: dict, run_id: int | None = None) -> Path | None:
    """One line per Dream-1 run in raw/runs/<day>.md."""
    if info.get("offline"):
        return None
    path = _raw("runs", f"{_day()}.md")
    head = (f"# Dream-1 runs on {_day()}\n\nWritten by the dashboard. One line per run. Seconds are simulated "
            "seconds. Cost is calls times the price.\n\n| Time | Run | Task | Prompt | Model | Source | Result | "
            "Stop reason | Calls | Cost (USD) | Seconds |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
    cost = result.get("cost_usd")
    line = (f"| {time.strftime('%H:%M:%S')} | {_cell(run_id)} | {_cell(info.get('task'))} | "
            f"{_cell(info.get('prompt'))} | {_cell(info.get('model'))} | {_cell(info.get('source'))} | "
            f"{_yes(result.get('success')) if result.get('success') is not None else 'no check'} | "
            f"{_cell(result.get('stop_reason'))} | {_cell(result.get('requests'))} | "
            f"{'-' if cost is None else f'{cost:.4f}'} | {_cell(round(result.get('sim_seconds') or 0, 1))} |\n")
    with _lock:
        new = not path.exists()
        with path.open("a", encoding="utf-8") as f:
            if new:
                f.write(head)
            f.write(line)
    return path


def campaign_ended(summary: dict) -> Path:
    """A finished robustness campaign: raw/robustness/<id>.md."""
    cfg = summary.get("config", {})
    cost = summary.get("cost") or {}
    lines = [f"# Robustness campaign {summary['id']}", "",
             "Written by the dashboard when the campaign ended.", "",
             f"- Task: {cfg.get('task')}",
             f"- Mode: {summary.get('mode')}"
             + (f", perturbation: {summary.get('perturbation', {}).get('label')}" if summary.get("mode") == "sweep"
                else ""),
             f"- Policy: {summary.get('policy')}",
             f"- State: {summary.get('state')}, {summary.get('done')} of {summary.get('total')} trials",
             f"- Dream-1 calls: {cost.get('calls', 0)}, cost: "
             + ("unknown" if cost.get("usd") is None else f"${cost['usd']:.4f}"),
             f"- Verdict: {summary.get('analysis', {}).get('verdict', {}).get('text')}", ""]
    per_value = summary.get("analysis", {}).get("per_value")
    if per_value:
        unit = summary.get("perturbation", {}).get("unit", "")
        lines += ["| Strength | Counted trials | Successes |", "|---|---|---|"]
        lines += [f"| {p['value']} {unit} | {p['n']} | {p['successes']} |" for p in per_value]
    path = _raw("robustness", f"{summary['id']}.md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rebuild_wiki()
    return path


def export_done(result: dict, task: str, episodes: list[dict]) -> Path:
    """An export for a fine-tune: raw/exports/<name>.md."""
    lines = [f"# Export {result['name']}", "", "Written by the dashboard when the export was made.", "",
             f"- Task: {task}", f"- Episodes: {result['episodes']}, frames: {result['frames']} (10 per second)",
             f"- Folder: out/exports/{result['name']} (not in git)",
             "- Dream Labs' dataset check: passed", "- Uploaded: no (upload and fine-tuning are separate steps)", "",
             "| Episode | Seconds | Finished by |", "|---|---|---|"]
    lines += [f"| {e['id']} | {e.get('seconds')} | {'person' if e.get('took_over') else 'Dream-1'} |"
              for e in episodes]
    path = _raw("exports", f"{result['name']}.md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rebuild_wiki()
    return path


def daily_summary(db, credits_summary: dict | None = None) -> Path:
    """The day's summary from the lab database: raw/summaries/<day>.md (rewritten during the day)."""
    s = db.summary()
    day = _day()
    lines = [f"# Summary for {day}", "", "Written by the dashboard from the lab database (out/lab.db). "
             "Rewritten after each Dream-1 run on this day; the last version of the day stays.", ""]
    if credits_summary:
        c = credits_summary
        lines += [f"- Spent today: ${c['spent_today_usd']:.4f}; this month: ${c['spent_month_usd']:.4f} of "
                  f"${c['monthly_limit_usd']:.2f}; balance: ${c['balance_usd']:.2f}", ""]
    lines += ["## Success and cost per model and task", "", "| Model | Task | Runs | Successes | Cost (USD) | "
              "Cost per success |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['model']} | {r['task']} | {r['runs']} | {r['successes']} | {_cell(r['cost_usd'])} | "
              f"{_cell(r['cost_per_success'])} |" for r in s["by_model"]] or ["| - | - | - | - | - | - |"]
    lines += ["", "## Episodes ready for a fine-tune", "", "| Task | Episodes | Seconds |", "|---|---|---|"]
    lines += [f"| {r['task']} | {r['episodes']} | {r['seconds']} |" for r in s["trainable"]] or ["| - | - | - |"]
    lines += ["", "## Where a person took over", "", "| Task | Episodes | Taken over |", "|---|---|---|"]
    lines += [f"| {r['task']} | {r['episodes']} | {r['took_over']} |" for r in s["takeovers"]] or ["| - | - | - |"]
    path = _raw("summaries", f"{day}.md")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rebuild_wiki()  # comes right after run_ended, so one build covers the run and the summary
    return path
