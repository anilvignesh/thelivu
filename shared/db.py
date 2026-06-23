import json
import os
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS token_usage (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER,
    skill           TEXT,
    model           TEXT,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    recorded_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pending_topics (
    id          SERIAL PRIMARY KEY,
    topic       TEXT NOT NULL,
    source      TEXT DEFAULT 'owner',
    submitted_at TIMESTAMP DEFAULT NOW(),
    status      TEXT DEFAULT 'queued'
);

CREATE TABLE IF NOT EXISTS seen_items (
    video_id    TEXT PRIMARY KEY,
    source      TEXT,
    ingested_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                  SERIAL PRIMARY KEY,
    video_id            TEXT,
    source              TEXT,
    throughline         TEXT,
    trust_gate          TEXT,
    draft_text          TEXT,
    review_text         TEXT,
    verification_report TEXT,
    status              TEXT DEFAULT 'investigating',
    tg_msg_id           INTEGER,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS publications (
    id              SERIAL PRIMARY KEY,
    run_id          INTEGER REFERENCES pipeline_runs(id),
    channel_msg_ids TEXT,
    confidence      TEXT,
    published_at    TIMESTAMP DEFAULT NOW()
);
"""

# SQLite fallback schema (same structure, SQLite syntax)
_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS token_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER,
    skill           TEXT,
    model           TEXT,
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    recorded_at     TEXT DEFAULT (datetime('now'))
);

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
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        c = psycopg2.connect(DATABASE_URL)
        return c
    else:
        import sqlite3
        import pathlib
        from shared.config import DB_PATH
        pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        return c


def _is_postgres():
    return bool(DATABASE_URL)


def _fetchone(cur):
    row = cur.fetchone()
    if row is None:
        return None
    if _is_postgres():
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))
    return dict(row)


def _fetchall(cur):
    rows = cur.fetchall()
    if _is_postgres():
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, r)) for r in rows]
    return [dict(r) for r in rows]


def init_db():
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            for statement in _SCHEMA.strip().split(";"):
                s = statement.strip()
                if s:
                    cur.execute(s)
        else:
            cur.executescript(_SCHEMA_SQLITE)
        conn.commit()
    finally:
        conn.close()


def is_seen(video_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM seen_items WHERE video_id = %s" if _is_postgres()
                    else "SELECT 1 FROM seen_items WHERE video_id = ?", (video_id,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def mark_seen(video_id, source):
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "INSERT INTO seen_items (video_id, source) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (video_id, source),
            )
        else:
            cur.execute(
                "INSERT OR IGNORE INTO seen_items (video_id, source) VALUES (?, ?)",
                (video_id, source),
            )
        conn.commit()
    finally:
        conn.close()


def save_run(video_id, source, throughline, trust_gate,
             draft_text=None, review_text=None, verification_report=None, status="investigating"):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"""INSERT INTO pipeline_runs
               (video_id, source, throughline, trust_gate,
                draft_text, review_text, verification_report, status)
               VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (video_id, source, throughline, trust_gate,
             draft_text, review_text, verification_report, status),
        )
        if _is_postgres():
            cur.execute("SELECT lastval()")
            run_id = cur.fetchone()[0]
        else:
            run_id = cur.lastrowid
        conn.commit()
        return run_id
    finally:
        conn.close()


def update_run(run_id, **kwargs):
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    ph = "%s" if _is_postgres() else "?"
    sets = ", ".join(f"{k} = {ph}" for k in kwargs)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pipeline_runs SET {sets} WHERE id = {ph}",
            (*kwargs.values(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_run(run_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute("SELECT * FROM pipeline_runs WHERE id = " + ph, (run_id,))
        return _fetchone(cur)
    finally:
        conn.close()


def get_held_runs(older_than_days=3):
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "SELECT * FROM pipeline_runs WHERE status = 'held' "
                "AND created_at < NOW() - INTERVAL '%s days'",
                (older_than_days,),
            )
        else:
            cur.execute(
                "SELECT * FROM pipeline_runs WHERE status = 'held' "
                "AND created_at < datetime('now', ?)",
                (f"-{older_than_days} days",),
            )
        return _fetchall(cur)
    finally:
        conn.close()


def queue_topic(topic, source="owner"):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO pending_topics (topic, source) VALUES ({ph}, {ph})",
            (topic, source),
        )
        conn.commit()
    finally:
        conn.close()


def pop_next_topic():
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "SELECT * FROM pending_topics WHERE status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
            )
        else:
            cur.execute(
                "SELECT * FROM pending_topics WHERE status = 'queued' ORDER BY id LIMIT 1"
            )
        row = _fetchone(cur)
        if not row:
            return None
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"UPDATE pending_topics SET status = 'running' WHERE id = {ph}", (row["id"],)
        )
        conn.commit()
        return row
    finally:
        conn.close()


