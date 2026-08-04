"""Thelivu Command Center — the operations base.

Run:  venv/bin/python -m command_center.app   (or command_center/run.sh)

Starlette + uvicorn (already in the venv), hand-rolled SPA in static/. Serves
on 0.0.0.0:8600 — laptop, LAN, and the phone over Tailscale. DASHBOARD_PASSWORD
is mandatory; every /api route (except login) requires the signed cookie.

Design + invariants: docs/command-center-v2.md. Publishing/posting is the ONLY
gated action; it goes through the ONE shared publishing paths and always sits
behind an explicit confirm in the UI. No bypass flag exists — do not add one.
"""
import os
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

# Import order matters: command_center.db patches shared.db._conn with the
# connection pool, so it must load before anything touches the DB.
from command_center import auth, db  # noqa: F401
from command_center.api import beliefs, media, ops, runs, system

STATIC = Path(__file__).parent / "static"
PORT = int(os.environ.get("CC_PORT", "8600"))


async def login(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not auth.password_ok(data.get("password")):
        return JSONResponse({"ok": False, "error": "wrong password"}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=30 * 24 * 3600,
                    httponly=True, samesite="lax")
    return resp


async def index(request):
    return FileResponse(STATIC / "index.html")


async def asset(request):
    name = request.path_params["name"]
    p = (STATIC / name).resolve()
    if not p.is_file() or p.parent != STATIC.resolve():
        return JSONResponse({"error": "not found"}, status_code=404)
    # `no-cache` = revalidate every time, NOT "never cache": FileResponse still sends
    # an ETag, so an unchanged file is a 304 and costs nothing. Without this the
    # browser heuristically caches app.js and silently serves the previous build —
    # a UI change ships to the server and isn't there in the tab. There is no
    # bundler/hash step to bust the URL, so the header is the whole mechanism.
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path != "/api/login":
            if not auth.token_ok(request.cookies.get(auth.COOKIE)):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


api_routes = (system.routes + runs.routes + media.routes + ops.routes
              + beliefs.routes)

app = Starlette(routes=[
    Route("/api/login", login, methods=["POST"]),
    Mount("/api", routes=api_routes),
    Route("/assets/{name}", asset, methods=["GET"]),
    Route("/", index, methods=["GET"]),
], middleware=[Middleware(AuthMiddleware)])


def main():
    if not os.environ.get("DASHBOARD_PASSWORD"):
        print("Refusing to start: DASHBOARD_PASSWORD is not set.", file=sys.stderr)
        sys.exit(1)
    db.prewarm()   # dial pool connections in the background before first use
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
