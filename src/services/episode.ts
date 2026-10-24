import fs from "node:fs";
import path from "node:path";
import { eq, and, sql, desc } from "drizzle-orm";
import { db, type Db } from "../database.js";
import { episodes, jobs } from "../schema.js";
import { settings } from "../config.js";
import { generateTitle } from "./transcript.js";
import { createLogger } from "../log-handler.js";

const log = createLogger("episode");

export async function createEpisode(
  topic: string,
  title: string | null | undefined,
  description: string | null | undefined,
  targetLengthMinutes: number,
  userId: string
) {
  if (!title) {
    title = (await generateTitle(topic)) ?? topic.slice(0, 100);
  }

  return await db.transaction(async (tx) => {
    const [episode] = await tx
      .insert(episodes)
      .values({
        userId,
        title: title!,
        topic,
        description: description ?? null,
        targetLengthMinutes,
        status: "pending",
      })
      .returning();

    await tx.insert(jobs).values({
      episodeId: episode.id,
      step: "research",
      status: "pending",
    });

    return episode;
  });
}

export async function listEpisodes(userId: string) {
  return db.query.episodes.findMany({
    where: eq(episodes.userId, userId),
    with: { jobs: true },
    orderBy: [desc(episodes.createdAt)],
  });
}

export async function getEpisode(episodeId: string, userId: string) {
  return db.query.episodes.findFirst({
    where: and(eq(episodes.id, episodeId), eq(episodes.userId, userId)),
    with: { jobs: true },
  });
}

export async function deleteEpisode(
  episodeId: string,
  userId: string
): Promise<boolean> {
  const episode = await getEpisode(episodeId, userId);
  if (!episode) return false;

  // Clean up audio files
  const userAudioDir = path.join(settings.audioDir, userId);
  if (episode.audioFilename) {
    try {
      const safeName = path.basename(episode.audioFilename);
      const audioPath = path.join(userAudioDir, safeName);
      if (fs.existsSync(audioPath)) {
        const resolved = fs.realpathSync(audioPath);
        const resolvedDir = fs.realpathSync(userAudioDir);
        if (resolved.startsWith(resolvedDir + path.sep)) {
          fs.unlinkSync(resolved);
        } else {
          log.warn("Refusing to delete file outside audio dir: %s", audioPath);
        }
      }
    } catch (e: any) {
      log.warn("Failed to clean up audio file: %s", e.message);
    }
  }

  // Clean up segments directory
  const segmentsDir = path.join(userAudioDir, "segments", episode.id);
  if (fs.existsSync(segmentsDir)) {
    fs.rmSync(segmentsDir, { recursive: true });
  }

  await db.delete(episodes).where(eq(episodes.id, episodeId));
  return true;
}

export async function retryEpisode(episodeId: string, userId: string) {
  const episode = await getEpisode(episodeId, userId);
  if (!episode || episode.status !== "failed") return null;

  const step = episode.failedStep || "research";

  await db
    .update(episodes)
    .set({ status: "pending", errorMessage: null, failedStep: null })
    .where(eq(episodes.id, episodeId));

  await db.insert(jobs).values({
    episodeId: episode.id,
    step,
    status: "pending",
  });

  return getEpisode(episodeId, userId);
}
