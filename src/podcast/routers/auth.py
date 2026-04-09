"""Auth routes: login flow, token verification, session management, registration."""

import logging
import os
import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from podcast.auth import (
    REGISTER_COOKIE,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    create_session_cookie,
    get_current_user,
    verify_shoo_token,
)
from podcast.config import settings
from podcast.database import get_db
from podcast.models import PodcastSettings, User

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


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, token: str = ""):
    """Validate invite token, set registration cookie, redirect to Shoo login."""
    if not token or not settings.register_token or token != settings.register_token:
        return templates.TemplateResponse(
            request, "invalid_invite.html", status_code=403
        )
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.set_cookie(
        REGISTER_COOKIE,
        token,
        max_age=3600,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure,
        path="/",
    )
    return response


@router.post("/verify")
async def verify_token(request: Request, db: AsyncSession = Depends(get_db)):
    """Verify a Shoo id_token, handle registration if needed, and set a session cookie."""
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

    # Look up existing user
    result = await db.execute(select(User).where(User.shoo_sub == sub))
    user = result.scalar_one_or_none()

    if user:
        if not user.enabled:
            return JSONResponse({"error": "Account disabled"}, status_code=403)
        # Existing active user — set session and return
        cookie_value = create_session_cookie(sub)
        response = JSONResponse({"ok": True, "sub": sub})
        response.set_cookie(
            SESSION_COOKIE, cookie_value,
            max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
            secure=_cookie_secure, path="/",
        )
        return response

    # User not found — check for registration token cookie
    register_token = request.cookies.get(REGISTER_COOKIE, "")
    if register_token and settings.register_token and register_token == settings.register_token:
        # Register new user
        try:
            # Check if this is the first user (will become admin)
            count_result = await db.execute(select(func.count(User.id)))
            is_first_user = count_result.scalar_one() == 0

            new_user = User(
                shoo_sub=sub,
                feed_token=secrets.token_urlsafe(32),
                is_admin=is_first_user,
            )
            db.add(new_user)
            await db.flush()

            # Create default podcast settings for the user
            user_settings = PodcastSettings(user_id=new_user.id)
            db.add(user_settings)

            # Create user's audio directory
            user_audio_dir = os.path.join(settings.audio_dir, str(new_user.id))
            os.makedirs(user_audio_dir, exist_ok=True)

            await db.commit()

            logger.info(
                "Registered new user: sub=%s, admin=%s", sub, is_first_user
            )

            cookie_value = create_session_cookie(sub)
            response = JSONResponse({"ok": True, "sub": sub, "registered": True})
            response.set_cookie(
                SESSION_COOKIE, cookie_value,
                max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
                secure=_cookie_secure, path="/",
            )
            # Clear the registration cookie
            response.delete_cookie(REGISTER_COOKIE, path="/")
            return response

        except IntegrityError:
            # Race condition: user was created between our check and insert
            await db.rollback()
            logger.info("User already registered (race condition): sub=%s", sub)
            cookie_value = create_session_cookie(sub)
            response = JSONResponse({"ok": True, "sub": sub})
            response.set_cookie(
                SESSION_COOKIE, cookie_value,
                max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
                secure=_cookie_secure, path="/",
            )
            return response

    # Not registered and no valid invite token — set session anyway
    # so the "not registered" page can show who they are with a logout button
    cookie_value = create_session_cookie(sub)
    response = JSONResponse({"ok": True, "sub": sub})
    response.set_cookie(
        SESSION_COOKIE, cookie_value,
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=_cookie_secure, path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """Clear the session cookie."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
