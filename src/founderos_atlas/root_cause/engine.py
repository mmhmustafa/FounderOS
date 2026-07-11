"""Root-cause orchestration: evidence -> graph -> hypotheses -> report.

``analyze`` works on artifact-shaped dicts, so the pipeline (live run) and
``analyze_record`` (historical replay from any archived discovery) produce
identical results from identical evidence — "what happened yesterday" is
just analysis over yesterday's stored artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

from founderos_atlas.history import HistoryRepository

from .correlation import correlate, hostname_for_ip, previous_adjacency
from .evidence import build_evidence
from .explanation import build_reasoning
from .hypothesis import generate_hypotheses, problem_subjects
from .models import RootCauseAnalysis, RootCauseReport
from .timeline import build_timeline


def analyze(
    *,
    generated_at: str,
    state_report: dict | None = None,
    topology_report: dict | None = None,
    config_report: dict | None = None,
    incident_report: dict | None = None,
    failed_details: tuple[tuple[str, str], ...] = (),
    previous_snapshot: dict | None = None,
    recurring_hosts: tuple[str, ...] = (),
    stale: bool = False,
) -> RootCauseReport:
    """Explain every observed problem in one discovery interval."""

    evidence = build_evidence(
        observed_at=generated_at,
        state_report=state_report,
        topology_report=topology_report,
        config_report=config_report,
        incident_report=incident_report,
        failed_details=failed_details,
    )
    graph = correlate(
        evidence,
        adjacency=previous_adjacency(previous_snapshot),
        ip_hostnames=hostname_for_ip(previous_snapshot),
    )
    evidence_by_id = {item.evidence_id: item for item in evidence}
    recurring = {host.casefold() for host in recurring_hosts}

    analyses: list[RootCauseAnalysis] = []
    for subject_kind, subject, anchor in problem_subjects(evidence):
        hypotheses = generate_hypotheses(
            subject_kind,
            subject,
            anchor,
            evidence,
            graph,
            recurring=any(
                device.casefold() in recurring for device in anchor.devices
            ),
            stale=stale,
        )
        if not hypotheses:
            continue
        primary, alternatives = hypotheses[0], hypotheses[1:]
        analyses.append(
            RootCauseAnalysis(
                subject=subject,
                subject_kind=subject_kind,
                problem=anchor.description,
                primary=primary,
                alternatives=alternatives,
                reasoning=build_reasoning(primary, anchor, evidence_by_id, graph),
                evidence_ids=tuple(
                    sorted(
                        set(primary.supporting)
                        | set(primary.contradicting)
                        | {anchor.evidence_id}
                    )
                ),
            )
        )
    analyses.sort(
        key=lambda item: (-item.primary.confidence, item.subject.casefold())
    )
    return RootCauseReport(
        generated_at=generated_at,
        evidence=evidence,
        timeline=build_timeline(evidence),
        analyses=tuple(analyses),
    )


def analyze_record(
    history_root: str | Path, record_id: str, *, generated_at: str | None = None
) -> RootCauseReport:
    """Historical replay: explain what happened in one archived discovery.

    Reads the artifacts preserved with that record — the same evidence the
    live run saw — so the explanation of "yesterday" is exactly what Atlas
    would have concluded yesterday.
    """

    repository = HistoryRepository(history_root)
    record_dir = repository.record_directory(record_id)
    index = repository.load()
    record = next(
        (item for item in index.records if item.record_id == record_id), None
    )
    observed_at = (
        record.completed_at if record is not None else (generated_at or "unrecorded")
    )
    previous_snapshot = None
    ordered = list(index.records)
    if record is not None and record in ordered:
        position = ordered.index(record)
        if position + 1 < len(ordered):
            previous_snapshot = _read_json(
                repository.record_directory(ordered[position + 1].record_id)
                / "topology_snapshot.json"
            )
    snapshot = _read_json(record_dir / "topology_snapshot.json") or {}
    failed_hosts = tuple(
        str(host) for host in (snapshot.get("metadata") or {}).get("failed_hosts") or ()
    )
    return analyze(
        generated_at=generated_at or observed_at,
        state_report=_read_json(record_dir / "state_change_report.json"),
        topology_report=_read_json(record_dir / "change_report.json"),
        config_report=_read_json(record_dir / "config_change_report.json"),
        incident_report=_read_json(record_dir / "incident_report.json"),
        failed_details=tuple((host, "failed discovery") for host in failed_hosts),
        previous_snapshot=previous_snapshot,
    )


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
