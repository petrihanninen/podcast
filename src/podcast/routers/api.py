import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from podcast.database import get_db
from podcast.models import Episode, LogEntry, PodcastSettings
from podcast.schemas import (
    EpisodeCreate,
    EpisodeListItem,
    EpisodeResponse,
    LogEntryResponse,
    LogListResponse,
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

# Claude Sonnet 4 pricing (per million tokens)
COST_PER_M_INPUT = 3.0
COST_PER_M_OUTPUT = 15.0

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


@router.get("/logs", response_model=LogListResponse)
async def get_logs(
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 100,
    level: str | None = None,
    source: str | None = None,
    search: str | None = None,
):
    query = select(LogEntry).order_by(LogEntry.timestamp.desc())
    count_query = select(func.count(LogEntry.id))

    if level:
        query = query.where(LogEntry.level == level.upper())
        count_query = count_query.where(LogEntry.level == level.upper())
    if source:
        query = query.where(LogEntry.source == source.lower())
        count_query = count_query.where(LogEntry.source == source.lower())
    if search:
        query = query.where(LogEntry.message.ilike(f"%{search}%"))
        count_query = count_query.where(LogEntry.message.ilike(f"%{search}%"))

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    logs = result.scalars().all()

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    return LogListResponse(
        logs=[LogEntryResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
        has_more=offset + page_size < total,
    )


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


def _calc_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * COST_PER_M_INPUT + output_tokens * COST_PER_M_OUTPUT) / 1_000_000


@router.get("/metrics")
async def get_metrics(db: AsyncSession = Depends(get_db)):
    """Aggregate metrics across all episodes."""
    result = await db.execute(
        select(Episode)
        .options(selectinload(Episode.jobs))
        .order_by(Episode.created_at.desc())
    )
    episodes = result.scalars().all()

    episode_metrics = []
    totals = {
        "episodes": 0,
        "episodes_ready": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cost": 0.0,
        "total_audio_seconds": 0,
        "total_generation_seconds": 0.0,
        "total_tts_seconds": 0.0,
    }

    for ep in episodes:
        totals["episodes"] += 1
        if ep.status == "ready":
            totals["episodes_ready"] += 1

        ep_data = {
            "id": str(ep.id),
            "title": ep.title,
            "status": ep.status,
            "episode_number": ep.episode_number,
            "audio_duration_seconds": ep.audio_duration_seconds,
            "audio_size_bytes": ep.audio_size_bytes,
            "created_at": ep.created_at.isoformat() if ep.created_at else None,
            "steps": {},
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
            "total_duration_seconds": 0.0,
        }

        for job in ep.jobs:
            if job.status != "completed" or not job.metrics_json:
                # Still include timing from started_at/completed_at if available
                if job.started_at and job.completed_at:
                    wall_time = (job.completed_at - job.started_at).total_seconds()
                    ep_data["steps"][job.step] = {"wall_seconds": round(wall_time, 2)}
                    ep_data["total_duration_seconds"] += wall_time
                continue

            metrics = json.loads(job.metrics_json)
            step_data = dict(metrics)

            # Add wall-clock time from DB timestamps
            if job.started_at and job.completed_at:
                wall_time = (job.completed_at - job.started_at).total_seconds()
                step_data["wall_seconds"] = round(wall_time, 2)
                ep_data["total_duration_seconds"] += wall_time

            ep_data["steps"][job.step] = step_data

            # Accumulate token counts for API steps
            input_t = metrics.get("input_tokens", 0)
            output_t = metrics.get("output_tokens", 0)
            ep_data["total_input_tokens"] += input_t
            ep_data["total_output_tokens"] += output_t
            totals["total_input_tokens"] += input_t
            totals["total_output_tokens"] += output_t

            # Accumulate TTS time
            if job.step == "tts":
                totals["total_tts_seconds"] += metrics.get("duration_seconds", 0)

        ep_data["total_cost"] = _calc_cost(
            ep_data["total_input_tokens"], ep_data["total_output_tokens"]
        )
        totals["total_cost"] += ep_data["total_cost"]
        totals["total_generation_seconds"] += ep_data["total_duration_seconds"]

        if ep.audio_duration_seconds:
            totals["total_audio_seconds"] += ep.audio_duration_seconds

        episode_metrics.append(ep_data)

    return {
        "totals": totals,
        "episodes": episode_metrics,
    }
