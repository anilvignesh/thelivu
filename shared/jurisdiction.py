"""The inputs a jurisdiction supplies, so the method does not have to know them.

Anil, 2026-09-15: *"Let's build the frameworks which can then be used anywhere.
Any country."*

Nothing that works today is about India. Finding document indexes on a
government domain, detecting a JS shell and watching it for its API, telling a
record from an office circular by content, noticing a source that has gone
quiet, reading whole documents and keeping the text, comparing across years and
across peer entities — all of that is method. What is Indian is a rupee, a state
name, and the CAG.

So that is the test, and it is the plan's own (`docs/plans/09-investigation-
framework.md` §1): **if a rule mentions a rupee, a state name, or the audit
body, it is config.** It lives in `jurisdictions/<key>.yaml` and is read through
here. A second country is a second YAML and a scout run.

This module is deliberately dependency-light and does no I/O beyond reading the
file once, because it is imported by the digger — which runs on a 945MB box
under a 256MB cap.
"""

import functools
import os
import re
from datetime import date, datetime

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "jurisdictions")

DEFAULT_KEY = os.environ.get("JURISDICTION", "india")


class JurisdictionError(RuntimeError):
    """The config is missing or unusable. Never swallowed: running with a
    half-read jurisdiction would silently narrow the peer set, and a comparison
    over the wrong peer set is a wrong claim rather than a missing one."""


class Jurisdiction:
    """One country's inputs. Read-only."""

    def __init__(self, data, path):
        self._d = data
        self.path = path
        self.key = data.get("key") or "?"
        self.name = data.get("name") or self.key
        self.entity_kind = data.get("entity_kind") or "entity"
        self.entities = list(data.get("entities") or [])
        self.languages = list(data.get("language") or ["en"])
        self.money = dict(data.get("money") or {})
        self.fiscal_year = dict(data.get("fiscal_year") or {})
        self.audit_body = dict(data.get("audit_body") or {})
        self.portals = list(data.get("portals") or [])
        self.audit_offices = list(data.get("audit_offices") or [])
        self.entity_aliases = {
            _norm_entity(k): v for k, v in (data.get("entity_aliases") or {}).items()}
        if not self.entities:
            raise JurisdictionError(f"{path}: no entities — nothing to compare across")

    # ── the peer set ────────────────────────────────────────────────────────

    @property
    def peer_count(self):
        """How many entities a cross-entity claim is measured against.

        Reported alongside such a claim, never assumed: "14 of 30 states" and
        "14 of 16 states" are different findings."""
        return len(self.entities)

    def is_entity(self, name):
        return self.canonical_entity(name) is not None

    def canonical_entity(self, name):
        """Match a loosely-written entity name to the peer set, or None.

        Documents write "Jammu and Kashmir", "J&K" and "Jammu & Kashmir" for one
        place. Matching is deliberately narrow — normalise punctuation and case,
        then consult the `entity_aliases` a person wrote down. Nothing fuzzy: a
        near-match that silently merged two states would manufacture a
        structural finding out of a clerical error, and it would look exactly
        like a real one."""
        if not name:
            return None
        want = _norm_entity(name)
        for e in self.entities:
            if _norm_entity(e) == want:
                return e
        alias = self.entity_aliases.get(want)
        if alias:
            for e in self.entities:
                if _norm_entity(e) == _norm_entity(alias):
                    return e
        return None

    # ── money ───────────────────────────────────────────────────────────────

    @property
    def base_unit(self):
        """The unit every stored amount is normalised to (`findings.amount_cr`)."""
        return self.money.get("base_unit") or "unit"

    def to_base_unit(self, amount, scale):
        """Convert `amount` written at `scale` into the base unit.

        Raises on an unknown scale rather than guessing. A figure converted by a
        guessed multiplier is off by a factor of 100 and reads entirely
        plausible, which is the worst failure available here."""
        scales = self.money.get("scales") or {}
        base = self.base_unit
        if scale == base:
            return float(amount)
        if scale not in scales:
            raise JurisdictionError(
                f"unknown money scale {scale!r} for {self.key}; "
                f"known: {sorted(scales) or 'none'}")
        if base not in scales:
            raise JurisdictionError(
                f"base unit {base!r} is not itself a listed scale for {self.key}")
        return float(amount) * scales[scale] / scales[base]

    def format_money(self, amount, unit=None):
        """"₹33,973 crore" — symbol, grouped digits, unit named.

        Indian grouping is 2-2-3 (12,34,567), not 3-3-3, so the stdlib's
        thousands separator is wrong here and every figure we put on screen
        would be subtly foreign-looking."""
        if amount is None:
            return ""
        unit = unit or self.base_unit
        sym = self.money.get("symbol") or ""
        grouped = _group(amount, self.money.get("grouping") or "western")
        return f"{sym}{grouped} {unit}".strip()

    # ── time ────────────────────────────────────────────────────────────────

    def fiscal_label(self, when):
        """The label an audit report covering `when` carries: "2023-24".

        A report is labelled by the period it audits, not when it was published.
        Comparing by publication date compares the wrong documents."""
        d = _as_date(when)
        start = self.fiscal_year.get("starts") or "01-01"
        try:
            m, day = (int(x) for x in start.split("-"))
        except ValueError:
            raise JurisdictionError(f"bad fiscal_year.starts {start!r} for {self.key}")
        y = d.year if (d.month, d.day) >= (m, day) else d.year - 1
        if (self.fiscal_year.get("label") or "").upper() == "YYYY-YY":
            return f"{y}-{str(y + 1)[-2:]}"
        return str(y)

    def fiscal_start_year(self, label):
        """The opening calendar year of a label like "2023-24" or "2023"."""
        m = re.match(r"\s*(\d{4})", str(label or ""))
        return int(m.group(1)) if m else None

    # ── the scout's starting points ─────────────────────────────────────────

    def seed_hosts(self):
        """Hosts the scout begins from. NOT trusted sources — places to look."""
        return [p.get("host") for p in self.portals if p.get("host")]

    def objection_vocabulary(self):
        return list(self.audit_body.get("objection_vocabulary") or [])

    def __repr__(self):
        return (f"<Jurisdiction {self.key} {self.peer_count} {self.entity_kind}s, "
                f"{len(self.audit_offices)} audit offices>")


