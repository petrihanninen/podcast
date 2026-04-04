# Podcast Generator

Auto-generates two-host podcast episodes from a topic using Claude for research & scripting and [Chatterbox TTS](https://github.com/resemble-ai/chatterbox) for voice synthesis. Comes with a web UI, background worker pipeline, and an RSS feed you can subscribe to from any podcast app.

Default host voices are samples from [LibriVox](https://librivox.org/) public domain audiobooks. Drop your own `.wav` files into `voice_refs/` to customize them.

## Running locally

You need Docker and some API keys.

```bash
cp .env.example .env   # then fill in your API keys
docker compose up
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
| `AUDIO_DIR` | Where episode audio files are stored | `/data/audio` |
| `VOICE_REFS_DIR` | Directory for voice reference `.wav` samples | `/app/voice_refs` |
| `BASE_URL` | Public URL (used in RSS feed links) | `http://localhost:9001` |
| `API_PASSWORD` | Optional password for mutating API endpoints | — |
| `ALLOWED_SUB` | Allowed subject for authentication | — |
| `SESSION_SECRET` | Session secret for authentication | — |
