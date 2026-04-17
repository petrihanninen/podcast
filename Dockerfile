FROM node:20-slim

# Install system dependencies (ffmpeg for audio encoding)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (cached layer unless package.json changes)
COPY package.json package-lock.json* ./
RUN npm ci --production=false

# Copy source and build
COPY tsconfig.json .
COPY src/ src/
COPY templates/ templates/
COPY static/ static/
COPY voice_refs/ voice_refs/
COPY drizzle/ drizzle/
COPY drizzle.config.ts .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Build TypeScript
RUN npm run build

ENTRYPOINT ["./entrypoint.sh"]
CMD ["combined"]
