# Second brain

The team's shared memory for Dream-1 Lab: what we tried, what worked, what it cost, and what we decided.

## How it works

```
dashboard ──writes──> raw/  ──build_wiki.py reads──> wiki/ ──people read──> Obsidian or GitHub
people ─────writes──> raw/notes/
```

1. The dashboard writes every Dream-1 run, robustness campaign and export into `raw/` by itself.
2. Team members put their own notes into `raw/notes/` (meeting notes, answers from Dream Labs, ideas).
3. The script `build_wiki.py` makes the wiki pages from `raw/`: one page per task goal and per model (runs, success
   rate, cost, cost per success, why runs stopped). A task page is per goal, not per wording: "put apple into the
   bowl", "place the apple in the bowl" and "Leg den Apfel in die Schüssel" all count for `tasks/apple-into-the-bowl`,
   which lists the wordings and how each did. Tasks without a recognisable object and container keep their own
   page. It also makes pages for the robustness campaigns, the exports, the team notes, and the decisions. The dashboard runs it by itself after every run, campaign and export.
4. Everyone reads `wiki/`.

Later, an AI agent (Claude Code, Codex or another one) can be added: it would read `AGENTS.md`, summarize the
notes, find contradictions and answer questions. The script does not do these three jobs.

## How to use it

- **Read:** open this folder in Obsidian ("Open folder as vault") or read the files on GitHub. Start at
  `wiki/index.md`.
- **Update the wiki by hand:** `python brain/build_wiki.py` from the repository root (needs only Python; works
  on every laptop). After a `git pull` this changes nothing, because the pages depend only on `raw/`.
- **Write down a decision:** in a note in `raw/notes/`, write a line that starts with `Decision:`. It appears on
  `wiki/decisions/decisions.md` at the next build.
- **Pages the script makes** start with "made by brain/build_wiki.py". Do not edit them by hand; the next build
  overwrites them. Pages without this line (for example `overview.md`) the script never changes.
- **Share:** commit and push `raw/` and `wiki/` like any other change.

The lab database itself (`out/lab.db`) stays on the host laptop and is not in git. The wiki holds summaries of it.