def _norm_entity(s):
    s = str(s).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", s)


def _as_date(when):
    if isinstance(when, datetime):
        return when.date()
    if isinstance(when, date):
        return when
    try:
        return datetime.fromisoformat(str(when)[:19]).date()
    except ValueError:
        raise JurisdictionError(f"not a date: {when!r}")


def _group(n, style):
    """Digit grouping. `indian` is 2-2-3; anything else is 3-3-3."""
    neg = n < 0
    whole = abs(n)
    frac = ""
    if isinstance(whole, float) and not whole.is_integer():
        whole, frac = int(whole), f"{abs(n) % 1:.2f}"[1:]
    s = str(int(whole))
    if style == "indian" and len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    elif len(s) > 3:
        s = f"{int(s):,}"
    return ("-" if neg else "") + s + frac


@functools.lru_cache(maxsize=8)
def load(key=None):
    """The jurisdiction, parsed once. `key` defaults to $JURISDICTION or india."""
    import yaml

    key = key or DEFAULT_KEY
    path = os.path.join(_DIR, f"{key}.yaml")
    if not os.path.exists(path):
        have = sorted(f[:-5] for f in os.listdir(_DIR)) if os.path.isdir(_DIR) else []
        raise JurisdictionError(f"no jurisdiction {key!r} in {_DIR}; have: {have}")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Jurisdiction(data, path)


def available():
    """Every jurisdiction file present, by key."""
    if not os.path.isdir(_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(_DIR) if f.endswith(".yaml"))
