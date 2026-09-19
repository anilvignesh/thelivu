"""Does each part of this system still do the thing it exists to do?

Anil, 2026-09-14: *"Let's get this into a proper commercial grade system."*

The definition comes from that day's failures, all six of which were found by
somebody asking a question and none of which raised an error:

    OCR shipped and never fired                       12 hours
    cag-reports reading the About page                weeks, 0 candidates EVER
    cag-press-releases with no link_pattern           weeks
    31 duplicate candidates, ~5x queue inflation      4 days
    reel #71 leaked template text to Instagram        18 days queued, posted unchecked
    the digger's first model 429ing into a fallback   unknown

Health checks already existed — model_health, api_health, illustration_health —
and each was written after a specific incident to watch that one thing.
model_health is NVIDIA-only, so it was watching a provider we had already moved
off while the digger's reader died beside it.

**THE DISTINCTION THIS MODULE IS BUILT ON: "nothing to report" and "not working"
are indistinguishable in any single cycle.** A digger target that finds nothing
today is quiet; one that has found nothing EVER is broken. A reel queue that
posts nothing on Sunday is quiet; one that has not posted in nine days is
broken. The signal only exists over time, and nobody reads a week of logs.

So a check does not ask "did it throw". It asks "is it still producing what it
exists to produce", and it must be able to answer BROKEN for a component that is
succeeding at nothing.

Nothing here sends anything. Checks return structured results and the caller
decides — which keeps every check testable without a Telegram token.
"""

import logging
from datetime import datetime, timezone

log = logging.getLogger("health")

OK = "ok"            # doing its job
QUIET = "quiet"      # nothing to report, and that is a legitimate answer
BROKEN = "broken"    # succeeding at nothing, which is the failure with no error
UNKNOWN = "unknown"  # could not tell — never treated as OK

_ORDER = {BROKEN: 0, UNKNOWN: 1, QUIET: 2, OK: 3}
_MARK = {BROKEN: "BROKEN ", UNKNOWN: "unknown", QUIET: "quiet  ", OK: "ok     "}


class Check:
    """One component's answer, in the shape a person reads."""

    def __init__(self, name, status, detail, fix=""):
        self.name = name
        self.status = status
        self.detail = detail
        # What to do about it. A digest line that names a problem and not its
        # remedy gets read once and skipped thereafter.
        self.fix = fix

    def __repr__(self):
        return f"<Check {self.name} {self.status}>"


def _safe(fn, name):
    """A check that raises must not take the digest down with it.

    The whole point is to be told when something stopped working; a health
    system that goes silent because one probe threw has the exact failure it
    was built to catch.
    """
    try:
        return fn()
    except Exception as e:                                  # noqa: BLE001
        log.warning("health check %s failed: %s", name, e)
        return [Check(name, UNKNOWN, f"the check itself failed: {e}"[:160],
                      "look at this check before trusting the rest")]


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

def check_digger_targets():
    """Targets that fetch documents and never find anything.

    This is barren_targets() — added 2026-09-14 after four of nine targets
    turned out to have produced zero candidates in their entire history —
    generalised into the digest rather than left in one log line.
    """
    from shared import db

    # The window is 7 days, so a target fixed TODAY still reports barren until
    # its bad history rolls out. Said plainly in the detail rather than left for
    # the reader to wonder about — a digest that looks wrong gets distrusted.
    barren = db.barren_targets()
    if not barren:
        return [Check("digger targets", OK, "every target has found something")]

    # A target whose documents were all REFERRED to the corpus is not broken —
    # the opposite. Its documents are too substantial for the digger's window,
    # which on an audit report reaches the cover and the table of contents.
    # Reporting those as "check index_url and link_pattern" sent a reviewer to
    # fix something already correct: on 2026-09-19 thirty-three targets said
    # exactly that, and every one of them was pointed at the right source.
    referred = db.referred_targets()

    out = []
    for key, runs, docs in barren:
        if key in referred:
            r_runs, r_docs = referred[key]
            out.append(Check(f"digger/{key}", QUIET,
                             f"{r_docs} document(s) too long for the digger — "
                             f"referred to the corpus, not extracted here"))
        elif docs:
            out.append(Check(f"digger/{key}", BROKEN,
                             f"{docs} document(s) read over {runs} runs, nothing "
                             f"found (7-day window)",
                             "wrong pages — check index_url and link_pattern"))
        else:
            out.append(Check(f"digger/{key}", BROKEN,
                             f"{runs} runs, fetched nothing at all",
                             "check the index still exists"))
    return out


def check_digger_output(quiet_days=2, broken_days=7):
    """Is the digger finding anything at all, lately?

    Two thresholds on purpose. A couple of quiet days is ordinary — sources
    publish in bursts. A week is not, and by 2026-09-14 the last genuinely new
    candidate was four days old while the queue kept GROWING, because the
    duplicate bug made a stalled digger look busy.
    """
    from shared import db

    n2 = db.candidates_since(days=quiet_days)
    n7 = db.candidates_since(days=broken_days)
    if n7 == 0:
        return [Check("digger output", BROKEN,
                      f"no candidate in {broken_days} days",
                      "the sources are reachable but nothing is being extracted")]
    if n2 == 0:
        return [Check("digger output", QUIET,
                      f"nothing new in {quiet_days} days ({n7} in {broken_days})")]
    return [Check("digger output", OK, f"{n2} new in {quiet_days} days")]


