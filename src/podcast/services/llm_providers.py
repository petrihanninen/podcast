"""
Multi-LLM provider abstraction layer.

Supports: Anthropic (Claude), Google (Gemini), OpenAI, Perplexity, DeepSeek.
Designed for easy expansion — add new models by appending to the registries,
and new providers by adding a completion function + base URL entry.

Usage:
    from podcast.services.llm_providers import complete, get_research_model

    model = get_research_model("claude-sonnet")
    response = await complete(model, system="...", user_message="...", use_web_search=True)
    print(response.text, response.input_tokens, response.output_tokens)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from podcast.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Standardised response from any LLM provider."""
    text: str
    input_tokens: int
    output_tokens: int
    model: str


# ---------------------------------------------------------------------------
# Model registry entry
# ---------------------------------------------------------------------------

@dataclass
class ModelInfo:
    """Metadata for a registered model."""
    id: str                     # Internal key (e.g. "claude-sonnet")
    provider: str               # Provider key (e.g. "anthropic")
    model_id: str               # Wire model string sent to the API
    display_name: str           # Human-readable label for the UI
    supports_web_search: bool   # True if provider has built-in or tool-based search
    pricing: dict               # {"input": float, "output": float} — $ per 1M tokens


# ---------------------------------------------------------------------------
# Provider base URLs (OpenAI-compatible providers)
# ---------------------------------------------------------------------------

PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "perplexity": "https://api.perplexity.ai",
    "deepseek": "https://api.deepseek.com",
}


# ---------------------------------------------------------------------------
# Provider implementation: Anthropic (Claude)
# ---------------------------------------------------------------------------

async def _complete_anthropic(
    model_id: str,
    system: str,
    user_message: str,
    max_tokens: int,
    temperature: float,
    use_web_search: bool = False,
) -> LLMResponse:
    from podcast.services.claude_client import get_client

    client = get_client()

    kwargs: dict = dict(
        model=model_id,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    if temperature != 1.0:
        kwargs["temperature"] = temperature
    if use_web_search:
        kwargs["tools"] = [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": 10}
        ]

    response = await client.messages.create(**kwargs)

    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text

    return LLMResponse(
        text=text,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        model=model_id,
    )


# ---------------------------------------------------------------------------
# Provider implementation: OpenAI-compatible (OpenAI, Perplexity, DeepSeek)
# ---------------------------------------------------------------------------

async def _complete_openai_compatible(
    base_url: str,
    api_key: str,
    model_id: str,
    system: str,
    user_message: str,
    max_tokens: int,
    temperature: float,
    web_search_options: dict | None = None,
) -> LLMResponse:
    """Generic OpenAI chat-completions client with retry."""
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(300.0, connect=30.0),
    ) as client:
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if web_search_options is not None:
            payload["web_search_options"] = web_search_options

        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (429, 500, 502, 503, 504):
                    wait = min(2**attempt * 2, 60)
                    logger.warning(
                        "%s %s error %d (attempt %d/5), retrying in %ds",
                        base_url,
                        model_id,
                        exc.response.status_code,
                        attempt + 1,
                        wait,
                    )
                    await asyncio.sleep(wait)
                elif exc.response.status_code == 400:
                    try:
                        error_body = exc.response.json()
                    except Exception:
                        error_body = exc.response.text
                    logger.error(
                        "%s 400 Bad Request: %s (model=%s)",
                        base_url,
                        error_body,
                        model_id,
                    )
                    raise
                else:
                    raise
            except httpx.TimeoutException as exc:
                last_error = exc
                wait = min(2**attempt * 2, 60)
                logger.warning(
                    "Timeout at %s (attempt %d/5), retrying in %ds",
                    base_url,
                    attempt + 1,
                    wait,
                )
                await asyncio.sleep(wait)
        else:
            raise RuntimeError(
                f"API at {base_url} ({model_id}) failed after 5 attempts: {last_error}"
            ) from last_error

    data = response.json()
    usage = data.get("usage", {})

    return LLMResponse(
        text=data["choices"][0]["message"]["content"],
        input_tokens=usage.get("prompt_tokens", 0),
        output_tokens=usage.get("completion_tokens", 0),
        model=model_id,
    )


