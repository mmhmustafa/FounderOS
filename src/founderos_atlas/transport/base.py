"""Vendor-neutral read-only device transport contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

from .exceptions import ReadOnlyViolationError


# The read-only grammar, by dialect. Every entry is a display/read verb
# that CANNOT change device state — audited per platform, never a
# wildcard. This is a deliberately small allowlist: a new platform earns
# entries here explicitly, in review, or its commands do not run.
_READ_ONLY_FIRST_WORDS = frozenset({
    "show",       # Cisco / Arista / Junos / FRR / FortiOS display verb
    "get",        # FortiOS read verb ("get system status") — display only
    "display",    # Comware/VRP display verb (future platforms)
    "list",       # tmsh read verb (F5 BIG-IP)
})

# Multi-word read-only prefixes for dialects whose read grammar starts
# with an otherwise-writeful verb. Exact prefixes, never single words:
# PAN-OS `set cli ...` adjusts the SESSION's presentation (pager, output
# format) and can never touch configuration — `set` alone stays banned.
_READ_ONLY_PREFIXES = (
    "set cli ",
    # AireOS spells its session pager-off "config paging disable" — the
    # one `config`-verb form allowed, as an exact presentation-only
    # prefix. `config` alone (and every other subtree) stays banned.
    "config paging ",
)


def ensure_read_only(command: str) -> str:
    """Return the normalized command or reject anything that is not read-only."""

    if not isinstance(command, str) or not command.strip():
        raise ReadOnlyViolationError("Command must be a non-empty string.")
    normalized = " ".join(command.strip().split())
    folded = normalized.casefold()
    first_word = folded.split(" ", 1)[0]
    if first_word not in _READ_ONLY_FIRST_WORDS and not any(
        folded.startswith(prefix) for prefix in _READ_ONLY_PREFIXES
    ):
        raise ReadOnlyViolationError(
            f"Command rejected by the read-only transport policy: {normalized!r}. "
            "Atlas transports only run read/display commands "
            "(show/get/display/list, or a session-presentation 'set cli')."
        )
    return normalized


@dataclass(frozen=True)
class DeviceCredentials:
    """Connection identity for one device; the password never appears in repr."""

    host: str
    username: str
    password: str = field(repr=False)
    port: int = 22

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("host is required")
        if not self.username.strip():
            raise ValueError("username is required")
        if not self.password:
            raise ValueError("password is required")
        if not isinstance(self.port, int) or not 0 < self.port < 65536:
            raise ValueError("port must be an integer between 1 and 65535")


class DeviceTransport(ABC):
    """Read-only command session with one reachable network device.

    Implementations must never enter configuration mode, never send write
    commands, and never mutate device state.
    """

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def execute(self, command: str) -> str:
        raise NotImplementedError

    def execute_many(self, commands: Iterable[str]) -> dict[str, str]:
        """Run read-only commands in order, keyed by the caller's command text."""

        return {command: self.execute(command) for command in commands}

    def __enter__(self) -> "DeviceTransport":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.disconnect()
        return False
