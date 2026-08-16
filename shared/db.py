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

CREATE TABLE IF NOT EXISTS engine_events (
    id          SERIAL PRIMARY KEY,
    kind        TEXT,
    level       TEXT DEFAULT 'info',
    title       TEXT NOT NULL,
    body        TEXT,
    report      TEXT,
    run_id      INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
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
    -- Which desk produced this run: 'news' | 'ek' | 'gk'. Declared here as well as
    -- in the ALTER migration so a fresh database can carry the index below.
    desk                TEXT NOT NULL DEFAULT 'news',
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

CREATE TABLE IF NOT EXISTS reels (
    id             SERIAL PRIMARY KEY,
    run_id         INTEGER REFERENCES pipeline_runs(id),
    kind           TEXT DEFAULT 'narrated',
    caption        TEXT,
    mp4            BYTEA,
    status         TEXT DEFAULT 'ready',
    ig_media_id    TEXT,
    ig_permalink   TEXT,
    notes          TEXT,
    created_at     TIMESTAMP DEFAULT NOW(),
    posted_at      TIMESTAMP
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

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_desk ON pipeline_runs(desk);

CREATE TABLE IF NOT EXISTS belief_pieces (
    id            SERIAL PRIMARY KEY,
    run_id        INTEGER REFERENCES pipeline_runs(id),
    belief        TEXT NOT NULL,
    shape         TEXT,
    currency      TEXT,
    case_anchor   TEXT,
    counter_case  TEXT,
    so_what       TEXT,
    spine         TEXT,
    label         TEXT,
    created_at    TIMESTAMP DEFAULT NOW()
);

-- The belief desks' intake. Owner-supplied beliefs land here as 'queued' and the
-- scout's proposals as 'proposed', so the owner's own submission never waits
-- behind an approval step it doesn't need. See docs/everyone-knows-desk.md §6.
CREATE TABLE IF NOT EXISTS belief_queue (
    id          SERIAL PRIMARY KEY,
    belief      TEXT NOT NULL,
    source      TEXT,                      -- owner | scout
    theme       TEXT,
    lane        TEXT,                      -- the scout's guess: ek | gk
    note        TEXT,                      -- currency / record / so-what, as found
    status      TEXT NOT NULL DEFAULT 'queued',  -- proposed|queued|running|done|dropped
    run_id      INTEGER,
    result      TEXT,
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

-- Readership. The engine has measured its own production in detail since day
-- one and its readership not at all. See docs/reach-analytics.md.
--
-- No IP, no raw user-agent, no cookie, no third party. `visitor_hash` is
-- sha256(ip + ua + a salt regenerated each UTC day), so "unique readers today"
-- is answerable and cross-day tracking is impossible by construction rather
-- than by policy. `referrer_host` is the host only — a full referrer can carry
-- a search query, which is content about the reader.
CREATE TABLE IF NOT EXISTS page_reads (
    id            SERIAL PRIMARY KEY,
    slug          TEXT NOT NULL,
    run_id        INTEGER,
    is_bot        BOOLEAN DEFAULT FALSE,   -- crawlers/link-unfurlers, kept not dropped
    visitor_hash  TEXT,
    referrer_host TEXT,
    read_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_page_reads_at ON page_reads (read_at);
CREATE INDEX IF NOT EXISTS idx_page_reads_slug ON page_reads (slug);

-- Instagram. One row per post; `run_id` ties it back to the story it came from.
CREATE TABLE IF NOT EXISTS ig_media (
    media_id      TEXT PRIMARY KEY,
    media_type    TEXT,               -- CAROUSEL_ALBUM | VIDEO
    product_type  TEXT,               -- FEED | REELS
    permalink     TEXT,
    caption       TEXT,
    run_id        INTEGER,
    posted_at     TIMESTAMP,
    seen_at       TIMESTAMP DEFAULT NOW()
);

-- Append-only snapshots: a post's numbers keep moving for days and the shape of
-- that curve is the interesting part. Both media types return this exact metric
-- set, which is why one table covers reels and carousels.
CREATE TABLE IF NOT EXISTS ig_media_metrics (
    id          SERIAL PRIMARY KEY,
    media_id    TEXT NOT NULL,
    reach       INTEGER,
    views       INTEGER,
    likes       INTEGER,
    comments    INTEGER,
    saved       INTEGER,
    shares      INTEGER,
    captured_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ig_metrics_media ON ig_media_metrics (media_id, captured_at);

-- One row per UTC day, upserted. Exists because the API will not give us
-- yesterday: account reach with period=day returns two days, and
-- followers_count is a bare current number with no history at all. If we do not
-- snapshot, the history does not exist.
CREATE TABLE IF NOT EXISTS audience_daily (
    day                TEXT PRIMARY KEY,   -- YYYY-MM-DD, UTC
    followers          INTEGER,   -- Instagram
    reach_day          INTEGER,
    accounts_engaged   INTEGER,
    total_interactions INTEGER,
    tg_subscribers     INTEGER,   -- Telegram channel; per-post views are MTProto-only
    updated_at         TIMESTAMP DEFAULT NOW()
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

CREATE TABLE IF NOT EXISTS engine_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT,
    level       TEXT DEFAULT 'info',
    title       TEXT NOT NULL,
    body        TEXT,
    report      TEXT,
    run_id      INTEGER,
    created_at  TEXT DEFAULT (datetime('now'))
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
    desk                TEXT NOT NULL DEFAULT 'news',
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

CREATE TABLE IF NOT EXISTS reels (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER REFERENCES pipeline_runs(id),
    kind           TEXT DEFAULT 'narrated',
    caption        TEXT,
    mp4            BLOB,
    status         TEXT DEFAULT 'ready',
    ig_media_id    TEXT,
    ig_permalink   TEXT,
    notes          TEXT,
    created_at     TEXT DEFAULT (datetime('now')),
    posted_at      TEXT
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

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_desk ON pipeline_runs(desk);

CREATE TABLE IF NOT EXISTS belief_pieces (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER REFERENCES pipeline_runs(id),
    belief        TEXT NOT NULL,
    shape         TEXT,
    currency      TEXT,
    case_anchor   TEXT,
    counter_case  TEXT,
    so_what       TEXT,
    spine         TEXT,
    label         TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS belief_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    belief      TEXT NOT NULL,
    source      TEXT,
    theme       TEXT,
    lane        TEXT,
    note        TEXT,
    status      TEXT NOT NULL DEFAULT 'queued',
    run_id      INTEGER,
    result      TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS page_reads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL,
    run_id        INTEGER,
    is_bot        INTEGER DEFAULT 0,
    visitor_hash  TEXT,
    referrer_host TEXT,
    read_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_page_reads_at ON page_reads (read_at);
CREATE INDEX IF NOT EXISTS idx_page_reads_slug ON page_reads (slug);

CREATE TABLE IF NOT EXISTS ig_media (
    media_id      TEXT PRIMARY KEY,
    media_type    TEXT,
    product_type  TEXT,
    permalink     TEXT,
    caption       TEXT,
    run_id        INTEGER,
    posted_at     TEXT,
    seen_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ig_media_metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id    TEXT NOT NULL,
    reach       INTEGER,
    views       INTEGER,
    likes       INTEGER,
    comments    INTEGER,
    saved       INTEGER,
    shares      INTEGER,
    captured_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ig_metrics_media ON ig_media_metrics (media_id, captured_at);

CREATE TABLE IF NOT EXISTS audience_daily (
    day                TEXT PRIMARY KEY,
    followers          INTEGER,
    reach_day          INTEGER,
    accounts_engaged   INTEGER,
    total_interactions INTEGER,
    tg_subscribers     INTEGER,
    updated_at         TEXT DEFAULT (datetime('now'))
);
"""


# Dial retries for the Postgres connection (see _conn). Small and bounded: this
# runs inside the 2-minute tick, so it must fail fast enough to not stack ticks.
_CONNECT_TRIES = 3
_CONNECT_BACKOFF = 1.5


def _conn():
    if DATABASE_URL:
        import psycopg2
        import psycopg2.extras
        # Keepalives are NOT optional here. Indian ISPs silently drop idle NAT
        # entries (HANDOFF §5), and Railway's public PG proxy is reached over the
        # open internet from Anil's laptop. Without these, a dropped connection
        # leaves psycopg2 blocked in recv() with no timeout — forever. That wedged
        # an attended cycle mid-ingest on 2026-07-22 with zero log output.
        # With them a dead socket surfaces as OperationalError in ~60s.
        # Timing out is better than hanging, but not good enough on its own: with a
        # flaky link a bare timeout just moves the failure one level up, and a
        # single dropped dial mid-ingest kills a whole source for the cycle
        # ("Ingest failed for The Hindu — Kerala: timeout expired", 2026-07-22).
        # Retry the dial a few times before giving up — the link recovers in
        # seconds, and every caller here is safe to retry (we've not sent a
        # statement yet, so there is nothing to double-apply).
        import time as _time
        last = None
        for attempt in range(_CONNECT_TRIES):
            try:
                return psycopg2.connect(
                    DATABASE_URL,
                    connect_timeout=10,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=3,
                )
            except psycopg2.OperationalError as e:
                last = e
                if attempt < _CONNECT_TRIES - 1:
                    _time.sleep(_CONNECT_BACKOFF * (2 ** attempt))
        raise last
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


def _strip_sql_comments(sql):
    """Drop `-- …` line comments so the naive split on ';' can't cut a statement.

    Only line comments, and only outside single quotes — the schema has no
    string literals containing `--`, but stripping inside one would corrupt a
    default value rather than a comment, and that is a worse failure than the
    one being fixed.
    """
    out = []
    for line in sql.splitlines():
        in_str, cut = False, None
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "'":
                in_str = not in_str
            elif not in_str and ch == "-" and line[i + 1:i + 2] == "-":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def init_db():
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            # Comments are stripped BEFORE the split, because the split is on ";"
            # and a semicolon inside a `-- comment` cuts the statement it belongs
            # to in half. Both halves then fail silently in the rollback below,
            # and the table simply never exists — which is exactly how
            # `ig_media` and `audience_daily` failed to be created on
            # 2026-08-08 while their neighbours were fine. A schema loader that
            # loses a table because of a punctuation mark in a comment should
            # not stay that way.
            for statement in _strip_sql_comments(_SCHEMA).strip().split(";"):
                s = statement.strip()
                if s:
                    try:
                        cur.execute(s)
                        conn.commit()
                    except Exception:
                        conn.rollback()
            # Migrations for existing tables
            for col, defn in [("legal_flag", "BOOLEAN DEFAULT FALSE"), ("legal_reason", "TEXT"), ("slug", "TEXT"),
                              # Which desk produced this run. Everything that predates
                              # the second desk is news, hence the default — and every
                              # news-desk read filters on it explicitly rather than
                              # relying on that default. See docs/everyone-knows-desk.md §7.
                              ("desk", "TEXT NOT NULL DEFAULT 'news'")]:
                try:
                    cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
            # `view_label` is the belief desks' shape-B marker. It lives on the
            # carousel_run, not only in the rendered file, because the fileserver
            # RE-RENDERS a slide from the DB on demand (and on ?fresh=1 after an
            # owner edits a headline) — a label that existed only in the first
            # render would quietly vanish from the image Meta actually fetches.
            for col, defn in [("files_cleaned_at", "TIMESTAMP"),
                              ("dark", "BOOLEAN DEFAULT FALSE"), ("stamp", "TEXT"),
                              ("view_label", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE carousel_runs ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
            # A topic's fate. `status` only ever said 'done' — published and
            # binned-in-five-seconds looked identical, and the reason lived only
            # in a Telegram card whose "Full report" link points at telegra.ph,
            # which is blocked on the owner's ISP. So the reason is stored HERE
            # and Telegraph is a mirror, not the system of record.
            for col, defn in [("outcome", "TEXT"), ("reason", "TEXT"),
                              ("report", "TEXT"), ("run_id", "INTEGER"),
                              ("decided_at", "TIMESTAMP")]:
                try:
                    cur.execute(f"ALTER TABLE pending_topics ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
            # Cache tokens were being thrown away, so the cost table under-reported
            # real spend (writes bill at 1.25x and counted as zero) and there was
            # no way to tell whether the caching we already implement works.
            for col, defn in [("cache_write_tokens", "INTEGER DEFAULT 0"),
                              ("cache_read_tokens", "INTEGER DEFAULT 0")]:
                try:
                    cur.execute(f"ALTER TABLE token_usage ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
            for col, defn in [("notes", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE reels ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
            # The spine is the reel's narration and the label is the shape-B view
            # marker. Both used to live inside draft_text, which put the spine on
            # the reader's page — see engine/desks/ek/draft.py.
            for col, defn in [("spine", "TEXT"), ("label", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE belief_pieces ADD COLUMN {col} {defn}")
                    conn.commit()
                except Exception:
                    conn.rollback()  # column already exists
            # Indexes over migrated columns must come AFTER the ALTERs. The copy in
            # _SCHEMA only fires for a fresh database, where CREATE TABLE already
            # carries the column; on an existing one it runs before `desk` exists,
            # fails, and is swallowed by the per-statement rollback — which is how
            # this index silently failed to appear the first time.
            for stmt in ["CREATE INDEX IF NOT EXISTS idx_pipeline_runs_desk ON pipeline_runs(desk)"]:
                try:
                    cur.execute(stmt)
                    conn.commit()
                except Exception:
                    conn.rollback()
        else:
            cur.executescript(_SCHEMA_SQLITE)
            for col, defn in [("legal_flag", "INTEGER DEFAULT 0"), ("legal_reason", "TEXT"), ("slug", "TEXT"),
                              ("desk", "TEXT NOT NULL DEFAULT 'news'")]:
                try:
                    cur.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            for col, defn in [("files_cleaned_at", "TEXT"),
                              ("dark", "INTEGER DEFAULT 0"), ("stamp", "TEXT"),
                              ("view_label", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE carousel_runs ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            for col, defn in [("notes", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE reels ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            for col, defn in [("spine", "TEXT"), ("label", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE belief_pieces ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            # See the Postgres branch: a topic's fate, stored rather than left
            # to a Telegram card on a domain the owner's ISP blocks.
            for col, defn in [("outcome", "TEXT"), ("reason", "TEXT"),
                              ("report", "TEXT"), ("run_id", "INTEGER"),
                              ("decided_at", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE pending_topics ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            for col, defn in [("cache_write_tokens", "INTEGER DEFAULT 0"),
                              ("cache_read_tokens", "INTEGER DEFAULT 0")]:
                try:
                    cur.execute(f"ALTER TABLE token_usage ADD COLUMN {col} {defn}")
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
             draft_text=None, review_text=None, verification_report=None, status="investigating",
             desk="news"):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"""INSERT INTO pipeline_runs
               (video_id, source, throughline, trust_gate,
                draft_text, review_text, verification_report, status, desk)
               VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})""",
            (video_id, source, throughline, trust_gate,
             draft_text, review_text, verification_report, status, desk),
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


def get_belief(run_id):
    """The belief_pieces row for a run, or None when the run is not a belief
    piece. Kept here rather than in the desk package because the reel builder
    and the command centre both need it and neither should import the desk."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute("SELECT * FROM belief_pieces WHERE run_id = " + ph +
                    " ORDER BY id DESC LIMIT 1", (run_id,))
        return _fetchone(cur)
    except Exception:
        # A database that predates the belief desks has no such table. That is a
        # news-only install, not an error — the caller wants "not a belief piece".
        return None
    finally:
        conn.close()


def save_belief_parts(run_id, **fields):
    """Update belief_pieces columns for a run. Used by the writer step (spine,
    label) and the backfill; column names are internal, never request text."""
    fields = {k: v for k, v in fields.items() if k in
              ("belief", "shape", "currency", "case_anchor", "counter_case",
               "so_what", "spine", "label")}
    if not fields:
        return
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        sets = ", ".join(f"{k} = {ph}" for k in fields)
        cur.execute(f"UPDATE belief_pieces SET {sets} WHERE run_id = {ph}",
                    tuple(fields.values()) + (run_id,))
        conn.commit()
    finally:
        conn.close()


def add_belief_candidate(belief, *, source="owner", theme="", lane="", note="",
                         status=None):
    """Queue a belief for the desks. Owner submissions are 'queued' (they are the
    approval); scout proposals are 'proposed' and wait for one.

    Returns the new row id, or None when this belief has already been taken —
    deduped against both the queue and the runs that exist, because the cheapest
    place to notice a repeat is before the gate call."""
    if not (belief or "").strip():
        return None
    belief = belief.strip()
    if status is None:
        status = "queued" if source == "owner" else "proposed"
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        key = belief.lower()[:200]
        cur.execute(f"SELECT id FROM belief_queue WHERE LOWER(belief) LIKE {ph} "
                    f"AND status NOT IN ('dropped')", (key + "%",))
        if _fetchone(cur):
            return None
        cur.execute(f"SELECT id FROM pipeline_runs WHERE desk IN ('ek','gk') "
                    f"AND LOWER(throughline) LIKE {ph}", (key + "%",))
        if _fetchone(cur):
            return None
        cur.execute(
            f"INSERT INTO belief_queue (belief, source, theme, lane, note, status) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph})"
            + (" RETURNING id" if _is_postgres() else ""),
            (belief, source, theme, lane, note, status))
        new_id = _fetchone(cur)["id"] if _is_postgres() else cur.lastrowid
        conn.commit()
        return new_id
    finally:
        conn.close()


def list_belief_queue(status=None, limit=50):
    """Queue rows, newest first. `status` is matched exactly when given."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        if status:
            cur.execute(f"SELECT * FROM belief_queue WHERE status = {ph} "
                        f"ORDER BY id DESC LIMIT {ph}", (status, limit))
        else:
            cur.execute(f"SELECT * FROM belief_queue ORDER BY id DESC LIMIT {ph}",
                        (limit,))
        return _fetchall(cur)
    finally:
        conn.close()


def pop_next_belief():
    """Claim the oldest approved belief, marking it 'running'. Same
    SKIP LOCKED shape as pop_next_topic so two ticks can't take the same row."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        if _is_postgres():
            cur.execute("SELECT * FROM belief_queue WHERE status = 'queued' "
                        "ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED")
        else:
            cur.execute("SELECT * FROM belief_queue WHERE status = 'queued' "
                        "ORDER BY id LIMIT 1")
        row = _fetchone(cur)
        if not row:
            return None
        cur.execute(f"UPDATE belief_queue SET status = 'running' WHERE id = {ph}",
                    (row["id"],))
        conn.commit()
        return row
    finally:
        conn.close()


def set_belief_status(qid, status, *, run_id=None, result=None):
    """Move a queue row on. `result` is a short human-readable outcome — the
    gate's verdict or the reason it stopped — so the command centre can say what
    happened without re-reading the run."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        now = "NOW()" if _is_postgres() else "datetime('now')"
        cur.execute(f"UPDATE belief_queue SET status = {ph}, run_id = COALESCE({ph}, run_id), "
                    f"result = COALESCE({ph}, result), updated_at = {now} WHERE id = {ph}",
                    (status, run_id, result, qid))
        conn.commit()
    finally:
        conn.close()


def taken_beliefs(limit=200):
    """Every belief this desk has already worked, for the scout to dedupe
    against — the queue and the runs together."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT belief FROM belief_queue WHERE status != 'dropped' "
                    "ORDER BY id DESC LIMIT %d" % int(limit))
        out = [r["belief"] for r in _fetchall(cur)]
        cur.execute("SELECT throughline FROM pipeline_runs WHERE desk IN ('ek','gk') "
                    "ORDER BY id DESC LIMIT %d" % int(limit))
        out += [r["throughline"] for r in _fetchall(cur) if r.get("throughline")]
        return out
    finally:
        conn.close()


def get_held_runs(older_than_days=3, limit=None, desk="news"):
    """Held stories untouched for older_than_days, oldest first.

    Covers BOTH 'held' (owner/dashboard) and 'hold' (the verifier's gate
    verdict, gate.lower()) — the old status='held' filter matched zero rows in
    prod, so the daily auto-recheck was a silent no-op (audit 2026-07-26).
    Filters on updated_at, not created_at: a story rechecked and held again
    yesterday was 'created weeks ago' and would have re-rechecked every single
    day forever. `limit` lets the auto-recheck cap its daily spend instead of
    queueing the whole backlog in one wave."""
    conn = _conn()
    try:
        cur = conn.cursor()
        lim = f" LIMIT {int(limit)}" if limit else ""
        if _is_postgres():
            cur.execute(
                "SELECT * FROM pipeline_runs WHERE status IN ('held', 'hold') "
                "AND desk = %s "
                "AND updated_at < NOW() - INTERVAL '%s days' "
                "ORDER BY updated_at" + lim,
                (desk, older_than_days),
            )
        else:
            cur.execute(
                "SELECT * FROM pipeline_runs WHERE status IN ('held', 'hold') "
                "AND desk = ? "
                "AND updated_at < datetime('now', ?) "
                "ORDER BY updated_at" + lim,
                (desk, f"-{older_than_days} days"),
            )
        return _fetchall(cur)
    finally:
        conn.close()


def get_recent_leads_by_source(source, days=14, limit=25):
    """Recent throughlines from one lead source (e.g. 'beat-monitor'), newest
    first. Used to hand a monitor its own recent output so it can recognise a
    re-worded repeat of a finding it already surfaced, not just an exact-string
    match (audit 2026-08-15: beat-monitor's CAG beat re-surfaced the same
    findings under fresh phrasing daily, defeating the sha1(throughline) dedup)."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        if _is_postgres():
            cur.execute(
                f"""SELECT throughline, created_at::date as date FROM pipeline_runs
                    WHERE source = {ph} AND created_at > NOW() - INTERVAL '{int(days)} days'
                    ORDER BY created_at DESC LIMIT {ph}""",
                (source, limit),
            )
        else:
            cur.execute(
                f"""SELECT throughline, created_at FROM pipeline_runs
                    WHERE source = {ph} AND created_at > datetime('now', '-{int(days)} days')
                    ORDER BY created_at DESC LIMIT {ph}""",
                (source, limit),
            )
        return _fetchall(cur)
    finally:
        conn.close()


def get_recheckable_runs(limit=30, desk="news"):
    """Held stories the owner can ask to re-develop — both human-held ('held') and
    verifier-held ('hold'), newest first."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, throughline, trust_gate, status, created_at "
            "FROM pipeline_runs WHERE status IN ('held', 'hold') AND desk = "
            + ("%s" if _is_postgres() else "?") + " "
            "ORDER BY id DESC LIMIT " + ("%s" if _is_postgres() else "?"),
            (desk, limit),
        )
        return _fetchall(cur)
    finally:
        conn.close()


def get_runs_by_status(status, limit=20, desk="news"):
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"SELECT * FROM pipeline_runs WHERE status = {ph} AND desk = {ph} "
            f"ORDER BY id LIMIT {ph}",
            (status, desk, limit),
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


# The fates a submitted topic can meet. `investigating` is the only one that
# means the topic became a story; every other value is a form of "no", and the
# whole point of this table is that they stop looking alike.
TOPIC_OUTCOMES = {
    "investigating",   # PROCEED + past the gate → a run exists (see run_id)
    "declined",        # topic-intake said DECLINE
    "parked",          # topic-intake said PARK
    "no_brief",        # said PROCEED but returned no STORY_BRIEF
    "gate_dropped",    # the absolute-floor newsworthiness gate dropped it
    "intake_failed",   # intake returned nothing usable (StructuredOutputError)
    "abandoned",       # repeated provider/spine failures; capped and dropped
}


def finish_topic(topic_id, outcome, reason="", report="", run_id=None):
    """Close a topic AND record what happened to it.

    `outcome` is required on purpose. Every terminal path used to call
    finish_topic(topic_id) and put its reasoning in a Telegram card, so
    pending_topics ended up 46 rows all reading 'done' — a published topic and
    one binned in five seconds were indistinguishable, and the reasoning was
    unrecoverable once the card scrolled away (worse: its Telegraph link is on
    a domain the owner's ISP blocks). Giving this parameter a default would let
    that failure back in the moment someone adds a seventh exit.

    `reason` is the short human-readable why; `report` is the model's full
    output, stored so the Command Center can render it without Telegraph.
    """
    if outcome not in TOPIC_OUTCOMES:
        raise ValueError(
            f"unknown topic outcome {outcome!r}; expected one of {sorted(TOPIC_OUTCOMES)}"
        )
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        now = "NOW()" if _is_postgres() else "datetime('now')"
        cur.execute(
            f"UPDATE pending_topics SET status = 'done', outcome = {ph}, reason = {ph}, "
            f"report = {ph}, run_id = {ph}, decided_at = {now} WHERE id = {ph}",
            (outcome, (reason or "")[:2000], report or "", run_id, topic_id),
        )
        conn.commit()
    finally:
        conn.close()


def record_event(kind, title, body="", report="", run_id=None, level="info"):
    """Persist one engine notification so the dashboard has it too.

    The engine used to speak only to Telegram: 19 `_notify_card` call sites —
    dropped leads, halted runs, steward recommendations, gate decisions — had no
    row anywhere, so a card that scrolled away (or a Telegraph link on a domain
    the owner's ISP blocks) took the information with it. Owner's rule, 2026-08-05:
    nothing may be visible only in Telegram.

    Written BEFORE the Telegram post on purpose — if Telegram is down or the token
    is wrong, the record still exists. That was the other half of the bug: an
    outage didn't just delay the notice, it erased it.
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO engine_events (kind, level, title, body, report, run_id) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
            (kind or "note", level or "info", (title or "")[:400],
             (body or "")[:8000], report or "", run_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_engine_events(limit=200, kind=None, level=None):
    """Recent engine notifications, newest first — the dashboard's feed."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        where, args = [], []
        if kind:
            where.append(f"kind = {ph}"); args.append(kind)
        if level:
            where.append(f"level = {ph}"); args.append(level)
        sql = ("SELECT id, kind, level, title, body, report, run_id, created_at "
               "FROM engine_events")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY id DESC LIMIT {ph}"
        args.append(limit)
        cur.execute(sql, tuple(args))
        return _fetchall(cur)
    finally:
        conn.close()


def get_topic_outcomes(limit=100):
    """Recent submitted topics with their fate, for the Command Center. Rows
    from before outcomes were recorded carry outcome NULL — shown as unknown
    rather than guessed at."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            "SELECT id, topic, source, status, outcome, reason, report, run_id, "
            f"submitted_at, decided_at FROM pending_topics ORDER BY id DESC LIMIT {ph}",
            (limit,),
        )
        return _fetchall(cur)
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


# ── Reach: Instagram snapshots + article reads ────────────────────────────────
# See docs/reach-analytics.md. The Instagram API keeps two days of account reach
# and no follower history at all, so these tables ARE the record.

def upsert_ig_media(media_id, *, media_type=None, product_type=None,
                    permalink=None, caption=None, posted_at=None, run_id=None):
    """One row per post. Idempotent — a sweep runs every 6 hours over the same
    posts, and `seen_at` is deliberately not touched on update so it keeps
    meaning 'when we first saw this'."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "INSERT INTO ig_media (media_id, media_type, product_type, permalink, "
                "caption, run_id, posted_at) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (media_id) DO UPDATE SET permalink = EXCLUDED.permalink, "
                "caption = EXCLUDED.caption, "
                # COALESCE so a later sweep that cannot resolve the run does not
                # erase a link an earlier one worked out.
                "run_id = COALESCE(EXCLUDED.run_id, ig_media.run_id)",
                (media_id, media_type, product_type, permalink, caption, run_id, posted_at))
        else:
            cur.execute("SELECT run_id FROM ig_media WHERE media_id = ?", (media_id,))
            row = _fetchone(cur)
            if row:
                # _fetchone returns a dict keyed by column name in BOTH dialects,
                # never a tuple — row[0] is a KeyError, not the first column.
                cur.execute("UPDATE ig_media SET permalink=?, caption=?, run_id=? "
                            "WHERE media_id=?",
                            (permalink, caption, run_id or row["run_id"], media_id))
            else:
                cur.execute("INSERT INTO ig_media (media_id, media_type, product_type, "
                            "permalink, caption, run_id, posted_at) VALUES (?,?,?,?,?,?,?)",
                            (media_id, media_type, product_type, permalink, caption,
                             run_id, posted_at))
        conn.commit()
    finally:
        conn.close()


def add_ig_media_metrics(media_id, **vals):
    """Append one snapshot. Append-only on purpose: a post's numbers keep moving
    for days and the shape of that curve is the interesting part."""
    cols = ("reach", "views", "likes", "comments", "saved", "shares")
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO ig_media_metrics (media_id, {', '.join(cols)}) "
            f"VALUES ({', '.join([ph] * (len(cols) + 1))})",
            (media_id, *[vals.get(c) for c in cols]))
        conn.commit()
    finally:
        conn.close()


def upsert_audience_day(day, **vals):
    """One row per UTC day. Upserted rather than appended — several sweeps a day
    are describing the same day, not different ones."""
    cols = ("followers", "reach_day", "accounts_engaged", "total_interactions",
            "tg_subscribers")
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                f"INSERT INTO audience_daily (day, {', '.join(cols)}, updated_at) "
                f"VALUES (%s,%s,%s,%s,%s,%s,NOW()) ON CONFLICT (day) DO UPDATE SET "
                + ", ".join(f"{c} = COALESCE(EXCLUDED.{c}, audience_daily.{c})"
                            for c in cols)
                + ", updated_at = NOW()",
                (day, *[vals.get(c) for c in cols]))
        else:
            cur.execute("INSERT OR REPLACE INTO audience_daily "
                        f"(day, {', '.join(cols)}) VALUES (?,?,?,?,?,?)",
                        (day, *[vals.get(c) for c in cols]))
        conn.commit()
    finally:
        conn.close()


def ig_run_id_for_media(media_id, permalink=None):
    """Trace a post back to the story it came from, via the ids we stored at
    post time. Returns None when it cannot be resolved — an older post from
    before we recorded the linkage, which is not an error."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        for table in ("reels", "carousel_runs"):
            try:
                cur.execute(f"SELECT run_id FROM {table} WHERE ig_media_id = {ph}",
                            (media_id,))
                row = _fetchone(cur)
                if row and row.get("run_id"):
                    return row["run_id"]
                if permalink:
                    cur.execute(f"SELECT run_id FROM {table} WHERE ig_permalink = {ph}",
                                (permalink,))
                    row = _fetchone(cur)
                    if row and row.get("run_id"):
                        return row["run_id"]
            except Exception:
                # carousel_runs may not carry these columns on an older schema;
                # an unresolved link is not worth failing a sweep over.
                continue
        return None
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


def get_queue_state(desk="news"):
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
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            "SELECT id, throughline, source, status, trust_gate, created_at "
            f"FROM pipeline_runs WHERE desk = {ph} ORDER BY id DESC LIMIT 5",
            (desk,),
        )
        recent_runs = _fetchall(cur)
        return {"topics": topics, "recent_runs": recent_runs}
    finally:
        conn.close()


def get_daily_costs(days=7):
    """Return per-day, per-model token usage for the last N days (for trend chart).

    Includes the cache counters. The 2026-08-05 change added
    `cache_write_tokens`/`cache_read_tokens` to `token_usage` and taught
    `cost_usd` to price them (writes at 1.25x, reads at 0.10x), then converted
    the governor, the steward's view and the cost report — **and missed this
    query.** The command centre's overview banner summed the two plain columns
    and reported $0.2967 for a day the governor priced at $0.5707, a 48%
    undercount of the same day from the same table. Since 2026-08-08 that number
    also decides whether the day is parked, so the disagreement stopped being
    cosmetic. Those figures must not disagree — see shared/costs.py.
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "SELECT recorded_at::date AS day, model, "
                "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok, "
                "SUM(COALESCE(cache_write_tokens,0)) AS cw_tok, "
                "SUM(COALESCE(cache_read_tokens,0)) AS cr_tok "
                "FROM token_usage WHERE recorded_at >= NOW() - INTERVAL %s "
                "GROUP BY recorded_at::date, model ORDER BY day",
                (f"{days} days",),
            )
        else:
            cur.execute(
                "SELECT date(recorded_at) AS day, model, "
                "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok, "
                "SUM(COALESCE(cache_write_tokens,0)) AS cw_tok, "
                "SUM(COALESCE(cache_read_tokens,0)) AS cr_tok "
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


def record_usage(skill, model, input_tokens, output_tokens, run_id=None,
                 cache_write_tokens=0, cache_read_tokens=0):
    """Record one skill call's token usage.

    `input_tokens` is the UNCACHED REMAINDER, not the prompt size — the real
    prompt is input + cache_write + cache_read. Recording only the first (which
    this did until 2026-08-05) silently under-reports spend: cache writes bill at
    1.25x and were being counted as zero. Pass all three.
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            f"INSERT INTO token_usage (run_id, skill, model, input_tokens, "
            f"output_tokens, cache_write_tokens, cache_read_tokens) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (run_id, skill, model, input_tokens, output_tokens,
             cache_write_tokens or 0, cache_read_tokens or 0),
        )
        conn.commit()
    finally:
        conn.close()


def get_pipeline_stats(desk="news"):
    """Lifetime pipeline statistics for /stats command, for ONE desk."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(f"SELECT status, COUNT(*) FROM pipeline_runs WHERE desk = {ph} "
                    "GROUP BY status", (desk,))
        by_status = {r[0]: r[1] for r in cur.fetchall()}
        cur.execute("""
            SELECT source,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) AS published,
                   SUM(CASE WHEN status='killed' THEN 1 ELSE 0 END) AS killed
            FROM pipeline_runs
            WHERE source IS NOT NULL AND desk = """ + ph + """
            GROUP BY source ORDER BY published DESC LIMIT 5
        """, (desk,))
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
        cur.execute(f"SELECT COUNT(*) FROM pipeline_runs WHERE desk = {ph}", (desk,))
        total = cur.fetchone()[0]
        return {"by_status": by_status, "top_sources": top_sources,
                "avg_tokens": int(avg_tokens), "total": total}
    finally:
        conn.close()


def search_runs(query, limit=10, desk="news"):
    """Search pipeline_runs by throughline keyword, within one desk."""
    conn = _conn()
    try:
        cur = conn.cursor()
        if _is_postgres():
            cur.execute(
                "SELECT id, throughline, status, trust_gate, created_at "
                "FROM pipeline_runs WHERE throughline ILIKE %s AND desk = %s "
                "ORDER BY id DESC LIMIT %s",
                (f"%{query}%", desk, limit),
            )
        else:
            cur.execute(
                "SELECT id, throughline, status, trust_gate, created_at "
                "FROM pipeline_runs WHERE throughline LIKE ? AND desk = ? "
                "ORDER BY id DESC LIMIT ?",
                (f"%{query}%", desk, limit),
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
                    SUM(COALESCE(cache_write_tokens,0)) FILTER (WHERE recorded_at::date = CURRENT_DATE) AS today_cw,
                    SUM(COALESCE(cache_read_tokens,0))  FILTER (WHERE recorded_at::date = CURRENT_DATE) AS today_cr,
                    SUM(COALESCE(cache_write_tokens,0)) FILTER (WHERE DATE_TRUNC('month', recorded_at) = DATE_TRUNC('month', NOW())) AS month_cw,
                    SUM(COALESCE(cache_read_tokens,0))  FILTER (WHERE DATE_TRUNC('month', recorded_at) = DATE_TRUNC('month', NOW())) AS month_cr,
                    SUM(COALESCE(cache_write_tokens,0)) AS total_cw,
                    SUM(COALESCE(cache_read_tokens,0))  AS total_cr,
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
                    SUM(CASE WHEN date(recorded_at)=date('now') THEN COALESCE(cache_write_tokens,0) ELSE 0 END) AS today_cw,
                    SUM(CASE WHEN date(recorded_at)=date('now') THEN COALESCE(cache_read_tokens,0) ELSE 0 END)  AS today_cr,
                    SUM(CASE WHEN strftime('%Y-%m',recorded_at)=strftime('%Y-%m','now') THEN COALESCE(cache_write_tokens,0) ELSE 0 END) AS month_cw,
                    SUM(CASE WHEN strftime('%Y-%m',recorded_at)=strftime('%Y-%m','now') THEN COALESCE(cache_read_tokens,0) ELSE 0 END)  AS month_cr,
                    SUM(COALESCE(cache_write_tokens,0)) AS total_cw,
                    SUM(COALESCE(cache_read_tokens,0))  AS total_cr,
                    SUM(input_tokens)  AS total_in,
                    SUM(output_tokens) AS total_out
                FROM token_usage
                GROUP BY model
            """)
        rows = _fetchall(cur)
        # Runs today — deliberately ACROSS ALL DESKS, unlike every other read in
        # this module. This is the spend report, and the budget cap is one shared
        # pot: a day where Everyone Knows burned the cap is a day the news desk
        # has no money left. Splitting this by desk would hide that.
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


def get_pending_runs(desk="news"):
    """Runs awaiting the human gate. Per-desk: each desk has its own queue, and
    mixing them would put an Everyone Knows piece in the news editor's list."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            "SELECT id, throughline, trust_gate, created_at FROM pipeline_runs "
            f"WHERE status = 'pending_human' AND desk = {ph} ORDER BY id DESC",
            (desk,),
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


# The statuses the spine passes THROUGH. Anything sitting in one of these after
# the engine restarted belongs to a process that no longer exists.
TRANSIENT_RUN_STATUSES = ("investigating", "writing", "verifying",
                          "scoping", "pending_review")


def clear_stale_runs(minutes=45):
    """Park pipeline_runs orphaned by an engine restart. Returns the ids parked.

    Railway restarts on every deploy, which kills whatever run was mid-spine.
    The belief desk already handles this (`scout._reclaim_stale_runs`, whose own
    comment notes the restart "is the normal case, not the exotic one") — the
    news desk never got the same treatment, so an interrupted run sat in
    'writing' forever, invisible to the gate and to every retry path.

    Parked as `needs_attention` rather than re-queued on purpose: there is no
    resume, so recovery means paying for the whole spine again. That is the
    owner's call, not an automatic one — and a story silently re-running its
    research on every deploy is exactly how a spend cap gets eaten.
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        marks = ",".join([ph] * len(TRANSIENT_RUN_STATUSES))
        cutoff = (f"NOW() - INTERVAL '{int(minutes)} minutes'" if _is_postgres()
                  else f"datetime('now', '-{int(minutes)} minutes')")
        cur.execute(
            f"SELECT id FROM pipeline_runs WHERE status IN ({marks}) "
            f"AND COALESCE(updated_at, created_at) < {cutoff}",
            TRANSIENT_RUN_STATUSES)
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            id_marks = ",".join([ph] * len(ids))
            cur.execute(
                f"UPDATE pipeline_runs SET status = 'needs_attention', "
                f"trust_gate = 'NEEDS-ATTENTION' WHERE id IN ({id_marks})", tuple(ids))
            conn.commit()
        return ids
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
                WHERE source IS NOT NULL AND desk = 'news'
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
                WHERE source IS NOT NULL AND desk = 'news'
                GROUP BY source
                HAVING COUNT(*) >= 2
                ORDER BY verified DESC
            """)
        return _fetchall(cur)
    finally:
        conn.close()


def get_published_stories(days=90, desk="news"):
    """Return published stories for follow-up tracking.

    Per-desk. This feeds the anti-repetition context, and an Everyone Knows
    piece about a 1904 etymology is not competing for the same slot as today's
    news story — blending them would suppress legitimate work on both sides."""
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
                WHERE r.created_at > NOW() - INTERVAL '%s days' AND r.desk = %s
                ORDER BY r.created_at DESC
                LIMIT 20
            """, (days, desk))
        else:
            cur.execute("""
                SELECT r.id, r.throughline, r.source, r.created_at,
                       SUBSTR(r.draft_text, 1, 800) as draft_summary,
                       r.trust_gate
                FROM pipeline_runs r
                JOIN publications p ON p.run_id = r.id
                WHERE r.created_at > datetime('now', ?) AND r.desk = ?
                ORDER BY r.created_at DESC
                LIMIT 20
            """, (f"-{days} days", desk))
        return _fetchall(cur)
    finally:
        conn.close()


def get_all_runs_summary(limit=60, desk="news"):
    """Return summary of all runs for meta-synthesis. Per-desk: meta-synthesis
    reasons about one desk's editorial pattern, and blending desks would draw
    conclusions from two different products."""
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
                WHERE r.desk = %s
                ORDER BY r.created_at DESC
                LIMIT %s
            """, (desk, limit))
        else:
            cur.execute("""
                SELECT r.id, r.throughline, r.source, r.trust_gate, r.status,
                       date(r.created_at) as date,
                       SUBSTR(r.review_text, 1, 400) as review_summary,
                       EXISTS(SELECT 1 FROM publications p WHERE p.run_id = r.id) as published
                FROM pipeline_runs r
                WHERE r.desk = ?
                ORDER BY r.created_at DESC
                LIMIT ?
            """, (desk, limit))
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


