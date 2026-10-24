# Podcast Generator

Auto-generates two-host podcast episodes from a topic. Research notes are grounded with web search, a script is written by an LLM, and the dialogue is voiced with [Chatterbox Turbo](https://huggingface.co/ResembleAI/chatterbox-turbo) voice cloning served by [DeepInfra](https://deepinfra.com). Comes with a web UI, a durable per-episode pipeline, and an RSS feed you can subscribe to from any podcast app.

It runs on Vercel's free Hobby plan: the Fastify app is one Vercel Function, each episode is a [Vercel Workflow](https://vercel.com/docs/workflows) run whose steps stay under the 300-second function limit, Postgres lives on [Neon](https://neon.tech), and the MP3s are stored in any S3-compatible bucket (Cloudflare R2, Backblaze B2, Neon Object Storage).

Default host voices are samples from [LibriVox](https://librivox.org/) public domain audiobooks (`voice_refs/`). They are uploaded to DeepInfra once as cloned voices; you can also paste your own DeepInfra voice IDs on the Settings page.

## Pipeline

Each episode is one workflow run: **research → transcript → TTS → encode**.

| Step | What happens | Default model |
|---|---|---|
| Research | One web-grounded LLM call producing research notes | Gemini 3.8 Flash + Google Search grounding (`gemini-flash`) |
| Transcript | 1–4 LLM calls (long episodes are outlined first, then written part by part), then a title | GPT-5.6 Luna (`gpt-luna`) |
| TTS | Dialogue lines are synthesized in batches of `TTS_BATCH_SIZE` lines; each batch is its own workflow step that encodes its audio to MP3 (LAME via WebAssembly, no ffmpeg) and uploads it; `TTS_PARALLEL_BATCHES` batches run at once | Chatterbox Turbo on DeepInfra (`chatterbox-turbo`) |
| Encode | Downloads the MP3 parts, concatenates them, uploads the final file, publishes the episode | — |

Approximate cost of a 30-minute episode at list prices (October 2026): research ≈ $0.04 (the first 5,000 Google Search grounding queries per month are free), transcript ≈ $0.01, TTS ≈ $0.03, total **≈ $0.10**. Every step records its own `cost_usd`, visible on the admin Metrics page, and new steps pause until the next UTC day once the day's estimated spend passes `DAILY_SPEND_LIMIT`. Failed episodes can be retried from the failed step.

Alternatives: `RESEARCH_MODEL` accepts `gemini-flash-lite`, `gpt-luna`, `gpt-6-luna` (OpenAI web search costs $0.01 per query); `TRANSCRIPT_MODEL` accepts `gpt-6-luna`, `gemini-flash`, `gemini-flash-lite`, `claude-haiku`.

## Deploying to Vercel

1. **Database**: add Neon from the Vercel Marketplace (free plan) or create a Neon project yourself; use the pooled connection string as `DATABASE_URL`.
2. **Audio storage**: create an S3-compatible bucket with public reads and set `STORAGE_ENDPOINT`, `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY_ID`, `STORAGE_SECRET_ACCESS_KEY` and `STORAGE_PUBLIC_URL` (the public base URL of the bucket). Cloudflare R2 (10 GB and all egress free, needs a custom domain on a Cloudflare zone for production URLs), Backblaze B2 (10 GB free, public "friendly" URLs without DNS) and Neon Object Storage (5 GB free per project) all work.
3. **Keys**: `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `DEEPINFRA_API_KEY`, plus `SESSION_SECRET` (`openssl rand -hex 32`) and `REGISTER_TOKEN`.
4. Import the repository in Vercel. Nitro is detected automatically (`npm run build`). In the project settings enable **Environment Variables → Enable access to System Environment Variables**; Workflow needs `VERCEL_DEPLOYMENT_ID` to pick the Vercel backend, otherwise every run fails on the read-only filesystem.
5. Apply the schema once against production: `DATABASE_URL=... npm run db:migrate`.
6. Deploy. `BASE_URL` defaults to the production URL; set it explicitly if you use a custom domain (it is also the login callback origin).

Pushes to `main` deploy automatically. Workflow runs, steps and retries are visible under **Observability → Workflows** in the Vercel dashboard.

## Local development

```bash
cp .env.example .env     # fill in keys; DATABASE_URL defaults to the compose Postgres below
docker compose up -d     # local Postgres on :9002
npm install
npm run db:migrate
npm run dev              # http://localhost:3000, workflows run in-process (Local World)
```

`npx workflow web` opens a local inspector for workflow runs. For storage you need a real bucket even locally, or any S3-compatible server.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string (Neon pooled URL in production) | `postgresql://podcast:podcast@localhost:9002/podcast` |
| `GOOGLE_API_KEY` | Gemini API key (research, optional transcript) | — |
| `OPENAI_API_KEY` | OpenAI API key (transcript + titles, optional research) | — |
| `ANTHROPIC_API_KEY` | Anthropic API key (only for `TRANSCRIPT_MODEL=claude-haiku`) | — |
| `DEEPINFRA_API_KEY` | DeepInfra API key (text-to-speech) | — |
| `STORAGE_ENDPOINT` | S3 endpoint URL | — |
| `STORAGE_REGION` | S3 region | `auto` |
| `STORAGE_BUCKET` | Bucket name | — |
| `STORAGE_ACCESS_KEY_ID` / `STORAGE_SECRET_ACCESS_KEY` | Bucket credentials | — |
| `STORAGE_PUBLIC_URL` | Public base URL of the bucket, used in the feed | — |
| `STORAGE_FORCE_PATH_STYLE` | Path-style S3 URLs | `true` |
| `BASE_URL` | Public URL of the app | Vercel production URL or `http://localhost:3000` |
| `SESSION_SECRET` | Session cookie signing secret (required in production) | random per start |
| `REGISTER_TOKEN` | Invite token for registration | — |
| `RESEARCH_MODEL` / `TRANSCRIPT_MODEL` / `TTS_MODEL` | Model keys | `gemini-flash` / `gpt-luna` / `chatterbox-turbo` |
| `TTS_CONCURRENCY` | Parallel TTS requests inside one batch | `4` |
| `TTS_BATCH_SIZE` | Dialogue lines per batch step | `12` |
| `TTS_PARALLEL_BATCHES` | Batch steps running at the same time | `4` |
| `MP3_KBPS` | MP3 bitrate (mono) | `64` |
| `DAILY_SPEND_LIMIT` | Max estimated USD spend per UTC day before new steps wait | `5.0` |
