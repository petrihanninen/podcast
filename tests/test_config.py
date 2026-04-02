"""Tests for podcast.config."""

import os
from unittest.mock import patch

from podcast.config import Settings


class TestSettings:
    def test_default_database_url(self):
        s = Settings()
        assert "postgresql+asyncpg" in s.database_url
        assert "podcast" in s.database_url

    def test_default_audio_dir(self):
        s = Settings()
        assert s.audio_dir == "/data/audio"

    def test_default_base_url(self):
        s = Settings()
        assert s.base_url == "http://localhost:9001"

    def test_default_anthropic_api_key_empty(self):
        s = Settings()
        assert s.anthropic_api_key == ""

    def test_custom_values_from_env(self):
        env = {
            "DATABASE_URL": "postgresql+asyncpg://custom:custom@db:5432/custom",
            "ANTHROPIC_API_KEY": "sk-test-key",
            "AUDIO_DIR": "/tmp/audio",
            "BASE_URL": "https://podcast.example.com",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings()
        assert s.database_url == env["DATABASE_URL"]
        assert s.anthropic_api_key == env["ANTHROPIC_API_KEY"]
        assert s.audio_dir == env["AUDIO_DIR"]
        assert s.base_url == env["BASE_URL"]

    def test_extra_env_vars_ignored(self):
        """Settings should ignore unknown environment variables (extra='ignore')."""
        with patch.dict(os.environ, {"UNKNOWN_VAR": "value"}, clear=False):
            s = Settings()
        assert not hasattr(s, "unknown_var")
