import { eq, sql, and } from "drizzle-orm";
import { db } from "./database.js";
import { closePool } from "./database.js";
import { episodes, jobs } from "./schema.js";
import { settings } from "./config.js";
import {
  setupLogging,
  startFlushLoop,
  stopFlushLoop,
  createLogger,
} from "./log-handler.js";
import { runResearch } from "./services/research.js";
import { generateTranscript } from "./services/transcript.js";
import { synthesizeSpeech } from "./services/tts.js";
import { encodeMp3 } from "./services/encoder.js";
import { getAllModelPricing } from "./services/llm-providers.js";

setupLogging("worker");
const log = createLogger("worker");

type StepHandler = (episodeId: string) => Promise<Record<string, unknown>>;

const STEP_HANDLERS: Record<string, StepHandler> = {
  research: runResearch,
  transcript: generateTranscript,
  tts: synthesizeSpeech,
  encode: encodeMp3,
};

const NEXT_STEP: Record<string, string | null> = {
  research: "transcript",
  transcript: "tts",
  tts: "encode",
  encode: null,
};

const EPISODE_STATUS_MAP: Record<string, string> = {
  research: "researching",
  transcript: "writing_transcript",
  tts: "generating_audio",
  encode: "encoding",
};

const STEP_PRIORITY: Record<string, number> = {
  encode: 0,
  tts: 1,
  transcript: 2,
  research: 3,
};

const POLL_INTERVAL = 10_000;
const COSTLY_STEPS = new Set(["research", "transcript", "tts"]);

const MODEL_PRICING = getAllModelPricing();
const DEFAULT_PRICING = { input: 3.0, output: 15.0 };

let shutdown = false;

async function todaysSpend(): Promise<number> {
  const todayStart = new Date();
  todayStart.setUTCHours(0, 0, 0, 0);

  const completedJobs = await db
    .select()
    .from(jobs)
    .where(
      and(
        eq(jobs.status, "completed"),
        sql`${jobs.completedAt} >= ${todayStart}`
      )
    );

  let total = 0;
  for (const job of completedJobs) {
    if (!job.metricsJson) continue;
    const metrics = JSON.parse(job.metricsJson);
    const inputT = metrics.input_tokens ?? 0;
    const outputT = metrics.output_tokens ?? 0;
    const model = metrics.model ?? "";
    const pricing = MODEL_PRICING[model] ?? DEFAULT_PRICING;
    total +=
      (inputT * pricing.input + outputT * pricing.output) / 1_000_000;
  }
  return total;
}

async function processJob(
  jobId: string,
  episodeId: string,
  step: string
): Promise<Record<string, unknown> | null> {
  const handler = STEP_HANDLERS[step];
  if (!handler) throw new Error(`Unknown step: ${step}`);

  log.info("Processing job %s: step=%s, episode=%s", jobId, step, episodeId);
  const result = await handler(episodeId);
  return typeof result === "object" ? result : null;
}

async function recoverStaleJobs(): Promise<void> {
  const staleJobs = await db
    .select()
    .from(jobs)
    .where(eq(jobs.status, "running"));

  for (const job of staleJobs) {
    log.warn(
      "Recovering stale job %s (step=%s, episode=%s) — resetting to pending",
      job.id,
      job.step,
      job.episodeId
    );
    await db
      .update(jobs)
      .set({ status: "pending", startedAt: null })
      .where(eq(jobs.id, job.id));

    // Reset the episode status
    const [episode] = await db
      .select()
      .from(episodes)
      .where(eq(episodes.id, job.episodeId))
      .limit(1);
    if (episode && episode.status !== "failed") {
      await db
        .update(episodes)
        .set({
          status: EPISODE_STATUS_MAP[job.step] ?? episode.status,
        })
        .where(eq(episodes.id, job.episodeId));
    }
  }

  if (staleJobs.length > 0) {
    log.info("Recovered %d stale job(s)", staleJobs.length);
  }
}

