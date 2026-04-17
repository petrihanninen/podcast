import { z } from "zod";
import path from "node:path";

// ─── Episode ─────────────────────────────────────────────────────────
export const episodeCreateSchema = z.object({
  topic: z.string().min(1).max(5000),
  title: z.string().max(200).nullish(),
  description: z.string().max(5000).nullish(),
  target_length_minutes: z.enum(["15", "30", "60", "120"]).transform(Number).default("30"),
});

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
function validateVoiceFilename(v: string | null | undefined): string | null {
  if (v == null || v === "") return null;
  const basename = path.basename(v);
  if (basename !== v || v.includes("..")) {
    throw new Error("Must be a simple filename, not a path");
  }
  return basename;
}

export const settingsUpdateSchema = z.object({
  title: z.string().max(200).nullish(),
  description: z.string().max(2000).nullish(),
  author: z.string().max(200).nullish(),
  language: z.string().max(10).nullish(),
  image_url: z.string().max(500).nullish(),
  host_a_name: z.string().max(50).nullish(),
  host_b_name: z.string().max(50).nullish(),
  voice_ref_a_path: z.string().nullish().transform(validateVoiceFilename),
  voice_ref_b_path: z.string().nullish().transform(validateVoiceFilename),
  transcript_tone_notes: z.array(z.string()).max(20).nullish(),
});

export type EpisodeCreate = z.infer<typeof episodeCreateJsonSchema>;
export type SettingsUpdate = z.infer<typeof settingsUpdateSchema>;
