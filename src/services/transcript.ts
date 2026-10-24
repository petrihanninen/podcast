import { eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings } from "../schema.js";
import { complete, getTranscriptModel, type LLMResponse } from "./llm-providers.js";
import { completeJob, startJob } from "./jobs.js";
import { createLogger } from "../log.js";

const log = createLogger("transcript");

export interface Segment {
  speaker: string;
  text: string;
}

export interface TranscriptPlan {
  parts: number;
  wordsPerPart: number;
  totalWords: number;
  duration: string;
  notesTruncation: number;
  maxTokensPerPart: number;
  hostA: string;
  hostB: string;
  toneNotes: string[];
  topic: string;
}

export interface Outline {
  sections: Array<{ title: string; points: string[] }>;
}

export interface LlmUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  calls: number;
}

const TRANSCRIPT_LENGTH_CONFIG: Record<
  number,
  { parts: number; wordsPerPart: number; duration: string; notesTruncation: number }
> = {
  15: { parts: 1, wordsPerPart: 2000, duration: "12-15", notesTruncation: 40000 },
  30: { parts: 1, wordsPerPart: 4000, duration: "25-30", notesTruncation: 60000 },
  60: { parts: 2, wordsPerPart: 4000, duration: "55-60", notesTruncation: 100000 },
  120: { parts: 4, wordsPerPart: 4000, duration: "110-120", notesTruncation: 160000 },
};

export const DEFAULT_TONE_NOTES: string[] = [
  "Make it feel like a real conversation between two knowledgeable friends",
  'Include natural interjections ("Right!", "That\'s fascinating", "Wait, really?")',
  "Add humor where appropriate — a witty aside or funny observation",
  "Build a clear narrative arc: hook → context → deep dive → implications → takeaway",
  "Each segment should be 1-4 sentences (natural speaking length)",
  "Make sure the listener learns something genuinely interesting and useful",
];

const SYSTEM_PROMPT = `You are a podcast script writer. You write engaging, natural-sounding \
conversational transcripts between two podcast hosts.

Your output MUST be a JSON array of dialogue segments. Each segment is an object with:
- "speaker": the host's name (exactly as provided)
- "text": what they say (natural speech, not written prose)

Guidelines for the conversation:
- {{host_a}} tends to introduce topics and provide structure
- {{host_b}} asks great questions, plays devil's advocate, and adds surprising perspectives
{tone_notes}\
- Don't use stage directions or descriptions — only spoken dialogue
- Write for text-to-speech: spell out numbers and abbreviations the way a person would say them, and avoid URLs, markdown and special symbols

Output ONLY the JSON array, no other text.`;

