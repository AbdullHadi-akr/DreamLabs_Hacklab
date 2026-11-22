# Rules for the AI agent that keeps this wiki

**Status: planned, not in use yet.** Today the script `build_wiki.py` keeps the wiki (see `README.md`). These rules
are kept for when the team adds an AI agent. The agent must then leave the script's pages alone (they start with
"made by brain/build_wiki.py") and write its own pages next to them; the script lists those in `wiki/index.md` too.

This folder is the team's second brain for DreamLab-Rat. It follows Andrej Karpathy's "LLM wiki" idea: an AI agent
reads sources and writes a wiki of linked Markdown pages; people read the wiki and ask questions; the agent keeps it
up to date.

## The three parts

| Folder or file | Who writes it | What it holds |
|---|---|---|
| `raw/` | The dashboard by itself, and people | Sources. Never change or delete a file here. |
| `wiki/` | You, the agent | The wiki pages. People read them, for example in Obsidian. |
| `AGENTS.md` | People | These rules. Change them only when a person asks. |

What the dashboard writes into `raw/`:

- `raw/runs/<day>.md`: one line per Dream-1 run: task, model, result, calls, cost, simulated seconds.
- `raw/robustness/<campaign>.md`: one file per finished robustness campaign.
- `raw/exports/<name>.md`: one file per export of episodes for a fine-tune.
- `raw/summaries/<day>.md`: the day's summary from the lab database.

People add notes as Markdown files in `raw/notes/`: meeting notes, answers from Dream Labs, ideas.

## The three jobs

### 1. Ingest (a person says "ingest")

1. Read `wiki/log.md` to see which raw files were already read.
2. Read every raw file that is new or changed since then.
3. Update the wiki pages these files touch, and make new pages where a new topic starts.
4. Update `wiki/index.md`: every page, one line each.
5. Add one entry to the end of `wiki/log.md`: the date, the raw files read, the pages changed.

### 2. Answer (a person asks a question)

1. Read `wiki/index.md`, then the pages that fit the question.
2. Answer from the pages, and name each page you used.
3. If the answer is new knowledge, offer to save it as a page.

### 3. Check (a person says "check")

Look for: pages that contradict each other, statements that newer raw files have replaced, pages no other page
links to, topics that appear in raw files but have no page. Report them; change pages only after the person agrees.

## Page rules

- One topic per page. File names in lowercase with dashes: `wiki/tasks/banana-on-the-plate.md`.
- Start each page with one sentence that says what the page is about.
- Link pages with `[[page-name]]` (Obsidian links).
- Every number or result names its raw file, for example `(raw/runs/2026-11-21.md)`.
- Plain words: no jargon, no idioms. Explain each technical term the first time it appears on a page.
- Keep what was measured apart from what someone thinks: write "measured" or "idea".
- Never copy an API key, an access code, a password or personal data into the wiki.

## Folders in `wiki/`

- `wiki/tasks/`: one page per task, for example "put banana on the plate": how often Dream-1 succeeds, with which
  model, what fails, how many episodes exist.
- `wiki/models/`: one page per model, for example Dream-1 beta or a fine-tune: success per task, cost per success.
- `wiki/robustness/`: what the robustness campaigns found.
- `wiki/fine-tuning/`: exports, uploads, training jobs, and what each fine-tune changed.
- `wiki/decisions/`: decisions the team made, with the date and the reason.
