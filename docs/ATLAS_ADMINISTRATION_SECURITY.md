# Atlas administration security contract

## Deployment boundary

Atlas now ships the production-security phase: authentication modes
(`local`/`password`/`proxy`), server-side RBAC on every route, CSRF
protection, server-side sessions, optimistic concurrency, enriched
audit, health probes, and structured logging — see
`ATLAS_PRODUCTION_DEPLOYMENT.md` for the deployment guide and threat
assumptions. Local mode remains the supported single-user development
mode: it binds to loopback and refuses non-loopback clients outright,
so it cannot be exposed by accident. Everything below still applies
unchanged.

## Secrets

- Passwords exist only in the configured `CredentialProvider` (OS keyring,
  AES-256-GCM encrypted file, or non-persistent test memory) and in short-lived
  connection variables.
- Profiles, credential-set files, discovery drafts, preferences, diagnostics,
  backups, templates, audit events, and URLs store references and metadata only.
- Discovery drafts structurally reject password, secret, token, private-key,
  and passphrase fields. Browser resumption therefore restores targeting and
  policy but always leaves password fields empty.
- “Test secure store” proves only that an opaque reference is readable. It does
  not claim that a device accepted the credential.
- Masked evidence/configuration export is the safe default for bulk workflows.
  Deliberate raw exports remain local-operator actions and are labelled as
  sensitive.

## Persistence and backup

Preferences and drafts use atomic replacement under the Atlas workspace.
Metadata backup includes allowlisted JSON/JSONL workspace records, but excludes
every credential store, sessions, raw network evidence, generated sensitive
artifacts, temporary files, and unknown future files. Restore accepts only an allowlist of root-level
Atlas metadata files, validates JSON, limits file size, and requires an explicit
confirmation phrase. Restore does not modify any credential provider.

## Audit

Profile lifecycle changes, credential-reference creation/deletion/testing,
configuration annotations, preference changes, diagnostics export, backup,
restore, and reset append secret-free events to the unified audit log. Audit
payload redaction is defense in depth; callers pass references, never values.

## Retention

`retention_days` is persisted policy metadata. Retention is manual: Atlas
rebuilds a preview immediately before execution, protects non-history records,
requires a typed destructive confirmation, audits the operation, and writes a
deletion manifest. No scheduled retention worker ships.

## External-provider limitations

The provider abstraction supports future Vault and cloud-secret adapters; this
repository ships the OS-keyring implementation, an AES-256-GCM encrypted-file
provider for headless servers, and an in-memory test provider. Network
authentication tests require an explicit target and are not inferred from
successful keyring reads. Credential permission separation is now enforced:
the `credentials.manage` permission (credential-admin and system-admin roles)
gates every credential page and mutation server-side.
