#!/bin/bash
set -e

# Run database migrations
echo "Running database migrations..."
python -m alembic upgrade head

case "$1" in
  web)
    echo "Starting web server..."
    exec uvicorn podcast.main:app --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  worker)
    echo "Starting worker..."
    exec python -m podcast.worker
    ;;
  combined)
    echo "Starting worker and web server..."
    # Start worker in background
    python -m podcast.worker &
    WORKER_PID=$!

    # Trap SIGTERM/SIGINT to forward to both processes
    trap 'echo "Received signal, terminating..."; kill $WORKER_PID 2>/dev/null || true; exit 0' SIGTERM SIGINT

    # Start web server in foreground
    uvicorn podcast.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
    WEB_PID=$!

    # Wait for either process to exit
    wait -n

    # Kill the other process
    kill $WORKER_PID 2>/dev/null || true
    kill $WEB_PID 2>/dev/null || true
    ;;
  *)
    exec "$@"
    ;;
esac
