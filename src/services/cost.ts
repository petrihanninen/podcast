import { getModelPricing } from "./llm-providers.js";

export function tokenCost(
  inputTokens: number,
  outputTokens: number,
  pricing: { input: number; output: number }
): number {
  return (inputTokens * pricing.input + outputTokens * pricing.output) / 1_000_000;
}

export function stepCost(metrics: Record<string, unknown> | null | undefined): number {
  if (!metrics) return 0;
  if (typeof metrics.cost_usd === "number") return metrics.cost_usd;
  const model = typeof metrics.model === "string" ? metrics.model : "";
  const pricing = getModelPricing(model);
  if (!pricing) return 0;
  return tokenCost(Number(metrics.input_tokens ?? 0), Number(metrics.output_tokens ?? 0), pricing);
}

export function parseMetrics(json: string | null | undefined): Record<string, unknown> | null {
  if (!json) return null;
  try {
    const parsed = JSON.parse(json);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}
