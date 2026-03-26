import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from podcast.database import get_db
from podcast.models import PodcastSettings
from podcast.schemas import (
    EpisodeCreate,
    EpisodeListItem,
    EpisodeResponse,
    SettingsResponse,
    SettingsUpdate,
)
from podcast.services.episode import (
    create_episode,
    delete_episode,
    get_episode,
    list_episodes,
    retry_episode,
)

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/episodes", response_model=EpisodeResponse)
async def create_episode_endpoint(data: EpisodeCreate, db: AsyncSession = Depends(get_db)):
    episode = await create_episode(db, data.topic, data.title, data.description)
    return episode


@router.get("/episodes", response_model=list[EpisodeListItem])
async def list_episodes_endpoint(db: AsyncSession = Depends(get_db)):
    episodes = await list_episodes(db)
    return episodes


@router.get("/episodes/{episode_id}", response_model=EpisodeResponse)
async def get_episode_endpoint(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    episode = await get_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    return episode


@router.delete("/episodes/{episode_id}")
async def delete_episode_endpoint(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    deleted = await delete_episode(db, episode_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Episode not found")
    return {"status": "deleted"}


@router.post("/episodes/{episode_id}/retry", response_model=EpisodeResponse)
async def retry_episode_endpoint(episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    episode = await retry_episode(db, episode_id)
    if not episode:
        raise HTTPException(status_code=400, detail="Episode not found or not in failed state")
    return episode


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    s = await db.get(PodcastSettings, 1)
    if not s:
        s = PodcastSettings()
        db.add(s)
        await db.flush()
    return s


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    s = await db.get(PodcastSettings, 1)
    if not s:
        s = PodcastSettings()
        db.add(s)
        await db.flush()

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(s, key, value)

    return s
