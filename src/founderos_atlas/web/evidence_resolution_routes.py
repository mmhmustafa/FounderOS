"""Web workflow for evidence coverage and identity resolution."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from founderos_atlas.audit import AuditEvent, AuditLog
from founderos_atlas.evidence_resolution import (
    ResolutionDecisionConflictError,
    ResolutionDecisionRepository,
    build_resolution_queue,
    coverage_dimensions,
    filter_resolution_queue,
)
from founderos_atlas.identity import (
    PeerResolutionConflictError,
    PeerResolutionRepository,
)
from founderos_atlas.listing import paginate

from .redirects import safe_redirect_target


def register_evidence_resolution_routes(
    app,
    *,
    scoped_context: Callable,
    evidence_sessions: Callable,
    session_scope: Callable,
    memory_store: Callable,
    topology_facts: Callable,
    current_actor: Callable[[], str],
    refresh_topologies: Callable[[], None],
) -> None:
    """Register the workflow while reusing the parent route's scope adapters."""

    from flask import (
        flash,
        g,
        redirect,
        render_template,
        request,
        url_for,
    )

    def workspace_root() -> Path:
        return Path(app.config["ATLAS_WORKSPACE_ROOT"])

    def _data():
        context, scopes, scope_id = scoped_context("memory")
        sessions = evidence_sessions(scopes, scope_id)
        if not sessions:
            return {
                "context": context,
                "scopes": scopes,
                "scope_id": scope_id,
                "sessions": (),
                "session": None,
                "scope": None,
                "records": (),
                "snapshots": (),
                "facts": None,
            }
        requested = (
            request.values.get("session")
            or request.args.get("session")
            or ""
        ).strip()
        session = next(
            (item for item in sessions if item["session_id"] == requested),
            sessions[0],
        )
        scope = session_scope(scopes, scope_id, session["session_id"])
        store = memory_store(scope)
        records = tuple(
            item.to_dict()
            for item in store.evidence_records(
                discovery_session=session["session_id"]
            )
        )
        snapshots = tuple(
            item.to_dict()
            for item in store.configuration_snapshots()
            if item.discovery_session == session["session_id"]
        )
        facts = topology_facts(
            scope.output_dir,
            workspace_root=workspace_root(),
        )
        return {
            "context": context,
            "scopes": scopes,
            "scope_id": scope_id,
            "sessions": sessions,
            "session": session,
            "scope": scope,
            "records": records,
            "snapshots": snapshots,
            "facts": facts,
        }

    def _queue(data, catalog):
        identity = dict((data["facts"] or {}).get("identity") or {})
        return build_resolution_queue(
            unresolved=identity.get("unresolved") or (),
            records=data["records"],
            snapshots=data["snapshots"],
            decisions=catalog,
        )

    def _actor_roles() -> tuple[str, ...]:
        principal = getattr(g, "principal", None)
        return tuple(getattr(principal, "roles", ()) or ())

    def _audit(
        *,
        operation: str,
        subject: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        reason: str | None = None,
        scope_id: str = "all",
    ) -> None:
        AuditLog(workspace_root()).append(AuditEvent.create(
            category="evidence-resolution",
            operation=operation,
            subject=subject,
            actor=current_actor(),
            actor_roles=_actor_roles(),
            scope_id=scope_id,
            before=before,
            after=after,
            reason=reason,
            correlation_id=getattr(g, "correlation_id", None),
        ))

    def _return_target() -> str:
        return safe_redirect_target(
            request.form.get("next"),
            url_for(
                "evidence_resolution_center",
                session=request.form.get("session") or None,
            ),
        )

    @app.route("/evidence/resolution-center")
    def evidence_resolution_center():
        data = _data()
        repository = ResolutionDecisionRepository(workspace_root())
        catalog = repository.load()
        all_items = _queue(data, catalog)
        filters = {
            "kind": str(request.args.get("kind") or "").strip(),
            "status": str(request.args.get("status") or "").strip(),
            "q": str(request.args.get("q") or "").strip(),
        }
        visible = filter_resolution_queue(all_items, **{
            "kind": filters["kind"],
            "status": filters["status"],
            "query": filters["q"],
        })
        try:
            page_number = max(1, int(request.args.get("page") or 1))
        except ValueError:
            page_number = 1
        page = paginate(visible, page_number, 30)
        facts = data["facts"] or {}
        identity = dict(facts.get("identity") or {})
        current_query = {
            key: value for key, value in {
                "session": (
                    data["session"]["session_id"]
                    if data["session"] else ""
                ),
                **filters,
            }.items() if value
        }
        return render_template(
            "evidence_resolution_center.html",
            sessions=data["sessions"],
            session=data["session"],
            coverage=coverage_dimensions(
                data["session"],
                data["records"],
                data["snapshots"],
                data["facts"],
            ),
            items=page.items,
            page=page,
            filters=filters,
            kinds=sorted({
                (str(item["kind"]), str(item["kind_label"]))
                for item in all_items
            }),
            counts={
                "total": len(all_items),
                "open": sum(
                    1 for item in all_items if item["status"] == "open"
                ),
                "deferred": sum(
                    1 for item in all_items if item["status"] == "deferred"
                ),
                "rejected": sum(
                    1 for item in all_items if item["status"] == "rejected"
                ),
            },
            decision_revision=catalog.revision,
            identity_revision=int(identity.get("revision") or 0),
            active_resolutions=identity.get("active") or (),
            identity_history=identity.get("history") or (),
            query_string=urlencode(current_query),
            corroboration_available=False,
            **data["context"],
        )

    @app.route(
        "/evidence/resolution-center/identity/confirm", methods=["POST"]
    )
    def evidence_resolution_identity_confirm():
        if request.form.get("confirm") != "yes":
            flash(
                "Review the impact and explicitly confirm this identity "
                "resolution.",
                "error",
            )
            return redirect(_return_target())
        data = _data()
        decision_catalog = ResolutionDecisionRepository(
            workspace_root()
        ).load()
        item = next(
            (
                candidate for candidate in _queue(data, decision_catalog)
                if candidate["item_key"] == request.form.get("item_key")
            ),
            None,
        )
        hostname = str(request.form.get("resolved_hostname") or "").strip()
        if item is None or item.get("kind") != "identity":
            flash(
                "That queue item no longer exists. Reload and review current "
                "evidence.",
                "error",
            )
            return redirect(_return_target())
        proposal = next(
            (
                proposal for proposal in item.get("proposals") or ()
                if proposal.get("hostname") == hostname
            ),
            None,
        )
        if proposal is None:
            flash(
                "The selected device is not supported by the current "
                "deterministic proposal.",
                "error",
            )
            return redirect(_return_target())
        reason = str(request.form.get("reason") or "").strip()[:500] or (
            f"Confirmed {proposal.get('signal')}: {proposal.get('detail')}"
        )
        try:
            catalog, event = PeerResolutionRepository(
                workspace_root()
            ).resolve(
                peer_label=str(item["peer_label"]),
                resolved_hostname=hostname,
                resolved_device_id=proposal.get("device_id"),
                reason=reason,
                actor=current_actor(),
                expected_revision=_int_or_none(
                    request.form.get("expected_identity_revision")
                ),
            )
        except (PeerResolutionConflictError, ValueError) as error:
            flash(str(error), "error")
            return redirect(_return_target())
        _audit(
            operation="confirm",
            subject=str(item["item_key"]),
            after={
                "peer_label": item["peer_label"],
                "resolved_hostname": hostname,
                "signal": proposal.get("signal"),
                "confidence": proposal.get("confidence"),
                "identity_revision": catalog.revision,
                "identity_event_id": event.event_id,
            },
            reason=reason,
            scope_id=data["scope_id"],
        )
        refresh_topologies()
        flash(
            f"Confirmed {item['peer_label']} as {hostname}. Discovery evidence "
            "was preserved and topology was recomputed.",
            "success",
        )
        return redirect(_return_target())

    @app.route(
        "/evidence/resolution-center/identity/bulk-confirm", methods=["POST"]
    )
    def evidence_resolution_identity_bulk_confirm():
        if request.form.get("confirm") != "yes":
            flash(
                "Explicitly confirm the selected identity resolutions.",
                "error",
            )
            return redirect(_return_target())
        data = _data()
        decision_catalog = ResolutionDecisionRepository(
            workspace_root()
        ).load()
        by_key = {
            item["item_key"]: item for item in _queue(data, decision_catalog)
        }
        selected = tuple(dict.fromkeys(request.form.getlist("item_keys")))[:100]
        items = [by_key.get(key) for key in selected]
        if not selected or any(item is None for item in items):
            flash("Select current identity proposals to confirm.", "error")
            return redirect(_return_target())
        resolved = []
        signals = set()
        for item in items:
            proposals = list(item.get("proposals") or ())
            if (
                item.get("kind") != "identity"
                or len(proposals) != 1
                or not proposals[0].get("auto_eligible")
            ):
                flash(
                    "Bulk confirmation is limited to proposals with one exact "
                    "address-ownership match. Review ambiguous items singly.",
                    "error",
                )
                return redirect(_return_target())
            proposal = proposals[0]
            signals.add(str(proposal.get("signal") or ""))
            resolved.append({
                "peer_label": item["peer_label"],
                "resolved_hostname": proposal["hostname"],
                "resolved_device_id": proposal.get("device_id"),
                "reason": (
                    f"Bulk confirmed {proposal.get('signal')}: "
                    f"{proposal.get('detail')}"
                ),
            })
        if len(signals) != 1:
            flash(
                "Bulk confirmation requires identical evidence rules. "
                "Review this mixed selection singly.",
                "error",
            )
            return redirect(_return_target())
        try:
            catalog, events = PeerResolutionRepository(
                workspace_root()
            ).resolve_many(
                resolved,
                actor=current_actor(),
                reason="Bulk confirmation of identical unambiguous evidence",
                expected_revision=_int_or_none(
                    request.form.get("expected_identity_revision")
                ),
            )
        except (PeerResolutionConflictError, ValueError) as error:
            flash(str(error), "error")
            return redirect(_return_target())
        for item, event in zip(items, events):
            _audit(
                operation="bulk-confirm",
                subject=str(item["item_key"]),
                after={
                    "peer_label": event.peer_label,
                    "resolved_hostname": event.after_hostname,
                    "signal": next(iter(signals)),
                    "identity_revision": event.revision,
                    "identity_event_id": event.event_id,
                },
                reason="Bulk confirmation of identical unambiguous evidence",
                scope_id=data["scope_id"],
            )
        refresh_topologies()
        flash(
            f"Confirmed {len(events)} unambiguous identities in one atomic "
            f"update (revision {catalog.revision}).",
            "success",
        )
        return redirect(_return_target())

    @app.route("/evidence/resolution-center/decision", methods=["POST"])
    def evidence_resolution_decide():
        data = _data()
        repository = ResolutionDecisionRepository(workspace_root())
        current = repository.load()
        item = next(
            (
                candidate for candidate in _queue(data, current)
                if candidate["item_key"] == request.form.get("item_key")
            ),
            None,
        )
        if item is None:
            flash("That queue item no longer exists.", "error")
            return redirect(_return_target())
        status = str(request.form.get("status") or "").strip()
        reason = str(request.form.get("reason") or "").strip()[:500]
        if not reason:
            flash("Give a reason so the decision remains explainable.", "error")
            return redirect(_return_target())
        try:
            _, event = repository.decide(
                item_key=str(item["item_key"]),
                status=status,
                reason=reason,
                actor=current_actor(),
                expected_revision=_int_or_none(
                    request.form.get("expected_decision_revision")
                ),
            )
        except (ResolutionDecisionConflictError, ValueError) as error:
            flash(str(error), "error")
            return redirect(_return_target())
        _audit(
            operation=status,
            subject=str(item["item_key"]),
            before=event.get("before"),
            after=event.get("after"),
            reason=reason,
            scope_id=data["scope_id"],
        )
        flash(
            "Queue item deferred." if status == "deferred"
            else "Proposal rejected. Underlying evidence remains visible.",
            "success",
        )
        return redirect(_return_target())

    @app.route("/evidence/resolution-center/decision/undo", methods=["POST"])
    def evidence_resolution_decision_undo():
        repository = ResolutionDecisionRepository(workspace_root())
        key = str(request.form.get("item_key") or "").strip()
        try:
            _, event = repository.undo(
                item_key=key,
                actor=current_actor(),
                expected_revision=_int_or_none(
                    request.form.get("expected_decision_revision")
                ),
            )
        except (ResolutionDecisionConflictError, ValueError) as error:
            flash(str(error), "error")
            return redirect(_return_target())
        _audit(
            operation="undo-decision",
            subject=key,
            before=event.get("before"),
            after={},
        )
        flash("Queue decision undone; the item is open again.", "success")
        return redirect(_return_target())

    @app.route(
        "/evidence/resolution-center/identity/undo", methods=["POST"]
    )
    def evidence_resolution_identity_undo():
        subject = str(request.form.get("subject_key") or "").strip()
        repository = PeerResolutionRepository(workspace_root())
        try:
            catalog, event = repository.undo(
                subject_key=subject,
                actor=current_actor(),
                expected_revision=_int_or_none(
                    request.form.get("expected_identity_revision")
                ),
            )
        except (PeerResolutionConflictError, ValueError) as error:
            flash(str(error), "error")
            return redirect(_return_target())
        _audit(
            operation="undo-confirmation",
            subject=subject,
            before={"resolved_hostname": event.before_hostname},
            after={"resolved_hostname": event.after_hostname},
            reason=event.reason,
        )
        refresh_topologies()
        flash(
            f"Undid the latest identity change (revision {catalog.revision}).",
            "success",
        )
        return redirect(_return_target())


def _int_or_none(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None