def check_digger_models():
    """Are the NAMED readers answering, or has the cross-check quietly become
    one model against whatever was free?

    gemini-3.5-flash-lite returned 429 on seven of eight calls in one second on
    2026-09-14 and had been falling through to FALLBACK_MODEL for an unknown
    stretch. Nothing noticed, because a fallback is not an error — it is the
    system working as designed, just not as intended.
    """
    import os

    from engine.digger import freellm

    # CANNOT-CHECK IS NOT BROKEN. freellmapi is bound to 127.0.0.1 on the digger
    # VM and its key lives only in that box's env, so this probe run anywhere
    # else reports a missing credential — which is a fact about the laptop, not
    # about the model. Calling that BROKEN is how a health digest teaches its
    # reader to skim, which is precisely the failure it exists to prevent.
    if not os.environ.get("FREELLMAPI_KEY"):
        return [Check("digger models", UNKNOWN,
                      "not checkable from here — freellmapi is local to the digger VM",
                      "run this on the digger host to probe the readers")]

    out = []
    for label, model in (("A", freellm.MODEL_A), ("B", freellm.MODEL_B)):
        try:
            freellm.complete("Reply with exactly: ok", model=model, max_tokens=8,
                             timeout=25)
            out.append(Check(f"digger model {label}", OK, model))
        except Exception as e:                              # noqa: BLE001
            out.append(Check(f"digger model {label}", BROKEN,
                             f"{model} unavailable: {str(e)[:90]}",
                             "the cross-check is running on the fallback — "
                             "re-measure the free tier and repoint it"))
    return out


def check_reel_queue(stale_days=7):
    """Reels piling up unposted, and anything held at the door."""
    from shared import db

    ready, held, last = db.reel_queue_state()
    out = []
    if held:
        out.append(Check("reels held", BROKEN,
                         f"{held} reel(s) refused at post time",
                         "leaked template text — remake them"))
    if last is None:
        out.append(Check("reels posting", UNKNOWN, "nothing has ever been posted"))
    else:
        age = (datetime.now(timezone.utc) - last).days
        if age >= stale_days and ready:
            out.append(Check("reels posting", BROKEN,
                             f"{ready} ready, nothing posted in {age} days",
                             "the posting sweep is not running or is refusing"))
        elif ready:
            out.append(Check("reels posting", OK,
                             f"{ready} ready, last posted {age}d ago"))
        else:
            out.append(Check("reels posting", QUIET, f"queue empty, last posted {age}d ago"))
    return out


def check_archive():
    """Is the document spool being drained, or growing forever?

    The digger captures at read time onto a 945MB box. If the laptop stops
    pulling, the spool silently fills and shared/archive.py stops archiving at
    MAX_SPOOL_BYTES_TOTAL — degrading to the old read-and-drop behaviour without
    a single error.
    """
    from shared import db

    held, unpulled = db.archive_state()
    if unpulled > 200:
        return [Check("archive", BROKEN,
                      f"{unpulled} document(s) recorded but never collected",
                      "run ops/pull-archive.sh")]
    if held == 0:
        return [Check("archive", QUIET, "nothing archived yet")]
    return [Check("archive", OK, f"{held} document(s) held, {unpulled} awaiting collection")]


CHECKS = (
    ("digger targets", check_digger_targets),
    ("digger output", check_digger_output),
    ("digger models", check_digger_models),
    ("reel queue", check_reel_queue),
    ("archive", check_archive),
)


def run_all(include_models=True):
    """Every check, worst first. Never raises."""
    out = []
    for name, fn in CHECKS:
        if not include_models and name == "digger models":
            continue
        out.extend(_safe(fn, name))
    out.sort(key=lambda c: (_ORDER.get(c.status, 9), c.name))
    return out


def digest(checks=None, include_models=True):
    """The daily line-per-component report. Returns (text, worst_status).

    Ordered worst-first and marked, so the answer to "is anything wrong" is the
    first line rather than something to be found by reading. A digest that has
    to be read in full to be understood will stop being read.
    """
    checks = run_all(include_models=include_models) if checks is None else list(checks)
    if not checks:
        return "no checks ran", UNKNOWN
    # Sort HERE, not only in run_all. The worst-first guarantee is a property of
    # the digest, so it has to hold however the checks arrived — it did not when
    # they were passed in, which the case caught.
    checks.sort(key=lambda c: (_ORDER.get(c.status, 9), c.name))
    worst = min((c.status for c in checks), key=lambda s: _ORDER.get(s, 9))
    bad = sum(1 for c in checks if c.status in (BROKEN, UNKNOWN))

    head = ("ALL CLEAR — %d component(s) checked" % len(checks) if not bad
            else "%d of %d component(s) need attention" % (bad, len(checks)))
    lines = [head, ""]
    for c in checks:
        lines.append("%s %-22s %s" % (_MARK.get(c.status, "?"), c.name, c.detail))
        if c.fix and c.status in (BROKEN, UNKNOWN):
            lines.append("%s %-22s -> %s" % (" " * 7, "", c.fix))
    return "\n".join(lines), worst
