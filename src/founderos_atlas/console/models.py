"""Console target and session models (PR-044A, CONSOLE).

Nothing in this module ever holds a secret. A console target carries a
*credential reference* — the name of a secret in Atlas's credential store —
and the session layer resolves that reference to a password server-side, at
connect time, and never returns it to a caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# -- device action states (spec: DEVICE ACTION STATES) ------------------------

ACTION_AVAILABLE = "available"
ACTION_CONNECTING = "connecting"
ACTION_CONNECTED = "connected"
ACTION_AUTH_FAILED = "authentication-failed"
ACTION_HOST_KEY_CHANGED = "host-key-changed"
ACTION_ENDPOINT_UNKNOWN = "management-endpoint-unknown"
ACTION_CREDENTIAL_REQUIRED = "credential-required"
ACTION_UNSUPPORTED_TRANSPORT = "unsupported-transport"
ACTION_SESSION_ENDED = "session-ended"

# Operator-facing explanations. The GUI never invents its own wording for a
# state, and never shows a stack trace.
ACTION_EXPLANATIONS = {
    ACTION_AVAILABLE: "Atlas has a verified management endpoint for this device.",
    ACTION_CONNECTING: "Opening an SSH session…",
    ACTION_CONNECTED: "Connected.",
    ACTION_AUTH_FAILED: (
        "Authentication failed. The credential Atlas holds for this device was "
        "not accepted."
    ),
    ACTION_HOST_KEY_CHANGED: (
        "The SSH host key changed. Atlas blocked the connection until the "
        "fingerprint is reviewed."
    ),
    ACTION_ENDPOINT_UNKNOWN: (
        "Atlas has observed this device but has not verified a management "
        "endpoint."
    ),
    ACTION_CREDENTIAL_REQUIRED: (
        "Atlas has no credential for this device. Choose a credential set to "
        "connect."
    ),
    ACTION_UNSUPPORTED_TRANSPORT: (
        "This device is not reachable over SSH from Atlas."
    ),
    ACTION_SESSION_ENDED: "The session ended.",
}


# -- why an endpoint is (not) eligible ---------------------------------------

#: The only evidence that makes an address eligible for a console session.
#: Atlas authenticated to this address during discovery and collected
#: evidence from it — the endpoint is verified by demonstration, not by
#: inference.
ENDPOINT_VERIFIED_BY_DISCOVERY = "authenticated-during-discovery"

#: Evidence kinds that must NEVER be used as a management endpoint. Each
#: proves a protocol relationship, not SSH manageability (the rule
#: ``discovery.multihop.management_candidate`` already applies to recursive
#: discovery; the console holds to it too, and more strictly).
INELIGIBLE_EVIDENCE = (
    "ospf-router-id",
    "bgp-peer",
    "route-next-hop",
    "loopback",
    "unresolved-peer",
    "protocol-observation",
    "interface-address",
)


@dataclass(frozen=True)
class ConsoleTarget:
    """A canonical device resolved for interactive SSH.

    ``eligible`` is the single authority the GUI consults. When it is False,
    ``state`` and ``reason`` say why in operator language and the SSH action
    is not offered at all.
    """

    device_id: str
    hostname: str
    network: str
    scope_id: str
    platform: str | None = None
    vendor: str | None = None
    management_ip: str | None = None
    port: int = 22
    username: str | None = None
    credential_ref: str | None = None      # reference only — never a secret
    credential_name: str | None = None
    eligible: bool = False
    state: str = ACTION_ENDPOINT_UNKNOWN
    reason: str = ACTION_EXPLANATIONS[ACTION_ENDPOINT_UNKNOWN]
    endpoint_evidence: str | None = None

    @property
    def ssh_command(self) -> str | None:
        """The command an engineer can paste into their own terminal.

        Never contains a password — Atlas has no way to put one in an SSH
        command safely, and would not if it could.
        """

        if not self.eligible or not self.management_ip:
            return None
        user = self.username or "<user>"
        if self.port and self.port != 22:
            return f"ssh -p {self.port} {user}@{self.management_ip}"
        return f"ssh {user}@{self.management_ip}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "network": self.network,
            "scope_id": self.scope_id,
            "platform": self.platform,
            "vendor": self.vendor,
            "management_ip": self.management_ip,
            "port": self.port,
            "username": self.username,
            # The reference is safe to render; the secret it names is not.
            "credential_ref": self.credential_ref,
            "credential_name": self.credential_name,
            "eligible": self.eligible,
            "state": self.state,
            "reason": self.reason,
            "endpoint_evidence": self.endpoint_evidence,
            "ssh_command": self.ssh_command,
        }


# -- host key states ---------------------------------------------------------

HOST_KEY_NEW = "new"
HOST_KEY_KNOWN = "known"
HOST_KEY_CHANGED = "changed"


@dataclass(frozen=True)
class HostKeyVerdict:
    """The result of checking a device's SSH host key."""

    status: str                      # new | known | changed
    host: str
    key_type: str
    fingerprint: str                 # SHA256:… of the key just presented
    known_fingerprint: str | None = None   # what Atlas trusted before
    known_key_type: str | None = None
    first_seen: str | None = None

    @property
    def blocked(self) -> bool:
        """A changed key blocks the connection. Never silently accepted."""

        return self.status == HOST_KEY_CHANGED

    @property
    def needs_acceptance(self) -> bool:
        return self.status == HOST_KEY_NEW

    @property
    def message(self) -> str:
        if self.status == HOST_KEY_CHANGED:
            return (
                f"SSH host key changed for {self.host}. This may indicate that "
                "the device was rebuilt, replaced, or intercepted. Review the "
                "fingerprint before continuing."
            )
        if self.status == HOST_KEY_NEW:
            return (
                f"Atlas has not seen {self.host}'s SSH host key before. Review "
                "the fingerprint and accept it to continue."
            )
        return f"Host key verified for {self.host}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "host": self.host,
            "key_type": self.key_type,
            "fingerprint": self.fingerprint,
            "known_fingerprint": self.known_fingerprint,
            "known_key_type": self.known_key_type,
            "first_seen": self.first_seen,
            "blocked": self.blocked,
            "needs_acceptance": self.needs_acceptance,
            "message": self.message,
        }


# -- sessions ----------------------------------------------------------------

SESSION_CONNECTING = "connecting"
SESSION_CONNECTED = "connected"
SESSION_CLOSED = "closed"
SESSION_FAILED = "failed"


@dataclass(frozen=True)
class ConsoleSessionInfo:
    """What Atlas records about a session — never its content.

    Commands typed and output returned are deliberately absent: the spec
    records *that* a session happened, not what was said in it. Optional
    audited recording is future work and would be an explicit setting.
    """

    session_id: str
    device_id: str
    hostname: str
    management_ip: str
    port: int
    username: str
    credential_ref: str            # reference only
    operator: str
    state: str
    opened_at: str
    closed_at: str | None = None
    result: str | None = None
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "hostname": self.hostname,
            "management_ip": self.management_ip,
            "port": self.port,
            "username": self.username,
            "credential_ref": self.credential_ref,
            "operator": self.operator,
            "state": self.state,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "result": self.result,
            "detail": self.detail,
            "metadata": dict(self.metadata),
        }
