"""Shoo authentication: JWT verification, session cookies, FastAPI dependencies."""

import hashlib
import hmac
import time
from urllib.parse import urlparse

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from podcast.config import settings
from podcast.database import get_db
from podcast.models import User

# JWKS client for verifying Shoo id_tokens (ES256 signed)
_jwks_client = jwt.PyJWKClient("https://shoo.dev/.well-known/jwks.json", cache_keys=True)

SESSION_COOKIE = "podcast_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 days
REGISTER_COOKIE = "register_token"


class RequiresLogin(Exception):
    """Raised when an unauthenticated user tries to access a protected page."""

    def __init__(self, next_url: str = "/"):
        self.next_url = next_url


class RequiresRegistration(Exception):
    """Raised when a Shoo-authenticated user is not registered in the app."""
    pass


def _get_origin(url: str) -> str:
    """Extract origin (scheme + host + port) from a URL."""
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port and parsed.port not in (80, 443):
        origin += f":{parsed.port}"
    return origin


def verify_shoo_token(id_token: str) -> dict:
    """Verify a Shoo id_token JWT and return its claims.

    Validates signature (ES256 via JWKS), issuer, and audience.
    """
    signing_key = _jwks_client.get_signing_key_from_jwt(id_token)
    origin = _get_origin(settings.base_url)
    payload = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["ES256"],
        issuer="https://shoo.dev",
        audience=f"origin:{origin}",
    )
    if "pairwise_sub" not in payload:
        raise ValueError("Missing pairwise_sub claim")
    return payload


def create_session_cookie(sub: str) -> str:
    """Create an HMAC-signed session cookie value: sub:expiry:signature."""
    expires = int(time.time()) + SESSION_MAX_AGE
    message = f"{sub}:{expires}"
    sig = hmac.new(
        settings.session_secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return f"{message}:{sig}"


def verify_session_cookie(cookie: str) -> str | None:
    """Verify session cookie and return the sub if valid, else None."""
    try:
        parts = cookie.rsplit(":", 2)
        if len(parts) != 3:
            return None
        sub, expires_str, sig = parts
        message = f"{sub}:{expires_str}"
        expected_sig = hmac.new(
            settings.session_secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        if int(expires_str) < int(time.time()):
            return None
        return sub
    except Exception:
        return None


def get_current_user(request: Request) -> str | None:
    """Read session cookie and return the authenticated sub, or None."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    return verify_session_cookie(cookie)


async def require_auth(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency for API routes — raises 401/403 if not authenticated/registered."""
    sub = get_current_user(request)
    if not sub:
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(select(User).where(User.shoo_sub == sub))
    user = result.scalar_one_or_none()
    if not user or not user.enabled:
        raise HTTPException(status_code=403, detail="Not registered or account disabled")
    return user


async def require_auth_page(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency for page routes — redirects to login or shows not-registered page."""
    sub = get_current_user(request)
    if not sub:
        raise RequiresLogin(next_url=str(request.url.path))
    result = await db.execute(select(User).where(User.shoo_sub == sub))
    user = result.scalar_one_or_none()
    if not user or not user.enabled:
        raise RequiresRegistration()
    return user


async def require_admin(user: User = Depends(require_auth)) -> User:
    """FastAPI dependency for admin-only API routes."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_admin_page(user: User = Depends(require_auth_page)) -> User:
    """FastAPI dependency for admin-only page routes."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
