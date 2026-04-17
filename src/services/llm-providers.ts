import { settings } from "../config.js";
import { getClient } from "./anthropic-client.js";
import { createLogger } from "../log-handler.js";

const log = createLogger("llm-providers");

// ─── Response type ───────────────────────────────────────────────────
export interface LLMResponse {
  text: string;
  inputTokens: number;
  outputTokens: number;
  model: string;
}

// ─── Model registry entry ────────────────────────────────────────────
export interface ModelInfo {
  id: string;
  provider: string;
  modelId: string;
  displayName: string;
  supportsWebSearch: boolean;
  pricing: { input: number; output: number };
}

// ─── Provider base URLs ──────────────────────────────────────────────
const PROVIDER_BASE_URLS: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  perplexity: "https://api.perplexity.ai",
  deepseek: "https://api.deepseek.com",
};

// ─── Provider: Anthropic ─────────────────────────────────────────────
async function completeAnthropic(
  modelId: string,
  system: string,
  userMessage: string,
  maxTokens: number,
  temperature: number,
  useWebSearch: boolean
): Promise<LLMResponse> {
  const client = getClient();

  const kwargs: Record<string, unknown> = {
    model: modelId,
    max_tokens: maxTokens,
    system,
    messages: [{ role: "user" as const, content: userMessage }],
  };
  if (temperature !== 1.0) kwargs.temperature = temperature;
  if (useWebSearch) {
    kwargs.tools = [
      { type: "web_search_20250305", name: "web_search", max_uses: 10 },
    ];
  }

  const response = await client.messages.create(kwargs as any);

  let text = "";
  for (const block of response.content) {
    if (block.type === "text") text += block.text;
  }

  return {
    text,
    inputTokens: response.usage.input_tokens,
    outputTokens: response.usage.output_tokens,
    model: modelId,
  };
}

