import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from podcast.config import settings
from podcast.routers import api, feed, pages

# Ensure audio directory exists before StaticFiles mount validates it
os.makedirs(settings.audio_dir, exist_ok=True)
os.makedirs(os.path.join(settings.audio_dir, "segments"), exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Podcast Generator", lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Serve audio files from the data directory
app.mount("/audio", StaticFiles(directory=settings.audio_dir), name="audio")

# Register Jinja2 filter for parsing JSON in templates
def from_json(value):
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


pages.templates.env.filters["from_json"] = from_json

# Routers
app.include_router(api.router)
app.include_router(feed.router)
app.include_router(pages.router)
