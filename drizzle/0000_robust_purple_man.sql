CREATE TABLE "episodes" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"title" varchar(500) NOT NULL,
	"description" text,
	"topic" text NOT NULL,
	"target_length_minutes" integer DEFAULT 30 NOT NULL,
	"status" varchar(50) DEFAULT 'pending' NOT NULL,
	"error_message" text,
	"failed_step" varchar(50),
	"research_model" varchar(100),
	"transcript_model" varchar(100),
	"research_notes" text,
	"transcript" text,
	"audio_filename" varchar(255),
	"audio_duration_seconds" integer,
	"audio_size_bytes" bigint,
	"episode_number" integer,
	"published_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "jobs" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"episode_id" uuid NOT NULL,
	"step" varchar(50) NOT NULL,
	"status" varchar(50) DEFAULT 'pending' NOT NULL,
	"error_message" text,
	"attempts" integer DEFAULT 0 NOT NULL,
	"max_attempts" integer DEFAULT 3 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"metrics_json" text
);
--> statement-breakpoint
CREATE TABLE "log_entries" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"timestamp" timestamp with time zone DEFAULT now() NOT NULL,
	"level" varchar(10) NOT NULL,
	"logger_name" varchar(255) NOT NULL,
	"message" text NOT NULL,
	"source" varchar(10) NOT NULL
);
--> statement-breakpoint
CREATE TABLE "podcast_settings" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"user_id" uuid NOT NULL,
	"title" varchar(500) DEFAULT 'My Private Podcast' NOT NULL,
	"description" text DEFAULT 'AI-generated podcast episodes' NOT NULL,
	"author" varchar(255) DEFAULT 'Podcast Bot' NOT NULL,
	"language" varchar(10) DEFAULT 'en' NOT NULL,
	"image_url" varchar(1000),
	"host_a_name" varchar(100) DEFAULT 'Alex' NOT NULL,
	"host_b_name" varchar(100) DEFAULT 'Sam' NOT NULL,
	"voice_ref_a_path" varchar(500),
	"voice_ref_b_path" varchar(500),
	"transcript_tone_notes" text,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "podcast_settings_user_id_unique" UNIQUE("user_id")
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"shoo_sub" varchar(255) NOT NULL,
	"email" varchar(320),
	"enabled" boolean DEFAULT true NOT NULL,
	"is_admin" boolean DEFAULT false NOT NULL,
	"feed_token" varchar(64) NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "users_shoo_sub_unique" UNIQUE("shoo_sub"),
	CONSTRAINT "users_feed_token_unique" UNIQUE("feed_token")
);
--> statement-breakpoint
ALTER TABLE "episodes" ADD CONSTRAINT "episodes_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "jobs" ADD CONSTRAINT "jobs_episode_id_episodes_id_fk" FOREIGN KEY ("episode_id") REFERENCES "public"."episodes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "podcast_settings" ADD CONSTRAINT "podcast_settings_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "idx_episodes_status" ON "episodes" USING btree ("status");--> statement-breakpoint
CREATE INDEX "idx_episodes_published_at" ON "episodes" USING btree ("published_at");--> statement-breakpoint
CREATE INDEX "idx_episodes_user_id" ON "episodes" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "idx_jobs_status" ON "jobs" USING btree ("status","created_at");--> statement-breakpoint
CREATE INDEX "idx_jobs_episode_id" ON "jobs" USING btree ("episode_id");--> statement-breakpoint
CREATE INDEX "idx_log_entries_timestamp" ON "log_entries" USING btree ("timestamp");--> statement-breakpoint
CREATE INDEX "idx_log_entries_level" ON "log_entries" USING btree ("level");--> statement-breakpoint
CREATE INDEX "idx_log_entries_source" ON "log_entries" USING btree ("source");