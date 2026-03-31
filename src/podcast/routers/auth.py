"""Auth routes: login flow, token verification, session management."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

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


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    """Render the login page which auto-triggers Shoo sign-in via JS."""
    # If already authenticated, skip straight to destination
    user = get_current_user(request)
    if user:
        return RedirectResponse(url=next, status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "next_url": next}
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
        secure=request.url.scheme == "https",
        path="/",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """Clear the session cookie."""
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_class=HTMLResponse)
async def me_page(request: Request):
    """Temporary page to view one's pairwise_sub after login.

    Delete this route after grabbing your sub for the ALLOWED_SUB env var.
    """
    # No server-side auth check — this is a setup page used to discover your
    # pairwise_sub *before* ALLOWED_SUB is configured.  The template shows
    # the Shoo identity from client-side localStorage (or a sign-in link).
    return templates.TemplateResponse("auth_me.html", {"request": request})
