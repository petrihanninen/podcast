import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs";
import path from "node:path";
import { eq, sql } from "drizzle-orm";
import { db } from "../database.js";
import { episodes } from "../schema.js";
import { settings } from "../config.js";
import { createLogger } from "../log-handler.js";

const execFileAsync = promisify(execFile);
const log = createLogger("encoder");

async function encode(
  episodeId: string,
  audioDir: string
): Promise<{ filename: string; durationSeconds: number; fileSize: number }> {
  const wavPath = path.join(audioDir, `${episodeId}.wav`);
  if (!fs.existsSync(wavPath)) {
    throw new Error(`WAV file not found: ${wavPath}`);
  }

  const mp3Filename = `${episodeId}.mp3`;
  const mp3Path = path.join(audioDir, mp3Filename);

  log.info("Encoding MP3 for episode %s", episodeId);

  // Convert to mono 44.1kHz 128kbps MP3
  await execFileAsync("ffmpeg", [
    "-i", wavPath,
    "-ac", "1",
    "-ar", "44100",
    "-b:a", "128k",
    "-y",
    mp3Path,
  ]);

  // Get duration via ffprobe
  const { stdout } = await execFileAsync("ffprobe", [
    "-v", "error",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    mp3Path,
  ]);
  const durationSeconds = Math.floor(parseFloat(stdout.trim()));
  const fileSize = fs.statSync(mp3Path).size;

  // Clean up WAV and segments
  fs.unlinkSync(wavPath);
  const segmentsDir = path.join(audioDir, "segments", episodeId);
  if (fs.existsSync(segmentsDir)) {
    fs.rmSync(segmentsDir, { recursive: true });
  }

  return { filename: mp3Filename, durationSeconds, fileSize };
}

export async function encodeMp3(
  episodeId: string
): Promise<Record<string, unknown>> {
  // Look up user_id
  const [episode] = await db
    .select()
    .from(episodes)
    .where(eq(episodes.id, episodeId))
    .limit(1);
  if (!episode) throw new Error(`Episode ${episodeId} not found`);

  const userAudioDir = path.join(settings.audioDir, episode.userId);

  const t0 = performance.now();
  const { filename, durationSeconds, fileSize } = await encode(
    episodeId,
    userAudioDir
  );
  const encodeDuration = (performance.now() - t0) / 1000;

  // Assign episode number and update atomically (advisory lock prevents races)
  const nextNumber = await db.transaction(async (tx) => {
    await tx.execute(
      sql`SELECT pg_advisory_xact_lock(hashtext(${episode.userId}))`
    );
    const [{ maxNum }] = await tx
      .select({
        maxNum: sql<number>`coalesce(max(${episodes.episodeNumber}), 0)`,
      })
      .from(episodes)
      .where(eq(episodes.userId, episode.userId));
    const next = (maxNum ?? 0) + 1;

    await tx
      .update(episodes)
      .set({
        audioFilename: filename,
        audioDurationSeconds: durationSeconds,
        audioSizeBytes: fileSize,
        episodeNumber: next,
      })
      .where(eq(episodes.id, episodeId));

    return next;
  });

  log.info(
    "Encoding complete for episode %s: %ds, %d bytes, episode #%d (%.1fs)",
    episodeId,
    durationSeconds,
    fileSize,
    nextNumber,
    encodeDuration
  );

  return {
    duration_seconds: Math.round(encodeDuration * 100) / 100,
    audio_duration_seconds: durationSeconds,
    output_size_bytes: fileSize,
  };
}
