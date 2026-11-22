"""The Brain tool's backend: pages, links and safety failures from the second brain; no file outside brain/."""

import json

import pytest
from fastapi import HTTPException

from dashboard.extensions.brain import read_graph, read_page


def make_brain(tmp_path):
    brain = tmp_path / "brain"
    (brain / "wiki" / "tasks").mkdir(parents=True)
    (brain / "raw" / "runs").mkdir(parents=True)
    (brain / "raw" / "notes").mkdir(parents=True)
    (brain / "wiki" / "index.md").write_text("# Index\n\n- [[tasks/apple]]: the apple task\n", encoding="utf-8")
    (brain / "wiki" / "tasks" / "apple.md").write_text(
        "# Task: apple\n\nBack to [[index|the index]].\n\nSources: raw/runs/2026-11-22.md\n", encoding="utf-8")
    (brain / "raw" / "runs" / "2026-11-22.md").write_text("# Runs\n", encoding="utf-8")
    (brain / "raw" / "notes" / "README.md").write_text("# How to write notes\n", encoding="utf-8")
    (brain / "CLAUDE.md").write_text("rules", encoding="utf-8")
    return brain


def test_graph_reads_pages_and_links(tmp_path):
    brain = make_brain(tmp_path)
    suite = tmp_path / "suite"
    (suite / "c1").mkdir(parents=True)
    (suite / "c1" / "report.json").write_text(json.dumps(
        {"trials": [{"safety_status": "fail"}, {"safety_status": "pass"}, {"safety_status": "fail"}]}), encoding="utf-8")

    graph = read_graph(brain, suite)

    ids = {p["id"]: p for p in graph["pages"]}
    assert set(ids) == {"wiki/index.md", "wiki/tasks/apple.md", "raw/runs/2026-11-22.md"}  # README is not a memory
    assert ids["wiki/tasks/apple.md"]["title"] == "Task: apple"
    assert ids["wiki/tasks/apple.md"]["group"] == "tasks" and ids["raw/runs/2026-11-22.md"]["kind"] == "raw"
    assert ["wiki/index.md", "wiki/tasks/apple.md"] in graph["links"]  # the [[link]], both directions as one line
    assert ["raw/runs/2026-11-22.md", "wiki/tasks/apple.md"] in graph["links"]  # the source mention
    assert len(graph["links"]) == 2
    assert graph["alarms"] == 2


def test_page_reads_only_markdown_inside_brain(tmp_path):
    brain = make_brain(tmp_path)
    (tmp_path / "secret.md").write_text("no", encoding="utf-8")

    assert read_page("wiki/tasks/apple.md", brain)["text"].startswith("# Task: apple")
    for path in ("../secret.md", "wiki/../../secret.md", "CLAUDE", "wiki/missing.md"):
        with pytest.raises(HTTPException):
            read_page(path, brain)
