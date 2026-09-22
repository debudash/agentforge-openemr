"""The model gateway (PRD PHI1, PHI4). One approved provider configuration; fail closed.

The agent talks to the model through the small `LLM` protocol below so the loop stays
legible and testable: `LangChainLLM` wraps ChatAnthropic (traced by LangSmith through
LangChain callbacks); `ScriptedLLM` replays canned responses for unit tests and evals
that must run without a key.
"""

from __future__ import annotations

import time
from typing import Any, Protocol, Sequence, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from .config import Settings
from .telemetry import emit

T = TypeVar("T", bound=BaseModel)


class ProviderNotApproved(RuntimeError):
    """Raised before any PHI leaves the service when the model configuration is not allowlisted."""


class LLM(Protocol):
    def invoke_with_tools(self, messages: Sequence[BaseMessage], tools: Sequence[BaseTool],
                          require_tool: bool = False) -> AIMessage: ...
    def structured(self, messages: Sequence[BaseMessage], schema: type[T]) -> T: ...


def classify_model_error(exc: BaseException) -> str:
    """'rate_limit' | 'provider_unavailable' | 'other'. The first two are the endpoint's problem, not the agent's."""
    name = type(exc).__name__
    text = str(exc)[:400]
    status = getattr(exc, "status_code", None)
    if "RateLimit" in name or status == 429 or " 429" in text:
        return "rate_limit"
    if status in (502, 503, 504) or "provider_unavailable" in text or "overloaded" in text.lower() \
            or "'code': 50" in text or "Connection" in name or "Timeout" in name:
        return "provider_unavailable"
    # OpenAI-compatible gateways answer an upstream outage with an error body and no `choices`;
    # the client's structured-output parser then fails with exactly this TypeError, and other
    # code paths raise ValueError carrying the gateway's error dict verbatim.
    if name == "TypeError" and "'NoneType' object is not iterable" in text:
        return "provider_unavailable"
    if name == "ValueError" and text.lstrip().startswith("{'message'"):
        return "provider_unavailable"
    return "other"


def error_excerpt(exc: BaseException) -> str | None:
    """A short excerpt of an unclassified model error, only when COPILOT_DEBUG_MODEL_ERRORS=1.

    Off by default because exception text can echo prompt content. Turn it on locally, with
    synthetic data, to identify a new failure signature; never in a deployment with PHI.
    """
    import os

    if os.environ.get("COPILOT_DEBUG_MODEL_ERRORS", "") not in ("1", "true"):
        return None
    return str(exc)[:160]


def _is_rate_limit(exc: BaseException) -> bool:
    return classify_model_error(exc) in ("rate_limit", "provider_unavailable")


def _retry_after_seconds(exc: BaseException, attempt: int) -> float:
    """Honour a Retry-After header when the provider sends one; otherwise back off geometrically."""
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}).get("retry-after") if response is not None else None
    try:
        if header:
            return min(float(header), 60.0)
    except ValueError:
        pass
    return min(8.0 * (2 ** (attempt - 1)), 60.0)


