"""A reel goes to Instagram at most once: the claim that guards the post.

    python -m shared.tests.run_reel_claim_cases

No network, no production database: a throwaway SQLite file.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from shared.db import claim_reel_for_post, get_reel, init_db, save_reel, update_reel   # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


def main():
    init_db()
    rid = save_reel(1, b"x", "cap", kind="animate")
    update_reel(rid, status="ready")
    check("first claim returns the previous status", claim_reel_for_post(rid), "ready")
    check("status is now posting", get_reel(rid)["status"], "posting")
    check("second claim is refused", claim_reel_for_post(rid), None)
    for st in ("posted", "killed", "superseded"):
        other = save_reel(2, b"x", "cap", kind="animate")
        update_reel(other, status=st)
        check(f"a {st} reel cannot be claimed", claim_reel_for_post(other), None)
    check("a missing reel cannot be claimed", claim_reel_for_post(99999), None)
    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        return 1
    print("all reel claim cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
