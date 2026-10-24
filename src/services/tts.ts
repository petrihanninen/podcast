import { createHash } from "node:crypto";
import { and, eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings, ttsVoices } from "../schema.js";
import { settings } from "../config.js";
import { createLogger } from "../log.js";
import { voiceRefs } from "../generated/voice-refs.js";
import { concatWavs, parseWav, wavDurationSeconds } from "./wav.js";
import { encodeClipsToMp3 } from "./mp3.js";
import { putObject } from "./storage.js";
import { addJobProgress, completeJob, setJobProgressTotal, startJob } from "./jobs.js";
import { RETRYABLE_STATUS, isNetworkError } from "./llm-providers.js";

const log = createLogger("tts");

export interface TtsModelInfo {
  id: string;
  provider: "deepinfra" | "gemini";
  modelId: string;
  displayName: string;
  // Maximum characters per request
  maxChars: number;
  pricing: {
    perMillionChars?: number;
    inputPerMillionTokens?: number;
    outputPerMillionTokens?: number;
  };
}

// List prices, October 2026. Gemini TTS prices double on 2027-01-01.
export const TTS_MODELS: Record<string, TtsModelInfo> = {
  "gemini-flash-lite-tts": {
    id: "gemini-flash-lite-tts",
    provider: "gemini",
    modelId: "gemini-3.8-flash-lite-tts",
    displayName: "Gemini 3.8 Flash-Lite TTS",
    maxChars: 3000,
    pricing: { inputPerMillionTokens: 0.5, outputPerMillionTokens: 6.0 },
  },
  "gemini-flash-tts": {
    id: "gemini-flash-tts",
    provider: "gemini",
    modelId: "gemini-3.8-flash-tts",
    displayName: "Gemini 3.8 Flash TTS",
    maxChars: 3000,
    pricing: { inputPerMillionTokens: 0.5, outputPerMillionTokens: 9.0 },
  },
  "chatterbox-turbo": {
    id: "chatterbox-turbo",
    provider: "deepinfra",
    modelId: "ResembleAI/chatterbox-turbo",
    displayName: "Chatterbox Turbo (DeepInfra)",
    maxChars: 4500,
    pricing: { perMillionChars: 1.0 },
  },
};

export const DEFAULT_TTS_MODEL = "gemini-flash-lite-tts";
export const DEFAULT_GEMINI_VOICES = { hostA: "Puck", hostB: "Kore" };
export const SEGMENT_GAP_SECONDS = 0.3;

export function getTtsModel(modelKey?: string | null): TtsModelInfo {
  const key = modelKey || settings.ttsModel || DEFAULT_TTS_MODEL;
  const model = TTS_MODELS[key];
  if (!model) {
    throw new Error(`Unknown TTS model '${key}'. Available: ${Object.keys(TTS_MODELS).join(", ")}`);
  }
  return model;
}

export interface Piece {
  text: string;
  isHostA: boolean;
}

export interface TtsBatch {
  episodeId: string;
  index: number;
  total: number;
  model: string;
  pieces: Piece[];
  hostA: string;
  hostB: string;
  voiceA: string | null;
  voiceB: string | null;
}

export interface TtsBatchResult {
  index: number;
  key: string;
  bytes: number;
  samples: number;
  sampleRate: number;
  durationSeconds: number;
  pieces: number;
  chars: number;
  costUsd: number;
  requestSeconds: number;
}

export function splitLongText(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];
  const sentences = text.match(/[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g) ?? [text];
  const chunks: string[] = [];
  let current = "";
  for (const sentence of sentences) {
    if (current && current.length + sentence.length > maxChars) {
      chunks.push(current.trim());
      current = "";
    }
    if (sentence.length > maxChars) {
      for (let i = 0; i < sentence.length; i += maxChars) {
        chunks.push(sentence.slice(i, i + maxChars).trim());
      }
      continue;
    }
    current += sentence;
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.filter(Boolean);
}

export function groupByChars(pieces: Piece[], maxChars: number): Piece[][] {
  const groups: Piece[][] = [];
  let current: Piece[] = [];
  let size = 0;
  for (const piece of pieces) {
    if (current.length > 0 && size + piece.text.length > maxChars) {
      groups.push(current);
      current = [];
      size = 0;
    }
    current.push(piece);
    size += piece.text.length;
  }
  if (current.length > 0) groups.push(current);
  return groups;
}

export function chunkArray<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  fn: (item: T, index: number) => Promise<R>
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.max(1, Math.min(concurrency, items.length)) }, async () => {
    while (true) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await fn(items[i], i);
    }
  });
  await Promise.all(workers);
  return results;
}

