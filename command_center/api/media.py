"""Carousels, reels, bio links — the presentation surfaces.

Posting (carousel or reel) is gated exactly like article publishing: the ONE
shared paths post_carousel_run / post_reel_run, behind a UI confirm. Making,
editing, rebuilding, killing are all autonomous actions.
"""
import os
import re

from starlette.responses import Response
from starlette.routing import Route

from command_center import db, jobs
from command_center.api.util import (J, endpoint, err, breaker_state, list_query,
                                     SORTS_BASE)
from shared.db import (
    get_run, get_carousel_slides, queue_carousel_run, get_reel_bytes,
    update_reel, add_bio_link, list_bio_links, delete_bio_link,
    set_bio_link_pinned,
)

_BASE = lambda: os.environ.get("SLIDE_SERVER_BASE_URL", "").rstrip("/")


# ── Carousels ─────────────────────────────────────────────────────────────────

_CAROUSEL_FROM = "carousel_runs cr LEFT JOIN pipeline_runs r ON r.id = cr.run_id"
# Same two base sorts as every other list surface, plus the one axis a posted-media
# screen actually wants. NULLS LAST so unposted rows don't crowd out the posted ones.
CAROUSEL_SORTS = {"newest": "cr.id DESC", "oldest": "cr.id ASC",
                  "posted": "cr.posted_at DESC NULLS LAST, cr.id DESC"}


@endpoint
def list_carousels(request, data):
    lq = list_query(request, sorts=CAROUSEL_SORTS, default_limit=20, max_limit=100)
    lq.filter_status("cr.status", {})
    # Desk scope: carousels and reels have no desk of their own — they inherit
    # the run's, which the LEFT JOIN above already has in `r`.
    lq.filter_desk("r.desk", request.query_params.get("desk"))
    lq.search("r.throughline", "cr.caption")
    r = db.parallel(
        cars=lambda: db.q("SELECT cr.id, cr.run_id, cr.status, cr.caption, cr.ig_permalink, "
                          "cr.dark, cr.article_url, cr.view_label, r.desk, "
                          "r.throughline AS story FROM "
                          + _CAROUSEL_FROM + lq.where_sql() + lq.page_sql(),
                          lq.page_params()),
        total=lambda: db.q(lq.count_sql(_CAROUSEL_FROM), tuple(lq.params))[0]["n"],
        breaker=breaker_state,
    )
    cars = r["cars"]
    # ALL slides in one query, not one per carousel (20 round trips ≈ 20s on a
    # slow link — the exact N+1 the Streamlit dashboard already learned to avoid).
    slides_by_car = {}
    if cars:
        ids = [c["id"] for c in cars]
        if db.is_postgres():
            rows = db.q("SELECT carousel_id, position, headline FROM carousel_slides "
                        "WHERE carousel_id = ANY(%s) ORDER BY carousel_id, position", (ids,))
        else:
            ph = ",".join("?" * len(ids))
            rows = db.q(f"SELECT carousel_id, position, headline FROM carousel_slides "
                        f"WHERE carousel_id IN ({ph}) ORDER BY carousel_id, position",
                        tuple(ids))
        for s in rows:
            slides_by_car.setdefault(s["carousel_id"], []).append(s)
    base = _BASE()
    for c in cars:
        c["slides"] = [{"position": s["position"], "headline": s["headline"],
                        "url": f"{base}/carousel_{c['id']}_{s['position']}.jpg" if base else None}
                       for s in slides_by_car.get(c["id"], [])]
    return J({"carousels": cars, "breaker": r["breaker"], "slide_base": base,
              **lq.envelope(r["total"])})


@endpoint
def make_carousel(request, data):
    rid = int(data.get("run_id") or 0)
    run = get_run(rid)
    if not run:
        return err("no such run", 404)
    if run["status"] != "published":
        return err(f"run #{rid} is '{run['status']}' — carousels are made for published stories")
    base = _BASE()
    url = f"{base}/a/{run['slug']}" if base and run.get("slug") else ""
    queue_carousel_run(rid, article_url=url)
    b = breaker_state()
    # The belief desks compose on the free NVIDIA model, exactly as the news desk
    # does — so the paid breaker being open does not stop either of them. The
    # warning stays because a missing NVIDIA key lands you in the same place, and
    # ./attend carousel is the answer to both.
    note = ("Queued — but composing needs a model and the breaker is open "
            f"({b['reason']}). Build it attended: ./attend carousel <id>."
            if b["open"] else "Queued — it composes on the next tick (~2 min).")
    from engine.desks.ek import carousel as ek_carousel
    if ek_carousel.is_belief(run.get("desk")):
        from shared.db import get_belief
        belief = get_belief(rid) or {}
        note += (f" {ek_carousel.SERIES_NAME.get((run['desk'] or '').lower(), '')} piece"
                 + (" — every slide will carry the "
                    f"“{ek_carousel.REEL_VIEW_LABEL}” marker."
                    if ek_carousel.slide_label(belief, run.get("draft_text") or "")
                    else "."))
    return J({"ok": True, "note": note})


