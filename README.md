# FounderOS Atlas

FounderOS Atlas is a vendor-neutral network discovery, evidence, topology,
policy, investigation, prediction, and change-governance application. The
authoritative application version is defined in
`src/founderos_atlas/release.py`; package metadata, CLI, Settings,
diagnostics, backups, reports, and startup logs reuse it.

Current release: **0.3.0a1**. Workspace schema: **v1**.

## Supported runtime

- Python 3.11, 3.12, 3.13, or 3.14.
- One Atlas process per workspace. In-process discovery threads are
  supported; multiple WSGI workers sharing a workspace are refused by an
  operating-system instance lock.
- Windows and POSIX filesystems supported by the test suite and locking
  implementation.

## Install

Create an isolated environment and install the complete application against
the reviewed lock:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip==26.1.2"
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev,ssh,credentials,web]"
```

POSIX:

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade "pip==26.1.2"
.venv/bin/python -m pip install -c constraints.txt -e '.[dev,ssh,credentials,web]'
```

## Start Atlas

Local development mode is loopback-only and grants the local process an
operator identity:

```powershell
.\.venv\Scripts\founderos.exe atlas web
```

Password mode uses the workspace user store and server-side opaque sessions:

```powershell
$env:ATLAS_AUTH_MODE = "password"
$env:ATLAS_BOOTSTRAP_ADMIN_USER = "admin"
$env:ATLAS_BOOTSTRAP_ADMIN_PASSWORD = "replace-with-a-long-random-password"
.\.venv\Scripts\founderos.exe atlas web
```

Remove the bootstrap variables after the first administrator is created.
For production, use exactly one WSGI worker per workspace and terminate TLS
at a trusted reverse proxy. Set `ATLAS_TLS=1` when the browser-facing endpoint
is HTTPS so Atlas emits HSTS and Secure cookies. Proxy SSO mode additionally
requires `ATLAS_AUTH_MODE=proxy`, `ATLAS_PROXY_SECRET`, and an explicit
`ATLAS_TRUSTED_PROXY_ADDRS` list. Exact configuration and startup examples
are in [Atlas production deployment](docs/ATLAS_PRODUCTION_DEPLOYMENT.md).

## Credential providers

`ATLAS_CREDENTIAL_PROVIDER` selects `keyring` (default), `encrypted-file`,
or `memory` (tests/development only). The encrypted-file provider requires a
32-byte base64 key supplied through `ATLAS_CREDENTIAL_KEY_FILE` or
`ATLAS_CREDENTIAL_KEY`. No plaintext provider exists and secrets are never
included in metadata backups.

## Safety and recovery

- All mutations are authenticated/authorized, CSRF protected, audited, and
  conflict checked in password/proxy modes.
- The final enabled administrator cannot be disabled, demoted, or deleted.
  Emergency recovery uses the documented `ATLAS_RECOVERY_ADMIN_*` variables.
- Metadata backups exclude credential stores, sessions, raw evidence,
  temporary files, and generated sensitive configuration artifacts. See the
  exact allowlist in `workspace/backup.py` and the production guide.
- Atlas does not silently install updates, push network configuration, or
  claim visibility into an external proxy's listener/TLS state.

## Quality and supply chain

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\audit_dependencies.py
.\.venv\Scripts\python.exe scripts\generate_sbom.py
```

`constraints.txt` is the reproducible dependency lock and `sbom.cdx.json` is
the generated CycloneDX inventory. CI rejects new unapproved vulnerabilities
and expired exceptions. The current Paramiko exception and compensating SSH
algorithm control are documented in
`security/vulnerability-exceptions.json` and
[dependency risk](docs/DEPENDENCY_SECURITY.md).

## Documentation

- [Production deployment](docs/ATLAS_PRODUCTION_DEPLOYMENT.md)
- [Administration security](docs/ATLAS_ADMINISTRATION_SECURITY.md)
- [Release report](docs/ATLAS_RELEASE_REPORT.md)
- [Platform capability matrix](docs/platforms/CAPABILITY_MATRIX.md)
- [Web architecture](src/founderos_atlas/web/README.md)

Earlier milestone and alpha descriptions remain under `docs/historical/`,
`docs/handoffs/`, and `docs/reviews/` as historical records, not current
deployment guidance.

## License

The repository's `LICENSE` file is intentionally unresolved. Product
ownership and distribution terms require an owner/legal decision; no license
has been invented by engineering. Until that decision is recorded, do not
assume permission to redistribute the product.
