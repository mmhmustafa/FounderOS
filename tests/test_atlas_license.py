"""PR-A2b — the Atlas proprietary controlled-beta licence.

These are trust-boundary tests. The licence is the only document that says
what an invited tester may and may not do, and the only place where Atlas's
proprietary restrictions meet the LGPL-2.1 and MPL-2.0 rights of the
components it ships. A regression here is not a cosmetic diff: it either
grants something the owner did not decide to grant, or it takes back a
permission a third-party licence requires Atlas to give.

So the assertions are structural wherever a structural assertion is
practical: the licence is parsed into sections, cross-references are
resolved against the sections they name, defined terms are checked against
their uses, the enumerated restrictions are split into whole clauses and
each one checked for its scoping term, and the licence identifier is
reconciled with the packaging metadata that publishes it.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSE_PATH = ROOT / "LICENSE"
PYPROJECT_PATH = ROOT / "pyproject.toml"
README_PATH = ROOT / "README.md"

LICENCE_EXPRESSION = "LicenseRef-FounderOS-Atlas-Beta"
OWNER = "Mohammed Mustafa Hussain"
CONTACT = "mmhmustafa@gmail.com"
EFFECTIVE_DATE = "15 August 2026"

_SECTION_RE = re.compile(r"^(\d+)\. ([A-Z][^\n]*)$", re.MULTILINE)


def _text() -> str:
    return LICENSE_PATH.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Collapse whitespace so assertions pin meaning, not line wrapping.

    The licence is hard-wrapped for readability. A phrase test written
    against the wrapped form would break on a re-wrap that changed nothing
    substantive, and could pass while a changed word hid across a break.
    Normalising first makes the assertion about the words.
    """

    return " ".join(text.split())


def _sections() -> dict[int, tuple[str, str]]:
    """Parse LICENSE into {number: (heading, body)}."""

    text = _text()
    matches = list(_SECTION_RE.finditer(text))
    sections: dict[int, tuple[str, str]] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[number] = (match.group(2).strip(), text[match.end():end])
    return sections


def _project() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]


class LicenceIdentityTests(unittest.TestCase):
    """Who owns it, when it takes effect, how to reach them."""

    def test_no_placeholder_language_remains(self) -> None:
        text = _text()
        self.assertFalse(text.startswith("LICENSE NOT YET SELECTED"))
        for placeholder in ("LICENSE NOT YET SELECTED", "TBD", "TODO",
                            "owner to supply"):
            self.assertNotIn(placeholder, text, placeholder)
        # No bracketed placeholder of any shape survived issuance.
        self.assertIsNone(re.search(r"\[[^\]]{3,}\]", text))

    def test_effective_date_is_exact_and_consistent(self) -> None:
        text = _text()
        self.assertIn(f"Effective date: {EFFECTIVE_DATE}", text)
        self.assertIn(f"This licence is effective from {EFFECTIVE_DATE}.", text)
        self.assertEqual(2, text.count(EFFECTIVE_DATE))
        # No competing machine-readable date form.
        self.assertEqual(set(), set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)))

    def test_licensor_is_the_named_individual(self) -> None:
        text = _text()
        flat = _flat(text)
        self.assertIn(
            f"Copyright (c) 2026 {OWNER}. All rights reserved.", text
        )
        self.assertIn(f"Licensor: {OWNER}", text)
        self.assertIn(f"owned by {OWNER}", flat)

    def test_no_fictional_company_or_legal_entity(self) -> None:
        text = _text()
        for form in (" Inc", " Ltd", " LLC", " GmbH", " Pvt", " Corp",
                     "Corporation", "Limited", "Incorporated"):
            self.assertNotIn(form, text, form)
        self.assertIsNone(
            re.search(r"(Atlas|FounderOS)\s+(Inc|Ltd|LLC|Corp)", text)
        )

    def test_no_parentage_detail(self) -> None:
        blob = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (LICENSE_PATH, PYPROJECT_PATH, README_PATH)
        ).lower()
        for token in ("gulam", "dastagir", "s/o ", "son of"):
            self.assertNotIn(token, blob, token)

    def test_contact_present_exactly_where_intended(self) -> None:
        text = _text()
        self.assertIn(f"Contact: {CONTACT}", text)
        self.assertEqual(1, text.count(CONTACT))
        self.assertEqual(CONTACT, _project()["authors"][0]["email"])

    def test_spdx_identifier_agrees_with_pyproject(self) -> None:
        # The licence names itself; the metadata names the licence. If these
        # disagree, the published expression describes a document that does
        # not exist.
        self.assertIn(
            f"SPDX-License-Identifier: {LICENCE_EXPRESSION}", _text()
        )
        self.assertEqual(LICENCE_EXPRESSION, _project()["license"])


