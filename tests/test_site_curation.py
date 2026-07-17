from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from founderos_atlas.demo import run_atlas_discovery_demo
from founderos_atlas.sites import (
    SITE_TYPE_INTERNET,
    SITE_TYPE_SITE,
    SITE_TYPE_WAN,
    Site,
    SiteCatalog,
    SiteOverrideCatalog,
    SiteOverrideConflictError,
    SiteOverrideRepository,
)
from founderos_atlas.visualization import TopologyRenderer
from founderos_atlas.visualization.stencils import stencil_data_uri


def test_site_type_is_backward_compatible_and_validated() -> None:
    legacy = Site.from_dict({"site_id": "hyd", "name": "Hyderabad"})
    assert legacy.site_type == SITE_TYPE_SITE
    assert Site(site_id="wan", name="WAN", site_type=SITE_TYPE_WAN).to_dict()[
        "site_type"
    ] == SITE_TYPE_WAN
    with pytest.raises(ValueError, match="site_type"):
        Site(site_id="bad", name="Bad", site_type="guess")


def test_override_persists_audits_conflicts_and_undoes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repository = SiteOverrideRepository(Path(tmp))
        catalog, assigned = repository.assign(
            site_id="beta",
            device_id="scope:router-1",
            hostname="router-1",
            management_ip="10.0.0.1",
            serial_number="ABC123",
            vendor="Cisco",
            reason="Confirmed by operator",
            expected_revision=0,
            occurred_at="2026-07-17T10:00:00+00:00",
        )

        assert catalog.revision == 1
        assert assigned.before_site_id is None
        assert repository.load().find(
            # A federated id still resolves through the durable serial.
            device_id="enterprise:different-id",
            serial_number="ABC123",
            vendor="cisco",
        ).site_id == "beta"
        assert repository.history()[0].reason == "Confirmed by operator"

        with pytest.raises(SiteOverrideConflictError):
            repository.assign(
                site_id="alpha", hostname="router-1", expected_revision=0
            )

        undone, event = repository.undo(
            subject_key=assigned.subject_key,
            expected_revision=1,
            occurred_at="2026-07-17T10:01:00+00:00",
        )
        assert undone.revision == 2
        assert undone.overrides == ()
        assert event.action == "undo"
        assert event.undoes_event_id == assigned.event_id


def test_renderer_applies_override_without_erasing_inference() -> None:
    snapshot = run_atlas_discovery_demo()[2]
    device = snapshot.devices[0]
    catalog = SiteCatalog(sites=(
        Site(
            site_id="alpha", name="Alpha",
            explicit_hostnames=(str(device["hostname"]),),
        ),
        Site(
            site_id="internet", name="Internet",
            site_type=SITE_TYPE_INTERNET,
        ),
    ))
    with tempfile.TemporaryDirectory() as tmp:
        overrides, _event = SiteOverrideRepository(Path(tmp)).assign(
            site_id="internet",
            device_id=str(device["device_id"]),
            hostname=str(device["hostname"]),
            management_ip=str(device["management_ip"]),
            serial_number=str(device["serial_number"]),
            vendor=str(device["vendor"]),
            expected_revision=0,
            occurred_at="2026-07-17T10:00:00+00:00",
        )

    renderer = TopologyRenderer(
        snapshot, site_catalog=catalog, site_overrides=overrides
    )
    elements = renderer.elements()
    site_view = renderer.site_view(elements)
    node = elements["nodes"][0]["data"]

    assert site_view["membership"][node["id"]] == "internet"
    assert node["site_assignment"]["source"] == "operator"
    assert node["site_assignment"]["inferred_site_id"] == "alpha"
    assert node["site_assignment"]["conflict"] is True
    internet = next(item for item in site_view["sites"] if item["site_id"] == "internet")
    assert internet["site_type"] == SITE_TYPE_INTERNET
    assert internet["stencil"] == stencil_data_uri("site-internet")


def test_explicit_unidentified_is_active_not_an_orphaned_override() -> None:
    snapshot = run_atlas_discovery_demo()[2]
    device = snapshot.devices[0]
    catalog = SiteCatalog(sites=(Site(site_id="alpha", name="Alpha"),))
    with tempfile.TemporaryDirectory() as tmp:
        overrides, _event = SiteOverrideRepository(Path(tmp)).assign(
            site_id="__none__",
            device_id=str(device["device_id"]),
            hostname=str(device["hostname"]),
            management_ip=str(device["management_ip"]),
            vendor=str(device["vendor"]),
            expected_revision=0,
        )
    renderer = TopologyRenderer(
        snapshot, site_catalog=catalog, site_overrides=overrides
    )
    elements = renderer.elements()
    renderer.site_view(elements)
    assignment = elements["nodes"][0]["data"]["site_assignment"]
    assert assignment["source"] == "operator"
    assert assignment["effective_site_id"] == "__none__"
    assert assignment["effective_site_name"] == "Site not identified"
    assert assignment["orphaned"] is False
