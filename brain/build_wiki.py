"""Builds the wiki of the second brain from brain/raw/, without an AI agent (Python standard library only).

Run by hand from the repository root:   python brain/build_wiki.py
The dashboard also runs it by itself after every Dream-1 run, robustness campaign and export.

What it reads (brain/raw/):
    runs/<day>.md            one line per Dream-1 run
    summaries/<day>.md       the day's summary from the lab database (the newest one is used)
    robustness/<id>.md       one file per robustness campaign
    exports/<name>.md        one file per export for a fine-tune
    notes/*.md               notes people write; a line "Decision: ..." goes onto the decisions page

What it writes (brain/wiki/):
    tasks/<task>.md, models/<model>.md, robustness/campaigns.md, fine-tuning/exports.md,
    decisions/decisions.md, notes.md     pages made by this script; it rewrites them every time
    index.md                             every page of the wiki, also pages a person or an AI agent wrote
    log.md                               one entry each time a page changed
    .raw-hashes.json                     which raw files were read, to name the new or changed ones in the log

It never changes raw/ and never touches a page it did not make (overview.md, or pages an AI agent adds later).
The pages depend only on raw/, so two laptops that run it on the same raw/ files make the same pages.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

MARK = "<!-- made by brain/build_wiki.py: do not edit by hand, the script rewrites this page -->"
HEAD_NOTE = "*Made by the script `brain/build_wiki.py` from `brain/raw/`. Changes by hand are lost at the next build.*"


# ---------------------------------------------------------------------------------------------------------------
# Reading raw/
# ---------------------------------------------------------------------------------------------------------------
def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unnamed"


def table_rows(text: str) -> list[list[str]]:
    """The body rows of every Markdown table in text (header and separator rows left out)."""
    rows, lines = [], text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        is_separator = all(re.fullmatch(r":?-{3,}:?", c) for c in cells)
        is_header = i + 1 < len(lines) and re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|)+", lines[i + 1].strip() or "x")
        if not is_separator and not is_header:
            rows.append(cells)
    return rows


def sections(text: str) -> dict[str, str]:
    """Text under each '## ' heading."""
    out, name = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = ""
        elif name:
            out[name] += line + "\n"
    return out


def bullets(text: str) -> dict[str, str]:
    """'- Key: value' lines."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"-\s+([^:]+):\s*(.*)", line.strip())
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def number(text: str) -> float | None:
    try:
        return float(text.replace("$", "").strip())
    except (ValueError, AttributeError):
        return None


def read_runs(raw: Path) -> list[dict]:
    runs = []
    for path in sorted((raw / "runs").glob("*.md")):
        day = path.stem
        for c in table_rows(path.read_text(encoding="utf-8")):
            if len(c) < 11:
                continue
            runs.append({"day": day, "time": c[0], "run": c[1], "task": c[2], "prompt": c[3], "model": c[4],
                         "source": c[5], "result": c[6], "stop": c[7], "calls": number(c[8]) or 0,
                         "cost": number(c[9]), "seconds": number(c[10]), "file": f"raw/runs/{path.name}"})
    return runs


def read_summary(raw: Path) -> dict:
    """The newest daily summary: episodes ready per task, take-overs per task."""
    files = sorted((raw / "summaries").glob("*.md"))
    if not files:
        return {"file": None, "ready": {}, "takeovers": {}}
    path = files[-1]
    parts = sections(path.read_text(encoding="utf-8"))
    ready = {c[0]: {"episodes": c[1], "seconds": c[2]}
             for c in table_rows(parts.get("Episodes ready for a fine-tune", "")) if len(c) >= 3 and c[0] != "-"}
    takeovers = {c[0]: {"episodes": c[1], "taken_over": c[2]}
                 for c in table_rows(parts.get("Where a person took over", "")) if len(c) >= 3 and c[0] != "-"}
    return {"file": f"raw/summaries/{path.name}", "ready": ready, "takeovers": takeovers}


