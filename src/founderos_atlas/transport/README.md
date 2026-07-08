# Atlas Transport Layer

Read-only device transports for Atlas live discovery.

## What this layer is

The transport layer opens a session with one reachable network device,
runs read-only `show` commands, and returns the raw text output unchanged.
That output feeds the existing `DiscoveryEngine` exactly as fixture files
do today — parsers, reconciliation, snapshots, and journeys are untouched.

```
DeviceTransport (base.py)         vendor-neutral contract
└── SSHDeviceTransport (ssh.py)   Netmiko-backed Cisco IOS/IOS-XE session
```

The transport is deliberately unaware of simulators. Cisco Modeling Labs,
EVE-NG, GNS3, and physical hardware are all just reachable SSH endpoints.
No simulator APIs are called and no simulator-specific logic exists here.

## Contract

```python
class DeviceTransport:
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def execute(self, command: str) -> str: ...
    def execute_many(self, commands: Iterable[str]) -> dict[str, str]: ...
```

Transports are context managers: `with transport:` guarantees `disconnect()`
runs even when a command fails.

## Read-only guarantees

- Every command passes `ensure_read_only()` before reaching the wire; only
  commands whose first word is `show` are allowed.
- The SSH transport never calls `enable()`, never opens configuration mode,
  and never sends configuration, `write`, `copy`, or `reload` commands.
- A rejected command raises `ReadOnlyViolationError` locally — nothing is
  sent to the device.

## Security

- Passwords live only in `DeviceCredentials`; the field is excluded from
  `repr()` and never appears in log output, exception messages, or CLI text.
- No credentials are persisted anywhere.
- No Netmiko session log is enabled.

## Failure model

All failures raise a typed subclass of `AtlasTransportError` with a clean,
user-facing message:

| Exception | Meaning |
| --- | --- |
| `AuthenticationError` | Device rejected the credentials |
| `ConnectionTimeoutError` | Device unreachable or too slow |
| `SSHUnavailableError` | SSH refused / no network path |
| `UnsupportedPlatformError` | Not a Cisco IOS/IOS-XE device |
| `PermissionDeniedError` | Account lacks privilege for a command |
| `ConnectionLostError` | Session dropped mid-collection |
| `ReadOnlyViolationError` | Non-`show` command rejected locally |
| `TransportDependencyError` | Netmiko is not installed |

Netmiko errors are classified by exception class name rather than imported
types, so the package imports (and its tests run) without Netmiko installed.

## Dependencies

Netmiko is optional and imported lazily on first `connect()`:

```
pip install founderos-runtime[ssh]
```

## Usage

```python
from founderos_atlas.live import run_live_discovery
from founderos_atlas.transport import DeviceCredentials, SSHDeviceTransport

credentials = DeviceCredentials(host="10.0.0.1", username="atlas", password="...")
result, graph, snapshot = run_live_discovery(SSHDeviceTransport(credentials))
```

Or from the CLI:

```
founderos atlas discover
```
