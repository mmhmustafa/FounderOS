"""ORACLE provider implementations and the provider registry (Part 2).

Every provider speaks the one contract in :mod:`.contract`. They are
registered by kind, so a future provider ships as a new registration —
no existing code changes, exactly like the OIR's intent registry.

HTTP is stdlib ``urllib`` on purpose: ORACLE adds NO dependency to
Atlas, which matters because Atlas must run identically with AI
disabled — and a disabled feature has no business dragging in a
package. TLS verification is on by default and only a customer's own
explicit setting (for a self-signed local endpoint) turns it off.

Nothing here knows what a device, an intent, or a piece of evidence
is: providers receive already-redacted text and return text.
"""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .contract import (
    AIProviderError,
    AIRequest,
    AIResult,
    ProviderHealth,
    ProviderSettings,
    ROLE_ASSISTANT,
    messages_payload,
    split_system,
)


KIND_DISABLED = "disabled"
KIND_OPENAI = "openai"
KIND_AZURE_OPENAI = "azure-openai"
KIND_ANTHROPIC = "anthropic"
KIND_GEMINI = "gemini"
KIND_OPENROUTER = "openrouter"
KIND_OPENAI_COMPATIBLE = "openai-compatible"
KIND_OLLAMA = "ollama"
KIND_LM_STUDIO = "lm-studio"
KIND_VLLM = "vllm"

# Which kinds send data OFF the customer's network. Governance uses
# this to enforce "no cloud AI" policies (Part 11) — the classification
# lives with the provider, so a new provider declares its own nature.
# OpenRouter is cloud TWICE over: it is a hosted service, and it
# forwards the request to whichever upstream model the operator names.
CLOUD_KINDS = frozenset((
    KIND_OPENAI, KIND_AZURE_OPENAI, KIND_ANTHROPIC, KIND_GEMINI,
    KIND_OPENROUTER,
))
LOCAL_KINDS = frozenset((
    KIND_OPENAI_COMPATIBLE, KIND_OLLAMA, KIND_LM_STUDIO, KIND_VLLM,
))


# -- HTTP -------------------------------------------------------------------

def _context(settings: ProviderSettings) -> ssl.SSLContext | None:
    if settings.verify_tls:
        return None  # urllib's default: verified, hostname-checked
    unverified = ssl.create_default_context()
    unverified.check_hostname = False
    unverified.verify_mode = ssl.CERT_NONE
    return unverified


def _request_json(
    url: str,
    *,
    settings: ProviderSettings,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "POST",
) -> dict[str, Any]:
    """One JSON round trip. Transport and protocol failures become
    :class:`AIProviderError` with an honest retryable flag."""

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(
            request, timeout=settings.timeout_seconds,
            context=_context(settings),
        ) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise AIProviderError(
            f"provider returned HTTP {error.code}: {detail}",
            # 408/409/425/429 and 5xx are worth one more try; 4xx
            # configuration errors are not.
            retryable=error.code in (408, 409, 425, 429)
            or 500 <= error.code < 600,
        ) from error
    except urllib.error.URLError as error:
        raise AIProviderError(
            f"provider unreachable: {error.reason}", retryable=True
        ) from error
    except (TimeoutError, OSError) as error:
        raise AIProviderError(
            f"provider connection failed: {error}", retryable=True
        ) from error
    if not text.strip():
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise AIProviderError(
            "provider returned a response that is not JSON"
        ) from error
    if not isinstance(parsed, dict):
        raise AIProviderError(
            "provider returned an unexpected response shape"
        )
    return parsed


def _timed(call: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    payload = call()
    return payload, int((time.perf_counter() - started) * 1000)


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


# -- providers --------------------------------------------------------------

class DisabledProvider:
    """The default. AI is off; every call fails cleanly and callers
    fall back to Atlas's own deterministic output (Part 14)."""

    kind = KIND_DISABLED

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings

    def complete(self, request: AIRequest) -> AIResult:
        raise AIProviderError("AI is disabled for this workspace.")

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            ok=False, detail="AI is disabled — Atlas runs fully without it."
        )


