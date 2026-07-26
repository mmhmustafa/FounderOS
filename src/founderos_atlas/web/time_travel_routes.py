"""Discoverable, evidence-bounded Network Time Travel routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from founderos_atlas.history import (
    HistoryRepository,
    ReplayUnavailableError,
    TopologyReplayService,
)
from founderos_atlas.listing import paginate
from founderos_atlas.workspace import GLOBAL_SCOPE_ID


def register_time_travel_routes(
    app,
    *,
    scoped_context,
    aggregation_scopes,
) -> None:
    """Register replay routes using the established scope resolver."""

    from flask import (
        Response,
        flash,
        jsonify,
        render_template,
        request,
        url_for,
    )

    def _available_scopes(scopes, scope_id):
        candidates = (
            aggregation_scopes(scopes)
            if scope_id == GLOBAL_SCOPE_ID
            else (scopes[scope_id],)
        )
        result = []
        for scope in candidates:
            repository = HistoryRepository(scope.history_root)
            index = repository.load()
            if index.records or scope_id != GLOBAL_SCOPE_ID:
                result.append((scope, repository, index))
        return result

    def _selected_world():
        context, scopes, scope_id = scoped_context("history")
        available = _available_scopes(scopes, scope_id)
        selected = None
        requested = str(request.args.get("network") or "").strip()
        if requested:
            selected = next(
                (item for item in available if item[0].scope_id == requested),
                None,
            )
            if selected is None and not request.path.startswith("/api/"):
                flash(
                    "The requested network has no visible discovery history. "
                    "Showing the first available network instead.",
                    "warning",
                )
        if selected is None and available:
            selected = next(
                (item for item in available if len(item[2].records) >= 2),
                available[0],
            )
        return context, scope_id, available, selected

    def _record_options(repository, records):
        options = []
        for record in records:
            snapshot = repository.snapshot_path(record.record_id)
            options.append({
                **record.to_dict(),
                "snapshot_available": snapshot.is_file(),
                "label": (
                    f"{record.started_at} · {record.device_count} devices · "
                    f"{record.relationship_count} relationships"
                ),
            })
        return options

    def _selection(records):
        from_id = str(request.args.get("from") or "").strip()
        to_id = str(request.args.get("to") or "").strip()
        ids = {record.record_id for record in records}
        if from_id and from_id not in ids:
            raise ReplayUnavailableError(
                "the selected From discovery is not in this network"
            )
        if to_id and to_id not in ids:
            raise ReplayUnavailableError(
                "the selected To discovery is not in this network"
            )
        if not from_id and len(records) >= 2:
            from_id = records[1].record_id
        if not to_id and records:
            to_id = records[0].record_id
        return from_id, to_id

    def _compare(repository, records):
        try:
            from_id, to_id = _selection(records)
        except ReplayUnavailableError as error:
            return "", "", None, str(error)
        if not from_id or not to_id:
            return from_id, to_id, None, None
        try:
            comparison = TopologyReplayService(repository).compare(
                from_id, to_id
            )
            return from_id, to_id, comparison, None
        except ReplayUnavailableError as error:
            return from_id, to_id, None, str(error)

    def _viewer_url(repository, record_id: str) -> str | None:
        path = (
            repository.record_directory(record_id) / "atlas_topology.html"
        ).resolve()
        output = Path(app.config["ATLAS_OUTPUT_DIR"]).resolve()
        try:
            relative = path.relative_to(output)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return url_for("artifacts", name=relative.as_posix())

    def _filtered_changes(comparison):
        if comparison is None:
            return (), {"category": "", "q": ""}
        category = str(request.args.get("category") or "").strip()
        query = str(request.args.get("q") or "").strip()
        needle = query.casefold()
        rows = []
        for change in comparison.changes:
            row = change.to_dict()
            if category and row["category"] != category:
                continue
            if needle and needle not in " ".join(
                str(row.get(key) or "")
                for key in (
                    "category", "subject", "description", "severity",
                    "before", "after",
                )
            ).casefold():
                continue
            rows.append(row)
        return tuple(rows), {"category": category, "q": query}

    @app.route("/history/time-travel")
    def network_time_travel():
        context, active_scope, available, selected = _selected_world()
        if selected is None:
            return render_template(
                "time_travel.html",
                network_options=(),
                selected_network=None,
                records=(),
                comparison=None,
                page=paginate((), 1, 50),
                filters={"category": "", "q": ""},
                categories=(),
                selection={"from": "", "to": ""},
                viewers={"from": None, "to": None},
                error=None,
                query_string="",
                **context,
            )
        scope, repository, index = selected
        from_id, to_id, comparison, error = _compare(
            repository, index.records
        )
        if error:
            flash(error, "warning")
        changes, filters = _filtered_changes(comparison)
        try:
            page_number = max(1, int(request.args.get("page") or 1))
        except ValueError:
            page_number = 1
        page = paginate(changes, page_number, 50)
        query = {
            key: value for key, value in {
                "scope": active_scope,
                "network": scope.scope_id,
                "from": from_id,
                "to": to_id,
                "category": filters["category"],
                "q": filters["q"],
            }.items() if value
        }
        return render_template(
            "time_travel.html",
            network_options=[
                {
                    "scope_id": candidate.scope_id,
                    "label": candidate.label,
                    "records": len(candidate_index.records),
                }
                for candidate, _repository, candidate_index in available
            ],
            selected_network={
                "scope_id": scope.scope_id,
                "label": scope.label,
            },
            records=_record_options(repository, index.records),
            comparison=(
                comparison.to_dict() if comparison is not None else None
            ),
            page=page,
            filters=filters,
            categories=sorted(
                set(comparison.summary) if comparison is not None else ()
            ),
            selection={"from": from_id, "to": to_id},
            viewers={
                "from": _viewer_url(repository, from_id) if from_id else None,
                "to": _viewer_url(repository, to_id) if to_id else None,
            },
            error=error,
            query_string=urlencode(query),
            **context,
        )

    @app.route("/api/history/time-travel")
    def api_network_time_travel():
        _context, _active_scope, _available, selected = _selected_world()
        if selected is None:
            return jsonify(error="No discovery history is available."), 404
        _scope, repository, index = selected
        _from_id, _to_id, comparison, error = _compare(
            repository, index.records
        )
        if error:
            return jsonify(error=error), 400
        if comparison is None:
            return jsonify(
                error="At least two compatible discovery records are required."
            ), 400
        return jsonify(comparison=comparison.to_dict())

    @app.route("/history/time-travel/export.json")
    def network_time_travel_export():
        _context, _active_scope, _available, selected = _selected_world()
        if selected is None:
            return Response(
                json.dumps({"error": "No discovery history is available."}),
                status=404,
                content_type="application/json",
            )
        scope, repository, index = selected
        _from_id, _to_id, comparison, error = _compare(
            repository, index.records
        )
        if error or comparison is None:
            return Response(
                json.dumps({
                    "error": error or (
                        "At least two compatible discovery records are required."
                    )
                }),
                status=400,
                content_type="application/json",
            )
        payload: dict[str, Any] = {
            "schema_version": "1.0.0",
            "kind": "atlas-network-time-travel",
            "network": {
                "scope_id": scope.scope_id,
                "label": scope.label,
            },
            "redaction": (
                "Topology facts and immutable identifiers only. Raw command "
                "output, configuration text and credential material are not "
                "included."
            ),
            "comparison": comparison.to_dict(),
        }
        return Response(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            content_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition":
                    'attachment; filename="atlas-network-time-travel.json"'
            },
        )
