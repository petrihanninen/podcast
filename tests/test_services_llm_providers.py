"""Tests for podcast.services.llm_providers."""

import pytest

from podcast.services.llm_providers import (
    DEFAULT_RESEARCH_MODEL,
    DEFAULT_TRANSCRIPT_MODEL,
    LLMResponse,
    ModelInfo,
    RESEARCH_MODELS,
    TRANSCRIPT_MODELS,
    get_all_model_pricing,
    get_research_model,
    get_transcript_model,
)


class TestLLMResponse:
    def test_creation(self):
        """LLMResponse can be created with required fields."""
        response = LLMResponse(
            text="Hello",
            input_tokens=10,
            output_tokens=20,
            model="test-model"
        )
        assert response.text == "Hello"
        assert response.input_tokens == 10
        assert response.output_tokens == 20
        assert response.model == "test-model"


class TestModelInfo:
    def test_creation(self):
        """ModelInfo can be created with required fields."""
        model = ModelInfo(
            id="test-id",
            provider="anthropic",
            model_id="test-model-v1",
            display_name="Test Model",
            supports_web_search=True,
            pricing={"input": 1.0, "output": 2.0}
        )
        assert model.id == "test-id"
        assert model.provider == "anthropic"
        assert model.model_id == "test-model-v1"
        assert model.display_name == "Test Model"
        assert model.supports_web_search is True
        assert model.pricing == {"input": 1.0, "output": 2.0}


class TestResearchModels:
    def test_registry_not_empty(self):
        """RESEARCH_MODELS registry should have entries."""
        assert len(RESEARCH_MODELS) > 0

    def test_all_entries_are_model_info(self):
        """All entries in RESEARCH_MODELS should be ModelInfo instances."""
        for key, model in RESEARCH_MODELS.items():
            assert isinstance(model, ModelInfo)
            assert model.id == key

    def test_model_has_required_fields(self):
        """Each research model should have all required fields."""
        for key, model in RESEARCH_MODELS.items():
            assert model.id
            assert model.provider
            assert model.model_id
            assert model.display_name
            assert model.supports_web_search is not None
            assert isinstance(model.pricing, dict)
            assert "input" in model.pricing
            assert "output" in model.pricing

    def test_default_model_exists(self):
        """The default research model should exist in registry."""
        assert DEFAULT_RESEARCH_MODEL in RESEARCH_MODELS


class TestTranscriptModels:
    def test_registry_not_empty(self):
        """TRANSCRIPT_MODELS registry should have entries."""
        assert len(TRANSCRIPT_MODELS) > 0

    def test_all_entries_are_model_info(self):
        """All entries in TRANSCRIPT_MODELS should be ModelInfo instances."""
        for key, model in TRANSCRIPT_MODELS.items():
            assert isinstance(model, ModelInfo)
            assert model.id == key

    def test_model_has_required_fields(self):
        """Each transcript model should have all required fields."""
        for key, model in TRANSCRIPT_MODELS.items():
            assert model.id
            assert model.provider
            assert model.model_id
            assert model.display_name
            assert model.supports_web_search is not None
            assert isinstance(model.pricing, dict)
            assert "input" in model.pricing
            assert "output" in model.pricing

    def test_default_model_exists(self):
        """The default transcript model should exist in registry."""
        assert DEFAULT_TRANSCRIPT_MODEL in TRANSCRIPT_MODELS


class TestGetResearchModel:
    def test_returns_model_by_key(self):
        """get_research_model should return correct model by key."""
        model = get_research_model("gpt-nano")
        assert model.id == "gpt-nano"
        assert isinstance(model, ModelInfo)

    def test_returns_default_when_none(self):
        """get_research_model should use default when key is None."""
        model = get_research_model(None)
        assert model.id == DEFAULT_RESEARCH_MODEL

    def test_empty_string_falls_back_to_default(self):
        """get_research_model treats empty string as falsy, uses default."""
        model = get_research_model("")
        assert model.id == DEFAULT_RESEARCH_MODEL

    def test_raises_for_unknown_model(self):
        """get_research_model should raise for unknown model key."""
        with pytest.raises(ValueError, match="Unknown research model"):
            get_research_model("nonexistent-model")

    def test_error_message_lists_available(self):
        """Error message should list available models."""
        try:
            get_research_model("invalid")
        except ValueError as e:
            assert "Available:" in str(e)


