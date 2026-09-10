"""Long-form video publishing — the details that differ from Shorts.

    python -m shared.tests.run_longform_cases

No network, no YouTube credentials: publish_video() is exercised against a
stubbed requests module, so the metadata and permalink logic is real but nothing
leaves the machine.

What this is FOR is the handful of ways a long video published through the
Shorts path goes quietly wrong — a "#Shorts" tag on a ten-minute video, a
/shorts/ permalink that redirects, chapters YouTube silently ignores. None of
these raise an error anywhere; they just produce a worse video and a wrong link.
"""
import os
import sys
import tempfile

os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DB_PATH"] = _TMPDB.name

from publishing import youtube                    # noqa: E402

_fails = []


def check(name, got, want):
    ok = got == want
    if not ok:
        _fails.append(f"{name}: got {got!r}, want {want!r}")
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))


class _Resp:
    def __init__(self, code=200, headers=None, payload=None):
        self.status_code = code
        self.headers = headers or {}
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


class _FakeRequests:
    """Captures the metadata publish_video() sends."""
    def __init__(self):
        self.metadata = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.metadata = json
        return _Resp(200, {"Location": "https://upload.example/session"})

    def put(self, url, headers=None, data=None, timeout=None):
        return _Resp(200, payload={"id": "VID123"})


def _publish(**kw):
    fake = _FakeRequests()
    orig_req, orig_tok = youtube.requests, youtube._access_token
    youtube.requests = fake
    youtube._access_token = lambda: "token"
    try:
        result = youtube.publish_video(b"x" * 1024, kw.pop("title", "T"), **kw)
    finally:
        youtube.requests, youtube._access_token = orig_req, orig_tok
    return result, fake.metadata


def t_permalink_is_watch_not_shorts():
    """A long video served under /shorts/ redirects — and any link already
    published stays wrong."""
    (vid, url), _ = _publish()
    check("video id returned", vid, "VID123")
    check("permalink is /watch", url, "https://youtube.com/watch?v=VID123")
    check("permalink is not /shorts", "/shorts/" in url, False)


def t_no_shorts_tag_is_appended():
    """Appending #Shorts to a ten-minute video does not make it a Short; it
    mislabels it."""
    _, meta = _publish(description="A long investigation.")
    check("description unchanged",
          meta["snippet"]["description"], "A long investigation.")
    check("no #Shorts appended",
          "#shorts" in meta["snippet"]["description"].lower(), False)


def t_privacy_is_settable_and_validated():
    _, meta = _publish(privacy="unlisted")
    check("privacy honoured", meta["status"]["privacyStatus"], "unlisted")
    _, meta = _publish()
    check("defaults to public", meta["status"]["privacyStatus"], "public")
    try:
        _publish(privacy="secret")
        check("invalid privacy rejected", False, True)
    except youtube.YouTubePublishError:
        check("invalid privacy rejected", True, True)


def t_title_truncated_to_youtube_limit():
    _, meta = _publish(title="x" * 250)
    check("title capped at 100", len(meta["snippet"]["title"]), 100)


def t_chapters_render_into_the_description():
    _, meta = _publish(description="Body.",
                       chapters=[(0, "Intro"), (95, "The audit"), (600, "What it means")])
    desc = meta["snippet"]["description"]
    check("body kept", desc.startswith("Body."), True)
    check("first chapter at 0:00", "0:00 Intro" in desc, True)
    check("minutes formatted", "1:35 The audit" in desc, True)
    # 600s is 10:00, NOT 0:10:00 — the hour field only appears past an hour,
    # which is what YouTube expects and what viewers read.
    check("ten minutes has no hour field", "10:00 What it means" in desc, True)
    check("no spurious 0: prefix", "0:10:00" in desc, False)


def t_hour_long_chapters_get_an_hour_field():
    _, meta = _publish(chapters=[(0, "Intro"), (600, "Middle"), (3725, "Close")])
    desc = meta["snippet"]["description"]
    check("past an hour formatted h:mm:ss", "1:02:05 Close" in desc, True)


def t_invalid_chapter_lists_are_dropped_not_half_written():
    """YouTube silently renders NO chapters if the list is malformed, so a
    half-valid block is worse than none — it looks fine and does nothing."""
    check("fewer than three dropped",
          youtube.format_chapters([(0, "A"), (10, "B")]), "")
    check("not starting at zero dropped",
          youtube.format_chapters([(5, "A"), (10, "B"), (20, "C")]), "")
    check("valid list rendered",
          youtube.format_chapters([(0, "A"), (10, "B"), (20, "C")]).splitlines()[0],
          "0:00 A")


def t_chapters_sorted_and_blank_labels_ignored():
    out = youtube.format_chapters([(20, "C"), (0, "A"), (10, "  "), (5, "B")])
    check("blank label dropped", "  " in out, False)
    check("ascending order", out.splitlines()[0], "0:00 A")
    check("three survivors rendered", len(out.splitlines()), 3)


def main():
    print("long-form video cases")
    for t in (t_permalink_is_watch_not_shorts,
              t_no_shorts_tag_is_appended,
              t_privacy_is_settable_and_validated,
              t_title_truncated_to_youtube_limit,
              t_chapters_render_into_the_description,
              t_hour_long_chapters_get_an_hour_field,
              t_invalid_chapter_lists_are_dropped_not_half_written,
              t_chapters_sorted_and_blank_labels_ignored):
        t()

    print("\n" + "=" * 72)
    if _fails:
        print(f"{len(_fails)} FAILURE(S)")
        for f in _fails:
            print(f"  {f}")
        return 1
    print("all long-form cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