// ─── Provider: OpenAI-compatible ─────────────────────────────────────
async function completeOpenAICompatible(
  baseUrl: string,
  apiKey: string,
  modelId: string,
  system: string,
  userMessage: string,
  maxTokens: number,
  temperature: number
): Promise<LLMResponse> {
  const tokenKey =
    baseUrl === PROVIDER_BASE_URLS.openai
      ? "max_completion_tokens"
      : "max_tokens";

  const payload: Record<string, unknown> = {
    model: modelId,
    messages: [
      { role: "system", content: system },
      { role: "user", content: userMessage },
    ],
    [tokenKey]: maxTokens,
    temperature,
    stream: false,
  };

  let lastError: Error | null = null;
  let data: any;

  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const res = await fetch(`${baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(300_000),
      });
      if (!res.ok) {
        const body = await res.text();
        if ([429, 500, 502, 503, 504].includes(res.status)) {
          const wait = Math.min(2 ** attempt * 2, 60);
          log.warn(
            "%s %s error %d (attempt %d/5), retrying in %ds",
            baseUrl,
            modelId,
            res.status,
            attempt + 1,
            wait
          );
          await sleep(wait * 1000);
          lastError = new Error(`HTTP ${res.status}: ${body}`);
          continue;
        }
        throw new Error(`HTTP ${res.status}: ${body}`);
      }
      data = await res.json();
      break;
    } catch (e: any) {
      lastError = e;
      if (e.name === "TimeoutError" || e.name === "AbortError") {
        const wait = Math.min(2 ** attempt * 2, 60);
        log.warn(
          "Timeout at %s (attempt %d/5), retrying in %ds",
          baseUrl,
          attempt + 1,
          wait
        );
        await sleep(wait * 1000);
        continue;
      }
      throw e;
    }
  }

  if (!data) {
    throw new Error(
      `API at ${baseUrl} (${modelId}) failed after 5 attempts: ${lastError?.message}`
    );
  }

  const usage = data.usage ?? {};
  return {
    text: data.choices[0].message.content,
    inputTokens: usage.prompt_tokens ?? 0,
    outputTokens: usage.completion_tokens ?? 0,
    model: modelId,
  };
}

// ─── Provider: OpenAI Responses API ──────────────────────────────────
async function completeOpenAIResponses(
  modelId: string,
  system: string,
  userMessage: string,
  maxTokens: number,
  temperature: number,
  useWebSearch: boolean
): Promise<LLMResponse> {
  const apiKey = settings.openaiApiKey;
  if (!apiKey) throw new Error("OPENAI_API_KEY is not configured");

  const payload: Record<string, unknown> = {
    model: modelId,
    instructions: system,
    input: userMessage,
    max_output_tokens: maxTokens,
    temperature,
  };
  if (useWebSearch) {
    payload.tools = [{ type: "web_search" }];
  }

  let lastError: Error | null = null;
  let data: any;

  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const res = await fetch("https://api.openai.com/v1/responses", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(300_000),
      });
      if (!res.ok) {
        const body = await res.text();
        if ([429, 500, 502, 503, 504].includes(res.status)) {
          const wait = Math.min(2 ** attempt * 2, 60);
          log.warn(
            "OpenAI Responses API %s error %d (attempt %d/5), retrying in %ds",
            modelId,
            res.status,
            attempt + 1,
            wait
          );
          await sleep(wait * 1000);
          lastError = new Error(`HTTP ${res.status}: ${body}`);
          continue;
        }
        throw new Error(`HTTP ${res.status}: ${body}`);
      }
      data = await res.json();
      break;
    } catch (e: any) {
      lastError = e;
      if (e.name === "TimeoutError" || e.name === "AbortError") {
        const wait = Math.min(2 ** attempt * 2, 60);
        log.warn(
          "OpenAI Responses API timeout (attempt %d/5), retrying in %ds",
          attempt + 1,
          wait
        );
        await sleep(wait * 1000);
        continue;
      }
      throw e;
    }
  }

  if (!data) {
    throw new Error(
      `OpenAI Responses API (${modelId}) failed after 5 attempts: ${lastError?.message}`
    );
  }

  const usage = data.usage ?? {};
  const status = data.status ?? "unknown";
  if (status !== "completed") {
    log.warn(
      "OpenAI Responses API returned status=%s (model=%s)",
      status,
      modelId
    );
  }

  let text = "";
  for (const item of data.output ?? []) {
    if (item.type === "message") {
      for (const block of item.content ?? []) {
        if (block.type === "output_text" || block.type === "text") {
          text += block.text ?? "";
        }
      }
    }
  }

  return {
    text,
    inputTokens: usage.input_tokens ?? 0,
    outputTokens: usage.output_tokens ?? 0,
    model: modelId,
  };
}

// ─── Provider: Google Gemini ─────────────────────────────────────────
async function completeGoogle(
  modelId: string,
  system: string,
  userMessage: string,
  maxTokens: number,
  temperature: number,
  useWebSearch: boolean
): Promise<LLMResponse> {
  const apiKey = settings.googleApiKey;
  if (!apiKey) throw new Error("GOOGLE_API_KEY is not configured");

  const url = `https://generativelanguage.googleapis.com/v1beta/models/${modelId}:generateContent`;
  const payload: Record<string, unknown> = {
    contents: [{ role: "user", parts: [{ text: userMessage }] }],
    systemInstruction: { parts: [{ text: system }] },
    generationConfig: { maxOutputTokens: maxTokens, temperature },
  };
  if (useWebSearch) {
    payload.tools = [{ google_search: {} }];
  }

  let lastError: Error | null = null;
  let data: any;

  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "x-goog-api-key": apiKey,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(300_000),
      });
      if (!res.ok) {
        const body = await res.text();
        if ([429, 500, 502, 503, 504].includes(res.status)) {
          const wait = Math.min(2 ** attempt * 2, 60);
          log.warn(
            "Gemini error %d (attempt %d/5), retrying in %ds",
            res.status,
            attempt + 1,
            wait
          );
          await sleep(wait * 1000);
          lastError = new Error(`HTTP ${res.status}: ${body}`);
          continue;
        }
        throw new Error(`HTTP ${res.status}: ${body}`);
      }
      data = await res.json();
      break;
    } catch (e: any) {
      lastError = e;
      if (e.name === "TimeoutError" || e.name === "AbortError") {
        const wait = Math.min(2 ** attempt * 2, 60);
        log.warn(
          "Gemini timeout (attempt %d/5), retrying in %ds",
          attempt + 1,
          wait
        );
        await sleep(wait * 1000);
        continue;
      }
      throw e;
    }
  }

  if (!data) {
    throw new Error(
      `Gemini API failed after 5 attempts: ${lastError?.message}`
    );
  }

  let text = "";
  for (const candidate of data.candidates ?? []) {
    for (const part of candidate.content?.parts ?? []) {
      text += part.text ?? "";
    }
  }

  const usage = data.usageMetadata ?? {};
  return {
    text,
    inputTokens: usage.promptTokenCount ?? 0,
    outputTokens: usage.candidatesTokenCount ?? 0,
    model: modelId,
  };
}

