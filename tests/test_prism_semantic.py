"""PR-166.2 — PRISM Semantic Redaction.

The claim under test: PRISM can protect an identifier without
destroying the meaning of the sentence it appears in, and the thing an
authorised operator reads is not the thing the provider received.

The tests are organised as the spec is:

* alias generation from metadata Atlas ALREADY HAS (never invented)
* alias stability and repeated references
* the three privacy profiles
* the operator's view, and its RBAC
* the transparency record
* the audit record
* regression: nothing about secrets got weaker
"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from founderos_atlas.prism import presentation, semantic
from founderos_atlas.prism.config import PrismConfig, PrismConfigRepository
from founderos_atlas.prism.redaction import RedactionPolicy, redact


# -- doubles ----------------------------------------------------------------
#
# Shaped like the enterprise graph, carrying only what alias generation
# reads. A real graph is exercised by the web tests.

@dataclass
class FakeSite:
    label: str = "unknown"


@dataclass
class FakeDevice:
    enterprise_id: str
    hostname: str
    platform: str = ""
    vendor: str = ""
    os_version: str = ""
    site: FakeSite = field(default_factory=FakeSite)


@dataclass
class FakeGraph:
    devices: tuple = ()
    interfaces: dict = field(default_factory=dict)
    attributes: dict = field(default_factory=dict)


def estate() -> FakeGraph:
    return FakeGraph(devices=(
        FakeDevice("d1", "edge-mumbai-core-01", "ISR4451",
                   site=FakeSite("mumbai")),
        FakeDevice("d2", "hyd-border-fw-02", "ASA5525",
                   site=FakeSite("hyderabad")),
        FakeDevice("d3", "chennai-access-sw-07", "C9300",
                   site=FakeSite("chennai")),
        FakeDevice("d4", "edge-mumbai-core-02", "ISR4451",
                   site=FakeSite("mumbai")),
        FakeDevice("d5", "zz11", site=FakeSite("unknown")),
    ))


def book_for(profile_key: str, graph: FakeGraph | None = None):
    profile = semantic.profile(profile_key)
    return semantic.build_alias_book(
        graph or estate(), active_profile=profile
    ), profile


def policy_for(profile) -> RedactionPolicy:
    return RedactionPolicy.from_names(profile.optional_rules())


def scrub(text: str, profile_key: str, graph: FakeGraph | None = None):
    book, profile = book_for(profile_key, graph)
    safe, report = redact(text, policy_for(profile), aliases=book)
    return safe, report, book, profile


# -- Part 1: aliases from metadata Atlas already has ------------------------

class SemanticAliasGenerationTests(unittest.TestCase):
    """An alias must be readable, and every word in it must be a fact."""

    def test_alias_names_site_role_and_device_kind(self) -> None:
        book, _ = book_for(semantic.PROFILE_CLOUD)
        entry = book.for_original("edge-mumbai-core-01")
        self.assertEqual(entry.alias, "Mumbai Core Router")

    def test_device_kind_comes_from_atlas_own_role_classification(self) -> None:
        """Not from the hostname. The platform model IS the evidence."""

        book, _ = book_for(semantic.PROFILE_CLOUD)
        firewall = book.for_original("hyd-border-fw-02")
        switch = book.for_original("chennai-access-sw-07")
        self.assertIn("Firewall", firewall.alias)
        self.assertIn("Switch", switch.alias)
        self.assertTrue(
            any("ASA5525" in item for item in firewall.basis),
            f"the ASA platform should be the stated basis: {firewall.basis}",
        )

    def test_every_alias_declares_what_it_was_built_from(self) -> None:
        book, _ = book_for(semantic.PROFILE_CLOUD)
        entry = book.for_original("edge-mumbai-core-01")
        self.assertIn("assigned site", entry.basis)
        self.assertIn("role word in the hostname", entry.basis)

    def test_unknown_metadata_yields_a_generic_alias_not_an_invention(
        self,
    ) -> None:
        """Atlas knows nothing about zz11 — so the alias says nothing."""

        book, _ = book_for(semantic.PROFILE_CLOUD)
        entry = book.for_original("zz11")
        self.assertEqual(entry.basis, ())
        self.assertRegex(entry.alias, r"^Device \d+$")
        for invented in ("Core", "Edge", "Router", "Switch", "Firewall"):
            self.assertNotIn(invented, entry.alias)

    def test_no_alias_is_minted_for_a_name_atlas_does_not_know(self) -> None:
        book, _ = book_for(semantic.PROFILE_CLOUD)
        self.assertIsNone(book.for_original("some-other-company-router"))

    def test_hostname_derived_site_is_labelled_as_weaker_evidence(
        self,
    ) -> None:
        """Reading location out of a hostname is allowed, and is stated
        as a naming convention rather than an assigned site."""

        graph = FakeGraph(devices=(
            FakeDevice("d1", "pune-edge-01", "ISR4451"),
        ))
        book, _ = book_for(semantic.PROFILE_CLOUD, graph)
        entry = book.for_original("pune-edge-01")
        self.assertIn("Pune", entry.alias)
        self.assertTrue(
            any("not an assigned site" in item for item in entry.basis),
            entry.basis,
        )


# -- Part 2: consistency ----------------------------------------------------

class AliasConsistencyTests(unittest.TestCase):
    """Device A is never later Device C. Consistency is mandatory."""

    def test_repeated_references_use_one_alias(self) -> None:
        text = ("edge-mumbai-core-01 lost a session. Check "
                "edge-mumbai-core-01, then edge-mumbai-core-01 again.")
        safe, _report, _book, _profile = scrub(text, semantic.PROFILE_CLOUD)
        self.assertEqual(safe.count("Mumbai Core Router"), 3)
        self.assertNotIn("edge-mumbai-core-01", safe)

    def test_two_similar_devices_never_share_an_alias(self) -> None:
        text = "edge-mumbai-core-01 peers with edge-mumbai-core-02."
        safe, _report, book, _profile = scrub(text, semantic.PROFILE_CLOUD)
        first = book.for_original("edge-mumbai-core-01").alias
        second = book.for_original("edge-mumbai-core-02").alias
        self.assertNotEqual(first, second)
        self.assertIn(first, safe)
        self.assertIn(second, safe)

    def test_aliases_are_stable_across_every_value_in_one_request(
        self,
    ) -> None:
        from founderos_atlas.prism.redaction import redact_all

        book, profile = book_for(semantic.PROFILE_CLOUD)
        values, report = redact_all(
            ["edge-mumbai-core-01 is down.",
             "The peer of edge-mumbai-core-01 is hyd-border-fw-02."],
            policy_for(profile), aliases=book,
        )
        self.assertIn("Mumbai Core Router", values[0])
        self.assertIn("Mumbai Core Router", values[1])
        self.assertTrue(report.aliases)

    def test_an_alias_is_never_rewritten_by_a_later_rule(self) -> None:
        """"Mumbai Core Router" must not be mangled by the site rule
        for "mumbai" that runs after it."""

        safe, _r, _b, _p = scrub(
            "edge-mumbai-core-01 at mumbai", semantic.PROFILE_HIGH_SECURITY,
        )
        self.assertNotIn("[redacted:hostname", safe)
        self.assertNotIn("[redacted:site", safe)


# -- Part 3: the three profiles ---------------------------------------------

SENSITIVE = (
    "edge-mumbai-core-01 (10.20.30.40, aa:bb:cc:dd:ee:ff) at mumbai. "
    "snmp-server community S3cr3tValue. Contact user: dpatel."
)


class PrivacyProfileTests(unittest.TestCase):

    def test_internal_preserves_hostnames_and_addresses(self) -> None:
        safe, _r, _b, _p = scrub(SENSITIVE, semantic.PROFILE_INTERNAL)
        self.assertIn("edge-mumbai-core-01", safe)
        self.assertIn("10.20.30.40", safe)
        self.assertIn("mumbai", safe)

    def test_internal_still_removes_secrets(self) -> None:
        """No profile can preserve a secret. There is no such setting."""

        safe, _r, _b, _p = scrub(SENSITIVE, semantic.PROFILE_INTERNAL)
        self.assertNotIn("S3cr3tValue", safe)

    def test_cloud_aliases_hostnames_masks_addresses_keeps_sites(
        self,
    ) -> None:
        safe, _r, _b, _p = scrub(SENSITIVE, semantic.PROFILE_CLOUD)
        self.assertNotIn("edge-mumbai-core-01", safe)
        self.assertIn("Mumbai Core Router", safe)
        self.assertNotIn("10.20.30.40", safe)
        self.assertIn("mumbai", safe)      # site names carry the meaning
        self.assertNotIn("S3cr3tValue", safe)

    def test_high_security_aliases_the_site_name_too(self) -> None:
        safe, _r, _b, _p = scrub(SENSITIVE, semantic.PROFILE_HIGH_SECURITY)
        self.assertNotIn("edge-mumbai-core-01", safe)
        self.assertNotIn("mumbai", safe.casefold())
        self.assertNotIn("10.20.30.40", safe)
        self.assertNotIn("S3cr3tValue", safe)

    def test_high_security_still_conveys_role_and_relationship(self) -> None:
        """Protection that destroys meaning is the thing this PR
        replaces — the sentence must still be about a core router."""

        safe, _r, _b, _p = scrub(SENSITIVE, semantic.PROFILE_HIGH_SECURITY)
        self.assertIn("Core Router", safe)

    def test_switching_profile_changes_the_outcome_for_one_text(
        self,
    ) -> None:
        outputs = {
            key: scrub(SENSITIVE, key)[0]
            for key in (semantic.PROFILE_INTERNAL, semantic.PROFILE_CLOUD,
                        semantic.PROFILE_HIGH_SECURITY)
        }
        self.assertEqual(len(set(outputs.values())), 3)

    def test_every_profile_is_complete(self) -> None:
        """A field with no policy would be an undefined disclosure."""

        for profile in semantic.PROFILES:
            for name, _label in semantic.FIELDS:
                with self.subTest(profile=profile.key, field=name):
                    self.assertIn(profile.action(name), semantic.ACTIONS)

    def test_a_callers_known_names_cannot_override_preserve(self) -> None:
        """The caller hands PRISM every name Atlas knows, sites
        included. Under Cloud the site name must survive that list —
        it was being masked as a hostname, so the payload read
        "site: [redacted:hostname-2]" while the profile promised the
        site would be preserved."""

        book, profile = book_for(semantic.PROFILE_CLOUD)
        names = semantic.known_names_for(
            book, ["mumbai", "hyderabad", "edge-mumbai-core-01"],
        )
        self.assertNotIn("mumbai", names)
        self.assertIn("edge-mumbai-core-01", names)

        safe, _report = redact(
            "edge-mumbai-core-01 at site mumbai",
            RedactionPolicy.from_names(
                profile.optional_rules(), known_names=names,
            ),
            aliases=book,
        )
        self.assertIn("mumbai", safe)
        self.assertNotIn("[redacted:hostname", safe)

    def test_high_security_drops_the_site_from_known_names_too(self) -> None:
        book, _profile = book_for(semantic.PROFILE_HIGH_SECURITY)
        names = semantic.known_names_for(book, ["mumbai"])
        self.assertIn("mumbai", names)   # aliased, so still protected

    def test_preserve_turns_the_matching_rule_off(self) -> None:
        internal = semantic.profile(semantic.PROFILE_INTERNAL)
        self.assertNotIn("hostnames", internal.optional_rules())
        cloud = semantic.profile(semantic.PROFILE_CLOUD)
        self.assertIn("hostnames", cloud.optional_rules())


# -- Parts 8 and 9: hosting defaults ----------------------------------------

class HostingDefaultTests(unittest.TestCase):

    def test_cloud_hosting_defaults_to_semantic_aliasing(self) -> None:
        chosen = semantic.profile(semantic.profile_for_hosting("cloud"))
        self.assertEqual(chosen.action(semantic.FIELD_HOSTNAMES),
                         semantic.ALIAS)

    def test_local_hosting_may_preserve_hostnames(self) -> None:
        chosen = semantic.profile(semantic.profile_for_hosting("local"))
        self.assertEqual(chosen.action(semantic.FIELD_HOSTNAMES),
                         semantic.PRESERVE)

    def test_the_default_profile_is_the_stronger_one(self) -> None:
        """A local provider does not silently relax protection: that is
        an administrator's explicit choice, not an inference."""

        config = PrismConfig(enabled=True, provider_kind="ollama",
                             model="llama3", endpoint="http://localhost:1")
        self.assertEqual(config.active_profile().key, semantic.PROFILE_CLOUD)

    def test_auto_follows_the_provider_when_chosen_explicitly(self) -> None:
        config = PrismConfig(
            enabled=True, provider_kind="ollama", model="llama3",
            endpoint="http://localhost:1",
            privacy_profile=semantic.PROFILE_AUTO,
        )
        self.assertEqual(config.active_profile().key,
                         semantic.PROFILE_INTERNAL)


