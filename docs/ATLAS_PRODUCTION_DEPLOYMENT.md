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

### How local mode can and cannot be exposed

Local mode **fails closed** on every path that could smuggle a remote
user in:

- Any request from a non-loopback address is refused with 403 before
  any view runs, and the CLI refuses to bind beyond 127.0.0.1.
- Any loopback request carrying proxy/forwarding headers (`Forwarded`,
  `X-Forwarded-For`, `X-Real-IP`, `X-Client-IP`, `True-Client-IP`,
  `CF-Connecting-IP`, and variants) is refused: a reverse proxy on the
  same machine makes remote users look loopback, and those headers are
  the tell. Header VALUES are never trusted to determine the client.
- Starting local mode with proxy-shaped settings
  (`ATLAS_TRUSTED_PROXY_ADDRS` or `ATLAS_PROXY_SECRET`) refuses at
  startup instead of guessing.
- The one narrow developer override is
  `ATLAS_LOCAL_ALLOW_FORWARDED=1`, for a deliberate localhost-only dev
  wrapper (e.g. local TLS terminator) that adds such headers to
  genuinely local traffic. It logs a prominent startup warning, still
  refuses non-loopback peers, and must never be combined with exposing
  the port.

There is no supported way to put local mode behind a proxy for other
users; serving anyone else requires `password` or `proxy` mode.

### Sessions (password mode)

- The browser holds an opaque 256-bit token (`atlas_session`,
  HttpOnly, SameSite=Lax, Secure under TLS). The store holds only its
  SHA-256, so the session file yields no usable tokens.
- Login always mints a fresh token (session fixation cannot survive
  authentication). Logout, account disable, and account delete revoke
  server-side immediately.
- Absolute lifetime `ATLAS_SESSION_MAX_AGE` (default 12 h) and idle
  timeout `ATLAS_SESSION_IDLE_TIMEOUT` (default 2 h).

### Bootstrap and emergency recovery

With an empty user store, set `ATLAS_BOOTSTRAP_ADMIN_USER` and
`ATLAS_BOOTSTRAP_ADMIN_PASSWORD` for the first start. The password is
hashed immediately and never stored in clear; remove both variables
after the first start. Further accounts are managed on `/users`
(system administrators only, fully audited).

**Administrator-lockout invariants** (enforced in the user store, so
every caller is covered):

1. At least one enabled, sign-in-capable system administrator always
   remains — the last one cannot be disabled, deleted, demoted, or
   left password-less in password mode. In proxy mode SSO-only
   administrators count as usable.
2. A signed-in administrator cannot disable their own account or
   remove their own system-admin role.
3. Disabling, deleting, or rotating the password of an account revokes
   its sessions immediately.
4. In password mode, every user-management change requires the acting
   administrator to re-enter **their own** password; refusals are
   audited.

**Emergency recovery** (tested): if every administrator is lost, set
`ATLAS_RECOVERY_ADMIN_USER` and `ATLAS_RECOVERY_ADMIN_PASSWORD` and
restart — the named account is created or reset as an enabled system
administrator (hash-stored, event audited as `recovery-reset`). Sign
in, repair the accounts, then unset both variables. This adds no trust
boundary: whoever sets this process's environment already owns the
host.

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
- Sign-in rate limiting is **layered** (fixed one-minute windows):
  an account layer keyed on the case-normalized submitted username —
  existing or not — so distributed attacks cannot dodge it and limiting
  reveals nothing about which accounts exist
  (`ATLAS_LOGIN_ACCOUNT_LIMIT`, default 5); a source-address layer
  (`ATLAS_LOGIN_SOURCE_LIMIT`, default 30); and an optional global
  ceiling (`ATLAS_LOGIN_GLOBAL_LIMIT`, default 500, 0 disables). Every
  attempt consumes every layer, successful logins never reset counters,
  and all layers answer with one identical 429. Other sensitive
  endpoints keep per-source limits (tests 20/min, restore 5/min,
  advisor 30/min). Denials are audited without passwords.
