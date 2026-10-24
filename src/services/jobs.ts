import { and, eq, sql } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, jobs } from "../schema.js";
import { EPISODE_STATUS_FOR_STEP, type PipelineStep } from "../view-helpers.js";
import { createLogger } from "../log.js";

const log = createLogger("jobs");

export async function startJob(episodeId: string, step: PipelineStep): Promise<string> {
  const now = new Date();
  const [job] = await db
    .insert(jobs)
    .values({
      episodeId,
      step,
      status: "running",
      attempts: 1,
      startedAt: now,
      completedAt: null,
      errorMessage: null,
      metricsJson: null,
    })
    .onConflictDoUpdate({
      target: [jobs.episodeId, jobs.step],
      set: {
        status: "running",
        attempts: sql`${jobs.attempts} + 1`,
        startedAt: now,
        completedAt: null,
        errorMessage: null,
        metricsJson: null,
        progressDone: 0,
        progressTotal: 0,
        progressSeconds: 0,
      },
    })
    .returning({ id: jobs.id });

  await db
    .update(episodes)
    .set({ status: EPISODE_STATUS_FOR_STEP[step], errorMessage: null, failedStep: null })
    .where(eq(episodes.id, episodeId));

  log.info("Episode %s: step %s started", episodeId, step);
  return job.id;
}

export async function completeJob(
  episodeId: string,
  step: PipelineStep,
  metrics: Record<string, unknown>
): Promise<void> {
  await db
    .update(jobs)
    .set({ status: "completed", completedAt: new Date(), metricsJson: JSON.stringify(metrics) })
    .where(and(eq(jobs.episodeId, episodeId), eq(jobs.step, step)));
  log.info("Episode %s: step %s completed", episodeId, step);
}

export async function failJob(
  episodeId: string,
  step: PipelineStep,
  message: string
): Promise<void> {
  await db
    .update(jobs)
    .set({ status: "failed", completedAt: new Date(), errorMessage: message })
    .where(and(eq(jobs.episodeId, episodeId), eq(jobs.step, step)));
  await db
    .update(episodes)
    .set({ status: "failed", errorMessage: message, failedStep: step })
    .where(eq(episodes.id, episodeId));
  log.error("Episode %s: step %s failed: %s", episodeId, step, message);
}

export async function setJobProgressTotal(
  episodeId: string,
  step: PipelineStep,
  total: number
): Promise<void> {
  await db
    .update(jobs)
    .set({ progressTotal: total, progressDone: 0, progressSeconds: 0 })
    .where(and(eq(jobs.episodeId, episodeId), eq(jobs.step, step)));
}

export async function addJobProgress(
  episodeId: string,
  step: PipelineStep,
  done: number,
  seconds: number
): Promise<void> {
  await db
    .update(jobs)
    .set({
      progressDone: sql`${jobs.progressDone} + ${done}`,
      progressSeconds: sql`${jobs.progressSeconds} + ${seconds}`,
    })
    .where(and(eq(jobs.episodeId, episodeId), eq(jobs.step, step)));
}
