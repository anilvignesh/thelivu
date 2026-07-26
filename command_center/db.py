"""Command-center DB access.

Two jobs:

1. **Pool the shared helpers.** Every `shared.db` helper dials a fresh
   connection and closes it — fine inside the Railway network, but from this
   laptop each dial over the public proxy costs seconds. We patch
   `shared.db._conn` with a factory that hands out warm pooled connections
   wrapped so `.close()` returns them to the pool. Every helper gets pooling
   for free; sqlite mode (local tests) is untouched.

   The pool is hand-rolled, not psycopg2's ThreadedConnectionPool, for two
   measured reasons (2026-07-26, ~250ms RTT link):
   - psycopg2's pool dials new connections INSIDE its lock, so parallel
     borrows serialize behind multi-second dials (a 0.25s parallel batch took
     6.5s that way).
   - Connections are **autocommit**: psycopg2 otherwise sends BEGIN before the
     first statement and needs a ROLLBACK after reads — three round trips per
     query instead of one. Helpers call conn.commit() themselves, which is a
     harmless no-op under autocommit; every helper is single-conn atomic-ish
     already (each opens and closes per call), so no cross-statement
     transactions are lost.

2. **A tiny query API** (`q` / `execute` / `scalar` / `kv_many` / `parallel`)
   for the command center's own reads, in portable SQL (no ::casts, no FILTER)
   so the scratch-sqlite test mode runs the same code paths as prod Postgres.
"""
import os
import queue
import threading
import time

import shared.db as sdb

_IS_PG = bool(os.environ.get("DATABASE_URL", ""))

_POOL_SIZE = 6
# Liveness-check a borrowed conn only after it's been idle a while: Railway
# drops idle sockets, but a conn used moments ago doesn't need a probe round
# trip added to every query.
_IDLE_CHECK_AFTER = 45  # seconds


class _Pool:
    """Minimal thread-safe pool: dials happen OUTSIDE the lock (parallel
    borrows never queue behind another borrow's dial), conns are autocommit."""

    def __init__(self, url, size):
        self._url = url
        self._size = size
        self._q = queue.Queue()
        self._created = 0
        self._lock = threading.Lock()
        self.last_used = {}  # id(conn) -> ts

    def _dial(self):
        import psycopg2
        conn = psycopg2.connect(
            self._url, connect_timeout=10,
            keepalives=1, keepalives_idle=30,
            keepalives_interval=10, keepalives_count=3,
        )
        conn.autocommit = True
        return conn

    def get(self):
        try:
            return self._q.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            may_create = self._created < self._size
            if may_create:
                self._created += 1
        if may_create:
            try:
                return self._dial()
            except Exception:
                with self._lock:
                    self._created -= 1
                raise
        return self._q.get(timeout=30)

    def put(self, conn, broken=False):
        if broken or getattr(conn, "closed", True):
            self.last_used.pop(id(conn), None)
            with self._lock:
                self._created -= 1
            try:
                conn.close()
            except Exception:
                pass
        else:
            self._q.put(conn)

    def prewarm(self, n):
        """Dial n connections in parallel background threads at startup so
        the first real request never pays for a dial."""
        def one():
            try:
                self.put(self.get())
            except Exception:
                pass
        for _ in range(n):
            threading.Thread(target=one, daemon=True).start()


_pool = None
_pool_lock = threading.Lock()


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = _Pool(os.environ["DATABASE_URL"], _POOL_SIZE)
    return _pool


def prewarm():
    if _IS_PG:
        _get_pool().prewarm(4)


class _PooledConn:
    """Duck-types a psycopg2 connection; close() returns it to the pool.
    No rollback on release — connections are autocommit (see module doc)."""

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._done = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        if self._done:
            return
        self._done = True
        self._pool.last_used[id(self._conn)] = time.time()
        self._pool.put(self._conn, broken=getattr(self._conn, "closed", True))


def _pooled_conn():
    """Borrow a live pooled connection; helpers mid-query can't retry, so a
    conn idle long enough to be suspect gets one cheap liveness probe."""
    pool = _get_pool()
    for _ in range(3):
        try:
            conn = pool.get()
        except Exception:
            break
        fresh = (time.time() - pool.last_used.get(id(conn), 0)) < _IDLE_CHECK_AFTER
        try:
            if not fresh:
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            pool.last_used[id(conn)] = time.time()
            return _PooledConn(conn, pool)
        except Exception:
            pool.put(conn, broken=True)
    # Pool kept handing back corpses — dial straight (shared.db's retrying dial).
    return _sdb_direct_conn()


_sdb_direct_conn = sdb._conn

if _IS_PG:
    sdb._conn = _pooled_conn


def is_postgres():
    return _IS_PG


def q(sql, params=()):
    """Portable read. Write placeholders as %s; converted for sqlite."""
    if not _IS_PG:
        sql = sql.replace("%s", "?")
    conn = sdb._conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return sdb._fetchall(cur)
    finally:
        conn.close()


def execute(sql, params=()):
    if not _IS_PG:
        sql = sql.replace("%s", "?")
    conn = sdb._conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def scalar(sql, params=()):
    rows = q(sql, params)
    if not rows:
        return 0
    return list(rows[0].values())[0] or 0


def kv_many(keys):
    """Read many kv_store keys in ONE round trip (kv_get per key costs a full
    round trip each — reading 7 schedule stamps serially was user-visible)."""
    if not keys:
        return {}
    if _IS_PG:
        rows = q("SELECT key, value FROM kv_store WHERE key = ANY(%s)", (list(keys),))
    else:
        ph = ",".join("?" * len(keys))
        conn = sdb._conn()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT key, value FROM kv_store WHERE key IN ({ph})", list(keys))
            rows = sdb._fetchall(cur)
        finally:
            conn.close()
    return {r["key"]: r["value"] for r in rows}


def parallel(**tasks):
    """Run independent no-arg callables concurrently (each on its own pooled
    conn) and return {name: result}. Wall time ≈ the slowest single query
    instead of the sum. Exceptions propagate (first one wins)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(tasks)))) as ex:
        futs = {name: ex.submit(fn) for name, fn in tasks.items()}
        return {name: f.result() for name, f in futs.items()}