class GrantTests(unittest.TestCase):
    """An invited tester actually receives permission; nobody else does."""

    @classmethod
    def setUpClass(cls):
        cls.sections = _sections()
        cls.text = _text()

    def test_operative_grant_exists(self) -> None:
        body = _flat(self.sections[4][1])
        self.assertIn("The Licensor grants you", body)
        for verb in ("install Atlas", "copy it for your own use", "use it"):
            self.assertIn(verb, body, verb)
        for quality in ("personal", "non-exclusive", "non-transferable",
                        "revocable"):
            self.assertIn(quality, body, quality)

    def test_the_pre_a2b_paradox_is_gone(self) -> None:
        # The placeholder said no permission could be inferred. A licence
        # that still said that would authorize nobody.
        self.assertNotIn("should be inferred", self.text)
        self.assertNotIn("No permission to copy", self.text)

    def test_uninvited_users_receive_nothing(self) -> None:
        body = _flat(self.sections[1][1])
        self.assertIn("If the Licensor did not invite you", body)
        self.assertIn("no licence to the Atlas-Owned Material", body)

    def test_evaluation_only_and_not_production(self) -> None:
        body = _flat(self.sections[5][1])
        self.assertIn("evaluation and testing", body)
        self.assertIn("not a production-use licence", body)
        self.assertIn("critical operational", body)

    def test_beta_limit_is_a_rights_limit_not_drm(self) -> None:
        body = _flat(self.sections[5][1])
        self.assertIn("not a technical restriction", body)
        for mechanism in ("no expiry timer", "no kill switch",
                          "no licence key", "no activation",
                          "no machine binding", "no phone-home"):
            self.assertIn(mechanism, body, mechanism)
        self.assertIn("introduces none", body)

    def test_controlled_beta_and_you_are_defined(self) -> None:
        body = _flat(self.sections[2][1])
        self.assertIn('"The controlled beta" means', body)
        self.assertIn('"You" means', body)


class ScopingTests(unittest.TestCase):
    """Every restriction bites Atlas-Owned Material only (A2B-REQ-2)."""

    @classmethod
    def setUpClass(cls):
        cls.sections = _sections()

    def test_definitions_separate_the_four_categories(self) -> None:
        body = _flat(self.sections[2][1])
        for term in ('"Atlas-Owned Material" means',
                     '"Third-Party Components" means',
                     '"Your Data" means',
                     '"Your Outputs" means'):
            self.assertIn(term, body, term)
        self.assertIn("It does not include Third-Party Components", body)

    def test_restriction_clause_is_scoped(self) -> None:
        heading, raw = self.sections[6]
        body = _flat(raw)
        self.assertIn("ATLAS-OWNED MATERIAL", heading)
        self.assertIn(
            "These restrictions apply to Atlas-Owned Material only.", body
        )
        self.assertIn(
            "They do not apply to Third-Party Components, to Your Data, or to"
            " Your Outputs.",
            body,
        )

    def test_no_restriction_operates_on_atlas_as_a_whole(self) -> None:
        # The A2B-REQ-2 failure the adversarial pass found: a restriction
        # written against "Atlas" reaches paramiko, scp and fqdn, which the
        # Licensor cannot restrict (LGPL-2.1 s10, MPL-2.0 s3.2(b)).
        # Whole clauses, not physical lines: the scoping term often sits on
        # the following line, and a line-based reading would miss it.
        body = _flat(self.sections[6][1]).split("These restrictions")[0]
        clauses = [
            clause.strip()
            for clause in re.split(r"\((?=[a-e]\))", body)
            if re.match(r"^[a-e]\)", clause.strip())
        ]
        self.assertEqual(5, len(clauses), clauses)
        for clause in clauses:
            self.assertIn(
                "Atlas-Owned Material", clause,
                f"restriction not scoped to Atlas-Owned Material: {clause}",
            )

    def test_termination_deletion_is_scoped_and_preserves_rights(self) -> None:
        body = _flat(self.sections[15][1])
        self.assertIn(
            "delete or return the copies of the Atlas-Owned Material you hold",
            body,
        )
        self.assertIn("except a modified copy you keep under section 7", body)
        self.assertIn(
            "does not require you to delete or stop using Your Data or Your"
            " Outputs",
            body,
        )
        self.assertIn(
            "does not require you to delete any Third-Party Component", body
        )
        self.assertIn("those rights come from their licensors", body)


