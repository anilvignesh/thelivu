"""In-process background jobs with live progress.

Long actions (publish, post carousel, build reel, AI suggestions) must never
freeze the UI — a job runs on a daemon thread, updates its registry entry via
a progress callback, and the frontend polls /api/jobs/<id>. Registry is
in-memory (this is a single-owner local app); the last 100 jobs are kept so
the System view can show history.
"""
import threading
import time
import uuid

_jobs = {}
_order = []
_lock = threading.Lock()
_KEEP = 100


def submit(name, fn, meta=None):
    """Run fn(progress) on a thread. fn returns a result dict; raising marks
    the job failed. progress(frac, msg) updates live state."""
    jid = uuid.uuid4().hex[:12]
    entry = {
        "id": jid, "name": name, "meta": meta or {},
        "state": "running", "progress": 0.0, "message": "starting…",
        "result": None, "error": None,
        "started_at": time.time(), "finished_at": None,
    }
    with _lock:
        _jobs[jid] = entry
        _order.append(jid)
        while len(_order) > _KEEP:
            _jobs.pop(_order.pop(0), None)

    def progress(frac, msg):
        entry["progress"] = max(0.0, min(1.0, float(frac)))
        entry["message"] = str(msg)

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
            entry["finished_at"] = time.time()

    threading.Thread(target=runner, daemon=True, name=f"job-{name}").start()
    return jid


def get(jid):
    return _jobs.get(jid)


def recent(limit=30):
    with _lock:
        ids = list(reversed(_order))[:limit]
    return [_jobs[i] for i in ids if i in _jobs]
