"""Settings. Everything comes from the environment (or a .env file next to the service).

The model-provider allowlist implements PRD PHI1: the service refuses to start a request
against any provider, model or endpoint that is not explicitly approved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Model gateway (PHI1, PHI4). Two providers are supported: "anthropic" (direct) and
    # "openrouter" (OpenAI-compatible; model slugs look like "anthropic/claude-sonnet-5").
    provider: str = os.environ.get("COPILOT_PROVIDER", "anthropic")
    model: str = os.environ.get("COPILOT_MODEL", "claude-sonnet-5")
    allowed_providers: list[str] = field(default_factory=lambda: _csv(os.environ.get("COPILOT_ALLOWED_PROVIDERS", "anthropic")))
    allowed_models: list[str] = field(default_factory=lambda: _csv(os.environ.get("COPILOT_ALLOWED_MODELS", "claude-sonnet-5")))
    allowed_endpoints: list[str] = field(default_factory=lambda: _csv(os.environ.get("COPILOT_ALLOWED_ENDPOINTS", "https://api.anthropic.com")))
    anthropic_base_url: str = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    openrouter_base_url: str = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_api_key: str = os.environ.get("OPENROUTER_API_KEY", "")
    # The eval judge may use a different (usually stronger) model than the agent; same provider,
    # and it must be on the same allowlist. Empty means "same model as the agent".
    judge_model: str = os.environ.get("COPILOT_JUDGE_MODEL", "")
    # Week 2: the model that reads document images. Defaults to the agent model; must be on the
    # allowlist like any other. Free slugs may log inputs provider-side, so the default path is
    # demo-data only (ARCHITECTURE.md, AUDIT.md).
    vision_model: str = os.environ.get("COPILOT_VISION_MODEL", "") or os.environ.get("COPILOT_MODEL", "claude-sonnet-5")
    max_document_pages: int = int(os.environ.get("COPILOT_MAX_DOCUMENT_PAGES", "6"))
    # A document read waits through fewer rate-limit retries than an answer: on a dead free-tier
    # quota the third retry never succeeds, and several documents in one run would outlast the
    # module's request timeout. One retry, then "could not be read", said plainly.
    vision_rate_limit_retries: int = int(os.environ.get("COPILOT_VISION_RATE_LIMIT_RETRIES", "1"))
    max_document_bytes: int = int(os.environ.get("COPILOT_MAX_DOCUMENT_BYTES", str(8 * 1024 * 1024)))
    # Week 2: guideline retrieval. "none" for embed_model runs BM25 only with no models and no
    # network, which is what the tests and the eval gate use.
    guidelines_dir: str = os.environ.get("COPILOT_GUIDELINES_DIR", "")
    embed_model: str = os.environ.get("COPILOT_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    rerank: str = os.environ.get("COPILOT_RERANK", "local")            # local | cohere | none
    rerank_model: str = os.environ.get("COPILOT_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    cohere_api_key: str = os.environ.get("COHERE_API_KEY", "")
    cohere_rerank_model: str = os.environ.get("COPILOT_COHERE_RERANK_MODEL", "rerank-v3.5")
    retrieval_top_k: int = int(os.environ.get("COPILOT_RETRIEVAL_TOP_K", "3"))
    retrieval_candidates: int = int(os.environ.get("COPILOT_RETRIEVAL_CANDIDATES", "10"))
    # OpenRouter reasoning models think before answering and count that against max_tokens;
    # on structured, tool-grounded calls the thinking sometimes runs away until the cap and the
    # answer is lost (measured: 185 hidden tokens normally, 3000+ when it spirals). Off by default.
    openrouter_reasoning: str = os.environ.get("COPILOT_REASONING", "off")   # off | default | low | medium | high
    # Classify each follow-up question on its own, with no conversation history, before any tool
    # runs. A model's off-topic judgement degrades once earlier answers are in context (measured:
    # "what is the weather" after a lab answer re-emitted the labs); the question alone classifies
    # reliably. One small extra call per follow-up.
    topic_check: bool = os.environ.get("COPILOT_TOPIC_CHECK", "1").lower() in ("1", "true", "yes")
    # The brief is a structured document with up to seven sections; 2000 tokens truncated it.
    max_output_tokens: int = int(os.environ.get("COPILOT_MAX_OUTPUT_TOKENS", "12000"))
    model_timeout_s: float = float(os.environ.get("COPILOT_MODEL_TIMEOUT_S", "40"))

    # Agent loop
    max_iterations: int = int(os.environ.get("COPILOT_MAX_ITERATIONS", "5"))
    comparison_hours: int = int(os.environ.get("COPILOT_COMPARISON_HOURS", "24"))
    recent_lab_days: int = int(os.environ.get("COPILOT_RECENT_LAB_DAYS", "180"))
    prefetch_concurrency: int = int(os.environ.get("COPILOT_PREFETCH_CONCURRENCY", "12"))
    # A brief is regenerated only when the chart behind it changes, so reopening the panel
    # reuses the previous one instead of paying for it again. Entries are keyed by patient,
    # chart fingerprint and model, so a data change or a model change both invalidate.
    brief_cache_size: int = int(os.environ.get("COPILOT_BRIEF_CACHE", "200"))
    prefetch_budget_s: int = int(os.environ.get("COPILOT_PREFETCH_BUDGET_S", "90"))
    answer_deadline_s: float = float(os.environ.get("COPILOT_ANSWER_DEADLINE_S", "60"))

    # Session store
    session_idle_minutes: int = int(os.environ.get("COPILOT_SESSION_IDLE_MINUTES", "120"))

    # Gateway auth (the PHP module signs every request with this secret)
    shared_secret: str = os.environ.get("COPILOT_SHARED_SECRET", "")
    signature_skew_s: int = int(os.environ.get("COPILOT_SIGNATURE_SKEW_S", "300"))

    # Observability (PHI7)
    langsmith_tracing: bool = os.environ.get("LANGSMITH_TRACING", "false").lower() in ("1", "true", "yes")
    langsmith_project: str = os.environ.get("LANGSMITH_PROJECT", "openemr-copilot")
    langsmith_endpoint: str = os.environ.get("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    # Data flows OpenEMR -> agent, so the agent never calls OpenEMR and cannot infer its address.
    # /ready needs one to probe, so it is configured explicitly and reported as missing if absent.
    openemr_url: str = os.environ.get("COPILOT_OPENEMR_URL", "")
    langsmith_api_key: str = os.environ.get("LANGSMITH_API_KEY", "")
    trace_redact: bool = os.environ.get("COPILOT_TRACE_REDACT", "false").lower() in ("1", "true", "yes")

    demo_disclaimer: str = "Demo data only. Not clinically validated for patient care."

    def endpoint(self) -> str:
        return self.openrouter_base_url if self.provider == "openrouter" else self.anthropic_base_url

    def api_key(self) -> str:
        return self.openrouter_api_key if self.provider == "openrouter" else self.anthropic_api_key

    def provider_approved(self, model: str | None = None) -> tuple[bool, str]:
        """PHI1: allowlisted provider, model and endpoint; fail closed otherwise."""
        model = model or self.model
        if self.provider not in ("anthropic", "openrouter"):
            return False, f"provider '{self.provider}' is not supported"
        if self.provider not in self.allowed_providers:
            return False, f"provider '{self.provider}' is not on the allowlist"
        if model not in self.allowed_models:
            return False, f"model '{model}' is not on the allowlist"
        if self.endpoint().rstrip("/") not in [e.rstrip("/") for e in self.allowed_endpoints]:
            return False, "model endpoint is not on the allowlist"
        if not self.api_key():
            return False, "no model API key configured"
        return True, "approved"


def get_settings() -> Settings:
    settings = Settings()
    # LangChain reads LANGSMITH_TRACING straight from the environment. Tracing without a key
    # only produces failed uploads, so normalise it here: on only when a key is present.
    os.environ["LANGSMITH_TRACING"] = "true" if (settings.langsmith_tracing and settings.langsmith_api_key) else "false"
    return settings
