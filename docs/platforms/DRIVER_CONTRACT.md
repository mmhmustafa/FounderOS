# The Production Driver Contract (PR-049 POLYGLOT)

A platform driver is `ProductionDriver` (`platforms/production.py`), extending
the proven `PlatformDriver` base. It declares:

| Contract point | Where | Meaning |
|---|---|---|
| `platform_id` / `display_name` / `vendor` | class attrs | identity |
| `matches(probe)` | classmethod | probe-based detection (see registry.identify) |
| `netmiko_device_type` | class attr | the session personality; the transport takes it from the driver, never the reverse |
| `session_setup` | class attr | read-only preparation (pagination off, width); failures tolerated + recorded |
| `command_plan()` | method | `CommandSpec` per capability: ordered command fallbacks, required flag, tier, limitation note |
| `rejects(output)` / `denied(output)` | methods | the platform's own refusal / privilege grammar |
| `adapter` | property | parse-only normalization into canonical models |
| `annotate(discovery)` | method | platform evidence summarized into canonical metadata (vPC, MLAG, BGP peers…) |
| `maturity` | class attr | EXPERIMENTAL / BETA / PRODUCTION — earned, never asserted |

The base `discover()` owns execute-or-fallback:

- device rejects a command → try the next form; all rejected → **UNSUPPORTED**
- transport/exec breaks → **FAILED** (required identity aborts the device;
  anything else preserves every result already collected)
- privilege denied → FAILED with the reason
- empty output from an executed command → **SUPPORTED** ("nothing to report")
- tier-excluded → **NOT_ATTEMPTED**, by name

Diagnostics (detection, tier, per-capability reports, warnings) are stamped
into canonical device metadata (`driver_diagnostics`) where device pages and
the Evidence Explorer read. Raw outputs flow to Enterprise Memory through the
existing sink, unchanged. Drivers never construct topology edges.
