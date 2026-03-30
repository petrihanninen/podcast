"""
Background worker that polls the jobs table and executes pipeline steps.

Run with: python -m podcast.worker
"""

import asyncio
import json
import logging
import signal
from datetime import datetime, timezone

from sqlalchemy import select

from podcast.database import get_session
from podcast.models import Episode, Job
from podcast.services.encoder import encode_mp3
from podcast.services.research import run_research
from podcast.services.transcript import generate_transcript
from podcast.services.tts import synthesize_speech

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STEP_HANDLERS = {
    "research": run_research,
    "transcript": generate_transcript,
    "tts": synthesize_speech,
    "encode": encode_mp3,
}

NEXT_STEP = {
    "research": "transcript",
    "transcript": "tts",
    "tts": "encode",
    "encode": None,
}

EPISODE_STATUS_MAP = {
    "research": "researching",
    "transcript": "writing_transcript",
    "tts": "generating_audio",
    "encode": "encoding",
}

POLL_INTERVAL = 10  # seconds

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Received signal %s, shutting down gracefully...", signum)
    _shutdown = True


async def process_job(job_id, episode_id, step):
    """Execute a single job step. Returns metrics dict or None."""
    handler = STEP_HANDLERS.get(step)
    if not handler:
        raise ValueError(f"Unknown step: {step}")

    logger.info("Processing job %s: step=%s, episode=%s", job_id, step, episode_id)
    result = await handler(episode_id)
    return result if isinstance(result, dict) else None


async def poll_loop():
    """Main loop: pick up pending jobs and process them."""
    logger.info("Worker started, polling every %ds", POLL_INTERVAL)

    while not _shutdown:
        try:
            # Pick up the next pending job
            job_id = None
            episode_id = None
            step = None

            async with get_session() as db:
                result = await db.execute(
                    select(Job)
                    .where(Job.status == "pending")
                    .order_by(Job.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                job = result.scalar_one_or_none()

                if job is None:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # Capture IDs before session closes
                job_id = job.id
                episode_id = job.episode_id
                step = job.step

                # Mark as running
                job.status = "running"
                job.started_at = datetime.now(timezone.utc)
                job.attempts += 1

                # Update episode status
                episode = await db.get(Episode, episode_id)
                if episode:
                    episode.status = EPISODE_STATUS_MAP.get(step, episode.status)

            # Process outside the DB session to avoid long-held transactions
            try:
                metrics = await process_job(job_id, episode_id, step)

                # Mark job complete
                async with get_session() as db:
                    job_record = await db.get(Job, job_id)
                    job_record.status = "completed"
                    job_record.completed_at = datetime.now(timezone.utc)
                    if metrics:
                        job_record.metrics_json = json.dumps(metrics)

                    # Enqueue next step or mark as ready
                    next_step = NEXT_STEP.get(step)
                    episode = await db.get(Episode, episode_id)

                    if next_step:
                        new_job = Job(
                            episode_id=episode_id,
                            step=next_step,
                            status="pending",
                        )
                        db.add(new_job)
                        logger.info("Enqueued next step: %s for episode %s", next_step, episode_id)
                    else:
                        # Pipeline complete
                        episode.status = "ready"
                        episode.published_at = datetime.now(timezone.utc)
                        logger.info("Episode %s is ready!", episode_id)

            except Exception as e:
                logger.exception("Job %s failed: %s", job_id, e)
                async with get_session() as db:
                    job_record = await db.get(Job, job_id)
                    job_record.status = "failed"
                    job_record.error_message = str(e)

                    episode = await db.get(Episode, episode_id)
                    episode.status = "failed"
                    episode.error_message = str(e)
                    episode.failed_step = step

        except Exception as e:
            logger.exception("Unexpected error in poll loop: %s", e)
            await asyncio.sleep(POLL_INTERVAL)

    logger.info("Worker shut down.")


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    asyncio.run(poll_loop())


if __name__ == "__main__":
    main()
