# Second brain

The team's shared memory for Dream-1 Lab: what we tried, what worked, what it cost, and what we decided.

## How it works

```
dashboard ──writes──> raw/  ──an AI agent reads──> wiki/ ──people read──> Obsidian or GitHub
people ─────writes──> raw/notes/
```

1. The dashboard writes every Dream-1 run, robustness campaign and export into `raw/` by itself.
2. Team members put their own notes into `raw/notes/` (meeting notes, answers from Dream Labs, ideas).
3. An AI agent (Claude Code, Codex or another one) reads `AGENTS.md` and keeps `wiki/` up to date.
4. Everyone reads `wiki/`.

## How to use it

- **Read:** open this folder in Obsidian ("Open folder as vault") or read the files on GitHub. Start at
  `wiki/index.md`.
- **Update the wiki:** open an AI agent in this folder and write `ingest`.
- **Ask a question:** ask the agent, for example "How often does Dream-1 put the banana on the plate?"
- **Check the wiki:** write `check`.
- **Share:** commit and push `raw/` and `wiki/` like any other change.

The lab database itself (`out/lab.db`) stays on the host laptop and is not in git. The wiki holds summaries of it.