def save_reel(run_id, mp4_bytes, caption, kind="narrated", notes=None):
    """Store a locally-generated reel MP4 in the DB so the Railway fileserver can
    serve it at a public URL for Instagram to fetch (Piper/ffmpeg run on Anil's
    laptop; Railway can't regenerate it — so the bytes live in the DB, same
    survive-redeploys philosophy as slides). Returns the reel id.

    `notes` is the owner's revision direction that shaped THIS cut (the remake
    suggestion box). Stored with the reel it produced, so the next remake can show
    what was asked last time instead of re-rolling blind."""
    ph = "%s" if _is_postgres() else "?"
    if _is_postgres():
        import psycopg2 as _pg
        blob = _pg.Binary(mp4_bytes)
    else:
        import sqlite3 as _sq
        blob = _sq.Binary(mp4_bytes)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO reels (run_id, kind, caption, mp4, notes, status) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},'ready')",
            (run_id, kind, caption, blob, notes or None),
        )
        if _is_postgres():
            cur.execute("SELECT lastval()"); rid = cur.fetchone()[0]
        else:
            rid = cur.lastrowid
        conn.commit()
        return rid
    finally:
        conn.close()


def get_reel(reel_id):
    """Reel metadata WITHOUT the mp4 blob (cheap)."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            "SELECT id, run_id, kind, caption, status, ig_media_id, ig_permalink, "
            "notes, created_at, posted_at FROM reels WHERE id = " + ph, (reel_id,))
        return _fetchone(cur)
    finally:
        conn.close()


def get_reel_for_run(run_id):
    """The most recent reel for a run (metadata only, no mp4 blob) — the dashboard
    uses it to tell whether a carousel's story already has a reel built, and to show
    its status / preview / Post button. None if no reel exists for the run yet."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute(
            "SELECT id, run_id, kind, caption, status, ig_media_id, ig_permalink, "
            "notes, created_at, posted_at FROM reels WHERE run_id = " + ph +
            " ORDER BY id DESC LIMIT 1", (run_id,))
        return _fetchone(cur)
    finally:
        conn.close()