class ThirdPartyRightsTests(unittest.TestCase):
    """The carve-out and the LGPL permissions (A2B-REQ-1)."""

    @classmethod
    def setUpClass(cls):
        cls.sections = _sections()
        cls.text = _text()

    def test_carve_out_precedes_the_restrictions(self) -> None:
        carve_out = self.text.index("3. THIRD-PARTY COMPONENTS COME FIRST")
        restrictions = self.text.index("6. WHAT YOU MAY NOT DO")
        self.assertLess(carve_out, restrictions)

    def test_carve_out_enumerates_preserved_rights(self) -> None:
        body = _flat(self.sections[3][1])
        self.assertIn("Each one stays under its own licence.", body)
        for right in ("copy or redistribute a component", "to modify it",
                      "to reverse engineer it", "to receive its source code"):
            self.assertIn(right, body, right)
        self.assertIn("those licences win", body)

    def test_lgpl_modification_permission_exists(self) -> None:
        body = _flat(self.sections[7][1])
        self.assertIn(
            "modify Atlas — including the Atlas-Owned Material — for your own"
            " use",
            body,
        )
        self.assertIn("to the extent the licence of any Third-Party Component",
                      body)

    def test_lgpl_debugging_permission_exists(self) -> None:
        body = _flat(self.sections[7][1])
        self.assertIn(
            "reverse engineer Atlas so far as necessary to debug modifications"
            " you",
            body,
        )

    def test_lgpl_permission_overrides_every_conflicting_clause(self) -> None:
        # The adversarial finding: overriding 6(d) and 8 but not 6(e) meant
        # exercising the permission could breach the notice clause, and
        # breach terminates the licence automatically.
        self.assertIn("despite sections 6(d), 6(e) and 8",
                      _flat(self.sections[7][1]))

    def test_lgpl_permission_survives_termination(self) -> None:
        # A permission revocable over a copy you must delete is not a
        # permission. Both halves are required.
        seven = _flat(self.sections[7][1])
        self.assertIn(
            "not revocable for a copy of Atlas already supplied to you", seven
        )
        self.assertIn(
            "If this licence ends, you may keep and continue to modify for"
            " your own use a copy you had already modified under this section",
            seven,
        )
        fifteen = _flat(self.sections[15][1])
        self.assertIn("Sections 3, 7, 9, 12, 13, 16, 17 and 18 survive",
                      fifteen)

    def test_lgpl_permission_does_not_grant_redistribution(self) -> None:
        body = _flat(self.sections[7][1])
        self.assertIn("This permission is for your own use.", body)
        self.assertIn(
            "does not permit you to publish, redistribute, sublicense or sell",
            body,
        )

    def test_third_party_notices_are_preserved_when_modifying(self) -> None:
        self.assertIn(
            "keep the third-party copyright and licence notices intact",
            _flat(self.sections[7][1]),
        )

    def test_no_absolute_reverse_engineering_prohibition(self) -> None:
        body = _flat(self.sections[8][1])
        self.assertIn(
            "Except as section 3 preserves, as section 7 permits, and as"
            " applicable law allows despite an agreement to the contrary",
            body,
        )
        self.assertIn("the Atlas-Owned Material", body)
        # No unqualified prohibition anywhere in the document.
        self.assertNotIn("under all circumstances", self.text)
        self.assertNotIn("may not modify any part", self.text)

    def test_source_availability_route_does_not_contradict_notices(self) -> None:
        # The notices state repository-relative paths a tester will not
        # possess, so the licence must offer a route through the Licensor.
        body = _flat(self.sections[3][1])
        self.assertIn("that source is supplied with", body)
        self.assertIn("the Licensor will give it to you on request", body)
        self.assertIn("no more than the cost of supplying it", body)