class LangChainLLM:
    """Wraps a LangChain chat model with bounded retries on endpoint failures (PRD NFR5).

    Free-tier and shared endpoints answer HTTP 429 under load, and 502/503 when the upstream
    provider is overloaded. Each call retries at most `rate_limit_retries` times, sleeping per
    Retry-After or 8/16/32 s, then raises so the agent reports "unable to answer" instead of
    hanging. Other errors are not retried here; the agent's one-retry policy for malformed
    output covers those.
    """

    def __init__(self, model: BaseChatModel, rate_limit_retries: int = 3) -> None:
        self.model = model
        self.rate_limit_retries = rate_limit_retries

    def _with_rate_limit_retry(self, call):
        attempt = 0
        while True:
            try:
                return call()
            except Exception as exc:  # noqa: BLE001 - only rate limits are retried; others re-raise
                attempt += 1
                if not _is_rate_limit(exc) or attempt > self.rate_limit_retries:
                    raise
                # The only retry path that was invisible. It is also the earliest warning that a
                # provider is degrading, so it is worth a counter of its own.
                emit("model_rate_limited", attempt=attempt, error_type=type(exc).__name__)
                time.sleep(_retry_after_seconds(exc, attempt))

    def invoke_with_tools(self, messages: Sequence[BaseMessage], tools: Sequence[BaseTool],
                          require_tool: bool = False) -> AIMessage:
        # "any" forces a tool call on this round; LangChain maps it to each provider's spelling.
        bound = self.model.bind_tools(list(tools), tool_choice="any") if require_tool else self.model.bind_tools(list(tools))
        response = self._with_rate_limit_retry(lambda: bound.invoke(list(messages)))
        if not isinstance(response, AIMessage):  # pragma: no cover - LangChain always returns AIMessage here
            raise TypeError("unexpected model response type")
        return response

    def structured(self, messages: Sequence[BaseMessage], schema: type[T]) -> T:
        structured = self.model.with_structured_output(schema)
        result = self._with_rate_limit_retry(lambda: structured.invoke(list(messages)))
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)


class ScriptedLLM:
    """Replays a fixed sequence of responses. Each entry is an AIMessage (tool round) or a BaseModel (final)."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def invoke_with_tools(self, messages: Sequence[BaseMessage], tools: Sequence[BaseTool],
                          require_tool: bool = False) -> AIMessage:
        self.calls.append("tools-required" if require_tool else "tools")
        if not self.responses:
            return AIMessage(content="")
        nxt = self.responses.pop(0)
        if isinstance(nxt, AIMessage):
            return nxt
        # A structured object where a tool round was expected: signal "no more tools".
        self.responses.insert(0, nxt)
        return AIMessage(content="")

    def structured(self, messages: Sequence[BaseMessage], schema: type[T]) -> T:
        """Return the first scripted instance of `schema`, leaving everything else in place."""
        self.calls.append("structured")
        for position, nxt in enumerate(self.responses):
            if isinstance(nxt, schema):
                return self.responses.pop(position)
        raise RuntimeError(f"scripted LLM has no {schema.__name__} response")


def build_llm(settings: Settings, model_name: str | None = None, rate_limit_retries: int = 3) -> LLM:
    """Build the agent model, or another allowlisted model of the same provider (the eval judge)."""
    name = model_name or settings.model
    approved, reason = settings.provider_approved(name)
    if not approved:
        raise ProviderNotApproved(reason)

    if settings.provider == "openrouter":
        # OpenRouter is OpenAI-compatible. Tool calling and structured output are required;
        # check a model's supported_parameters on openrouter.ai before adding it to the allowlist.
        from langchain_openai import ChatOpenAI

        reasoning = settings.openrouter_reasoning.strip().lower()
        extra_body = None
        if reasoning == "off":
            extra_body = {"reasoning": {"enabled": False}}
        elif reasoning in ("low", "medium", "high"):
            extra_body = {"reasoning": {"effort": reasoning}}
        model = ChatOpenAI(
            model=name,
            temperature=0,
            max_tokens=settings.max_output_tokens,
            timeout=settings.model_timeout_s,
            max_retries=1,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers={"HTTP-Referer": "https://labs.gauntletai.com/debudash/openemragent",
                             "X-Title": "OpenEMR Clinical Co-Pilot"},
            extra_body=extra_body,
        )
        return LangChainLLM(model, rate_limit_retries)

    from langchain_anthropic import ChatAnthropic  # imported here so tests without the package can use ScriptedLLM

    model = ChatAnthropic(
        model=name,
        temperature=0,
        max_tokens=settings.max_output_tokens,
        timeout=settings.model_timeout_s,
        max_retries=1,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )
    return LangChainLLM(model, rate_limit_retries)
