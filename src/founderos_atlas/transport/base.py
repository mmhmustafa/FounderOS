"""Vendor-neutral read-only device transport contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field

from .exceptions import ReadOnlyViolationError


_READ_ONLY_FIRST_WORDS = frozenset({"show"})


def ensure_read_only(command: str) -> str:
    """Return the normalized command or reject anything that is not read-only."""

    if not isinstance(command, str) or not command.strip():
        raise ReadOnlyViolationError("Command must be a non-empty string.")
    normalized = " ".join(command.strip().split())
    first_word = normalized.split(" ", 1)[0].casefold()
    if first_word not in _READ_ONLY_FIRST_WORDS:
        raise ReadOnlyViolationError(
            f"Command rejected by the read-only transport policy: {normalized!r}. "
            "Atlas transports only run 'show' commands."
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