@endpoint
def carousel_action(request, data):
    cid = int(request.path_params["cid"])
    action = data.get("action")
    if action == "kill":
        db.execute("UPDATE carousel_runs SET status='killed' WHERE id = %s", (cid,))
        return J({"ok": True})
    if action == "rebuild":
        # Never destroy the current slides to request new ones — the composer
        # clears them itself right before writing the new set (HANDOFF lesson,
        # carousel #14).
        db.execute("UPDATE carousel_runs SET status='queued' WHERE id = %s", (cid,))
        b = breaker_state()
        note = (f"Queued to rebuild — breaker is open ({b['reason']}); current slides "
                f"stay until new ones exist. Attended: ./attend carousel {cid}."
                if b["open"] else "Queued to rebuild — new slides in ~2 min.")
        return J({"ok": True, "note": note})
    return err("action must be kill|rebuild")


@endpoint
def edit_caption(request, data):
    cid = int(request.path_params["cid"])
    cap = data.get("caption")
    if not isinstance(cap, str):
        return err("caption required")
    db.execute("UPDATE carousel_runs SET caption = %s WHERE id = %s", (cap, cid))
    return J({"ok": True})


@endpoint
def edit_slide(request, data):
    """Owner edit of one slide's headline. The rendered file cached on Railway
    goes stale, so we ask the fileserver to re-render (?fresh=1) — that's what
    Meta fetches at post time."""
    cid = int(request.path_params["cid"])
    pos = int(request.path_params["pos"])
    headline = (data.get("headline") or "").strip()
    if not headline:
        return err("headline required")
    db.execute("UPDATE carousel_slides SET headline = %s "
               "WHERE carousel_id = %s AND position = %s", (headline, cid, pos))
    refreshed = False
    base = _BASE()
    if base:
        try:
            import requests
            r = requests.get(f"{base}/carousel_{cid}_{pos}.jpg?fresh=1", timeout=30)
            refreshed = r.status_code == 200
        except Exception:
            pass
    return J({"ok": True, "refreshed": refreshed,
              "note": None if refreshed else
              "Saved — but the hosted slide image could not be re-rendered; "
              "check the fileserver before posting."})


@endpoint
def post_carousel(request, data):
    cid = int(request.path_params["cid"])
    if not get_carousel_slides(cid):
        return err("no slides composed yet — nothing to post")

    def do_post(progress):
        from publishing.publish import post_carousel_run
        return post_carousel_run(cid, progress=progress)

    return J({"ok": True, "job": jobs.submit(f"post carousel #{cid}", do_post,
                                             {"carousel_id": cid}, kind="post")})


# ── Reels ─────────────────────────────────────────────────────────────────────

_REEL_FROM = "reels re LEFT JOIN pipeline_runs r ON r.id = re.run_id"
REEL_SORTS = {"newest": "re.id DESC", "oldest": "re.id ASC",
              "posted": "re.posted_at DESC NULLS LAST, re.id DESC"}


@endpoint
def list_reels(request, data):
    lq = list_query(request, sorts=REEL_SORTS, default_limit=20, max_limit=100)
    lq.filter_status("re.status", {})
    # `kind` is the one axis that genuinely separates reels (illustrated vs text-slide),
    # so it gets a filter of its own rather than being folded into status.
    kind = (request.query_params.get("kind") or "").strip()
    if kind and kind != "all":
        lq.add("re.kind = %s", kind)
    lq.filter_desk("r.desk", request.query_params.get("desk"))
    lq.search("r.throughline", "re.caption")
    size = "OCTET_LENGTH(re.mp4)" if db.is_postgres() else "LENGTH(re.mp4)"
    reels = db.q(f"SELECT re.id, re.run_id, re.kind, re.caption, re.status, "
                 f"re.ig_permalink, re.notes, re.created_at, re.posted_at, "
                 f"{size} AS size_bytes, r.throughline AS story FROM "
                 + _REEL_FROM + lq.where_sql() + lq.page_sql(), lq.page_params())
    total = db.q(lq.count_sql(_REEL_FROM), tuple(lq.params))[0]["n"]
    from command_center.api.system import voice_status
    from publishing import voices
    from shared.db import kv_get
    return J({"reels": reels, "voice_up": voice_status(), "kind": kind or "all",
              "voices": voices.available(),
              "voice_default": (kv_get("reel_voice") or "").strip() or voices.default_name(),
              **lq.envelope(total)})


