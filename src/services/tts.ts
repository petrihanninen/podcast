import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { and, eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings, ttsVoices } from "../schema.js";
import { settings } from "../config.js";
import { createLogger } from "../log-handler.js";
import { concatWavs, parseWav, wavDurationSeconds } from "./wav.js";
import { RETRYABLE_STATUS, isNetworkError } from "./llm-providers.js";

const log = createLogger("tts");

export interface TtsModelInfo {
  id: string;
  provider: "deepinfra";
  modelId: string;
  displayName: string;
  pricePerMillionChars: number;
  maxChars: number;
}

export const TTS_MODELS: Record<string, TtsModelInfo> = {
  "chatterbox-turbo": {
    id: "chatterbox-turbo",
    provider: "deepinfra",
    modelId: "ResembleAI/chatterbox-turbo",
    displayName: "Chatterbox Turbo (DeepInfra)",
    pricePerMillionChars: 1.0,
    maxChars: 4500,
  },
};

export const DEFAULT_TTS_MODEL = "chatterbox-turbo";
const SEGMENT_GAP_SECONDS = 0.3;
const DEEPINFRA_BASE = "https://api.deepinfra.com";

export function getTtsModel(modelKey?: string | null): TtsModelInfo {
  const key = modelKey || settings.ttsModel || DEFAULT_TTS_MODEL;
  const model = TTS_MODELS[key];
  if (!model) {
    throw new Error(`Unknown TTS model '${key}'. Available: ${Object.keys(TTS_MODELS).join(", ")}`);
  }
  return model;
}

interface Segment {
  speaker: string;
  text: string;
}

export interface TtsProgress {
  segments_completed: number;
  total_segments: number;
  audio_duration_seconds: number;
  audio_duration_formatted: string;
}

function progressPath(episodeId: string): string {
  return path.join(settings.audioDir, "segments", `${episodeId}.json`);
}

function writeProgress(episodeId: string, progress: TtsProgress): void {
  try {
    fs.mkdirSync(path.dirname(progressPath(episodeId)), { recursive: true });
    fs.writeFileSync(progressPath(episodeId), JSON.stringify(progress));
  } catch (e: any) {
    log.warn("Failed to write TTS progress: %s", e.message);
  }
}

function clearProgress(episodeId: string): void {
  try {
    fs.rmSync(progressPath(episodeId), { force: true });
  } catch {}
}

export function getTtsProgress(episodeId: string): TtsProgress | null {
  try {
    const raw = fs.readFileSync(progressPath(episodeId), "utf8");
    return JSON.parse(raw) as TtsProgress;
  } catch {
    return null;
  }
}

