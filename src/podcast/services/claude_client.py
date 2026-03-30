"""Shared Anthropic client with retry and rate-limit handling."""

import anthropic

from podcast.config import settings

# The Anthropic SDK automatically retries on 429 (rate limit) and transient
# server errors (500, 502, 503, 504) using exponential backoff that respects
# the Retry-After header.  The default max_retries is 2 which is too
# aggressive for bursty workloads — raise it so the worker survives
# short rate-limit windows instead of failing the job immediately.

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    """Return a singleton AsyncAnthropic client with generous retry settings."""
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=5,
        )
    return _client