# -- Part 7: per-field administration ---------------------------------------

class FieldPolicyTests(unittest.TestCase):

    def test_an_override_changes_one_field_only(self) -> None:
        config = PrismConfig(
            privacy_profile=semantic.PROFILE_CLOUD,
            field_overrides=((semantic.FIELD_SITE_NAMES, semantic.ALIAS),),
        )
        active = config.active_profile()
        self.assertEqual(active.action(semantic.FIELD_SITE_NAMES),
                         semantic.ALIAS)
        self.assertEqual(active.action(semantic.FIELD_HOSTNAMES),
                         semantic.ALIAS)
        self.assertEqual(active.action(semantic.FIELD_APPLICATIONS),
                         semantic.PRESERVE)

    def test_an_unknown_field_or_action_is_ignored(self) -> None:
        base = semantic.profile(semantic.PROFILE_CLOUD)
        changed = base.with_overrides({"not-a-field": semantic.REMOVE,
                                       semantic.FIELD_VLANS: "obliterate"})
        self.assertEqual(changed.rules, base.rules)

    def test_overrides_survive_a_save_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = PrismConfigRepository(Path(tmp))
            repository.save(PrismConfig(
                privacy_profile=semantic.PROFILE_HIGH_SECURITY,
                field_overrides=((semantic.FIELD_VLANS, semantic.REMOVE),),
            ), now="2026-01-01T00:00:00Z")
            loaded = PrismConfigRepository(Path(tmp)).load()
            self.assertEqual(loaded.privacy_profile,
                             semantic.PROFILE_HIGH_SECURITY)
            self.assertEqual(loaded.active_profile().action(
                semantic.FIELD_VLANS), semantic.REMOVE)

    def test_a_pre_profile_configuration_keeps_its_own_rules(self) -> None:
        """Upgrading must not silently change a privacy posture."""

        config = PrismConfig.from_dict({
            "provider_kind": "openai", "model": "gpt-4o-mini",
            "redaction_rules": ["hostnames"],
        })
        self.assertEqual(config.privacy_profile, "")
        active = config.active_profile()
        self.assertEqual(active.action(semantic.FIELD_HOSTNAMES),
                         semantic.MASK)
        self.assertEqual(active.action(semantic.FIELD_IP_ADDRESSES),
                         semantic.PRESERVE)

    def test_a_new_configuration_gets_the_cloud_profile(self) -> None:
        config = PrismConfig.from_dict({"provider_kind": "openai"})
        self.assertEqual(config.privacy_profile, semantic.PROFILE_CLOUD)


