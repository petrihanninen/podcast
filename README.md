# Podcast Generator

Auto-generates two-host podcast episodes from a topic using Claude for research & scripting and [Chatterbox TTS](https://github.com/resemble-ai/chatterbox) for voice synthesis. Comes with a web UI, background worker pipeline, and an RSS feed you can subscribe to from any podcast app.

Default host voices are samples from [LibriVox](https://librivox.org/) public domain audiobooks. Drop your own `.wav` files into `voice_refs/` to customize them.

## Running locally

You need Docker, a PostgreSQL database, and an [Anthropic API key](https://console.anthropic.com/).

**1. Start Postgres** (or use an existing one):

```bash
docker run -d --name podcast-db \
  -e POSTGRES_USER=podcast \
  -e POSTGRES_PASSWORD=podcast \
  -e POSTGRES_DB=podcast \
  -p 9002:5432 \
  postgres:16
```

**2. Build the image:**

```bash
docker build -t podcast .
```

**3. Run the web server + worker:**

```bash
# Web UI on port 9001
docker run -d --name podcast-web \
  -e DATABASE_URL=postgresql+asyncpg://podcast:podcast@host.docker.internal:9002/podcast \
  -e BASE_URL=http://localhost:9001 \
  -v podcast-audio:/data/audio \
  -p 9001:9001 \
  podcast web

# Background worker (generates the actual episodes)
docker run -d --name podcast-worker \
  -e DATABASE_URL=postgresql+asyncpg://podcast:podcast@host.docker.internal:9002/podcast \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e DEEPSEEK_API_KEY=sk-... \
  -e HF_TOKEN=hf_... \
  -e BASE_URL=http://localhost:9001 \
  -v podcast-audio:/data/audio \
  podcast worker
```

Open [http://localhost:9001](http://localhost:9001) and create your first episode.

## Hosting

To host this properly, you basically need:

- A server that can run Docker (any VPS works)
- A PostgreSQL instance (managed or self-hosted)
- A persistent volume for `/data/audio`
- `BASE_URL` set to your public URL so the RSS feed links work

Set `BASE_URL` to whatever your public domain is, point a reverse proxy (nginx, Caddy, etc.) at port 9001, and you're good. The RSS feed lives at `/feed.xml` — add that to your podcast app of choice.

## Tests

```bash
# Install test dependencies
uv sync --extra test

# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_services_transcript.py

# Run a specific test class or method
uv run pytest tests/test_routers_pages.py::TestFormatDuration
```

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://podcast:podcast@localhost:9002/podcast` |
| `ANTHROPIC_API_KEY` | Your Anthropic API key | — |
| `DEEPSEEK_API_KEY` | DeepSeek API key (used for transcript generation) | — |
| `HF_TOKEN` | Hugging Face token (for downloading TTS models) | — |
| `AUDIO_DIR` | Where episode audio files are stored | `/data/audio` |
| `BASE_URL` | Public URL (used in RSS feed links) | `http://localhost:9001` |
| `API_PASSWORD` | Optional password for mutating API endpoints | — |
