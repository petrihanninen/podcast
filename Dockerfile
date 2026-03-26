FROM python:3.11-slim

# Install ffmpeg for audio encoding
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ src/
COPY alembic.ini .
COPY alembic/ alembic/
COPY static/ static/
COPY voice_refs/ voice_refs/

# Entrypoint
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
CMD ["web"]
