import { settings } from "../config.js";
import { getClient } from "./anthropic-client.js";
import { createLogger } from "../log-handler.js";

const log = createLogger("llm-providers");

export interface LLMResponse {
  text: string;
  inputTokens: number;
  outputTokens: number;
  searchQueries: number;
  costUsd: number;
  model: string;
}

export interface ModelInfo {
  id: string;
  provider: "openai" | "google" | "anthropic";
  modelId: string;
  displayName: string;
  supportsWebSearch: boolean;
  pricing: { input: number; output: number; perSearch: number };
}

export interface CompletionRequest {
  system: string;
  user: string;
  maxTokens: number;
  webSearch?: boolean;
  effort?: "low" | "medium" | "high";
}

// Prices are USD per 1M tokens (list price, Oct 2026) and USD per search query.
export const MODELS: Record<string, ModelInfo> = {
  "gemini-flash": {
    id: "gemini-flash",
    provider: "google",
    modelId: "gemini-3.8-flash",
    displayName: "Gemini 3.8 Flash",
    supportsWebSearch: true,
    pricing: { input: 0.75, output: 3.75, perSearch: 0 },
  },
  "gemini-flash-lite": {
    id: "gemini-flash-lite",
    provider: "google",
    modelId: "gemini-3.5-flash-lite",
    displayName: "Gemini 3.5 Flash-Lite",
    supportsWebSearch: true,
    pricing: { input: 0.3, output: 2.5, perSearch: 0 },
  },
  "gpt-luna": {
    id: "gpt-luna",
    provider: "openai",
    modelId: "gpt-5.6-luna",
    displayName: "GPT-5.6 Luna",
    supportsWebSearch: true,
    pricing: { input: 0.2, output: 1.2, perSearch: 0.01 },
  },
  "gpt-6-luna": {
    id: "gpt-6-luna",
    provider: "openai",
    modelId: "gpt-6-luna",
    displayName: "GPT-6 Luna",
    supportsWebSearch: true,
    pricing: { input: 0.1, output: 0.5, perSearch: 0.01 },
  },
  "claude-haiku": {
    id: "claude-haiku",
    provider: "anthropic",
    modelId: "claude-haiku-5-5",
    displayName: "Claude Haiku 5.5",
    supportsWebSearch: false,
    pricing: { input: 0.1, output: 0.5, perSearch: 0 },
  },
};

export const DEFAULT_RESEARCH_MODEL = "gemini-flash";
export const DEFAULT_TRANSCRIPT_MODEL = "gpt-luna";

function resolveModel(key: string, purpose: string): ModelInfo {
  const model = MODELS[key];
  if (!model) {
    throw new Error(
      `Unknown ${purpose} model '${key}'. Available: ${Object.keys(MODELS).join(", ")}`
    );
  }
  return model;
}

export function getResearchModel(modelKey?: string | null): ModelInfo {
  const model = resolveModel(
    modelKey || settings.researchModel || DEFAULT_RESEARCH_MODEL,
    "research"
  );
  if (!model.supportsWebSearch) {
    throw new Error(`Research model '${model.id}' does not support web search`);
  }
  return model;
}

export function getTranscriptModel(modelKey?: string | null): ModelInfo {
  return resolveModel(
    modelKey || settings.transcriptModel || DEFAULT_TRANSCRIPT_MODEL,
    "transcript"
  );
}

export function getModelPricing(
  modelId: string
): { input: number; output: number } | null {
  for (const info of Object.values(MODELS)) {
    if (info.modelId === modelId) return info.pricing;
  }
  return null;
}

function costOf(
  model: ModelInfo,
  inputTokens: number,
  outputTokens: number,
  searchQueries: number
): number {
  const p = model.pricing;
  return (
    (inputTokens * p.input + outputTokens * p.output) / 1_000_000 +
    searchQueries * p.perSearch
  );
}

async function postJson(
  url: string,
  headers: Record<string, string>,
  payload: unknown,
  label: string
): Promise<any> {
  let lastError: Error | null = null;
  for (let attempt = 0; attempt < 5; attempt++) {
    let retryable = false;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(600_000),
      });
      if (res.ok) return await res.json();
      const body = await res.text();
      lastError = new Error(`${label} HTTP ${res.status}: ${body.slice(0, 2000)}`);
      retryable = RETRYABLE_STATUS.has(res.status);
    } catch (e: any) {
      lastError = e;
      retryable = isNetworkError(e);
    }
    if (!retryable) throw lastError;
    const wait = Math.min(2 ** attempt * 2, 60);
    log.warn("%s failed (attempt %d/5): %s — retrying in %ds", label, attempt + 1, lastError?.message, wait);
    await new Promise((r) => setTimeout(r, wait * 1000));
  }
  throw new Error(`${label} failed after 5 attempts: ${lastError?.message}`);
}

