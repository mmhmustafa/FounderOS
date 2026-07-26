# CURRENT SPRINT

Sprint: Atlas PR-155 through PR-162 implementation and release audit

Updated: 26 July 2026

## Goal

Complete the eight post-PR-154 product increments, integrate them without
weakening evidence honesty or security, and run an adversarial release audit.

## Baseline

- Product capability entered this sprint shipped through PR-154.
- The existing suite contained more than 2,300 tests.
- External device, notification, telemetry, and cloud providers remain explicit
  adapter boundaries; Atlas must never simulate their availability.

## Completed scope

- PR-155 topology and calm-interface stabilization.
- PR-156 Evidence and Identity Resolution Center.
- PR-157 policy intent, applicability, governance, and prioritization.
- PR-158 operational Action Center and bounded delivery outbox.
- PR-159 immutable Network Time Travel.
- PR-160 unified investigation cases.
- PR-161 durable scheduled operations and maintenance windows.
- PR-162 operational telemetry adapter foundation and overlays.
- Independent security review of adapter exceptions, secret normalization,
  concurrent delivery, persistence, authorization, CSP, and exports.

## Definition of done

- Focused and complete automated suites pass after integration.
- Dependency, documentation, encoding, compilation, packaging, route/RBAC,
  CSP, secret-canary, persistence, concurrency, and performance gates pass.
- Representative real-browser flows render without server errors, broken
  resources, inline handlers, inaccessible controls, or horizontal overflow.
- No blocker or high-severity issue remains.
- External adapters and accepted persistence limitations are documented rather
  than implied to be complete.

## Explicit limitation

Workspace state files and the dedicated audit JSONL use atomic writes and
process-safe locks, but they are not one cross-file transaction. A host crash
between those writes can leave a durable state change without its local audit
entry. A transactional workspace journal is the required architectural fix.
