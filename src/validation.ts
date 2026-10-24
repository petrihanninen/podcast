import { z } from "zod";

// ─── Episode ─────────────────────────────────────────────────────────
export const episodeCreateJsonSchema = z.object({
  topic: z.string().min(1).max(5000),
  title: z.string().max(200).nullish(),
  description: z.string().max(5000).nullish(),
  target_length_minutes: z.union([
    z.literal(15),
    z.literal(30),
    z.literal(60),
    z.literal(120),
  ]).default(30),
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
export type SettingsUpdate = z.infer<typeof settingsUpdateSchema>;
