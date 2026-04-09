import json
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from podcast.auth import require_auth_page
from podcast.database import get_db
from podcast.models import Episode, PodcastSettings
from podcast.services.episode import create_episode, get_episode, list_episodes
from podcast.services.tts import get_tts_progress as _read_tts_progress
from podcast.services.llm_providers import get_all_model_pricing

# Pricing pulled dynamically from provider registry
_MODEL_PRICING = get_all_model_pricing()
# Fallback pricing (Claude Sonnet 4 rates)
_DEFAULT_PRICING = {"input": 3.0, "output": 15.0}

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


def _get_tts_progress(episode) -> dict | None:
    """Get TTS progress for an episode, if generating audio."""
    if episode.status != "generating_audio":
        return None
    progress = _read_tts_progress(episode.id)
    if not progress:
        return None
    # Add formatted audio duration for template convenience
    total_secs = int(progress["audio_duration_seconds"])
    minutes = total_secs // 60
    secs = total_secs % 60
    progress["audio_duration_formatted"] = f"{minutes}:{secs:02d}"
    return progress


# Register template globals
templates.env.globals["status_badge"] = _status_badge
templates.env.globals["status_label"] = _status_label
templates.env.globals["format_duration"] = _format_duration
templates.env.globals["format_file_size"] = _format_file_size
templates.env.globals["build_pipeline_info"] = _build_pipeline_info
templates.env.globals["get_current_step_index"] = _get_current_step_index
templates.env.globals["get_tts_progress"] = _get_tts_progress


@router.get("/shoo/callback", response_class=HTMLResponse)
async def shoo_callback(request: Request):
    """Callback page for Shoo OAuth — shoo.js handles the code exchange."""
    return templates.TemplateResponse(request, "auth_callback.html")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    episodes = await list_episodes(db)
    return templates.TemplateResponse(
        request, "index.html", context={"episodes": episodes}
    )


@router.get("/episodes/new", response_class=HTMLResponse)
async def new_episode_page(request: Request, _user: str = Depends(require_auth_page)):
    return templates.TemplateResponse(request, "episode_new.html")


@router.post("/episodes/new")
async def new_episode_submit(request: Request, db: AsyncSession = Depends(get_db), _user: str = Depends(require_auth_page)):
    form = await request.form()
    topic = form.get("topic", "").strip()
    title = form.get("title", "").strip() or None

    # Parse and validate target length
    try:
        target_length = int(form.get("target_length_minutes", "30"))
    except (TypeError, ValueError):
        target_length = 30
    if target_length not in (15, 30, 60, 120):
        target_length = 30

    if not topic:
        return templates.TemplateResponse(
            request,
            "episode_new.html",
            context={"error": "Topic is required"},
        )
    episode = await create_episode(
        db, topic, title,
        target_length_minutes=target_length,
    )
    await db.commit()
    return RedirectResponse(url=f"/episodes/{episode.id}", status_code=303)


@router.get("/episodes/{episode_id}", response_class=HTMLResponse)
async def episode_detail(
    request: Request, episode_id: uuid.UUID, db: AsyncSession = Depends(get_db),
    _user: str = Depends(require_auth_page),
):
    episode = await get_episode(db, episode_id)
    if not episode:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        request, "episode_detail.html", context={"episode": episode}
    )


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, _user: str = Depends(require_auth_page)):
    return templates.TemplateResponse(request, "logs.html")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db), _user: str = Depends(require_auth_page)):
    from podcast.services.transcript import DEFAULT_TONE_NOTES

    s = await db.get(PodcastSettings, 1)
    if not s:
        s = PodcastSettings()
        db.add(s)
        await db.flush()

    # Parse stored tone notes (JSON string → list), fall back to defaults
    tone_notes = list(DEFAULT_TONE_NOTES)
    if s.transcript_tone_notes:
        try:
            parsed = json.loads(s.transcript_tone_notes)
            if isinstance(parsed, list):
                tone_notes = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    return templates.TemplateResponse(
        request, "settings.html", context={"settings": s, "tone_notes": tone_notes}
    )


@router.post("/settings")
async def settings_submit(request: Request, db: AsyncSession = Depends(get_db), _user: str = Depends(require_auth_page)):
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


def _calc_cost(input_tokens: int, output_tokens: int, model: str = "") -> float:
    pricing = _MODEL_PRICING.get(model, _DEFAULT_PRICING)
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


@router.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request, db: AsyncSession = Depends(get_db), _user: str = Depends(require_auth_page)):
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

        # Accumulate per-job cost using per-model pricing
        for job in ep.jobs:
            if job.status != "completed" or not job.metrics_json:
                continue
            m = json.loads(job.metrics_json) if job.metrics_json else {}
            in_t = m.get("input_tokens", 0)
            out_t = m.get("output_tokens", 0)
            model_name = m.get("model", "")
            row["total_cost"] += _calc_cost(in_t, out_t, model_name)
        totals["total_cost"] += row["total_cost"]
        totals["total_generation_seconds"] += row["total_duration_seconds"]

        if ep.audio_duration_seconds:
            totals["total_audio_seconds"] += ep.audio_duration_seconds

        episode_rows.append(row)

    return templates.TemplateResponse(
        request, "metrics.html", context={"totals": totals, "episodes": episode_rows}
    )