- **The built-in limiter is single-process and in-memory**: counters
  are not shared across workers and reset on restart. Multi-worker
  deployments must supply a shared implementation behind the
  `ATLAS_RATE_LIMITER` adapter boundary (unknown names refuse to
  start); until then run one process, or enforce limits at the proxy.
- Behind an SSO proxy, set `ATLAS_TRUSTED_PROXY_ADDRS` to the proxy's
  address(es): rate limiting and audit then attribute requests to the
  closest untrusted `X-Forwarded-For` hop. Header values are used for
  attribution only, only from those peers, and never for
  authentication.
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

## Supported process model (enforced)

Atlas supports exactly **one process per workspace**. Threads are fine
(discovery jobs, request handling); multiple WSGI workers or a second
service instance over the same workspace are NOT supported and are
actively prevented: at startup the application takes an OS-level
exclusive instance lock derived from the workspace path, and a second
process fails to start with instructions instead of silently racing
shared files. The lock releases automatically if the process dies.
``/readyz`` reports ``single-instance``; a false value means an
unsupported multi-process deployment.

Deployment commands:

- Windows/dev: ``python -m founderos_runtime … atlas web`` (one process).
- gunicorn: ``gunicorn --workers 1 --threads 8 'founderos_atlas.web:create_app()'``
  — **exactly** ``--workers 1``; more workers will fail to start by design.

Nothing in this guide implies multi-worker safety. Scaling beyond one
process requires a transactional persistence adapter and a shared rate
limiter — both deliberate future work behind existing seams.

## Backup contract

``/settings/backup`` builds from an explicit, reviewed manifest
(``workspace/backup.py``) — never from "every JSON in the directory".
An unknown future file is excluded until consciously classified, so a
new secret store can never leak into backups by default.

- **Included (operational metadata)**: profiles, credential-set
  references, credential success memory, preferences, drafts, sites,
  site overrides + audit, identity resolutions + audit, policy
  exceptions/trend, annotations, incidents, notifications, the unified
  audit log, the schema marker.
- **Included but sensitive**: ``users.json`` (scrypt password hashes —
  protect the archive).
- **Always excluded**: ``credentials.enc.json`` and every credential
  store (encrypted or not; the OS keyring is never read),
  ``sessions.json`` (restoring tokens would resurrect revoked access),
  temporary ``.…writing``/``*.restoring`` files, raw evidence (a
  separate explicit export), migration backups, and any file not in the
  manifest.

Every archive carries ``backup-manifest.json``: backup schema version,
file names/sizes/SHA-256 hashes/classifications, creation time, and
application version.

## Restore transaction model

Restore (``/settings/restore``) is a transaction:

1. refuse oversized uploads before reading the body;
2. validate EVERY member — plain workspace filenames only (no
   traversal), no duplicates, only manifest-known files (sessions and
   credential stores are never restorable), per-member and total size
   limits, compression-ratio bomb guard, JSON/JSONL structure, schema
   compatibility, manifest hash verification;
3. stage all files beside the workspace;
4. snapshot the current state to ``pre-restore-snapshots/<stamp>/``;
5. commit atomically file-by-file — any failure rolls every committed
   file back from the snapshot (verified by a fault-injection test);
6. run integrity verification over the restored files;
7. audit the outcome (success or refusal, without data), and instruct
   an application restart so in-memory views reload.

Recovery: if a restore ever leaves doubt, the pre-restore snapshot
directory contains the exact prior state of every touched file — copy
them back and restart. ``/system/integrity`` names any corrupt file and
its recovery step.

## Resilience and data lifecycle

- **Migrations**: `workspace/migrations.py` — ordered, idempotent,
  audited; each backs affected files up to
  `migration-backups/v<N>/` before touching them. They run at startup;
  `/system/integrity` shows applied vs target schema version.
- **Backup**: `/settings/backup` (system administrators) follows the
  explicit backup contract above — reviewed manifest, machine-readable
  hashes, secrets/sessions/evidence excluded by construction.
- **Restore**: `/settings/restore` runs the transactional model above
  (validate → stage → snapshot → commit → verify, with full rollback);
  it requires the confirmation phrase and **never restores
  `sessions.json`** or any credential store.
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
