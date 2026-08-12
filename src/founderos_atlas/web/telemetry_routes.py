"""Operational telemetry collection boundary and focused evidence view."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode


def register_telemetry_routes(app) -> None:
    from flask import flash, g, redirect, render_template, request, url_for

    from founderos_atlas.telemetry import (
        AdapterUnavailableError,
        FACT_KINDS,
        derive_signals,
    )

    def store():
        return app.config["ATLAS_TELEMETRY_STORE"]

    def registry():
        return app.config["ATLAS_TELEMETRY_REGISTRY"]

    def _query(
        *, scope_id: str | None = None, entity_id: str | None = None,
        kind: str | None = None, limit: int = 5000,
    ):
        effective_scope = (
            None if scope_id in (None, "", "all", "enterprise") else scope_id
        )
        facts = store().query(
            scope_id=effective_scope,
            kind=kind,
            since=datetime.now(timezone.utc) - timedelta(days=7),
            limit=limit,
        )
        if entity_id:
            wanted = entity_id.strip().casefold()
            facts = [
                item for item in facts
                if item.entity_id.casefold() == wanted
                or item.entity_id.casefold().startswith(wanted + ":")
                or item.entity_id.casefold().startswith(wanted + "->")
            ]
        return facts

    def telemetry_context(
        scope_id: str | None = None, entity_id: str | None = None
    ) -> dict:
        facts = _query(
            scope_id=scope_id, entity_id=entity_id, limit=1000
        )
        signals = derive_signals(facts)
        statuses = registry().statuses()
        query = {}
        if scope_id and scope_id not in ("all", "enterprise"):
            query["scope"] = scope_id
        if entity_id:
            query["entity"] = entity_id
        return {
            "facts": len(facts),
            "signals": len(signals),
            "stale_signals": sum(1 for item in signals if item.stale),
            "latest": max(
                (item.observed_at for item in facts), default=None
            ),
            "configured_adapters": len(statuses),
            "available_adapters": sum(
                1 for item in statuses.values()
                if item.get("state") == "available"
            ),
            "href": "/telemetry" + (
                "?" + urlencode(query) if query else ""
            ),
        }

    @app.context_processor
    def _telemetry_template_context():
        # A callable avoids reading the evidence store on pages that do not
        # display operational context.
        return {"telemetry_context": telemetry_context}

    @app.route("/telemetry")
    def telemetry_page():
        scope_id = str(request.args.get("scope") or "").strip() or None
        entity_id = str(request.args.get("entity") or "").strip() or None
        kind = str(request.args.get("kind") or "").strip() or None
        if kind not in (None, *FACT_KINDS):
            kind = None
        try:
            requested_page = max(1, int(request.args.get("page", "1")))
        except ValueError:
            requested_page = 1
        from .pagination import paginate

        all_facts = _query(
            scope_id=scope_id, entity_id=entity_id, kind=kind,
            limit=store().max_facts,
        )
        page = paginate(
            all_facts, requested_page=requested_page, page_size=100
        )
        signals = derive_signals(all_facts)
        # PR-177: full workspace context so a deep link keeps its
        # breadcrumb trail even while guided navigation hides Signals.
        base = app.extensions["atlas_base_context"]("telemetry")
        return render_template(
            "telemetry.html",
            **base,
            facts=page.items,
            fact_total=page.total,
            fact_page=page.number,
            fact_page_count=page.page_count,
            signals=signals,
            scope_id=scope_id or "",
            entity_id=entity_id or "",
            selected_kind=kind or "",
            fact_kinds=FACT_KINDS,
            filter_args={
                key: value for key, value in {
                    "scope": scope_id, "entity": entity_id, "kind": kind,
                }.items() if value
            },
            adapter_status=registry().statuses(),
            retention_days=store().retention_days,
        )

    @app.route("/telemetry/collect", methods=["POST"])
    def telemetry_collect():
        adapter_name = str(request.form.get("adapter") or "").strip()
        scope_id = str(request.form.get("scope") or "").strip()
        principal = getattr(g, "principal", None)
        actor = getattr(principal, "username", None) or "local-operator"
        roles = getattr(principal, "roles", ())
        try:
            result = app.config[
                "ATLAS_TELEMETRY_COLLECTION_SERVICE"
            ].collect(
                adapter_name, scope_id=scope_id, actor=actor,
                actor_roles=roles,
            )
        except (AdapterUnavailableError, ValueError):
            flash(
                "The telemetry provider could not complete collection. "
                "Provider status was updated; no credential detail was stored.",
                "error",
            )
        else:
            flash(
                f"Collected {result.received} observation(s); "
                f"{result.added} new fact(s) retained.",
                "success",
            )
        return redirect(url_for("telemetry_page", scope=scope_id))