async function pollJobs(): Promise<void> {
  while (!shutdown) {
    try {
      // Atomically claim the next pending job (SELECT FOR UPDATE + mark running in one tx)
      const claimed = await db.transaction(async (tx) => {
        const result = await tx.execute(sql`
          SELECT id, episode_id, step
          FROM jobs
          WHERE status = 'pending'
          ORDER BY
            CASE step
              WHEN 'encode' THEN 0
              WHEN 'tts' THEN 1
              WHEN 'transcript' THEN 2
              WHEN 'research' THEN 3
              ELSE 99
            END,
            created_at
          LIMIT 1
          FOR UPDATE SKIP LOCKED
        `);

        const rows = result.rows as Array<{
          id: string;
          episode_id: string;
          step: string;
        }>;
        if (!rows || rows.length === 0) return null;

        const { id, episode_id: episodeId, step } = rows[0];

        // Gate costly steps behind daily spend limit
        if (COSTLY_STEPS.has(step) && settings.dailySpendLimit > 0) {
          const spend = await todaysSpend();
          if (spend >= settings.dailySpendLimit) {
            log.warn(
              "Daily spend limit ($%.2f/$%.2f) reached — skipping %s job %s",
              spend,
              settings.dailySpendLimit,
              step,
              id
            );
            return null;
          }
        }

        // Mark as running
        await tx
          .update(jobs)
          .set({
            status: "running",
            startedAt: new Date(),
            attempts: sql`${jobs.attempts} + 1`,
          })
          .where(eq(jobs.id, id));

        return { id, episodeId, step };
      });

      if (!claimed) {
        await sleep(POLL_INTERVAL);
        continue;
      }

      const { id: jobId, episodeId, step } = claimed;

      // Update episode status
      await db
        .update(episodes)
        .set({ status: EPISODE_STATUS_MAP[step] ?? "pending" })
        .where(eq(episodes.id, episodeId));

      // Process the job
      try {
        const metrics = await processJob(jobId, episodeId, step);

        // Mark job complete
        await db
          .update(jobs)
          .set({
            status: "completed",
            completedAt: new Date(),
            metricsJson: metrics ? JSON.stringify(metrics) : null,
          })
          .where(eq(jobs.id, jobId));

        // Enqueue next step or mark as ready
        const nextStep = NEXT_STEP[step];
        if (nextStep) {
          await db.insert(jobs).values({
            episodeId,
            step: nextStep,
            status: "pending",
          });
          log.info(
            "Enqueued next step: %s for episode %s",
            nextStep,
            episodeId
          );
        } else {
          // Pipeline complete
          await db
            .update(episodes)
            .set({ status: "ready", publishedAt: new Date() })
            .where(eq(episodes.id, episodeId));
          log.info("Episode %s is ready!", episodeId);
        }
      } catch (e: any) {
        log.error("Job %s failed: %s", jobId, e.message);
        await db
          .update(jobs)
          .set({ status: "failed", errorMessage: String(e) })
          .where(eq(jobs.id, jobId));
        await db
          .update(episodes)
          .set({
            status: "failed",
            errorMessage: String(e),
            failedStep: step,
          })
          .where(eq(episodes.id, episodeId));
      }
    } catch (e: any) {
      log.error("Unexpected error in poll loop: %s", e.message);
      await sleep(POLL_INTERVAL);
    }
  }

  log.info("Worker shut down.");
}

async function main(): Promise<void> {
  log.info("Worker started, polling every %ds", POLL_INTERVAL / 1000);
  startFlushLoop();

  process.on("SIGTERM", () => {
    log.info("Received SIGTERM, shutting down gracefully...");
    shutdown = true;
  });
  process.on("SIGINT", () => {
    log.info("Received SIGINT, shutting down gracefully...");
    shutdown = true;
  });

  try {
    await recoverStaleJobs();
    await pollJobs();
  } finally {
    await stopFlushLoop();
    await closePool();
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

main().catch((err) => {
  console.error("Worker fatal error:", err);
  process.exit(1);
});
