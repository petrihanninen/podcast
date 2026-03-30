import logging
import uuid

from podcast.database import get_session
from podcast.services.claude_client import get_client
from podcast.models import Episode

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are a podcast research assistant. Given a topic, produce comprehensive \
research notes that will be used to write a podcast episode transcript.

Your research should include:
- Key facts and background information
- Interesting angles and perspectives
- Recent developments and current state
- Common misconceptions or surprising findings
- Potential discussion points and debate areas
- Relevant examples, case studies, or anecdotes

Be thorough but organized. Use clear headings and bullet points. \
The research should provide enough material for a 15-30 minute conversational podcast episode."""


async def run_research(episode_id: uuid.UUID) -> None:
    """Research a topic using Claude API with web search."""
    # Read episode data
    async with get_session() as db:
        episode = await db.get(Episode, episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")
        topic = episode.topic

    logger.info("Researching topic for episode %s: %s", episode_id, topic[:100])

    client = get_client()

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=RESEARCH_SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
        messages=[
            {
                "role": "user",
                "content": f"Research the following topic thoroughly:\n\n{topic}",
            }
        ],
    )

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

    logger.info("Research complete for episode %s (%d chars)", episode_id, len(research_text))
