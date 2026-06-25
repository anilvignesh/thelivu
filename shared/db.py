import json
import os
from datetime import datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv_store (
    key   TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_proposals (
    id          SERIAL PRIMARY KEY,
    name        TEXT,
    platform    TEXT,
    handle      TEXT,
    feed_url    TEXT,
    lean        TEXT,
    role        TEXT,
    tier        INTEGER,
    notes       TEXT,
    tg_msg_id   INTEGER,
    status      TEXT DEFAULT 'pending',
    proposed_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approved_sources (
    id        SERIAL PRIMARY KEY,
    name      TEXT,
    platform  TEXT,
    handle    TEXT,
    feed_url  TEXT,
    lean      TEXT,
    role      TEXT DEFAULT 'lead',
    tier      INTEGER DEFAULT 3,
    notes     TEXT,
    status    TEXT DEFAULT 'active',
    added_at  TIMESTAMP DEFAULT NOW()
);

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
    legal_flag          BOOLEAN DEFAULT FALSE,
    legal_reason        TEXT,
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

CREATE TABLE IF NOT EXISTS active_agents (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER,
    skill       TEXT,
    model       TEXT,
    topic       TEXT,
    started_at  TIMESTAMP DEFAULT NOW()
);
"""

# SQLite fallback schema (same structure, SQLite syntax)
_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS kv_store (
    key   TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    platform    TEXT,
    handle      TEXT,
    feed_url    TEXT,
    lean        TEXT,
    role        TEXT,
    tier        INTEGER,
    notes       TEXT,
    tg_msg_id   INTEGER,
    status      TEXT DEFAULT 'pending',
    proposed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS approved_sources (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT,
    platform  TEXT,
    handle    TEXT,
    feed_url  TEXT,
    lean      TEXT,
    role      TEXT DEFAULT 'lead',
    tier      INTEGER DEFAULT 3,
    notes     TEXT,
    status    TEXT DEFAULT 'active',
    added_at  TEXT DEFAULT (datetime('now'))
);

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
    legal_flag          INTEGER DEFAULT 0,
    legal_reason        TEXT,
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

CREATE TABLE IF NOT EXISTS active_agents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER,
    skill       TEXT,
    model       TEXT,
    topic       TEXT,
    started_at  TEXT DEFAULT (datetime('now'))
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
            # Migrations for existing tables
            for col, defn in [("legal_flag", "BOOLEAN DEFAULT FALSE"), ("legal_reason", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {col} {defn}")
                except Exception:
                    pass  # column already exists
        else:
            cur.executescript(_SCHEMA_SQLITE)
            for col, defn in [("legal_flag", "INTEGER DEFAULT 0"), ("legal_reason", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {col} {defn}")
                except Exception:
                    pass
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


def kv_set(key, value):
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "INSERT INTO kv_store (key, value, updated_at) VALUES (%s, %s, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (key, value),
            )
        else:
            cur.execute(
                "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", (key, value)
            )
        conn.commit()
    finally:
        conn.close()


def kv_get(key, default=None):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"SELECT value FROM kv_store WHERE key = {ph}", (key,))
        row = cur.fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def get_queue_state():
    """Return pending topics + last pipeline run for /queue display."""
    conn = _conn()
    try:
        cur = conn.cursor()
        # Pending/running owner topics
        cur.execute(
            "SELECT id, topic, source, status, submitted_at FROM pending_topics "
            "WHERE status IN ('queued', 'running') ORDER BY id"
        )
        topics = _fetchall(cur)
        # Last 3 pipeline runs
        cur.execute(
            "SELECT id, throughline, source, status, trust_gate, created_at "
            "FROM pipeline_runs ORDER BY id DESC LIMIT 3"
        )
        recent_runs = _fetchall(cur)
        return {"topics": topics, "recent_runs": recent_runs}
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


def save_proposal(name, platform, handle, feed_url, lean, role, tier, notes):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO source_proposals (name, platform, handle, feed_url, lean, role, tier, notes) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (name, platform, handle, feed_url, lean, role, tier, notes),
        )
        if _is_postgres():
            cur.execute("SELECT lastval()")
            pid = cur.fetchone()[0]
        else:
            pid = cur.lastrowid
        conn.commit()
        return pid
    finally:
        conn.close()


def set_proposal_msg_id(proposal_id, tg_msg_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"UPDATE source_proposals SET tg_msg_id={ph} WHERE id={ph}", (tg_msg_id, proposal_id))
        conn.commit()
    finally:
        conn.close()


def approve_proposal(proposal_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"SELECT * FROM source_proposals WHERE id={ph}", (proposal_id,))
        row = _fetchone(cur)
        if not row:
            return None
        cur.execute(
            f"INSERT INTO approved_sources (name, platform, handle, feed_url, lean, role, tier, notes) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (row["name"], row["platform"], row["handle"], row["feed_url"],
             row["lean"], row["role"], row["tier"], row["notes"]),
        )
        cur.execute(f"UPDATE source_proposals SET status='approved' WHERE id={ph}", (proposal_id,))
        conn.commit()
        return row
    finally:
        conn.close()


def skip_proposal(proposal_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"UPDATE source_proposals SET status='skipped' WHERE id={ph}", (proposal_id,))
        conn.commit()
    finally:
        conn.close()


def get_approved_sources():
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM approved_sources WHERE status='active'")
        return _fetchall(cur)
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


def agent_start(skill, model, topic=None, run_id=None):
    """Record that a skill agent has started. Returns the active_agent id."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO active_agents (run_id, skill, model, topic) VALUES ({ph},{ph},{ph},{ph})",
            (run_id, skill, model, (topic or "")[:120]),
        )
        if _is_postgres():
            cur.execute("SELECT lastval()")
            aid = cur.fetchone()[0]
        else:
            aid = cur.lastrowid
        conn.commit()
        return aid
    finally:
        conn.close()


def agent_done(agent_id):
    """Remove the active_agent entry when a skill finishes."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"DELETE FROM active_agents WHERE id = {ph}", (agent_id,))
        conn.commit()
    finally:
        conn.close()


def clear_stale_agents():
    """Remove active_agent rows older than 30 minutes (crash recovery)."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("DELETE FROM active_agents WHERE started_at < NOW() - INTERVAL '30 minutes'")
        else:
            cur.execute("DELETE FROM active_agents WHERE started_at < datetime('now', '-30 minutes')")
        conn.commit()
    finally:
        conn.close()


def get_source_reliability():
    """Return per-source trust gate outcomes computed from pipeline_runs."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("""
                SELECT source,
                       COUNT(*) as total,
                       COUNT(*) FILTER (WHERE trust_gate IN ('READY-FOR-HUMAN','FRAMING-FIX')) as verified,
                       COUNT(*) FILTER (WHERE trust_gate = 'KILL') as killed,
                       COUNT(*) FILTER (WHERE trust_gate = 'HOLD') as held
                FROM pipeline_runs
                WHERE source IS NOT NULL
                GROUP BY source
                HAVING COUNT(*) >= 2
                ORDER BY verified DESC
            """)
        else:
            cur.execute("""
                SELECT source,
                       COUNT(*) as total,
                       SUM(CASE WHEN trust_gate IN ('READY-FOR-HUMAN','FRAMING-FIX') THEN 1 ELSE 0 END) as verified,
                       SUM(CASE WHEN trust_gate = 'KILL' THEN 1 ELSE 0 END) as killed,
                       SUM(CASE WHEN trust_gate = 'HOLD' THEN 1 ELSE 0 END) as held
                FROM pipeline_runs
                WHERE source IS NOT NULL
                GROUP BY source
                HAVING COUNT(*) >= 2
                ORDER BY verified DESC
            """)
        return _fetchall(cur)
    finally:
        conn.close()


def get_published_stories(days=90):
    """Return published stories for follow-up tracking."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute("""
                SELECT r.id, r.throughline, r.source, r.created_at,
                       LEFT(r.draft_text, 800) as draft_summary,
                       r.trust_gate
                FROM pipeline_runs r
                JOIN publications p ON p.run_id = r.id
                WHERE r.created_at > NOW() - INTERVAL '%s days'
                ORDER BY r.created_at DESC
                LIMIT 20
            """, (days,))
        else:
            cur.execute("""
                SELECT r.id, r.throughline, r.source, r.created_at,
                       SUBSTR(r.draft_text, 1, 800) as draft_summary,
                       r.trust_gate
                FROM pipeline_runs r
                JOIN publications p ON p.run_id = r.id
                WHERE r.created_at > datetime('now', ?)
                ORDER BY r.created_at DESC
                LIMIT 20
            """, (f"-{days} days",))
        return _fetchall(cur)
    finally:
        conn.close()


def get_all_runs_summary(limit=60):
    """Return summary of all runs for meta-synthesis."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        if _is_postgres():
            cur.execute("""
                SELECT r.id, r.throughline, r.source, r.trust_gate, r.status,
                       r.created_at::date as date,
                       LEFT(r.review_text, 400) as review_summary,
                       EXISTS(SELECT 1 FROM publications p WHERE p.run_id = r.id) as published
                FROM pipeline_runs r
                ORDER BY r.created_at DESC
                LIMIT %s
            """, (limit,))
        else:
            cur.execute("""
                SELECT r.id, r.throughline, r.source, r.trust_gate, r.status,
                       date(r.created_at) as date,
                       SUBSTR(r.review_text, 1, 400) as review_summary,
                       EXISTS(SELECT 1 FROM publications p WHERE p.run_id = r.id) as published
                FROM pipeline_runs r
                ORDER BY r.created_at DESC
                LIMIT ?
            """, (limit,))
        return _fetchall(cur)
    finally:
        conn.close()


def update_run_legal_flag(run_id, legal_flag, legal_reason=""):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"UPDATE pipeline_runs SET legal_flag={ph}, legal_reason={ph}, updated_at={ph} WHERE id={ph}",
            (legal_flag, legal_reason, datetime.now(timezone.utc).isoformat(), run_id),
        )
        conn.commit()
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


def reset_run_for_review(run_id):
    """Undo a publication so a run can be approved again.

    Deletes any publication rows for the run and sets its status back to
    pending_human. Use when a run was published in error (or wrongly marked
    published) and needs to go back through the human gate. Does NOT touch the
    channel — any bad post already sent must be deleted there by hand.

    Returns the refreshed run dict, or None if the run does not exist.
    """
    if get_run(run_id) is None:
        return None
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"DELETE FROM publications WHERE run_id = {ph}", (run_id,))
        conn.commit()
    finally:
        conn.close()
    update_run(run_id, status="pending_human")
    return get_run(run_id)