# -- Part 5.1: the authorised operator's view -------------------------------

ANSWER = ("The Mumbai Core Router lost its session with the "
          "Hyderabad Border Firewall.")


class OperatorPresentationTests(unittest.TestCase):

    def present(self, *, can_view: bool, can_reveal: bool):
        book, profile = book_for(semantic.PROFILE_CLOUD)
        return presentation.present(
            ANSWER, aliases=book, active_profile=profile,
            can_view=can_view, can_reveal=can_reveal,
        )

    def test_an_alias_is_annotated_for_the_operator(self) -> None:
        segments = self.present(can_view=True, can_reveal=True)
        alias = [item for item in segments if item.is_alias]
        self.assertTrue(alias)
        self.assertIn("protected during AI processing", alias[0].note)

    def test_an_alias_links_to_the_atlas_object(self) -> None:
        segments = self.present(can_view=True, can_reveal=True)
        hrefs = {item.href for item in segments if item.is_alias}
        self.assertIn("/devices/d1", hrefs)

    def test_the_operator_view_reassembles_the_whole_answer(self) -> None:
        segments = self.present(can_view=True, can_reveal=False)
        self.assertEqual("".join(item.text for item in segments), ANSWER)

    def test_no_link_without_the_permission_to_follow_it(self) -> None:
        segments = self.present(can_view=False, can_reveal=False)
        self.assertTrue([item for item in segments if item.is_alias])
        self.assertEqual(
            {item.href for item in segments if item.is_alias}, {""},
        )

    def test_no_original_name_without_the_permission_to_read_it(
        self,
    ) -> None:
        for can_view in (True, False):
            with self.subTest(can_view=can_view):
                segments = self.present(can_view=can_view, can_reveal=False)
                for item in segments:
                    self.assertEqual(item.original, "")
                    self.assertNotIn("original", item.to_dict())

    def test_the_original_name_is_available_when_permitted(self) -> None:
        segments = self.present(can_view=True, can_reveal=True)
        originals = {item.original for item in segments if item.is_alias}
        self.assertIn("edge-mumbai-core-01", originals)

    def test_an_alias_atlas_never_issued_is_not_linked(self) -> None:
        """A model that invents "the Chennai Core Router" must not
        produce a link claiming to be a real device."""

        book, profile = book_for(semantic.PROFILE_CLOUD)
        segments = presentation.present(
            "The Kolkata Spine Router is fine.", aliases=book,
            active_profile=profile, can_view=True, can_reveal=True,
        )
        self.assertEqual([item for item in segments if item.is_alias], [])

    def test_the_legend_hides_originals_without_permission(self) -> None:
        book, _profile = book_for(semantic.PROFILE_CLOUD)
        rows = presentation.alias_legend(book, can_reveal=False)
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn("original", row)

    def test_a_preserved_value_needs_no_alias_row(self) -> None:
        book, _profile = book_for(semantic.PROFILE_INTERNAL)
        self.assertEqual(presentation.alias_legend(book, can_reveal=True), [])


