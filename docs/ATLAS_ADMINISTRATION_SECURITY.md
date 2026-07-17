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

- Passwords exist only in the configured `CredentialProvider` (normally the
  operating-system keyring) and in short-lived connection variables.
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
Metadata backup includes JSON/JSONL workspace records, but excludes OS-keyring
secrets and raw network evidence. Restore accepts only an allowlist of root-level
Atlas metadata files, validates JSON, limits file size, and requires an explicit
confirmation phrase. Restore does not modify the OS keyring.

## Audit

Profile lifecycle changes, credential-reference creation/deletion/testing,
configuration annotations, preference changes, diagnostics export, backup,
restore, and reset append secret-free events to the unified audit log. Audit
payload redaction is defense in depth; callers pass references, never values.

## Retention

`retention_days` is persisted policy metadata. Prompt 5 deliberately does not
silently delete evidence: an eventual retention worker must first provide an
audited preview, protect active baselines and investigations, and require an
explicit destructive confirmation.

## External-provider limitations

The provider abstraction supports future Vault and cloud-secret adapters; this
repository ships the OS-keyring implementation, an AES-256-GCM encrypted-file
provider for headless servers, and an in-memory test provider. Network
authentication tests require an explicit target and are not inferred from
successful keyring reads. Credential permission separation is now enforced:
the `credentials.manage` permission (credential-admin and system-admin roles)
gates every credential page and mutation server-side.
