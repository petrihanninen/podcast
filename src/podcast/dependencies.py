from fastapi import Header, HTTPException

from podcast.config import settings


async def require_password(authorization: str | None = Header(default=None)):
    """Validate password for mutating API endpoints.

    Expects an ``Authorization: Bearer <password>`` header when
    ``api_password`` is configured.  If no password is set in the
    environment the check is skipped (backwards compatible).
    """
    if not settings.api_password:
        return

    if not authorization:
        raise HTTPException(status_code=401, detail="Password required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != settings.api_password:
        raise HTTPException(status_code=401, detail="Invalid password")