# -- Part 5.2: transparency -------------------------------------------------

class ProtectionTransparencyTests(unittest.TestCase):

    def record(self, profile_key=semantic.PROFILE_CLOUD):
        book, profile = book_for(profile_key)
        return presentation.protection_record(
            book.for_original("edge-mumbai-core-01"),
            active_profile=profile, provider="openai", model="gpt-4o-mini",
        )

    def test_it_states_the_active_profile_and_the_rule(self) -> None:
        record = self.record()
        self.assertEqual(record["profile_key"], semantic.PROFILE_CLOUD)
        self.assertIn("Hostnames", record["rule"])
        self.assertIn("Semantic alias", record["rule"])

    def test_it_states_the_object_type(self) -> None:
        self.assertEqual(self.record()["object_type"], "device")

    def test_it_states_that_atlas_still_holds_the_original(self) -> None:
        record = self.record()
        self.assertTrue(record["retained"])
        self.assertIn("unchanged", record["retained_note"])

    def test_it_states_what_the_provider_received(self) -> None:
        self.assertIn("never the original", self.record()["sent_note"])

    def test_it_never_contains_the_original_value(self) -> None:
        """The record explains the protection; it is not a back door
        around it. The original is added separately, by a caller that
        has checked permission."""

        record = self.record()
        self.assertNotIn("edge-mumbai-core-01", repr(record))

    def test_a_generic_alias_says_why_it_is_generic(self) -> None:
        book, profile = book_for(semantic.PROFILE_CLOUD)
        record = presentation.protection_record(
            book.for_original("zz11"), active_profile=profile,
        )
        self.assertIn("rather than inventing one", record["basis_note"])


# -- Part 10: audit ---------------------------------------------------------

class AuditRecordTests(unittest.TestCase):

    def test_counts_are_reported_by_action(self) -> None:
        _safe, report, _book, _profile = scrub(
            SENSITIVE, semantic.PROFILE_CLOUD,
        )
        payload = report.to_dict()
        self.assertGreaterEqual(payload["semantic_alias_count"], 1)
        self.assertGreaterEqual(payload["masked_field_count"], 1)
        self.assertGreaterEqual(payload["removed_field_count"], 1)

    def test_remove_is_not_a_mask_by_another_name(self) -> None:
        """Cloud sets usernames to Remove. A stable placeholder would
        let a model correlate the same user across mentions — that is
        pseudonymisation, not removal, so a removal carries no index."""

        safe, report, _book, _profile = scrub(
            "Contact user: dpatel and user: rmehta about user: dpatel.",
            semantic.PROFILE_CLOUD,
        )
        self.assertNotIn("dpatel", safe)
        self.assertNotIn("rmehta", safe)
        self.assertIn("[removed:username]", safe)
        self.assertNotIn("[redacted:username", safe)
        # Nothing distinguishes the two users, or the repeat.
        self.assertEqual(safe.count("[removed:username]"), 3)
        self.assertEqual(report.action_counts()[semantic.REMOVE], 3)

    def test_mask_still_correlates(self) -> None:
        """The opposite guarantee: Cloud MASKS addresses, so the same
        address reads the same twice — a model must still be able to
        reason about one device."""

        safe, _report, _book, _profile = scrub(
            "10.20.30.40 peers with 10.20.30.41; retry 10.20.30.40.",
            semantic.PROFILE_CLOUD,
        )
        self.assertEqual(safe.count("[redacted:ip-1]"), 2)
        self.assertIn("[redacted:ip-2]", safe)

    def test_no_removed_secret_appears_in_the_report(self) -> None:
        _safe, report, _book, _profile = scrub(
            SENSITIVE, semantic.PROFILE_CLOUD,
        )
        self.assertNotIn("S3cr3tValue", repr(report.to_dict()))

    def test_the_usage_record_carries_the_profile_and_counts(self) -> None:
        from founderos_atlas.prism.usage import UsageRecord

        payload = UsageRecord(
            at="2026-01-01T00:00:00Z", capability="c", provider="openai",
            model="m", prompt_version="v", outcome="success",
            privacy_profile=semantic.PROFILE_CLOUD,
            semantic_alias_count=3, masked_field_count=2,
            removed_field_count=1,
        ).to_dict()
        self.assertEqual(payload["privacy_profile"], semantic.PROFILE_CLOUD)
        self.assertEqual(payload["semantic_alias_count"], 3)
        self.assertEqual(payload["masked_field_count"], 2)
        self.assertEqual(payload["removed_field_count"], 1)


# -- regression: the secret tier is untouched -------------------------------

