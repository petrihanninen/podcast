"""Tests for podcast.main (app initialization).

podcast.main has module-level side effects (os.makedirs, StaticFiles mounts)
that make it difficult to import in test environments. We test the from_json
filter logic directly and test app setup via import when directories exist.
"""

import json
import os
import tempfile
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Test the from_json filter logic (same implementation as podcast.main.from_json)
# ---------------------------------------------------------------------------


def _from_json(value):
    """Replicate from_json for testing without importing main."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


class TestFromJsonFilter:
    def test_valid_json_array(self):
        result = _from_json('[{"speaker": "Alex", "text": "Hello"}]')
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["speaker"] == "Alex"

    def test_valid_json_object(self):
        data = {"key": [1, 2, 3], "nested": {"a": "b"}}
        result = _from_json(json.dumps(data))
        assert result["key"] == [1, 2, 3]
        assert result["nested"]["a"] == "b"

    def test_invalid_json_returns_empty_list(self):
        result = _from_json("not json")
        assert result == []

    def test_none_returns_empty_list(self):
        result = _from_json(None)
        assert result == []

    def test_empty_string_returns_empty_list(self):
        result = _from_json("")
        assert result == []

    def test_valid_empty_array(self):
        result = _from_json("[]")
        assert result == []

    def test_valid_number(self):
        result = _from_json("42")
        assert result == 42

    def test_valid_string(self):
        result = _from_json('"hello"')
        assert result == "hello"


class TestAppImport:
    """Test that the app can be imported with proper filesystem setup."""

    def test_app_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_dir = os.path.join(tmpdir, "audio")
            os.makedirs(audio_dir)
            os.makedirs(os.path.join(audio_dir, "segments"))

            with patch("podcast.config.settings") as mock_settings:
                mock_settings.audio_dir = audio_dir
                mock_settings.base_url = "http://localhost:8000"
                mock_settings.database_url = "postgresql+asyncpg://test:test@localhost/test"

                # Force re-import by removing from cache
                import sys
                was_imported = "podcast.main" in sys.modules
                if was_imported:
                    saved = sys.modules.pop("podcast.main")

                try:
                    import podcast.main

                    assert podcast.main.app.title == "Podcast Generator"

                    # Verify routes exist
                    route_paths = [r.path for r in podcast.main.app.routes]
                    assert "/api/health" in route_paths
                    assert "/feed.xml" in route_paths

                    # Verify from_json is registered as a filter
                    result = podcast.main.from_json('[{"a":1}]')
                    assert result == [{"a": 1}]
                finally:
                    if was_imported:
                        sys.modules["podcast.main"] = saved
