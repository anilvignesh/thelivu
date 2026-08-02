"""In-process background jobs with live progress.

Long actions (publish, post carousel, build reel, AI suggestions) must never
freeze the UI — a job runs on a daemon thread, updates its registry entry via
a progress callback, and the frontend polls /api/jobs. The Activity view is the
one place all of that is visible; the per-action modal is just a shortcut to it.

**Why the registry is in-process and not in Postgres.** A job *is* a daemon
thread in this process, so it cannot outlive it: persisting rows would only
preserve corpses of work nothing is doing any more, and the artefact a finished
job produced (the reel row, the posted carousel) is already in the DB and
already has a view. Meanwhile Activity polls every 2s and a Railway round trip
from the laptop is 0.25-1s (see command_center/db.py) — a DB-backed registry
would make the one screen that has to feel live the slowest screen in the app.
The cost of that choice is that a CC restart loses the history, which is
honest: the restart killed the threads too. Activity states that with `boot_at`.

Server-side, though, is the point — the state is NOT in the browser, so a reload
or a different device (the phone, over Tailscale) picks the same job back up.
"""
import threading
import time
import uuid

_jobs = {}
_order = []
_lock = threading.Lock()
# ~200 jobs is a few days of real use and costs a few hundred KB of dicts; the
# old 100 dropped a morning's reel attempts off the bottom of the history.
_KEEP = 200
# A reel build calls back once per illustrated shot (up to ~18) plus a stage per
# phase, so the timeline stays readable and bounded without truncating a normal
# build at all.
_STEPS_KEEP = 40

# When this process came up. Anything from before it is gone, and Activity says so
# rather than implying nothing ever ran.
BOOT_AT = time.time()


def submit(name, fn, meta=None, kind=None):
    """Run fn(progress) on a thread. fn returns a result dict; raising marks
    the job failed. progress(frac, msg) updates live state.

    `kind` groups jobs for the Activity view's filter and icon ("reel", "post",
    "publish", "suggest"). `meta` carries the ids the view resolves to a story
    title (run_id / carousel_id / reel_id)."""
    jid = uuid.uuid4().hex[:12]
    now = time.time()
    entry = {
        "id": jid, "name": name, "kind": kind or "job", "meta": meta or {},
        "state": "running", "progress": 0.0, "message": "starting…",
        # The stage timeline — what it did and when, so "stuck" and "slow" are
        # distinguishable on a 20-minute render.
        "steps": [{"at": now, "progress": 0.0, "message": "starting…"}],
        "result": None, "error": None,
        "started_at": now, "updated_at": now, "finished_at": None,
    }
    with _lock:
        _jobs[jid] = entry
        _order.append(jid)
        while len(_order) > _KEEP:
            _jobs.pop(_order.pop(0), None)

    def progress(frac, msg):
        frac = max(0.0, min(1.0, float(frac)))
        msg = str(msg)
        entry["progress"] = frac
        entry["message"] = msg
        entry["updated_at"] = time.time()
        steps = entry["steps"]
        # One timeline row per distinct stage message. The illustration step
        # calls back per shot ("Illustrating shot 3/6…"), which is genuinely new
        # information; a repeated identical message is not, so it just advances
        # the row already there instead of printing the same line 40 times.
        if steps and steps[-1]["message"] == msg:
            steps[-1]["progress"] = frac
        else:
            steps.append({"at": entry["updated_at"], "progress": frac, "message": msg})
            del steps[:-_STEPS_KEEP]

    def runner():
        try:
            res = fn(progress)
            entry["result"] = res
            ok = not (isinstance(res, dict) and res.get("ok") is False)
            entry["state"] = "done" if ok else "failed"
            if not ok:
                entry["error"] = (res or {}).get("error") or entry["message"]
            else:
                entry["progress"] = 1.0
        except Exception as e:
            entry["state"] = "failed"
            entry["error"] = f"{type(e).__name__}: {e}"
        finally:
            entry["finished_at"] = entry["updated_at"] = time.time()

    threading.Thread(target=runner, daemon=True, name=f"job-{name}").start()
    return jid


def view(entry, *, slim=False):
    """A JSON-safe copy with the derived fields the UI needs.

    A copy, not the live entry: the API decorates it with a story label and the
    running thread is mutating the original underneath us."""
    if entry is None:
        return None
    now = time.time()
    end = entry["finished_at"] or now
    out = dict(entry)
    out["elapsed"] = round(end - entry["started_at"], 1)
    # Seconds since the last progress callback. A render sits on one message for
    # minutes, so "how long has it been silent" is the only way to tell a slow
    # ffmpeg from a wedged one.
    out["stale_secs"] = round(now - entry["updated_at"], 1) if not entry["finished_at"] else 0
    if slim:
        # The list poll runs every 2s; the timeline and the result (a reel result
        # carries a 2200-char caption) belong to the detail call.
        out.pop("steps", None)
        out.pop("result", None)
    return out


def get(jid):
    return _jobs.get(jid)


def _snapshot():
    with _lock:
        ids = list(reversed(_order))
    return [_jobs[i] for i in ids if i in _jobs]


def recent(limit=30, *, slim=False):
    return [view(e, slim=slim) for e in _snapshot()[:limit]]


def active():
    """Everything still running, oldest-started first — that ordering keeps a
    long reel build at the top instead of being pushed down by a quick post."""
    running = [e for e in _snapshot() if e["state"] == "running"]
    running.sort(key=lambda e: e["started_at"])
    return [view(e, slim=True) for e in running]


def query(*, q="", state=None, kind=None, limit=40, offset=0):
    """Filter/page the registry with the same semantics the SQL list surfaces use.

    Deliberately NOT api.util.list_query: that builds WHERE/ORDER BY for a table,
    and this registry is a list of dicts in RAM. The wire params and the response
    envelope are identical, so the frontend's one `listBar` control drives this
    screen unchanged — which is the part that has to match."""
    rows = _snapshot()
    if state and state != "all":
        rows = [e for e in rows if e["state"] == state]
    if kind and kind != "all":
        rows = [e for e in rows if e["kind"] == kind]
    if q:
        needle = q.lower()
        rows = [e for e in rows
                if needle in (e["name"] or "").lower()
                or needle in (e["message"] or "").lower()
                or needle in (e["error"] or "").lower()]
    total = len(rows)
    return [view(e, slim=True) for e in rows[offset:offset + limit]], total


def summary():
    """Counts for the nav badge — pure RAM, so the whole app can poll it."""
    rows = _snapshot()
    out = {"running": 0, "done": 0, "failed": 0, "boot_at": BOOT_AT}
    for e in rows:
        if e["state"] in out:
            out[e["state"]] += 1
    return out
