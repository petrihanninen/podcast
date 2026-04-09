"""Tests for podcast.routers.feed endpoint."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from podcast.routers.feed import router
from tests.conftest import make_user


def _make_test_client(db_mock):
    app = FastAPI()
    app.include_router(router)

    async def override_get_db():
        yield db_mock

    from podcast.database import get_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


_TEST_FEED_TOKEN = "test-feed-token-abc123"


class TestFeedEndpoint:
    def test_returns_rss_xml(self):
        db = AsyncMock()
        user = make_user(feed_token=_TEST_FEED_TOKEN, enabled=True)

        # Mock the user lookup query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.routers.feed.generate_feed", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = '<?xml version="1.0"?><rss></rss>'
            client = _make_test_client(db)
            response = client.get(f"/feed/{_TEST_FEED_TOKEN}.xml")

        assert response.status_code == 200
        assert "application/rss+xml" in response.headers["content-type"]
        assert "<?xml" in response.text

    def test_content_type_is_rss(self):
        db = AsyncMock()
        user = make_user(feed_token=_TEST_FEED_TOKEN, enabled=True)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        db.execute = AsyncMock(return_value=mock_result)

        with patch("podcast.routers.feed.generate_feed", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "<rss>test</rss>"
            client = _make_test_client(db)
            response = client.get(f"/feed/{_TEST_FEED_TOKEN}.xml")

        assert "application/rss+xml" in response.headers["content-type"]
        assert "charset=utf-8" in response.headers["content-type"]

    def test_invalid_token_returns_404(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        client = _make_test_client(db)
        response = client.get("/feed/invalid-token.xml")

        assert response.status_code == 404
