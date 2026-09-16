"""The model gateway (PRD PHI1, PHI4). One approved provider configuration; fail closed.

The agent talks to the model through the small `LLM` protocol below so the loop stays
legible and testable: `LangChainLLM` wraps ChatAnthropic (traced by LangSmith through
LangChain callbacks); `ScriptedLLM` replays canned responses for unit tests and evals
that must run without a key.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from .config import Settings

T = TypeVar("T", bound=BaseModel)


class ProviderNotApproved(RuntimeError):
    """Raised before any PHI leaves the service when the model configuration is not allowlisted."""


class LLM(Protocol):
    def invoke_with_tools(self, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]) -> AIMessage: ...
    def structured(self, messages: Sequence[BaseMessage], schema: type[T]) -> T: ...


class LangChainLLM:
    def __init__(self, model: BaseChatModel) -> None:
        self.model = model

    def invoke_with_tools(self, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]) -> AIMessage:
        bound = self.model.bind_tools(list(tools))
        response = bound.invoke(list(messages))
        if not isinstance(response, AIMessage):  # pragma: no cover - LangChain always returns AIMessage here
            raise TypeError("unexpected model response type")
        return response

    def structured(self, messages: Sequence[BaseMessage], schema: type[T]) -> T:
        structured = self.model.with_structured_output(schema)
        result = structured.invoke(list(messages))
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)


class ScriptedLLM:
    """Replays a fixed sequence of responses. Each entry is an AIMessage (tool round) or a BaseModel (final)."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def invoke_with_tools(self, messages: Sequence[BaseMessage], tools: Sequence[BaseTool]) -> AIMessage:
        self.calls.append("tools")
        if not self.responses:
            return AIMessage(content="")
        nxt = self.responses.pop(0)
        if isinstance(nxt, AIMessage):
            return nxt
        # A structured object where a tool round was expected: signal "no more tools".
        self.responses.insert(0, nxt)
        return AIMessage(content="")

    def structured(self, messages: Sequence[BaseMessage], schema: type[T]) -> T:
        self.calls.append("structured")
        while self.responses:
            nxt = self.responses.pop(0)
            if isinstance(nxt, schema):
                return nxt
        raise RuntimeError("scripted LLM has no structured response left")


def build_llm(settings: Settings) -> LLM:
    approved, reason = settings.provider_approved()
    if not approved:
        raise ProviderNotApproved(reason)

    if settings.provider == "openrouter":
        # OpenRouter is OpenAI-compatible. Tool calling and structured output work for the
        # Claude slugs (anthropic/claude-sonnet-5 and others list both capabilities).
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=settings.model,
            temperature=0,
            max_tokens=settings.max_output_tokens,
            timeout=settings.model_timeout_s,
            max_retries=1,
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers={"HTTP-Referer": "https://labs.gauntletai.com/debudash/openemragent",
                             "X-Title": "OpenEMR Clinical Co-Pilot"},
        )
        return LangChainLLM(model)

    from langchain_anthropic import ChatAnthropic  # imported here so tests without the package can use ScriptedLLM

    model = ChatAnthropic(
        model=settings.model,
        temperature=0,
        max_tokens=settings.max_output_tokens,
        timeout=settings.model_timeout_s,
        max_retries=1,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )
    return LangChainLLM(model)
