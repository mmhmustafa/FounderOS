# FounderOS command-line interface

The CLI is the supported automation and local-start boundary for FounderOS
Atlas. `founderos version` reads the same authoritative release identity as
package metadata, Settings, diagnostics, backups, and startup logs.

Use `founderos help` for the complete command inventory. Common operations:

```text
founderos version
founderos doctor
founderos atlas web
founderos atlas discover --profile <name>
founderos atlas history --profile <name>
founderos atlas investigate --profile <name>
```

Commands call application/service boundaries directly; the web application
does not shell out to the CLI. Live discovery uses read-only SSH commands and
the configured secure credential provider.
