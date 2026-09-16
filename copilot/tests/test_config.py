"""The provider allowlist (PRD PHI1) for both supported providers."""

from copilot.config import Settings


ANTHROPIC = dict(provider="anthropic", allowed_providers=["anthropic"], allowed_models=["claude-sonnet-5"],
                 allowed_endpoints=["https://api.anthropic.com"])


def test_anthropic_direct_is_approved_only_with_key_and_allowlist():
    ok = Settings(**ANTHROPIC, model="claude-sonnet-5", anthropic_api_key="k")
    assert ok.provider_approved() == (True, "approved")
    assert Settings(**ANTHROPIC, model="claude-sonnet-5", anthropic_api_key="").provider_approved()[1] == "no model API key configured"
    assert "not on the allowlist" in Settings(**ANTHROPIC, model="claude-haiku-4-5", anthropic_api_key="k").provider_approved()[1]


def test_openrouter_uses_its_own_endpoint_key_and_slugs():
    ok = Settings(provider="openrouter", model="anthropic/claude-sonnet-5", allowed_providers=["openrouter"],
                  allowed_models=["anthropic/claude-sonnet-5"], allowed_endpoints=["https://openrouter.ai/api/v1"],
                  openrouter_api_key="k", anthropic_api_key="")
    assert ok.provider_approved() == (True, "approved")
    assert ok.endpoint() == "https://openrouter.ai/api/v1"

    # An Anthropic key does not approve the OpenRouter path, and vice versa.
    no_key = Settings(provider="openrouter", model="anthropic/claude-sonnet-5", allowed_providers=["openrouter"],
                      allowed_models=["anthropic/claude-sonnet-5"], allowed_endpoints=["https://openrouter.ai/api/v1"],
                      openrouter_api_key="", anthropic_api_key="k")
    assert no_key.provider_approved()[1] == "no model API key configured"

    # OpenRouter not on the provider allowlist -> refused before anything else.
    assert "not on the allowlist" in Settings(provider="openrouter", openrouter_api_key="k").provider_approved()[1]


def test_model_error_classification_separates_endpoint_faults_from_model_faults():
    from copilot.llm import classify_model_error

    class RateLimitError(Exception):
        status_code = 429

    assert classify_model_error(RateLimitError("too many")) == "rate_limit"
    assert classify_model_error(ValueError("{'message': 'Upstream error from Nvidia: Service temporarily overloaded', 'code': 502}")) == "provider_unavailable"
    assert classify_model_error(TypeError("'NoneType' object is not iterable")) == "provider_unavailable"   # no `choices` in the reply
    assert classify_model_error(ConnectionError("down")) == "provider_unavailable"
    assert classify_model_error(ValueError("{'message': 'Provider returned error', 'code': 520}")) == "provider_unavailable"  # any gateway error body
    assert classify_model_error(ValueError("Function get_x arguments are not valid JSON")) == "other"      # a real model fault


def test_unknown_provider_is_refused():
    assert Settings(provider="azure", allowed_providers=["azure"]).provider_approved()[1] == "provider 'azure' is not supported"
