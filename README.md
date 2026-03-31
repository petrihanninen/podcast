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
  -p 5432:5432 \
  postgres:16
```

**2. Build the image:**

```bash
docker build -t podcast .
```

**3. Run the web server + worker:**

```bash
# Web UI on port 8000
docker run -d --name podcast-web \
  -e DATABASE_URL=postgresql+asyncpg://podcast:podcast@host.docker.internal:5432/podcast \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e BASE_URL=http://localhost:8000 \
  -v podcast-audio:/data/audio \
  -p 8000:8000 \
  podcast web

# Background worker (generates the actual episodes)
docker run -d --name podcast-worker \
  -e DATABASE_URL=postgresql+asyncpg://podcast:podcast@host.docker.internal:5432/podcast \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e BASE_URL=http://localhost:8000 \
  -v podcast-audio:/data/audio \
  podcast worker
```

Open [http://localhost:8000](http://localhost:8000) and create your first episode.

## Hosting

To host this properly, you basically need:

- A server that can run Docker (any VPS works)
- A PostgreSQL instance (managed or self-hosted)
- A persistent volume for `/data/audio`
- `BASE_URL` set to your public URL so the RSS feed links work

Set `BASE_URL` to whatever your public domain is, point a reverse proxy (nginx, Caddy, etc.) at port 8000, and you're good. The RSS feed lives at `/feed.xml` — add that to your podcast app of choice.

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

Tests run automatically on every commit via a pre-commit hook. To set up the hook after cloning:

```bash
git config core.hooksPath .githooks
```

### Test structure

```
tests/
├── conftest.py                  # Shared fixtures and factory helpers
├── test_config.py               # Settings loading and env overrides
├── test_schemas.py              # Pydantic request/response validation
├── test_models.py               # SQLAlchemy model metadata and constraints
├── test_log_handler.py          # Buffered DB logging handler
├── test_main.py                 # App initialization and JSON filter
├── test_worker.py               # Job pipeline dispatch and signal handling
├── test_services_claude_client.py  # Singleton client configuration
├── test_services_episode.py     # Episode CRUD operations
├── test_services_research.py    # Claude research integration
├── test_services_transcript.py  # Transcript generation and validation
├── test_services_tts.py         # Voice ref resolution and TTS orchestration
├── test_services_encoder.py     # WAV→MP3 encoding and cleanup
├── test_services_feed.py        # RSS feed generation
├── test_routers_api.py          # REST API endpoints
├── test_routers_feed.py         # RSS feed endpoint
└── test_routers_pages.py        # Template helper functions
```

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://podcast:podcast@localhost:5432/podcast` |
| `ANTHROPIC_API_KEY` | Your Anthropic API key | — |
| `AUDIO_DIR` | Where episode audio files are stored | `/data/audio` |
| `BASE_URL` | Public URL (used in RSS feed links) | `http://localhost:8000` |