export const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

export function isNetworkError(e: any): boolean {
  return (
    e?.name === "TimeoutError" ||
    e?.name === "AbortError" ||
    (e?.name === "TypeError" && /fetch failed/i.test(String(e?.message)))
  );
}

async function completeOpenAI(model: ModelInfo, req: CompletionRequest): Promise<LLMResponse> {
  if (!settings.openaiApiKey) throw new Error("OPENAI_API_KEY is not configured");

  const payload: Record<string, unknown> = {
    model: model.modelId,
    instructions: req.system,
    input: req.user,
    max_output_tokens: req.maxTokens,
    store: false,
  };
  if (req.effort) payload.reasoning = { effort: req.effort };
  if (req.webSearch) payload.tools = [{ type: "web_search" }];

  const data = await postJson(
    "https://api.openai.com/v1/responses",
    { Authorization: `Bearer ${settings.openaiApiKey}` },
    payload,
    `OpenAI ${model.modelId}`
  );

  if (data.status && data.status !== "completed") {
    log.warn("OpenAI response status=%s (model=%s)", data.status, model.modelId);
  }

  let text = "";
  let searchQueries = 0;
  for (const item of data.output ?? []) {
    if (item.type === "web_search_call") searchQueries++;
    if (item.type !== "message") continue;
    for (const block of item.content ?? []) {
      if (block.type === "output_text") text += block.text ?? "";
    }
  }

  const inputTokens = data.usage?.input_tokens ?? 0;
  const outputTokens = data.usage?.output_tokens ?? 0;
  return {
    text,
    inputTokens,
    outputTokens,
    searchQueries,
    costUsd: costOf(model, inputTokens, outputTokens, searchQueries),
    model: model.modelId,
  };
}

async function completeGoogle(model: ModelInfo, req: CompletionRequest): Promise<LLMResponse> {
  if (!settings.googleApiKey) throw new Error("GOOGLE_API_KEY is not configured");

  const payload: Record<string, unknown> = {
    model: model.modelId,
    system_instruction: req.system,
    input: req.user,
    generation_config: {
      max_output_tokens: req.maxTokens,
      ...(req.effort ? { thinking_level: req.effort } : {}),
    },
    store: false,
  };
  if (req.webSearch) payload.tools = [{ type: "google_search" }];

  const data = await postJson(
    "https://generativelanguage.googleapis.com/v1beta/interactions",
    { "x-goog-api-key": settings.googleApiKey },
    payload,
    `Gemini ${model.modelId}`
  );

  if (data.status && data.status !== "completed") {
    log.warn("Gemini interaction status=%s (model=%s)", data.status, model.modelId);
  }

  let text = "";
  let searchQueries = 0;
  for (const step of data.steps ?? []) {
    if (step.type === "google_search_call") {
      searchQueries += Math.max(1, step.arguments?.queries?.length ?? 1);
    }
    if (step.type !== "model_output") continue;
    for (const block of step.content ?? []) {
      if (block.type === "text") text += block.text ?? "";
    }
  }

  const usage = data.usage ?? {};
  const inputTokens = usage.total_input_tokens ?? usage.prompt_tokens ?? 0;
  const outputTokens =
    (usage.total_output_tokens ?? usage.completion_tokens ?? 0) +
    (usage.total_thought_tokens ?? 0);
  return {
    text,
    inputTokens,
    outputTokens,
    searchQueries,
    costUsd: costOf(model, inputTokens, outputTokens, searchQueries),
    model: model.modelId,
  };
}

async function completeAnthropic(model: ModelInfo, req: CompletionRequest): Promise<LLMResponse> {
  if (!settings.anthropicApiKey) throw new Error("ANTHROPIC_API_KEY is not configured");

  const response = await getClient()
    .messages.stream({
      model: model.modelId,
      max_tokens: req.maxTokens,
      system: req.system,
      messages: [{ role: "user", content: req.user }],
    })
    .finalMessage();

  let text = "";
  for (const block of response.content) {
    if (block.type === "text") text += block.text;
  }
  const inputTokens = response.usage.input_tokens;
  const outputTokens = response.usage.output_tokens;
  return {
    text,
    inputTokens,
    outputTokens,
    searchQueries: 0,
    costUsd: costOf(model, inputTokens, outputTokens, 0),
    model: model.modelId,
  };
}

export async function complete(model: ModelInfo, req: CompletionRequest): Promise<LLMResponse> {
  if (req.webSearch && !model.supportsWebSearch) {
    throw new Error(`Model '${model.id}' does not support web search`);
  }
  switch (model.provider) {
    case "openai":
      return completeOpenAI(model, req);
    case "google":
      return completeGoogle(model, req);
    case "anthropic":
      return completeAnthropic(model, req);
  }
}
