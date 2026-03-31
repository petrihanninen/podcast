FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip setuptools

WORKDIR /app

# Install dependencies first (cached layer unless pyproject.toml changes)
COPY pyproject.toml .
RUN mkdir -p src/podcast && touch src/podcast/__init__.py && \
    pip install --no-cache-dir . && \
    pip uninstall -y podcast

# Copy full application code
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/
COPY static/ static/
COPY voice_refs/ voice_refs/
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Install the actual package (fast — deps already cached)
RUN pip install --no-cache-dir --no-deps .

ENTRYPOINT ["./entrypoint.sh"]
CMD ["web"]
