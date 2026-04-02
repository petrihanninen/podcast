import json
import logging
import re
import time
import uuid

import httpx

from podcast.config import settings
from podcast.database import get_session
from podcast.models import Episode, PodcastSettings

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# Transcript config scaled by target episode length
TRANSCRIPT_LENGTH_CONFIG = {
    15: {"word_target": 2000, "duration": "12-15", "notes_truncation": 8000, "max_tokens": 8192},
    30: {"word_target": 4000, "duration": "25-30", "notes_truncation": 12000, "max_tokens": 8192},
    60: {"word_target": 8000, "duration": "55-60", "notes_truncation": 24000, "max_tokens": 16384},
    120: {"word_target": 16000, "duration": "110-120", "notes_truncation": 40000, "max_tokens": 32768},
}

DEFAULT_TONE_NOTES: list[str] = [
    "Make it feel like a real conversation between two knowledgeable friends",
    'Include natural interjections ("Right!", "That\'s fascinating", "Wait, really?")',
    "Add humor where appropriate — a witty aside or funny observation",
    "Build a clear narrative arc: hook → context → deep dive → implications → takeaway",
    "Each segment should be 1-4 sentences (natural speaking length)",
    "Make sure the listener learns something genuinely interesting and useful",
]

TRANSCRIPT_SYSTEM_PROMPT = """You are a podcast script writer. You write engaging, natural-sounding \
conversational transcripts between two podcast hosts.

Your output MUST be a JSON array of dialogue segments. Each segment is an object with:
- "speaker": the host's name (exactly as provided)
- "text": what they say (natural speech, not written prose)

Guidelines for the conversation:
- {{host_a}} tends to introduce topics and provide structure
- {{host_b}} asks great questions, plays devil's advocate, and adds surprising perspectives
{tone_notes}\
- Target {{word_target}} words total (roughly {{duration}} minutes at speaking pace)
- Don't use stage directions or descriptions — only spoken dialogue

Output ONLY the JSON array, no other text."""


def _build_system_prompt(
    host_a: str,
    host_b: str,
    word_target: int,
    duration: str,
    tone_notes: list[str] | None = None,
) -> str:
    """Assemble the transcript system prompt with customisable tone notes."""
    notes = tone_notes if tone_notes is not None else DEFAULT_TONE_NOTES
    tone_lines = "".join(f"- {note}\n" for note in notes)
    template = TRANSCRIPT_SYSTEM_PROMPT.format(tone_notes=tone_lines)
    return template.format(
        host_a=host_a, host_b=host_b, word_target=word_target, duration=duration
    )


def _repair_json(text: str) -> str:
    """Attempt common JSON fixes for LLM output."""
    # Remove trailing commas before ] or }
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # Remove any non-JSON text before the first [ or after the last ]
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text


def _parse_json_with_repair(text: str) -> list:
    """Parse JSON, attempting repairs on failure."""
    # First: try parsing as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        original_error = exc
        logger.warning("Initial JSON parse failed: %s — attempting repair", exc)

    # Second: try common fixes
    try:
        repaired = _repair_json(text)
        return json.loads(repaired)
    except json.JSONDecodeError:
        logger.warning("Repaired JSON still invalid — re-raising original error")

    raise original_error


