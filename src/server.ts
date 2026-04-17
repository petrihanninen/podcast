import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Fastify from "fastify";
import fastifyCookie from "@fastify/cookie";
import fastifyFormbody from "@fastify/formbody";
import fastifyStatic from "@fastify/static";
import nunjucks from "nunjucks";

import { settings } from "./config.js";
import { RequiresLogin, RequiresRegistration } from "./auth.js";
import { setupLogging, startFlushLoop, stopFlushLoop } from "./log-handler.js";
import { apiRoutes } from "./routes/api.js";
import { authRoutes } from "./routes/auth.js";
import { feedRoutes } from "./routes/feed.js";
import { pageRoutes, statusBadge, statusLabel, formatDuration, formatFileSize, buildPipelineInfo, getCurrentStepIndex, getTtsProgress } from "./routes/pages.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ─── Nunjucks setup ──────────────────────────────────────────────────
const nunjucksEnv = nunjucks.configure(
  path.join(__dirname, "..", "templates"),
  { autoescape: true, noCache: process.env.NODE_ENV !== "production" }
);

// Register template globals (matching the Python Jinja2 globals)
nunjucksEnv.addGlobal("status_badge", statusBadge);
nunjucksEnv.addGlobal("status_label", statusLabel);
nunjucksEnv.addGlobal("format_duration", formatDuration);
nunjucksEnv.addGlobal("format_file_size", formatFileSize);
nunjucksEnv.addGlobal("build_pipeline_info", buildPipelineInfo);
nunjucksEnv.addGlobal("get_current_step_index", getCurrentStepIndex);
nunjucksEnv.addGlobal("get_tts_progress", getTtsProgress);

// Register filters
nunjucksEnv.addFilter("from_json", (value: string) => {
  try {
    return JSON.parse(value);
  } catch {
    return [];
  }
});

// Date formatting filter (replaces Python's strftime)
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
nunjucksEnv.addFilter("date", (value: Date | string | null, fmt: string) => {
  if (!value) return "";
  const d = typeof value === "string" ? new Date(value) : value;
  if (isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return fmt
    .replace("%b", MONTHS[d.getMonth()])
    .replace("%d", String(d.getDate()))
    .replace("%Y", String(d.getFullYear()))
    .replace("%H", pad(d.getHours()))
    .replace("%M", pad(d.getMinutes()));
});

export function renderTemplate(
  name: string,
  context: Record<string, unknown>
): string {
  return nunjucksEnv.render(name, context);
}

// ─── Ensure audio directory exists ───────────────────────────────────
fs.mkdirSync(settings.audioDir, { recursive: true });
fs.mkdirSync(path.join(settings.audioDir, "segments"), { recursive: true });

// ─── Configure logging ──────────────────────────────────────────────
setupLogging("web");

// ─── Fastify app ─────────────────────────────────────────────────────
const app = Fastify({ logger: false });

// Plugins
await app.register(fastifyCookie);
await app.register(fastifyFormbody);

// Static files
await app.register(fastifyStatic, {
  root: path.join(__dirname, "..", "static"),
  prefix: "/static/",
  decorateReply: false,
});
await app.register(fastifyStatic, {
  root: settings.audioDir,
  prefix: "/audio/",
  decorateReply: false,
});

// ─── Error handlers ─────────────────────────────────────────────────
app.setErrorHandler((error: any, request, reply) => {
  if (error instanceof RequiresLogin) {
    return reply
      .code(303)
      .redirect(`/auth/login?next=${encodeURIComponent(error.nextUrl)}`);
  }
  if (error instanceof RequiresRegistration) {
    return reply
      .code(403)
      .header("Content-Type", "text/html")
      .send(renderTemplate("not_registered.html", {}));
  }
  // Default error handling
  reply.code(error.statusCode ?? 500).send({
    error: error.message || "Internal Server Error",
  });
});

// ─── Register routes ─────────────────────────────────────────────────
await app.register(authRoutes);
await app.register(apiRoutes);
await app.register(feedRoutes);
await app.register(pageRoutes);

// ─── Start ──────────────────────────────────────────────────────────
const port = parseInt(process.env.PORT || "9001", 10);

startFlushLoop();

const shutdown = async () => {
  await stopFlushLoop();
  await app.close();
  process.exit(0);
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

await app.listen({ port, host: "0.0.0.0" });
console.log(`Server listening on http://0.0.0.0:${port}`);
