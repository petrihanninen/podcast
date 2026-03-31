"""Tests for podcast.worker."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from podcast.worker import (
    EPISODE_STATUS_MAP,
    NEXT_STEP,
    POLL_INTERVAL,
    STEP_HANDLERS,
    _handle_signal,
    process_job,
)


class TestStepHandlers:
    def test_all_steps_have_handlers(self):
        expected_steps = {"research", "transcript", "tts", "encode"}
        assert set(STEP_HANDLERS.keys()) == expected_steps

    def test_handlers_are_callable(self):
        for step, handler in STEP_HANDLERS.items():
            assert callable(handler), f"Handler for {step} is not callable"


class TestNextStep:
    def test_research_to_transcript(self):
        assert NEXT_STEP["research"] == "transcript"

    def test_transcript_to_tts(self):
        assert NEXT_STEP["transcript"] == "tts"

    def test_tts_to_encode(self):
        assert NEXT_STEP["tts"] == "encode"

    def test_encode_is_terminal(self):
        assert NEXT_STEP["encode"] is None

    def test_pipeline_order(self):
        step = "research"
        pipeline = [step]
        while NEXT_STEP.get(step):
            step = NEXT_STEP[step]
            pipeline.append(step)
        assert pipeline == ["research", "transcript", "tts", "encode"]


class TestEpisodeStatusMap:
    def test_all_steps_mapped(self):
        expected = {"research", "transcript", "tts", "encode"}
        assert set(EPISODE_STATUS_MAP.keys()) == expected

    def test_research_status(self):
        assert EPISODE_STATUS_MAP["research"] == "researching"

    def test_transcript_status(self):
        assert EPISODE_STATUS_MAP["transcript"] == "writing_transcript"

    def test_tts_status(self):
        assert EPISODE_STATUS_MAP["tts"] == "generating_audio"

    def test_encode_status(self):
        assert EPISODE_STATUS_MAP["encode"] == "encoding"


class TestProcessJob:
    async def test_calls_correct_handler(self):
        job_id = uuid.uuid4()
        episode_id = uuid.uuid4()
        mock_handler = AsyncMock(return_value={"tokens": 100})

        with patch.dict(STEP_HANDLERS, {"research": mock_handler}):
            result = await process_job(job_id, episode_id, "research")

        mock_handler.assert_awaited_once_with(episode_id)
        assert result == {"tokens": 100}

    async def test_returns_metrics_dict(self):
        job_id = uuid.uuid4()
        episode_id = uuid.uuid4()
        mock_handler = AsyncMock(return_value={"input_tokens": 50, "output_tokens": 100})

        with patch.dict(STEP_HANDLERS, {"transcript": mock_handler}):
            result = await process_job(job_id, episode_id, "transcript")

        assert result["input_tokens"] == 50
        assert result["output_tokens"] == 100

    async def test_returns_none_for_non_dict_result(self):
        job_id = uuid.uuid4()
        episode_id = uuid.uuid4()
        mock_handler = AsyncMock(return_value="not a dict")

        with patch.dict(STEP_HANDLERS, {"research": mock_handler}):
            result = await process_job(job_id, episode_id, "research")

        assert result is None

    async def test_unknown_step_raises(self):
        with pytest.raises(ValueError, match="Unknown step"):
            await process_job(uuid.uuid4(), uuid.uuid4(), "nonexistent")

    async def test_handler_exception_propagates(self):
        job_id = uuid.uuid4()
        episode_id = uuid.uuid4()
        mock_handler = AsyncMock(side_effect=RuntimeError("API error"))

        with patch.dict(STEP_HANDLERS, {"research": mock_handler}):
            with pytest.raises(RuntimeError, match="API error"):
                await process_job(job_id, episode_id, "research")


class TestHandleSignal:
    def test_sets_shutdown_flag(self):
        import podcast.worker as wm
        original = wm._shutdown
        try:
            wm._shutdown = False
            _handle_signal(15, None)  # SIGTERM
            assert wm._shutdown is True
        finally:
            wm._shutdown = original


class TestConstants:
    def test_poll_interval(self):
        assert POLL_INTERVAL == 10