class SecretsAreNeverAliasedTests(unittest.TestCase):
    """Semantic redaction adds a tier; it must not weaken the one that
    was already there."""

    SECRETS = (
        "password Hunter2",
        "snmp-server community Public1",
        "Authorization: Bearer abcdef0123456789",
        "api_key sk-abcdefghijklmnopqrst",
        "enable secret 5 $1$abc$defghijk",
        "https://admin:hunter2@example.net/api",
    )

    def test_every_secret_is_removed_under_every_profile(self) -> None:
        leaks = ("Hunter2", "Public1", "abcdef0123456789",
                 "sk-abcdefghijklmnopqrst", "$1$abc$defghijk", "hunter2")
        for profile_key in (semantic.PROFILE_INTERNAL, semantic.PROFILE_CLOUD,
                            semantic.PROFILE_HIGH_SECURITY):
            for text in self.SECRETS:
                with self.subTest(profile=profile_key, text=text):
                    safe, _r, _b, _p = scrub(text, profile_key)
                    for leak in leaks:
                        if leak in text:
                            self.assertNotIn(leak, safe)

    def test_no_privacy_field_can_govern_a_secret(self) -> None:
        for name, _label in semantic.FIELDS:
            self.assertNotIn(
                name,
                ("passwords", "secrets", "api_keys", "credentials",
                 "private_keys", "snmp_communities"),
            )

    def test_redaction_without_an_alias_book_is_unchanged(self) -> None:
        """Callers that never pass a book keep the previous behaviour
        exactly — this PR is additive."""

        safe, report = redact(
            "mumbai-core is at 10.1.2.3",
            RedactionPolicy.from_names(
                ("hostnames", "ip-addresses"), known_names=("mumbai-core",),
            ),
        )
        self.assertIn("[redacted:hostname-1]", safe)
        self.assertIn("[redacted:ip-1]", safe)
        self.assertEqual(report.aliases, [])

    def test_a_sentence_survives_username_redaction(self) -> None:
        """The full stop is not part of the username — a mangled
        sentence protects nothing and costs meaning."""

        safe, _report = redact(
            "Contact user: dpatel. Then escalate.",
            RedactionPolicy.from_names(("usernames",)),
        )
        self.assertNotIn("dpatel", safe)
        self.assertIn("]. Then escalate.", safe)


# -- governance -------------------------------------------------------------

class GovernanceWarningTests(unittest.TestCase):

    def test_a_cloud_provider_with_preserved_fields_warns_by_name(
        self,
    ) -> None:
        from founderos_atlas.prism.config import validate

        problems = validate(
            PrismConfig(enabled=True, provider_kind="openai",
                        model="gpt-4o-mini", allow_cloud_providers=True,
                        privacy_profile=semantic.PROFILE_INTERNAL),
            has_api_key=True,
        )
        warning = [item for item in problems if item.startswith("Warning")]
        self.assertTrue(warning)
        self.assertIn("hostnames", warning[0])

    def test_high_security_on_a_cloud_provider_warns_about_nothing(
        self,
    ) -> None:
        from founderos_atlas.prism.config import validate

        problems = validate(
            PrismConfig(enabled=True, provider_kind="openai",
                        model="gpt-4o-mini", allow_cloud_providers=True,
                        privacy_profile=semantic.PROFILE_HIGH_SECURITY),
            has_api_key=True,
        )
        self.assertEqual(
            [item for item in problems if item.startswith("Warning")], [],
        )

    def test_the_default_cloud_posture_does_not_warn(self) -> None:
        """Cloud preserves site names, VLANs and application names by
        design. Warning about that on every save would train
        administrators to ignore the warning that matters."""

        from founderos_atlas.prism.config import validate

        problems = validate(
            PrismConfig(enabled=True, provider_kind="openai",
                        model="gpt-4o-mini", allow_cloud_providers=True,
                        privacy_profile=semantic.PROFILE_CLOUD),
            has_api_key=True,
        )
        self.assertEqual(
            [item for item in problems if item.startswith("Warning")], [],
        )


# -- the settings surface (Part 7), end to end -----------------------------

