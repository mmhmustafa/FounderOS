"""ORACLE — Atlas's AI Integration Platform (PR-165).

ORACLE is NOT an AI assistant. It is the platform that lets optional AI
capabilities exist safely inside Atlas: provider abstraction, AI
settings, capability and prompt registries, privacy enforcement and
redaction, cost and token accounting, model management, diagnostics,
governance, auditing, and feature gating.

The architecture it enforces:

    Operator -> (optional AI) -> Operational Intent Router
             -> Atlas engines -> evidence
             -> (optional AI explanation) -> operator

Atlas always determines the facts. AI may only assist interpretation —
it may interpret, summarize, explain, translate, rephrase, generate
reports and suggest questions. It may never invent or modify evidence,
override an Atlas conclusion, create devices or topology, execute
changes, alter workflow routing, or hide uncertainty.

Atlas functions identically with AI disabled, which is the default.
Consumers depend on :class:`OracleService`, never on a provider.
"""

from .capabilities import (
    CAPABILITY_CONVERSATION,
    CAPABILITY_EXECUTIVE_SUMMARY,
    CAPABILITY_INCIDENT_SUMMARY,
    CAPABILITY_PLAIN_ENGLISH,
    CAPABILITY_QUESTION_REWRITE,
    CAPABILITY_REPORT,
    CAPABILITY_TRANSLATION,
    DEFAULT_CAPABILITY_REGISTRY,
    AICapability,
    CapabilityRegistry,
    build_default_capability_registry,
)
from .config import (
    DISABLED_CONFIG,
    MODE_CLOUD,
    MODE_DISABLED,
    MODE_LOCAL,
    ORACLE_FILENAME,
    ORACLE_SCHEMA_VERSION,
    OracleConfig,
    OracleConfigError,
    OracleConfigRepository,
    credential_ref_for,
    validate,
)
from .contract import (
    AIMessage,
    AIProvider,
    AIProviderError,
    AIRequest,
    AIResult,
    ProviderHealth,
    ProviderSettings,
)
from .prompts import (
    DEFAULT_PROMPT_REGISTRY,
    SAFETY_PREAMBLE,
    PromptError,
    PromptRegistry,
    PromptTemplate,
    build_default_prompt_registry,
)
from .providers import (
    CLOUD_KINDS,
    DEFAULT_PROVIDER_REGISTRY,
    KIND_ANTHROPIC,
    KIND_AZURE_OPENAI,
    KIND_DISABLED,
    KIND_GEMINI,
    KIND_LM_STUDIO,
    KIND_OLLAMA,
    KIND_OPENAI,
    KIND_OPENAI_COMPATIBLE,
    KIND_OPENROUTER,
    KIND_VLLM,
    LOCAL_KINDS,
    ProviderDescriptor,
    ProviderRegistry,
    build_provider_registry,
)
from .redaction import (
    OPTIONAL_RULES,
    OPTIONAL_RULE_LABELS,
    STRICT_POLICY,
    RedactionPolicy,
    RedactionReport,
    redact,
)
from .service import Enhancement, OracleService
from .usage import (
    USAGE_FILENAME,
    UsageLedger,
    UsageRecord,
    estimate_cost,
)

__all__ = [
    "AICapability",
    "AIMessage",
    "AIProvider",
    "AIProviderError",
    "AIRequest",
    "AIResult",
    "CAPABILITY_CONVERSATION",
    "CAPABILITY_EXECUTIVE_SUMMARY",
    "CAPABILITY_INCIDENT_SUMMARY",
    "CAPABILITY_PLAIN_ENGLISH",
    "CAPABILITY_QUESTION_REWRITE",
    "CAPABILITY_REPORT",
    "CAPABILITY_TRANSLATION",
    "CLOUD_KINDS",
    "CapabilityRegistry",
    "DEFAULT_CAPABILITY_REGISTRY",
    "DEFAULT_PROMPT_REGISTRY",
    "DEFAULT_PROVIDER_REGISTRY",
    "DISABLED_CONFIG",
    "Enhancement",
    "KIND_ANTHROPIC",
    "KIND_AZURE_OPENAI",
    "KIND_DISABLED",
    "KIND_GEMINI",
    "KIND_LM_STUDIO",
    "KIND_OLLAMA",
    "KIND_OPENAI",
    "KIND_OPENAI_COMPATIBLE",
    "KIND_OPENROUTER",
    "KIND_VLLM",
    "LOCAL_KINDS",
    "MODE_CLOUD",
    "MODE_DISABLED",
    "MODE_LOCAL",
    "OPTIONAL_RULES",
    "OPTIONAL_RULE_LABELS",
    "ORACLE_FILENAME",
    "ORACLE_SCHEMA_VERSION",
    "OracleConfig",
    "OracleConfigError",
    "OracleConfigRepository",
    "OracleService",
    "ProviderDescriptor",
    "ProviderHealth",
    "ProviderRegistry",
    "ProviderSettings",
    "PromptError",
    "PromptRegistry",
    "PromptTemplate",
    "RedactionPolicy",
    "RedactionReport",
    "SAFETY_PREAMBLE",
    "STRICT_POLICY",
    "USAGE_FILENAME",
    "UsageLedger",
    "UsageRecord",
    "build_default_capability_registry",
    "build_default_prompt_registry",
    "build_provider_registry",
    "credential_ref_for",
    "estimate_cost",
    "redact",
    "validate",
]
