import { asc, eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, episodeSources } from "../schema.js";
import { complete, getResearchModel } from "./llm-providers.js";
import { createLogger } from "../log.js";

const log = createLogger("research");

const RESEARCH_SYSTEM_PROMPT_TEMPLATE = `You are a podcast research assistant. Given a topic, produce comprehensive \
research notes that will be used to write a podcast episode transcript.

Use web search to ground the notes in current, reliable sources. Your research should include:
- Key facts and background information
- Interesting angles and perspectives
- Recent developments and current state (with dates)
- Common misconceptions or surprising findings
- Potential discussion points and debate areas
- Relevant examples, case studies, or anecdotes

Be thorough but organized. Use clear headings and bullet points, and mention the source \
of important claims. The research should provide enough material for a {duration_description} \
conversational podcast episode.`;

const MATERIAL_SYSTEM_PROMPT_TEMPLATE = `You are a podcast research assistant. The listener has supplied a brief and \
source material (documents, code, conversation logs, notes). Produce comprehensive research notes that \
will be used to write a podcast episode transcript answering the brief.

Work primarily from the supplied material; it is the subject of the episode. Where the brief asks for \
analysis, advice or evaluation, do that analysis yourself and write down concrete findings, examples and \
recommendations drawn from the material. {web_search_instruction}

The notes should let a script writer who has never seen the material write the episode, so include:
- What the material is and how it fits together
- The key facts, structures, decisions and patterns, with concrete examples quoted or paraphrased
- Interesting angles, tensions, surprises and open questions
- Direct answers to the brief, with specific recommendations where asked
- Potential discussion points for two hosts

If the brief speaks in the first person, it refers to the listener; write the notes about them in the \
third person ("the listener"). Be thorough but organized, with clear headings and bullet points. The \
research should provide enough material for a {duration_description} conversational podcast episode.`;

const RESEARCH_LENGTH_CONFIG: Record<
  number,
  { durationDescription: string; maxTokens: number }
> = {
  15: { durationDescription: "10-15 minute", maxTokens: 6000 },
  30: { durationDescription: "25-30 minute", maxTokens: 10000 },
  60: { durationDescription: "55-60 minute", maxTokens: 16000 },
  120: { durationDescription: "2-hour", maxTokens: 16000 },
};

export async function runResearch(
  episodeId: string
): Promise<Record<string, unknown>> {
  const [episode] = await db
    .select()
    .from(episodes)
    .where(eq(episodes.id, episodeId))
    .limit(1);
  if (!episode) throw new Error(`Episode ${episodeId} not found`);

  const modelInfo = getResearchModel(episode.researchModel);
  const config = RESEARCH_LENGTH_CONFIG[episode.targetLengthMinutes] ??
    RESEARCH_LENGTH_CONFIG[30];

  const sources = await db
    .select()
    .from(episodeSources)
    .where(eq(episodeSources.episodeId, episodeId))
    .orderBy(asc(episodeSources.position));

  let systemPrompt: string;
  let userPrompt: string;
  if (sources.length > 0) {
    systemPrompt = MATERIAL_SYSTEM_PROMPT_TEMPLATE.replace(
      "{duration_description}",
      config.durationDescription
    ).replace(
      "{web_search_instruction}",
      episode.webSearch
        ? "Use web search to add context, definitions and recent developments where it helps, and say which claims come from the web."
        : "Do not assume anything beyond the material and general knowledge."
    );
    const material = sources
      .map((s) => `=== ${s.name} ===\n${s.content}`)
      .join("\n\n");
    userPrompt = `Brief:\n${episode.topic}\n\nSource material (${sources.length} document${sources.length === 1 ? "" : "s"}):\n\n${material}`;
  } else {
    systemPrompt = RESEARCH_SYSTEM_PROMPT_TEMPLATE.replace(
      "{duration_description}",
      config.durationDescription
    );
    userPrompt = `Research the following topic thoroughly:\n\n${episode.topic}`;
  }

  log.info(
    "Researching topic for episode %s via %s (%s, %d sources, web search %s): %s",
    episodeId,
    modelInfo.displayName,
    modelInfo.modelId,
    sources.length,
    episode.webSearch ? "on" : "off",
    episode.topic.slice(0, 100)
  );

  const MAX_EMPTY_RETRIES = 2;
  const t0 = performance.now();
  let response = null;

  for (let attempt = 0; attempt <= MAX_EMPTY_RETRIES; attempt++) {
    response = await complete(modelInfo, {
      system: systemPrompt,
      user: userPrompt,
      maxTokens: config.maxTokens,
      webSearch: episode.webSearch,
    });
    if (response.text) break;
    if (attempt < MAX_EMPTY_RETRIES) {
      const wait = 3 * 2 ** attempt;
      log.warn(
        "Research for episode %s returned empty text (attempt %d/%d, model=%s), retrying in %ds...",
        episodeId,
        attempt + 1,
        MAX_EMPTY_RETRIES + 1,
        modelInfo.modelId,
        wait
      );
      await new Promise((r) => setTimeout(r, wait * 1000));
    }
  }

  const duration = (performance.now() - t0) / 1000;

  if (!response?.text) {
    throw new Error(
      `No research content generated after ${MAX_EMPTY_RETRIES + 1} attempts ` +
        `(model=${modelInfo.modelId}). The API returned 200 OK but the response contained no text output.`
    );
  }

  await db
    .update(episodes)
    .set({ researchNotes: response.text })
    .where(eq(episodes.id, episodeId));

  const metrics = {
    model: response.model,
    provider: modelInfo.provider,
    input_tokens: response.inputTokens,
    output_tokens: response.outputTokens,
    search_queries: response.searchQueries,
    cost_usd: response.costUsd,
    duration_seconds: Math.round(duration * 100) / 100,
    output_chars: response.text.length,
    source_count: sources.length,
  };

  log.info(
    "Research complete for episode %s (%d chars, %d in/%d out tokens, %d searches, $%s, %.1fs)",
    episodeId,
    response.text.length,
    metrics.input_tokens,
    metrics.output_tokens,
    metrics.search_queries,
    metrics.cost_usd.toFixed(4),
    duration
  );

  return metrics;
}
