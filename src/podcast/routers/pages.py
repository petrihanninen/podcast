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


# Register template globals
templates.env.globals["status_badge"] = _status_badge
templates.env.globals["status_label"] = _status_label
templates.env.globals["format_duration"] = _format_duration


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
