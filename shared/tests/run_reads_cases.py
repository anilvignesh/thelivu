"""Article read counting — the privacy promise and the bot line.

    python -m shared.tests.run_reads_cases

No network, no production database: a throwaway SQLite file.

What it is FOR is the two ways this feature can be quietly wrong. It can count
Telegram's link-unfurler as a reader, which inflates the numbers in the
flattering direction — the worst way for a verification-first project to be
wrong. And it can leak: an IP, a raw user-agent, a full referrer with a search
query in it, or a visitor hash stable enough across days to follow somebody
around. Both failures look like success from the dashboard.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

import datetime as _dt                                  # noqa: E402

from publishing import reads                            # noqa: E402
from shared.db import init_db, _conn                    # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def check_that(name, cond, detail=""):
    if not cond:
        _fails.append(f"{name}: {detail or 'false'}")
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"\n        {detail}"))


def rows():
    cur = _conn().cursor()
    cur.execute("SELECT slug, run_id, is_bot, visitor_hash, referrer_host FROM page_reads "
                "ORDER BY id")
    return [tuple(r) for r in cur.fetchall()]


def clear():
    conn = _conn()
    conn.cursor().execute("DELETE FROM page_reads")
    conn.commit()
    conn.close()


CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def t_bot_line():
    print("\nwho counts as a reader:")
    check("a real browser is a reader", reads.is_bot(CHROME), False)
    check("an iPhone browser is a reader", reads.is_bot(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
        "Version/17.5 Mobile/15E148 Safari/604.1"), False)
    # The ones that will actually dominate /a/ traffic.
    for ua in ("TelegramBot (like TwitterBot)",
               "facebookexternalhit/1.1",
               "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
               "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
               "WhatsApp/2.23",
               "python-requests/2.31.0",
               "curl/8.4.0"):
        check(f"  {ua[:38]!r:42} is not", reads.is_bot(ua), True)
    # No UA at all is a script. Every real browser sends one, so the safe
    # reading of silence is "not a reader".
    check("no user-agent at all is not a reader", reads.is_bot(""), True)
    check("...nor is a missing one", reads.is_bot(None), True)


def t_referrer_is_host_only():
    print("\nthe referrer keeps the host and nothing else:")
    check("a search URL loses its query",
          reads.referrer_host("https://www.google.com/search?q=cag+kerala+cmdrf+scam"),
          "www.google.com")
    check("a path is dropped",
          reads.referrer_host("https://t.me/thelivu_reports/41"), "t.me")
    check("a port is dropped", reads.referrer_host("http://localhost:8000/x"), "localhost")
    check("no referrer is None", reads.referrer_host(""), None)
    check("None is None", reads.referrer_host(None), None)


def t_hash_is_daily():
    print("\nthe visitor hash answers 'today' and cannot answer 'this week':")
    a = reads.visitor_hash("49.37.1.2", CHROME)
    b = reads.visitor_hash("49.37.1.2", CHROME)
    check("stable within the day", a, b)
    check_that("a different reader hashes differently",
               reads.visitor_hash("49.37.9.9", CHROME) != a, "")
    check_that("a different browser on one IP too",
               reads.visitor_hash("49.37.1.2", "Firefox/1.0") != a, "")

    # Roll the day. The salt is regenerated and the old one is not kept
    # anywhere, so the same reader is unrecognisable tomorrow — that is the
    # promise, and it is structural rather than a policy we have to keep.
    reads._salt_day = _dt.date(2000, 1, 1)
    tomorrow = reads.visitor_hash("49.37.1.2", CHROME)
    check_that("and unrecognisable across days", tomorrow != a, "")
    check_that("the old salt is gone, not archived",
               reads._salt_day != _dt.date(2000, 1, 1), "salt day did not roll")


def t_records_and_stores_nothing_identifying():
    print("\nwhat actually lands in the table:")
    clear()
    reads.record("152-cag-flags-irregular-parking", run_id=152, ip="49.37.1.2",
                 user_agent=CHROME, referrer="https://t.me/thelivu_reports/41")
    reads.record("152-cag-flags-irregular-parking", run_id=152, ip="49.37.1.2",
                 user_agent=CHROME, referrer=None)
    reads.record("152-cag-flags-irregular-parking", run_id=152, ip="10.0.0.9",
                 user_agent="TelegramBot (like TwitterBot)", referrer=None)
    reads.flush()
    got = rows()
    check("three reads landed", len(got), 3)
    check("the bot is flagged, not dropped", [r[2] for r in got], [0, 0, 1])
    check("...so humans are countable separately",
          len([r for r in got if not r[2]]), 2)
    check("the same reader twice is one unique",
          len({r[3] for r in got if not r[2]}), 1)
    check("host kept, path and query gone", got[0][4], "t.me")
    check("run_id is carried", got[0][1], 152)

    blob = repr(got)
    check_that("no IP anywhere in the table", "49.37.1.2" not in blob, blob[:200])
    check_that("no raw user-agent either", "Mozilla" not in blob, blob[:200])


def t_never_breaks_the_page():
    print("\nanalytics must not be able to break the thing it measures:")
    clear()
    # A DB that refuses writes must not raise into the request handler. The
    # writer thread swallows it; `record` only ever queues.
    import shared.db as sdb
    original = sdb._conn
    sdb._conn = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db gone"))
    try:
        reads.record("x-slug", ip="1.2.3.4", user_agent=CHROME)
        reads.flush(timeout=2)
        print("  PASS  a dead database does not raise into the caller")
    except Exception as e:
        _fails.append(f"a dead database raised: {e}")
        print(f"  FAIL  a dead database raised: {e}")
    finally:
        sdb._conn = original

    # A full queue drops rather than blocking a reader. Unbounded here would
    # turn a DB outage into a memory leak in the public web server.
    import queue as _queue
    saved = reads._q
    reads._q = _queue.Queue(maxsize=1)
    reads._q.put_nowait(("filler", None, False, "h", None, _dt.datetime.now()))
    try:
        reads.record("y-slug", ip="1.2.3.4", user_agent=CHROME)
        print("  PASS  a full queue drops the read instead of blocking")
    except Exception as e:
        _fails.append(f"a full queue raised: {e}")
        print(f"  FAIL  a full queue raised: {e}")
    finally:
        reads._q = saved


def main():
    init_db()
    for t in (t_bot_line, t_referrer_is_host_only, t_hash_is_daily,
              t_records_and_stores_nothing_identifying, t_never_breaks_the_page):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all read-counting cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
