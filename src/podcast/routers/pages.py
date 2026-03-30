import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from podcast.database import get_db
from podcast.models import PodcastSettings
from podcast.services.episode import create_episode, get_episode, list_episodes

templates = Jinja2Templates(directory="src/podcast/templates")

router = APIRouter()


def _status_badge(status: str) -> str:
    """Map episode status to badge CSS class."""
    mapping = {
        "ready": "badge--success",
        "failed": "badge--error",
        "pending": "badge--info",
    }
    # All in-progress statuses get warning
    return mapping.get(status, "badge--warning")


def _status_label(status: str) -> str:
    """Human-readable status label."""
    mapping = {
        "pending": "Pending",
        "researching": "Researching",
        "writing_transcript": "Writing transcript",
        "generating_audio": "Generating audio",
        "encoding": "Encoding",
        "ready": "Ready",
        "failed": "Failed",
    }
    return mapping.get(status, status.replace("_", " ").title())


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


def _format_file_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return ""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


PIPELINE_STEPS = ["research", "transcript", "tts", "encode"]

STEP_LABELS = {
    "research": "Research",
    "transcript": "Transcript",
    "tts": "Audio",
    "encode": "Encode",
}


def _build_pipeline_info(episode) -> list[dict]:
    """Build ordered pipeline step info from episode jobs."""
    jobs_by_step = {job.step: job for job in (episode.jobs or [])}

    steps = []
    for step_name in PIPELINE_STEPS:
        job = jobs_by_step.get(step_name)
        if job:
            duration = None
            if job.started_at and job.completed_at:
                delta = job.completed_at - job.started_at
                total_secs = int(delta.total_seconds())
                if total_secs >= 60:
                    duration = f"{total_secs // 60}m {total_secs % 60}s"
                else:
                    duration = f"{total_secs}s"
            steps.append({
                "name": step_name,
                "label": STEP_LABELS[step_name],
                "status": job.status,
                "attempts": job.attempts,
                "duration": duration,
            })
        else:
            steps.append({
                "name": step_name,
                "label": STEP_LABELS[step_name],
                "status": "waiting",
                "attempts": 0,
                "duration": None,
            })

    return steps


def _get_current_step_index(episode) -> int:
    """Return 0-based index of the current/completed pipeline step."""
    if episode.status == "ready":
        return len(PIPELINE_STEPS)
    jobs_by_step = {job.step: job for job in (episode.jobs or [])}
    for i, step_name in enumerate(PIPELINE_STEPS):
        job = jobs_by_step.get(step_name)
        if not job or job.status in ("pending", "running"):
            return i
    return len(PIPELINE_STEPS)


# Register template globals
templates.env.globals["status_badge"] = _status_badge
templates.env.globals["status_label"] = _status_label
templates.env.globals["format_duration"] = _format_duration
templates.env.globals["format_file_size"] = _format_file_size
templates.env.globals["build_pipeline_info"] = _build_pipeline_info
templates.env.globals["get_current_step_index"] = _get_current_step_index


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    episodes = await list_episodes(db)
    return templates.TemplateResponse(
        "index.html", {"request": request, "episodes": episodes}
    )


@router.get("/episodes/new", response_class=HTMLResponse)
async def new_episode_page(request: Request):
    return templates.TemplateResponse("episode_new.html", {"request": request})


@router.post("/episodes/new")
async def new_episode_submit(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    topic = form.get("topic", "").strip()
    title = form.get("title", "").strip() or None
    if not topic:
        return templates.TemplateResponse(
            "episode_new.html",
            {"request": request, "error": "Topic is required"},
        )
    episode = await create_episode(db, topic, title)
    return RedirectResponse(url=f"/episodes/{episode.id}", status_code=303)


@router.get("/episodes/{episode_id}", response_class=HTMLResponse)
async def episode_detail(
    request: Request, episode_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    episode = await get_episode(db, episode_id)
    if not episode:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        "episode_detail.html", {"request": request, "episode": episode}
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    s = await db.get(PodcastSettings, 1)
    if not s:
        s = PodcastSettings()
        db.add(s)
        await db.flush()
    return templates.TemplateResponse(
        "settings.html", {"request": request, "settings": s}
    )


@router.post("/settings")
async def settings_submit(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    s = await db.get(PodcastSettings, 1)
    if not s:
        s = PodcastSettings()
        db.add(s)
        await db.flush()

    for field in ["title", "description", "author", "language", "host_a_name", "host_b_name"]:
        value = form.get(field, "").strip()
        if value:
            setattr(s, field, value)

    return RedirectResponse(url="/settings", status_code=303)
