from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from podcast.database import get_db
from podcast.services.feed import generate_feed

router = APIRouter()


@router.get("/feed.xml", name="feed")
async def feed(db: AsyncSession = Depends(get_db)):
    xml = await generate_feed(db)
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")
