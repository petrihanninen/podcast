from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from podcast.database import get_db
from podcast.models import User
from podcast.services.feed import generate_feed

router = APIRouter()


@router.get("/feed/{feed_token}.xml", name="feed")
async def feed(feed_token: str, db: AsyncSession = Depends(get_db)):
    """Serve a user's podcast RSS feed by their unique feed token."""
    result = await db.execute(
        select(User).where(User.feed_token == feed_token, User.enabled == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Feed not found")

    xml = await generate_feed(db, user)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
