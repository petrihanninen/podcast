import json
import logging
import re
import time
import uuid

from podcast.database import get_session
from podcast.services.claude_client import get_client
from podcast.models import Episode, PodcastSettings

logger = logging.getLogger(__name__)

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
    """Generate a two-host conversational transcript using Claude API. Returns metrics dict."""
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

    logger.info("Generating transcript for episode %s", episode_id)

    # Target 4000 words for ~20 min episode
    word_target = 4000
    duration = "15-20"

    system = TRANSCRIPT_SYSTEM_PROMPT.format(
        host_a=host_a, host_b=host_b, word_target=word_target, duration=duration
    )

    client = get_client()

    # Truncate research notes to ~12k chars (~3k tokens) to stay within rate limits
    notes = research_notes or "No research notes available."
    if len(notes) > 12000:
        notes = notes[:12000] + "\n\n[...truncated]"

    user_message = f"""Write a podcast episode transcript about the following topic.

Topic: {topic}

Research notes:
{notes}

The two hosts are {host_a} and {host_b}. Remember to output ONLY the JSON array."""

    t0 = time.monotonic()
    
    model = 'claude-sonnet-4-20250514'
    
    response = await client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    api_duration = time.monotonic() - t0

    # Extract text
    transcript_text = ""
    for block in response.content:
        if block.type == "text":
            transcript_text += block.text

    # Validate it's valid JSON
    transcript_text = transcript_text.strip()
    # Handle markdown code blocks if Claude wraps it
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

    # Save results
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        episode.transcript = json.dumps(segments)

    word_count = sum(len(seg["text"].split()) for seg in segments)
    metrics = {
        "model": model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
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
