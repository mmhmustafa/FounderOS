"""Operational routes: health probes, inbox, users, cancellation, approval.

Registered after the main routes so the authorization table governs all
of them (``healthz``/``readyz`` are PUBLIC by design: a load balancer
has no session — the probes therefore reveal component NAMES and
boolean readiness only, never paths or configuration).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

from founderos_atlas.audit import AuditEvent, AuditLog
from founderos_atlas.notifications import (
    KIND_APPROVAL_REQUEST,
    NotificationStore,
)


def register_ops_routes(app) -> None:
    from flask import Response, abort, flash, g, redirect, render_template, request

    def cfg(name):
        return app.config[name]

    def _workspace_root() -> Path:
        return Path(cfg("ATLAS_WORKSPACE_ROOT"))

    def _audit() -> AuditLog:
        return AuditLog(_workspace_root())

    def _notifications() -> NotificationStore:
        return NotificationStore(_workspace_root())

    def _actor():
        principal = getattr(g, "principal", None)
        return principal

    def _audit_event(**kwargs) -> AuditEvent:
        principal = _actor()
        return AuditEvent.create(
            actor=principal.username if principal else "unauthenticated",
            actor_roles=principal.roles if principal else (),
            correlation_id=getattr(g, "correlation_id", None),
            **kwargs,
        )

    # -- health ------------------------------------------------------------

    @app.route("/healthz")
    def healthz():
        return Response(
            json.dumps({"status": "ok"}), mimetype="application/json"
        )

    @app.route("/readyz")
    def readyz():
        components: dict[str, bool] = {}

        root = _workspace_root()
        try:
            root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=root, delete=True):
                pass
            components["workspace-writable"] = True
        except OSError:
            components["workspace-writable"] = False

        try:
            AuditLog(root).events()
            components["audit-log"] = True
        except Exception:
            components["audit-log"] = False

        mode = app.config.get("ATLAS_AUTH_MODE", "local")
        if mode != "local":
            try:
                components["user-store"] = not cfg(
                    "ATLAS_USER_STORE"
                ).is_empty()
            except Exception:
                components["user-store"] = False

        try:
            provider = cfg("ATLAS_PROFILE_SERVICE")._credentials  # noqa: SLF001
            components["credential-provider"] = bool(provider.available())
        except Exception:
            components["credential-provider"] = False

        ready = all(components.values())
        return Response(
            json.dumps({
                "status": "ready" if ready else "degraded",
                "components": components,
            }),
            status=200 if ready else 503,
            mimetype="application/json",
        )

    # -- inbox -------------------------------------------------------------

    @app.route("/inbox")
    def inbox():
        principal = _actor()
        include_done = request.args.get("done") == "1"
        items = _notifications().for_principal(
            principal.username, principal.roles, include_done=include_done,
        )
        return render_template(
            "inbox.html", notifications=items, include_done=include_done,
        )

    @app.route("/inbox/<notification_id>", methods=["POST"])
    def inbox_update(notification_id: str):
        status = str(request.form.get("status") or "read")
        try:
            changed = _notifications().set_status(notification_id, status)
        except ValueError as error:
            flash(str(error), "error")
            return redirect("/inbox")
        if changed:
            flash(f"Notification marked {status}.", "success")
        else:
            flash("That notification no longer exists.", "error")
        return redirect(request.form.get("next") or "/inbox")

    # -- users administration ---------------------------------------------

    @app.route("/users")
    def users_page():
        store = cfg("ATLAS_USER_STORE")
        from founderos_atlas.access.models import ALL_ROLES

        return render_template(
            "users.html",
            accounts=[account.public_dict() for account in store.list()],
            revision=store.revision(),
            roles=ALL_ROLES,
            auth_mode_active=app.config.get("ATLAS_AUTH_MODE"),
            session_count=cfg("ATLAS_SESSION_STORE").active_count(),
        )

    @app.route("/users", methods=["POST"], endpoint="users_create")
    def users_create():
        from founderos_atlas.access import UserConflictError, UserStoreError

        store = cfg("ATLAS_USER_STORE")
        try:
            expected = int(request.form.get("expected_revision", "") or 0)
            account = store.create(
                username=str(request.form.get("username") or ""),
                display_name=str(request.form.get("display_name") or "") or None,
                roles=request.form.getlist("roles"),
                password=str(request.form.get("password") or "") or None,
                expected_revision=expected,
            )
        except UserConflictError as error:
            abort(409, description=str(error))
        except UserStoreError as error:
            flash(str(error), "error")
            return redirect("/users")
        _audit().append(_audit_event(
            category="user-account", operation="create",
            subject=f"user:{account.username}",
            after={"roles": list(account.roles),
                   "display_name": account.display_name},
        ))
        flash(f"Account {account.username} created.", "success")
        return redirect("/users")

    @app.route("/users/<username>", methods=["POST"], endpoint="users_update")
    def users_update(username: str):
        from founderos_atlas.access import UserConflictError, UserStoreError

        store = cfg("ATLAS_USER_STORE")
        before = store.get(username)
        if before is None:
            flash("No such account.", "error")
            return redirect("/users")
        disabled = request.form.get("disabled")
        try:
            expected = int(request.form.get("expected_revision", "") or 0)
            account = store.update(
                username,
                display_name=(
                    str(request.form["display_name"])
                    if "display_name" in request.form else None
                ),
                roles=(
                    request.form.getlist("roles")
                    if request.form.getlist("roles") else None
                ),
                password=str(request.form.get("password") or "") or None,
                disabled=(disabled == "1") if disabled is not None else None,
                expected_revision=expected,
            )
        except UserConflictError as error:
            abort(409, description=str(error))
        except UserStoreError as error:
            flash(str(error), "error")
            return redirect("/users")
        if account.disabled and not before.disabled:
            cfg("ATLAS_SESSION_STORE").invalidate_user(account.username)
        _audit().append(_audit_event(
            category="user-account", operation="update",
            subject=f"user:{account.username}",
            before={"roles": list(before.roles), "disabled": before.disabled},
            after={"roles": list(account.roles), "disabled": account.disabled,
                   "password_changed": bool(request.form.get("password"))},
        ))
        flash(f"Account {account.username} updated.", "success")
        return redirect("/users")

    @app.route(
        "/users/<username>/delete", methods=["POST"], endpoint="users_delete"
    )
    def users_delete(username: str):
        from founderos_atlas.access import UserConflictError

        principal = _actor()
        if principal is not None and (
            principal.username.casefold() == str(username).casefold()
        ):
            flash("You cannot delete the account you are signed in with.",
                  "error")
            return redirect("/users")
        store = cfg("ATLAS_USER_STORE")
        try:
            expected = int(request.form.get("expected_revision", "") or 0)
            removed = store.delete(username, expected_revision=expected)
        except UserConflictError as error:
            abort(409, description=str(error))
        if removed:
            cfg("ATLAS_SESSION_STORE").invalidate_user(username)
            _audit().append(_audit_event(
                category="user-account", operation="delete",
                subject=f"user:{username}",
            ))
            flash(f"Account {username} deleted and its sessions revoked.",
                  "success")
        else:
            flash("No such account.", "error")
        return redirect("/users")

    # -- workspace integrity ----------------------------------------------

    @app.route("/system/integrity")
    def system_integrity():
        from founderos_atlas.workspace.integrity import verify_workspace
        from founderos_atlas.workspace.migrations import (
            CURRENT_SCHEMA_VERSION, applied_version,
        )

        statuses = verify_workspace(_workspace_root())
        return render_template(
            "system_integrity.html",
            statuses=statuses,
            corrupt=[item for item in statuses if item.state == "corrupt"],
            schema_version=applied_version(_workspace_root()),
            schema_target=CURRENT_SCHEMA_VERSION,
        )

    # -- job cancellation --------------------------------------------------

    @app.route(
        "/api/discovery/jobs/<job_id>/cancel", methods=["POST"],
        endpoint="api_discovery_job_cancel",
    )
    def api_discovery_job_cancel(job_id: str):
        manager = cfg("ATLAS_JOB_MANAGER")
        job = manager.request_cancel(job_id)
        if job is None:
            return Response(
                json.dumps({"error": "no such job"}), status=404,
                mimetype="application/json",
            )
        _audit().append(_audit_event(
            category="discovery-job", operation="cancel",
            subject=f"job:{job_id}",
            after={"status": job.status,
                   "cancel_requested": job.cancel_requested},
        ))
        return Response(
            json.dumps(manager.snapshot(job)), mimetype="application/json"
        )

    # -- compass approval --------------------------------------------------

    @app.route(
        "/compass/<plan_id>/decision", methods=["POST"],
        endpoint="compass_approve",
    )
    def compass_approve(plan_id: str):
        from founderos_atlas.compass.service import (
            PlanConflictError, PlanRepository, decide_plan,
        )
        from datetime import datetime, timezone

        repository = PlanRepository(cfg("ATLAS_OUTPUT_DIR"))
        approve = str(request.form.get("decision") or "") == "approve"
        reason = str(request.form.get("reason") or "")
        principal = _actor()
        try:
            expected_raw = request.form.get("expected_revision", "")
            expected = int(expected_raw) if expected_raw != "" else None
            plan = repository.check_revision(plan_id, expected)
            if plan is None:
                flash("No such plan.", "error")
                return redirect("/compass")
            if plan.status == "in-review":
                from founderos_atlas.compass.lifecycle import decide_review

                decided = decide_review(
                    plan, approve=approve, actor=principal.username,
                    reason=reason,
                )
                repository.save(decided)
            else:
                decided = decide_plan(
                    repository, plan, approve=approve,
                    actor=principal.username, reason=reason,
                    decided_at=datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                )
        except PlanConflictError as error:
            abort(409, description=str(error))
        except ValueError as error:
            flash(str(error), "error")
            return redirect(f"/compass/{plan_id}")
        _audit().append(_audit_event(
            category="compass-plan",
            operation="approve" if approve else "reject",
            subject=f"plan:{plan_id}",
            before={"status": plan.status},
            after={"status": decided.status},
            reason=reason or None,
        ))
        flash(
            f"Plan {'approved' if approve else 'rejected'} — recorded in "
            "the audit log.",
            "success",
        )
        return redirect(f"/compass/{plan_id}")

    # -- notification emitters shared with routes --------------------------

    def notify_approval_requested(plan_id: str, title: str) -> None:
        _notifications().notify(
            kind=KIND_APPROVAL_REQUEST,
            title=f"Approval requested: {title}",
            detail="An analysed change plan awaits an approver's decision.",
            href=f"/compass/{plan_id}",
            audience="role:approver",
            correlation_id=getattr(g, "correlation_id", None),
            dedupe_key=plan_id,
        )

    app.config["ATLAS_NOTIFY_APPROVAL"] = notify_approval_requested