async def generate_transcript(episode_id: uuid.UUID) -> dict:
    """Generate a two-host conversational transcript using DeepSeek API. Returns metrics dict."""
    # Read episode data and settings
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")

        podcast_settings = await db.get(PodcastSettings, 1)
        host_a = podcast_settings.host_a_name if podcast_settings else "Alex"
        host_b = podcast_settings.host_b_name if podcast_settings else "Sam"
        topic = episode.topic
        research_notes = episode.research_notes
        target_length = episode.target_length_minutes

        # Load custom tone notes (JSON string → list), fall back to defaults
        tone_notes = None
        if podcast_settings and podcast_settings.transcript_tone_notes:
            try:
                parsed = json.loads(podcast_settings.transcript_tone_notes)
                if isinstance(parsed, list):
                    tone_notes = parsed
            except (json.JSONDecodeError, TypeError):
                pass

    logger.info("Generating transcript for episode %s via DeepSeek", episode_id)

    config = TRANSCRIPT_LENGTH_CONFIG.get(target_length, TRANSCRIPT_LENGTH_CONFIG[30])
    word_target = config["word_target"]
    duration = config["duration"]

    system = _build_system_prompt(
        host_a=host_a,
        host_b=host_b,
        word_target=word_target,
        duration=duration,
        tone_notes=tone_notes,
    )

    # Truncate research notes based on target length
    notes = research_notes or "No research notes available."
    notes_truncation = config["notes_truncation"]
    if len(notes) > notes_truncation:
        notes = notes[:notes_truncation] + "\n\n[...truncated]"

    user_message = f"""Write a podcast episode transcript about the following topic.

Topic: {topic}

Research notes:
{notes}

The two hosts are {host_a} and {host_b}. Remember to output ONLY the JSON array."""

    api_key = settings.deepseek_api_key
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")

    t0 = time.monotonic()

    # Call DeepSeek chat completions API (OpenAI-compatible format)
    async with httpx.AsyncClient(
        base_url=DEEPSEEK_BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(300.0, connect=30.0),
    ) as client:
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": config["max_tokens"],
            "temperature": 1.0,
            "stream": False,
        }

        # Retry with exponential backoff (similar to previous Anthropic client behaviour)
        last_error = None
        for attempt in range(5):
            try:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code == 429:
                    # Rate limited — back off
                    wait = min(2 ** attempt * 2, 60)
                    logger.warning(
                        "DeepSeek rate limited (attempt %d/5), retrying in %ds",
                        attempt + 1,
                        wait,
                    )
                    import asyncio
                    await asyncio.sleep(wait)
                elif exc.response.status_code >= 500:
                    wait = min(2 ** attempt * 2, 60)
                    logger.warning(
                        "DeepSeek server error %d (attempt %d/5), retrying in %ds",
                        exc.response.status_code,
                        attempt + 1,
                        wait,
                    )
                    import asyncio
                    await asyncio.sleep(wait)
                else:
                    raise
            except httpx.TimeoutException as exc:
                last_error = exc
                wait = min(2 ** attempt * 2, 60)
                logger.warning(
                    "DeepSeek request timed out (attempt %d/5), retrying in %ds",
                    attempt + 1,
                    wait,
                )
                import asyncio
                await asyncio.sleep(wait)
        else:
            raise RuntimeError(
                f"DeepSeek API failed after 5 attempts: {last_error}"
            ) from last_error

    api_duration = time.monotonic() - t0
    data = response.json()

    # Extract text from OpenAI-compatible response
    transcript_text = data["choices"][0]["message"]["content"]

    # Parse usage stats
    usage = data.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    # Validate it's valid JSON
    transcript_text = transcript_text.strip()
    # Handle markdown code blocks if model wraps it
    if transcript_text.startswith("```"):
        lines = transcript_text.split("\n")
        # Remove first and last lines (``` markers)
        lines = [l for l in lines if not l.strip().startswith("```")]
        transcript_text = "\n".join(lines)

    segments = _parse_json_with_repair(transcript_text)
    if not isinstance(segments, list) or len(segments) == 0:
        raise RuntimeError("Invalid transcript format: expected non-empty JSON array")

    # Validate structure
    for seg in segments:
        if "speaker" not in seg or "text" not in seg:
            raise RuntimeError(f"Invalid segment format: {seg}")

    # Save transcript
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        episode.transcript = json.dumps(segments)

    # Generate a refined title based on the actual transcript content
    try:
        title_response = await client.messages.create(
            model="claude-haiku-4-20250414",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"Based on this podcast transcript, generate a short, catchy episode title (max 8 words). Output ONLY the title, no quotes.\n\nTopic: {topic}\n\nTranscript excerpt:\n{transcript_text[:3000]}",
            }],
        )
        new_title = title_response.content[0].text.strip().strip('"\'')
        if new_title:
            async with get_session() as db:
                episode = await db.get(Episode, episode_id)
                episode.title = new_title[:200]
            logger.info("Refined title for episode %s: %s", episode_id, new_title)
    except Exception:
        logger.warning("Failed to refine episode title, keeping original", exc_info=True)

    word_count = sum(len(seg["text"].split()) for seg in segments)
    metrics = {
        "model": DEEPSEEK_MODEL,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_seconds": round(api_duration, 2),
        "segment_count": len(segments),
        "word_count": word_count,
    }
    logger.info(
        "Transcript generated for episode %s: %d segments, %d words, %d in/%d out tokens, %.1fs",
        episode_id,
        len(segments),
        word_count,
        metrics["input_tokens"],
        metrics["output_tokens"],
        api_duration,
    )
    return metrics
