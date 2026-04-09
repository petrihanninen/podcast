import json
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from podcast.auth import RequiresLogin, RequiresRegistration
from podcast.config import settings
from podcast.log_handler import setup_logging, start_flush_loop, stop_flush_loop
from podcast.routers import api, auth, feed, pages

# Configure logging (adds buffered DB handler alongside default stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
setup_logging("web")

# Ensure audio directory exists before StaticFiles mount validates it
os.makedirs(settings.audio_dir, exist_ok=True)
os.makedirs(os.path.join(settings.audio_dir, "segments"), exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_flush_loop()
    yield
    await stop_flush_loop()


app = FastAPI(title="Podcast Generator", lifespan=lifespan)


_templates = Jinja2Templates(directory="src/podcast/templates")


@app.exception_handler(RequiresLogin)
async def requires_login_handler(request: Request, exc: RequiresLogin):
    """Redirect unauthenticated users to the login page."""
    return RedirectResponse(
        url=f"/auth/login?next={quote(exc.next_url, safe='')}", status_code=303
    )


@app.exception_handler(RequiresRegistration)
async def requires_registration_handler(request: Request, exc: RequiresRegistration):
    """Show a 'not registered' page for authenticated but unregistered users."""
    return _templates.TemplateResponse(
        request, "not_registered.html", status_code=403
    )


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
app.include_router(auth.router)
app.include_router(api.router)
app.include_router(feed.router)
app.include_router(pages.router)