def get_ready_reels():
    """Every reel waiting for its Post tap, one query — NOT a per-run lookup.
    Added 2026-08-16 alongside the autopublish sweep: walking published runs and
    calling get_reel_for_run() once each is an N+1 that took 40s+ over Railway's
    ~0.5-1s/round-trip Postgres link at just 100 runs (docs/reach-analytics.md's
    'a fetch in the command centre would leave holes' lesson, same root cause —
    this project has hit this exact class of bug before, see command_center/db.py)."""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, run_id, kind, caption, status, ig_media_id, ig_permalink, "
            "notes, created_at, posted_at FROM reels WHERE status = 'ready' ORDER BY id")
        return _fetchall(cur)
    finally:
        conn.close()


def get_reel_bytes(reel_id):
    """The raw MP4 bytes for the fileserver to serve. None if absent."""
    conn = _conn()
    try:
        cur = conn.cursor()
        ph = "%s" if _is_postgres() else "?"
        cur.execute("SELECT mp4 FROM reels WHERE id = " + ph, (reel_id,))
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return bytes(row[0])
    finally:
        conn.close()


def update_reel(reel_id, **kwargs):
    ph = "%s" if _is_postgres() else "?"
    sets = ", ".join(f"{k} = {ph}" for k in kwargs)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(f"UPDATE reels SET {sets} WHERE id = {ph}", (*kwargs.values(), reel_id))
        conn.commit()
    finally:
        conn.close()


def get_slide_render_data(carousel_id, position):
    """Everything needed to re-render one carousel slide from the DB, so rendered
    PNGs never have to survive a redeploy. Returns {headline, position, total,
    dark, stamp, view_label} or None. Style defaults gracefully for carousels
    composed before dark/stamp/view_label were persisted.

    `view_label` matters more than the other two: it is the belief desks'
    shape-B marker, and a re-render that dropped it would strip the one thing on
    the slide that says the frame is argued."""
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
        cur.execute(f"SELECT dark, stamp, view_label FROM carousel_runs WHERE id={ph}",
                    (carousel_id,))
        cr = _fetchone(cur) or {}
        return {"headline": headline, "position": position, "total": total,
                "dark": bool(cr.get("dark")), "stamp": (cr.get("stamp") or "VERIFIED"),
                "view_label": cr.get("view_label") or ""}
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
