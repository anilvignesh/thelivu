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
    slug                TEXT,
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

CREATE TABLE IF NOT EXISTS lead_queue (
    id           SERIAL PRIMARY KEY,
    video_id     TEXT UNIQUE,
    source       TEXT,
    source_id    TEXT,
    video_url    TEXT,
    title        TEXT,
    throughline  TEXT,
    claims       TEXT,
    status       TEXT DEFAULT 'queued',
    created_at   TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS carousel_runs (
    id             SERIAL PRIMARY KEY,
    run_id         INTEGER REFERENCES pipeline_runs(id),
    article_url    TEXT,
    caption        TEXT,
    status         TEXT DEFAULT 'queued',
    tg_msg_id      INTEGER,
    ig_media_id    TEXT,
    ig_permalink   TEXT,
    created_at     TIMESTAMP DEFAULT NOW(),
    posted_at      TIMESTAMP,
    files_cleaned_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS carousel_slides (
    id             SERIAL PRIMARY KEY,
    carousel_id    INTEGER REFERENCES carousel_runs(id),
    position       INTEGER,
    headline       TEXT,
    image_path     TEXT,
    image_url      TEXT
);

CREATE TABLE IF NOT EXISTS bio_links (
    id          SERIAL PRIMARY KEY,
    title       TEXT,
    url         TEXT,
    pinned      BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS digs (
    id             SERIAL PRIMARY KEY,
    title          TEXT NOT NULL,
    question       TEXT,
    kerala_anchor  TEXT,
    hypothesis     TEXT,
    status         TEXT DEFAULT 'scoping',
    priority       INTEGER DEFAULT 2,
    watchlist_id   TEXT,
    owner_note     TEXT,
    next_action_at TIMESTAMP,
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dig_updates (
    id          SERIAL PRIMARY KEY,
    dig_id      INTEGER REFERENCES digs(id),
    kind        TEXT DEFAULT 'note',
    body        TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
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
    slug                TEXT,
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

CREATE TABLE IF NOT EXISTS lead_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id     TEXT UNIQUE,
    source       TEXT,
    source_id    TEXT,
    video_url    TEXT,
    title        TEXT,
    throughline  TEXT,
    claims       TEXT,
    status       TEXT DEFAULT 'queued',
    created_at   TEXT DEFAULT (datetime('now')),
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS carousel_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER REFERENCES pipeline_runs(id),
    article_url    TEXT,
    caption        TEXT,
    status         TEXT DEFAULT 'queued',
    tg_msg_id      INTEGER,
    ig_media_id    TEXT,
    ig_permalink   TEXT,
    created_at     TEXT DEFAULT (datetime('now')),
    posted_at      TEXT,
    files_cleaned_at TEXT
);

CREATE TABLE IF NOT EXISTS carousel_slides (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    carousel_id    INTEGER REFERENCES carousel_runs(id),
    position       INTEGER,
    headline       TEXT,
    image_path     TEXT,
    image_url      TEXT
);

CREATE TABLE IF NOT EXISTS bio_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT,
    url         TEXT,
    pinned      INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS digs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    question       TEXT,
    kerala_anchor  TEXT,
    hypothesis     TEXT,
    status         TEXT DEFAULT 'scoping',
    priority       INTEGER DEFAULT 2,
    watchlist_id   TEXT,
    owner_note     TEXT,
    next_action_at TEXT,
    created_at     TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS dig_updates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dig_id      INTEGER REFERENCES digs(id),
    kind        TEXT DEFAULT 'note',
    body        TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
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
                    try:
                        cur.execute(s)
                        conn.commit()
                    except Exception:
                        conn.rollback()
            # Migrations for existing tables
            for col, defn in [("legal_flag", "BOOLEAN DEFAULT FALSE"), ("legal_reason", "TEXT"), ("slug", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
            for col, defn in [("files_cleaned_at", "TIMESTAMP"),
                              ("dark", "BOOLEAN DEFAULT FALSE"), ("stamp", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE carousel_runs ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
        else:
            cur.executescript(_SCHEMA_SQLITE)
            for col, defn in [("legal_flag", "INTEGER DEFAULT 0"), ("legal_reason", "TEXT"), ("slug", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            for col, defn in [("files_cleaned_at", "TEXT"),
                              ("dark", "INTEGER DEFAULT 0"), ("stamp", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE carousel_runs ADD COLUMN {col} {defn}")
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


def get_recheckable_runs(limit=30):
    """Held stories the owner can ask to re-develop — both human-held ('held') and
    verifier-held ('hold'), newest first."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, throughline, trust_gate, status, created_at "
            "FROM pipeline_runs WHERE status IN ('held', 'hold') "
            "ORDER BY id DESC LIMIT " + ("%s" if _is_postgres() else "?"),
            (limit,),
        )
        return _fetchall(cur)
    finally:
        conn.close()


def get_runs_by_status(status, limit=20):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"SELECT * FROM pipeline_runs WHERE status = {ph} ORDER BY id LIMIT {ph}",
            (status, limit),
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


def requeue_topic(topic_id):
    """Put an owner topic back in the queue (e.g. a provider outage paused it) so a
    later cycle retries it instead of dropping it."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"UPDATE pending_topics SET status = 'queued' WHERE id = {ph}", (topic_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ── Lead queue ────────────────────────────────────────────────────────────────
# Captured leads persist here so the cheap "find leads" stage survives a provider
# outage; the expensive spine drains the queue when credit is available.

def enqueue_lead(lead):
    """Insert a captured lead if its video_id isn't already queued. Returns True
    if newly enqueued. Dedup is by video_id (ON CONFLICT DO NOTHING)."""
    vid = lead.get("video_id")
    if not vid:
        return False
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        conflict = "ON CONFLICT (video_id) DO NOTHING" if _is_postgres() else "OR IGNORE"
        if _is_postgres():
            sql = (f"INSERT INTO lead_queue (video_id, source, source_id, video_url, "
                   f"title, throughline, claims) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph}) {conflict}")
        else:
            sql = (f"INSERT OR IGNORE INTO lead_queue (video_id, source, source_id, video_url, "
                   f"title, throughline, claims) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})")
        cur.execute(sql, (
            vid, lead.get("source"), lead.get("source_id"), lead.get("video_url"),
            lead.get("title"), lead.get("throughline"),
            json.dumps(lead.get("claims") or []),
        ))
        newly = cur.rowcount > 0
        conn.commit()
        return newly
    finally:
        conn.close()


def get_queued_leads(limit=40, max_age_days=7):
    """Return queued leads newer than max_age_days, freshest first, as lead dicts
    the daily cycle can feed straight into news-monitor / the spine."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "SELECT * FROM lead_queue WHERE status = 'queued' "
                "AND created_at > NOW() - INTERVAL '%s days' "
                "ORDER BY created_at DESC LIMIT %s",
                (max_age_days, limit),
            )
        else:
            cur.execute(
                "SELECT * FROM lead_queue WHERE status = 'queued' "
                "AND created_at > datetime('now', ?) ORDER BY created_at DESC LIMIT ?",
                (f"-{max_age_days} days", limit),
            )
        leads = []
        for row in _fetchall(cur):
            try:
                row["claims"] = json.loads(row.get("claims") or "[]")
            except Exception:
                row["claims"] = []
            row["queue_id"] = row["id"]
            leads.append(row)
        return leads
    finally:
        conn.close()


def mark_lead_processed(queue_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        ts = datetime.now(timezone.utc).isoformat()
        cur.execute(
            f"UPDATE lead_queue SET status = 'processed', processed_at = {ph} WHERE id = {ph}",
            (ts, queue_id),
        )
        conn.commit()
    finally:
        conn.close()


def requeue_lead(queue_id):
    """Put a lead back in the queue (e.g. a provider went down mid-spine) so it is
    retried from scratch on a later cycle instead of being lost."""
    if not queue_id:
        return
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"UPDATE lead_queue SET status = 'queued', processed_at = NULL WHERE id = {ph}",
            (queue_id,),
        )
        conn.commit()
    finally:
        conn.close()


def expire_old_leads(max_age_days=7):
    """Drop queued leads older than the window so the backlog can't fill with
    stale news. Returns the number expired."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "UPDATE lead_queue SET status = 'dropped' WHERE status = 'queued' "
                "AND created_at < NOW() - INTERVAL '%s days'", (max_age_days,),
            )
        else:
            cur.execute(
                "UPDATE lead_queue SET status = 'dropped' WHERE status = 'queued' "
                "AND created_at < datetime('now', ?)", (f"-{max_age_days} days",),
            )
        n = cur.rowcount
        conn.commit()
        return n
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
        # Queued topics only — 'running' ones are either live (agent is on it right
        # now) or stale (crashed; startup cleanup resets them). Show both but tag
        # stale ones so the /queue display can warn appropriately.
        if _is_postgres():
            cur.execute(
                "SELECT id, topic, source, status, submitted_at, "
                "(status='running' AND submitted_at < NOW() - INTERVAL '1 hour') AS stale "
                "FROM pending_topics WHERE status IN ('queued', 'running') ORDER BY id"
            )
        else:
            cur.execute(
                "SELECT id, topic, source, status, submitted_at, "
                "(status='running' AND submitted_at < datetime('now', '-1 hour')) AS stale "
                "FROM pending_topics WHERE status IN ('queued', 'running') ORDER BY id"
            )
        topics = _fetchall(cur)
        # Last 5 pipeline runs
        cur.execute(
            "SELECT id, throughline, source, status, trust_gate, created_at "
            "FROM pipeline_runs ORDER BY id DESC LIMIT 5"
        )
        recent_runs = _fetchall(cur)
        return {"topics": topics, "recent_runs": recent_runs}
    finally:
        conn.close()


def get_daily_costs(days=7):
    """Return per-day, per-model token usage for the last N days (for trend chart)."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "SELECT recorded_at::date AS day, model, "
                "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok "
                "FROM token_usage WHERE recorded_at >= NOW() - INTERVAL %s "
                "GROUP BY recorded_at::date, model ORDER BY day",
                (f"{days} days",),
            )
        else:
            cur.execute(
                "SELECT date(recorded_at) AS day, model, "
                "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok "
                "FROM token_usage WHERE recorded_at >= datetime('now', ?) "
                "GROUP BY date(recorded_at), model ORDER BY day",
                (f"-{days} days",),
            )
        return _fetchall(cur)
    finally:
        conn.close()


def deactivate_approved_source(source_id):
    """Mark a DB-approved source as inactive so it stops being ingested."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"UPDATE approved_sources SET status='inactive' WHERE id={ph}", (source_id,))
        conn.commit()
        return cur.rowcount > 0
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


def get_pipeline_stats():
    """Lifetime pipeline statistics for /stats command."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM pipeline_runs GROUP BY status")
        by_status = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("""
            SELECT source,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) AS published,
                   SUM(CASE WHEN status='killed' THEN 1 ELSE 0 END) AS killed
            FROM pipeline_runs
            WHERE source IS NOT NULL
            GROUP BY source ORDER BY published DESC LIMIT 5
        """)
        top_sources = _fetchall(cur)
        if _is_postgres():
            cur.execute("""
                SELECT AVG(tok) FROM (
                    SELECT run_id, SUM(input_tokens + output_tokens) AS tok
                    FROM token_usage WHERE run_id IS NOT NULL
                    GROUP BY run_id
                ) t
            """)
        else:
            cur.execute("""
                SELECT AVG(tok) FROM (
                    SELECT run_id, SUM(input_tokens + output_tokens) AS tok
                    FROM token_usage WHERE run_id IS NOT NULL
                    GROUP BY run_id
                )
            """)
        avg_tokens = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM pipeline_runs")
        total = cur.fetchone()[0]
        return {"by_status": by_status, "top_sources": top_sources,
                "avg_tokens": int(avg_tokens), "total": total}
    finally:
        conn.close()


def search_runs(query, limit=10):
    """Search pipeline_runs by throughline keyword."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "SELECT id, throughline, status, trust_gate, created_at "
                "FROM pipeline_runs WHERE throughline ILIKE %s "
                "ORDER BY id DESC LIMIT %s",
                (f"%{query}%", limit),
            )
        else:
            cur.execute(
                "SELECT id, throughline, status, trust_gate, created_at "
                "FROM pipeline_runs WHERE throughline LIKE ? "
                "ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit),
            )
        return _fetchall(cur)
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


def clear_agents_for_run(run_id):
    """Remove active_agent entries for a specific run (manual ghost cleanup)."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"DELETE FROM active_agents WHERE run_id = {ph}", (run_id,))
        conn.commit()
    finally:
        conn.close()


def clear_stale_topics():
    """Reset pending_topics rows stuck in 'running' for more than 1 hour back to 'queued'.

    This happens when the agent crashes between pop_next_topic() and finish_topic(),
    leaving the row permanently 'running' and invisible to the next pop_next_topic() call.
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "UPDATE pending_topics SET status='queued' "
                "WHERE status='running' AND submitted_at < NOW() - INTERVAL '1 hour'"
            )
        else:
            cur.execute(
                "UPDATE pending_topics SET status='queued' "
                "WHERE status='running' AND submitted_at < datetime('now', '-1 hour')"
            )
        n = cur.rowcount
        conn.commit()
        return n
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


def queue_carousel_run(run_id, article_url=""):
    """Queue carousel generation for a just-approved article. The orchestrator
    picks up 'queued' rows on its next tick; bot.py never does the heavy
    composer/render work itself. Returns the new carousel_runs id."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO carousel_runs (run_id, article_url, status) VALUES ({ph}, {ph}, 'queued')",
            (run_id, article_url),
        )
        if _is_postgres():
            cur.execute("SELECT lastval()")
            carousel_id = cur.fetchone()[0]
        else:
            carousel_id = cur.lastrowid
        conn.commit()
        return carousel_id
    finally:
        conn.close()


def get_queued_carousel_runs():
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM carousel_runs WHERE status = 'queued' ORDER BY id")
        return _fetchall(cur)
    finally:
        conn.close()


def update_carousel_run(carousel_id, **kwargs):
    ph = "%s" if _is_postgres() else "?"
    sets = ", ".join(f"{k} = {ph}" for k in kwargs)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE carousel_runs SET {sets} WHERE id = {ph}", (*kwargs.values(), carousel_id))
        conn.commit()
    finally:
        conn.close()


def get_carousel_run(carousel_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute("SELECT * FROM carousel_runs WHERE id = " + ph, (carousel_id,))
        return _fetchone(cur)
    finally:
        conn.close()


def get_slide_render_data(carousel_id, position):
    """Everything needed to re-render one carousel slide from the DB, so rendered
    PNGs never have to survive a redeploy. Returns {headline, position, total,
    dark, stamp} or None. Style defaults gracefully for carousels composed before
    dark/stamp were persisted."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"SELECT headline FROM carousel_slides WHERE carousel_id={ph} AND position={ph}",
                    (carousel_id, position))
        row = _fetchone(cur)
        if not row:
            return None
        headline = row["headline"]
        cur.execute(f"SELECT COUNT(*) AS n FROM carousel_slides WHERE carousel_id={ph}", (carousel_id,))
        total = (_fetchone(cur) or {}).get("n", 1)
        cur.execute(f"SELECT dark, stamp FROM carousel_runs WHERE id={ph}", (carousel_id,))
        cr = _fetchone(cur) or {}
        return {"headline": headline, "position": position, "total": total,
                "dark": bool(cr.get("dark")), "stamp": (cr.get("stamp") or "VERIFIED")}
    finally:
        conn.close()


def clear_carousel_slides(carousel_id):
    """Remove a carousel's slide rows before a (re-)compose so re-rendering can't
    leave duplicate positions in carousel_slides."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"DELETE FROM carousel_slides WHERE carousel_id = {ph}", (carousel_id,))
        conn.commit()
    finally:
        conn.close()


def add_carousel_slide(carousel_id, position, headline, image_path="", image_url=""):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"""INSERT INTO carousel_slides (carousel_id, position, headline, image_path, image_url)
               VALUES ({ph},{ph},{ph},{ph},{ph})""",
            (carousel_id, position, headline, image_path, image_url),
        )
        conn.commit()
    finally:
        conn.close()


def get_carousel_slides(carousel_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"SELECT * FROM carousel_slides WHERE carousel_id = {ph} ORDER BY position", (carousel_id,)
        )
        return _fetchall(cur)
    finally:
        conn.close()


_CAROUSEL_TERMINAL_STATUSES = ("posted", "killed", "approved_manual", "failed")


def get_unclean_finished_carousels():
    """Carousels in a terminal state whose rendered slide files haven't been
    deleted from disk yet. Drives the orchestrator's automatic cleanup pass —
    see cleanup_finished_carousels() in engine/agents/orchestrator.py."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        placeholders = ", ".join(ph for _ in _CAROUSEL_TERMINAL_STATUSES)
        cur.execute(
            f"SELECT * FROM carousel_runs WHERE status IN ({placeholders}) "
            f"AND files_cleaned_at IS NULL ORDER BY id",
            _CAROUSEL_TERMINAL_STATUSES,
        )
        return _fetchall(cur)
    finally:
        conn.close()


def mark_carousel_cleaned(carousel_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        now = "NOW()" if _is_postgres() else "datetime('now')"
        cur.execute(f"UPDATE carousel_runs SET files_cleaned_at = {now} WHERE id = {ph}", (carousel_id,))
        conn.commit()
    finally:
        conn.close()


def get_pending_carousels():
    """Carousels rendered and waiting for the owner's post/kill tap."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM carousel_runs WHERE status = 'pending_review' ORDER BY id")
        return _fetchall(cur)
    finally:
        conn.close()


def get_pending_proposals():
    """Source-scout proposals the owner hasn't approved/skipped yet."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM source_proposals WHERE status = 'pending' ORDER BY id")
        return _fetchall(cur)
    finally:
        conn.close()


def set_run_slug(run_id, slug):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"UPDATE pipeline_runs SET slug = {ph} WHERE id = {ph}", (slug, run_id))
        conn.commit()
    finally:
        conn.close()


def get_run_by_slug(slug):
    """The pipeline run a public article URL points at, or None.

    Slugs are '<run_id>-<kebab-headline>'; only the run-id prefix is matched,
    so a link keeps working even if the article is later retitled and gets a
    fresh slug. The caller (the /a/ route) checks status — this just resolves."""
    m = str(slug).split("-", 1)[0]
    if not m.isdigit():
        return None
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"SELECT * FROM pipeline_runs WHERE id = {ph}", (int(m),))
        return _fetchone(cur)
    finally:
        conn.close()


def add_bio_link(title, url, pinned=False):
    """Add a link to the public bio page. Deduped by URL: re-adding an existing
    URL updates its title instead of creating a second row (republishing a run
    must not double-list it). Returns the link id."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"SELECT id FROM bio_links WHERE url = {ph}", (url,))
        row = _fetchone(cur)
        if row:
            cur.execute(f"UPDATE bio_links SET title = {ph} WHERE id = {ph}", (title, row["id"]))
            conn.commit()
            return row["id"]
        cur.execute(
            f"INSERT INTO bio_links (title, url, pinned) VALUES ({ph}, {ph}, {ph})",
            (title, url, pinned if _is_postgres() else int(pinned)),
        )
        conn.commit()
        if _is_postgres():
            cur.execute("SELECT id FROM bio_links WHERE url = %s", (url,))
            return _fetchone(cur)["id"]
        return cur.lastrowid
    finally:
        conn.close()


def list_bio_links():
    """All bio links in page order: pinned first, then newest first."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM bio_links ORDER BY pinned DESC, id DESC")
        return _fetchall(cur)
    finally:
        conn.close()


def delete_bio_link(link_id):
    """Remove a bio link. Returns True if a row was deleted."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"DELETE FROM bio_links WHERE id = {ph}", (link_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_bio_link_pinned(link_id, pinned):
    """Pin/unpin a bio link. Returns True if the row exists."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        val = bool(pinned) if _is_postgres() else int(bool(pinned))
        cur.execute(f"UPDATE bio_links SET pinned = {ph} WHERE id = {ph}", (val, link_id))
        conn.commit()
        return cur.rowcount > 0
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


# ── Digs — persistent, multi-day investigation threads ──────────────────────────
# A dig is a thread we work over days: scope it, pull primary records, try to
# disprove, log findings, and promote to the pipeline only when it holds. The
# dig_updates table is an append-only investigation log. See docs/command-center.md.

_DIG_STATUSES = ("scoping", "records-pending", "verifying", "ready-to-write", "parked", "killed")


def create_dig(title, question="", kerala_anchor="", hypothesis="",
               watchlist_id="", priority=2, owner_note="", status="scoping"):
    """Open a new dig thread. Returns the new dig id."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"""INSERT INTO digs
               (title, question, kerala_anchor, hypothesis, watchlist_id,
                priority, owner_note, status)
               VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (title, question, kerala_anchor, hypothesis, watchlist_id,
             priority, owner_note, status),
        )
        if _is_postgres():
            cur.execute("SELECT lastval()")
            dig_id = cur.fetchone()[0]
        else:
            dig_id = cur.lastrowid
        conn.commit()
        return dig_id
    finally:
        conn.close()


def add_dig_update(dig_id, body, kind="note"):
    """Append an entry to a dig's investigation log. Also bumps digs.updated_at.
    kind ∈ brief|records|finding|rti|kill-test|note|promoted."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO dig_updates (dig_id, kind, body) VALUES ({ph},{ph},{ph})",
            (dig_id, kind, body),
        )
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(f"UPDATE digs SET updated_at = {ph} WHERE id = {ph}", (now, dig_id))
        conn.commit()
    finally:
        conn.close()


def update_dig(dig_id, **kwargs):
    """Patch dig fields (status, priority, next_action_at, hypothesis, …)."""
    kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
    ph = "%s" if _is_postgres() else "?"
    sets = ", ".join(f"{k} = {ph}" for k in kwargs)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE digs SET {sets} WHERE id = {ph}", (*kwargs.values(), dig_id))
        conn.commit()
    finally:
        conn.close()


def get_dig(dig_id):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"SELECT * FROM digs WHERE id = {ph}", (dig_id,))
        return _fetchone(cur)
    finally:
        conn.close()


def list_digs(include_closed=True, limit=100):
    """All digs, newest activity first. Set include_closed=False to hide
    parked/killed threads."""
    conn = _conn()
    try:
        cur = conn.cursor()
        where = "" if include_closed else "WHERE status NOT IN ('parked','killed') "
        cur.execute(
            f"SELECT * FROM digs {where}ORDER BY updated_at DESC LIMIT "
            + ("%s" if _is_postgres() else "?"),
            (limit,),
        )
        return _fetchall(cur)
    finally:
        conn.close()


def get_dig_updates(dig_id, limit=200):
    """A dig's investigation log, oldest first (reads as a timeline)."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"SELECT * FROM dig_updates WHERE dig_id = {ph} ORDER BY id ASC LIMIT {ph}",
            (dig_id, limit),
        )
        return _fetchall(cur)
    finally:
        conn.close()


def get_due_digs(limit=5):
    """Active digs whose next_action_at has passed — the daily auto-advance set.
    Only live statuses; parked/killed/ready-to-write are excluded."""
    conn = _conn()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"""SELECT * FROM digs
                WHERE status IN ('scoping','records-pending','verifying')
                  AND next_action_at IS NOT NULL AND next_action_at <= {ph}
                ORDER BY priority ASC, next_action_at ASC LIMIT {ph}""",
            (now, limit),
        )
        return _fetchall(cur)
    finally:
        conn.close()


def queue_ingest(url, note=""):
    """Queue a pasted link (article or video) for the pipeline to pick up.

    Writes a pending_topics row (source='ingest') with a [LINK] marker so
    _run_topic_intake fetches the URL's content before triaging. Returns the
    topic id. The result still lands at the human gate — ingestion never
    auto-publishes."""
    label = f"[LINK] {url}"
    if note:
        label += f"\nAngle/note: {note}"
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO pending_topics (topic, source) VALUES ({ph}, {ph})",
            (label, "ingest"),
        )
        if _is_postgres():
            cur.execute("SELECT lastval()")
            tid = cur.fetchone()[0]
        else:
            tid = cur.lastrowid
        conn.commit()
        return tid
    finally:
        conn.close()