class PrivacySettingsPageTests(unittest.TestCase):
    """The per-field policy must survive a real form round trip — a
    privacy control that silently fails to save is worse than none."""

    def client(self, workdir: Path):
        from founderos_atlas.web import create_app
        from founderos_atlas.workspace import (
            InMemoryCredentialProvider, ProfileRepository, ProfileService,
        )

        service = ProfileService(
            ProfileRepository(workdir / "workspace"),
            InMemoryCredentialProvider(),
        )
        app = create_app(
            profile_service=service, output_dir=workdir / "out",
            history_root=workdir / "out" / ".atlas" / "history",
            workspace_root=workdir / "workspace",
        )
        app.config.update(TESTING=True)
        return app, app.test_client()

    def test_the_page_offers_every_field_and_every_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _app, client = self.client(Path(tmp))
            body = client.get("/settings/ai").data.decode()
            for name, _label in semantic.FIELDS:
                self.assertIn(f'name="policy__{name}"', body)
            self.assertEqual(body.count('name="policy__hostnames"'),
                             len(semantic.ACTIONS))
            # Three profiles plus "match the provider".
            self.assertEqual(body.count('name="privacy_profile"'),
                             len(semantic.PROFILES) + 1)

    def test_the_page_states_that_secrets_are_never_optional(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _app, client = self.client(Path(tmp))
            body = client.get("/settings/ai").data.decode()
            self.assertIn("no way to switch that off", body)

    def test_a_profile_and_an_override_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _app, client = self.client(workdir)
            client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": "ollama",
                "model": "llama3", "endpoint": "http://localhost:11434",
                "privacy_profile": semantic.PROFILE_HIGH_SECURITY,
                "policy__vlans": semantic.PRESERVE,
                "policy__hostnames": semantic.ALIAS,
            }, follow_redirects=True)
            from founderos_atlas.prism.config import PrismConfigRepository

            stored = PrismConfigRepository(workdir / "workspace").load()
            self.assertEqual(stored.privacy_profile,
                             semantic.PROFILE_HIGH_SECURITY)
            active = stored.active_profile()
            self.assertEqual(active.action(semantic.FIELD_VLANS),
                             semantic.PRESERVE)
            # Matching the profile's own action stores no override.
            self.assertEqual(
                [name for name, _ in stored.field_overrides],
                [semantic.FIELD_VLANS],
            )

    def test_an_unrecognised_profile_keeps_the_current_one(self) -> None:
        """A malformed post must never quietly relax a posture."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _app, client = self.client(workdir)
            from founderos_atlas.prism.config import PrismConfigRepository

            repository = PrismConfigRepository(workdir / "workspace")
            repository.save(
                PrismConfig(privacy_profile=semantic.PROFILE_HIGH_SECURITY),
                now="2026-01-01T00:00:00Z",
            )
            client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": "ollama", "model": "llama3",
                "endpoint": "http://localhost:11434",
                "privacy_profile": "wide-open",
            }, follow_redirects=True)
            self.assertEqual(repository.load().privacy_profile,
                             semantic.PROFILE_HIGH_SECURITY)

    def test_switching_profile_actually_switches_it(self) -> None:
        """The per-field radios are rendered from the profile in force.
        Submitting them alongside a DIFFERENT profile stored every
        difference as an override, reinstating the old policy in full —
        so the primary privacy control did nothing at all."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _app, client = self.client(workdir)
            from founderos_atlas.prism.config import PrismConfigRepository

            repository = PrismConfigRepository(workdir / "workspace")
            repository.save(
                PrismConfig(privacy_profile=semantic.PROFILE_INTERNAL),
                now="2026-01-01T00:00:00Z",
            )
            internal = semantic.profile(semantic.PROFILE_INTERNAL)
            # Exactly what the browser posts: the OLD profile's radios
            # plus the newly selected profile.
            data = {
                "enabled": "1", "provider_kind": "ollama", "model": "llama3",
                "endpoint": "http://localhost:11434",
                "privacy_profile": semantic.PROFILE_HIGH_SECURITY,
                # The hidden field records the RESOLVED profile the
                # table was rendered from.
                "privacy_profile_rendered": semantic.PROFILE_INTERNAL,
            }
            for name, _label in semantic.FIELDS:
                data[f"policy__{name}"] = internal.action(name)
            client.post("/settings/ai", data=data, follow_redirects=True)

            active = repository.load().active_profile()
            expected = semantic.profile(semantic.PROFILE_HIGH_SECURITY)
            for name, _label in semantic.FIELDS:
                with self.subTest(field=name):
                    self.assertEqual(active.action(name),
                                     expected.action(name))

    def test_auto_does_not_freeze_into_eleven_overrides(self) -> None:
        """``auto`` is not a profile key, so the baseline lookup failed
        and every field was stored as a hard override — pinning
        whatever was on screen and defeating "match the provider"."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _app, client = self.client(workdir)
            from founderos_atlas.prism.config import PrismConfigRepository

            repository = PrismConfigRepository(workdir / "workspace")
            data = {
                "enabled": "1", "provider_kind": "ollama", "model": "llama3",
                "endpoint": "http://localhost:11434",
                "privacy_profile": semantic.PROFILE_AUTO,
                # Auto + a local provider renders the Internal table.
                "privacy_profile_rendered": semantic.PROFILE_INTERNAL,
            }
            # A local provider under auto resolves to Internal, so these
            # are the values the page would show.
            internal = semantic.profile(semantic.PROFILE_INTERNAL)
            for name, _label in semantic.FIELDS:
                data[f"policy__{name}"] = internal.action(name)
            client.post("/settings/ai", data=data, follow_redirects=True)

            stored = repository.load()
            self.assertEqual(stored.privacy_profile, semantic.PROFILE_AUTO)
            self.assertEqual(stored.field_overrides, ())
            # And auto still follows the provider afterwards.
            from dataclasses import replace as _replace

            as_cloud = _replace(stored, provider_kind="openai")
            self.assertEqual(as_cloud.active_profile().key,
                             semantic.PROFILE_CLOUD)

    def test_the_summary_reflects_the_profile_not_the_stale_rules(
        self,
    ) -> None:
        """The read-only view exists "so every operator can see what
        Atlas would send". It computed that line from the now-vestigial
        rule list, so it OVERSTATED protection the moment a profile was
        chosen — the one place a non-admin has to trust."""

        from unittest.mock import patch

        from founderos_atlas.prism.config import PrismConfigRepository
        from founderos_atlas.web import create_app
        from founderos_atlas.access.users import UserStore

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "ws"
            workspace.mkdir(parents=True, exist_ok=True)
            store = UserStore(workspace)
            store.create(username="sso-viewer", roles=("viewer",))
            PrismConfigRepository(workspace).save(
                # The rules claim four protections; the Internal
                # profile preserves every one of them.
                PrismConfig(privacy_profile=semantic.PROFILE_INTERNAL,
                            redaction_rules=("hostnames", "ip-addresses",
                                             "usernames", "mac-addresses")),
                now="2026-01-01T00:00:00Z",
            )
            with patch.dict("os.environ", {
                "ATLAS_PROXY_SECRET": "proxy-shared-secret-1",
            }):
                app = create_app(
                    output_dir=Path(tmp), workspace_root=workspace,
                    auth_mode="proxy",
                )
            app.config.update(TESTING=True)
            body = app.test_client().get("/settings/ai", headers={
                "X-Atlas-Proxy-Secret": "proxy-shared-secret-1",
                "X-Atlas-Remote-User": "sso-viewer",
            }).data.decode()

            self.assertIn("Viewing only", body)
            summary = body.split("Redacted before sending", 1)[1]
            summary = summary.split("</li>", 1)[0]
            self.assertIn("credentials and key material", summary)
            self.assertNotIn("hostnames", summary)
            self.assertNotIn("ip addresses", summary)

    def test_saving_does_not_empty_a_legacy_rule_set(self) -> None:
        """The form no longer posts the old rules; they must be
        retained, not cleared, or an unrelated save would strip a
        pre-profile enterprise's protection."""

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            _app, client = self.client(workdir)
            from founderos_atlas.prism.config import PrismConfigRepository

            repository = PrismConfigRepository(workdir / "workspace")
            repository.save(
                PrismConfig(privacy_profile="",
                            redaction_rules=("hostnames", "ip-addresses")),
                now="2026-01-01T00:00:00Z",
            )
            client.post("/settings/ai", data={
                "enabled": "1", "provider_kind": "ollama", "model": "llama3",
                "endpoint": "http://localhost:11434",
                "privacy_profile": "",
            }, follow_redirects=True)
            self.assertEqual(repository.load().redaction_rules,
                             ("hostnames", "ip-addresses"))