function buildSystemPrompt(plan: TranscriptPlan): string {
  const toneLines = plan.toneNotes.map((n) => `- ${n}\n`).join("");
  return SYSTEM_PROMPT.replace("{tone_notes}", toneLines)
    .replace(/\{\{host_a\}\}/g, plan.hostA)
    .replace(/\{\{host_b\}\}/g, plan.hostB);
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

function stripFences(raw: string): string {
  let text = raw.trim();
  if (text.startsWith("```")) {
    text = text
      .split("\n")
      .filter((l) => !l.trim().startsWith("```"))
      .join("\n");
  }
  return text;
}

export function parseSegments(raw: string): Segment[] {
  const text = stripFences(raw);
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

function parseOutline(raw: string, parts: number): Outline {
  const text = stripFences(raw);
  let parsed: any;
  try {
    parsed = JSON.parse(text);
  } catch {
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    parsed = JSON.parse(text.slice(start, end + 1));
  }
  const sections = Array.isArray(parsed?.sections) ? parsed.sections : Array.isArray(parsed) ? parsed : null;
  if (!sections || sections.length === 0) throw new Error("Outline did not contain sections");
  const cleaned = sections.map((s: any, i: number) => ({
    title: typeof s?.title === "string" ? s.title : `Part ${i + 1}`,
    points: Array.isArray(s?.points) ? s.points.map(String) : [],
  }));
  while (cleaned.length < parts) cleaned.push({ title: `Part ${cleaned.length + 1}`, points: [] });
  return { sections: cleaned.slice(0, parts) };
}

function usageOf(response: LLMResponse): LlmUsage {
  return {
    input_tokens: response.inputTokens,
    output_tokens: response.outputTokens,
    cost_usd: response.costUsd,
    calls: 1,
  };
}

export function addUsage(a: LlmUsage, b: LlmUsage): LlmUsage {
  return {
    input_tokens: a.input_tokens + b.input_tokens,
    output_tokens: a.output_tokens + b.output_tokens,
    cost_usd: a.cost_usd + b.cost_usd,
    calls: a.calls + b.calls,
  };
}

export const EMPTY_USAGE: LlmUsage = { input_tokens: 0, output_tokens: 0, cost_usd: 0, calls: 0 };

async function loadEpisode(episodeId: string) {
  const [episode] = await db.select().from(episodes).where(eq(episodes.id, episodeId)).limit(1);
  if (!episode) throw new Error(`Episode ${episodeId} not found`);
  return episode;
}

async function researchNotesFor(episodeId: string, truncation: number): Promise<string> {
  const episode = await loadEpisode(episodeId);
  let notes = episode.researchNotes || "No research notes available.";
  if (notes.length > truncation) notes = notes.slice(0, truncation) + "\n\n[...truncated]";
  return notes;
}

export async function planTranscript(episodeId: string): Promise<TranscriptPlan> {
  const episode = await loadEpisode(episodeId);
  const [settings] = await db
    .select()
    .from(podcastSettings)
    .where(eq(podcastSettings.userId, episode.userId))
    .limit(1);

  let toneNotes: string[] = DEFAULT_TONE_NOTES;
  if (settings?.transcriptToneNotes) {
    try {
      const parsed = JSON.parse(settings.transcriptToneNotes);
      if (Array.isArray(parsed)) toneNotes = parsed.map(String);
    } catch {}
  }

  const config = TRANSCRIPT_LENGTH_CONFIG[episode.targetLengthMinutes] ?? TRANSCRIPT_LENGTH_CONFIG[30];
  await startJob(episodeId, "transcript");

  return {
    parts: config.parts,
    wordsPerPart: config.wordsPerPart,
    totalWords: config.parts * config.wordsPerPart,
    duration: config.duration,
    notesTruncation: config.notesTruncation,
    maxTokensPerPart: Math.round(config.wordsPerPart * 3),
    hostA: settings?.hostAName ?? "Alex",
    hostB: settings?.hostBName ?? "Sam",
    toneNotes,
    topic: episode.topic,
  };
}

export async function outlineTranscript(
  episodeId: string,
  plan: TranscriptPlan
): Promise<{ outline: Outline; usage: LlmUsage }> {
  const modelInfo = getTranscriptModel();
  const notes = await researchNotesFor(episodeId, plan.notesTruncation);
  const response = await complete(modelInfo, {
    system:
      "You plan long-form podcast episodes. Output ONLY a JSON object of the form " +
      '{"sections":[{"title":"...","points":["...","..."]}]} with no other text.',
    user: `Plan a ${plan.duration} minute two-host podcast episode as exactly ${plan.parts} consecutive \
sections of roughly equal length, in narrative order (hook and context first, implications and \
takeaways last). Each section needs a title and 4-8 bullet points of concrete material from the \
research notes to cover, without repeating material between sections.

Topic: ${plan.topic}

Research notes:
${notes}`,
    maxTokens: 4000,
    effort: "low",
  });
  log.info("Outline for episode %s: %d sections", episodeId, plan.parts);
  return { outline: parseOutline(response.text, plan.parts), usage: usageOf(response) };
}

export async function writeTranscriptPart(
  episodeId: string,
  plan: TranscriptPlan,
  partIndex: number,
  outline: Outline | null,
  previousTail: Segment[]
): Promise<{ segments: Segment[]; usage: LlmUsage; model: string }> {
  const modelInfo = getTranscriptModel();
  const notes = await researchNotesFor(episodeId, plan.notesTruncation);
  const isFirst = partIndex === 0;
  const isLast = partIndex === plan.parts - 1;

  let partInstructions = "";
  if (plan.parts > 1) {
    const section = outline?.sections[partIndex];
    const sectionText = section
      ? `${section.title}\n${section.points.map((p) => `- ${p}`).join("\n")}`
      : "(no outline available)";
    const others = outline
      ? outline.sections
          .map((s, i) => `${i + 1}. ${s.title}${i === partIndex ? " (THIS PART)" : ""}`)
          .join("\n")
      : "";
    partInstructions = `
This episode is written in ${plan.parts} parts; you are writing PART ${partIndex + 1} of ${plan.parts}. \
Target about ${plan.wordsPerPart} words for this part.
Full episode outline:
${others}

Cover ONLY this part's section:
${sectionText}

${isFirst ? "Open the episode with a hook and introductions." : "Do NOT re-introduce the show or the hosts; continue the conversation seamlessly from where it left off."}
${isLast ? "Close the episode with takeaways and a sign-off." : "Do NOT wrap up or sign off; end at a natural transition into the next section."}
${previousTail.length > 0 ? `The conversation so far ended with:\n${previousTail.map((s) => `${s.speaker}: ${s.text}`).join("\n")}` : ""}`;
  } else {
    partInstructions = `Target ${plan.totalWords} words total (roughly ${plan.duration} minutes at speaking pace).`;
  }

  const response = await complete(modelInfo, {
    system: buildSystemPrompt(plan),
    user: `Write a podcast episode transcript about the following topic.

Topic: ${plan.topic}

Research notes:
${notes}

${partInstructions}

The two hosts are ${plan.hostA} and ${plan.hostB}. Remember to output ONLY the JSON array.`,
    maxTokens: plan.maxTokensPerPart,
  });

  const segments = parseSegments(response.text);
  const known = new Set([plan.hostA, plan.hostB]);
  const unknown = segments.filter((s) => !known.has(s.speaker));
  if (unknown.length > 0) {
    log.warn(
      "Episode %s part %d: %d segment(s) with unknown speaker (e.g. %s) will use host B's voice",
      episodeId,
      partIndex + 1,
      unknown.length,
      unknown[0].speaker
    );
  }
  log.info(
    "Episode %s part %d/%d: %d segments, %d in/%d out tokens",
    episodeId,
    partIndex + 1,
    plan.parts,
    segments.length,
    response.inputTokens,
    response.outputTokens
  );
  return { segments, usage: usageOf(response), model: response.model };
}

export async function generateTitle(topic: string, transcriptExcerpt?: string): Promise<string | null> {
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

export async function saveTranscript(
  episodeId: string,
  segments: Segment[],
  usage: LlmUsage,
  model: string,
  durationSeconds: number
): Promise<Record<string, unknown>> {
  const episode = await loadEpisode(episodeId);
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
    await db.update(episodes).set({ title: newTitle }).where(eq(episodes.id, episodeId));
    log.info("Refined title for episode %s: %s", episodeId, newTitle);
  }

  const wordCount = segments.reduce((sum, seg) => sum + seg.text.split(/\s+/).length, 0);
  const metrics = {
    model,
    provider: getTranscriptModel().provider,
    input_tokens: usage.input_tokens,
    output_tokens: usage.output_tokens,
    cost_usd: usage.cost_usd,
    llm_calls: usage.calls,
    duration_seconds: Math.round(durationSeconds * 100) / 100,
    segment_count: segments.length,
    word_count: wordCount,
  };
  await completeJob(episodeId, "transcript", metrics);
  log.info(
    "Transcript saved for episode %s: %d segments, %d words, $%s",
    episodeId,
    segments.length,
    wordCount,
    usage.cost_usd.toFixed(4)
  );
  return metrics;
}
