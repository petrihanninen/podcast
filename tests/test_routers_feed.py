"""Tests for podcast.routers.feed endpoint."""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from podcast.routers.feed import router


def _make_test_client(db_mock):
    app = FastAPI()
    app.include_router(router)

    async def override_get_db():
        yield db_mock

    from podcast.database import get_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


class TestFeedEndpoint:
    def test_returns_rss_xml(self):
        db = AsyncMock()

        with patch("podcast.routers.feed.generate_feed", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = '<?xml version="1.0"?><rss></rss>'
            client = _make_test_client(db)
            response = client.get("/feed.xml")

        assert response.status_code == 200
        assert "application/rss+xml" in response.headers["content-type"]
        assert "<?xml" in response.text

    def test_content_type_is_rss(self):
        db = AsyncMock()

        with patch("podcast.routers.feed.generate_feed", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "<rss>test</rss>"
            client = _make_test_client(db)
            response = client.get("/feed.xml")

        assert "application/rss+xml" in response.headers["content-type"]
        assert "charset=utf-8" in response.headers["content-type"]