class TestGetTranscriptModel:
    def test_returns_model_by_key(self):
        """get_transcript_model should return correct model by key."""
        model = get_transcript_model("gpt-mini")
        assert model.id == "gpt-mini"
        assert isinstance(model, ModelInfo)

    def test_returns_default_when_none(self):
        """get_transcript_model should use default when key is None."""
        model = get_transcript_model(None)
        assert model.id == DEFAULT_TRANSCRIPT_MODEL

    def test_empty_string_falls_back_to_default(self):
        """get_transcript_model treats empty string as falsy, uses default."""
        model = get_transcript_model("")
        assert model.id == DEFAULT_TRANSCRIPT_MODEL

    def test_raises_for_unknown_model(self):
        """get_transcript_model should raise for unknown model key."""
        with pytest.raises(ValueError, match="Unknown transcript model"):
            get_transcript_model("nonexistent-model")

    def test_error_message_lists_available(self):
        """Error message should list available models."""
        try:
            get_transcript_model("invalid")
        except ValueError as e:
            assert "Available:" in str(e)


class TestGetAllModelPricing:
    def test_returns_dict(self):
        """get_all_model_pricing should return a dictionary."""
        pricing = get_all_model_pricing()
        assert isinstance(pricing, dict)

    def test_contains_both_registries(self):
        """Pricing should include models from both registries."""
        pricing = get_all_model_pricing()
        # Should have entries from research and transcript models
        research_models_count = sum(1 for m in RESEARCH_MODELS.values())
        transcript_models_count = sum(1 for m in TRANSCRIPT_MODELS.values())
        # Note: if a model appears in both, it's counted once (dict keys)
        assert len(pricing) >= max(research_models_count, transcript_models_count)

    def test_pricing_format(self):
        """Each pricing entry should have input and output costs."""
        pricing = get_all_model_pricing()
        for model_id, price_dict in pricing.items():
            assert isinstance(price_dict, dict)
            assert "input" in price_dict
            assert "output" in price_dict
            assert isinstance(price_dict["input"], (int, float))
            assert isinstance(price_dict["output"], (int, float))

    def test_pricing_is_not_empty(self):
        """Pricing dict should not be empty."""
        pricing = get_all_model_pricing()
        assert len(pricing) > 0

    def test_all_registered_models_have_pricing(self):
        """All models should have pricing info."""
        pricing = get_all_model_pricing()
        for research_model in RESEARCH_MODELS.values():
            assert research_model.model_id in pricing
        for transcript_model in TRANSCRIPT_MODELS.values():
            assert transcript_model.model_id in pricing


class TestModelProviders:
    def test_research_models_have_valid_providers(self):
        """All research models should use valid provider names."""
        valid_providers = {"anthropic", "google", "openai", "perplexity", "deepseek"}
        for model in RESEARCH_MODELS.values():
            assert model.provider in valid_providers

    def test_transcript_models_have_valid_providers(self):
        """All transcript models should use valid provider names."""
        valid_providers = {"anthropic", "google", "openai", "perplexity", "deepseek"}
        for model in TRANSCRIPT_MODELS.values():
            assert model.provider in valid_providers

    def test_openai_models_in_both_registries(self):
        """At least one OpenAI model should be in both registries."""
        research_openai = any(m.provider == "openai" for m in RESEARCH_MODELS.values())
        transcript_openai = any(m.provider == "openai" for m in TRANSCRIPT_MODELS.values())
        assert research_openai
        assert transcript_openai


class TestWebSearchSupport:
    def test_research_models_web_search_flag(self):
        """Research models should indicate web search support."""
        for model in RESEARCH_MODELS.values():
            # Should be either True or False
            assert isinstance(model.supports_web_search, bool)

    def test_transcript_models_typically_no_web_search(self):
        """Transcript models typically don't need web search."""
        # This is a soft check - we expect most transcript models to have False
        has_false = any(not m.supports_web_search for m in TRANSCRIPT_MODELS.values())
        assert has_false

    def test_anthropic_research_supports_web_search(self):
        """Claude (Anthropic) research model should support web search."""
        if "claude-sonnet" in RESEARCH_MODELS:
            model = RESEARCH_MODELS["claude-sonnet"]
            assert model.supports_web_search is True