function formatDuration(seconds: number): string {
  const total = Math.floor(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function validateVoiceRefPath(refPath: string): string | null {
  const allowedDir = fs.realpathSync(settings.voiceRefsDir);
  const resolved = fs.realpathSync(path.join(allowedDir, path.basename(refPath)));
  if (!resolved.startsWith(allowedDir + path.sep) && resolved !== allowedDir) {
    log.warn("Voice ref path escapes allowed directory: %s", refPath);
    return null;
  }
  return resolved;
}

function readVoiceRefBytes(
  dbPath: string | null | undefined,
  defaultFilename: string
): Buffer | null {
  if (dbPath) {
    try {
      const safePath = validateVoiceRefPath(dbPath);
      if (safePath && fs.existsSync(safePath)) return fs.readFileSync(safePath);
    } catch {}
  }
  const defaultPath = path.join(settings.voiceRefsDir, defaultFilename);
  if (fs.existsSync(defaultPath)) return fs.readFileSync(defaultPath);
  log.warn("No voice ref found, tried: db=%s, default=%s", dbPath, defaultPath);
  return null;
}

function deepinfraHeaders(): Record<string, string> {
  if (!settings.deepinfraApiKey) throw new Error("DEEPINFRA_API_KEY is not configured");
  return { Authorization: `Bearer ${settings.deepinfraApiKey}` };
}

async function fetchWithRetry(
  url: string,
  init: RequestInit,
  label: string
): Promise<Response> {
  let lastError: Error | null = null;
  for (let attempt = 0; attempt < 5; attempt++) {
    let retryable = false;
    try {
      const res = await fetch(url, { ...init, signal: AbortSignal.timeout(300_000) });
      if (res.ok) return res;
      const body = await res.text();
      lastError = new Error(`${label} HTTP ${res.status}: ${body.slice(0, 1000)}`);
      retryable = RETRYABLE_STATUS.has(res.status);
    } catch (e: any) {
      lastError = e;
      retryable = isNetworkError(e);
    }
    if (!retryable) throw lastError;
    const wait = Math.min(2 ** attempt * 2, 60);
    log.warn("%s failed (attempt %d/5): %s — retrying in %ds", label, attempt + 1, lastError?.message, wait);
    await new Promise((r) => setTimeout(r, wait * 1000));
  }
  throw new Error(`${label} failed after 5 attempts: ${lastError?.message}`);
}

async function ensureDeepinfraVoice(refBytes: Buffer, label: string): Promise<string> {
  const refHash = createHash("sha256").update(refBytes).digest("hex");
  const [existing] = await db
    .select()
    .from(ttsVoices)
    .where(and(eq(ttsVoices.provider, "deepinfra"), eq(ttsVoices.refHash, refHash)))
    .limit(1);
  if (existing) return existing.voiceId;

  log.info("Uploading voice reference for %s to DeepInfra (%d bytes)", label, refBytes.length);
  const form = new FormData();
  form.append("name", `podcast-${label}-${refHash.slice(0, 8)}`);
  form.append("description", `Podcast host ${label} voice reference ${refHash.slice(0, 12)}`);
  form.append("files", new Blob([new Uint8Array(refBytes)], { type: "audio/wav" }), `${label}.wav`);

  const res = await fetchWithRetry(
    `${DEEPINFRA_BASE}/v1/voices/add`,
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

function decodeAudioField(audio: unknown): Buffer {
  if (typeof audio !== "string" || !audio) {
    throw new Error("DeepInfra TTS response contained no audio");
  }
  const comma = audio.startsWith("data:") ? audio.indexOf(",") : -1;
  return Buffer.from(comma >= 0 ? audio.slice(comma + 1) : audio, "base64");
}

interface SegmentResult {
  wav: Buffer;
  chars: number;
  costUsd: number | null;
  runtimeMs: number | null;
}

async function synthesizeDeepinfra(
  model: TtsModelInfo,
  text: string,
  voiceId: string | null
): Promise<SegmentResult> {
  const body: Record<string, unknown> = { text, response_format: "wav" };
  if (voiceId) body.voice_id = voiceId;

  const res = await fetchWithRetry(
    `${DEEPINFRA_BASE}/v1/inference/${model.modelId}`,
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
      inference_status?: { cost?: number; runtime_ms?: number };
    };
    return {
      wav: decodeAudioField(data.audio),
      chars: data.input_character_length ?? text.length,
      costUsd: typeof data.inference_status?.cost === "number" ? data.inference_status.cost : null,
      runtimeMs: data.inference_status?.runtime_ms ?? null,
    };
  }
  return {
    wav: Buffer.from(await res.arrayBuffer()),
    chars: text.length,
    costUsd: null,
    runtimeMs: null,
  };
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

export async function synthesizeSpeech(
  episodeId: string
): Promise<Record<string, unknown>> {
  const [episode] = await db
    .select()
    .from(episodes)
    .where(eq(episodes.id, episodeId))
    .limit(1);
  if (!episode || !episode.transcript) {
    throw new Error(`Episode ${episodeId} not found or has no transcript`);
  }

  const [psettings] = await db
    .select()
    .from(podcastSettings)
    .where(eq(podcastSettings.userId, episode.userId))
    .limit(1);

  const hostA = psettings?.hostAName ?? "Alex";
  const model = getTtsModel();
  const segments = JSON.parse(episode.transcript) as Segment[];

  const pieces: Array<{ text: string; isHostA: boolean }> = [];
  for (const seg of segments) {
    for (const text of splitLongText(seg.text, model.maxChars)) {
      pieces.push({ text, isHostA: seg.speaker === hostA });
    }
  }

  log.info(
    "Synthesizing %d segments (%d requests) for episode %s via %s",
    segments.length,
    pieces.length,
    episodeId,
    model.displayName
  );

  const refA = readVoiceRefBytes(psettings?.voiceRefAPath, "host_a.wav");
  const refB = readVoiceRefBytes(psettings?.voiceRefBPath, "host_b.wav");
  const voiceA = refA ? await ensureDeepinfraVoice(refA, "host-a") : null;
  const voiceB = refB ? await ensureDeepinfraVoice(refB, "host-b") : null;

  let completed = 0;
  let audioSeconds = 0;
  const progress = (): TtsProgress => ({
    segments_completed: completed,
    total_segments: pieces.length,
    audio_duration_seconds: audioSeconds,
    audio_duration_formatted: formatDuration(audioSeconds),
  });
  writeProgress(episodeId, progress());

  const t0 = performance.now();
  let results: SegmentResult[];
  try {
    results = await mapWithConcurrency(pieces, settings.ttsConcurrency, async (piece, i) => {
      const result = await synthesizeDeepinfra(model, piece.text, piece.isHostA ? voiceA : voiceB);
      completed++;
      audioSeconds += wavDurationSeconds(parseWav(result.wav));
      if (completed % 10 === 0 || completed === pieces.length) {
        log.info("TTS progress for episode %s: %d/%d segments", episodeId, completed, pieces.length);
      }
      writeProgress(episodeId, progress());
      return result;
    });
  } finally {
    clearProgress(episodeId);
  }
  const generationSeconds = (performance.now() - t0) / 1000;

  const { wav, durationSeconds } = concatWavs(
    results.map((r) => r.wav),
    SEGMENT_GAP_SECONDS
  );

  const userAudioDir = path.join(settings.audioDir, episode.userId);
  fs.mkdirSync(userAudioDir, { recursive: true });
  const outputWav = path.join(userAudioDir, `${episodeId}.wav`);
  fs.writeFileSync(outputWav, wav);
  log.info("Wrote audio file: %s", outputWav);

  const chars = results.reduce((sum, r) => sum + r.chars, 0);
  const reportedCost = results.every((r) => r.costUsd !== null)
    ? results.reduce((sum, r) => sum + (r.costUsd ?? 0), 0)
    : null;
  const costUsd = reportedCost ?? (chars * model.pricePerMillionChars) / 1_000_000;
  const runtimes = results.map((r) => r.runtimeMs).filter((r): r is number => r !== null);

  const metrics = {
    provider: model.provider,
    model: model.modelId,
    segment_count: segments.length,
    segments_generated: pieces.length,
    characters: chars,
    cost_usd: Math.round(costUsd * 1_000_000) / 1_000_000,
    concurrency: settings.ttsConcurrency,
    duration_seconds: Math.round(generationSeconds * 100) / 100,
    audio_duration_seconds: Math.round(durationSeconds * 100) / 100,
    avg_segment_seconds:
      runtimes.length > 0
        ? Math.round((runtimes.reduce((a, b) => a + b, 0) / runtimes.length / 1000) * 100) / 100
        : Math.round((generationSeconds / pieces.length) * 100) / 100,
    realtime_factor:
      generationSeconds > 0 ? Math.round((durationSeconds / generationSeconds) * 100) / 100 : 0,
  };

  log.info(
    "TTS complete for episode %s: %.1fs audio in %.1fs (%sx realtime), %d chars, $%s",
    episodeId,
    durationSeconds,
    generationSeconds,
    metrics.realtime_factor,
    chars,
    costUsd.toFixed(4)
  );

  return metrics;
}
