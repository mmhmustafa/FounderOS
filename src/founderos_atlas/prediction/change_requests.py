"""Open change-type registry: what kinds of change Atlas can reason about.

Change types are registered, never hardcoded into the pipeline. Each spec
carries the metadata every engine needs (category, default reversibility);
registering a new type — "disable-hsrp", "modify-security-group",
"restart-kubernetes-cni" — requires no change to any model or the
simulator. Unregistered types still predict honestly (low confidence,
explicit unknowns) rather than failing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChangeTypeSpec:
    name: str
    category: str            # interface, routing, gateway, platform, policy, ...
    reversible_by_default: bool
    description: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "reversible_by_default": self.reversible_by_default,
            "description": self.description,
        }


_REGISTRY: dict[str, ChangeTypeSpec] = {}


def register_change_type(spec: ChangeTypeSpec) -> None:
    _REGISTRY[spec.name] = spec


def change_type(name: str) -> ChangeTypeSpec | None:
    return _REGISTRY.get(name)


def known_change_types() -> tuple[ChangeTypeSpec, ...]:
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))


# -- the built-in vocabulary (extensible at runtime) --------------------------

register_change_type(
    ChangeTypeSpec(
        name="shutdown-interface",
        category="interface",
        reversible_by_default=True,
        description="Administratively shut an interface.",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="remove-vlan",
        category="switching",
        reversible_by_default=True,
        description="Remove a VLAN from a device.",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="delete-route",
        category="routing",
        reversible_by_default=True,
        description="Delete a static route or routing statement.",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="modify-acl",
        category="policy",
        reversible_by_default=True,
        description="Change an access control list.",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="disable-protocol",
        category="protocol",
        reversible_by_default=True,
        description="Disable a routing or gateway protocol (OSPF, HSRP, ...).",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="reboot-device",
        category="platform",
        reversible_by_default=False,  # you cannot un-reboot
        description="Reload a device.",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="shutdown-device",
        category="platform",
        # A shutdown is undone by powering the device back on — but not by
        # the automation, and not on its own, so it is not "reversible" in
        # the sense the pipeline means (a change it can roll back itself).
        reversible_by_default=False,
        description="Power a device down (stays down until brought back).",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="decommission-device",
        category="platform",
        reversible_by_default=False,  # a removal is not undone by automation
        description="Permanently remove a device from service.",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="link-failure",
        category="physical",
        # A cut cable or dead optic is fixed by re-cabling, not by rolling a
        # config back — so, like a reboot, not reversible in the pipeline's
        # sense. It is also not a planned change but a failure to rehearse.
        reversible_by_default=False,
        description="A physical link fails (cut cable, dead optic).",
    )
)
register_change_type(
    ChangeTypeSpec(
        name="upgrade-firmware",
        category="platform",
        reversible_by_default=False,
        description="Upgrade the operating system image.",
    )
)
