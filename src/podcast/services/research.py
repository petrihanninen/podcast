import logging
import time
import uuid

from podcast.database import get_session
from podcast.models import Episode
from podcast.services.llm_providers import complete, get_research_model

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
    15: {"duration_description": "10-15 minute", "max_tokens": 4096},
    30: {"duration_description": "25-30 minute", "max_tokens": 8192},
    60: {"duration_description": "55-60 minute", "max_tokens": 12000},
    120: {"duration_description": "2-hour", "max_tokens": 16000},
}


async def run_research(episode_id: uuid.UUID) -> dict:
    """Research a topic using the configured LLM provider. Returns metrics dict."""
    # Read episode data
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")
        topic = episode.topic
        model_key = episode.research_model
        target_length = episode.target_length_minutes

    model_info = get_research_model(model_key)

    config = RESEARCH_LENGTH_CONFIG.get(target_length, RESEARCH_LENGTH_CONFIG[30])
    system_prompt = RESEARCH_SYSTEM_PROMPT_TEMPLATE.format(
        duration_description=config["duration_description"],
    )

    logger.info(
        "Researching topic for episode %s via %s (%s): %s",
        episode_id,
        model_info.display_name,
        model_info.model_id,
        topic[:100],
    )

    t0 = time.monotonic()
    response = await complete(
        model_info,
        system=system_prompt,
        user_message=f"Research the following topic thoroughly:\n\n{topic}",
        max_tokens=config["max_tokens"],
        use_web_search=True,
    )
    duration = time.monotonic() - t0

    if not response.text:
        raise RuntimeError("No research content generated")

    # Save results
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        episode.research_notes = response.text

    metrics = {
        "model": response.model,
        "provider": model_info.provider,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "duration_seconds": round(duration, 2),
        "output_chars": len(response.text),
    }
    logger.info(
        "Research complete for episode %s (%d chars, %d in/%d out tokens, %.1fs)",
        episode_id,
        len(response.text),
        metrics["input_tokens"],
        metrics["output_tokens"],
        duration,
    )
    return metrics
