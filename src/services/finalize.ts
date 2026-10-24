import { randomBytes } from "node:crypto";
import { and, eq, sql } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, jobs } from "../schema.js";
import { createLogger } from "../log.js";
import { parseMetrics } from "./cost.js";
import { concatMp3Parts } from "./mp3.js";
import { deleteObjects, getObject, publicUrl, putObject } from "./storage.js";
import { completeJob, startJob } from "./jobs.js";

const log = createLogger("finalize");

interface PartInfo {
  key: string;
  bytes: number;
  samples: number;
  sampleRate: number;
  durationSeconds: number;
}

export async function finalizeEpisode(episodeId: string): Promise<Record<string, unknown>> {
  const [episode] = await db.select().from(episodes).where(eq(episodes.id, episodeId)).limit(1);
  if (!episode) throw new Error(`Episode ${episodeId} not found`);

  const [ttsJob] = await db
    .select()
    .from(jobs)
    .where(and(eq(jobs.episodeId, episodeId), eq(jobs.step, "tts")))
    .limit(1);
  const ttsMetrics = parseMetrics(ttsJob?.metricsJson);
  const parts = (ttsMetrics?.parts as PartInfo[] | undefined) ?? [];
  if (ttsJob?.status !== "completed" || parts.length === 0) {
    throw new Error(`Episode ${episodeId} has no completed TTS parts to assemble`);
  }

  await startJob(episodeId, "encode");
  const t0 = performance.now();

  const buffers: Buffer[] = [];
  for (const part of parts) buffers.push(await getObject(part.key));
  const mp3 = concatMp3Parts(buffers);

  const samples = parts.reduce((s, p) => s + p.samples, 0);
  const durationSeconds = Math.round(samples / parts[0].sampleRate);
  const key = `episodes/${episodeId}/${randomBytes(12).toString("hex")}.mp3`;
  await putObject(key, mp3, "audio/mpeg");
  const audioUrl = publicUrl(key);

  const episodeNumber = await db.transaction(async (tx) => {
    await tx.execute(sql`SELECT pg_advisory_xact_lock(hashtext(${episode.userId}))`);
    let next = episode.episodeNumber;
    if (!next) {
      const [{ maxNum }] = await tx
        .select({ maxNum: sql<number>`coalesce(max(${episodes.episodeNumber}), 0)` })
        .from(episodes)
        .where(eq(episodes.userId, episode.userId));
      next = (maxNum ?? 0) + 1;
    }
    await tx
      .update(episodes)
      .set({
        audioUrl,
        audioDurationSeconds: durationSeconds,
        audioSizeBytes: mp3.length,
        episodeNumber: next,
        status: "ready",
        publishedAt: episode.publishedAt ?? new Date(),
        errorMessage: null,
        failedStep: null,
      })
      .where(eq(episodes.id, episodeId));
    return next;
  });

  try {
    await deleteObjects(parts.map((p) => p.key));
  } catch (e: any) {
    log.warn("Failed to delete TTS parts for episode %s: %s", episodeId, e.message);
  }

  const wall = (performance.now() - t0) / 1000;
  const metrics = {
    duration_seconds: Math.round(wall * 100) / 100,
    audio_duration_seconds: durationSeconds,
    output_size_bytes: mp3.length,
    parts: parts.length,
    cost_usd: 0,
  };
  await completeJob(episodeId, "encode", metrics);
  log.info(
    "Episode %s is ready: #%d, %ds, %d bytes, %s",
    episodeId,
    episodeNumber,
    durationSeconds,
    mp3.length,
    audioUrl
  );
  return metrics;
}
