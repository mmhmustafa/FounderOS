"""PRISM provider contract (PR-165, Part 2).

Every AI provider — cloud or customer-hosted — implements this one
contract. Consumers never see a provider class: they talk to
:class:`founderos_atlas.prism.service.PrismService`, which talks to
whichever provider the configuration names. Switching providers is a
configuration change, never a code change.

Design principle, enforced at this boundary: Atlas determines facts;
AI may only assist interpretation. A provider receives already-redacted
text and returns text — it can never touch evidence, topology, or
workflow routing, because nothing in this contract can express that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


@dataclass(frozen=True)
class AIMessage:
    """One chat message. ``role`` is system/user/assistant."""

    role: str
    content: str


@dataclass(frozen=True)
class AIRequest:
    """One completion request, provider-neutral."""

    messages: tuple[AIMessage, ...]
    model: str
    max_output_tokens: int = 1024
    temperature: float = 0.2


@dataclass(frozen=True)
class AIResult:
    """One completion result, provider-neutral. Token counts are the
    PROVIDER'S numbers when reported, None when the provider does not
    report them — never estimated silently."""

    text: str
    model: str
    provider: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    retries: int = 0


@dataclass(frozen=True)
class ProviderHealth:
    """One health probe outcome."""

    ok: bool
    detail: str
    latency_ms: int | None = None
    models: tuple[str, ...] = ()  # discovered models, when listable


class AIProviderError(RuntimeError):
    """A provider call failed. ``retryable`` marks transient failures
    (timeouts, 429s, 5xx) the service may retry within its budget."""

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderSettings:
    """Everything a provider needs, from configuration. One shape for
    every provider; fields a provider does not use are ignored.

    ``api_key`` is SECRET: it exists here so a provider can
    authenticate, and nowhere else — it is never audited, never
    logged, never rendered back to a page in full.
    """

    kind: str
    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    organization: str = ""
    region: str = ""
    api_version: str = ""          # Azure OpenAI
    timeout_seconds: int = 30
    verify_tls: bool = True
    retries: int = 1
    max_context_tokens: int = 8192


class AIProvider(Protocol):
    """The contract. ``kind`` identifies the provider implementation;
    ``complete`` performs one completion; ``health`` probes liveness
    and (when the provider supports it) lists available models."""

    kind: str

    def complete(self, request: AIRequest) -> AIResult:  # pragma: no cover
        ...

    def health(self) -> ProviderHealth:  # pragma: no cover
        ...


def messages_payload(request: AIRequest) -> list[dict[str, Any]]:
    """The request's messages as plain dicts (OpenAI wire shape)."""

    return [
        {"role": message.role, "content": message.content}
        for message in request.messages
    ]


def split_system(request: AIRequest) -> tuple[str, list[AIMessage]]:
    """(system text, remaining messages) — for providers whose wire
    format carries the system prompt separately (Anthropic, Gemini)."""

    system_parts: list[str] = []
    rest: list[AIMessage] = []
    for message in request.messages:
        if message.role == ROLE_SYSTEM:
            system_parts.append(message.content)
        else:
            rest.append(message)
    return "\n\n".join(system_parts), rest
