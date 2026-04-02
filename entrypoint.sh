#!/bin/bash
set -e

# Run database migrations
echo "Running database migrations..."
python -m alembic upgrade head

case "$1" in
  web)
    echo "Starting web server..."
    exec uvicorn podcast.main:app --host 0.0.0.0 --port 9001
    ;;
  worker)
    echo "Starting worker..."
    exec python -m podcast.worker
    ;;
  *)
    exec "$@"
    ;;
esac
