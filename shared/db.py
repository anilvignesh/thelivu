import json
import sqlite3
from datetime import datetime, timezone
from shared.config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL,
    source      TEXT DEFAULT 'owner',
    submitted_at TEXT DEFAULT (datetime('now')),
    status      TEXT DEFAULT 'queued'
);

CREATE TABLE IF NOT EXISTS seen_items (
    video_id    TEXT PRIMARY KEY,
    source      TEXT,
    ingested_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id            TEXT,
    source              TEXT,
    throughline         TEXT,
    trust_gate          TEXT,
    draft_text          TEXT,
    review_text         TEXT,
    verification_report TEXT,
    status              TEXT DEFAULT 'investigating',
    tg_msg_id           INTEGER,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS publications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES pipeline_runs(id),
    channel_msg_ids TEXT,
    confidence      TEXT,
    published_at    TEXT DEFAULT (datetime('now'))
);
"""


def _conn():
    import pathlib
    pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript(_SCHEMA)


def is_seen(video_id):
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM seen_items WHERE video_id = ?", (video_id,)
        ).fetchone() is not None


def mark_seen(video_id, source):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen_items (video_id, source) VALUES (?, ?)",
            (video_id, source),
        )
        c.commit()


def save_run(
    video_id,
    source,
    throughline,
    trust_gate,
    draft_text=None,
    review_text=None,
    verification_report=None,
    status="investigating",
):
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO pipeline_runs
               (video_id, source, throughline, trust_gate,
                draft_text, review_text, verification_report, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (video_id, source, throughline, trust_gate,
             draft_text, review_text, verification_report, status),
        )
        c.commit()
        return cur.lastrowid


def update_run(run_id, **kwargs):
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    with _conn() as c:
        c.execute(
            f"UPDATE pipeline_runs SET {sets} WHERE id = ?",
            (*kwargs.values(), run_id),
        )
        c.commit()


def get_run(run_id):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None


def get_held_runs(older_than_days=3):
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM pipeline_runs
               WHERE status = 'held'
               AND created_at < datetime('now', ?)""",
            (f"-{older_than_days} days",),
        ).fetchall()
        return [dict(r) for r in rows]


def queue_topic(topic, source="owner"):
    with _conn() as c:
        c.execute(
            "INSERT INTO pending_topics (topic, source) VALUES (?, ?)",
            (topic, source),
        )
        c.commit()


def pop_next_topic():
    """Return and claim the oldest queued topic, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pending_topics WHERE status = 'queued' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE pending_topics SET status = 'running' WHERE id = ?", (row["id"],)
        )
        c.commit()
        return dict(row)


def finish_topic(topic_id):
    with _conn() as c:
        c.execute(
            "UPDATE pending_topics SET status = 'done' WHERE id = ?", (topic_id,)
        )
        c.commit()


def save_publication(run_id, channel_msg_ids, confidence):
    with _conn() as c:
        c.execute(
            "INSERT INTO publications (run_id, channel_msg_ids, confidence) VALUES (?, ?, ?)",
            (run_id, json.dumps(channel_msg_ids), confidence),
        )
        c.commit()
