import json
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from podcast.database import get_db
from podcast.models import Episode, PodcastSettings
from podcast.services.episode import create_episode, get_episode, list_episodes

# Claude Sonnet 4 pricing (per million tokens)
COST_PER_M_INPUT = 3.0
COST_PER_M_OUTPUT = 15.0

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


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse("logs.html", {"request": request})


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


def _calc_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * COST_PER_M_INPUT + output_tokens * COST_PER_M_OUTPUT) / 1_000_000


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Episode)
        .options(selectinload(Episode.jobs))
        .order_by(Episode.created_at.desc())
    )
    episodes = result.scalars().all()

    episode_rows = []
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

        row = {
            "id": str(ep.id),
            "title": ep.title,
            "status": ep.status,
            "episode_number": ep.episode_number,
            "audio_duration_seconds": ep.audio_duration_seconds,
            "audio_size_bytes": ep.audio_size_bytes,
            "created_at": ep.created_at,
            "steps": {},
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
            "total_duration_seconds": 0.0,
        }

        for job in ep.jobs:
            if job.status != "completed":
                if job.started_at and job.completed_at:
                    wall = (job.completed_at - job.started_at).total_seconds()
                    row["steps"][job.step] = {"wall_seconds": round(wall, 2)}
                    row["total_duration_seconds"] += wall
                continue

            metrics = json.loads(job.metrics_json) if job.metrics_json else {}
            step_data = dict(metrics)

            if job.started_at and job.completed_at:
                wall = (job.completed_at - job.started_at).total_seconds()
                step_data["wall_seconds"] = round(wall, 2)
                row["total_duration_seconds"] += wall

            row["steps"][job.step] = step_data

            input_t = metrics.get("input_tokens", 0)
            output_t = metrics.get("output_tokens", 0)
            row["total_input_tokens"] += input_t
            row["total_output_tokens"] += output_t
            totals["total_input_tokens"] += input_t
            totals["total_output_tokens"] += output_t

            if job.step == "tts":
                totals["total_tts_seconds"] += metrics.get("duration_seconds", 0)

        row["total_cost"] = _calc_cost(row["total_input_tokens"], row["total_output_tokens"])
        totals["total_cost"] += row["total_cost"]
        totals["total_generation_seconds"] += row["total_duration_seconds"]

        if ep.audio_duration_seconds:
            totals["total_audio_seconds"] += ep.audio_duration_seconds

        episode_rows.append(row)

    return templates.TemplateResponse(
        "metrics.html",
        {"request": request, "totals": totals, "episodes": episode_rows},
    )