class TesterDataAndOutputTests(unittest.TestCase):
    """The clause the product exists to protect."""

    @classmethod
    def setUpClass(cls):
        cls.sections = _sections()

    def test_outputs_are_keyed_to_data_not_to_whose_environment(self) -> None:
        # The BLOCKING adversarial finding: an MSP's report about a CLIENT
        # network fell outside the definition, and so outside every
        # protection keyed to it.
        body = _flat(self.sections[2][1])
        self.assertIn(
            "whether they describe your own environment or a network you run"
            " Atlas against for someone else",
            body,
        )
        self.assertNotIn("about your own environment:", body)

    def test_outputs_cover_material_atlas_embeds_in_them(self) -> None:
        # Measured fact: the exported topology viewer carries Atlas template
        # and viewer code inside it.
        definition = _flat(self.sections[2][1])
        self.assertIn(
            "even where Atlas builds its own templates or viewer code into"
            " them",
            definition,
        )
        nine = _flat(self.sections[9][1])
        self.assertIn(
            "Where Your Outputs contain Atlas templates, styling or viewer"
            " code",
            nine,
        )
        self.assertIn("you may share them anyway", nine)

    def test_data_and_output_ownership_are_both_disclaimed(self) -> None:
        body = _flat(self.sections[9][1])
        self.assertIn("Your Data is yours, or the relevant rights-holder's.",
                      body)
        self.assertIn("Your Outputs are yours.", body)
        self.assertIn("acquires no right in them", body)
        self.assertIn("gains no ownership by Atlas having produced them", body)

    def test_sharing_outputs_is_not_redistribution(self) -> None:
        body = _flat(self.sections[9][1])
        self.assertIn(
            "the restrictions in section 6 do not apply to Your Outputs", body
        )
        self.assertIn("is not redistribution of Atlas", body)
        self.assertIn("including with clients", body)

    def test_client_engagement_is_not_a_service_bureau(self) -> None:
        body = _flat(self.sections[6][1])
        self.assertIn(
            "Running Atlas yourself during an engagement and giving that"
            " client Your Outputs is not hosting Atlas as a service",
            body,
        )

    def test_licensor_receives_no_data_and_no_permission_to(self) -> None:
        body = _flat(self.sections[9][1])
        self.assertIn("It does not send Your Data to the Licensor", body)
        self.assertIn(
            "no permission to collect, receive or access Your Data, your"
            " credentials, or your usage",
            body,
        )
        # The corrected factual claim: rights disclaimed, not an absolute
        # assertion the feedback clause would falsify.
        self.assertNotIn("and does not receive it", body)

    def test_feedback_is_narrow_and_data_safe(self) -> None:
        body = _flat(self.sections[12][1])
        self.assertIn("You keep ownership of everything you create.", body)
        self.assertIn("only to feedback about Atlas", body)
        self.assertIn(
            "no right to your work, your inventions, Your Data or Your"
            " Outputs",
            body,
        )
        self.assertIn("Remove Your Data from anything you send", body)
        for grab in ("assign", "assignment", "all right, title"):
            self.assertNotIn(grab, body.lower(), grab)


