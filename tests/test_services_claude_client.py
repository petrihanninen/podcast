"""Tests for podcast.services.claude_client."""

from unittest.mock import patch

import podcast.services.claude_client as cc_module


class TestGetClient:
    def setup_method(self):
        """Reset the singleton before each test."""
        cc_module._client = None

    def teardown_method(self):
        cc_module._client = None

    def test_returns_client(self):
        with patch("podcast.services.claude_client.anthropic") as mock_anthropic:
            mock_client = mock_anthropic.AsyncAnthropic.return_value
            client = cc_module.get_client()
            assert client is mock_client

    def test_singleton_returns_same_instance(self):
        with patch("podcast.services.claude_client.anthropic") as mock_anthropic:
            c1 = cc_module.get_client()
            c2 = cc_module.get_client()
            assert c1 is c2
            # Constructor should only be called once
            assert mock_anthropic.AsyncAnthropic.call_count == 1

    def test_configures_max_retries(self):
        with patch("podcast.services.claude_client.anthropic") as mock_anthropic:
            cc_module.get_client()
            call_kwargs = mock_anthropic.AsyncAnthropic.call_args[1]
            assert call_kwargs["max_retries"] == 5

    def test_uses_api_key_from_settings(self):
        with patch("podcast.services.claude_client.anthropic") as mock_anthropic:
            with patch("podcast.services.claude_client.settings") as mock_settings:
                mock_settings.anthropic_api_key = "sk-test-123"
                cc_module.get_client()
                call_kwargs = mock_anthropic.AsyncAnthropic.call_args[1]
                assert call_kwargs["api_key"] == "sk-test-123"