class AuditFindingRegressionTests(unittest.TestCase):
    """Defects found by an adversarial audit of this PR, each
    reproduced before it was fixed. They are grouped here because they
    share a theme: a second code path that did not receive the alias
    book, or received one built for a different profile."""

    def test_a_second_pass_does_not_mangle_the_first_passs_aliases(
        self,
    ) -> None:
        """The translation capability re-redacts text that ALREADY
        contains aliases. Without the book it ran with an unreconciled
        name list and no profile, and produced
        "the [redacted:hostname-1] Core Router at site
        [redacted:hostname-1]" — the alias broken, the preserved site
        masked, and two distinct objects on one placeholder."""

        book, profile = book_for(semantic.PROFILE_CLOUD)
        raw = ["mumbai", "hyderabad", "edge-mumbai-core-01"]
        first_pass = "The Mumbai Core Router at site Mumbai lost its peer."

        # What the second pass does now: the book comes along.
        safe, _report = redact(
            first_pass,
            RedactionPolicy.from_names(
                profile.optional_rules(),
                known_names=semantic.known_names_for(book, raw),
            ),
            aliases=book,
        )
        self.assertEqual(safe, first_pass)
        self.assertNotIn("[redacted:hostname", safe)

    def test_translation_is_given_the_alias_book(self) -> None:
        """Pins the call itself, so the book cannot be dropped again."""

        import inspect

        from founderos_atlas.advisor import explanation as module

        source = inspect.getsource(module.explain)
        translation = source.split("CAPABILITY_TRANSLATION", 1)[1]
        translation = translation.split(")", 1)[0] + ")"
        self.assertIn("aliases=aliases", translation)

    def test_a_device_named_after_its_site_is_still_protected(self) -> None:
        """A site "mumbai" and a device "mumbai" collide on one key.
        The site entry (Preserve, under Cloud) was returned for the
        device too, so the device never got an alias AND
        known_names_for dropped it as "preserved" — the real hostname
        went to the provider verbatim. Protection wins over
        preservation."""

        graph = FakeGraph(devices=(
            FakeDevice("d9", "mumbai", "ISR4451", site=FakeSite("mumbai")),
        ))
        book, profile = book_for(semantic.PROFILE_CLOUD, graph)
        entry = book.for_original("mumbai")
        self.assertEqual(entry.kind, "device")
        self.assertNotEqual(entry.action, semantic.PRESERVE)

        names = semantic.known_names_for(book, ["mumbai"])
        self.assertIn("mumbai", names)
        safe, _report = redact(
            "Device mumbai is down.",
            RedactionPolicy.from_names(
                profile.optional_rules(), known_names=names,
            ),
            aliases=book,
        )
        self.assertNotIn("mumbai", safe.casefold())

    def test_an_alias_never_contains_the_value_it_protects(self) -> None:
        """The invariant behind the previous test, stated generally.
        Building an alias out of a site name discloses the hostname
        whenever the two are the same word."""

        graph = FakeGraph(devices=(
            FakeDevice("d1", "mumbai", "ISR4451", site=FakeSite("mumbai")),
            FakeDevice("d2", "core", "C9300", site=FakeSite("pune")),
            FakeDevice("d3", "edge-mumbai-core-01", "ISR4451",
                       site=FakeSite("mumbai")),
        ))
        for profile_key in (semantic.PROFILE_CLOUD,
                            semantic.PROFILE_HIGH_SECURITY):
            book, _profile = book_for(profile_key, graph)
            for entry in book.entries():
                if entry.action != semantic.ALIAS:
                    continue
                with self.subTest(profile=profile_key,
                                  original=entry.original):
                    self.assertNotIn(
                        entry.original.casefold(), entry.alias.casefold(),
                    )

    def test_a_preserved_entry_is_not_replaced_by_another_preserve(
        self,
    ) -> None:
        """The upgrade is one-way: nothing weakens an existing entry."""

        graph = FakeGraph(devices=(
            FakeDevice("d9", "mumbai", "ISR4451", site=FakeSite("mumbai")),
        ))
        book, _profile = book_for(semantic.PROFILE_INTERNAL, graph)
        entry = book.for_original("mumbai")
        self.assertEqual(entry.action, semantic.PRESERVE)

    def test_a_removed_value_is_never_attributed_to_a_device(self) -> None:
        """Removed values are deliberately identical, so presenting one
        as "this device" attached a real hostname to whichever entry
        matched first — disclosing the wrong device's name."""

        profile = semantic.profile(semantic.PROFILE_CLOUD).with_overrides(
            {semantic.FIELD_HOSTNAMES: semantic.REMOVE}
        )
        book = semantic.build_alias_book(estate(), active_profile=profile)
        segments = presentation.present(
            "Both [removed:device] and [removed:device] failed.",
            aliases=book.entries(), active_profile=profile,
            can_view=True, can_reveal=True,
        )
        self.assertEqual([item for item in segments if item.is_alias], [])

    def test_two_originals_sharing_an_alias_are_never_linked(self) -> None:
        """Ambiguity is dropped, not guessed at."""

        from founderos_atlas.prism.semantic import SemanticAlias

        twins = (
            SemanticAlias(alias="Core Router", original="a-01", kind="device",
                          action=semantic.ALIAS,
                          field=semantic.FIELD_HOSTNAMES, object_id="d1",
                          href="/devices/d1"),
            SemanticAlias(alias="Core Router", original="b-02", kind="device",
                          action=semantic.ALIAS,
                          field=semantic.FIELD_HOSTNAMES, object_id="d2",
                          href="/devices/d2"),
        )
        segments = presentation.present(
            "The Core Router failed.", aliases=twins,
            active_profile=semantic.profile(semantic.PROFILE_CLOUD),
            can_view=True, can_reveal=True,
        )
        self.assertEqual([item for item in segments if item.is_alias], [])

    def test_the_book_matches_the_service_that_uses_it(self) -> None:
        """An Internal book handed to a Cloud service leaves the policy
        with NO known names, so bare hostnames go out in the clear."""

        internal_book, _ = book_for(semantic.PROFILE_INTERNAL)
        cloud = semantic.profile(semantic.PROFILE_CLOUD)
        names = semantic.known_names_for(
            internal_book, ["edge-mumbai-core-01"],
        )
        self.assertEqual(names, [])          # the bug's mechanism

        # Built for the profile that will use it, the names survive.
        cloud_book, _ = book_for(semantic.PROFILE_CLOUD)
        self.assertIn(
            "edge-mumbai-core-01",
            semantic.known_names_for(cloud_book, ["edge-mumbai-core-01"]),
        )
        safe, _report = redact(
            "edge-mumbai-core-01 is down.",
            RedactionPolicy.from_names(
                cloud.optional_rules(),
                known_names=semantic.known_names_for(
                    cloud_book, ["edge-mumbai-core-01"],
                ),
            ),
            aliases=cloud_book,
        )
        self.assertNotIn("edge-mumbai-core-01", safe)


