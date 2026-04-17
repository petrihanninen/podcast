import Anthropic from "@anthropic-ai/sdk";
import { settings } from "../config.js";

let client: Anthropic | null = null;

export function getClient(): Anthropic {
  if (!client) {
    client = new Anthropic({
      apiKey: settings.anthropicApiKey,
      maxRetries: 5,
    });
  }
  return client;
}