// ─── API key resolver ────────────────────────────────────────────────
function getApiKey(provider: string): string {
  const keyMap: Record<string, string> = {
    anthropic: settings.anthropicApiKey,
    google: settings.googleApiKey,
    openai: settings.openaiApiKey,
    perplexity: settings.perplexityApiKey,
    deepseek: settings.deepseekApiKey,
  };
  const key = keyMap[provider] ?? "";
  if (!key) {
    const upper = provider.toUpperCase();
    throw new Error(
      `${upper}_API_KEY is not configured. Set the ${upper}_API_KEY environment variable.`
    );
  }
  return key;
}

// ─── Model registries ────────────────────────────────────────────────
export const RESEARCH_MODELS: Record<string, ModelInfo> = {
  "gpt-nano": {
    id: "gpt-nano",
    provider: "openai",
    modelId: "gpt-5-nano-2025-08-07",
    displayName: "GPT-5 Nano",
    supportsWebSearch: true,
    pricing: { input: 0.05, output: 0.4 },
  },
};

export const TRANSCRIPT_MODELS: Record<string, ModelInfo> = {
  "gpt-mini": {
    id: "gpt-mini",
    provider: "openai",
    modelId: "gpt-5.4-mini-2026-03-17",
    displayName: "GPT 5.4-mini",
    supportsWebSearch: false,
    pricing: { input: 0.75, output: 4.5 },
  },
};

export const DEFAULT_RESEARCH_MODEL = "gpt-nano";
export const DEFAULT_TRANSCRIPT_MODEL = "gpt-mini";

// ─── Public helpers ──────────────────────────────────────────────────
export function getResearchModel(modelKey?: string | null): ModelInfo {
  const key = modelKey || DEFAULT_RESEARCH_MODEL;
  const model = RESEARCH_MODELS[key];
  if (!model) {
    throw new Error(
      `Unknown research model '${key}'. Available: ${Object.keys(RESEARCH_MODELS).join(", ")}`
    );
  }
  return model;
}

export function getTranscriptModel(modelKey?: string | null): ModelInfo {
  const key = modelKey || DEFAULT_TRANSCRIPT_MODEL;
  const model = TRANSCRIPT_MODELS[key];
  if (!model) {
    throw new Error(
      `Unknown transcript model '${key}'. Available: ${Object.keys(TRANSCRIPT_MODELS).join(", ")}`
    );
  }
  return model;
}

export function getAllModelPricing(): Record<
  string,
  { input: number; output: number }
> {
  const pricing: Record<string, { input: number; output: number }> = {};
  for (const registry of [RESEARCH_MODELS, TRANSCRIPT_MODELS]) {
    for (const info of Object.values(registry)) {
      pricing[info.modelId] = info.pricing;
    }
  }
  return pricing;
}

// ─── Universal completion ────────────────────────────────────────────
export async function complete(
  modelInfo: ModelInfo,
  system: string,
  userMessage: string,
  maxTokens = 8192,
  temperature = 1.0,
  useWebSearch = false
): Promise<LLMResponse> {
  const { provider } = modelInfo;

  if (provider === "anthropic") {
    return completeAnthropic(
      modelInfo.modelId,
      system,
      userMessage,
      maxTokens,
      temperature,
      useWebSearch && modelInfo.supportsWebSearch
    );
  }

  if (provider === "google") {
    return completeGoogle(
      modelInfo.modelId,
      system,
      userMessage,
      maxTokens,
      temperature,
      useWebSearch && modelInfo.supportsWebSearch
    );
  }

  if (
    provider === "openai" &&
    useWebSearch &&
    modelInfo.supportsWebSearch
  ) {
    return completeOpenAIResponses(
      modelInfo.modelId,
      system,
      userMessage,
      maxTokens,
      temperature,
      true
    );
  }

  const apiKey = getApiKey(provider);
  const baseUrl = PROVIDER_BASE_URLS[provider];
  if (!baseUrl) {
    throw new Error(
      `No base URL for provider '${provider}'. Add it to PROVIDER_BASE_URLS.`
    );
  }

  return completeOpenAICompatible(
    baseUrl,
    apiKey,
    modelInfo.modelId,
    system,
    userMessage,
    maxTokens,
    temperature
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