class PreviewMatchesWhatIsSentTests(unittest.TestCase):
    """The Playground's "data sent to the provider" panel must be what
    the provider ACTUALLY receives.

    PR-166.1 shipped a preview that overstated protection — it claimed
    hostnames were redacted that the provider got in the clear, because
    the preview and the real call were built from different name lists.
    PR-166.2 adds a second thing that must agree: the alias book. This
    test compares the two byte for byte, so a future divergence is a
    failure rather than a discovery.
    """

    EVIDENCE = (
        "BGP between edge-mumbai-core-01 and hyd-border-fw-02 is down. "
        "Management 10.20.30.40 at site mumbai. Contact user: dpatel. "
        "snmp-server community S3cr3tValue."
    )

    def test_the_preview_is_byte_identical_to_the_payload(self) -> None:
        from tests.test_prism import (
            PrismHarness, RecordingProvider, build_doubles_registry,
        )
        from founderos_atlas.prism import CAPABILITY_PLAIN_ENGLISH
        from founderos_atlas.prism.config import PrismConfigRepository
        from founderos_atlas.prism.service import PrismService

        for profile_key in (semantic.PROFILE_INTERNAL,
                            semantic.PROFILE_CLOUD,
                            semantic.PROFILE_HIGH_SECURITY):
            with self.subTest(profile=profile_key):
                RecordingProvider.requests = []
                book, profile = book_for(profile_key)
                # Exactly what the route hands PRISM: every name Atlas
                # knows, including sites and a profile name.
                known = ["mumbai", "hyderabad", "chennai", "AtlasProfile",
                         "edge-mumbai-core-01", "hyd-border-fw-02"]

                # 1. The preview, built the way the Playground builds it.
                with tempfile.TemporaryDirectory() as tmp:
                    registry = build_doubles_registry()
                    repository = PrismConfigRepository(
                        Path(tmp), registry=registry,
                    )
                    config = PrismConfig(
                        enabled=True, provider_kind="recording",
                        model="local-1",
                        enabled_capabilities=(CAPABILITY_PLAIN_ENGLISH,),
                        privacy_profile=profile_key,
                    )
                    repository.save(config, now="2026-01-01T00:00:00Z")
                    policy = config.redaction_policy().with_known_names(
                        semantic.known_names_for(book, known)
                    )
                    preview, _report = redact(
                        self.EVIDENCE, policy, aliases=book,
                    )

                    # 2. The real call.
                    service = PrismService(
                        repository=repository, output_dir=Path(tmp),
                        providers=registry,
                        clock=lambda: "2026-01-01T00:00:00Z",
                    )
                    result = service.enhance(
                        CAPABILITY_PLAIN_ENGLISH,
                        {"finding": self.EVIDENCE, "confidence": "Medium",
                         "limitations": "none", "audience": "an engineer"},
                        known_names=known, aliases=book,
                    )
                    self.assertTrue(result.ok, result.reason)
                    sent = RecordingProvider.requests[-1].messages[-1].content

                # The preview text must appear verbatim in the payload.
                self.assertIn(
                    preview, sent,
                    f"preview and payload diverged under {profile_key}",
                )
                # And the secret is gone from both, always.
                self.assertNotIn("S3cr3tValue", preview)
                self.assertNotIn("S3cr3tValue", sent)


class AliasVisibilityIsDrivenByPermissionsTests(unittest.TestCase):
    """The route decides who may follow a link and who may read an
    original name, from permissions the principal already holds. This
    pins the mapping so it cannot drift into granting more than the
    RBAC would."""

    def visibility(self, roles):
        from founderos_atlas.access.models import Principal

        if roles is None:
            return presentation.visibility_for(None)
        return presentation.visibility_for(
            Principal.for_roles(username="tester", roles=roles)
        )

    def test_an_unauthenticated_principal_gets_neither(self) -> None:
        self.assertEqual(self.visibility(None), (False, False))

    def test_viewing_pages_permits_a_link(self) -> None:
        from founderos_atlas.access.models import PAGES_VIEW, permissions_for

        for role in ("viewer", "operator", "system-admin"):
            with self.subTest(role=role):
                if PAGES_VIEW not in permissions_for((role,)):
                    continue
                can_view, _can_reveal = self.visibility((role,))
                self.assertTrue(can_view)

    def test_revealing_a_name_needs_the_evidence_permission(self) -> None:
        from founderos_atlas.access.models import (
            EVIDENCE_VIEW, permissions_for,
        )

        for role in ("viewer", "operator", "system-admin"):
            with self.subTest(role=role):
                _can_view, can_reveal = self.visibility((role,))
                self.assertEqual(
                    can_reveal, EVIDENCE_VIEW in permissions_for((role,)),
                )


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
