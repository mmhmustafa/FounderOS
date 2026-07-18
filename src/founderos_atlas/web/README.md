# Atlas web application

The Flask application exposes the same Atlas services used by the CLI. It
supports three explicit authentication modes:

- `local`: loopback-only development principal; remote and proxied requests
  fail closed.
- `password`: workspace accounts, scrypt password hashes, opaque server-side
  sessions, RBAC, CSRF, conflict detection, and audit attribution.
- `proxy`: identity asserted by a trusted SSO reverse proxy using a shared
  proof header and explicitly provisioned Atlas accounts/roles.

`create_app()` wires routes, default-deny authorization, security headers,
structured logs, health probes, migrations, a workspace instance lock, and
the in-process discovery manager. Atlas supports one process per workspace;
discovery runs in controlled threads and survives browser navigation, but an
active job is marked interrupted after a process restart.

The UI never receives stored secrets. Profiles and credential sets hold only
opaque references resolved by the effective credential provider. Settings
and diagnostics report that provider, its availability, authentication mode,
TLS/HSTS state, application bind, trusted proxies, session policy, worker
model/status, workspace schema, release/commit, logging, retention, and update
provider without claiming visibility into an external reverse proxy.

Run locally with `founderos atlas web`. Production password/proxy/TLS startup,
backup exclusions, and recovery controls are documented in
`docs/ATLAS_PRODUCTION_DEPLOYMENT.md`.