def read_campaigns(raw: Path) -> list[dict]:
    out = []
    for path in sorted((raw / "robustness").glob("*.md")):
        b = bullets(path.read_text(encoding="utf-8"))
        cost = re.search(r"cost:\s*(\S+)", b.get("Dream-1 calls", ""))
        out.append({"id": path.stem, "task": b.get("Task", "-"), "mode": b.get("Mode", "-"),
                    "policy": b.get("Policy", "-"), "state": b.get("State", "-"),
                    "cost": cost.group(1) if cost else "-", "verdict": b.get("Verdict", "-"),
                    "file": f"raw/robustness/{path.name}"})
    return out


def read_exports(raw: Path) -> list[dict]:
    out = []
    for path in sorted((raw / "exports").glob("*.md")):
        b = bullets(path.read_text(encoding="utf-8"))
        episodes = re.match(r"(\d+)", b.get("Episodes", ""))
        out.append({"name": path.stem, "task": b.get("Task", "-"), "episodes": episodes.group(1) if episodes else "-",
                    "uploaded": b.get("Uploaded", "-"), "file": f"raw/exports/{path.name}"})
    return out


def read_notes(raw: Path) -> tuple[list[dict], list[dict]]:
    notes, decisions = [], []
    for path in sorted((raw / "notes").glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8")
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        day = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
        day = day.group(1) if day else "no date in the file name"
        notes.append({"title": title, "day": day, "file": f"raw/notes/{path.name}"})
        for line in text.splitlines():
            plain = line.strip().lstrip("-* ").replace("**", "")  # also "- **Decision:** ..."
            m = re.match(r"decision\s*:\s*(.+)", plain, re.IGNORECASE)
            if m:
                decisions.append({"text": m.group(1).strip(), "day": day, "file": f"raw/notes/{path.name}"})
    return notes, decisions


# ---------------------------------------------------------------------------------------------------------------
# Writing wiki/
# ---------------------------------------------------------------------------------------------------------------
def money(value: float | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def tally(runs: list[dict]) -> dict:
    """Counts for a group of runs."""
    checked = [r for r in runs if r["result"] in ("yes", "no")]
    wins = sum(r["result"] == "yes" for r in runs)
    costs = [r["cost"] for r in runs if r["cost"] is not None]
    cost = sum(costs) if costs else None
    return {"runs": len(runs), "checked": len(checked), "wins": wins,
            "rate": f"{100 * wins / len(checked):.0f} %" if checked else "-",
            "calls": int(sum(r["calls"] for r in runs)), "cost": cost,
            "per_win": money(cost / wins) if cost is not None and wins else "-",
            "last": max(f"{r['day']} {r['time']}" for r in runs) if runs else "-"}


def link(folder: str, name: str) -> str:
    return f"[[{folder}/{slug(name)}|{name}]]"


def page(title: str, first: str, body: list[str]) -> str:
    return "\n".join([MARK, f"# {title}", "", first, "", HEAD_NOTE, ""] + body).rstrip() + "\n"


def sources(files) -> list[str]:
    files = sorted(set(f for f in files if f))
    return ["", "## Sources", ""] + ([f"- `{f}`" for f in files] or ["- none yet"])


def task_page(task, runs, summary, campaigns, exports) -> str:
    total = tally(runs)
    body = ["## Measured", "",
            f"- Dream-1 runs: {total['runs']}; with a success check: {total['checked']}; successes: {total['wins']} "
            f"({total['rate']})",
            f"- Dream-1 calls: {total['calls']}; cost: {money(total['cost'])}; cost per success: {total['per_win']}",
            f"- Last run: {total['last']}", ""]
    ready, taken = summary["ready"].get(task), summary["takeovers"].get(task)
    if ready or taken:
        body += [f"- Episodes ready for a fine-tune: {ready['episodes'] if ready else 0}"
                 + (f" ({ready['seconds']} seconds)" if ready else ""),
                 f"- Episodes where a person took over: {taken['taken_over'] if taken else 0} of "
                 f"{taken['episodes'] if taken else 0}", ""]
    body += ["## Per model", "", "| Model | Runs | Successes | Success rate | Calls | Cost | Cost per success |",
             "|---|---|---|---|---|---|---|"]
    by_model = defaultdict(list)
    for r in runs:
        by_model[r["model"]].append(r)
    for model in sorted(by_model):
        t = tally(by_model[model])
        body.append(f"| {link('models', model)} | {t['runs']} | {t['wins']} | {t['rate']} | {t['calls']} | "
                    f"{money(t['cost'])} | {t['per_win']} |")
    stops = defaultdict(int)
    for r in runs:
        stops[r["stop"]] += 1
    body += ["", "## Why the runs stopped", "", "| Stop reason | Runs |", "|---|---|"]
    body += [f"| {reason} | {n} |" for reason, n in sorted(stops.items(), key=lambda x: (-x[1], x[0]))]
    mine = [c for c in campaigns if c["task"] == task]
    if mine:
        body += ["", "## Robustness campaigns", ""] + [f"- {c['id']}: {c['verdict']}" for c in mine]
    shipped = [e for e in exports if e["task"] == task]
    if shipped:
        body += ["", "## Exports for a fine-tune", ""] + [f"- {e['name']}: {e['episodes']} episodes" for e in shipped]
    files = [r["file"] for r in runs] + [summary["file"] if (ready or taken) else None]
    files += [c["file"] for c in mine] + [e["file"] for e in shipped]
    return page(f"Task: {task}", f"This page shows how often the task \"{task}\" succeeded, with which model, and "
                f"what it cost.", body + sources(files))


def model_page(model, runs) -> str:
    total = tally(runs)
    body = ["## Measured", "",
            f"- Dream-1 runs: {total['runs']}; successes: {total['wins']} ({total['rate']} of the runs with a "
            f"success check)",
            f"- Calls: {total['calls']}; cost: {money(total['cost'])}; cost per success: {total['per_win']}", "",
            "## Per task", "", "| Task | Runs | Successes | Success rate | Cost | Cost per success |",
            "|---|---|---|---|---|---|"]
    by_task = defaultdict(list)
    for r in runs:
        by_task[r["task"]].append(r)
    for task in sorted(by_task):
        t = tally(by_task[task])
        body.append(f"| {link('tasks', task)} | {t['runs']} | {t['wins']} | {t['rate']} | {money(t['cost'])} | "
                    f"{t['per_win']} |")
    return page(f"Model: {model}", f"This page shows how the model \"{model}\" did on each task, and what it cost.",
                body + sources(r["file"] for r in runs))


def campaigns_page(campaigns) -> str:
    body = ["| Campaign | Task | Mode | Policy | State | Cost | Verdict |", "|---|---|---|---|---|---|---|"]
    body += [f"| {c['id']} | {link('tasks', c['task'])} | {c['mode']} | {c['policy']} | {c['state']} | {c['cost']} | "
             f"{c['verdict']} |" for c in campaigns] or ["| - | - | - | - | - | - | - |"]
    return page("Robustness campaigns", "This page lists every robustness campaign: a series of Dream-1 runs where "
                "the dashboard changes the scene step by step to find where Dream-1 starts to fail.",
                body + sources(c["file"] for c in campaigns))


def exports_page(exports) -> str:
    body = ["| Export | Task | Episodes | Uploaded |", "|---|---|---|---|"]
    body += [f"| {e['name']} | {link('tasks', e['task'])} | {e['episodes']} | {e['uploaded']} |" for e in exports] \
        or ["| - | - | - | - |"]
    return page("Exports for fine-tuning", "This page lists every export: a folder of successful episodes of one "
                "task, checked with Dream Labs' own dataset check, ready to train (fine-tune) Dream-1 further.",
                body + sources(e["file"] for e in exports))


def decisions_page(decisions) -> str:
    body = ["How to add one: in a note in `brain/raw/notes/`, write a line that starts with `Decision:`.", "",
            "| Date | Decision | Note |", "|---|---|---|"]
    body += [f"| {d['day']} | {d['text'].replace('|', '/')} | `{d['file']}` |" for d in decisions] \
        or ["| - | - | - |"]
    return page("Decisions", "This page lists the decisions the team wrote down in its notes, oldest first.",
                body + sources(d["file"] for d in decisions))


def notes_page(notes) -> str:
    body = ["| Date | Title | File |", "|---|---|---|"]
    body += [f"| {n['day']} | {n['title'].replace('|', '/')} | `{n['file']}` |" for n in notes] or ["| - | - | - |"]
    return page("Team notes", "This page lists the notes team members put into `brain/raw/notes/`. The script "
                "lists them; it does not summarize them.", body + sources(n["file"] for n in notes))


def first_sentence(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "<!--", "*Made by", "|", "-")):
            return line.split(". ")[0].rstrip(".") + "."
    return ""


def index_page(wiki: Path) -> str:
    lines = ["# Index", "", "Every page of the wiki, one line each. The script `brain/build_wiki.py` rewrites this "
             "list after each build; it also lists pages a person or an AI agent wrote.", ""]
    groups = defaultdict(list)
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(wiki).with_suffix("").as_posix()
        if rel == "index":
            continue
        groups[rel.split("/")[0] if "/" in rel else ""].append(f"- [[{rel}]]: {first_sentence(path)}")
    for group in sorted(groups):
        if group:
            lines += ["", f"## {group}", ""]
        lines += groups[group]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------------------------------
def build(brain: Path, now: str | None = None) -> dict:
    """Rewrites the script's pages from raw/. Returns the pages that changed and the raw files that were new."""
    raw, wiki = brain / "raw", brain / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    runs, summary = read_runs(raw), read_summary(raw)
    campaigns, exports = read_campaigns(raw), read_exports(raw)
    notes, decisions = read_notes(raw)

    pages: dict[str, str] = {}
    by_task, by_model = defaultdict(list), defaultdict(list)
    for r in runs:
        by_task[r["task"]].append(r)
        by_model[r["model"]].append(r)
    for task in set(by_task) | set(summary["ready"]) | set(summary["takeovers"]):
        pages[f"tasks/{slug(task)}.md"] = task_page(task, by_task[task], summary, campaigns, exports)
    for model, mruns in by_model.items():
        pages[f"models/{slug(model)}.md"] = model_page(model, mruns)
    pages["robustness/campaigns.md"] = campaigns_page(campaigns)
    pages["fine-tuning/exports.md"] = exports_page(exports)
    pages["decisions/decisions.md"] = decisions_page(decisions)
    pages["notes.md"] = notes_page(notes)

    changed = []
    for rel, text in sorted(pages.items()):
        path = wiki / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            changed.append(rel)
    # A page this script made earlier whose task or model no longer appears in raw/: remove it.
    for path in wiki.rglob("*.md"):
        rel = path.relative_to(wiki).as_posix()
        if rel not in pages and path.read_text(encoding="utf-8").startswith(MARK):
            path.unlink()
            changed.append(rel + " (removed)")

    index = wiki / "index.md"
    text = index_page(wiki)
    if not index.exists() or index.read_text(encoding="utf-8") != text:
        index.write_text(text, encoding="utf-8")
        changed.append("index.md")

    hashes_file = wiki / ".raw-hashes.json"
    old = json.loads(hashes_file.read_text(encoding="utf-8")) if hashes_file.exists() else {}
    new = {p.relative_to(brain).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()[:16]
           for p in sorted(raw.rglob("*.md")) if p.name.lower() != "readme.md"}
    read = [f for f in new if old.get(f) != new[f]]
    if new != old:
        hashes_file.write_text(json.dumps(new, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if changed:
        log = wiki / "log.md"
        entry = [f"\n## {now or time.strftime('%Y-%m-%d %H:%M')}: build by the script", "",
                 "- Raw files new or changed: " + (", ".join(f"`{f}`" for f in read) or "none"),
                 "- Pages changed: " + ", ".join(f"`{p}`" for p in changed)]
        with log.open("a", encoding="utf-8") as f:
            f.write("\n".join(entry) + "\n")
    return {"changed": changed, "raw_read": read}


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    result = build(folder)
    print(f"Pages changed: {len(result['changed'])}" + "".join(f"\n  {p}" for p in result["changed"]))
    print(f"Raw files new or changed: {len(result['raw_read'])}")
