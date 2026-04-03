"""Tests for podcast.routers.api endpoints."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from podcast.routers.api import _calc_cost, router
from tests.conftest import make_episode, make_job, make_log_entry, make_settings


# ---------------------------------------------------------------------------
# Test app setup
# ---------------------------------------------------------------------------


def _make_test_client(db_mock):
    """Create a FastAPI TestClient with overridden DB dependency."""
    app = FastAPI()
    app.include_router(router)

    async def override_get_db():
        yield db_mock

    from podcast.database import get_db
    from podcast.auth import require_auth

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_auth] = lambda: "test-user"
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        client = _make_test_client(AsyncMock())
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestGetModelsEndpoint:
    def test_returns_available_models(self):
        client = _make_test_client(AsyncMock())
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()

        # Should have research and transcript keys
        assert "research" in data
        assert "transcript" in data

        # Should have at least one model in each
        assert len(data["research"]) > 0
        assert len(data["transcript"]) > 0

        # Check research model structure
        research_models = data["research"]
        for key, model_info in research_models.items():
            assert "display_name" in model_info
            assert "provider" in model_info
            assert "supports_web_search" in model_info

        # Check transcript model structure
        transcript_models = data["transcript"]
        for key, model_info in transcript_models.items():
            assert "display_name" in model_info
            assert "provider" in model_info

    def test_includes_expected_models(self):
        """Verify some standard models are available."""
        client = _make_test_client(AsyncMock())
        response = client.get("/api/models")
        data = response.json()

        # Check for at least one research model
        assert len(data["research"]) > 0
        # Check for at least one transcript model
        assert len(data["transcript"]) > 0


# ---------------------------------------------------------------------------
# Episodes CRUD
# ---------------------------------------------------------------------------


class TestCreateEpisodeEndpoint:
    def test_creates_episode(self):
        db = AsyncMock()
        ep = make_episode(title="My Episode", topic="Test topic", status="pending")

        with patch("podcast.routers.api.create_episode", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = ep
            client = _make_test_client(db)
            response = client.post(
                "/api/episodes",
                json={"topic": "Test topic", "title": "My Episode"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "My Episode"
        assert data["topic"] == "Test topic"
        assert data["status"] == "pending"

    def test_creates_episode_with_model_selections(self):
        db = AsyncMock()
        ep = make_episode(
            title="My Episode",
            topic="Test topic",
            status="pending",
            research_model="gemini-flash",
            transcript_model="deepseek"
        )

        with patch("podcast.routers.api.create_episode", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = ep
            client = _make_test_client(db)
            response = client.post(
                "/api/episodes",
                json={
                    "topic": "Test topic",
                    "title": "My Episode",
                    "research_model": "gemini-flash",
                    "transcript_model": "deepseek"
                },
            )

        assert response.status_code == 200
        # Verify create_episode was called with the model parameters
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["research_model"] == "gemini-flash"
        assert call_kwargs["transcript_model"] == "deepseek"

    def test_missing_topic_returns_422(self):
        client = _make_test_client(AsyncMock())
        response = client.post("/api/episodes", json={})
        assert response.status_code == 422

    def test_auto_title(self):
        db = AsyncMock()
        ep = make_episode(title="Some topic", topic="Some topic", status="pending")

        with patch("podcast.routers.api.create_episode", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = ep
            client = _make_test_client(db)
            response = client.post(
                "/api/episodes",
                json={"topic": "Some topic"},
            )

        assert response.status_code == 200


class TestListEpisodesEndpoint:
    def test_returns_episode_list(self):
        ep = make_episode(title="Listed Episode")

        with patch("podcast.routers.api.list_episodes", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [ep]
            db = AsyncMock()
            client = _make_test_client(db)
            response = client.get("/api/episodes")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Listed Episode"

    def test_returns_empty_list(self):
        with patch("podcast.routers.api.list_episodes", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = []
            client = _make_test_client(AsyncMock())
            response = client.get("/api/episodes")

        assert response.status_code == 200
        assert response.json() == []


class TestGetEpisodeEndpoint:
    def test_returns_episode(self):
        ep_id = uuid.uuid4()
        ep = make_episode(id=ep_id, title="Detail Episode")

        with patch("podcast.routers.api.get_episode", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = ep
            db = AsyncMock()
            client = _make_test_client(db)
            response = client.get(f"/api/episodes/{ep_id}")

        assert response.status_code == 200
        assert response.json()["title"] == "Detail Episode"

    def test_not_found_returns_404(self):
        with patch("podcast.routers.api.get_episode", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            client = _make_test_client(AsyncMock())
            response = client.get(f"/api/episodes/{uuid.uuid4()}")

        assert response.status_code == 404


class TestDeleteEpisodeEndpoint:
    def test_successful_delete(self):
        with patch("podcast.routers.api.delete_episode", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = True
            client = _make_test_client(AsyncMock())
            response = client.delete(f"/api/episodes/{uuid.uuid4()}")

        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

    def test_not_found_returns_404(self):
        with patch("podcast.routers.api.delete_episode", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = False
            client = _make_test_client(AsyncMock())
            response = client.delete(f"/api/episodes/{uuid.uuid4()}")

        assert response.status_code == 404


class TestRetryEpisodeEndpoint:
    def test_successful_retry(self):
        ep = make_episode(status="pending", failed_step=None, error_message=None)

        with patch("podcast.routers.api.retry_episode", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = ep
            client = _make_test_client(AsyncMock())
            response = client.post(f"/api/episodes/{ep.id}/retry")

        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    def test_non_failed_returns_400(self):
        with patch("podcast.routers.api.retry_episode", new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = None
            client = _make_test_client(AsyncMock())
            response = client.post(f"/api/episodes/{uuid.uuid4()}/retry")

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestGetSettingsEndpoint:
    def test_returns_existing_settings(self):
        settings = make_settings(title="My Podcast")
        db = AsyncMock()
        db.get = AsyncMock(return_value=settings)

        client = _make_test_client(db)
        response = client.get("/api/settings")

        assert response.status_code == 200
        assert response.json()["title"] == "My Podcast"

    def test_creates_default_settings_if_none(self):
        """When no settings exist, the endpoint creates a default PodcastSettings."""
        db = AsyncMock()
        db.get = AsyncMock(return_value=None)
        added = []
        db.add = lambda obj: added.append(obj)

        # Simulate flush populating defaults (as SQLAlchemy would)
        async def mock_flush():
            for obj in added:
                if hasattr(obj, "title") and obj.title is None:
                    obj.title = "My Private Podcast"
                    obj.description = "AI-generated podcast episodes"
                    obj.author = "Podcast Bot"
                    obj.language = "en"
                    obj.host_a_name = "Alex"
                    obj.host_b_name = "Sam"

        db.flush = AsyncMock(side_effect=mock_flush)

        client = _make_test_client(db)
        response = client.get("/api/settings")

        assert response.status_code == 200
        assert len(added) == 1


class TestUpdateSettingsEndpoint:
    def test_updates_settings(self):
        settings = make_settings(title="Old Title")
        db = AsyncMock()
        db.get = AsyncMock(return_value=settings)

        client = _make_test_client(db)
        response = client.put("/api/settings", json={"title": "New Title"})

        assert response.status_code == 200
        assert settings.title == "New Title"

    def test_partial_update(self):
        settings = make_settings(title="Original", author="Original Author")
        db = AsyncMock()
        db.get = AsyncMock(return_value=settings)

        client = _make_test_client(db)
        response = client.put("/api/settings", json={"author": "New Author"})

        assert response.status_code == 200
        assert settings.author == "New Author"
        # title should not change since it wasn't in the request
        assert settings.title == "Original"


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


class TestGetLogsEndpoint:
    def test_returns_logs(self):
        log = make_log_entry(message="Test log")
        db = AsyncMock()
        log_result = MagicMock()
        log_scalars = MagicMock()
        log_scalars.all.return_value = [log]
        log_result.scalars.return_value = log_scalars

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        db.execute = AsyncMock(side_effect=[log_result, count_result])

        client = _make_test_client(db)
        response = client.get("/api/logs")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["logs"]) == 1

    def test_pagination(self):
        db = AsyncMock()
        log_result = MagicMock()
        log_scalars = MagicMock()
        log_scalars.all.return_value = []
        log_result.scalars.return_value = log_scalars

        count_result = MagicMock()
        count_result.scalar_one.return_value = 150

        db.execute = AsyncMock(side_effect=[log_result, count_result])

        client = _make_test_client(db)
        response = client.get("/api/logs?page=1&page_size=100")

        assert response.status_code == 200
        data = response.json()
        assert data["has_more"] is True
        assert data["page"] == 1
        assert data["page_size"] == 100


# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------


class TestCalcCost:
    def test_zero(self):
        assert _calc_cost(0, 0) == 0.0

    def test_calculation(self):
        cost = _calc_cost(1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)

    def test_only_input(self):
        cost = _calc_cost(1_000_000, 0)
        assert cost == pytest.approx(3.0)

    def test_only_output(self):
        cost = _calc_cost(0, 1_000_000)
        assert cost == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# Metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_empty_metrics(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        client = _make_test_client(db)
        response = client.get("/api/metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["totals"]["episodes"] == 0
        assert data["episodes"] == []

    def test_metrics_with_completed_jobs(self):
        now = datetime.now(timezone.utc)
        job = make_job(
            step="research",
            status="completed",
            started_at=now,
            completed_at=now,
            metrics_json=json.dumps({
                "input_tokens": 1000,
                "output_tokens": 500,
                "duration_seconds": 5.0,
            }),
        )
        ep = make_episode(status="ready", audio_duration_seconds=600, jobs=[job])

        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [ep]
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        client = _make_test_client(db)
        response = client.get("/api/metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["totals"]["episodes"] == 1
        assert data["totals"]["episodes_ready"] == 1
        assert data["totals"]["total_input_tokens"] == 1000
        assert data["totals"]["total_output_tokens"] == 500
        assert data["totals"]["total_audio_seconds"] == 600

    def test_metrics_tts_time_accumulation(self):
        now = datetime.now(timezone.utc)
        tts_job = make_job(
            step="tts",
            status="completed",
            started_at=now,
            completed_at=now,
            metrics_json=json.dumps({"duration_seconds": 120.5}),
        )
        ep = make_episode(status="ready", jobs=[tts_job])

        db = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [ep]
        mock_result.scalars.return_value = mock_scalars
        db.execute = AsyncMock(return_value=mock_result)

        client = _make_test_client(db)
        response = client.get("/api/metrics")

        data = response.json()
        assert data["totals"]["total_tts_seconds"] == 120.5
