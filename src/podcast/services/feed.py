from feedgen.feed import FeedGenerator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from podcast.config import settings
from podcast.models import Episode, PodcastSettings


def _format_duration(seconds: int) -> str:
    """Format seconds as HH:MM:SS for iTunes duration."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


async def generate_feed(db: AsyncSession) -> str:
    """Generate a podcast-compatible RSS feed."""
    podcast_settings = await db.get(PodcastSettings, 1)
    if not podcast_settings:
        podcast_settings = PodcastSettings()

    base = settings.base_url.rstrip("/")

    fg = FeedGenerator()
    fg.load_extension("podcast")

    # Channel-level metadata
    fg.title(podcast_settings.title)
    fg.description(podcast_settings.description)
    fg.link(href=f"{base}/feed.xml", rel="self")
    fg.link(href=base, rel="alternate")
    fg.language(podcast_settings.language)
    fg.generator("Podcast Generator")

    # iTunes metadata
    fg.podcast.itunes_author(podcast_settings.author)
    fg.podcast.itunes_summary(podcast_settings.description)
    fg.podcast.itunes_category("Technology")
    fg.podcast.itunes_explicit("no")

    image_url = podcast_settings.image_url or f"{base}/static/til.png"
    fg.podcast.itunes_image(image_url)

    # Episodes
    result = await db.execute(
        select(Episode)
        .where(Episode.status == "ready")
        .where(Episode.audio_filename.isnot(None))
        .order_by(Episode.published_at.desc())
    )
    episodes = result.scalars().all()

    for ep in episodes:
        fe = fg.add_entry()
        fe.id(str(ep.id))
        fe.title(ep.title)
        fe.description(ep.description or ep.topic)
        fe.published(ep.published_at)

        audio_url = f"{base}/audio/{ep.audio_filename}"
        fe.enclosure(audio_url, str(ep.audio_size_bytes or 0), "audio/mpeg")

        if ep.audio_duration_seconds:
            fe.podcast.itunes_duration(_format_duration(ep.audio_duration_seconds))

        if ep.episode_number:
            fe.podcast.itunes_episode(ep.episode_number)

        fe.podcast.itunes_author(podcast_settings.author)

    return fg.rss_str(pretty=True).decode("utf-8")
