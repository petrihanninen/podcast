# Podcast Generator

Auto-generates two-host podcast episodes from a topic using Claude for research & scripting and [Chatterbox TTS](https://github.com/resemble-ai/chatterbox) for voice synthesis. Comes with a web UI, background worker pipeline, and an RSS feed you can subscribe to from any podcast app.

Default host voices are samples from [LibriVox](https://librivox.org/) public domain audiobooks. Drop your own `.wav` files into `voice_refs/` to customize them.

## Architecture

The app is split into two deployments:

- **Web + Worker** (Railway, or any Docker host) — serves the UI, runs the background pipeline (research → transcript → TTS → encode), and hosts the RSS feed.
- **TTS on Modal** — GPU-accelerated speech synthesis runs on [Modal](https://modal.com/) as a separate serverless function. The worker calls it remotely, so the main server doesn't need a GPU.

The episode pipeline is: **research → transcript → TTS (Modal) → encode**.

## Running locally

You need Docker, some API keys, and a Modal account (free tier works).

### 1. Set up environment

```bash
cp .env.example .env   # then fill in your API keys
```

You need at least one LLM provider key (Anthropic, OpenAI, etc.) and a [Modal](https://modal.com/) token pair (`MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET`) for TTS. Get your Modal tokens from [modal.com/settings](https://modal.com/settings).

### 2. Deploy the TTS function to Modal

```bash
pip install modal
modal setup              # authenticate (first time only)
modal deploy src/podcast/modal_app.py
```

This builds a GPU image with the Chatterbox model baked in, so cold starts skip the download. The function runs on an NVIDIA T4.

### 3. Start the app

```bash
docker compose up
```

Open [http://localhost:9001](http://localhost:9001) and create your first episode.

## Hosting

### Web + Worker (Railway)

The repo includes a `railway.toml` that runs both the web server and background worker in a single container (`combined` mode). Set these in your Railway service:

- `DATABASE_URL` — Railway Postgres connection string
- `BASE_URL` — your public domain (so RSS feed links work)
- `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` — for calling the Modal TTS function
- LLM provider keys as needed

Database migrations run automatically on startup. The RSS feed lives at `/feed.xml`.

You can also host this on any VPS that runs Docker — just point a reverse proxy at port 9001.

### TTS (Modal)

Deploy separately from your local machine or CI:

```bash
modal deploy src/podcast/modal_app.py
```

The Modal app (`podcast-tts`) needs a Hugging Face secret named `huggingface` with your `HF_TOKEN` — create it via `modal secret create huggingface HF_TOKEN=hf_...`. This is used to download the Chatterbox model weights at image build time.

## Tests

```bash
# Install test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_services_transcript.py

# Run a specific test class or method
pytest tests/test_routers_pages.py::TestFormatDuration
```

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://podcast:podcast@localhost:9002/podcast` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `DEEPSEEK_API_KEY` | DeepSeek API key | — |
| `GOOGLE_API_KEY` | Google Gemini API key | — |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `PERPLEXITY_API_KEY` | Perplexity API key | — |
| `HF_TOKEN` | Hugging Face token (for downloading TTS models) | — |
| `MODAL_TOKEN_ID` | Modal authentication token ID | — |
| `MODAL_TOKEN_SECRET` | Modal authentication token secret | — |
| `AUDIO_DIR` | Where episode audio files are stored | `/data/audio` |
| `VOICE_REFS_DIR` | Directory for voice reference `.wav` samples | `/app/voice_refs` |
| `BASE_URL` | Public URL (used in RSS feed links) | `http://localhost:9001` |
| `API_PASSWORD` | Optional password for mutating API endpoints | — |
| `ALLOWED_SUB` | Allowed subject for authentication | — |
| `SESSION_SECRET` | Session secret for authentication | — |
