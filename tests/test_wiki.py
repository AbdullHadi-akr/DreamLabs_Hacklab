"""The wiki script brain/build_wiki.py: pages from raw files, no AI agent."""

import importlib.util
from pathlib import Path

from dashboard import brain
from dashboard.lab_db import LabDB

spec = importlib.util.spec_from_file_location("build_wiki", Path(__file__).resolve().parents[1] / "brain" / "build_wiki.py")
build_wiki = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_wiki)


def write_raw(root: Path):
    (root / "raw" / "runs").mkdir(parents=True)
    (root / "raw" / "notes").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    (root / "wiki" / "overview.md").write_text("# Overview\n\nThis page explains Dream-1 Lab.\n", encoding="utf-8")
    (root / "wiki" / "log.md").write_text("# Log\n\nWhat was read and changed.\n", encoding="utf-8")
    head = ("# Dream-1 runs on 2026-11-22\n\n| Time | Run | Task | Prompt | Model | Source | Result | Stop reason | "
            "Calls | Cost (USD) | Seconds |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
    rows = ["| 10:00:00 | 1 | put banana on the plate | p | dreamlabs/dream-1-beta | core | yes | success | 10 | 0.0140 | 9.5 |",
            "| 10:05:00 | 2 | put banana on the plate | p | dreamlabs/dream-1-beta | core | no | time limit | 30 | 0.0420 | 60 |",
            "| 10:10:00 | 3 | lift the apple | p | dreamlabs/dream-1-beta | core | yes | success | 5 | 0.0070 | 4 |"]
    (root / "raw" / "runs" / "2026-11-22.md").write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    (root / "raw" / "notes" / "2026-11-22-meeting.md").write_text(
        "# Meeting with Dream Labs\n\n- Decision: train only on the part after the take-over.\n"
        "- **Decision:** ask about the price first.\nNo decision here.\n", encoding="utf-8")


def test_pages_counts_index_and_decisions(tmp_path):
    write_raw(tmp_path)
    result = build_wiki.build(tmp_path, now="2026-11-22 12:00")
    wiki = tmp_path / "wiki"
    task = (wiki / "tasks" / "banana-onto-the-plate.md").read_text(encoding="utf-8")
    assert "successes: 1 (50 %)" in task and "cost: $0.0560" in task and "cost per success: $0.0560" in task
    assert "| time limit | 1 |" in task and "`raw/runs/2026-11-22.md`" in task
    model = (wiki / "models" / "dreamlabs-dream-1-beta.md").read_text(encoding="utf-8")
    assert "[[tasks/lift-the-apple|lift the apple]]" in model
    decisions = (wiki / "decisions" / "decisions.md").read_text(encoding="utf-8")
    assert "train only on the part after the take-over" in decisions and "ask about the price first" in decisions
    assert "No decision here" not in decisions
    index = (wiki / "index.md").read_text(encoding="utf-8")
    assert "[[overview]]: This page explains Dream-1 Lab." in index and "[[tasks/lift-the-apple]]" in index
    assert "Meeting with Dream Labs" in (wiki / "notes.md").read_text(encoding="utf-8")
    assert "raw/runs/2026-11-22.md" in result["raw_read"]
    assert (wiki / "overview.md").read_text(encoding="utf-8").startswith("# Overview")  # a page it did not make
    log = (wiki / "log.md").read_text(encoding="utf-8")
    assert log.count("build by the script") == 1


def test_second_build_changes_nothing_and_removes_old_pages(tmp_path):
    write_raw(tmp_path)
    build_wiki.build(tmp_path, now="1")
    again = build_wiki.build(tmp_path, now="2")
    assert again == {"changed": [], "raw_read": []}
    assert (tmp_path / "wiki" / "log.md").read_text(encoding="utf-8").count("build by the script") == 1
    runs = tmp_path / "raw" / "runs" / "2026-11-22.md"
    runs.write_text("\n".join(line for line in runs.read_text().splitlines() if "lift the apple" not in line) + "\n")
    third = build_wiki.build(tmp_path, now="3")
    assert "tasks/lift-the-apple.md (removed)" in third["changed"]
    assert not (tmp_path / "wiki" / "tasks" / "lift-the-apple.md").exists()


def test_dashboard_rebuilds_the_wiki_after_a_run(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "BRAIN_DIR", tmp_path / "brain")
    brain.run_ended({"task": "lift the apple", "model": "m", "source": "core", "prompt": "p"},
                    {"success": True, "stop_reason": "success", "requests": 2, "cost_usd": 0.0028,
                     "sim_seconds": 3.0}, 1)
    brain.daily_summary(LabDB(tmp_path / "lab.db"))
    page = tmp_path / "brain" / "wiki" / "tasks" / "lift-the-apple.md"
    assert page.exists() and "successes: 1 (100 %)" in page.read_text(encoding="utf-8")


def test_wordings_of_one_goal_share_a_page(tmp_path):
    """All wordings of one goal (German too) go to one page that lists them."""
    write_raw(tmp_path)
    runs = tmp_path / "raw" / "runs" / "2026-11-22.md"
    extra = ["| 11:00:00 | 4 | put apple into the bowl | p | dreamlabs/dream-1-beta | core | no | time limit | 8 | 0.0112 | 40 |",
             "| 11:05:00 | 5 | place the apple in the bowl | p | dreamlabs/dream-1-beta | core | yes | success | 6 | 0.0084 | 20 |",
             "| 11:10:00 | 6 | Leg den Apfel in die Schüssel | p | dreamlabs/dream-1-beta | core | yes | success | 4 | 0.0056 | 15 |"]
    runs.write_text(runs.read_text(encoding="utf-8") + chr(10).join(extra) + chr(10), encoding="utf-8")
    build_wiki.build(tmp_path, now="1")
    tasks = sorted(p.name for p in (tmp_path / "wiki" / "tasks").glob("*.md"))
    assert tasks == ["apple-into-the-bowl.md", "banana-onto-the-plate.md", "lift-the-apple.md"]
    page = (tmp_path / "wiki" / "tasks" / "apple-into-the-bowl.md").read_text(encoding="utf-8")
    assert "Dream-1 runs: 3" in page and "successes: 2 (67 %)" in page
    assert "## Wordings" in page and "| Leg den Apfel in die Schüssel | 1 | 1 | 100 % |" in page
    model = (tmp_path / "wiki" / "models" / "dreamlabs-dream-1-beta.md").read_text(encoding="utf-8")
    assert "[[tasks/apple-into-the-bowl|apple into the bowl]]" in model and "put apple into the bowl" not in model
