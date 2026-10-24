import type { FastifyInstance } from "fastify";
import { eq, desc } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings, type User } from "../schema.js";
import { requireAuthPage, requireAdminPage } from "../auth.js";
import {
  createEpisode,
  getEpisode,
  listEpisodes,
} from "../services/episode.js";
import { getTtsProgress as readTtsProgress, type TtsProgress } from "../services/tts.js";
import { parseMetrics, stepCost } from "../services/cost.js";
import { DEFAULT_TONE_NOTES } from "../services/transcript.js";
import { renderTemplate } from "../server.js";

// ─── Template helpers ────────────────────────────────────────────────
export function statusBadge(status: string): string {
  const mapping: Record<string, string> = {
    ready: "badge--success",
    failed: "badge--error",
    pending: "badge--info",
  };
  return mapping[status] ?? "badge--warning";
}

export function statusLabel(status: string): string {
  const mapping: Record<string, string> = {
    pending: "Pending",
    researching: "Researching",
    writing_transcript: "Writing transcript",
    generating_audio: "Generating audio",
    encoding: "Encoding",
    ready: "Ready",
    failed: "Failed",
  };
  return mapping[status] ?? status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "";
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

export function formatFileSize(sizeBytes: number | null): string {
  if (sizeBytes == null) return "";
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024)
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

const PIPELINE_STEPS = ["research", "transcript", "tts", "encode"];
const STEP_LABELS: Record<string, string> = {
  research: "Research",
  transcript: "Transcript",
  tts: "Audio",
  encode: "Encode",
};

export function buildPipelineInfo(episode: any): Array<Record<string, unknown>> {
  const jobsByStep: Record<string, any> = {};
  for (const job of episode.jobs ?? []) {
    jobsByStep[job.step] = job;
  }

  return PIPELINE_STEPS.map((stepName) => {
    const job = jobsByStep[stepName];
    if (job) {
      let duration = null;
      if (job.startedAt && job.completedAt) {
        const totalSecs = Math.round(
          (new Date(job.completedAt).getTime() -
            new Date(job.startedAt).getTime()) /
            1000
        );
        duration =
          totalSecs >= 60
            ? `${Math.floor(totalSecs / 60)}m ${totalSecs % 60}s`
            : `${totalSecs}s`;
      }
      return {
        name: stepName,
        label: STEP_LABELS[stepName],
        status: job.status,
        attempts: job.attempts,
        duration,
      };
    }
    return {
      name: stepName,
      label: STEP_LABELS[stepName],
      status: "waiting",
      attempts: 0,
      duration: null,
    };
  });
}

export function getCurrentStepIndex(episode: any): number {
  if (episode.status === "ready") return PIPELINE_STEPS.length;
  const jobsByStep: Record<string, any> = {};
  for (const job of episode.jobs ?? []) {
    jobsByStep[job.step] = job;
  }
  for (let i = 0; i < PIPELINE_STEPS.length; i++) {
    const job = jobsByStep[PIPELINE_STEPS[i]];
    if (!job || job.status === "pending" || job.status === "running") return i;
  }
  return PIPELINE_STEPS.length;
}

export function getTtsProgress(episode: any): TtsProgress | null {
  if (episode.status !== "generating_audio") return null;
  return readTtsProgress(episode.id);
}

function html(reply: any, content: string) {
  return reply.header("Content-Type", "text/html").send(content);
}

export async function pageRoutes(app: FastifyInstance) {
  // Shoo callback
  app.get("/shoo/callback", async (_request, reply) => {
    return html(reply, renderTemplate("auth_callback.html", {}));
  });

  // Home — new episode form
  app.get("/", async (request, reply) => {
    const user = await requireAuthPage(request, reply);
    return html(reply, renderTemplate("episode_new.html", { user }));
  });

  // Create episode via form POST
  app.post("/", async (request, reply) => {
    const user = await requireAuthPage(request, reply);
    const form = request.body as Record<string, string>;
    const topic = (form.topic || "").trim();
    const title = (form.title || "").trim() || null;
    let targetLength = parseInt(form.target_length_minutes || "30", 10);
    if (![15, 30, 60, 120].includes(targetLength)) targetLength = 30;

    if (!topic) {
      return html(
        reply,
        renderTemplate("episode_new.html", {
          error: "Topic is required",
          user,
        })
      );
    }

    const episode = await createEpisode(
      topic,
      title,
      null,
      targetLength,
      user.id
    );
    return reply.code(303).redirect( `/episodes/${episode.id}`);
  });

  // Also handle POST /episodes/new for the form
  app.post("/episodes/new", async (request, reply) => {
    const user = await requireAuthPage(request, reply);
    const form = request.body as Record<string, string>;
    const topic = (form.topic || "").trim();
    const title = (form.title || "").trim() || null;
    let targetLength = parseInt(form.target_length_minutes || "30", 10);
    if (![15, 30, 60, 120].includes(targetLength)) targetLength = 30;

    if (!topic) {
      return html(
        reply,
        renderTemplate("episode_new.html", {
          error: "Topic is required",
          user,
        })
      );
    }

    const episode = await createEpisode(
      topic,
      title,
      null,
      targetLength,
      user.id
    );
    return reply.code(303).redirect( `/episodes/${episode.id}`);
  });

  // Episode list
  app.get("/episodes", async (request, reply) => {
    const user = await requireAuthPage(request, reply);
    const eps = await listEpisodes(user.id);
    return html(
      reply,
      renderTemplate("index.html", { episodes: eps, user })
    );
  });

  // Legacy redirect
  app.get("/episodes/new", async (_request, reply) => {
    return reply.code(301).redirect( "/");
  });

  // Episode detail
  app.get<{ Params: { episodeId: string } }>(
    "/episodes/:episodeId",
    async (request, reply) => {
      const user = await requireAuthPage(request, reply);
      const episode = await getEpisode(request.params.episodeId, user.id);
      if (!episode) {
        return reply.code(404).header("Content-Type", "text/html").send("Not found");
      }
      return html(
        reply,
        renderTemplate("episode_detail.html", { episode, user })
      );
    }
  );

  // Logs page (admin)
  app.get("/logs", async (request, reply) => {
    const user = await requireAdminPage(request, reply);
    return html(reply, renderTemplate("logs.html", { user }));
  });

  // Settings page
  app.get("/settings", async (request, reply) => {
    const user = await requireAuthPage(request, reply);
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

    let toneNotes = [...DEFAULT_TONE_NOTES];
    if (s.transcriptToneNotes) {
      try {
        const parsed = JSON.parse(s.transcriptToneNotes);
        if (Array.isArray(parsed)) toneNotes = parsed;
      } catch {}
    }

    return html(
      reply,
      renderTemplate("settings.html", { settings: s, tone_notes: toneNotes, user })
    );
  });

  // Settings form POST
  app.post("/settings", async (request, reply) => {
    const user = await requireAuthPage(request, reply);
    const form = request.body as Record<string, string>;

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
    const fieldMap: Record<string, string> = {
      title: "title",
      description: "description",
      author: "author",
      language: "language",
      host_a_name: "hostAName",
      host_b_name: "hostBName",
    };

    for (const [formField, dbField] of Object.entries(fieldMap)) {
      const value = (form[formField] || "").trim();
      if (value) updateData[dbField] = value;
    }

    if (Object.keys(updateData).length > 0) {
      await db
        .update(podcastSettings)
        .set(updateData)
        .where(eq(podcastSettings.userId, user.id));
    }

    return reply.code(303).redirect( "/settings");
  });

  // Metrics page (admin)
  app.get("/metrics", async (request, reply) => {
    const user = await requireAdminPage(request, reply);

    const allEpisodes = await db.query.episodes.findMany({
      with: { jobs: true },
      orderBy: [desc(episodes.createdAt)],
    });

    const totals = {
      episodes: 0,
      episodes_ready: 0,
      total_input_tokens: 0,
      total_output_tokens: 0,
      total_search_queries: 0,
      total_cost: 0,
      total_llm_cost: 0,
      total_tts_cost: 0,
      total_audio_seconds: 0,
      total_generation_seconds: 0,
      total_tts_seconds: 0,
    };

    const episodeRows = allEpisodes.map((ep) => {
      totals.episodes++;
      if (ep.status === "ready") totals.episodes_ready++;

      const steps: Record<string, Record<string, unknown>> = {};
      let inputTokens = 0;
      let outputTokens = 0;
      let cost = 0;
      let wallTotal = 0;

      for (const job of ep.jobs) {
        const wall =
          job.startedAt && job.completedAt
            ? Math.round(((job.completedAt.getTime() - job.startedAt.getTime()) / 1000) * 100) / 100
            : null;
        if (wall !== null) wallTotal += wall;

        const metrics = job.status === "completed" ? parseMetrics(job.metricsJson) : null;
        if (!metrics) {
          if (wall !== null) steps[job.step] = { wall_seconds: wall };
          continue;
        }

        const stepCostUsd = stepCost(metrics);
        steps[job.step] = { ...metrics, cost_usd: stepCostUsd, wall_seconds: wall };
        inputTokens += Number(metrics.input_tokens ?? 0);
        outputTokens += Number(metrics.output_tokens ?? 0);
        totals.total_search_queries += Number(metrics.search_queries ?? 0);
        cost += stepCostUsd;
        if (job.step === "tts") {
          totals.total_tts_seconds += Number(metrics.duration_seconds ?? 0);
          totals.total_tts_cost += stepCostUsd;
        } else {
          totals.total_llm_cost += stepCostUsd;
        }
      }

      totals.total_input_tokens += inputTokens;
      totals.total_output_tokens += outputTokens;
      totals.total_cost += cost;
      totals.total_generation_seconds += wallTotal;
      if (ep.audioDurationSeconds) totals.total_audio_seconds += ep.audioDurationSeconds;

      return {
        id: ep.id,
        title: ep.title,
        status: ep.status,
        episode_number: ep.episodeNumber,
        audio_duration_seconds: ep.audioDurationSeconds,
        audio_size_bytes: ep.audioSizeBytes,
        created_at: ep.createdAt,
        steps,
        total_input_tokens: inputTokens,
        total_output_tokens: outputTokens,
        total_cost: cost,
        total_duration_seconds: wallTotal,
      };
    });

    const ttsEpisodes = episodeRows.filter((row) => row.steps.tts?.segment_count);

    return html(
      reply,
      renderTemplate("metrics.html", {
        totals,
        episodes: episodeRows,
        tts_episodes: ttsEpisodes,
        user,
      })
    );
  });
}
