"""ORACLE cost accounting and AI audit (PR-165, Parts 9 and 10).

One append-only JSONL ledger, ``oracle-usage.jsonl``, in the workspace
output directory. Every AI call writes exactly one record: capability,
provider, model, prompt VERSION, redaction policy applied, token
counts, estimated cost, latency, retries, and outcome.

What is never written: prompt text, response text, API keys, endpoints
with credentials, or any redacted value. The ledger answers "what did
Atlas ask a model to do, and what did it cost" — never "what was in
it". That is a deliberate boundary: an audit trail that quotes
prompts becomes a second copy of the evidence, with none of the
evidence store's protections.

Cost is an ESTIMATE and is labelled as one everywhere it appears:
providers price per model and change prices, so Atlas multiplies the
operator's configured rate by the provider's reported token counts and
never claims to be a billing system.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


USAGE_FILENAME = "oracle-usage.jsonl"
USAGE_SCHEMA_VERSION = "1.0.0"

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BACKUPS = 3
MAX_FIELD_CHARS = 200

OUTCOME_SUCCESS = "success"
OUTCOME_FAILED = "failed"
OUTCOME_BLOCKED = "blocked"     # policy or feature flag refused the call
OUTCOME_DISABLED = "disabled"   # AI is off

# Field names that may never appear in a usage record, whatever a
# caller passes. Enforced structurally, like the config store's guard.
FORBIDDEN_FIELDS = frozenset({
    "prompt", "prompt_text", "response", "response_text", "text",
    "api_key", "key", "secret", "password", "token", "messages",
    "content", "finding", "evidence",
})

_write_lock = threading.Lock()


@dataclass(frozen=True)
class UsageRecord:
    """One AI call, as audited."""

    at: str
    capability: str
    provider: str
    model: str
    prompt_version: str
    outcome: str
    redaction_rules: tuple[str, ...] = ()
    redactions: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    currency: str = "USD"
    latency_ms: int | None = None
    retries: int = 0
    evidence_version: str = ""     # the Atlas snapshot the answer rests on
    detail: str = ""               # failure reason, never response text

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": USAGE_SCHEMA_VERSION,
            "at": self.at,
            "capability": self.capability,
            "provider": self.provider,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "outcome": self.outcome,
            "redaction_rules": list(self.redaction_rules),
            "redactions": self.redactions,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "currency": self.currency,
            "latency_ms": self.latency_ms,
            "retries": self.retries,
            "evidence_version": self.evidence_version,
            "detail": self.detail[:MAX_FIELD_CHARS],
        }


def estimate_cost(
    input_tokens: int | None, output_tokens: int | None,
    *, input_per_million: float, output_per_million: float,
) -> float | None:
    """The estimated cost, or None when the provider reported no token
    counts or no rate is configured. None means "not known" — Atlas
    does not invent a number to fill a column."""

    if not input_per_million and not output_per_million:
        return None
    if input_tokens is None and output_tokens is None:
        return None
    total = 0.0
    if input_tokens is not None:
        total += (input_tokens / 1_000_000) * input_per_million
    if output_tokens is not None:
        total += (output_tokens / 1_000_000) * output_per_million
    return round(total, 6)


class UsageLedger:
    """Append-only, size-bounded AI usage and audit ledger."""

    def __init__(self, base_dir: str | Path) -> None:
        self.path = Path(base_dir) / USAGE_FILENAME

    # -- writing -----------------------------------------------------

    def _rotate_if_needed(self) -> None:
        try:
            if (not self.path.is_file()
                    or self.path.stat().st_size < MAX_FILE_BYTES):
                return
            oldest = self.path.with_name(f"{self.path.name}.{MAX_BACKUPS}")
            if oldest.exists():
                oldest.unlink()
            for index in range(MAX_BACKUPS - 1, 0, -1):
                source = self.path.with_name(f"{self.path.name}.{index}")
                if source.exists():
                    source.rename(
                        self.path.with_name(f"{self.path.name}.{index + 1}")
                    )
            self.path.rename(self.path.with_name(f"{self.path.name}.1"))
        except OSError:
            pass

    def record(self, entry: UsageRecord) -> None:
        """Append one record. Best-effort: an audit failure must never
        break the answer path, and a blocked write is not a reason to
        surface an error the operator cannot act on."""

        document = entry.to_dict()
        for name in list(document):
            if name.casefold() in FORBIDDEN_FIELDS:
                document.pop(name)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _write_lock:
                self._rotate_if_needed()
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(document, sort_keys=True) + "\n")
        except (OSError, TypeError, ValueError):
            pass

    # -- reading -----------------------------------------------------

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
        return records

    def summary(self) -> dict[str, Any]:
        """The usage dashboard's numbers (Part 9).

        Counts are exact. Cost is a sum of estimates and is labelled as
        such; ``cost_known_for`` says how many calls actually carried a
        cost estimate, so a small number next to a large call count is
        visibly an under-count rather than a cheap month.
        """

        records = self.entries()
        totals = {
            "requests": len(records),
            "successes": 0,
            "failures": 0,
            "blocked": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost": 0.0,
            "cost_known_for": 0,
            "currency": "USD",
            "average_latency_ms": None,
            "retries": 0,
            "by_capability": {},
            "by_model": {},
            "recent_failures": [],
        }
        latencies: list[int] = []
        for record in records:
            outcome = record.get("outcome")
            if outcome == OUTCOME_SUCCESS:
                totals["successes"] += 1
            elif outcome == OUTCOME_BLOCKED:
                totals["blocked"] += 1
            elif outcome in (OUTCOME_FAILED, OUTCOME_DISABLED):
                totals["failures"] += 1
            for field_name, key in (
                ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"),
            ):
                value = record.get(field_name)
                if isinstance(value, int):
                    totals[key] += value
            cost = record.get("estimated_cost")
            if isinstance(cost, (int, float)) and math.isfinite(cost):
                totals["estimated_cost"] += float(cost)
                totals["cost_known_for"] += 1
            if isinstance(record.get("currency"), str) and record["currency"]:
                totals["currency"] = record["currency"]
            latency = record.get("latency_ms")
            if isinstance(latency, int):
                latencies.append(latency)
            retries = record.get("retries")
            if isinstance(retries, int):
                totals["retries"] += retries
            for bucket, field_name in (
                ("by_capability", "capability"), ("by_model", "model"),
            ):
                name = str(record.get(field_name) or "unknown")
                totals[bucket][name] = totals[bucket].get(name, 0) + 1
            if outcome == OUTCOME_FAILED:
                totals["recent_failures"].append({
                    "at": record.get("at"),
                    "capability": record.get("capability"),
                    "detail": record.get("detail"),
                })
        totals["estimated_cost"] = round(totals["estimated_cost"], 6)
        totals["recent_failures"] = totals["recent_failures"][-5:]
        if latencies:
            totals["average_latency_ms"] = int(sum(latencies) / len(latencies))
        return totals
