import { z } from "zod";

// ─── Episode ─────────────────────────────────────────────────────────
export const MAX_SOURCES = 200;
export const MAX_SOURCE_CHARS = 1_500_000;

export const episodeSourceSchema = z.object({
  name: z.string().trim().min(1).max(500),
  content: z.string().min(1),
});

export const episodeCreateJsonSchema = z
  .object({
    topic: z.string().trim().min(1).max(5000),
    title: z.string().max(200).nullish(),
    description: z.string().max(5000).nullish(),
    target_length_minutes: z
      .union([z.literal(15), z.literal(30), z.literal(60), z.literal(120)])
      .default(30),
    sources: z.array(episodeSourceSchema).max(MAX_SOURCES).default([]),
    web_search: z.boolean().optional(),
  })
  .check((ctx) => {
    const total = ctx.value.sources.reduce((sum, s) => sum + s.content.length, 0);
    if (total > MAX_SOURCE_CHARS) {
      ctx.issues.push({
        code: "too_big",
        origin: "array",
        maximum: MAX_SOURCE_CHARS,
        inclusive: true,
        message: `Sources total ${total} characters; the limit is ${MAX_SOURCE_CHARS}`,
        input: ctx.value.sources,
        path: ["sources"],
      });
    }
  });

// ─── Settings ────────────────────────────────────────────────────────
export const settingsUpdateSchema = z.object({
  title: z.string().max(200).nullish(),
  description: z.string().max(2000).nullish(),
  author: z.string().max(200).nullish(),
  language: z.string().max(10).nullish(),
  image_url: z.string().max(500).nullish(),
  host_a_name: z.string().max(50).nullish(),
  host_b_name: z.string().max(50).nullish(),
  tts_voice_a: z.string().max(255).nullish(),
  tts_voice_b: z.string().max(255).nullish(),
  transcript_tone_notes: z.array(z.string()).max(20).nullish(),
});

export type EpisodeCreate = z.infer<typeof episodeCreateJsonSchema>;
export type EpisodeSourceInput = z.infer<typeof episodeSourceSchema>;
export type SettingsUpdate = z.infer<typeof settingsUpdateSchema>;
