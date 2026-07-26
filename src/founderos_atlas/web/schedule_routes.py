"""Administration routes for durable discovery schedules and quiet windows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def register_schedule_routes(app) -> None:
    from flask import flash, g, redirect, render_template, request, url_for

    from founderos_atlas.scheduling import (
        MISFIRE_RUN_ONCE,
        RECURRENCE_INTERVAL,
        ScheduleConflictError,
        ScheduleStore,
        resolve_local_datetime,
    )

    def store() -> ScheduleStore:
        return ScheduleStore(Path(app.config["ATLAS_WORKSPACE_ROOT"]))

    def actor() -> str:
        principal = getattr(g, "principal", None)
        return principal.username if principal else "local-operator"

    def revision() -> int:
        raw = str(request.form.get("expected_revision") or "")
        if not raw.isdigit():
            raise ScheduleConflictError(
                "The schedule page is stale or incomplete. Reload and retry."
            )
        return int(raw)

    def aware_local(value: str, timezone_name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).strip())
        except ValueError as error:
            raise ValueError("Enter a valid date and time.") from error
        return resolve_local_datetime(parsed, timezone_name)

    @app.route("/schedules")
    def schedules_page():
        repository = store()
        try:
            schedules = repository.schedules()
            runs = repository.runs(limit=30)
            maintenance_windows = repository.maintenance_windows()
            schedule_revision = repository.revision()
            catalog_error = None
        except (OSError, ValueError) as error:
            schedules = []
            runs = []
            maintenance_windows = []
            schedule_revision = 0
            catalog_error = (
                "The schedule catalog could not be read safely. Atlas did "
                "not overwrite it; open System Integrity for recovery steps "
                f"({type(error).__name__})."
            )
        return render_template(
            "schedules.html",
            active="discover",
            active_group="setup",
            schedules=schedules,
            runs=runs,
            maintenance_windows=maintenance_windows,
            schedule_revision=schedule_revision,
            catalog_error=catalog_error,
            profiles=app.config["ATLAS_PROFILE_SERVICE"].list_profiles(),
        )

    @app.route("/schedules", methods=["POST"])
    def schedules_create():
        timezone_name = str(request.form.get("timezone_name") or "UTC")
        try:
            profile_id = str(request.form.get("profile_id") or "")
            known_profiles = {
                item.profile_id
                for item in app.config[
                    "ATLAS_PROFILE_SERVICE"
                ].list_profiles()
            }
            if profile_id not in known_profiles:
                raise ValueError(
                    "Select an active discovery profile."
                )
            store().create_schedule(
                profile_id=profile_id,
                name=str(request.form.get("name") or ""),
                recurrence=str(
                    request.form.get("recurrence") or RECURRENCE_INTERVAL
                ),
                timezone_name=timezone_name,
                first_run_at=aware_local(
                    str(request.form.get("first_run_at") or ""),
                    timezone_name,
                ),
                interval_minutes=(
                    int(request.form["interval_minutes"])
                    if request.form.get("interval_minutes") else None
                ),
                daily_time=str(request.form.get("daily_time") or "") or None,
                misfire_policy=str(
                    request.form.get("misfire_policy") or MISFIRE_RUN_ONCE
                ),
                max_retries=max(
                    0, min(10, int(request.form.get("max_retries") or 0))
                ),
                retry_delay_minutes=max(
                    1,
                    min(
                        1440,
                        int(request.form.get("retry_delay_minutes") or 5),
                    ),
                ),
                actor=actor(),
                expected_revision=revision(),
            )
            flash("Discovery schedule created.", "success")
        except (ScheduleConflictError, ValueError) as error:
            flash(str(error), "error")
        return redirect(url_for("schedules_page"))

    @app.route("/schedules/<schedule_id>/state", methods=["POST"])
    def schedules_state(schedule_id: str):
        try:
            store().set_enabled(
                schedule_id,
                str(request.form.get("enabled") or "") == "1",
                actor=actor(),
                expected_revision=revision(),
            )
            flash("Schedule updated.", "success")
        except (ScheduleConflictError, ValueError) as error:
            flash(str(error), "error")
        return redirect(url_for("schedules_page"))

    @app.route("/schedules/maintenance", methods=["POST"])
    def maintenance_create():
        timezone_name = str(request.form.get("timezone_name") or "UTC")
        try:
            scope_type = str(request.form.get("scope_type") or "global")
            scope_id = str(request.form.get("scope_id") or "") or None
            if scope_type == "profile":
                known_profiles = {
                    item.profile_id
                    for item in app.config[
                        "ATLAS_PROFILE_SERVICE"
                    ].list_profiles()
                }
                if scope_id not in known_profiles:
                    raise ValueError(
                        "Select an active discovery profile for this window."
                    )
            store().add_maintenance_window(
                name=str(request.form.get("name") or ""),
                starts_at=aware_local(
                    str(request.form.get("starts_at") or ""), timezone_name
                ),
                ends_at=aware_local(
                    str(request.form.get("ends_at") or ""), timezone_name
                ),
                timezone_name=timezone_name,
                scope_type=scope_type,
                scope_id=scope_id,
                suppress_notifications=(
                    request.form.get("suppress_notifications") == "1"
                ),
                reason=str(request.form.get("reason") or ""),
                actor=actor(),
                expected_revision=revision(),
            )
            flash("Maintenance window created.", "success")
        except (ScheduleConflictError, ValueError) as error:
            flash(str(error), "error")
        return redirect(url_for("schedules_page"))
