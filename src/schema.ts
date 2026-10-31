import {
  pgTable,
  uuid,
  varchar,
  text,
  boolean,
  timestamp,
  integer,
  bigint,
  real,
  index,
  uniqueIndex,
} from "drizzle-orm/pg-core";
import { relations } from "drizzle-orm";
import { randomUUID } from "node:crypto";

// ─── Users ───────────────────────────────────────────────────────────
export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom().$defaultFn(() => randomUUID()),
  shooSub: varchar("shoo_sub", { length: 255 }).notNull().unique(),
  email: varchar("email", { length: 320 }),
  enabled: boolean("enabled").notNull().default(true),
  isAdmin: boolean("is_admin").notNull().default(false),
  feedToken: varchar("feed_token", { length: 64 }).notNull().unique(),
  apiToken: varchar("api_token", { length: 64 }).unique(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .notNull()
    .defaultNow(),
});

export const usersRelations = relations(users, ({ many, one }) => ({
  episodes: many(episodes),
  settings: one(podcastSettings),
}));

// ─── Episodes ────────────────────────────────────────────────────────
export const episodes = pgTable(
  "episodes",
  {
    id: uuid("id").primaryKey().defaultRandom().$defaultFn(() => randomUUID()),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    title: varchar("title", { length: 500 }).notNull(),
    description: text("description"),
    topic: text("topic").notNull(),
    targetLengthMinutes: integer("target_length_minutes").notNull().default(30),
    webSearch: boolean("web_search").notNull().default(true),

    status: varchar("status", { length: 50 }).notNull().default("pending"),
    errorMessage: text("error_message"),
    failedStep: varchar("failed_step", { length: 50 }),
    workflowRunId: varchar("workflow_run_id", { length: 255 }),

    researchModel: varchar("research_model", { length: 100 }),
    transcriptModel: varchar("transcript_model", { length: 100 }),

    researchNotes: text("research_notes"),
    transcript: text("transcript"),

    audioUrl: text("audio_url"),
    audioDurationSeconds: integer("audio_duration_seconds"),
    audioSizeBytes: bigint("audio_size_bytes", { mode: "number" }),

    episodeNumber: integer("episode_number"),
    publishedAt: timestamp("published_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true })
      .notNull()
      .defaultNow()
      .$onUpdate(() => new Date()),
  },
  (table) => [
    index("idx_episodes_status").on(table.status),
    index("idx_episodes_published_at").on(table.publishedAt),
    index("idx_episodes_user_id").on(table.userId),
  ]
);

export const episodesRelations = relations(episodes, ({ one, many }) => ({
  user: one(users, { fields: [episodes.userId], references: [users.id] }),
  jobs: many(jobs),
  sources: many(episodeSources),
}));

// ─── Episode sources (material supplied with the brief) ──────────────
export const episodeSources = pgTable(
  "episode_sources",
  {
    id: uuid("id").primaryKey().defaultRandom().$defaultFn(() => randomUUID()),
    episodeId: uuid("episode_id")
      .notNull()
      .references(() => episodes.id, { onDelete: "cascade" }),
    position: integer("position").notNull().default(0),
    name: varchar("name", { length: 500 }).notNull(),
    content: text("content").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (table) => [index("idx_episode_sources_episode_id").on(table.episodeId)]
);

export const episodeSourcesRelations = relations(episodeSources, ({ one }) => ({
  episode: one(episodes, {
    fields: [episodeSources.episodeId],
    references: [episodes.id],
  }),
}));

// ─── Jobs (one row per pipeline step per episode) ────────────────────
export const jobs = pgTable(
  "jobs",
  {
    id: uuid("id").primaryKey().defaultRandom().$defaultFn(() => randomUUID()),
    episodeId: uuid("episode_id")
      .notNull()
      .references(() => episodes.id, { onDelete: "cascade" }),
    step: varchar("step", { length: 50 }).notNull(),
    status: varchar("status", { length: 50 }).notNull().default("pending"),
    errorMessage: text("error_message"),
    attempts: integer("attempts").notNull().default(0),

    progressDone: integer("progress_done").notNull().default(0),
    progressTotal: integer("progress_total").notNull().default(0),
    progressSeconds: real("progress_seconds").notNull().default(0),

    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    metricsJson: text("metrics_json"),
  },
  (table) => [
    uniqueIndex("idx_jobs_episode_step").on(table.episodeId, table.step),
    index("idx_jobs_status").on(table.status, table.createdAt),
  ]
);

export const jobsRelations = relations(jobs, ({ one }) => ({
  episode: one(episodes, {
    fields: [jobs.episodeId],
    references: [episodes.id],
  }),
}));

// ─── Podcast Settings ────────────────────────────────────────────────
export const podcastSettings = pgTable("podcast_settings", {
  id: uuid("id").primaryKey().defaultRandom().$defaultFn(() => randomUUID()),
  userId: uuid("user_id")
    .notNull()
    .unique()
    .references(() => users.id, { onDelete: "cascade" }),
  title: varchar("title", { length: 500 }).notNull().default("My Private Podcast"),
  description: text("description")
    .notNull()
    .default("AI-generated podcast episodes"),
  author: varchar("author", { length: 255 }).notNull().default("Podcast Bot"),
  language: varchar("language", { length: 10 }).notNull().default("en"),
  imageUrl: varchar("image_url", { length: 1000 }),

  hostAName: varchar("host_a_name", { length: 100 }).notNull().default("Alex"),
  hostBName: varchar("host_b_name", { length: 100 }).notNull().default("Sam"),
  ttsVoiceA: varchar("tts_voice_a", { length: 255 }),
  ttsVoiceB: varchar("tts_voice_b", { length: 255 }),
  transcriptToneNotes: text("transcript_tone_notes"),

  updatedAt: timestamp("updated_at", { withTimezone: true })
    .notNull()
    .defaultNow()
    .$onUpdate(() => new Date()),
});

export const podcastSettingsRelations = relations(
  podcastSettings,
  ({ one }) => ({
    user: one(users, {
      fields: [podcastSettings.userId],
      references: [users.id],
    }),
  })
);

// ─── TTS voices (cloned voice ids cached per reference audio) ────────
export const ttsVoices = pgTable(
  "tts_voices",
  {
    id: uuid("id").primaryKey().defaultRandom().$defaultFn(() => randomUUID()),
    provider: varchar("provider", { length: 50 }).notNull(),
    refHash: varchar("ref_hash", { length: 64 }).notNull(),
    voiceId: varchar("voice_id", { length: 255 }).notNull(),
    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (table) => [
    uniqueIndex("idx_tts_voices_provider_ref").on(table.provider, table.refHash),
  ]
);

// ─── Type exports ────────────────────────────────────────────────────
export type User = typeof users.$inferSelect;
export type Episode = typeof episodes.$inferSelect;
export type Job = typeof jobs.$inferSelect;
export type EpisodeSource = typeof episodeSources.$inferSelect;
export type PodcastSettings = typeof podcastSettings.$inferSelect;
export type TtsVoice = typeof ttsVoices.$inferSelect;
