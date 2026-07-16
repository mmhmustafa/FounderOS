# Adding a Platform Driver

1. **Capture sanitized transcripts** of real output (identity, interfaces,
   neighbors, routes, config; plus degraded variants). No credentials, no
   customer identifiers. Put them in `tests/platform_fixtures/<platform>.py`.
2. **Subclass `ProductionDriver`** in `platforms/drivers/<platform>.py`:
   matcher, `netmiko_device_type`, `session_setup`, `command_plan()` with
   fallbacks and tiers, a parse-only `DiscoveryAdapter`, `annotate()` for
   platform-distinctive evidence. Override `rejects()`/`denied()` when the
   platform's refusal grammar is not Cisco-style.
3. **Register** in `registry.default_registry()` — production platforms before
   lab ones; more-specific matchers before broader ones (see IOS-XE vs IOS).
4. **Tests**: platform-specific assertions + add the driver to `_wave1()` in
   `tests/test_polyglot_drivers.py` so the cross-vendor contract suite runs it.
5. **Maturity**: start EXPERIMENTAL. BETA requires live validation on at least
   one supported version, recorded in the platform doc. Never grant maturity
   by editing the guard test.
6. **Document** in `docs/platforms/<PLATFORM>.md`.