class OpenAIChatProvider:
    """OpenAI and every OpenAI-compatible endpoint.

    One implementation covers OpenAI, generic compatible servers,
    Ollama, LM Studio and vLLM: they differ in base URL and whether a
    key is needed, not in wire format. Azure OpenAI subclasses it for
    its deployment-style URL and header.
    """

    kind = KIND_OPENAI
    default_endpoint = "https://api.openai.com/v1"

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings

    # -- URLs and headers (Azure overrides these) --------------------

    def _base(self) -> str:
        return (self.settings.endpoint or self.default_endpoint).rstrip("/")

    def _completions_url(self) -> str:
        return f"{self._base()}/chat/completions"

    def _models_url(self) -> str:
        return f"{self._base()}/models"

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        if self.settings.organization:
            headers["OpenAI-Organization"] = self.settings.organization
        return headers

    def _payload(self, request: AIRequest) -> dict[str, Any]:
        return {
            "model": request.model,
            "messages": messages_payload(request),
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }

    # -- contract ----------------------------------------------------

    def complete(self, request: AIRequest) -> AIResult:
        payload, latency = _timed(lambda: _request_json(
            self._completions_url(), settings=self.settings,
            payload=self._payload(request), headers=self._headers(),
        ))
        choices = payload.get("choices") or []
        if not choices:
            raise AIProviderError("provider returned no completion")
        message = (choices[0] or {}).get("message") or {}
        usage = payload.get("usage") or {}
        return AIResult(
            text=str(message.get("content") or "").strip(),
            model=str(payload.get("model") or request.model),
            provider=self.kind,
            input_tokens=_int_or_none(usage.get("prompt_tokens")),
            output_tokens=_int_or_none(usage.get("completion_tokens")),
            latency_ms=latency,
        )

    def health(self) -> ProviderHealth:
        try:
            payload, latency = _timed(lambda: _request_json(
                self._models_url(), settings=self.settings,
                headers=self._headers(), method="GET",
            ))
        except AIProviderError as error:
            return ProviderHealth(ok=False, detail=error.reason)
        models = tuple(
            str(item.get("id"))
            for item in (payload.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        )
        return ProviderHealth(
            ok=True,
            detail=f"reachable — {len(models)} model(s) listed"
            if models else "reachable",
            latency_ms=latency, models=models,
        )


class AzureOpenAIProvider(OpenAIChatProvider):
    """Azure OpenAI: deployment-style URLs, api-key header, api-version."""

    kind = KIND_AZURE_OPENAI
    default_endpoint = ""

    def _completions_url(self) -> str:
        version = self.settings.api_version or "2024-02-01"
        return (
            f"{self._base()}/openai/deployments/{self.settings.model}"
            f"/chat/completions?api-version={version}"
        )

    def _models_url(self) -> str:
        version = self.settings.api_version or "2024-02-01"
        return f"{self._base()}/openai/models?api-version={version}"

    def _headers(self) -> dict[str, str]:
        return {"api-key": self.settings.api_key} if self.settings.api_key \
            else {}


class OpenRouterProvider(OpenAIChatProvider):
    """OpenRouter — a hosted aggregator in front of many upstream
    models, speaking the OpenAI chat API.

    Model ids are namespaced by their upstream vendor, e.g.
    ``anthropic/claude-sonnet-4`` or ``meta-llama/llama-3.3-70b``.
    The attribution header identifies Atlas in the operator's own
    OpenRouter dashboard; it carries no evidence and no operator
    identity.
    """

    kind = KIND_OPENROUTER
    default_endpoint = "https://openrouter.ai/api/v1"

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        headers["X-Title"] = "FounderOS Atlas"
        return headers


class OpenAICompatibleProvider(OpenAIChatProvider):
    kind = KIND_OPENAI_COMPATIBLE
    default_endpoint = "http://localhost:8000/v1"


class OllamaProvider(OpenAIChatProvider):
    kind = KIND_OLLAMA
    default_endpoint = "http://localhost:11434/v1"


class LMStudioProvider(OpenAIChatProvider):
    kind = KIND_LM_STUDIO
    default_endpoint = "http://localhost:1234/v1"


class VLLMProvider(OpenAIChatProvider):
    kind = KIND_VLLM
    default_endpoint = "http://localhost:8000/v1"


class AnthropicProvider:
    """Anthropic Messages API."""

    kind = KIND_ANTHROPIC
    default_endpoint = "https://api.anthropic.com/v1"
    api_version = "2023-06-01"

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings

    def _base(self) -> str:
        return (self.settings.endpoint or self.default_endpoint).rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"anthropic-version": self.api_version}
        if self.settings.api_key:
            headers["x-api-key"] = self.settings.api_key
        return headers

    def complete(self, request: AIRequest) -> AIResult:
        system, rest = split_system(request)
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in rest
            ],
        }
        if system:
            payload["system"] = system
        body, latency = _timed(lambda: _request_json(
            f"{self._base()}/messages", settings=self.settings,
            payload=payload, headers=self._headers(),
        ))
        blocks = body.get("content") or []
        text = "".join(
            str(block.get("text") or "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            raise AIProviderError("provider returned no completion")
        usage = body.get("usage") or {}
        return AIResult(
            text=text,
            model=str(body.get("model") or request.model),
            provider=self.kind,
            input_tokens=_int_or_none(usage.get("input_tokens")),
            output_tokens=_int_or_none(usage.get("output_tokens")),
            latency_ms=latency,
        )

    def health(self) -> ProviderHealth:
        try:
            payload, latency = _timed(lambda: _request_json(
                f"{self._base()}/models", settings=self.settings,
                headers=self._headers(), method="GET",
            ))
        except AIProviderError as error:
            return ProviderHealth(ok=False, detail=error.reason)
        models = tuple(
            str(item.get("id"))
            for item in (payload.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        )
        return ProviderHealth(
            ok=True,
            detail=f"reachable — {len(models)} model(s) listed"
            if models else "reachable",
            latency_ms=latency, models=models,
        )


class GeminiProvider:
    """Google Gemini generateContent API."""

    kind = KIND_GEMINI
    default_endpoint = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings

    def _base(self) -> str:
        return (self.settings.endpoint or self.default_endpoint).rstrip("/")

    def _headers(self) -> dict[str, str]:
        # The key rides in a header, never in the URL: query strings
        # land in proxy and server logs.
        return {"x-goog-api-key": self.settings.api_key} \
            if self.settings.api_key else {}

    def complete(self, request: AIRequest) -> AIResult:
        system, rest = split_system(request)
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if message.role == ROLE_ASSISTANT
                    else "user",
                    "parts": [{"text": message.content}],
                }
                for message in rest
            ],
            "generationConfig": {
                "maxOutputTokens": request.max_output_tokens,
                "temperature": request.temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        body, latency = _timed(lambda: _request_json(
            f"{self._base()}/models/{request.model}:generateContent",
            settings=self.settings, payload=payload,
            headers=self._headers(),
        ))
        candidates = body.get("candidates") or []
        if not candidates:
            raise AIProviderError("provider returned no completion")
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
        text = "".join(
            str(part.get("text") or "")
            for part in parts if isinstance(part, dict)
        ).strip()
        if not text:
            raise AIProviderError("provider returned no completion")
        usage = body.get("usageMetadata") or {}
        return AIResult(
            text=text, model=request.model, provider=self.kind,
            input_tokens=_int_or_none(usage.get("promptTokenCount")),
            output_tokens=_int_or_none(usage.get("candidatesTokenCount")),
            latency_ms=latency,
        )

    def health(self) -> ProviderHealth:
        try:
            payload, latency = _timed(lambda: _request_json(
                f"{self._base()}/models", settings=self.settings,
                headers=self._headers(), method="GET",
            ))
        except AIProviderError as error:
            return ProviderHealth(ok=False, detail=error.reason)
        models = tuple(
            str(item.get("name") or "").split("/")[-1]
            for item in (payload.get("models") or [])
            if isinstance(item, dict) and item.get("name")
        )
        return ProviderHealth(
            ok=True,
            detail=f"reachable — {len(models)} model(s) listed"
            if models else "reachable",
            latency_ms=latency, models=models,
        )


# -- the registry -----------------------------------------------------------

@dataclass(frozen=True)
class ProviderDescriptor:
    """One registered provider kind: how to build it, how to label it,
    and whether using it sends data off the customer's network."""

    kind: str
    label: str
    factory: Callable[[ProviderSettings], Any]
    hosting: str                      # "cloud" | "local" | "none"
    needs_api_key: bool = False
    needs_endpoint: bool = False
    default_endpoint: str = ""
    notes: str = ""

    def build(self, settings: ProviderSettings):
        return self.factory(settings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "label": self.label,
            "hosting": self.hosting,
            "needs_api_key": self.needs_api_key,
            "needs_endpoint": self.needs_endpoint,
            "default_endpoint": self.default_endpoint,
            "notes": self.notes,
        }


class ProviderRegistry:
    """Registered provider kinds, in registration order."""

    def __init__(self) -> None:
        self._by_kind: dict[str, ProviderDescriptor] = {}

    def register(self, descriptor: ProviderDescriptor) -> ProviderDescriptor:
        if descriptor.kind in self._by_kind:
            raise ValueError(
                f"provider kind {descriptor.kind!r} is already registered"
            )
        self._by_kind[descriptor.kind] = descriptor
        return descriptor

    def get(self, kind: str) -> ProviderDescriptor | None:
        return self._by_kind.get(kind)

    def kinds(self) -> tuple[str, ...]:
        return tuple(self._by_kind)

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(self._by_kind.values())


def build_provider_registry() -> ProviderRegistry:
    """The built-in providers. A future provider registers here — or
    on a registry of its own — without touching any existing class."""

    registry = ProviderRegistry()
    registry.register(ProviderDescriptor(
        kind=KIND_DISABLED, label="AI disabled", factory=DisabledProvider,
        hosting="none",
        notes="Atlas runs fully without AI. This is the default.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_OPENAI, label="OpenAI", factory=OpenAIChatProvider,
        hosting="cloud", needs_api_key=True,
        default_endpoint=OpenAIChatProvider.default_endpoint,
        notes="Sends prompt text to OpenAI.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_AZURE_OPENAI, label="Azure OpenAI",
        factory=AzureOpenAIProvider, hosting="cloud",
        needs_api_key=True, needs_endpoint=True,
        notes="Endpoint is your Azure resource URL; model is the "
              "deployment name.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_ANTHROPIC, label="Anthropic", factory=AnthropicProvider,
        hosting="cloud", needs_api_key=True,
        default_endpoint=AnthropicProvider.default_endpoint,
        notes="Sends prompt text to Anthropic.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_GEMINI, label="Google Gemini", factory=GeminiProvider,
        hosting="cloud", needs_api_key=True,
        default_endpoint=GeminiProvider.default_endpoint,
        notes="Sends prompt text to Google.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_OPENROUTER, label="OpenRouter", factory=OpenRouterProvider,
        hosting="cloud", needs_api_key=True,
        default_endpoint=OpenRouterProvider.default_endpoint,
        notes="Hosted aggregator: your prompt goes to OpenRouter and on "
              "to the upstream vendor of the model you name "
              "(e.g. anthropic/claude-sonnet-4).",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_OPENAI_COMPATIBLE, label="OpenAI-compatible endpoint",
        factory=OpenAICompatibleProvider, hosting="local",
        needs_endpoint=True,
        default_endpoint=OpenAICompatibleProvider.default_endpoint,
        notes="Any server speaking the OpenAI chat API.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_OLLAMA, label="Ollama (self-hosted)",
        factory=OllamaProvider, hosting="local", needs_endpoint=True,
        default_endpoint=OllamaProvider.default_endpoint,
        notes="Customer-hosted. Nothing leaves your network.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_LM_STUDIO, label="LM Studio (self-hosted)",
        factory=LMStudioProvider, hosting="local", needs_endpoint=True,
        default_endpoint=LMStudioProvider.default_endpoint,
        notes="Customer-hosted. Nothing leaves your network.",
    ))
    registry.register(ProviderDescriptor(
        kind=KIND_VLLM, label="vLLM (self-hosted)",
        factory=VLLMProvider, hosting="local", needs_endpoint=True,
        default_endpoint=VLLMProvider.default_endpoint,
        notes="Customer-hosted. Nothing leaves your network.",
    ))
    return registry


DEFAULT_PROVIDER_REGISTRY = build_provider_registry()