# ---------------------------------------------------------------------------
# Provider implementation: Google Gemini (native REST API)
# ---------------------------------------------------------------------------

async def _complete_google(
    model_id: str,
    system: str,
    user_message: str,
    max_tokens: int,
    temperature: float,
    use_web_search: bool = False,
) -> LLMResponse:
    api_key = settings.google_api_key
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not configured")

    base = "https://generativelanguage.googleapis.com/v1beta"
    url = f"{base}/models/{model_id}:generateContent"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    if use_web_search:
        payload["tools"] = [{"google_search": {}}]

    async with httpx.AsyncClient(
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        timeout=httpx.Timeout(300.0, connect=30.0),
    ) as client:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (429, 500, 502, 503, 504):
                    wait = min(2**attempt * 2, 60)
                    logger.warning(
                        "Gemini error %d (attempt %d/5), retrying in %ds",
                        exc.response.status_code,
                        attempt + 1,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise
            except httpx.TimeoutException as exc:
                last_error = exc
                wait = min(2**attempt * 2, 60)
                logger.warning(
                    "Gemini timeout (attempt %d/5), retrying in %ds",
                    attempt + 1,
                    wait,
                )
                await asyncio.sleep(wait)
        else:
            raise RuntimeError(
                f"Gemini API failed after 5 attempts: {last_error}"
            ) from last_error

    data = response.json()

    # Extract text from Gemini response format
    text = ""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            text += part.get("text", "")

    usage = data.get("usageMetadata", {})

    return LLMResponse(
        text=text,
        input_tokens=usage.get("promptTokenCount", 0),
        output_tokens=usage.get("candidatesTokenCount", 0),
        model=model_id,
    )


# ---------------------------------------------------------------------------
# API key resolver
# ---------------------------------------------------------------------------

def _get_api_key(provider: str) -> str:
    """Resolve API key from settings for the given provider."""
    key_map = {
        "anthropic": settings.anthropic_api_key,
        "google": settings.google_api_key,
        "openai": settings.openai_api_key,
        "perplexity": settings.perplexity_api_key,
        "deepseek": settings.deepseek_api_key,
    }
    api_key = key_map.get(provider, "")
    if not api_key:
        provider_upper = provider.upper()
        raise RuntimeError(
            f"{provider_upper}_API_KEY is not configured. "
            f"Set the {provider_upper}_API_KEY environment variable."
        )
    return api_key


# ===================================================================
# MODEL REGISTRIES
#
# To add a new model:   append an entry to the appropriate dict.
# To add a new vendor:  1) add a base URL to PROVIDER_BASE_URLS
#                           (or a dedicated _complete_* function),
#                        2) add the env-var mapping in _get_api_key,
#                        3) add the field in config.py Settings.
# ===================================================================

RESEARCH_MODELS: dict[str, ModelInfo] = {
    "claude-sonnet": ModelInfo(
        id="claude-sonnet",
        provider="anthropic",
        model_id="claude-sonnet-4-6-20250514",
        display_name="Claude Sonnet 4.6",
        supports_web_search=True,
        pricing={"input": 3.0, "output": 15.0},
    ),
    "gemini-flash": ModelInfo(
        id="gemini-flash",
        provider="google",
        model_id="gemini-2.5-flash",
        display_name="Gemini 3 Flash",
        supports_web_search=True,
        pricing={"input": 0.50, "output": 3.0},
    ),
    "perplexity-deep-research": ModelInfo(
        id="perplexity-deep-research",
        provider="perplexity",
        model_id="sonar-deep-research",
        display_name="Perplexity Sonar Deep Research",
        supports_web_search=True,
        pricing={"input": 2.0, "output": 8.0},
    ),
    "gpt-nano": ModelInfo(
        id="gpt-nano",
        provider="openai",
        model_id="gpt-5-nano-2025-08-07",
        display_name="GPT-5 Nano",
        supports_web_search=True,
        pricing={"input": 0.05, "output": 0.40},
    ),
}

TRANSCRIPT_MODELS: dict[str, ModelInfo] = {
    "claude-sonnet": ModelInfo(
        id="claude-sonnet",
        provider="anthropic",
        model_id="claude-sonnet-4-6-20250514",
        display_name="Claude Sonnet 4.6",
        supports_web_search=False,
        pricing={"input": 3.0, "output": 15.0},
    ),
    "gemini-flash": ModelInfo(
        id="gemini-flash",
        provider="google",
        model_id="gemini-2.5-flash",
        display_name="Gemini 3 Flash",
        supports_web_search=False,
        pricing={"input": 0.50, "output": 3.0},
    ),
    "perplexity-pro": ModelInfo(
        id="perplexity-pro",
        provider="perplexity",
        model_id="sonar-pro",
        display_name="Perplexity Sonar Pro Writing",
        supports_web_search=False,
        pricing={"input": 3.0, "output": 15.0},
    ),
    "gpt-mini": ModelInfo(
        id="gpt-mini",
        provider="openai",
        model_id="gpt-5.4-mini-2026-03-17",
        display_name="GPT 5.4-mini",
        supports_web_search=False,
        pricing={"input": 0.75, "output": 4.50},
    ),
    "deepseek": ModelInfo(
        id="deepseek",
        provider="deepseek",
        model_id="deepseek-chat",
        display_name="DeepSeek",
        supports_web_search=False,
        pricing={"input": 0.27, "output": 1.10},
    ),
}

DEFAULT_RESEARCH_MODEL = "claude-sonnet"
DEFAULT_TRANSCRIPT_MODEL = "deepseek"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_research_model(model_key: str | None = None) -> ModelInfo:
    """Look up a research model by registry key. Falls back to the default."""
    key = model_key or DEFAULT_RESEARCH_MODEL
    if key not in RESEARCH_MODELS:
        raise ValueError(
            f"Unknown research model '{key}'. "
            f"Available: {list(RESEARCH_MODELS.keys())}"
        )
    return RESEARCH_MODELS[key]


def get_transcript_model(model_key: str | None = None) -> ModelInfo:
    """Look up a transcript model by registry key. Falls back to the default."""
    key = model_key or DEFAULT_TRANSCRIPT_MODEL
    if key not in TRANSCRIPT_MODELS:
        raise ValueError(
            f"Unknown transcript model '{key}'. "
            f"Available: {list(TRANSCRIPT_MODELS.keys())}"
        )
    return TRANSCRIPT_MODELS[key]


def get_all_model_pricing() -> dict[str, dict[str, float]]:
    """Collect pricing for every registered model_id (for cost calculation)."""
    pricing: dict[str, dict[str, float]] = {}
    for registry in (RESEARCH_MODELS, TRANSCRIPT_MODELS):
        for info in registry.values():
            pricing[info.model_id] = info.pricing
    return pricing


async def complete(
    model_info: ModelInfo,
    system: str,
    user_message: str,
    max_tokens: int = 8192,
    temperature: float = 1.0,
    use_web_search: bool = False,
) -> LLMResponse:
    """
    Universal completion — routes to the correct provider.

    For research with ``use_web_search=True``:
      • Anthropic  → Claude web_search tool
      • Google     → Gemini google_search grounding tool
      • OpenAI     → search model variant + web_search_options
      • Perplexity → search is built-in (automatic)
      • Others     → completes without live search data
    """
    provider = model_info.provider

    if provider == "anthropic":
        return await _complete_anthropic(
            model_info.model_id,
            system,
            user_message,
            max_tokens,
            temperature,
            use_web_search=use_web_search and model_info.supports_web_search,
        )

    if provider == "google":
        return await _complete_google(
            model_info.model_id,
            system,
            user_message,
            max_tokens,
            temperature,
            use_web_search=use_web_search and model_info.supports_web_search,
        )

    # OpenAI-compatible providers (openai, perplexity, deepseek, …)
    api_key = _get_api_key(provider)
    base_url = PROVIDER_BASE_URLS.get(provider)
    if not base_url:
        raise ValueError(
            f"No base URL for provider '{provider}'. "
            f"Add it to PROVIDER_BASE_URLS in llm_providers.py."
        )

    web_search_opts = None
    if use_web_search and model_info.supports_web_search and provider == "openai":
        web_search_opts = {}

    return await _complete_openai_compatible(
        base_url,
        api_key,
        model_info.model_id,
        system,
        user_message,
        max_tokens,
        temperature,
        web_search_options=web_search_opts,
    )