class BoundaryClauseTests(unittest.TestCase):
    """Networks, services, branding, confidentiality, warranty, liability."""

    @classmethod
    def setUpClass(cls):
        cls.sections = _sections()
        cls.text = _text()

    def test_authorized_network_responsibility(self) -> None:
        body = _flat(self.sections[10][1])
        self.assertIn("You are responsible for having authorisation", body)
        self.assertIn("no authority over anyone else's", body)

    def test_external_service_clause_describes_and_does_not_grant(self) -> None:
        body = _flat(self.sections[11][1])
        self.assertIn("off by default", body)
        self.assertIn("only if you turn it on", body)
        self.assertIn("The Licensor is not a party to it", body)
        self.assertIn("receives nothing through it", body)
        # It must not read as a permission the tester grants the Licensor.
        self.assertNotIn("you authorise the licensor", body.lower())
        self.assertNotIn("you consent to", body.lower())

    def test_no_telemetry_or_transmission_permission_anywhere(self) -> None:
        lowered = self.text.lower()
        self.assertNotIn("telemetry", lowered)
        self.assertNotIn("usage data", lowered)
        self.assertNotIn("phone home", lowered)

    def test_branding_without_registration_claim(self) -> None:
        body = _flat(self.sections[13][1])
        self.assertIn("no rights in the names", body)
        self.assertNotIn("®", self.text)
        self.assertNotIn("registered trademark", self.text.lower())

    def test_no_confidentiality_obligation(self) -> None:
        body = _flat(self.sections[14][1])
        self.assertIn("imposes no confidentiality or non-disclosure", body)
        self.assertIn("does not mean you have agreed", body)
        self.assertIn("You may discuss Atlas", body)
        # And no obligation smuggled in elsewhere.
        lowered = _flat(self.text).lower()
        self.assertNotIn("you must keep", lowered)
        self.assertNotIn("shall not disclose", lowered)

    def test_warranty_carries_the_applicable_law_qualifier(self) -> None:
        body = _flat(self.sections[16][1])
        self.assertIn("To the extent permitted by applicable law", body)
        self.assertIn("no warranty of any kind", body)
        self.assertIn("Verify anything important independently", body)

    def test_liability_excepts_non_excludable_liability(self) -> None:
        body = _flat(self.sections[17][1])
        self.assertIn("To the extent permitted by applicable law", body)
        self.assertIn(
            "except for liability that cannot lawfully be limited or excluded",
            body,
        )

    def test_non_excludable_rights_preserved(self) -> None:
        body = _flat(self.sections[18][1])
        self.assertIn(
            "Nothing in this licence limits any right you have that cannot"
            " lawfully be limited or excluded",
            body,
        )
        self.assertIn("nothing in it limits any right a Third-Party", body)

    def test_no_governing_law_or_arbitration_invented(self) -> None:
        lowered = _flat(self.text).lower()
        for invented in ("governing law", "governed by the laws",
                         "arbitration", "exclusive jurisdiction", "venue"):
            self.assertNotIn(invented, lowered, invented)

    def test_no_licence_key_activation_or_drm(self) -> None:
        lowered = _flat(self.text).lower()
        five = _flat(self.sections[5][1]).lower()
        # These words appear ONLY in section 5's negative list.
        for token in ("licence key", "activation", "machine binding",
                      "kill switch", "expiry timer"):
            self.assertIn(token, five, token)
            self.assertEqual(
                lowered.count(token), five.count(token),
                f"{token} appears outside section 5's negative list",
            )
        self.assertNotIn(" drm", lowered)
        self.assertNotIn("entitlement", lowered)