async function fetchWithRetry(url: string, init: RequestInit, label: string): Promise<Response> {
  let lastError: Error | null = null;
  for (let attempt = 0; attempt < 4; attempt++) {
    let retryable = false;
    try {
      const res = await fetch(url, { ...init, signal: AbortSignal.timeout(120_000) });
      if (res.ok) return res;
      const body = await res.text();
      lastError = new Error(`${label} HTTP ${res.status}: ${body.slice(0, 1000)}`);
      retryable = RETRYABLE_STATUS.has(res.status);
    } catch (e: any) {
      lastError = e;
      retryable = isNetworkError(e);
    }
    if (!retryable) throw lastError;
    const wait = Math.min(2 ** attempt * 2, 20);
    log.warn("%s failed (attempt %d/4): %s — retrying in %ds", label, attempt + 1, lastError?.message, wait);
    await new Promise((r) => setTimeout(r, wait * 1000));
  }
  throw new Error(`${label} failed after 4 attempts: ${lastError?.message}`);
}

// ─── DeepInfra (Chatterbox Turbo, cloned voices) ─────────────────────

function deepinfraHeaders(): Record<string, string> {
  if (!settings.deepinfraApiKey) throw new Error("DEEPINFRA_API_KEY is not configured");
  return { Authorization: `Bearer ${settings.deepinfraApiKey}` };
}

async function ensureDeepinfraVoice(refBytes: Buffer, label: string): Promise<string> {
  const refHash = createHash("sha256").update(refBytes).digest("hex");
  const [existing] = await db
    .select()
    .from(ttsVoices)
    .where(and(eq(ttsVoices.provider, "deepinfra"), eq(ttsVoices.refHash, refHash)))
    .limit(1);
  if (existing) return existing.voiceId;

  log.info("Uploading voice reference %s to DeepInfra (%d bytes)", label, refBytes.length);
  const form = new FormData();
  form.append("name", `podcast-${label}-${refHash.slice(0, 8)}`);
  form.append("description", `Podcast host ${label} voice reference ${refHash.slice(0, 12)}`);
  form.append("files", new Blob([new Uint8Array(refBytes)], { type: "audio/wav" }), `${label}.wav`);

  const res = await fetchWithRetry(
    `${settings.deepinfraBaseUrl}/v1/voices/add`,
    { method: "POST", headers: deepinfraHeaders(), body: form },
    "DeepInfra voice upload"
  );
  const data = (await res.json()) as { voice_id?: string };
  if (!data.voice_id) {
    throw new Error(`DeepInfra voice upload returned no voice_id: ${JSON.stringify(data).slice(0, 500)}`);
  }
  await db
    .insert(ttsVoices)
    .values({ provider: "deepinfra", refHash, voiceId: data.voice_id })
    .onConflictDoNothing();
  return data.voice_id;
}

async function resolveVoice(configured: string | null | undefined, defaultRef: string, label: string) {
  if (configured && configured.trim()) return configured.trim();
  const base64 = voiceRefs[defaultRef];
  if (!base64) {
    log.warn("No bundled voice reference %s; using the provider's default voice", defaultRef);
    return null;
  }
  return ensureDeepinfraVoice(Buffer.from(base64, "base64"), label);
}

function decodeAudioField(audio: unknown): Buffer {
  if (typeof audio !== "string" || !audio) throw new Error("TTS response contained no audio");
  const comma = audio.startsWith("data:") ? audio.indexOf(",") : -1;
  return Buffer.from(comma >= 0 ? audio.slice(comma + 1) : audio, "base64");
}

interface ClipResult {
  wav: Buffer;
  chars: number;
  costUsd: number | null;
}

// ─── Gemini TTS (native two-speaker dialogue, prebuilt voices) ───────

