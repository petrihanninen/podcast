# Podcast Generator

Auto-generates two-host podcast episodes from a topic. Research notes are grounded with web search, a script is written by an LLM, and the dialogue is voiced with [Chatterbox Turbo](https://huggingface.co/ResembleAI/chatterbox-turbo) voice cloning served by [DeepInfra](https://deepinfra.com). Comes with a web UI, a background worker pipeline, and an RSS feed you can subscribe to from any podcast app.

Default host voices are samples from [LibriVox](https://librivox.org/) public domain audiobooks. Drop your own `.wav` files into `voice_refs/` to customize them; each reference is uploaded to DeepInfra once as a cloned voice and reused afterwards.

## Pipeline

**research → transcript → TTS → encode**, all driven by the worker from a `jobs` table in Postgres.

| Step | Default | Alternatives (`RESEARCH_MODEL` / `TRANSCRIPT_MODEL` / `TTS_MODEL`) |
|---|---|---|
| Research (web-grounded notes) | Gemini 3.8 Flash with Google Search grounding (`gemini-flash`) | `gemini-flash-lite`, `gpt-luna`, `gpt-6-luna` (OpenAI web search, $0.01 per search) |
| Transcript + titles | GPT-5.6 Luna (`gpt-luna`) | `gpt-6-luna`, `gemini-flash`, `gemini-flash-lite`, `claude-haiku` |
| Text-to-speech | Chatterbox Turbo on DeepInfra (`chatterbox-turbo`) | — |
| Encode | ffmpeg → 128 kbps mono MP3 | — |

Approximate cost of a 30-minute episode at list prices (October 2026): research ≈ $0.04 (Google Search grounding is free for the first 5,000 queries per month), transcript ≈ $0.01, TTS ≈ $0.03, total **≈ $0.10**. The worker refuses to start costly steps once the day's estimated spend passes `DAILY_SPEND_LIMIT`. Every step records its own `cost_usd`, visible on the admin Metrics page.

TTS segments are synthesized in parallel (`TTS_CONCURRENCY`, default 4) and stitched locally, so a 30-minute episode is usually ready a few minutes after the transcript.

## Running locally

You need Docker and API keys for Google (Gemini), OpenAI and DeepInfra.

```bash
cp .env.example .env   # then fill in your API keys
docker compose up
```

Open [http://localhost:9001](http://localhost:9001) and create your first episode.

For development without Docker (needs Node 20+, ffmpeg and a Postgres on `DATABASE_URL`):

```bash
npm install
npm run db:migrate
npm run dev          # web server
npm run dev:worker   # pipeline worker
```

## Hosting

The repo includes a `railway.toml` that runs both the web server and background worker in a single container (`combined` mode). Set these in your Railway service:

- `DATABASE_URL` — Postgres connection string
- `BASE_URL` — your public domain (so RSS feed links work)
- `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `DEEPINFRA_API_KEY`
- `AUDIO_DIR` — mount a volume here

Database migrations run automatically on startup. The RSS feed lives at `/feed/<token>.xml` (copy it from the nav bar).

Any Docker host works the same way: point a reverse proxy at port 9001 and mount a volume for `AUDIO_DIR`. A Fly.io `shared-cpu-1x` machine or a Hetzner CX23 comes in at roughly the same monthly price as Railway's Hobby plan.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://podcast:podcast@localhost:9002/podcast` |
| `GOOGLE_API_KEY` | Gemini API key (research, optional transcript) | — |
| `OPENAI_API_KEY` | OpenAI API key (transcript + titles, optional research) | — |
| `ANTHROPIC_API_KEY` | Anthropic API key (only for `TRANSCRIPT_MODEL=claude-haiku`) | — |
| `DEEPINFRA_API_KEY` | DeepInfra API key (text-to-speech) | — |
| `RESEARCH_MODEL` | Research model key | `gemini-flash` |
| `TRANSCRIPT_MODEL` | Transcript/title model key | `gpt-luna` |
| `TTS_MODEL` | TTS model key | `chatterbox-turbo` |
| `TTS_CONCURRENCY` | Parallel TTS requests | `4` |
| `DAILY_SPEND_LIMIT` | Max estimated USD spend per day before the worker pauses costly steps | `5.0` |
| `AUDIO_DIR` | Where episode audio files are stored | `/data/audio` |
| `VOICE_REFS_DIR` | Directory for voice reference `.wav` samples | `/app/voice_refs` |
| `BASE_URL` | Public URL (used in RSS feed links) | `http://localhost:9001` |
| `API_PASSWORD` | Optional password for mutating API endpoints | — |
| `REGISTER_TOKEN` | Invite token for registration | — |
| `SESSION_SECRET` | Session secret for authentication | random per start |
