import { eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings } from "../schema.js";
import { getClient } from "./anthropic-client.js";
import { complete, getTranscriptModel } from "./llm-providers.js";
import { createLogger } from "../log-handler.js";

const log = createLogger("transcript");

const TRANSCRIPT_LENGTH_CONFIG: Record<
  number,
  {
    wordTarget: number;
    duration: string;
    notesTruncation: number;
    maxTokens: number;
  }
> = {
  15: { wordTarget: 2000, duration: "12-15", notesTruncation: 8000, maxTokens: 8192 },
  30: { wordTarget: 4000, duration: "25-30", notesTruncation: 12000, maxTokens: 8192 },
  60: { wordTarget: 8000, duration: "55-60", notesTruncation: 24000, maxTokens: 16384 },
  120: { wordTarget: 16000, duration: "110-120", notesTruncation: 40000, maxTokens: 32768 },
};

export const DEFAULT_TONE_NOTES: string[] = [
  "Make it feel like a real conversation between two knowledgeable friends",
  'Include natural interjections ("Right!", "That\'s fascinating", "Wait, really?")',
  "Add humor where appropriate — a witty aside or funny observation",
  "Build a clear narrative arc: hook → context → deep dive → implications → takeaway",
  "Each segment should be 1-4 sentences (natural speaking length)",
  "Make sure the listener learns something genuinely interesting and useful",
];

const TRANSCRIPT_SYSTEM_PROMPT = `You are a podcast script writer. You write engaging, natural-sounding \
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

Output ONLY the JSON array, no other text.`;

function buildSystemPrompt(
  hostA: string,
  hostB: string,
  wordTarget: number,
  duration: string,
  toneNotes?: string[] | null
): string {
  const notes = toneNotes ?? DEFAULT_TONE_NOTES;
  const toneLines = notes.map((n) => `- ${n}\n`).join("");
  let template = TRANSCRIPT_SYSTEM_PROMPT.replace("{tone_notes}", toneLines);
  template = template
    .replace(/\{\{host_a\}\}/g, hostA)
    .replace(/\{\{host_b\}\}/g, hostB)
    .replace(/\{\{word_target\}\}/g, String(wordTarget))
    .replace(/\{\{duration\}\}/g, duration);
  return template;
}

function repairJson(text: string): string {
  // Remove trailing commas before ] or }
  text = text.replace(/,\s*([}\]])/g, "$1");
  // Remove any non-JSON text before the first [ or after the last ]
  const start = text.indexOf("[");
  const end = text.lastIndexOf("]");
  if (start !== -1 && end !== -1 && end > start) {
    text = text.slice(start, end + 1);
  }
  return text;
}

function parseJsonWithRepair(text: string): unknown[] {
  try {
    return JSON.parse(text);
  } catch (originalError) {
    log.warn("Initial JSON parse failed — attempting repair");
  }
  try {
    return JSON.parse(repairJson(text));
  } catch {
    log.warn("Repaired JSON still invalid — re-raising original error");
  }
  throw new Error("Failed to parse transcript JSON");
}

export async function generateTranscript(
  episodeId: string
): Promise<Record<string, unknown>> {
  // Read episode data and settings
  const [episode] = await db
    .select()
    .from(episodes)
    .where(eq(episodes.id, episodeId))
    .limit(1);
  if (!episode) throw new Error(`Episode ${episodeId} not found`);

  const [settings] = await db
    .select()
    .from(podcastSettings)
    .where(eq(podcastSettings.userId, episode.userId))
    .limit(1);

  const hostA = settings?.hostAName ?? "Alex";
  const hostB = settings?.hostBName ?? "Sam";

  let toneNotes: string[] | null = null;
  if (settings?.transcriptToneNotes) {
    try {
      const parsed = JSON.parse(settings.transcriptToneNotes);
      if (Array.isArray(parsed)) toneNotes = parsed;
    } catch {}
  }

  const modelInfo = getTranscriptModel(episode.transcriptModel);
  log.info(
    "Generating transcript for episode %s via %s (%s)",
    episodeId,
    modelInfo.displayName,
    modelInfo.modelId
  );

  const config = TRANSCRIPT_LENGTH_CONFIG[episode.targetLengthMinutes] ??
    TRANSCRIPT_LENGTH_CONFIG[30];

  const system = buildSystemPrompt(
    hostA,
    hostB,
    config.wordTarget,
    config.duration,
    toneNotes
  );

  let notes = episode.researchNotes || "No research notes available.";
  if (notes.length > config.notesTruncation) {
    notes = notes.slice(0, config.notesTruncation) + "\n\n[...truncated]";
  }

  const userMessage = `Write a podcast episode transcript about the following topic.

Topic: ${episode.topic}

Research notes:
${notes}

The two hosts are ${hostA} and ${hostB}. Remember to output ONLY the JSON array.`;

  const t0 = performance.now();
  const response = await complete(
    modelInfo,
    system,
    userMessage,
    config.maxTokens,
    1.0,
    false
  );
  const apiDuration = (performance.now() - t0) / 1000;

  // Parse transcript JSON
  let transcriptText = response.text.trim();
  if (transcriptText.startsWith("```")) {
    const lines = transcriptText.split("\n");
    transcriptText = lines
      .filter((l) => !l.trim().startsWith("```"))
      .join("\n");
  }

  const segments = parseJsonWithRepair(transcriptText) as Array<{
    speaker: string;
    text: string;
  }>;
  if (!Array.isArray(segments) || segments.length === 0) {
    throw new Error(
      "Invalid transcript format: expected non-empty JSON array"
    );
  }

  for (const seg of segments) {
    if (!seg.speaker || !seg.text) {
      throw new Error(`Invalid segment format: ${JSON.stringify(seg)}`);
    }
  }

  // Save transcript
  await db
    .update(episodes)
    .set({ transcript: JSON.stringify(segments) })
    .where(eq(episodes.id, episodeId));

  // Generate a refined title
  try {
    const client = getClient();
    const titleResponse = await client.messages.create({
      model: "claude-haiku-4-20250414",
      max_tokens: 100,
      messages: [
        {
          role: "user",
          content:
            "Based on this podcast transcript, generate a short, catchy episode " +
            "title (max 8 words). Output ONLY the title, no quotes.\n\n" +
            `Topic: ${episode.topic}\n\nTranscript excerpt:\n${transcriptText.slice(0, 3000)}`,
        },
      ],
    });
    const newTitle = (
      titleResponse.content[0] as { text: string }
    ).text
      .trim()
      .replace(/^["']|["']$/g, "");
    if (newTitle) {
      await db
        .update(episodes)
        .set({ title: newTitle.slice(0, 200) })
        .where(eq(episodes.id, episodeId));
      log.info("Refined title for episode %s: %s", episodeId, newTitle);
    }
  } catch {
    log.warn("Failed to refine episode title, keeping original");
  }

  const wordCount = segments.reduce(
    (sum, seg) => sum + seg.text.split(/\s+/).length,
    0
  );
  const metrics = {
    model: response.model,
    provider: modelInfo.provider,
    input_tokens: response.inputTokens,
    output_tokens: response.outputTokens,
    duration_seconds: Math.round(apiDuration * 100) / 100,
    segment_count: segments.length,
    word_count: wordCount,
  };

  log.info(
    "Transcript generated for episode %s: %d segments, %d words, %d in/%d out tokens, %.1fs",
    episodeId,
    segments.length,
    wordCount,
    metrics.input_tokens,
    metrics.output_tokens,
    apiDuration
  );

  return metrics;
}
