# Atlas Workspace & Saved Discovery Profiles

A persistent workspace so a discovery target and its settings can be saved
once and reused — the backend foundation for the Atlas GUI (PR-031).

## What a profile stores

```
Profile name:          Hyderabad Lab
Site:                  CML Lab
Management IP:         192.168.1.12
Username:              atlas
Credential reference:  atlas-profile:hyderabad-lab   (password NOT stored here)
Max depth:             1
Max devices:           10
Collect configuration: yes
Created / Updated / Last discovery timestamps
```

The `DiscoveryProfile` model has **no password field** by design — a
profile can never serialize a secret. The password lives only in a secure
credential store, referenced by `credential_ref`.

## Storage layout

```
~/.atlas/workspace/profiles.json     # profile metadata + credential refs only
```

The workspace root is `~/.atlas` (override with the `ATLAS_HOME` environment
variable). It is outside the repository and never committed. Generated
runtime artifacts (snapshots, reports, history) are unaffected and continue
to live where discovery writes them.

## Secure credentials

Passwords are never written to JSON, YAML, logs, reports, history,
snapshots, dashboards, or command output. The `CredentialProvider`
abstraction stores them in a secure backend:

- `KeyringCredentialProvider` — OS-native storage via the `keyring` library
  (optional extra: `pip install founderos-runtime[credentials]`). This is
  the default.
- `InMemoryCredentialProvider` — process-local, for tests and sessions;
  never touches disk.

There is deliberately **no plaintext file provider**. If no secure store is
available, credential operations raise `CredentialStoreUnavailableError`
rather than writing a secret in the clear. The abstraction is extensible for
future enterprise backends (HashiCorp Vault, AWS Secrets Manager, Azure Key
Vault) with no change to the profile model or service.

## Service layer (reused by the GUI)

`ProfileService` holds all profile and credential business logic:

```python
service.add_profile(name=..., management_ip=..., username=..., password=..., ...)
service.list_profiles()
service.get_profile(name)
service.update_profile(name, ...)
service.delete_profile(name)
service.resolve_discovery_inputs(name)   # -> host, username, password, settings
service.record_discovery(name, when)     # updates last-discovery timestamp
```

The CLI (`founderos atlas profile ...` and `founderos atlas discover
--profile ...`) is a thin adapter over these methods. PR-031's local web GUI
calls the same service — list, add, edit, delete, run discovery, show status
— without invoking CLI commands or duplicating logic.

## CLI

```
founderos atlas profile add
founderos atlas profile list
founderos atlas profile show "Hyderabad Lab"
founderos atlas profile update "Hyderabad Lab"
founderos atlas profile delete "Hyderabad Lab"
founderos atlas discover --profile "Hyderabad Lab"
```

Password input is masked; passwords are never displayed. The interactive
`founderos atlas discover` (no profile) continues to work unchanged.

## Discovery scopes (PR-031A)

`scopes.py` defines the isolation boundary that fixes multi-profile
discovery: a `DiscoveryScope` names one isolated workspace — output
directory plus history root. Each profile's scope lives at
`<base>/.atlas/profiles/<profile_id>/` (history in `history/` inside it);
the *default scope* is the classic unscoped layout used by profile-less
discovery. The scope key is the stable `profile_id`, never the display
name, so renaming a profile (`ProfileService.update_profile(new_name=...)`)
keeps its history, credential, and baselines. New profile ids are unique
even when different names slug to the same value ("Lab A" / "Lab-A").

Legacy data recorded before scoping stays in the default scope and is never
reassigned to a profile: Atlas cannot know which network produced it.

`active_scopes()` implements the legacy-data policy for aggregated (All
Networks) views: profile scopes with discovery data are authoritative; the
default scope participates only while no profile scope holds data. Legacy
data is never deleted and stays selectable directly.
