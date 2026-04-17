import { eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes } from "../schema.js";
import { complete, getResearchModel } from "./llm-providers.js";
import { createLogger } from "../log-handler.js";

const log = createLogger("research");

const RESEARCH_SYSTEM_PROMPT_TEMPLATE = `You are a podcast research assistant. Given a topic, produce comprehensive \
research notes that will be used to write a podcast episode transcript.

Your research should include:
- Key facts and background information
- Interesting angles and perspectives
- Recent developments and current state
- Common misconceptions or surprising findings
- Potential discussion points and debate areas
- Relevant examples, case studies, or anecdotes

Be thorough but organized. Use clear headings and bullet points. \
The research should provide enough material for a {duration_description} conversational podcast episode.`;

const RESEARCH_LENGTH_CONFIG: Record<
  number,
  { durationDescription: string; maxTokens: number }
> = {
  15: { durationDescription: "10-15 minute", maxTokens: 4096 },
  30: { durationDescription: "25-30 minute", maxTokens: 8192 },
  60: { durationDescription: "55-60 minute", maxTokens: 12000 },
  120: { durationDescription: "2-hour", maxTokens: 16000 },
};

export async function runResearch(
  episodeId: string
): Promise<Record<string, unknown>> {
  // Read episode data
  const [episode] = await db
    .select()
    .from(episodes)
    .where(eq(episodes.id, episodeId))
    .limit(1);
  if (!episode) throw new Error(`Episode ${episodeId} not found`);

  const modelInfo = getResearchModel(episode.researchModel);
  const config = RESEARCH_LENGTH_CONFIG[episode.targetLengthMinutes] ??
    RESEARCH_LENGTH_CONFIG[30];

  const systemPrompt = RESEARCH_SYSTEM_PROMPT_TEMPLATE.replace(
    "{duration_description}",
    config.durationDescription
  );

  log.info(
    "Researching topic for episode %s via %s (%s): %s",
    episodeId,
    modelInfo.displayName,
    modelInfo.modelId,
    episode.topic.slice(0, 100)
  );

  const MAX_EMPTY_RETRIES = 2;
  const t0 = performance.now();
  let response = null;

  for (let attempt = 0; attempt <= MAX_EMPTY_RETRIES; attempt++) {
    response = await complete(
      modelInfo,
      systemPrompt,
      `Research the following topic thoroughly:\n\n${episode.topic}`,
      config.maxTokens,
      1.0,
      true
    );
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

  // Save results
  await db
    .update(episodes)
    .set({ researchNotes: response.text })
    .where(eq(episodes.id, episodeId));

  const metrics = {
    model: response.model,
    provider: modelInfo.provider,
    input_tokens: response.inputTokens,
    output_tokens: response.outputTokens,
    duration_seconds: Math.round(duration * 100) / 100,
    output_chars: response.text.length,
  };

  log.info(
    "Research complete for episode %s (%d chars, %d in/%d out tokens, %.1fs)",
    episodeId,
    response.text.length,
    metrics.input_tokens,
    metrics.output_tokens,
    duration
  );

  return metrics;
}
