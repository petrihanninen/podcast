import type { FastifyInstance, FastifyRequest, FastifyReply } from "fastify";
import { eq, sql, desc, and, ilike } from "drizzle-orm";
import { db } from "../database.js";
import {
  episodes,
  jobs,
  logEntries,
  podcastSettings,
  type User,
} from "../schema.js";
import { requireAuth, requireAdmin } from "../auth.js";
import { episodeCreateJsonSchema, settingsUpdateSchema } from "../validation.js";
import {
  createEpisode,
  deleteEpisode,
  getEpisode,
  listEpisodes,
  retryEpisode,
} from "../services/episode.js";
import { getTtsProgress } from "../services/tts.js";
import { getAllModelPricing } from "../services/llm-providers.js";

const MODEL_PRICING = getAllModelPricing();
const DEFAULT_PRICING = { input: 3.0, output: 15.0 };

function calcCost(
  inputTokens: number,
  outputTokens: number,
  model = ""
): number {
  const pricing = MODEL_PRICING[model] ?? DEFAULT_PRICING;
  return (
    (inputTokens * pricing.input + outputTokens * pricing.output) / 1_000_000
  );
}

function escapeLike(s: string): string {
  return s.replace(/[%_\\]/g, "\\$&");
}

export async function apiRoutes(app: FastifyInstance) {
  // Health check
  app.get("/api/health", async () => ({ status: "ok" }));

  // ─── Episodes ────────────────────────────────────────────────
  app.post("/api/episodes", async (request, reply) => {
    const user: User = await requireAuth(request, reply);
    const data = episodeCreateJsonSchema.parse(request.body);
    const episode = await createEpisode(
      data.topic,
      data.title,
      data.description,
      data.target_length_minutes,
      user.id
    );
    // Refetch with jobs
    const full = await getEpisode(episode.id, user.id);
    return full;
  });

  app.get("/api/episodes", async (request, reply) => {
    const user: User = await requireAuth(request, reply);
    const eps = await listEpisodes(user.id);
    return eps.map((ep) => {
      const ttsProgress =
        ep.status === "generating_audio" ? getTtsProgress(ep.id) : null;
      return { ...ep, ttsProgress };
    });
  });

  app.get<{ Params: { episodeId: string } }>(
    "/api/episodes/:episodeId",
    async (request, reply) => {
      const user: User = await requireAuth(request, reply);
      const episode = await getEpisode(request.params.episodeId, user.id);
      if (!episode) {
        return reply.code(404).send({ error: "Episode not found" });
      }
      const ttsProgress =
        episode.status === "generating_audio"
          ? getTtsProgress(episode.id)
          : null;
      return { ...episode, ttsProgress };
    }
  );

  app.delete<{ Params: { episodeId: string } }>(
    "/api/episodes/:episodeId",
    async (request, reply) => {
      const user: User = await requireAuth(request, reply);
      const deleted = await deleteEpisode(request.params.episodeId, user.id);
      if (!deleted) {
        return reply.code(404).send({ error: "Episode not found" });
      }
      return { status: "deleted" };
    }
  );

  app.post<{ Params: { episodeId: string } }>(
    "/api/episodes/:episodeId/retry",
    async (request, reply) => {
      const user: User = await requireAuth(request, reply);
      const episode = await retryEpisode(request.params.episodeId, user.id);
      if (!episode) {
        return reply
          .code(400)
          .send({ error: "Episode not found or not in failed state" });
      }
      return episode;
    }
  );

  // ─── Logs ────────────────────────────────────────────────────
  app.get<{
    Querystring: {
      page?: string;
      page_size?: string;
      level?: string;
      source?: string;
      search?: string;
    };
  }>("/api/logs", async (request, reply) => {
    await requireAdmin(request, reply);
    const page = Math.max(1, parseInt(request.query.page || "1", 10));
    const pageSize = Math.min(
      500,
      Math.max(1, parseInt(request.query.page_size || "100", 10))
    );
    const { level, source, search } = request.query;

    const conditions = [];
    if (level) conditions.push(eq(logEntries.level, level.toUpperCase()));
    if (source) conditions.push(eq(logEntries.source, source.toLowerCase()));
    if (search) conditions.push(ilike(logEntries.message, `%${escapeLike(search)}%`));

    const where =
      conditions.length > 0 ? and(...conditions) : undefined;
    const offset = (page - 1) * pageSize;

    const [logsResult, [{ total }]] = await Promise.all([
      db
        .select()
        .from(logEntries)
        .where(where)
        .orderBy(desc(logEntries.timestamp))
        .offset(offset)
        .limit(pageSize),
      db
        .select({ total: sql<number>`count(*)` })
        .from(logEntries)
        .where(where),
    ]);

    return {
      logs: logsResult,
      total,
      page,
      page_size: pageSize,
      has_more: offset + pageSize < total,
    };
  });

  // ─── Settings ────────────────────────────────────────────────
  app.get("/api/settings", async (request, reply) => {
    const user: User = await requireAuth(request, reply);
    let [s] = await db
      .select()
      .from(podcastSettings)
      .where(eq(podcastSettings.userId, user.id))
      .limit(1);
    if (!s) {
      [s] = await db
        .insert(podcastSettings)
        .values({ userId: user.id })
        .returning();
    }
    return s;
  });

  app.put("/api/settings", async (request, reply) => {
    const user: User = await requireAuth(request, reply);
    const data = settingsUpdateSchema.parse(request.body);

    let [s] = await db
      .select()
      .from(podcastSettings)
      .where(eq(podcastSettings.userId, user.id))
      .limit(1);
    if (!s) {
      [s] = await db
        .insert(podcastSettings)
        .values({ userId: user.id })
        .returning();
    }

    const updateData: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(data)) {
      if (value === undefined) continue;
      if (key === "transcript_tone_notes" && Array.isArray(value)) {
        updateData.transcriptToneNotes = JSON.stringify(value);
      } else {
        // Convert snake_case to camelCase for Drizzle
        const camelKey = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
        updateData[camelKey] = value;
      }
    }

    if (Object.keys(updateData).length > 0) {
      await db
        .update(podcastSettings)
        .set(updateData)
        .where(eq(podcastSettings.userId, user.id));
    }

    const [updated] = await db
      .select()
      .from(podcastSettings)
      .where(eq(podcastSettings.userId, user.id))
      .limit(1);
    return updated;
  });

  // ─── Metrics ─────────────────────────────────────────────────
  app.get("/api/metrics", async (request, reply) => {
    await requireAdmin(request, reply);

    const allEpisodes = await db.query.episodes.findMany({
      with: { jobs: true },
      orderBy: [desc(episodes.createdAt)],
    });

    const totals = {
      episodes: 0,
      episodes_ready: 0,
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_cost: 0,
      total_audio_seconds: 0,
      total_generation_seconds: 0,
      total_tts_seconds: 0,
    };

    const episodeMetrics = allEpisodes.map((ep) => {
      totals.episodes++;
      if (ep.status === "ready") totals.episodes_ready++;

      const epData: Record<string, unknown> = {
        id: ep.id,
        title: ep.title,
        status: ep.status,
        episode_number: ep.episodeNumber,
        audio_duration_seconds: ep.audioDurationSeconds,
        audio_size_bytes: ep.audioSizeBytes,
        created_at: ep.createdAt?.toISOString(),
        steps: {} as Record<string, unknown>,
        total_input_tokens: 0,
        total_output_tokens: 0,
        total_cost: 0,
        total_duration_seconds: 0,
      };

      for (const job of ep.jobs) {
        if (job.status !== "completed" || !job.metricsJson) {
          if (job.startedAt && job.completedAt) {
            const wall =
              (job.completedAt.getTime() - job.startedAt.getTime()) / 1000;
            (epData.steps as any)[job.step] = {
              wall_seconds: Math.round(wall * 100) / 100,
            };
            (epData.total_duration_seconds as number) += wall;
          }
          continue;
        }

        const metrics = JSON.parse(job.metricsJson);
        const stepData: Record<string, unknown> = { ...metrics };

        if (job.startedAt && job.completedAt) {
          const wall =
            (job.completedAt.getTime() - job.startedAt.getTime()) / 1000;
          stepData.wall_seconds = Math.round(wall * 100) / 100;
          (epData.total_duration_seconds as number) += wall;
        }

        (epData.steps as any)[job.step] = stepData;

        const inputT = metrics.input_tokens ?? 0;
        const outputT = metrics.output_tokens ?? 0;
        (epData.total_input_tokens as number) += inputT;
        (epData.total_output_tokens as number) += outputT;
        totals.total_input_tokens += inputT;
        totals.total_output_tokens += outputT;

        (epData.total_cost as number) += calcCost(
          inputT,
          outputT,
          metrics.model ?? ""
        );

        if (job.step === "tts") {
          totals.total_tts_seconds += metrics.duration_seconds ?? 0;
        }
      }

      totals.total_cost += epData.total_cost as number;
      totals.total_generation_seconds += epData.total_duration_seconds as number;
      if (ep.audioDurationSeconds) {
        totals.total_audio_seconds += ep.audioDurationSeconds;
      }

      return epData;
    });

    return { totals, episodes: episodeMetrics };
  });
}
