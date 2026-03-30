"""
Buffered database logging handler.

The core problem: logging.Handler.emit() is synchronous, but our only DB
driver (asyncpg) is async.  This module bridges the gap with a bounded
in-memory deque that is periodically flushed to PostgreSQL by an asyncio
background task.

Usage (call once at process startup):

    from podcast.log_handler import setup_logging, start_flush_loop, stop_flush_loop

    setup_logging("web")            # or "worker"
    await start_flush_loop()        # in the async entry-point
    ...
    await stop_flush_loop()         # on shutdown
"""

import asyncio
import collections
import logging
import threading
from datetime import datetime, timezone

from sqlalchemy import text

from podcast.database import get_session

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_buffer: collections.deque[dict] = collections.deque(maxlen=1000)
_buffer_lock = threading.Lock()

_source: str = "unknown"
_flush_task: asyncio.Task | None = None

FLUSH_INTERVAL_SECONDS = 5
MAX_LOGS_IN_DB = 5000
PRUNE_BATCH_SIZE = 500  # prune triggers when count > MAX + BATCH


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class BufferedDBHandler(logging.Handler):
    """Logging handler that captures records into a thread-safe deque.

    The deque has a fixed maxlen so if flushing falls behind, the oldest
    un-flushed records are silently dropped.  Logging must never block or
    crash the application.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc),
                "level": record.levelname,
                "logger_name": record.name,
                "message": self.format(record),
                "source": _source,
            }
            with _buffer_lock:
                _buffer.append(entry)
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Async flush / prune helpers
# ---------------------------------------------------------------------------

_INSERT_SQL = text(
    "INSERT INTO log_entries (timestamp, level, logger_name, message, source) "
    "VALUES (:timestamp, :level, :logger_name, :message, :source)"
)


async def flush_to_db() -> None:
    """Drain the buffer and bulk-insert into log_entries."""
    with _buffer_lock:
        if not _buffer:
            return
        batch = list(_buffer)
        _buffer.clear()

    try:
        async with get_session() as session:
            await session.execute(_INSERT_SQL, batch)
    except Exception:
        # If DB write fails, records are lost — acceptable for logs.
        pass


async def prune_old_logs() -> None:
    """Delete log entries beyond the retention limit."""
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM log_entries"))
            count = result.scalar_one()

            if count > MAX_LOGS_IN_DB + PRUNE_BATCH_SIZE:
                await session.execute(
                    text(
                        "DELETE FROM log_entries WHERE id NOT IN "
                        "(SELECT id FROM log_entries ORDER BY timestamp DESC LIMIT :keep)"
                    ),
                    {"keep": MAX_LOGS_IN_DB},
                )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------


async def _flush_loop() -> None:
    """Background loop: flush buffer and periodically prune."""
    prune_counter = 0
    while True:
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        await flush_to_db()

        # Prune every ~60 s  (12 iterations × 5 s)
        prune_counter += 1
        if prune_counter >= 12:
            prune_counter = 0
            await prune_old_logs()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logging(source: str) -> None:
    """Configure logging for the given process ("web" or "worker").

    Adds the buffered DB handler to the root logger *alongside* any
    existing handlers (e.g. the StreamHandler from ``basicConfig``).
    """
    global _source
    _source = source

    handler = BufferedDBHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.addHandler(handler)

    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)


async def start_flush_loop() -> asyncio.Task:
    """Start the background flush task.  Returns the task for cleanup."""
    global _flush_task
    _flush_task = asyncio.create_task(_flush_loop())
    return _flush_task


async def stop_flush_loop() -> None:
    """Cancel the flush loop and do one final flush."""
    global _flush_task
    if _flush_task:
        _flush_task.cancel()
        try:
            await _flush_task
        except asyncio.CancelledError:
            pass
    await flush_to_db()
