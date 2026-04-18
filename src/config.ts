import "dotenv/config";
import { randomBytes } from "node:crypto";

function env(key: string, fallback = ""): string {
  return process.env[key] ?? fallback;
}

function normalizeDbUrl(url: string): string {
  // Strip asyncpg prefix if present (from Python config)
  return url.replace("postgresql+asyncpg://", "postgresql://");
}

export const settings = {
  databaseUrl: normalizeDbUrl(
    env("DATABASE_URL", "postgresql://podcast:podcast@localhost:9002/podcast")
  ),

  // LLM provider API keys
  anthropicApiKey: env("ANTHROPIC_API_KEY"),
  deepseekApiKey: env("DEEPSEEK_API_KEY"),
  googleApiKey: env("GOOGLE_API_KEY"),
  openaiApiKey: env("OPENAI_API_KEY"),
  perplexityApiKey: env("PERPLEXITY_API_KEY"),

  hfToken: env("HF_TOKEN"),
  audioDir: env("AUDIO_DIR", "/data/audio"),
  voiceRefsDir: env("VOICE_REFS_DIR", "/app/voice_refs"),
  baseUrl: env("BASE_URL", "http://localhost:9001"),
  apiPassword: env("API_PASSWORD"),
  registerToken: env("REGISTER_TOKEN"),
  sessionSecret: env("SESSION_SECRET") || (() => {
    console.warn("WARNING: SESSION_SECRET not set — using random value (sessions won't persist across restarts)");
    return randomBytes(32).toString("hex");
  })(),
  dailySpendLimit: parseFloat(env("DAILY_SPEND_LIMIT", "5.0")),

  // Modal TTS endpoint URL (set after deploying modal_app.py with web endpoint)
  modalTtsUrl: env("MODAL_TTS_URL"),
} as const;
