"""Auth routes: login flow, token verification, session management."""

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

from podcast.auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_cookie,
    get_current_user,
    verify_shoo_token,
)
from podcast.config import settings

templates = Jinja2Templates(directory="src/podcast/templates")

router = APIRouter(prefix="/auth")

# Determine cookie secure flag from config rather than per-request scheme,
# so it works correctly behind TLS-terminating reverse proxies.
_cookie_secure = settings.base_url.startswith("https://")


def _safe_redirect_url(next_url: str) -> str:
    """Validate that a redirect target is a relative path (prevent open redirect)."""
    parsed = urlparse(next_url)
    if parsed.netloc or parsed.scheme:
        return "/"
    return next_url


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    """Render the login page which auto-triggers Shoo sign-in via JS."""
    next = _safe_redirect_url(next)
    # If already authenticated, skip straight to destination
    user = get_current_user(request)
    if user:
        return RedirectResponse(url=next, status_code=303)
    return templates.TemplateResponse(
        request, "login.html", context={"next_url": next}
    )


@router.post("/verify")
async def verify_token(request: Request):
    """Verify a Shoo id_token, check authorization, and set a session cookie."""
    body = await request.json()
    token = body.get("token")
    if not token:
        return JSONResponse({"error": "Missing token"}, status_code=400)

    try:
        claims = verify_shoo_token(token)
    except Exception as e:
        logger.warning("Token verification failed: %s", e)
        return JSONResponse({"error": f"Invalid token: {e}"}, status_code=401)

    sub = claims["pairwise_sub"]

    # If allowed_sub is configured, enforce it
    if settings.allowed_sub and sub != settings.allowed_sub:
        return JSONResponse({"error": "Unauthorized user"}, status_code=403)

    # Set session cookie
    cookie_value = create_session_cookie(sub)
    response = JSONResponse({"ok": True, "sub": sub})
    response.set_cookie(
        SESSION_COOKIE,
        cookie_value,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure,
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """Clear the session cookie."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