@endpoint
def make_reel(request, data):
    """Build a narrated reel locally (Gemma 4 script + Chatterbox voice +
    ffmpeg). Long — runs as a job with live progress.

    `notes` is the remake suggestion box: what to change about the cut he just
    watched. It steers the script step and is stored on the resulting reel."""
    rid = int(data.get("run_id") or 0)
    run = get_run(rid)
    if not run:
        return err("no such run", 404)
    dark = data.get("dark")
    notes = (data.get("notes") or "").strip() or None
    # Which voice narrates. Validated here rather than 600s later inside the
    # render: an unknown name should fail the click, not the job.
    voice = (data.get("voice") or "").strip() or None
    if voice:
        from publishing import voices
        try:
            voices.resolve(voice)
        except ValueError as e:
            return err(str(e))
    article_url = None
    base = _BASE()
    if base and run.get("slug"):
        article_url = f"{base}/a/{run['slug']}"

    def do_make(progress):
        from publishing.make_reel import make_narrated_reel
        return make_narrated_reel(rid, dark=dark, article_url=article_url,
                                  progress=progress, notes=notes, voice=voice)

    return J({"ok": True, "job": jobs.submit(f"build reel for run #{rid}", do_make,
                                             {"run_id": rid}, kind="reel")})


@endpoint
def reel_action(request, data):
    reel_id = int(request.path_params["reel_id"])
    action = data.get("action")
    if action == "kill":
        update_reel(reel_id, status="killed")
        return J({"ok": True})
    if action == "caption":
        cap = data.get("caption")
        if not isinstance(cap, str):
            return err("caption required")
        update_reel(reel_id, caption=cap)
        return J({"ok": True})
    return err("action must be kill|caption")


@endpoint
def post_reel(request, data):
    reel_id = int(request.path_params["reel_id"])

    def do_post(progress):
        from publishing.publish import post_reel_run
        return post_reel_run(reel_id, progress=progress)

    return J({"ok": True, "job": jobs.submit(f"post reel #{reel_id}", do_post,
                                             {"reel_id": reel_id}, kind="post")})


@endpoint
def reel_mp4(request, data):
    """Serve the reel video from the DB with Range support, so the <video>
    preview works without round-tripping through Railway."""
    reel_id = int(request.path_params["reel_id"])
    blob = get_reel_bytes(reel_id)
    if blob is None:
        return err("no such reel / no video bytes", 404)
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    total = len(blob)
    rng = request.headers.get("range")
    headers = {"Accept-Ranges": "bytes"}
    if rng:
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        if m:
            start = int(m.group(1)) if m.group(1) else 0
            end = int(m.group(2)) if m.group(2) else total - 1
            end = min(end, total - 1)
            if start > end or start >= total:
                return Response(status_code=416,
                                headers={"Content-Range": f"bytes */{total}"})
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
            return Response(blob[start:end + 1], status_code=206,
                            media_type="video/mp4", headers=headers)
    return Response(blob, media_type="video/mp4", headers=headers)


# ── Bio links ─────────────────────────────────────────────────────────────────

@endpoint
def bio_list(request, data):
    return J({"links": list_bio_links(), "base": _BASE()})


@endpoint
def bio_add(request, data):
    title = (data.get("title") or "").strip()
    url = (data.get("url") or "").strip()
    if not title or not url:
        return err("title and url required")
    add_bio_link(title, url, pinned=bool(data.get("pinned")))
    return J({"ok": True})


@endpoint
def bio_modify(request, data):
    link_id = int(request.path_params["link_id"])
    if request.method == "DELETE":
        delete_bio_link(link_id)
        return J({"ok": True})
    set_bio_link_pinned(link_id, bool(data.get("pinned")))
    return J({"ok": True})


routes = [
    Route("/carousels", list_carousels, methods=["GET"]),
    Route("/carousels", make_carousel, methods=["POST"]),
    Route("/carousels/{cid:int}", edit_caption, methods=["PATCH"]),
    Route("/carousels/{cid:int}/action", carousel_action, methods=["POST"]),
    Route("/carousels/{cid:int}/post", post_carousel, methods=["POST"]),
    Route("/carousels/{cid:int}/slides/{pos:int}", edit_slide, methods=["PATCH"]),
    Route("/reels", list_reels, methods=["GET"]),
    Route("/reels", make_reel, methods=["POST"]),
    Route("/reels/{reel_id:int}/action", reel_action, methods=["POST"]),
    Route("/reels/{reel_id:int}/post", post_reel, methods=["POST"]),
    Route("/reels/{reel_id:int}.mp4", reel_mp4, methods=["GET"]),
    Route("/bio", bio_list, methods=["GET"]),
    Route("/bio", bio_add, methods=["POST"]),
    Route("/bio/{link_id:int}", bio_modify, methods=["DELETE", "PATCH"]),
]