class InternalConsistencyTests(unittest.TestCase):
    """Cross-references resolve; defined terms are used as defined."""

    @classmethod
    def setUpClass(cls):
        cls.sections = _sections()
        cls.text = _text()

    def test_sections_are_numbered_contiguously(self) -> None:
        self.assertEqual(list(range(1, 20)), sorted(self.sections))

    def test_every_cross_reference_names_an_existing_section(self) -> None:
        referenced: set[int] = set()
        for match in re.finditer(r"sections?\s+([0-9(),a-e\s]+?)(?:\.|,|;| of| and\b|$)",
                                 _flat(self.text), re.IGNORECASE):
            for number in re.findall(r"\b(\d+)\b", match.group(1)):
                referenced.add(int(number))
        self.assertTrue(referenced)
        for number in sorted(referenced):
            self.assertIn(number, self.sections,
                          f"cross-reference to non-existent section {number}")

    def test_permission_references_point_at_permissive_sections(self) -> None:
        # The defect the review caught: section 6's chapeau cited section 8,
        # whose entire body is a prohibition and which permits nothing.
        chapeau = _flat(self.sections[6][1].split(":")[0])
        self.assertIn("Except as sections 3, 7 and 9 expressly permit",
                      chapeau)
        self.assertNotIn("8", chapeau)

    def test_survival_list_only_names_existing_sections(self) -> None:
        line = next(
            l for l in self.sections[15][1].splitlines() if "survive" in l
        )
        numbers = [int(n) for n in re.findall(r"\b(\d+)\b", line)]
        self.assertTrue(numbers)
        for number in numbers:
            self.assertIn(number, self.sections)
        # The two that must survive for third-party compliance.
        self.assertIn(3, numbers)
        self.assertIn(7, numbers)

    def test_defined_terms_are_used_and_used_terms_are_defined(self) -> None:
        definitions = set(
            re.findall(r'"([^"]+)" means', _flat(self.sections[2][1]))
        )
        self.assertEqual(
            {"Atlas", "You", "The controlled beta", "Atlas-Owned Material",
             "Third-Party Components", "Your Data", "Your Outputs"},
            definitions,
        )
        after = self.text[self.text.index("3. THIRD-PARTY COMPONENTS COME FIRST"):]
        for term in ("Atlas-Owned Material", "Third-Party Component",
                     "Your Data", "Your Outputs"):
            self.assertIn(term, after, f"defined term never used: {term}")
        # A capitalised term used but never defined is the inverse defect.
        for suspicious in ("Licensed Material", "Software", "Documentation"):
            self.assertNotIn(f'"{suspicious}"', self.text)

    def test_named_files_exist(self) -> None:
        named = set(re.findall(r"\b([A-Z][A-Z0-9-]+\.txt)\b", self.text))
        self.assertIn("THIRD-PARTY-NOTICES.txt", named)
        for name in named:
            self.assertTrue((ROOT / name).is_file(), name)

    def test_licence_is_lf_and_readable_length(self) -> None:
        raw = LICENSE_PATH.read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))
        # Readable by a trusted beta tester: a deliberate owner constraint,
        # not an arbitrary bound.
        self.assertLess(len(self.text.split()), 3000)


class RepositoryAgreementTests(unittest.TestCase):
    """The rest of the repository says what the licence says."""

    def test_readme_matches_the_licence(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn("proprietary", readme)
        self.assertIn("controlled beta", readme)
        self.assertIn(OWNER, readme)
        self.assertNotIn("not yet licensed", readme)
        for overclaim in ("production ready", "generally available",
                          "commercially released", "publicly distributable"):
            self.assertNotIn(overclaim, readme, overclaim)

    def test_no_osi_classifier_claims_open_source(self) -> None:
        for classifier in _project().get("classifiers", []):
            self.assertNotIn("OSI Approved", classifier)
            self.assertNotIn("License ::", classifier)

    def test_licence_expression_is_a_valid_licenseref(self) -> None:
        from packaging.licenses import canonicalize_license_expression

        canonical = str(canonicalize_license_expression(LICENCE_EXPRESSION))
        self.assertEqual(LICENCE_EXPRESSION, canonical)
        self.assertTrue(canonical.startswith("LicenseRef-"))

    def test_no_packaging_work_landed(self) -> None:
        # A2b is not PR-B.
        for pattern in ("*.spec", "*.iss", "*.nsi", "*.wxs"):
            self.assertEqual([], list(ROOT.glob(pattern)), pattern)
        pyproject = PYPROJECT_PATH.read_text(encoding="utf-8").lower()
        for token in ("pyinstaller", "cx_freeze", "nuitka", "briefcase"):
            self.assertNotIn(token, pyproject, token)


if __name__ == "__main__":
    unittest.main()
