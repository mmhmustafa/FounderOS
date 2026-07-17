# Atlas production deployment and security guide

This document covers threat assumptions, deployment configuration,
operational recovery, and the integration seams deliberately left
behind adapters. The administration-security contract in
`ATLAS_ADMINISTRATION_SECURITY.md` still applies; this document extends
it to multi-user operation.

## Authentication modes

`ATLAS_AUTH_MODE` selects the mode at startup:

| Mode | Who it is for | Identity source |
| --- | --- | --- |
| `local` (default) | Single developer on their own machine | Automatic `local-operator` principal, **loopback clients only** |
| `password` | Small teams, direct deployment | Workspace user store (`users.json`, scrypt hashes) + server-side sessions |
| `proxy` | Enterprises with SSO | SSO-terminating reverse proxy asserts the login in `X-Atlas-Remote-User` and proves itself with `X-Atlas-Proxy-Secret` |

Local mode **cannot** be exposed by accident: any request from a
non-loopback address is refused with 403 before any view runs, and the
CLI refuses to bind beyond 127.0.0.1. To serve other clients you must
consciously choose a production mode.

### Sessions (password mode)

- The browser holds an opaque 256-bit token (`atlas_session`,
  HttpOnly, SameSite=Lax, Secure under TLS). The store holds only its
  SHA-256, so the session file yields no usable tokens.
- Login always mints a fresh token (session fixation cannot survive
  authentication). Logout, account disable, and account delete revoke
  server-side immediately.
- Absolute lifetime `ATLAS_SESSION_MAX_AGE` (default 12 h) and idle
  timeout `ATLAS_SESSION_IDLE_TIMEOUT` (default 2 h).

### Bootstrap

With an empty user store, set `ATLAS_BOOTSTRAP_ADMIN_USER` and
`ATLAS_BOOTSTRAP_ADMIN_PASSWORD` for the first start. The password is
hashed immediately and never stored in clear; remove both variables
after the first start. Further accounts are managed on `/users`
(system administrators only, fully audited).

## Authorization (RBAC)

Roles: `viewer`, `investigator`, `network-operator`, `policy-manager`,
`credential-admin`, `system-admin`, `approver`. Grants live in
`founderos_atlas/access/models.py`; the endpoint → permission table in
`founderos_atlas/web/authz_map.py` is enforced in `before_request` for
every route. **An endpoint absent from the table is denied**, and a
test (`test_production_security.AuthorizationTableTests`) fails the
build if a route ships unmapped. Hiding a button is never the control;
every check happens server-side, and every denial is audited with
actor, roles, endpoint, outcome, and correlation id.

## CSRF

- All modes: mutating requests with a cross-origin `Origin` /
  `Sec-Fetch-Site` are refused.
- Password mode additionally requires the session's CSRF token on every
  mutation (`_csrf` form field or `X-Atlas-CSRF` header; the token is
  compared against the server-side session, not merely double-submitted).
  Templates inject it via `csrf_field()`; `atlas.js` wraps `fetch` so
  every same-origin mutating call carries the header automatically.
- Proxy mode relies on the origin check plus the proxy's own
  authentication; the proxy secret is compared in constant time.

## Transport, headers, limits

- TLS terminates at a reverse proxy (recommended) or via WSGI server
  configuration; set `ATLAS_TLS=1` so cookies are `Secure` and HSTS is
  emitted. Atlas never serves credentials in URLs.
- Every response: CSP (`default-src 'self'`, nonce'd scripts,
  `frame-ancestors 'none'`, `form-action 'self'`),
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, `Cache-Control: no-store` on
  authenticated pages, and an `X-Request-ID` correlation id.
- Rate limits (per source address, fixed one-minute windows): login
  5/min **per account**, credential/profile tests 20/min, restore
  5/min, advisor 30/min. Denials return 429 and are audited.
- Error pages never include stack traces, paths, or internals — only a
  safe message and the correlation id that finds the full server-side
  log line.

## Secrets

- Device credentials live only in the configured `CredentialProvider`:
  - `keyring` (default): the OS keyring.
  - `encrypted-file`: AES-256-GCM sealed `credentials.enc.json` for
    headless servers. The key never touches the workspace: supply it
    via `ATLAS_CREDENTIAL_KEY` (base64, 32 bytes) or better
    `ATLAS_CREDENTIAL_KEY_FILE` (a mounted secret). Each secret is
    bound to its credential reference as AEAD associated data.
  - `memory`: tests only.
  Select with `ATLAS_CREDENTIAL_PROVIDER`. There is deliberately no
  plaintext-file provider. Vault/KMS integrations implement the same
  `CredentialProvider` interface — that seam is the adapter boundary.
