#!/bin/bash
set -e

# Run database migrations with timeout
echo "Running database migrations..."
timeout 30 npx drizzle-kit migrate 2>&1 || MIGRATE_EXIT=$?

if [ ! -z "$MIGRATE_EXIT" ]; then
  if [ "$MIGRATE_EXIT" = "124" ]; then
    echo "Warning: Database migrations timed out, continuing..."
  else
    echo "Warning: Database migrations failed with exit code $MIGRATE_EXIT, continuing..."
  fi
fi

case "$1" in
  web)
    echo "Starting web server..."
    exec node dist/server.js
    ;;
  worker)
    echo "Starting worker..."
    exec node dist/worker.js
    ;;
  combined)
    echo "Starting worker and web server..."
    # Start worker in background
    node dist/worker.js &
    WORKER_PID=$!

    # Trap SIGTERM/SIGINT to clean up worker
    trap 'echo "Received signal, terminating..."; kill $WORKER_PID 2>/dev/null || true; exit 0' SIGTERM SIGINT

    # Run web server in foreground — container stays alive as long as the server runs
    node dist/server.js
    EXIT_CODE=$?

    # Web server exited — clean up worker
    kill $WORKER_PID 2>/dev/null || true
    exit $EXIT_CODE
    ;;
  *)
    exec "$@"
    ;;
esac
