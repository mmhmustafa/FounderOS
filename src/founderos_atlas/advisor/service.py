"""Advisor services: conversation persistence, reusable ask() entry point.

Conversations live in ``.atlas/advisor/conversations.json`` (local
workspace only, gitignored with the rest of the Atlas state, capped) so
the GUI can show Recent Conversations and re-open any stored response.
Only the question and the structured evidence-cited response are stored
— never a secret, never free-form generated text.
"""

from __future__ import annotations

import json
from pathlib import Path

from .engine import AdvisorContext, answer
from .models import AdvisorResponse


ADVISOR_SUBDIR = Path(".atlas") / "advisor"
CONVERSATIONS_FILENAME = "conversations.json"
CONVERSATION_LIMIT = 20


def advisor_dir(base_output_dir: str | Path) -> Path:
    return Path(base_output_dir) / ADVISOR_SUBDIR


class ConversationRepository:
    """JSON persistence for the most recent Advisor conversations."""

    def __init__(self, base_output_dir: str | Path) -> None:
        self._path = advisor_dir(base_output_dir) / CONVERSATIONS_FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def list_conversations(self) -> list[dict]:
        """Stored conversations, newest first."""

        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [entry for entry in data if isinstance(entry, dict)] if isinstance(
            data, list
        ) else []

    def save(self, response: AdvisorResponse) -> None:
        entries = self.list_conversations()
        entries.insert(
            0,
            {
                "asked_at": response.generated_at,
                "response": response.to_dict(),
            },
        )
        del entries[CONVERSATION_LIMIT:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                entries, indent=2, sort_keys=True, ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )


def ask(
    question: str,
    *,
    base_output_dir: str | Path,
    profiles,
    graph,
    snapshot: dict | None,
    search_index,
    generated_at: str,
    repository: ConversationRepository | None = None,
) -> AdvisorResponse:
    """Answer one question from evidence and (optionally) store it.

    The caller supplies the SAME cached enterprise graph and search
    index the GUI already uses — Advisor adds no second source of truth
    and re-derives nothing.
    """

    response = answer(
        question,
        AdvisorContext(
            base_output_dir=Path(base_output_dir),
            profiles=tuple(profiles),
            graph=graph,
            snapshot=snapshot,
            search_index=search_index,
            generated_at=generated_at,
        ),
    )
    if repository is not None:
        repository.save(response)
    return response
