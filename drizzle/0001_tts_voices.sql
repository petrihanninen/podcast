CREATE TABLE "tts_voices" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"provider" varchar(50) NOT NULL,
	"ref_hash" varchar(64) NOT NULL,
	"voice_id" varchar(255) NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX "idx_tts_voices_provider_ref" ON "tts_voices" USING btree ("provider","ref_hash");