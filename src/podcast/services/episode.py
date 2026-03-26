import os
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from podcast.config import settings
from podcast.models import Episode, Job


async def create_episode(
    db: AsyncSession, topic: str, title: str | None = None, description: str | None = None
) -> Episode:
    """Create a new episode and enqueue the first pipeline job."""
    if not title:
        title = topic[:100] if len(topic) > 100 else topic

    episode = Episode(title=title, topic=topic, description=description, status="pending")
    db.add(episode)
    await db.flush()

    job = Job(episode_id=episode.id, step="research", status="pending")
    db.add(job)

    return episode


async def list_episodes(db: AsyncSession) -> list[Episode]:
    result = await db.execute(
        select(Episode).order_by(Episode.created_at.desc())
    )
    return list(result.scalars().all())


async def get_episode(db: AsyncSession, episode_id: uuid.UUID) -> Episode | None:
    result = await db.execute(
        select(Episode)
        .where(Episode.id == episode_id)
        .options(selectinload(Episode.jobs))
    )
    return result.scalar_one_or_none()


async def delete_episode(db: AsyncSession, episode_id: uuid.UUID) -> bool:
    episode = await get_episode(db, episode_id)
    if not episode:
        return False

    # Clean up audio files
    if episode.audio_filename:
        audio_path = os.path.join(settings.audio_dir, episode.audio_filename)
        if os.path.exists(audio_path):
            os.remove(audio_path)

    # Clean up segments directory
    segments_dir = os.path.join(settings.audio_dir, "segments", str(episode.id))
    if os.path.isdir(segments_dir):
        import shutil
        shutil.rmtree(segments_dir)

    await db.delete(episode)
    return True


async def retry_episode(db: AsyncSession, episode_id: uuid.UUID) -> Episode | None:
    """Retry a failed episode from its failed step."""
    episode = await get_episode(db, episode_id)
    if not episode or episode.status != "failed":
        return None

    step = episode.failed_step or "research"
    episode.status = "pending"
    episode.error_message = None
    episode.failed_step = None

    job = Job(episode_id=episode.id, step=step, status="pending")
    db.add(job)

    return episode


async def get_next_episode_number(db: AsyncSession) -> int:
    result = await db.execute(select(func.coalesce(func.max(Episode.episode_number), 0)))
    return result.scalar_one() + 1
