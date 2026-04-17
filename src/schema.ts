import {
  pgTable,
  uuid,
  varchar,
  text,
  boolean,
  timestamp,
  integer,
  bigint,
  index,
  uniqueIndex,
  bigserial,
} from "drizzle-orm/pg-core";
import { relations } from "drizzle-orm";

// ─── Users ───────────────────────────────────────────────────────────
export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  shooSub: varchar("shoo_sub", { length: 255 }).notNull().unique(),
  email: varchar("email", { length: 320 }),
  enabled: boolean("enabled").notNull().default(true),
  isAdmin: boolean("is_admin").notNull().default(false),
  feedToken: varchar("feed_token", { length: 64 }).notNull().unique(),
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
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    title: varchar("title", { length: 500 }).notNull(),
    description: text("description"),
    topic: text("topic").notNull(),
    targetLengthMinutes: integer("target_length_minutes").notNull().default(30),

    status: varchar("status", { length: 50 }).notNull().default("pending"),
    errorMessage: text("error_message"),
    failedStep: varchar("failed_step", { length: 50 }),

    researchModel: varchar("research_model", { length: 100 }),
    transcriptModel: varchar("transcript_model", { length: 100 }),

    researchNotes: text("research_notes"),
    transcript: text("transcript"),

    audioFilename: varchar("audio_filename", { length: 255 }),
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
}));

// ─── Jobs ────────────────────────────────────────────────────────────
export const jobs = pgTable(
  "jobs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    episodeId: uuid("episode_id")
      .notNull()
      .references(() => episodes.id, { onDelete: "cascade" }),
    step: varchar("step", { length: 50 }).notNull(),
    status: varchar("status", { length: 50 }).notNull().default("pending"),
    errorMessage: text("error_message"),
    attempts: integer("attempts").notNull().default(0),
    maxAttempts: integer("max_attempts").notNull().default(3),

    createdAt: timestamp("created_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    metricsJson: text("metrics_json"),
  },
  (table) => [
    index("idx_jobs_status").on(table.status, table.createdAt),
    index("idx_jobs_episode_id").on(table.episodeId),
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
  id: uuid("id").primaryKey().defaultRandom(),
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
  voiceRefAPath: varchar("voice_ref_a_path", { length: 500 }),
  voiceRefBPath: varchar("voice_ref_b_path", { length: 500 }),
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

// ─── Log Entries ─────────────────────────────────────────────────────
export const logEntries = pgTable(
  "log_entries",
  {
    id: bigserial("id", { mode: "number" }).primaryKey(),
    timestamp: timestamp("timestamp", { withTimezone: true })
      .notNull()
      .defaultNow(),
    level: varchar("level", { length: 10 }).notNull(),
    loggerName: varchar("logger_name", { length: 255 }).notNull(),
    message: text("message").notNull(),
    source: varchar("source", { length: 10 }).notNull(),
  },
  (table) => [
    index("idx_log_entries_timestamp").on(table.timestamp),
    index("idx_log_entries_level").on(table.level),
    index("idx_log_entries_source").on(table.source),
  ]
);

// ─── Type exports ────────────────────────────────────────────────────
export type User = typeof users.$inferSelect;
export type Episode = typeof episodes.$inferSelect;
export type Job = typeof jobs.$inferSelect;
export type PodcastSettings = typeof podcastSettings.$inferSelect;
export type LogEntry = typeof logEntries.$inferSelect;
