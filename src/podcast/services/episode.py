import logging
import os
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from podcast.config import settings
from podcast.models import Episode, Job
from podcast.services.claude_client import get_client

logger = logging.getLogger(__name__)


async def generate_title_from_topic(topic: str) -> str:
    """Generate a short podcast episode title from the topic using Claude."""
    client = get_client()
    try:
        response = await client.messages.create(
            model="claude-haiku-4-20250414",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"Generate a short, catchy podcast episode title (max 8 words) for this topic. Output ONLY the title, no quotes or punctuation unless part of the title.\n\nTopic: {topic}",
            }],
        )
        title = response.content[0].text.strip().strip('"\'')
        return title[:200] if title else topic[:100]
    except Exception:
        logger.warning("Failed to generate title from topic, using fallback", exc_info=True)
        return topic[:100] if len(topic) > 100 else topic


async def create_episode(
    db: AsyncSession,
    topic: str,
    title: str | None = None,
    description: str | None = None,
    target_length_minutes: int = 30,
    research_model: str | None = None,
    transcript_model: str | None = None,
) -> Episode:
    """Create a new episode and enqueue the first pipeline job."""
    if not title:
        title = await generate_title_from_topic(topic)

    episode = Episode(
        title=title,
        topic=topic,
        description=description,
        target_length_minutes=target_length_minutes,
        status="pending",
        research_model=research_model,
        transcript_model=transcript_model,
    )
    db.add(episode)
    await db.flush()

    job = Job(episode_id=episode.id, step="research", status="pending")
    db.add(job)

    return episode


async def list_episodes(db: AsyncSession) -> list[Episode]:
    result = await db.execute(
        select(Episode)
        .options(selectinload(Episode.jobs))
        .order_by(Episode.created_at.desc())
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
