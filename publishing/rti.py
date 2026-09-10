"""RTI: the statutory route to records nobody publishes.

The blocked-host problem was never where the truth was. Measured across a real
investigation on 2026-09-10: every host that refused us was serving a *copy* of
something reachable elsewhere, while the one genuinely unavailable record — a
project-by-project breakdown of which highway penalties were waived, contested
or never pursued — is not behind any bot wall. It simply is not published.

No scraper returns that. An RTI application does, or the refusal to provide it
becomes the story instead. `engine/skills/beat-monitor/SKILL.md` already lists
"RTI/CIC — denials and what they reveal" as source category #7; this is the
machinery that category always needed.

## The craft detail that decides whether a request works

**The RTI Act gives you access to RECORDS, not answers to questions.** A public
information officer may lawfully reject "why was no penalty recovered?" as
seeking an opinion, and routinely does. The same information is obtainable by
asking for the record that would contain it: "a copy of each recovery notice
issued under clause X between date A and date B."

Almost every failed RTI fails here, so `draft()` refuses to emit a request
phrased as a question, and says why.

## Timelines (RTI Act 2005)

  * 30 days for a reply; 48 hours where life or liberty is concerned.
  * Silence past 30 days is a "deemed refusal" — appealable exactly like a
    written refusal, and worth treating as one rather than waiting on.
  * First Appeal to the First Appellate Authority within 30 days of the
    refusal or the deadline passing.
  * Second Appeal to the Information Commission within 90 days after that.

Filing is a person's act — it needs an identity, a fee and an address — so this
module drafts, tracks and reminds. It does not file.
"""

import re
from datetime import datetime, timedelta, timezone

REPLY_DAYS = 30
FIRST_APPEAL_DAYS = 30
SECOND_APPEAL_DAYS = 90

DRAFTED = "drafted"
FILED = "filed"
ANSWERED = "answered"
REFUSED = "refused"
DEEMED_REFUSED = "deemed_refused"   # 30 days elapsed in silence
APPEALED = "appealed"

# Phrasings that get an application rejected as "seeking an opinion" rather than
# a record. Checked at the start of a numbered item, which is where they appear.
_QUESTION_OPENERS = re.compile(
    r"^\s*(why|whether|is it|was it|does|do you|did you|explain|clarify|"
    r"what is the reason|kindly state|please state|justify)\b", re.I)


class RTIDraftError(ValueError):
    pass


def _iso(d):
    return d.date().isoformat()


def draft(authority, items, subject, period=None, applicant="", public_interest=""):
    """Compose an RTI application.

    `items` are the RECORDS sought, one per line — copies, registers, notings,
    correspondence. Not questions.
    """
    if not authority.strip():
        raise RTIDraftError("a public authority must be named — an RTI goes to a "
                            "specific PIO, not to a government in general")
    if not items:
        raise RTIDraftError("no records requested")

    bad = [i for i in items if _QUESTION_OPENERS.match(i)]
    if bad:
        raise RTIDraftError(
            "these read as questions, and a PIO may lawfully reject them as "
            "seeking an opinion rather than a record: "
            + "; ".join(b[:60] for b in bad)
            + ". Ask instead for the document that would contain the answer — "
              "'a copy of each notice issued under...' rather than 'why was...'")

    lines = [
        "APPLICATION UNDER THE RIGHT TO INFORMATION ACT, 2005",
        "",
        f"To: The Public Information Officer, {authority}",
        f"Subject: {subject}",
    ]
    if period:
        lines.append(f"Period: {period}")
    lines += ["", "I request copies of the following records:", ""]
    for n, item in enumerate(items, 1):
        lines.append(f"{n}. {item.rstrip('.')}.")
    lines += [
        "",
        "Where a record is held in electronic form, an electronic copy is "
        "requested. If any part of this request is held by another public "
        "authority, please transfer that part under Section 6(3) and inform me.",
        "",
        "If any part is refused, please state the specific exemption under "
        "Section 8 or 9 relied upon, and the details of the First Appellate "
        "Authority, as required by Section 7(8).",
    ]
    if public_interest:
        lines += ["", f"Public interest: {public_interest}"]
    if applicant:
        lines += ["", applicant]
    return "\n".join(lines)


def due_dates(filed_on):
    """Reply deadline and the appeal windows that follow it."""
    if isinstance(filed_on, str):
        filed_on = datetime.fromisoformat(filed_on)
    reply_by = filed_on + timedelta(days=REPLY_DAYS)
    return {
        "filed_on": _iso(filed_on),
        "reply_by": _iso(reply_by),
        "first_appeal_by": _iso(reply_by + timedelta(days=FIRST_APPEAL_DAYS)),
        "second_appeal_by": _iso(reply_by + timedelta(days=FIRST_APPEAL_DAYS)
                                 + timedelta(days=SECOND_APPEAL_DAYS)),
    }


def status_for(filed_on, replied=False, refused=False, now=None):
    """Where a filed request stands.

    Silence past the deadline is a DEEMED REFUSAL, not "still waiting". The
    distinction matters twice over: it starts the appeal clock, and an authority
    that lets the clock run out has itself done something worth reporting.
    """
    now = now or datetime.now(timezone.utc)
    if isinstance(filed_on, str):
        filed_on = datetime.fromisoformat(filed_on)
    if filed_on.tzinfo is None:
        filed_on = filed_on.replace(tzinfo=timezone.utc)
    if refused:
        return REFUSED
    if replied:
        return ANSWERED
    if (now - filed_on).days > REPLY_DAYS:
        return DEEMED_REFUSED
    return FILED


def is_lead(status, exemption_cited=""):
    """Is this outcome itself a story?

    A refusal is not a dead end. Beat-monitor category #7 exists because what
    an authority declines to disclose, and which exemption it reaches for, is
    frequently more revealing than the record would have been. A deemed refusal
    — simply not answering — says something too.
    """
    if status == DEEMED_REFUSED:
        return True, ("no reply within the statutory 30 days: a deemed refusal, "
                      "appealable, and a documented failure to answer")
    if status == REFUSED:
        why = f" citing {exemption_cited}" if exemption_cited else ""
        return True, (f"refused{why} — the exemption claimed is itself a "
                      "checkable fact, and often the story")
    return False, ""


def suggest_from_gap(claim_text, authority):
    """Turn an evidence gap into record requests.

    Deliberately conservative: it proposes the shape of a request for a human
    to sharpen. A vague RTI is refused as too broad, and a refusal costs 30
    days, so precision here is worth more than coverage.
    """
    return {
        "authority": authority,
        "subject": f"Records concerning: {claim_text[:120]}",
        "items": [
            "a copy of the file notings, correspondence and any order relating "
            "to the matter described in the subject above",
            "a copy of any circular, guideline or standing instruction applied "
            "in deciding that matter",
            "a statement of action taken, with dates, and copies of any notice "
            "issued",
        ],
        "note": ("sharpen each item to a named record and a date range before "
                 "filing — a broad request is refused as such, and that costs "
                 "30 days"),
    }
