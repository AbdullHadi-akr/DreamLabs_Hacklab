"""Brain: the second brain and the parts of DreamLab-Rat drawn as one 3D brain (panel + full page brain.html).

The browser draws the brain (brainview.js). This backend only answers two questions:
  GET /api/ext/brain/graph          every page of brain/wiki/ and file of brain/raw/, the links between them,
                                    and the count of Test Suite safety failures (the amygdala)
  GET /api/ext/brain/page?path=...  the text of one of those files (only .md files inside brain/)

Links: [[folder/page]] links between wiki pages, and "raw/<folder>/<file>.md" mentions, which the wiki script
(brain/build_wiki.py) writes into each page's sources. Live activity comes from the dashboard's own events
(run.started, run.reply, run.ended, sim.state, episode.exported, ext.test_suite.*), read in the browser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from dashboard.extension import DATA_DIR, Extension

BRAIN_DIR = Path(__file__).resolve().parents[3] / "brain"
WIKI_LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
RAW_MENTION = re.compile(r"raw/[\w.\-/]+?\.md")
SKIP = {"README.md", "AGENTS.md", "CLAUDE.md"}


def _title(path: Path, text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ")


def read_graph(brain: Path = BRAIN_DIR, suite_dir: Path = DATA_DIR / "test_suite") -> dict:
    """The second brain as a graph for the 3D view: one point per wiki/raw page, and the links between them."""
    pages, texts = [], {}
    for kind in ("wiki", "raw"):
        root = brain / kind
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.name in SKIP:  # instructions for people and agents, not memories
                continue
            rel = path.relative_to(brain).as_posix()          # "wiki/tasks/apple.md", "raw/runs/2026-11-22.md"
            text = path.read_text(encoding="utf-8", errors="replace")
            texts[rel] = text
            folder = path.parent.relative_to(root).as_posix()
            pages.append({"id": rel, "kind": kind, "group": "" if folder == "." else folder,
                          "title": _title(path, text), "mtime": round(path.stat().st_mtime, 3)})
    ids = {p["id"] for p in pages}
    links = set()
    for rel, text in texts.items():
        if not rel.startswith("wiki/"):
            continue
        for target in WIKI_LINK.findall(text):
            other = f"wiki/{target.strip()}.md"
            if other in ids and other != rel:
                links.add(tuple(sorted((rel, other))))
        for mention in RAW_MENTION.findall(text):
            if mention in ids:
                links.add((mention, rel))                    # raw file -> the wiki page made from it
    return {"pages": pages, "links": [list(link) for link in sorted(links)], "alarms": _safety_failures(suite_dir)}


def _safety_failures(suite_dir: Path) -> int:
    """Test Suite cases whose safety check failed, over all saved campaigns."""
    count = 0
    for path in suite_dir.glob("*/report.json"):
        try:
            trials = json.loads(path.read_text(encoding="utf-8")).get("trials") or []
        except (OSError, ValueError):
            continue
        count += sum(1 for row in trials if isinstance(row, dict) and row.get("safety_status") == "fail")
    return count


def read_page(path: str, brain: Path = BRAIN_DIR) -> dict:
    """The text of one .md page inside brain/ (404 for anything else, e.g. a path that leaves the folder)."""
    try:
        target = (brain / path).resolve()
        found = target.suffix == ".md" and brain.resolve() in target.parents and target.is_file()
    except (ValueError, OSError):  # a null byte or an impossible path: not a page, not a server error
        found = False
    if not found:
        raise HTTPException(404, "No such page in the second brain.")
    return {"path": path, "text": target.read_text(encoding="utf-8", errors="replace")}


class BrainExtension(Extension):
    """Tool "Brain": the second brain (brain/) and the parts of DreamLab-Rat as one 3D brain view."""

    title = "Brain"
    icon = ""
    description = ("The second brain and DreamLab-Rat as one 3D brain. Regions light up when their part of the "
                   "system works; click a point to read its page.")
    order = 90

    def router(self):
        r = APIRouter()

        @r.get("/graph")
        def graph():
            return read_graph()

        @r.get("/page")
        def page(path: str):
            return read_page(path)

        return r