def finish_topic(topic_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"UPDATE pending_topics SET status = 'done' WHERE id = {ph}", (topic_id,)
        )
        conn.commit()
    finally:
        conn.close()


def record_usage(skill, model, input_tokens, output_tokens, run_id=None):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO token_usage (run_id, skill, model, input_tokens, output_tokens) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph})",
            (run_id, skill, model, input_tokens, output_tokens),
        )
        conn.commit()
    finally:
        conn.close()


def get_cost_report_data():
    """Return token usage aggregated for today, this month, and all time."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("""
                SELECT
                    model,
                    SUM(input_tokens)  FILTER (WHERE recorded_at::date = CURRENT_DATE)  AS today_in,
                    SUM(output_tokens) FILTER (WHERE recorded_at::date = CURRENT_DATE)  AS today_out,
                    SUM(input_tokens)  FILTER (WHERE DATE_TRUNC('month', recorded_at) = DATE_TRUNC('month', NOW())) AS month_in,
                    SUM(output_tokens) FILTER (WHERE DATE_TRUNC('month', recorded_at) = DATE_TRUNC('month', NOW())) AS month_out,
                    SUM(input_tokens)  AS total_in,
                    SUM(output_tokens) AS total_out
                FROM token_usage
                GROUP BY model
            """)
        else:
            cur.execute("""
                SELECT
                    model,
                    SUM(CASE WHEN date(recorded_at)=date('now') THEN input_tokens ELSE 0 END)  AS today_in,
                    SUM(CASE WHEN date(recorded_at)=date('now') THEN output_tokens ELSE 0 END) AS today_out,
                    SUM(CASE WHEN strftime('%Y-%m',recorded_at)=strftime('%Y-%m','now') THEN input_tokens ELSE 0 END)  AS month_in,
                    SUM(CASE WHEN strftime('%Y-%m',recorded_at)=strftime('%Y-%m','now') THEN output_tokens ELSE 0 END) AS month_out,
                    SUM(input_tokens)  AS total_in,
                    SUM(output_tokens) AS total_out
                FROM token_usage
                GROUP BY model
            """)
        rows = _fetchall(cur)
        # runs today
        if _is_postgres():
            cur.execute("SELECT COUNT(*) FROM pipeline_runs WHERE created_at::date = CURRENT_DATE")
        else:
            cur.execute("SELECT COUNT(*) FROM pipeline_runs WHERE date(created_at) = date('now')")
        runs_today = cur.fetchone()[0]
        return {"by_model": rows, "runs_today": runs_today}
    finally:
        conn.close()


def get_pending_runs():
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, throughline, trust_gate, created_at FROM pipeline_runs "
            "WHERE status = 'pending_human' ORDER BY id DESC"
        )
        return _fetchall(cur)
    finally:
        conn.close()


def save_publication(run_id, channel_msg_ids, confidence):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO publications (run_id, channel_msg_ids, confidence) VALUES ({ph},{ph},{ph})",
            (run_id, json.dumps(channel_msg_ids), confidence),
        )
        conn.commit()
    finally:
        conn.close()