async function synthesizeGemini(model: TtsModelInfo, group: Piece[], batch: TtsBatch): Promise<ClipResult> {
  if (!settings.googleApiKey) throw new Error("GOOGLE_API_KEY is not configured");
  const payload = {
    model: model.modelId,
    input: [
      {
        type: "user_input",
        content: group.map((piece) => ({
          type: "text",
          text: piece.text,
          annotations: [{ type: "speech_metadata", speaker: piece.isHostA ? batch.hostA : batch.hostB }],
        })),
      },
    ],
    response_format: { type: "audio" },
    generation_config: {
      speech_config: {
        mode: "conversational",
        speakers: [
          { speaker: batch.hostA, voice: batch.voiceA ?? DEFAULT_GEMINI_VOICES.hostA },
          { speaker: batch.hostB, voice: batch.voiceB ?? DEFAULT_GEMINI_VOICES.hostB },
        ],
      },
    },
    store: false,
  };

  const res = await fetchWithRetry(
    `${settings.geminiBaseUrl}/interactions`,
    {
      method: "POST",
      headers: { "x-goog-api-key": settings.googleApiKey, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    `Gemini ${model.modelId}`
  );
  const data = (await res.json()) as {
    status?: string;
    steps?: Array<{ type: string; content?: Array<{ type: string; data?: string }> }>;
    usage?: { total_input_tokens?: number; total_output_tokens?: number };
  };

  const audio: Buffer[] = [];
  for (const step of data.steps ?? []) {
    if (step.type !== "model_output") continue;
    for (const block of step.content ?? []) {
      if (block.type === "audio" && block.data) audio.push(decodeAudioField(block.data));
    }
  }
  if (audio.length === 0) {
    throw new Error(
      `Gemini TTS returned no audio (status=${data.status ?? "unknown"}): ${JSON.stringify(data).slice(0, 500)}`
    );
  }

  const inputTokens = data.usage?.total_input_tokens ?? 0;
  const outputTokens = data.usage?.total_output_tokens ?? 0;
  const p = model.pricing;
  return {
    wav: audio.length === 1 ? audio[0] : concatWavs(audio, 0).wav,
    chars: group.reduce((sum, piece) => sum + piece.text.length, 0),
    costUsd:
      (inputTokens * (p.inputPerMillionTokens ?? 0) + outputTokens * (p.outputPerMillionTokens ?? 0)) / 1_000_000,
  };
}

async function synthesizeDeepinfra(model: TtsModelInfo, text: string, voiceId: string | null): Promise<ClipResult> {
  const body: Record<string, unknown> = { text, response_format: "wav" };
  if (voiceId) body.voice_id = voiceId;

  const res = await fetchWithRetry(
    `${settings.deepinfraBaseUrl}/v1/inference/${model.modelId}`,
    {
      method: "POST",
      headers: { ...deepinfraHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    `DeepInfra ${model.modelId}`
  );

  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const data = (await res.json()) as {
      audio?: string;
      input_character_length?: number;
      inference_status?: { cost?: number };
    };
    return {
      wav: decodeAudioField(data.audio),
      chars: data.input_character_length ?? text.length,
      costUsd: typeof data.inference_status?.cost === "number" ? data.inference_status.cost : null,
    };
  }
  return { wav: Buffer.from(await res.arrayBuffer()), chars: text.length, costUsd: null };
}

// ─── Pipeline: plan → batches → results ───────────────────────────────

export async function planTts(episodeId: string): Promise<{ batches: TtsBatch[]; parallel: number }> {
  const [episode] = await db.select().from(episodes).where(eq(episodes.id, episodeId)).limit(1);
  if (!episode || !episode.transcript) throw new Error(`Episode ${episodeId} has no transcript`);

  const [psettings] = await db
    .select()
    .from(podcastSettings)
    .where(eq(podcastSettings.userId, episode.userId))
    .limit(1);
  const hostA = psettings?.hostAName ?? "Alex";
  const hostB = psettings?.hostBName ?? "Sam";
  const model = getTtsModel();

  await startJob(episodeId, "tts");

  const segments = JSON.parse(episode.transcript) as Array<{ speaker: string; text: string }>;
  const pieces: Piece[] = [];
  for (const seg of segments) {
    for (const text of splitLongText(seg.text, model.maxChars)) {
      pieces.push({ text, isHostA: seg.speaker === hostA });
    }
  }

  let voiceA: string | null;
  let voiceB: string | null;
  if (model.provider === "gemini") {
    voiceA = psettings?.ttsVoiceA?.trim() || DEFAULT_GEMINI_VOICES.hostA;
    voiceB = psettings?.ttsVoiceB?.trim() || DEFAULT_GEMINI_VOICES.hostB;
  } else {
    voiceA = await resolveVoice(psettings?.ttsVoiceA, "host_a.wav", "host-a");
    voiceB = await resolveVoice(psettings?.ttsVoiceB, "host_b.wav", "host-b");
  }

  const groups = chunkArray(pieces, Math.max(1, settings.ttsBatchSize));
  const batches: TtsBatch[] = groups.map((group, index) => ({
    episodeId,
    index,
    total: groups.length,
    model: model.id,
    pieces: group,
    hostA,
    hostB,
    voiceA,
    voiceB,
  }));

  await setJobProgressTotal(episodeId, "tts", pieces.length);
  log.info(
    "Episode %s: %d segments → %d pieces in %d batches via %s",
    episodeId,
    segments.length,
    pieces.length,
    batches.length,
    model.displayName
  );
  return { batches, parallel: Math.max(1, settings.ttsParallelBatches) };
}

export async function synthesizeBatch(batch: TtsBatch): Promise<TtsBatchResult> {
  const model = getTtsModel(batch.model);
  const t0 = performance.now();
  const clips =
    model.provider === "gemini"
      ? await mapWithConcurrency(groupByChars(batch.pieces, model.maxChars), settings.ttsConcurrency, (group) =>
          synthesizeGemini(model, group, batch)
        )
      : await mapWithConcurrency(batch.pieces, settings.ttsConcurrency, (piece) =>
          synthesizeDeepinfra(model, piece.text, piece.isHostA ? batch.voiceA : batch.voiceB)
        );
  const requestSeconds = (performance.now() - t0) / 1000;

  const encoded = await encodeClipsToMp3(
    clips.map((c) => c.wav),
    SEGMENT_GAP_SECONDS,
    settings.mp3Kbps
  );
  const key = `episodes/${batch.episodeId}/parts/${String(batch.index).padStart(4, "0")}.mp3`;
  await putObject(key, encoded.mp3, "audio/mpeg");

  const chars = clips.reduce((sum, c) => sum + c.chars, 0);
  const reported = clips.every((c) => c.costUsd !== null)
    ? clips.reduce((sum, c) => sum + (c.costUsd ?? 0), 0)
    : null;
  const costUsd = reported ?? (chars * (model.pricing.perMillionChars ?? 0)) / 1_000_000;

  await addJobProgress(batch.episodeId, "tts", batch.pieces.length, encoded.durationSeconds);
  log.info(
    "Episode %s: batch %d/%d done — %d pieces, %.1fs audio, %.1fs of requests, $%s",
    batch.episodeId,
    batch.index + 1,
    batch.total,
    batch.pieces.length,
    encoded.durationSeconds,
    requestSeconds,
    costUsd.toFixed(4)
  );

  return {
    index: batch.index,
    key,
    bytes: encoded.mp3.length,
    samples: encoded.samples,
    sampleRate: encoded.sampleRate,
    durationSeconds: encoded.durationSeconds,
    pieces: batch.pieces.length,
    chars,
    costUsd,
    requestSeconds,
  };
}

export async function finishTts(
  episodeId: string,
  results: TtsBatchResult[],
  wallSeconds: number
): Promise<Record<string, unknown>> {
  const sorted = [...results].sort((a, b) => a.index - b.index);
  const model = getTtsModel();
  const audioSeconds = sorted.reduce((s, r) => s + r.durationSeconds, 0);
  const chars = sorted.reduce((s, r) => s + r.chars, 0);
  const costUsd = sorted.reduce((s, r) => s + r.costUsd, 0);
  const requestSeconds = sorted.reduce((s, r) => s + r.requestSeconds, 0);
  const pieces = sorted.reduce((s, r) => s + r.pieces, 0);

  const metrics = {
    provider: model.provider,
    model: model.modelId,
    segment_count: pieces,
    batches: sorted.length,
    characters: chars,
    cost_usd: Math.round(costUsd * 1_000_000) / 1_000_000,
    duration_seconds: Math.round(wallSeconds * 100) / 100,
    request_seconds: Math.round(requestSeconds * 100) / 100,
    audio_duration_seconds: Math.round(audioSeconds * 100) / 100,
    realtime_factor: wallSeconds > 0 ? Math.round((audioSeconds / wallSeconds) * 100) / 100 : 0,
    parts: sorted.map((r) => ({
      key: r.key,
      bytes: r.bytes,
      samples: r.samples,
      sampleRate: r.sampleRate,
      durationSeconds: r.durationSeconds,
    })),
  };
  await completeJob(episodeId, "tts", metrics);
  log.info(
    "Episode %s: TTS complete — %.1fs audio in %.1fs wall, %d chars, $%s",
    episodeId,
    audioSeconds,
    wallSeconds,
    chars,
    costUsd.toFixed(4)
  );
  return metrics;
}

export function clipDuration(wav: Buffer): number {
  return wavDurationSeconds(parseWav(wav));
}