- User passwords: scrypt (n=2¹⁴, r=8, p=1) with per-user random salts.
- Audit events, logs, exports, backups, and notifications carry
  references and metadata only; `redact_payload` drops forbidden keys
  as defence in depth, and the leakage tests assert no plaintext secret
  ever appears in HTML, workspace files, backups, or exports.
- `ATLAS_SECRET_KEY` (optional) signs Flask flashes only; sessions do
  not depend on it. Never commit it — no secret belongs in source
  control.

## Threat assumptions

- The server host and workspace directory are trusted; OS file
  permissions protect the workspace (Atlas adds no file encryption for
  metadata — evidence is operational data, not secrets).
- In proxy mode the reverse proxy is trusted to authenticate users;
  Atlas verifies the proxy (shared secret), maps the asserted login to
  a provisioned account, and never accepts roles from headers.
- Browsers are untrusted: CSRF, CSP, cookie flags, and server-side
  authorization assume hostile pages elsewhere in the browser.
- Network devices are untrusted input: their output is evidence,
  parsed defensively and rendered escaped.
- Denial-of-service beyond the sensitive-endpoint rate limits is out of
  scope; deploy behind a proxy with connection limits.

## Resilience and data lifecycle

- **Migrations**: `workspace/migrations.py` — ordered, idempotent,
  audited; each backs affected files up to
  `migration-backups/v<N>/` before touching them. They run at startup;
  `/system/integrity` shows applied vs target schema version.
- **Backup**: `/settings/backup` (system administrators) exports all
  workspace JSON/JSONL metadata. Secrets and raw evidence are excluded
  by design.
- **Restore**: `/settings/restore` accepts only allowlisted root-level
  metadata files, validates JSON, limits size, requires the
  confirmation phrase, and **never restores `sessions.json`** — a
  backup must not resurrect revoked access. Recovery procedure: stop
  the server, restore the backup through the UI (or unzip the named
  files into the workspace root), restart, and check
  `/system/integrity`.
- **Corruption**: `/system/integrity` parses every known metadata file
  and names the recovery step per file; JSONL readers skip bad lines
  so one damaged line never hides a record.
- **Jobs**: discovery jobs persist across restarts, and
  `POST /api/discovery/jobs/<id>/cancel` requests cooperative
  cancellation — the run stops between observable steps, never
  mid-write, and the job ends in an explicit `cancelled` state.
- **Probes**: `/healthz` (liveness) and `/readyz` (workspace
  writability, audit log, user store, credential provider — component
  names and booleans only).
- **Logs**: one JSON line per request (actor, endpoint, status,
  duration, correlation id) on stderr; the same correlation id appears
  on the response header and in every audit event the request wrote.
  Bodies, query strings, and cookies are never logged.
- **Retention**: `retention_days` remains policy metadata; deletion
  still requires the audited, explicit-confirmation worker described in
  the administration contract.

## Notifications

`notifications.jsonl` is the internal inbox: assignments, failed
discoveries, policy regressions, edit conflicts, and approval requests,
addressed to a username or role. Ownership and status (unread → read →
done) need no email integration; an email/webhook bridge belongs
behind `NotificationStore` so the in-app record stays authoritative.

## Concurrency

Editable records carry revisions (site overrides and identity
resolutions always did; profiles, policy exceptions, plans, settings,
and users do now). Forms carry the revision they were rendered from; a
stale submission gets a 409 conflict page that names both revisions and
overwrites nothing, plus an inbox notification. Compass approvals bind
to the analysed revision — any later edit returns the plan to draft.

## Dependencies and supply chain

- Direct dependencies are range-pinned in `pyproject.toml`; the full
  environment is exact-pinned in `constraints.txt`
  (`pip install -c constraints.txt`).
- No runtime CDN dependencies: xterm.js is vendored, everything else is
  first-party.
- Scanning: `python -m pip_audit -r constraints.txt --no-deps`.
  Current status: setuptools upgraded past PYSEC-2026-3447;
  PYSEC-2026-2858 (paramiko 4.0.0) has **no fixed release listed** at
  scan time — tracked, revisit on the next paramiko release rather than
  jumping the untested 5.x major.

## Deliberate adapter boundaries

| Integration | Seam | Shipped today |
| --- | --- | --- |
| SSO / OIDC / SAML | `access/providers.py` (`identify()` contract) | `ProxySSOAuth` (proxy-asserted identity) |
| Vault / cloud secrets | `CredentialProvider` | keyring + encrypted-file |
| External job backend | `DiscoveryJobManager` runner interface | in-process threads |
| Email / chat delivery | `NotificationStore` | in-app inbox only |
