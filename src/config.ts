import "dotenv/config";
import { randomBytes } from "node:crypto";

function env(key: string, fallback = ""): string {
  return process.env[key] ?? fallback;
}

function defaultBaseUrl(): string {
  if (process.env.BASE_URL) return process.env.BASE_URL;
  const vercelHost =
    process.env.VERCEL_PROJECT_PRODUCTION_URL || process.env.VERCEL_URL;
  if (vercelHost) return `https://${vercelHost}`;
  return "http://localhost:3000";
}

export const settings = {
  databaseUrl: env("DATABASE_URL", "postgresql://podcast:podcast@localhost:9002/podcast"),

  anthropicApiKey: env("ANTHROPIC_API_KEY"),
  googleApiKey: env("GOOGLE_API_KEY"),
  openaiApiKey: env("OPENAI_API_KEY"),
  deepinfraApiKey: env("DEEPINFRA_API_KEY"),

  openaiBaseUrl: env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
  geminiBaseUrl: env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
  deepinfraBaseUrl: env("DEEPINFRA_BASE_URL", "https://api.deepinfra.com"),

  researchModel: env("RESEARCH_MODEL"),
  transcriptModel: env("TRANSCRIPT_MODEL"),
  ttsModel: env("TTS_MODEL"),
  ttsConcurrency: parseInt(env("TTS_CONCURRENCY", "4"), 10),
  ttsBatchSize: parseInt(env("TTS_BATCH_SIZE", "12"), 10),
  ttsParallelBatches: parseInt(env("TTS_PARALLEL_BATCHES", "4"), 10),
  mp3Kbps: parseInt(env("MP3_KBPS", "64"), 10),

  storage: {
    endpoint: env("STORAGE_ENDPOINT"),
    region: env("STORAGE_REGION", "auto"),
    bucket: env("STORAGE_BUCKET"),
    accessKeyId: env("STORAGE_ACCESS_KEY_ID"),
    secretAccessKey: env("STORAGE_SECRET_ACCESS_KEY"),
    publicUrl: env("STORAGE_PUBLIC_URL").replace(/\/$/, ""),
    forcePathStyle: env("STORAGE_FORCE_PATH_STYLE", "true") !== "false",
  },

  baseUrl: defaultBaseUrl(),
  apiPassword: env("API_PASSWORD"),
  registerToken: env("REGISTER_TOKEN"),
  sessionSecret: env("SESSION_SECRET") || (() => {
    console.warn("WARNING: SESSION_SECRET not set — using a random value, sessions will not survive restarts or span instances");
    return randomBytes(32).toString("hex");
  })(),
  dailySpendLimit: parseFloat(env("DAILY_SPEND_LIMIT", "5.0")),
} as const;
