import { eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings } from "../schema.js";
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
  15: { wordTarget: 2000, duration: "12-15", notesTruncation: 40000, maxTokens: 12000 },
  30: { wordTarget: 4000, duration: "25-30", notesTruncation: 60000, maxTokens: 20000 },
  60: { wordTarget: 8000, duration: "55-60", notesTruncation: 100000, maxTokens: 36000 },
  120: { wordTarget: 16000, duration: "110-120", notesTruncation: 160000, maxTokens: 64000 },
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
- Write for text-to-speech: spell out numbers and abbreviations the way a person would say them, and avoid URLs, markdown and special symbols

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
  text = text.replace(/,\s*([}\]])/g, "$1");
  const start = text.indexOf("[");
  const end = text.lastIndexOf("]");
  if (start !== -1 && end !== -1 && end > start) {
    text = text.slice(start, end + 1);
  }
  return text;
}

export function parseSegments(raw: string): Array<{ speaker: string; text: string }> {
  let text = raw.trim();
  if (text.startsWith("```")) {
    text = text
      .split("\n")
      .filter((l) => !l.trim().startsWith("```"))
      .join("\n");
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    log.warn("Initial JSON parse failed — attempting repair");
    try {
      parsed = JSON.parse(repairJson(text));
    } catch {
      throw new Error("Failed to parse transcript JSON");
    }
  }

  if (!Array.isArray(parsed) && parsed && typeof parsed === "object") {
    const inner = Object.values(parsed as Record<string, unknown>).find(Array.isArray);
    if (inner) parsed = inner;
  }
  if (!Array.isArray(parsed) || parsed.length === 0) {
    throw new Error("Invalid transcript format: expected non-empty JSON array");
  }

  return parsed.map((seg: any) => {
    if (!seg || typeof seg.speaker !== "string" || typeof seg.text !== "string" || !seg.text.trim()) {
      throw new Error(`Invalid segment format: ${JSON.stringify(seg)}`);
    }
    return { speaker: seg.speaker.trim(), text: seg.text.trim() };
  });
}

export async function generateTitle(
  topic: string,
  transcriptExcerpt?: string
): Promise<string | null> {
  const modelInfo = getTranscriptModel();
  const context = transcriptExcerpt
    ? `Topic: ${topic}\n\nTranscript excerpt:\n${transcriptExcerpt}`
    : `Topic: ${topic}`;
  try {
    const response = await complete(modelInfo, {
      system:
        "You write short, catchy podcast episode titles (max 8 words). " +
        "Output ONLY the title: no quotes, no explanation.",
      user: `Write an episode title for this podcast episode.\n\n${context}`,
      maxTokens: 2000,
      effort: "low",
    });
    const title = response.text
      .trim()
      .split("\n")[0]
      .replace(/^["'“”]+|["'“”]+$/g, "")
      .trim();
    return title ? title.slice(0, 200) : null;
  } catch (e: any) {
    log.warn("Title generation failed: %s", e.message);
    return null;
  }
}

export async function generateTranscript(
  episodeId: string
): Promise<Record<string, unknown>> {
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
  const response = await complete(modelInfo, {
    system,
    user: userMessage,
    maxTokens: config.maxTokens,
  });
  const apiDuration = (performance.now() - t0) / 1000;

  const segments = parseSegments(response.text);
  const knownSpeakers = new Set([hostA, hostB]);
  const unknown = segments.filter((s) => !knownSpeakers.has(s.speaker));
  if (unknown.length > 0) {
    log.warn(
      "Transcript for episode %s has %d segment(s) with unknown speakers (e.g. %s); they will use host B's voice",
      episodeId,
      unknown.length,
      unknown[0].speaker
    );
  }

  await db
    .update(episodes)
    .set({ transcript: JSON.stringify(segments) })
    .where(eq(episodes.id, episodeId));

  const excerpt = segments
    .slice(0, 12)
    .map((s) => `${s.speaker}: ${s.text}`)
    .join("\n")
    .slice(0, 3000);
  const newTitle = await generateTitle(episode.topic, excerpt);
  if (newTitle) {
    await db
      .update(episodes)
      .set({ title: newTitle })
      .where(eq(episodes.id, episodeId));
    log.info("Refined title for episode %s: %s", episodeId, newTitle);
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
    cost_usd: response.costUsd,
    duration_seconds: Math.round(apiDuration * 100) / 100,
    segment_count: segments.length,
    word_count: wordCount,
  };

  log.info(
    "Transcript generated for episode %s: %d segments, %d words, %d in/%d out tokens, $%s, %.1fs",
    episodeId,
    segments.length,
    wordCount,
    metrics.input_tokens,
    metrics.output_tokens,
    metrics.cost_usd.toFixed(4),
    apiDuration
  );

  return metrics;
}
