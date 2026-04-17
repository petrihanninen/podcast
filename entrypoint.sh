#!/bin/bash
set -e

# Run database migrations
echo "Running database migrations..."
npx drizzle-kit migrate

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

    # Trap SIGTERM/SIGINT to forward to both processes
    trap 'echo "Received signal, terminating..."; kill $WORKER_PID 2>/dev/null || true; exit 0' SIGTERM SIGINT

    # Start web server in foreground
    node dist/server.js &
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
