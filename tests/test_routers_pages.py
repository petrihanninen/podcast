"""Tests for podcast.routers.pages helper functions."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from podcast.routers.pages import (
    PIPELINE_STEPS,
    STEP_LABELS,
    _build_pipeline_info,
    _calc_cost,
    _format_duration,
    _format_file_size,
    _get_current_step_index,
    _status_badge,
    _status_label,
)
from tests.conftest import make_episode, make_job


class TestStatusBadge:
    def test_ready(self):
        assert _status_badge("ready") == "badge--success"

    def test_failed(self):
        assert _status_badge("failed") == "badge--error"

    def test_pending(self):
        assert _status_badge("pending") == "badge--info"

    def test_researching(self):
        assert _status_badge("researching") == "badge--warning"

    def test_writing_transcript(self):
        assert _status_badge("writing_transcript") == "badge--warning"

    def test_generating_audio(self):
        assert _status_badge("generating_audio") == "badge--warning"

    def test_encoding(self):
        assert _status_badge("encoding") == "badge--warning"

    def test_unknown_status(self):
        assert _status_badge("some_unknown") == "badge--warning"


class TestStatusLabel:
    def test_pending(self):
        assert _status_label("pending") == "Pending"

    def test_researching(self):
        assert _status_label("researching") == "Researching"

    def test_writing_transcript(self):
        assert _status_label("writing_transcript") == "Writing transcript"

    def test_generating_audio(self):
        assert _status_label("generating_audio") == "Generating audio"

    def test_encoding(self):
        assert _status_label("encoding") == "Encoding"

    def test_ready(self):
        assert _status_label("ready") == "Ready"

    def test_failed(self):
        assert _status_label("failed") == "Failed"

    def test_unknown_formats_nicely(self):
        assert _status_label("some_custom_status") == "Some Custom Status"


class TestFormatDuration:
    def test_none_returns_empty(self):
        assert _format_duration(None) == ""

    def test_zero(self):
        assert _format_duration(0) == "0:00"

    def test_seconds_only(self):
        assert _format_duration(45) == "0:45"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2:05"

    def test_exact_minutes(self):
        assert _format_duration(600) == "10:00"

    def test_one_second(self):
        assert _format_duration(1) == "0:01"


class TestFormatFileSize:
    def test_none_returns_empty(self):
        assert _format_file_size(None) == ""

    def test_bytes(self):
        assert _format_file_size(500) == "500 B"

    def test_kilobytes(self):
        result = _format_file_size(2048)
        assert "KB" in result
        assert "2.0" in result

    def test_megabytes(self):
        result = _format_file_size(5 * 1024 * 1024)
        assert "MB" in result
        assert "5.0" in result

    def test_zero_bytes(self):
        assert _format_file_size(0) == "0 B"

    def test_exactly_1024_bytes(self):
        result = _format_file_size(1024)
        assert "KB" in result

    def test_just_under_1024(self):
        assert _format_file_size(1023) == "1023 B"

    def test_large_megabytes(self):
        result = _format_file_size(100 * 1024 * 1024)
        assert "100.0 MB" in result


class TestBuildPipelineInfo:
    def test_no_jobs(self):
        ep = make_episode(jobs=[])
        steps = _build_pipeline_info(ep)

        assert len(steps) == 4
        assert all(s["status"] == "waiting" for s in steps)
        assert all(s["attempts"] == 0 for s in steps)
        assert steps[0]["label"] == "Research"
        assert steps[1]["label"] == "Transcript"
        assert steps[2]["label"] == "Audio"
        assert steps[3]["label"] == "Encode"

    def test_with_completed_job(self):
        now = datetime.now(timezone.utc)
        job = make_job(
            step="research",
            status="completed",
            attempts=1,
            started_at=now - timedelta(seconds=30),
            completed_at=now,
        )
        ep = make_episode(jobs=[job])
        steps = _build_pipeline_info(ep)

        assert steps[0]["status"] == "completed"
        assert steps[0]["attempts"] == 1
        assert steps[0]["duration"] == "30s"
        assert steps[1]["status"] == "waiting"  # Next step not started

    def test_long_duration_formatted(self):
        now = datetime.now(timezone.utc)
        job = make_job(
            step="tts",
            status="completed",
            attempts=1,
            started_at=now - timedelta(seconds=125),
            completed_at=now,
        )
        ep = make_episode(jobs=[job])
        steps = _build_pipeline_info(ep)

        assert steps[2]["duration"] == "2m 5s"

    def test_running_job(self):
        now = datetime.now(timezone.utc)
        job = make_job(step="transcript", status="running", attempts=1, started_at=now)
        ep = make_episode(jobs=[job])
        steps = _build_pipeline_info(ep)

        assert steps[1]["status"] == "running"
        assert steps[1]["duration"] is None  # No completed_at


class TestGetCurrentStepIndex:
    def test_ready_returns_past_all_steps(self):
        ep = make_episode(status="ready", jobs=[])
        assert _get_current_step_index(ep) == len(PIPELINE_STEPS)

    def test_no_jobs_returns_zero(self):
        ep = make_episode(status="pending", jobs=[])
        assert _get_current_step_index(ep) == 0

    def test_first_job_pending(self):
        job = make_job(step="research", status="pending")
        ep = make_episode(status="pending", jobs=[job])
        assert _get_current_step_index(ep) == 0

    def test_first_job_completed_second_pending(self):
        j1 = make_job(step="research", status="completed")
        j2 = make_job(step="transcript", status="pending")
        ep = make_episode(status="pending", jobs=[j1, j2])
        assert _get_current_step_index(ep) == 1

    def test_all_completed(self):
        jobs = [
            make_job(step="research", status="completed"),
            make_job(step="transcript", status="completed"),
            make_job(step="tts", status="completed"),
            make_job(step="encode", status="completed"),
        ]
        ep = make_episode(status="encoding", jobs=jobs)
        assert _get_current_step_index(ep) == len(PIPELINE_STEPS)


class TestCalcCost:
    def test_zero_tokens(self):
        assert _calc_cost(0, 0) == 0.0

    def test_known_values(self):
        # 1M input tokens * $3 + 1M output tokens * $15 = $18
        cost = _calc_cost(1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)

    def test_small_values(self):
        # 1000 input * $3/1M + 500 output * $15/1M
        cost = _calc_cost(1000, 500)
        expected = (1000 * 3.0 + 500 * 15.0) / 1_000_000
        assert cost == pytest.approx(expected)


class TestPipelineSteps:
    def test_step_order(self):
        assert PIPELINE_STEPS == ["research", "transcript", "tts", "encode"]

    def test_all_steps_have_labels(self):
        for step in PIPELINE_STEPS:
            assert step in STEP_LABELS
