"""The lab's records: one SQLite file (out/lab.db) on the host laptop.

SQLite keeps a whole database in one file and needs no server program. The file is NOT committed to git (out/ is in
.gitignore): git cannot merge two copies of a database file. Summaries for people go into the wiki instead.

Tables:
    runs        one row per run (Dream-1, offline test motion, Home, robustness): task, model, result, calls, cost
    episodes    one row per recorded episode (a LeRobot folder in out/episodes/): who moved the arms, success
    finetunes   one row per export of episodes for a fine-tune: which episodes went in, and later the model id

The questions this answers, for whoever prepares a fine-tune:
    which episodes to train on      -> episodes where success = 1 and finetune_id IS NULL and long enough
    did the fine-tune help          -> runs grouped by model and task: share of successes
    what a success costs            -> sum(cost_usd) / sum(success) per model
    where Dream-1 fails             -> episodes where took_over = 1, grouped by task
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("DREAM_LAB_DB") or Path(__file__).resolve().parents[1] / "out" / "lab.db")

## Price per Dream-1 call in US dollars (the Dream Labs price list, beta). A model not listed here (a fine-tune, an
## offline run) gets no cost: NULL, not 0, so a sum never pretends to know.
PRICE_PER_CALL_USD = {"dreamlabs/dream-1-beta": 0.0014}

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    REAL NOT NULL,       -- seconds since 1970 (UTC)
    ended_at      REAL,
    task          TEXT NOT NULL,       -- the goal the success check judges
    prompt        TEXT,                -- the text Dream-1 received
    model         TEXT NOT NULL,       -- model id, or "offline"
    source        TEXT,                -- core, or the extension that started the run
    label         TEXT,
    stop_reason   TEXT,                -- success, timeout, stopped, take over, error: ...
    success       INTEGER,             -- 1, 0, or NULL when no success check exists for the task
    steps         INTEGER,
    calls         INTEGER,             -- Dream-1 calls
    mean_reply_s  REAL,
    seconds       REAL,                -- simulated seconds
    cost_usd      REAL                 -- calls x price; NULL when the price is unknown
);
CREATE TABLE IF NOT EXISTS episodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES runs(id),
    started_at      REAL NOT NULL,
    ended_at        REAL,
    task            TEXT NOT NULL,
    model           TEXT,              -- the model that started the episode
    status          TEXT NOT NULL,     -- recording, paused, takeover, saved, discarded
    took_over       INTEGER NOT NULL DEFAULT 0,  -- 1 when a person finished the task by remote control
    dream_frames    INTEGER NOT NULL DEFAULT 0,  -- frames while Dream-1 moved the arms
    person_frames   INTEGER NOT NULL DEFAULT 0,  -- frames while a person moved the arms
    fps             INTEGER,
    seconds         REAL,              -- simulated seconds
    dream_success   INTEGER,           -- did Dream-1 alone finish the task (1, 0, NULL)
    success         INTEGER,           -- success check at the end of the episode (1, 0, NULL)
    folder          TEXT,              -- the LeRobot folder, relative to out/episodes/
    finetune_id     INTEGER REFERENCES finetunes(id),  -- set when an export used this episode
    note            TEXT
);
CREATE TABLE IF NOT EXISTS finetunes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    REAL NOT NULL,
    name          TEXT NOT NULL,       -- the dataset name for Dream Labs
    task          TEXT,
    folder        TEXT NOT NULL,       -- the export folder, relative to out/exports/
    episodes      INTEGER NOT NULL,
    frames        INTEGER NOT NULL,
    model_id      TEXT,                -- dream-1-ft:... once Dream Labs has trained it
    status        TEXT NOT NULL,       -- exported, uploaded, training, done, failed
    cost_usd      REAL,
    note          TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key           TEXT PRIMARY KEY,    -- see dashboard/credits.py DEFAULTS
    value         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS episodes_task ON episodes(task, status, success);
CREATE INDEX IF NOT EXISTS runs_model_task ON runs(model, task);
"""


class LabDB:
    """Thread-safe: every call opens its own short connection; one lock keeps writes in order."""

    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def execute(self, sql: str, params=()) -> int:
        """A write. Returns the new row's id (for INSERT)."""
        with self._lock, self._connect() as con:
            return con.execute(sql, params).lastrowid

    def query(self, sql: str, params=()) -> list[dict]:
        with self._connect() as con:
            return [dict(row) for row in con.execute(sql, params).fetchall()]

    def update(self, table: str, row_id: int, **values) -> None:
        if not values:
            return
        columns = ", ".join(f"{key} = ?" for key in values)
        self.execute(f"UPDATE {table} SET {columns} WHERE id = ?", (*values.values(), row_id))

    # ---------- runs ----------

    def run_started(self, *, task, prompt, model, source, label) -> int:
        return self.execute(
            "INSERT INTO runs (started_at, task, prompt, model, source, label) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), task, prompt, model, source, label))

    def run_ended(self, run_id: int, result: dict) -> None:
        calls = result.get("requests") or 0
        price = PRICE_PER_CALL_USD.get(result.get("model"))
        success = result.get("success")
        self.update("runs", run_id, ended_at=time.time(), stop_reason=result.get("stop_reason"),
                    success=None if success is None else int(bool(success)), steps=result.get("steps"),
                    calls=calls, mean_reply_s=result.get("mean_rtt_s"),
                    seconds=result.get("sim_seconds", result.get("seconds")),
                    cost_usd=None if price is None else round(calls * price, 6))

    # ---------- summaries for the dashboard ----------

    def summary(self) -> dict:
        """The four questions, answered from the records."""
        return {
            "trainable": self.query(
                "SELECT task, COUNT(*) AS episodes, ROUND(SUM(seconds), 1) AS seconds FROM episodes "
                "WHERE status = 'saved' AND success = 1 AND finetune_id IS NULL GROUP BY task ORDER BY episodes DESC"),
            "by_model": self.query(
                "SELECT model, task, COUNT(*) AS runs, SUM(success) AS successes, "
                "ROUND(SUM(cost_usd), 4) AS cost_usd, "
                "CASE WHEN SUM(success) > 0 THEN ROUND(SUM(cost_usd) / SUM(success), 4) END AS cost_per_success "
                "FROM runs WHERE model != 'offline' AND success IS NOT NULL GROUP BY model, task ORDER BY task, model"),
            "takeovers": self.query(
                "SELECT task, COUNT(*) AS episodes, SUM(took_over) AS took_over FROM episodes "
                "WHERE status = 'saved' GROUP BY task ORDER BY took_over DESC"),
            "spent_usd": (self.query("SELECT ROUND(COALESCE(SUM(cost_usd), 0), 4) AS v FROM runs")[0]["v"]),
        }
