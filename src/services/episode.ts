import { eq, and, asc, desc, sql } from "drizzle-orm";
import { start } from "workflow/api";
import { db } from "../database.js";
import { episodes, episodeSources } from "../schema.js";
import { createLogger } from "../log.js";
import { generateTitle } from "./transcript.js";
import { deletePrefix } from "./storage.js";
import { generateEpisode } from "../../workflows/episode.js";
import type { PipelineStep } from "../view-helpers.js";

const log = createLogger("episode");

async function startPipeline(episodeId: string, fromStep: PipelineStep): Promise<string> {
  const run = await start(generateEpisode, [episodeId, fromStep]);
  await db.update(episodes).set({ workflowRunId: run.runId }).where(eq(episodes.id, episodeId));
  log.info("Started workflow run %s for episode %s from step %s", run.runId, episodeId, fromStep);
  return run.runId;
}

export interface EpisodeSourceInput {
  name: string;
  content: string;
}

export interface CreateEpisodeInput {
  topic: string;
  title?: string | null;
  description?: string | null;
  targetLengthMinutes: number;
  sources?: EpisodeSourceInput[];
  webSearch?: boolean;
}

export async function createEpisode(input: CreateEpisodeInput, userId: string) {
  const sources = input.sources ?? [];
  const title = input.title || (await generateTitle(input.topic)) || input.topic.slice(0, 100);

  const [episode] = await db
    .insert(episodes)
    .values({
      userId,
      title,
      topic: input.topic,
      description: input.description ?? null,
      targetLengthMinutes: input.targetLengthMinutes,
      webSearch: input.webSearch ?? sources.length === 0,
      status: "pending",
    })
    .returning();

  if (sources.length > 0) {
    await db.insert(episodeSources).values(
      sources.map((s, position) => ({ episodeId: episode.id, position, name: s.name, content: s.content }))
    );
    log.info(
      "Episode %s: stored %d source(s), %d chars",
      episode.id,
      sources.length,
      sources.reduce((sum, s) => sum + s.content.length, 0)
    );
  }

  await startPipeline(episode.id, "research");
  return episode;
}

export async function listEpisodeSources(episodeId: string) {
  return db
    .select({
      name: episodeSources.name,
      chars: sql<number>`length(${episodeSources.content})`.mapWith(Number),
    })
    .from(episodeSources)
    .where(eq(episodeSources.episodeId, episodeId))
    .orderBy(asc(episodeSources.position));
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

export async function deleteEpisode(episodeId: string, userId: string): Promise<boolean> {
  const episode = await getEpisode(episodeId, userId);
  if (!episode) return false;

  try {
    const removed = await deletePrefix(`episodes/${episodeId}/`);
    if (removed > 0) log.info("Deleted %d stored object(s) for episode %s", removed, episodeId);
  } catch (e: any) {
    log.warn("Failed to delete stored audio for episode %s: %s", episodeId, e.message);
  }

  await db.delete(episodes).where(eq(episodes.id, episodeId));
  return true;
}

export async function retryEpisode(episodeId: string, userId: string) {
  const episode = await getEpisode(episodeId, userId);
  if (!episode || episode.status !== "failed") return null;

  const step = (episode.failedStep || "research") as PipelineStep;
  await db
    .update(episodes)
    .set({ status: "pending", errorMessage: null, failedStep: null })
    .where(eq(episodes.id, episodeId));
  await startPipeline(episodeId, step);
  return getEpisode(episodeId, userId);
}
