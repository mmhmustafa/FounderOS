"""Standard-library command-line interface for FounderOS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .application import FounderOSApplication
from .errors import RuntimeFoundationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="founderos", description="FounderOS local runtime CLI")
    parser.add_argument("--project-dir", default=".founderos", help="Local FounderOS project directory")
    subcommands = parser.add_subparsers(dest="command", required=True)

    new = subcommands.add_parser("new", help="Create a local FounderOS project")
    new.add_argument("--name", required=True)
    new.add_argument("--founder-name", required=True)
    new.add_argument("--founder-id", default="founder")
    new.add_argument("--domain", required=True)
    new.add_argument("--idempotency-key")

    subcommands.add_parser("status", help="Show current project status")
    subcommands.add_parser("plan", help="Show the deterministic execution plan")

    brief = subcommands.add_parser("founder-brief", help="Create a structured Founder Brief")
    brief.add_argument("--input", required=True, type=Path, help="Path to Founder Brief JSON input")
    brief.add_argument("--idempotency-key")

    approve = subcommands.add_parser("approve", help="Approve the pending Founder Brief and request transition")
    approve.add_argument("--rationale", required=True)
    approve.add_argument("--founder-id")
    approve.add_argument("--founder-name")
    approve.add_argument("--idempotency-key")

    subcommands.add_parser("decisions", help="List recorded decisions")
    subcommands.add_parser("events", help="List ordered project events")
    subcommands.add_parser("health", help="Validate local persistence and backup health")
    subcommands.add_parser("recover", help="Restore the last validated local backup")
    audit = subcommands.add_parser("audit", help="Show ordered, correlated runtime audit diagnostics")
    audit.add_argument("--include-sensitive", action="store_true", help="Include Artifact content and sensitive fields")
    subcommands.add_parser("runs", help="List WorkflowRun and AgentRun diagnostics")
    subcommands.add_parser("transitions", help="List transition and approval trace diagnostics")
    return parser


def execute(arguments: argparse.Namespace) -> Any:
    app = FounderOSApplication(arguments.project_dir)
    if arguments.command == "new":
        return app.new(name=arguments.name, founder_id=arguments.founder_id, founder_name=arguments.founder_name, domain=arguments.domain, command_key=arguments.idempotency_key)
    if arguments.command == "status":
        return app.status()
    if arguments.command == "plan":
        return app.plan()
    if arguments.command == "founder-brief":
        try:
            content = json.loads(arguments.input.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Cannot read Founder Brief input: {error}") from error
        if not isinstance(content, dict):
            raise ValueError("Founder Brief input must be a JSON object")
        return app.founder_brief(content, command_key=arguments.idempotency_key)
    if arguments.command == "approve":
        return app.approve(rationale=arguments.rationale, founder_id=arguments.founder_id, founder_name=arguments.founder_name, command_key=arguments.idempotency_key)
    if arguments.command == "decisions":
        return app.decisions()
    if arguments.command == "events":
        return app.events()
    if arguments.command == "health":
        return app.health()
    if arguments.command == "recover":
        return app.recover()
    if arguments.command == "audit":
        return app.audit(include_sensitive=arguments.include_sensitive)
    if arguments.command == "runs":
        return app.runs()
    if arguments.command == "transitions":
        return app.transitions()
    raise ValueError(f"Unknown command: {arguments.command}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        result = execute(parser.parse_args(argv))
    except (RuntimeFoundationError, OSError, ValueError) as error:
        print(json.dumps({"error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
