import fs from "node:fs";
import path from "node:path";
import { eq } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings } from "../schema.js";
import { settings } from "../config.js";
import { createLogger } from "../log-handler.js";

const log = createLogger("tts");

export function getTtsProgress(_episodeId: string): null {
  // Modal TTS doesn't write progress files (GPU work is remote).
  return null;
}

function validateVoiceRefPath(refPath: string): string | null {
  const allowedDir = fs.realpathSync(settings.voiceRefsDir);
  const resolved = fs.realpathSync(
    path.join(allowedDir, path.basename(refPath))
  );
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
  // Try database path first
  if (dbPath) {
    try {
      const safePath = validateVoiceRefPath(dbPath);
      if (safePath && fs.existsSync(safePath)) {
        return fs.readFileSync(safePath);
      }
    } catch {}
  }
  // Try default path
  const defaultPath = path.join(settings.voiceRefsDir, defaultFilename);
  if (fs.existsSync(defaultPath)) {
    return fs.readFileSync(defaultPath);
  }
  log.warn("No voice ref found, tried: db=%s, default=%s", dbPath, defaultPath);
  return null;
}

export async function synthesizeSpeech(
  episodeId: string
): Promise<Record<string, unknown>> {
  // Read data from DB
  const [episode] = await db
    .select()
    .from(episodes)
    .where(eq(episodes.id, episodeId))
    .limit(1);
  if (!episode || !episode.transcript) {
    throw new Error(
      `Episode ${episodeId} not found or has no transcript`
    );
  }

  const [psettings] = await db
    .select()
    .from(podcastSettings)
    .where(eq(podcastSettings.userId, episode.userId))
    .limit(1);

  const hostA = psettings?.hostAName ?? "Alex";
  const voiceRefA = psettings?.voiceRefAPath ?? null;
  const voiceRefB = psettings?.voiceRefBPath ?? null;
  const segments = JSON.parse(episode.transcript);

  log.info(
    "Synthesizing %d segments for episode %s",
    segments.length,
    episodeId
  );

  // Read voice ref bytes
  const voiceRefABytes = readVoiceRefBytes(voiceRefA, "host_a.wav");
  const voiceRefBBytes = readVoiceRefBytes(voiceRefB, "host_b.wav");

  // Call Modal TTS via HTTP web endpoint
  const modalUrl = settings.modalTtsUrl;
  if (!modalUrl) {
    throw new Error(
      "MODAL_TTS_URL is not configured. Deploy modal_app.py and set the URL."
    );
  }

  const body: Record<string, unknown> = {
    segments,
    host_a_name: hostA,
    voice_ref_a_bytes: voiceRefABytes
      ? voiceRefABytes.toString("base64")
      : null,
    voice_ref_b_bytes: voiceRefBBytes
      ? voiceRefBBytes.toString("base64")
      : null,
  };

  const res = await fetch(modalUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(1800_000), // 30 min timeout
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Modal TTS call failed (${res.status}): ${errText}`);
  }

  const result = (await res.json()) as {
    wav_bytes: string;
    metrics: Record<string, unknown>;
  };

  // Write WAV bytes to disk (namespaced per user)
  const userAudioDir = path.join(settings.audioDir, episode.userId);
  const outputWav = path.join(userAudioDir, `${episodeId}.wav`);
  fs.mkdirSync(userAudioDir, { recursive: true });
  fs.writeFileSync(outputWav, Buffer.from(result.wav_bytes, "base64"));
  log.info("Wrote audio file: %s", outputWav);

  return result.metrics;
}
