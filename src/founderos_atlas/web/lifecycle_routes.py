"""Routes connecting detection → investigation → prediction → execution.

Registered from ``register_routes`` with a namespace of the app's scope
helpers, so incidents, Compass lifecycle, Advisor conversations, and
the async entity APIs share the same scope resolution, actor
attribution, audit log, and CSRF/RBAC gates as everything else.
"""

from __future__ import annotations

import json
from pathlib import Path


def register_lifecycle_routes(app, h) -> None:
    from flask import (
        Response, abort, flash, g, redirect, render_template, request, url_for,
    )

    from founderos_atlas.audit import AuditEvent, AuditLog
    from founderos_atlas.incidents.records import (
        CASE_STATUSES,
        IncidentCaseRepository,
        IncidentConflictError,
        SEVERITIES,
    )

    def _cases() -> IncidentCaseRepository:
        return IncidentCaseRepository(h.cfg("ATLAS_WORKSPACE_ROOT"))

    def _audit_log() -> AuditLog:
        return AuditLog(h.cfg("ATLAS_WORKSPACE_ROOT"))

    def _correlation() -> str | None:
        return getattr(g, "correlation_id", None)

    # -- async entity APIs (the pickers' backend) --------------------------

    @app.route("/api/entities")
    def api_entities():
        """Search devices/sites in the active scope: ?q=&kind=&limit=.

        Returns at most ``limit`` matches — the DOM never receives the
        whole estate.
        """

        scopes = h.known_scopes()
        scope_id = h.active_scope_id(scopes)
        query = str(request.args.get("q") or "").strip().casefold()
        kind = str(request.args.get("kind") or "device")
        limit = max(1, min(int(request.args.get("limit", 12) or 12), 50))
        graph, _snapshot, _profiles = h.scoped_world(scope_id)
        results: list[dict] = []
        if kind == "site":
            from founderos_atlas.sites import SiteCatalogRepository

            catalog = SiteCatalogRepository(h.cfg("ATLAS_WORKSPACE_ROOT")).load()
            for site in catalog.sites:
                if not query or query in site.name.casefold() or (
                    query in site.site_id.casefold()
                ):
                    results.append({
                        "value": site.site_id, "label": site.name,
                        "detail": site.site_id,
                    })
        else:
            devices = getattr(graph, "devices", ()) or ()
            for device in devices:
                hostname = str(getattr(device, "hostname", "") or "")
                if not hostname:
                    continue
                management = str(getattr(device, "management_ip", "") or "")
                platform = str(getattr(device, "platform", "") or "")
                haystack = f"{hostname} {management} {platform}".casefold()
                if not query or query in haystack:
                    results.append({
                        "value": hostname, "label": hostname,
                        "detail": " · ".join(
                            part for part in (management, platform) if part
                        ),
                    })
        results.sort(key=lambda item: item["label"].casefold())
        return Response(
            json.dumps({"results": results[:limit],
                        "total": len(results)}),
            mimetype="application/json",
        )

    @app.route("/api/device-interfaces")
    def api_device_interfaces():
        """Interfaces of ONE device, fetched when the device is chosen —
        never preloaded for the whole estate."""

        from founderos_atlas.web.models import prediction_targets

        scopes = h.known_scopes()
        scope_id = h.active_scope_id(scopes)
        hostname = str(request.args.get("device") or "").strip()
        if not hostname:
            return Response(
                json.dumps({"results": []}), mimetype="application/json"
            )
        _graph, snapshot, _profiles = h.scoped_world(scope_id)
        needle = hostname.casefold()
        results = []
        for device in prediction_targets(snapshot):
            if str(device.get("hostname", "")).casefold() != needle:
                continue
            for interface in device.get("interfaces") or ():
                # The label carries the same evidence context the old
                # dropdown did: state, address, description, neighbor.
                label = str(interface.get("label") or interface.get("name"))
                name = str(interface.get("name"))
                detail = label
                if detail.startswith(name):
                    detail = detail[len(name):].strip(" —·-")
                results.append({
                    "value": name, "label": name,
                    "detail": detail or "state unrecorded",
                })
            break
        return Response(
            json.dumps({"results": results, "total": len(results)}),
            mimetype="application/json",
        )

    # -- incident cases ----------------------------------------------------

    @app.route("/incidents/case/<case_id>")
    def incident_case_page(case_id: str):
        context, scopes, _scope_id = h.scoped_context("incidents")
        case = _cases().get(case_id)
        if case is None:
            flash("No such incident case.", "error")
            return redirect(url_for("incidents"))
        scope = scopes.get(case.scope_id)
        report = (
            h.load_json(scope.output_dir / "incident_report.json")
            if scope is not None else None
        )
        # Only show the report that belongs to this case; a newer
        # investigation in the same scope replaces the artifact on disk.
        if report and case.report_incident_id and (
            report.get("incident_id") != case.report_incident_id
        ):
            report = None
        root_cause = (
            (h.load_json(scope.output_dir / "root_cause_report.json") or {})
            if scope is not None else {}
        ).get("most_important")
        case_events = [
            event for event in _audit_log().events(category="incident")
            if event.subject == f"incident:{case.case_id}"
        ]
        case_events.sort(key=lambda event: event.occurred_at)
        from founderos_atlas.compass.service import PlanRepository

        plans = {
            plan.plan_id: plan.to_dict()
            for plan in PlanRepository(h.cfg("ATLAS_OUTPUT_DIR")).list_plans()
            if plan.plan_id in case.linked_plans
            or plan.incident_ref == case.case_id
        }
        return render_template(
            "incident_case.html",
            case=case,
            case_revision=_cases().revision(),
            report=report,
            root_cause=root_cause,
            case_events=case_events,
            linked_plans=list(plans.values()),
            severities=SEVERITIES,
            statuses=CASE_STATUSES,
            artifact_prefix=h.artifact_prefix(scope) if scope else "",
            **context,
        )

    @app.route("/incidents/case/<case_id>/action", methods=["POST"])
    def incident_case_action(case_id: str):
        repo = _cases()
        action = str(request.form.get("action") or "")
        actor = h.current_actor()
        raw = request.form.get("expected_revision", "")
        expected = int(raw) if raw.strip().isdigit() else None
        try:
            if action == "acknowledge":
                repo.acknowledge(case_id, actor=actor,
                                 expected_revision=expected)
                flash("Incident acknowledged.", "success")
            elif action == "assign":
                owner = str(request.form.get("owner") or "")
                repo.assign(case_id, owner=owner, actor=actor,
                            expected_revision=expected)
                try:
                    from founderos_atlas.notifications import (
                        KIND_INCIDENT, NotificationStore,
                    )

                    case = repo.get(case_id)
                    NotificationStore(h.cfg("ATLAS_WORKSPACE_ROOT")).notify(
                        kind=KIND_INCIDENT,
                        title=f"Incident assigned to you: {case.title}",
                        detail=f"Assigned by {actor}.",
                        href=f"/incidents/case/{case_id}",
                        audience=owner.strip(),
                        correlation_id=_correlation(),
                    )
                except OSError:
                    pass
                flash(f"Incident assigned to {owner}.", "success")
            elif action == "annotate":
                repo.annotate(case_id, text=str(request.form.get("text") or ""),
                              actor=actor, expected_revision=expected)
                flash("Note added.", "success")
            elif action == "suppress":
                repo.suppress(case_id, reason=str(request.form.get("reason") or ""),
                              actor=actor, expected_revision=expected)
                flash("Incident suppressed — retained, hidden by default.",
                      "success")
            elif action == "resolve":
                repo.resolve(case_id,
                             resolution=str(request.form.get("resolution") or ""),
                             actor=actor, expected_revision=expected)
                flash("Incident resolved.", "success")
            elif action == "reopen":
                repo.reopen(case_id, reason=str(request.form.get("reason") or ""),
                            actor=actor, expected_revision=expected)
                flash("Incident reopened.", "success")
            elif action == "severity":
                repo.set_severity(
                    case_id, severity=str(request.form.get("severity") or ""),
                    actor=actor, expected_revision=expected,
                )
                flash("Severity updated.", "success")
            else:
                flash("Unknown incident action.", "error")
        except IncidentConflictError as error:
            abort(409, description=str(error))
        except ValueError as error:
            flash(str(error), "error")
        return redirect(
            request.form.get("next") or url_for("incident_case_page",
                                                case_id=case_id)
        )

    @app.route("/incidents/case/<case_id>/link", methods=["POST"])
    def incident_case_link(case_id: str):
        repo = _cases()
        try:
            repo.link(
                case_id,
                kind=str(request.form.get("kind") or ""),
                value=str(request.form.get("value") or "").strip(),
                actor=h.current_actor(),
                correlation_id=_correlation(),
            )
            flash("Linked to the incident.", "success")
        except ValueError as error:
            flash(str(error), "error")
        return redirect(
            request.form.get("next") or url_for("incident_case_page",
                                                case_id=case_id)
        )

    # -- compass lifecycle -------------------------------------------------

    def _plan_repo():
        from founderos_atlas.compass.service import PlanRepository

        return PlanRepository(h.cfg("ATLAS_OUTPUT_DIR"))

    def _load_plan(repository, plan_id: str):
        from founderos_atlas.compass.service import PlanConflictError

        raw = request.form.get("expected_revision", "")
        expected = int(raw) if raw.strip().isdigit() else None
        try:
            plan = repository.check_revision(plan_id, expected)
        except PlanConflictError as error:
            abort(409, description=str(error))
        if plan is None:
            flash("That maintenance plan no longer exists.", "error")
            return None
        return plan

    def _plan_audit(operation: str, plan, *, reason: str | None = None,
                    after: dict | None = None) -> None:
        _audit_log().append(AuditEvent.create(
            category="compass-plan", operation=operation,
            subject=f"plan:{plan.plan_id}", actor=h.current_actor(),
            after=after or {"status": plan.status}, reason=reason,
            correlation_id=_correlation(),
        ))

    def _back(plan_id: str):
        return redirect(url_for("compass_plan_page", plan_id=plan_id))

    @app.route("/compass/<plan_id>/readiness", methods=["POST"])
    def compass_readiness(plan_id: str):
        from founderos_atlas.compass.lifecycle import (
            PlanLifecycleError, update_readiness,
        )

        repository = _plan_repo()
        plan = _load_plan(repository, plan_id)
        if plan is None:
            return redirect(url_for("compass_page"))

        def lines(name):
            raw = request.form.get(name)
            if raw is None:
                return None
            return [line for line in raw.splitlines() if line.strip()]

        try:
            updated = update_readiness(
                plan,
                rollback_plan=request.form.get("rollback_plan"),
                success_criteria=lines("success_criteria"),
                reviewers=lines("reviewers"),
                window_start=request.form.get("window_start"),
                window_end=request.form.get("window_end"),
                pre_checks=lines("pre_checks"),
                post_checks=lines("post_checks"),
            )
        except PlanLifecycleError as error:
            flash(str(error), "error")
            return _back(plan_id)
        repository.save(updated)
        _plan_audit("readiness-update", updated)
        flash("Readiness details saved.", "success")
        return _back(plan_id)

    @app.route("/compass/<plan_id>/reorder", methods=["POST"])
    def compass_reorder(plan_id: str):
        from founderos_atlas.compass.lifecycle import (
            PlanLifecycleError, reorder_change,
        )

        repository = _plan_repo()
        plan = _load_plan(repository, plan_id)
        if plan is None:
            return redirect(url_for("compass_page"))
        try:
            updated = reorder_change(
                plan, str(request.form.get("change_id") or ""),
                1 if request.form.get("direction") == "down" else -1,
            )
        except PlanLifecycleError as error:
            flash(str(error), "error")
            return _back(plan_id)
        repository.save(updated)
        _plan_audit("reorder", updated)
        return _back(plan_id)

    @app.route("/compass/<plan_id>/dependencies", methods=["POST"])
    def compass_dependencies(plan_id: str):
        from founderos_atlas.compass.lifecycle import (
            PlanLifecycleError, set_dependencies,
        )

        repository = _plan_repo()
        plan = _load_plan(repository, plan_id)
        if plan is None:
            return redirect(url_for("compass_page"))
        try:
            updated = set_dependencies(
                plan, str(request.form.get("change_id") or ""),
                depends_on=request.form.getlist("depends_on"),
                concurrency_group=request.form.get("concurrency_group"),
            )
        except PlanLifecycleError as error:
            flash(str(error), "error")
            return _back(plan_id)
        repository.save(updated)
        _plan_audit("dependencies", updated)
        flash("Dependencies updated.", "success")
        return _back(plan_id)

    @app.route("/compass/<plan_id>/submit", methods=["POST"])
    def compass_submit(plan_id: str):
        from founderos_atlas.compass.lifecycle import (
            PlanLifecycleError, submit_for_review,
        )

        repository = _plan_repo()
        plan = _load_plan(repository, plan_id)
        if plan is None:
            return redirect(url_for("compass_page"))
        try:
            updated = submit_for_review(plan)
        except PlanLifecycleError as error:
            flash(str(error), "error")
            return _back(plan_id)
        repository.save(updated)
        _plan_audit("submit-for-review", updated)
        notify = app.config.get("ATLAS_NOTIFY_APPROVAL")
        if notify is not None:
            notify(plan_id, plan.title)
        flash("Plan submitted for review — approvers have been notified.",
              "success")
        return _back(plan_id)

    @app.route("/compass/<plan_id>/schedule", methods=["POST"])
    def compass_schedule(plan_id: str):
        from founderos_atlas.compass.lifecycle import (
            PlanLifecycleError, schedule,
        )

        repository = _plan_repo()
        plan = _load_plan(repository, plan_id)
        if plan is None:
            return redirect(url_for("compass_page"))
        try:
            updated = schedule(
                plan,
                window_start=str(request.form.get("window_start") or ""),
                window_end=str(request.form.get("window_end") or ""),
            )
        except PlanLifecycleError as error:
            flash(str(error), "error")
            return _back(plan_id)
        repository.save(updated)
        _plan_audit("schedule", updated, after={
            "status": updated.status, "window_start": updated.window_start,
            "window_end": updated.window_end,
        })
        flash("Plan scheduled.", "success")
        return _back(plan_id)

    @app.route("/compass/<plan_id>/execution", methods=["POST"])
    def compass_execution(plan_id: str):
        from founderos_atlas.compass import lifecycle

        repository = _plan_repo()
        plan = _load_plan(repository, plan_id)
        if plan is None:
            return redirect(url_for("compass_page"))
        actor = h.current_actor()
        action = str(request.form.get("action") or "")
        note = str(request.form.get("note") or "").strip()
        try:
            if action == "start":
                updated = lifecycle.start_execution(plan, actor=actor)
            elif action == "check":
                updated = lifecycle.record_check(
                    plan,
                    phase=str(request.form.get("phase") or ""),
                    check_id=str(request.form.get("check_id") or ""),
                    passed=request.form.get("passed") == "1",
                    actor=actor, note=note,
                )
            elif action == "checkpoint":
                updated = lifecycle.checkpoint_change(
                    plan,
                    change_id=str(request.form.get("change_id") or ""),
                    outcome=str(request.form.get("outcome") or ""),
                    actor=actor, note=note,
                )
            elif action == "complete":
                updated = lifecycle.complete(plan, actor=actor, note=note)
            elif action == "fail":
                updated = lifecycle.fail(plan, actor=actor, note=note)
            elif action == "rollback":
                updated = lifecycle.rollback(plan, actor=actor, note=note)
            elif action == "cancel":
                updated = lifecycle.cancel(plan, actor=actor, reason=note)
            else:
                flash("Unknown execution action.", "error")
                return _back(plan_id)
        except lifecycle.PlanLifecycleError as error:
            flash(str(error), "error")
            return _back(plan_id)
        repository.save(updated)
        _plan_audit(f"execution-{action}", updated, reason=note or None)
        # Terminal states feed evidence back to the incident this plan serves.
        if updated.incident_ref and updated.status != plan.status:
            try:
                _cases().annotate(
                    updated.incident_ref,
                    text=(
                        f"Compass plan {plan_id} is now {updated.status}"
                        + (f": {note}" if note else ".")
                    ),
                    actor=actor,
                )
            except ValueError:
                pass
        flash(f"Recorded: {action}.", "success")
        return _back(plan_id)

    @app.route("/compass/<plan_id>/cab.md")
    def compass_cab_export(plan_id: str):
        from founderos_atlas.compass.lifecycle import cab_export_markdown

        repository = _plan_repo()
        plan, assessment = repository.get(plan_id)
        if plan is None:
            abort(404)
        _plan_audit("cab-export", plan)
        response = Response(
            cab_export_markdown(plan, assessment), mimetype="text/markdown"
        )
        response.headers["Content-Disposition"] = (
            f'attachment; filename="cab-{plan_id}.md"'
        )
        return response

    # -- advisor conversations and feedback --------------------------------

    def _conversations():
        from founderos_atlas.advisor import ConversationRepository

        return ConversationRepository(h.output_dir())

    @app.route("/advisor/feedback", methods=["POST"])
    def advisor_feedback():
        helpful = request.form.get("helpful") == "1"
        question = str(request.form.get("question") or "")[:300]
        note = str(request.form.get("note") or "").strip()[:500]
        feedback_path = (
            Path(h.cfg("ATLAS_WORKSPACE_ROOT")) / "advisor-feedback.jsonl"
        )
        feedback_path.parent.mkdir(parents=True, exist_ok=True)
        with feedback_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "at": h.now_iso(), "actor": h.current_actor(),
                "question": question, "helpful": helpful, "note": note,
            }, sort_keys=True) + "\n")
        _audit_log().append(AuditEvent.create(
            category="advisor", operation="feedback",
            subject="advisor:answer", actor=h.current_actor(),
            after={"helpful": helpful}, reason=note or None,
            correlation_id=_correlation(),
        ))
        flash("Feedback recorded — thank you.", "success")
        return redirect(request.form.get("next") or "/advisor")

    @app.route("/advisor/conversations/<int:index>/delete", methods=["POST"])
    def advisor_conversation_delete(index: int):
        from .confirmation import require_confirmation

        entry = _conversations().get(index)
        question = (
            (entry or {}).get("label")
            or ((entry or {}).get("response") or {}).get("question")
            or f"conversation {index}"
        )
        confirmation = require_confirmation(
            title="Delete conversation",
            detail=f"This deletes the Advisor conversation {question!r}.",
            consequence="The conversation and its citations are removed "
                        "from the Advisor history.",
        )
        if confirmation is not None:
            return confirmation
        if _conversations().delete(index):
            _audit_log().append(AuditEvent.create(
                category="advisor", operation="delete-conversation",
                subject=f"advisor:conversation:{index}",
                actor=h.current_actor(), correlation_id=_correlation(),
            ))
            flash("Conversation deleted.", "success")
        else:
            flash("No such conversation.", "error")
        return redirect("/advisor")

    @app.route("/advisor/conversations/<int:index>/rename", methods=["POST"])
    def advisor_conversation_rename(index: int):
        label = str(request.form.get("label") or "")
        if _conversations().rename(index, label):
            flash("Conversation renamed.", "success")
        else:
            flash("A non-empty name is required.", "error")
        return redirect("/advisor")

    @app.route("/advisor/conversations/<int:index>/export")
    def advisor_conversation_export(index: int):
        entry = _conversations().get(index)
        if entry is None:
            abort(404)
        response = Response(
            json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False),
            mimetype="application/json",
        )
        response.headers["Content-Disposition"] = (
            f'attachment; filename="advisor-conversation-{index}.json"'
        )
        return response

    # -- path comparison ---------------------------------------------------

    @app.route("/paths/compare")
    def paths_compare():
        context, scopes, scope_id = h.scoped_context("paths")
        investigations = h.past_path_investigations(scopes, scope_id)

        def pick(name):
            raw = str(request.args.get(name) or "").strip()
            if raw.isdigit() and int(raw) < len(investigations):
                return investigations[int(raw)]
            return None

        left, right = pick("left"), pick("right")
        differences: list[str] = []
        if left and right:
            if left.get("status") != right.get("status"):
                differences.append(
                    f"Outcome changed: {left.get('status')} → "
                    f"{right.get('status')}."
                )
            left_path = tuple(left.get("path") or ())
            right_path = tuple(right.get("path") or ())
            if left_path != right_path:
                differences.append(
                    "The hop sequence differs: "
                    f"{' → '.join(left_path) or 'none'} vs "
                    f"{' → '.join(right_path) or 'none'}."
                )
            if not differences:
                differences.append(
                    "Same outcome and same hop sequence — the change is in "
                    "the per-hop evidence below, if anywhere."
                )
        return render_template(
            "paths_compare.html",
            investigations=investigations,
            left=left, right=right, differences=differences,
            **context,
        )
