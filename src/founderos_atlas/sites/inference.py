"""Multi-signal site inference. Honest about uncertainty by design.

Signal classes:

- **Explicit assignment** (user mapped this device to a site): decisive —
  assigned with high confidence, marked explicit.
- **Assigning signals** (hostname convention, seed-origin/profile hint):
  each votes for a site. One agreeing signal → low confidence; two or more
  agreeing → medium. Disagreeing assigning signals → *ambiguous*.
- **Corroborating signals** (management IP inside a site's declared range):
  never assign by themselves — a subnet is only one signal, and one
  supernet may span many sites. Corroboration raises the confidence of an
  existing assignment one step (low→medium, medium→high).

No assigning signal → *unknown*, with whatever corroborating evidence was
seen recorded for transparency.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from ipaddress import ip_address, ip_network

from .models import (
    ASSIGNMENT_AMBIGUOUS,
    ASSIGNMENT_ASSIGNED,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    SiteAssignment,
    SiteCatalog,
    SiteEvidence,
    unknown_assignment,
)


SIGNAL_EXPLICIT = "explicit-assignment"
SIGNAL_HOSTNAME = "hostname-convention"
SIGNAL_SEED_ORIGIN = "seed-origin"
SIGNAL_SUBNET = "subnet"

_STEP_UP = {CONFIDENCE_LOW: CONFIDENCE_MEDIUM, CONFIDENCE_MEDIUM: CONFIDENCE_HIGH,
            CONFIDENCE_HIGH: CONFIDENCE_HIGH}


class SiteInferenceEngine:
    """Evaluates the site of one device from catalog rules plus hints."""

    def __init__(self, catalog: SiteCatalog | None = None) -> None:
        self._catalog = catalog or SiteCatalog()

    def assign(
        self,
        *,
        hostname: str | None = None,
        management_ips: tuple[str, ...] = (),
        device_ids: tuple[str, ...] = (),
        profile_site_hints: tuple[str, ...] = (),
    ) -> SiteAssignment:
        """Weigh every signal for one device and conclude honestly.

        ``profile_site_hints`` are the site hints of the profiles that
        observed the device (seed origin) — an assigning but weak signal.
        """

        explicit = self._explicit(hostname, device_ids)
        if explicit is not None:
            return explicit

        assigning: list[SiteEvidence] = []
        corroborating: list[SiteEvidence] = []
        assigning.extend(self._hostname_votes(hostname))
        assigning.extend(self._seed_origin_votes(profile_site_hints))
        corroborating.extend(self._subnet_votes(management_ips))

        voted_sites = {evidence.site_id for evidence in assigning}
        if not voted_sites:
            # A subnet alone never forces a site assignment.
            return unknown_assignment(tuple(corroborating))
        if len(voted_sites) > 1:
            return SiteAssignment(
                status=ASSIGNMENT_AMBIGUOUS,
                site_id=None,
                confidence=None,
                explicit=False,
                evidence=tuple(assigning + corroborating),
            )
        site_id = next(iter(voted_sites))
        confidence = CONFIDENCE_LOW if len(assigning) == 1 else CONFIDENCE_MEDIUM
        agreeing_corroboration = [
            evidence for evidence in corroborating if evidence.site_id == site_id
        ]
        conflicting_corroboration = [
            evidence for evidence in corroborating if evidence.site_id != site_id
        ]
        if agreeing_corroboration and not conflicting_corroboration:
            confidence = _STEP_UP[confidence]
        return SiteAssignment(
            status=ASSIGNMENT_ASSIGNED,
            site_id=site_id,
            confidence=confidence,
            explicit=False,
            evidence=tuple(assigning + corroborating),
        )

    # -- signals ------------------------------------------------------------

    def _explicit(
        self, hostname: str | None, device_ids: tuple[str, ...]
    ) -> SiteAssignment | None:
        lowered = (hostname or "").strip().casefold()
        for site in self._catalog.sites:
            for device_id in device_ids:
                if device_id in site.explicit_device_ids:
                    return self._explicit_assignment(
                        site.site_id, f"device {device_id} is explicitly assigned"
                    )
            if lowered and any(
                lowered == name.strip().casefold()
                for name in site.explicit_hostnames
            ):
                return self._explicit_assignment(
                    site.site_id, f"hostname {hostname} is explicitly assigned"
                )
        return None

    @staticmethod
    def _explicit_assignment(site_id: str, detail: str) -> SiteAssignment:
        return SiteAssignment(
            status=ASSIGNMENT_ASSIGNED,
            site_id=site_id,
            confidence=CONFIDENCE_HIGH,
            explicit=True,
            evidence=(
                SiteEvidence(
                    signal=SIGNAL_EXPLICIT,
                    site_id=site_id,
                    detail=detail,
                    assigning=True,
                ),
            ),
        )

    def _hostname_votes(self, hostname: str | None) -> list[SiteEvidence]:
        lowered = (hostname or "").strip().casefold()
        if not lowered:
            return []
        votes: list[SiteEvidence] = []
        for site in self._catalog.sites:
            for pattern in site.hostname_patterns:
                if fnmatchcase(lowered, pattern.casefold()):
                    votes.append(
                        SiteEvidence(
                            signal=SIGNAL_HOSTNAME,
                            site_id=site.site_id,
                            detail=f"hostname matches convention {pattern!r}",
                            assigning=True,
                        )
                    )
                    break
        return votes

    def _seed_origin_votes(
        self, profile_site_hints: tuple[str, ...]
    ) -> list[SiteEvidence]:
        votes: list[SiteEvidence] = []
        seen: set[str] = set()
        for hint in profile_site_hints:
            cleaned = str(hint).strip()
            if not cleaned:
                continue
            site = self._catalog.get(cleaned)
            site_id = site.site_id if site is not None else None
            if site_id is None:
                # A hint naming an uncataloged site still counts as a vote
                # for that (implicitly defined) site id.
                from .models import site_id_for

                site_id = site_id_for(cleaned)
            if site_id in seen:
                continue
            seen.add(site_id)
            votes.append(
                SiteEvidence(
                    signal=SIGNAL_SEED_ORIGIN,
                    site_id=site_id,
                    detail=f"observed via a profile hinting site {cleaned!r}",
                    assigning=True,
                )
            )
        return votes

    def _subnet_votes(self, management_ips: tuple[str, ...]) -> list[SiteEvidence]:
        votes: list[SiteEvidence] = []
        for site in self._catalog.sites:
            for cidr in site.cidrs:
                network = ip_network(cidr, strict=False)
                for raw in management_ips:
                    try:
                        address = ip_address(raw)
                    except ValueError:
                        continue
                    if address in network:
                        votes.append(
                            SiteEvidence(
                                signal=SIGNAL_SUBNET,
                                site_id=site.site_id,
                                detail=f"{raw} is inside declared range {cidr}",
                                assigning=False,  # corroborating only, by principle
                            )
                        )
                        break
                else:
                    continue
                break
        return votes
