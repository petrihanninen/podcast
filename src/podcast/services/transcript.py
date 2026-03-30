import json
import logging
import time
import uuid

import httpx

from podcast.config import settings
from podcast.database import get_session
from podcast.models import Episode, PodcastSettings

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

TRANSCRIPT_SYSTEM_PROMPT = """You are a podcast script writer. You write engaging, natural-sounding \
conversational transcripts between two podcast hosts.

Your output MUST be a JSON array of dialogue segments. Each segment is an object with:
- "speaker": the host's name (exactly as provided)
- "text": what they say (natural speech, not written prose)

Guidelines for the conversation:
- Make it feel like a real conversation between two knowledgeable friends
- {host_a} tends to introduce topics and provide structure
- {host_b} asks great questions, plays devil's advocate, and adds surprising perspectives
- Include natural interjections ("Right!", "That's fascinating", "Wait, really?")
- Add humor where appropriate — a witty aside or funny observation
- Build a clear narrative arc: hook → context → deep dive → implications → takeaway
- Target {word_target} words total (roughly {duration} minutes at speaking pace)
- Each segment should be 1-4 sentences (natural speaking length)
- Don't use stage directions or descriptions — only spoken dialogue
- Make sure the listener learns something genuinely interesting and useful

Output ONLY the JSON array, no other text."""


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

    logger.info("Generating transcript for episode %s via DeepSeek", episode_id)

    # Target 4000 words for ~20 min episode
    word_target = 4000
    duration = "15-20"

    system = TRANSCRIPT_SYSTEM_PROMPT.format(
        host_a=host_a, host_b=host_b, word_target=word_target, duration=duration
    )

    # Truncate research notes to ~12k chars (~3k tokens) to stay within rate limits
    notes = research_notes or "No research notes available."
    if len(notes) > 12000:
        notes = notes[:12000] + "\n\n[...truncated]"

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
            "max_tokens": 8192,
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

    segments = json.loads(transcript_text)
    if not isinstance(segments, list) or len(segments) == 0:
        raise RuntimeError("Invalid transcript format: expected non-empty JSON array")

    # Validate structure
    for seg in segments:
        if "speaker" not in seg or "text" not in seg:
            raise RuntimeError(f"Invalid segment format: {seg}")

    # Save results
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        episode.transcript = json.dumps(segments)

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
