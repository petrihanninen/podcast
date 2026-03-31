"""Tests for podcast.log_handler."""

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.log_handler import (
    FLUSH_INTERVAL_SECONDS,
    MAX_LOGS_IN_DB,
    PRUNE_BATCH_SIZE,
    BufferedDBHandler,
    _buffer,
    _buffer_lock,
    flush_to_db,
    prune_old_logs,
    setup_logging,
    start_flush_loop,
    stop_flush_loop,
)


class TestBufferedDBHandler:
    def setup_method(self):
        """Clear the buffer before each test."""
        with _buffer_lock:
            _buffer.clear()

    def test_emit_adds_to_buffer(self):
        handler = BufferedDBHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        handler.emit(record)

        with _buffer_lock:
            assert len(_buffer) == 1
            entry = _buffer[0]

        assert entry["level"] == "INFO"
        assert entry["logger_name"] == "test"
        assert "test message" in entry["message"]
        assert isinstance(entry["timestamp"], datetime)
        assert entry["timestamp"].tzinfo == timezone.utc

    def test_emit_multiple_records(self):
        handler = BufferedDBHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        for i in range(5):
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg=f"message {i}", args=(), exc_info=None,
            )
            handler.emit(record)

        with _buffer_lock:
            assert len(_buffer) == 5

    def test_emit_respects_maxlen(self):
        """Buffer has maxlen=1000 so oldest entries are dropped."""
        handler = BufferedDBHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        for i in range(1100):
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg=f"msg-{i}", args=(), exc_info=None,
            )
            handler.emit(record)

        with _buffer_lock:
            assert len(_buffer) == 1000
            # Oldest entries should be dropped, newest kept
            assert "msg-1099" in _buffer[-1]["message"]

    def test_emit_handles_error_gracefully(self):
        """If an error occurs during emit, it should not raise."""
        handler = BufferedDBHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.handleError = MagicMock()

        # Create a record that will cause an error in formatting
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test", args=(), exc_info=None,
        )
        # Make format raise an exception
        handler.format = MagicMock(side_effect=RuntimeError("format error"))
        handler.emit(record)

        handler.handleError.assert_called_once()

    def test_emit_uses_source_from_module(self):
        """emit() should use the module-level _source variable."""
        import podcast.log_handler as lh
        original = lh._source
        try:
            lh._source = "worker"
            handler = BufferedDBHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))

            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=0,
                msg="test", args=(), exc_info=None,
            )
            handler.emit(record)

            with _buffer_lock:
                assert _buffer[-1]["source"] == "worker"
        finally:
            lh._source = original


class TestFlushToDb:
    def setup_method(self):
        with _buffer_lock:
            _buffer.clear()

    async def test_flush_empty_buffer_is_noop(self):
        """Flushing an empty buffer should not touch the DB."""
        with patch("podcast.log_handler.get_session") as mock_gs:
            await flush_to_db()
            mock_gs.assert_not_called()

    async def test_flush_drains_buffer(self):
        """After flush, buffer should be empty."""
        with _buffer_lock:
            _buffer.append({
                "timestamp": datetime.now(timezone.utc),
                "level": "INFO",
                "logger_name": "test",
                "message": "hello",
                "source": "web",
            })

        mock_session = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("podcast.log_handler.get_session", return_value=mock_ctx):
            await flush_to_db()

        with _buffer_lock:
            assert len(_buffer) == 0

        mock_session.execute.assert_awaited_once()

    async def test_flush_handles_db_error(self):
        """If DB write fails, records are lost but no exception is raised."""
        with _buffer_lock:
            _buffer.append({
                "timestamp": datetime.now(timezone.utc),
                "level": "ERROR",
                "logger_name": "test",
                "message": "test",
                "source": "web",
            })

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("podcast.log_handler.get_session", return_value=mock_ctx):
            # Should not raise
            await flush_to_db()

        # Buffer should still be cleared (records are lost)
        with _buffer_lock:
            assert len(_buffer) == 0


class TestPruneOldLogs:
    async def test_prune_does_nothing_when_below_threshold(self):
        """No deletion when count <= MAX_LOGS_IN_DB + PRUNE_BATCH_SIZE."""
        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = MAX_LOGS_IN_DB  # Below threshold
        mock_session.execute = AsyncMock(return_value=count_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("podcast.log_handler.get_session", return_value=mock_ctx):
            await prune_old_logs()

        # execute called once for COUNT, not for DELETE
        assert mock_session.execute.await_count == 1

    async def test_prune_deletes_when_above_threshold(self):
        """Deletion occurs when count > MAX_LOGS_IN_DB + PRUNE_BATCH_SIZE."""
        mock_session = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = MAX_LOGS_IN_DB + PRUNE_BATCH_SIZE + 100
        mock_session.execute = AsyncMock(return_value=count_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("podcast.log_handler.get_session", return_value=mock_ctx):
            await prune_old_logs()

        # execute called twice: COUNT + DELETE
        assert mock_session.execute.await_count == 2

    async def test_prune_handles_error(self):
        """Prune should silently handle DB errors."""
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB error"))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("podcast.log_handler.get_session", return_value=mock_ctx):
            # Should not raise
            await prune_old_logs()


class TestSetupLogging:
    def test_sets_source(self):
        import podcast.log_handler as lh
        original = lh._source
        try:
            setup_logging("test_source")
            assert lh._source == "test_source"
        finally:
            lh._source = original
            # Clean up the handler we added
            root = logging.getLogger()
            for h in root.handlers[:]:
                if isinstance(h, BufferedDBHandler):
                    root.removeHandler(h)

    def test_adds_handler_to_root_logger(self):
        root = logging.getLogger()
        initial_count = len([h for h in root.handlers if isinstance(h, BufferedDBHandler)])

        setup_logging("test")

        new_count = len([h for h in root.handlers if isinstance(h, BufferedDBHandler)])
        assert new_count == initial_count + 1

        # Clean up
        for h in root.handlers[:]:
            if isinstance(h, BufferedDBHandler):
                root.removeHandler(h)

    def test_sets_root_level_to_info(self):
        root = logging.getLogger()
        original_level = root.level
        try:
            root.setLevel(logging.WARNING)
            setup_logging("test")
            assert root.level <= logging.INFO
        finally:
            root.setLevel(original_level)
            for h in root.handlers[:]:
                if isinstance(h, BufferedDBHandler):
                    root.removeHandler(h)


class TestFlushLoopLifecycle:
    async def test_start_and_stop(self):
        with patch("podcast.log_handler.flush_to_db", new_callable=AsyncMock) as mock_flush:
            task = await start_flush_loop()
            assert task is not None
            assert not task.done()

            await stop_flush_loop()
            # Final flush should be called
            mock_flush.assert_awaited()


class TestConstants:
    def test_flush_interval(self):
        assert FLUSH_INTERVAL_SECONDS == 5

    def test_max_logs(self):
        assert MAX_LOGS_IN_DB == 5000

    def test_prune_batch_size(self):
        assert PRUNE_BATCH_SIZE == 500
