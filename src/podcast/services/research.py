import logging
import time
import uuid

from podcast.database import get_session
from podcast.services.claude_client import get_client
from podcast.models import Episode

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT_TEMPLATE = """You are a podcast research assistant. Given a topic, produce comprehensive \
research notes that will be used to write a podcast episode transcript.

Your research should include:
- Key facts and background information
- Interesting angles and perspectives
- Recent developments and current state
- Common misconceptions or surprising findings
- Potential discussion points and debate areas
- Relevant examples, case studies, or anecdotes

Be thorough but organized. Use clear headings and bullet points. \
The research should provide enough material for a {duration_description} conversational podcast episode."""

# Research config scaled by target episode length
RESEARCH_LENGTH_CONFIG = {
    15: {"duration_description": "10-15 minute", "max_tokens": 4096, "max_uses": 5},
    30: {"duration_description": "25-30 minute", "max_tokens": 8192, "max_uses": 10},
    60: {"duration_description": "55-60 minute", "max_tokens": 12000, "max_uses": 15},
    120: {"duration_description": "2-hour", "max_tokens": 16000, "max_uses": 20},
}


async def run_research(episode_id: uuid.UUID) -> dict:
    """Research a topic using Claude API with web search. Returns metrics dict."""
    # Read episode data
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")
        topic = episode.topic
        target_length = episode.target_length_minutes

    logger.info("Researching topic for episode %s: %s", episode_id, topic[:100])

    config = RESEARCH_LENGTH_CONFIG.get(target_length, RESEARCH_LENGTH_CONFIG[30])
    system_prompt = RESEARCH_SYSTEM_PROMPT_TEMPLATE.format(
        duration_description=config["duration_description"],
    )

    client = get_client()
    model = 'claude-sonnet-4-20250514'

    t0 = time.monotonic()
    response = await client.messages.create(
        model=model,
        max_tokens=config["max_tokens"],
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": config["max_uses"]}],
        messages=[
            {
                "role": "user",
                "content": f"Research the following topic thoroughly:\n\n{topic}",
            }
        ],
    )
    duration = time.monotonic() - t0

    # Extract text from response
    research_text = ""
    for block in response.content:
        if block.type == "text":
            research_text += block.text

    if not research_text:
        raise RuntimeError("No research content generated")

    # Save results
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        episode.research_notes = research_text

    metrics = {
        "model": model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "duration_seconds": round(duration, 2),
        "output_chars": len(research_text),
    }
    logger.info(
        "Research complete for episode %s (%d chars, %d in/%d out tokens, %.1fs)",
        episode_id,
        len(research_text),
        metrics["input_tokens"],
        metrics["output_tokens"],
        duration,
    )
    return metrics
