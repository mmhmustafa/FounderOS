# Dependency security and accepted risk

Reviewed: 2026-07-18. Inventory: `constraints.txt` and `sbom.cdx.json`.

## Paramiko PYSEC-2026-2858 / CVE-2026-44405

Paramiko through 4.0.0 permits the legacy `ssh-rsa` SHA-1 signature
algorithm. The upstream correction is commit `a448945`; Paramiko 5.0.0
contains that change. Atlas cannot yet adopt 5.0.0 because Netmiko 4.7.0—the
current and upstream development release—declares `paramiko>=3.5,<5`.

Affected Atlas paths are live discovery/credential tests (Netmiko), host-key
probing (Paramiko Transport), and the interactive console (Paramiko
SSHClient). Atlas passes `disabled_algorithms` for both `keys` and `pubkeys`
with `ssh-rsa` disabled on every path. Legacy endpoints that offer only
SHA-1 RSA therefore fail closed; RSA SHA-2, ECDSA, and Ed25519 remain usable.

The temporary exception is machine-readable in
`security/vulnerability-exceptions.json`, expires 2026-10-18, and is checked
by CI. The upgrade gate is a Netmiko release compatible with Paramiko 5;
once available, Atlas must upgrade, remove the exception, and retest all live
transport and console paths.

Authoritative review sources:

- [NVD CVE-2026-44405](https://nvd.nist.gov/vuln/detail/CVE-2026-44405)
- [Paramiko corrective commit](https://github.com/paramiko/paramiko/commit/a4489456b6f65281e172380cc4826cee5e851dbb)
- [Paramiko 5.0.0 release metadata](https://pypi.org/project/paramiko/)
- [Netmiko dependency declaration](https://raw.githubusercontent.com/ktbyers/netmiko/develop/pyproject.toml)

## Audit policy

`scripts/audit_dependencies.py` runs `pip-audit` directly against every exact
version in `constraints.txt`, deduplicates findings, and fails for every
vulnerability without a package/version/identifier-specific, unexpired
exception. This keeps the result independent of whichever packages happen to
be installed in a developer environment. Exceptions are never silent: they
require an owner, reason, expiry, compensating controls, and upgrade gate.
