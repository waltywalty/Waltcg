"""What a second source is corroborating, and what it silently is not.

The failure this guards against does not look like a failure. A row reaches
`verified` because two sources agree; the question nobody asks is what they
agreed ABOUT. Both instances here are cases where the second source confirms
the collector number and is structurally incapable of confirming anything
else -- and both look like confirmation of the whole row.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.corroboration import (CHECKSUM, IDENTITY_FIELDS,  # noqa: E402
                                   NOT_REACHED, PHYSICAL_CARD_PROTOCOL,
                                   PHYSICAL_CARD_PROVENANCE,
                                   STRUCTURALLY_NUMBER_ONLY, TIERS, attests,
                                   composes, field_is_established,
                                   is_structurally_number_only,
                                   physical_card_row_is_well_formed,
                                   row_is_verifiable,
                                   tier_counts_toward_verified)


class OnlyFullCorroborationCounts(unittest.TestCase):

    def test_full_counts(self):
        self.assertTrue(tier_counts_toward_verified("full"))

    def test_number_only_does_not(self):
        self.assertFalse(tier_counts_toward_verified("number_only"))

    def test_an_unknown_tier_does_not_count(self):
        """A tier nobody has classified is not a licence to assume the
        strongest one. If a new source class arrives and nobody decides what
        it can attest, the answer is no, not yes."""
        for unknown in ("partial", "probably_full", "", None, "FULL"):
            with self.subTest(tier=unknown):
                self.assertFalse(tier_counts_toward_verified(unknown))

    def test_every_tier_states_what_it_attests(self):
        for name, tier in TIERS.items():
            with self.subTest(tier=name):
                self.assertTrue(tier["what"].strip())
                self.assertIn("counts_toward_verified", tier)

    def test_a_tier_that_does_not_count_says_why(self):
        for name, tier in TIERS.items():
            if not tier["counts_toward_verified"]:
                with self.subTest(tier=name):
                    self.assertTrue(tier.get("why", "").strip(),
                                    f"{name} refuses to count and does not "
                                    f"say why")


class TheTwoStructuralCases(unittest.TestCase):
    """Arrived at from opposite directions, identical in shape."""

    def test_shared_numbering_is_structural(self):
        self.assertTrue(
            is_structurally_number_only("shared_numbering_across_languages"))

    def test_retained_number_reprint_is_structural(self):
        self.assertTrue(is_structurally_number_only("retained_number_reprint"))

    def test_an_unlisted_situation_is_not_asserted_either_way(self):
        self.assertFalse(is_structurally_number_only("some_new_source_class"))
        self.assertFalse(is_structurally_number_only(None))

    def test_each_case_names_what_it_applies_to_and_why(self):
        for name, case in STRUCTURALLY_NUMBER_ONLY.items():
            with self.subTest(case=name):
                self.assertTrue(case["applies_to"].strip())
                self.assertTrue(case["why"].strip())
                self.assertTrue(case["example"].strip())

    def test_the_reprint_case_names_a_discriminating_source(self):
        """Saying a source class cannot answer the question is only half the
        finding. The other half is which source class can -- otherwise the
        entry reads as `unknowable` and the row never gets resolved."""
        case = STRUCTURALLY_NUMBER_ONLY["retained_number_reprint"]
        self.assertIn("Limitless", case["discriminating_source"])
        self.assertIn("per printing", case["discriminating_source"])

    def test_the_reprint_case_records_the_ebay_reasoning(self):
        """The specific mechanism, not a general caution. The seller reads the
        number; the number says OP01; the listing says Romance Dawn."""
        why = STRUCTURALLY_NUMBER_ONLY["retained_number_reprint"]["why"]
        self.assertIn("OP01", why)
        self.assertIn("Romance Dawn", why)
        self.assertIn("eBay", why)


if __name__ == "__main__":
    unittest.main()


class TheAdmissionStandardIsPerField(unittest.TestCase):
    """PRE-REGISTERED before any row was collected under it.

    `number_only` meant "attests the NUMBER, silent on the PRINTING". A
    physical card is the opposite shape -- decisive about the printing, weak
    about the number. Reusing the tier name would make
    `tier_counts_toward_verified` mean two things depending on who asked, so
    attestation is recorded per FIELD instead.
    """

    def test_a_card_in_hand_settles_that_the_printing_exists(self):
        self.assertEqual(attests("physical_card", "printing_exists"),
                         "decisive")
        self.assertEqual(attests("physical_card", "language"), "decisive")
        self.assertEqual(attests("physical_card", "treatment"), "decisive")

    def test_a_card_in_hand_is_only_optical_about_its_number(self):
        """Transcription is the weak point, and it is the ONLY weak point."""
        self.assertEqual(attests("physical_card", "number"), "optical")

    def test_the_documentary_source_stays_silent_on_the_printing(self):
        """The half of the original rule that was load-bearing is untouched:
        an EN or JP list says nothing about whether a Simplified Chinese
        printing was made."""
        for field in ("printing_exists", "language", "treatment"):
            with self.subTest(field=field):
                self.assertIsNone(
                    attests("shared_numbering_reference", field))

    def test_silent_and_weak_are_different_things(self):
        """The distinction the per-source tier could not carry."""
        self.assertIsNone(attests("shared_numbering_reference", "name"))
        self.assertEqual(attests("physical_card", "name"), "optical")


class CompositionHasToBeArguedFor(unittest.TestCase):

    def test_optical_and_documentary_compose(self):
        rule = composes({"optical", "documentary"})
        self.assertIsNotNone(rule)
        self.assertIn("failure modes are disjoint", rule["why"])

    def test_a_pair_nobody_argued_for_does_not_compose(self):
        """Two partial attestations are not automatically one whole."""
        self.assertIsNone(composes({"optical", "optical"}))
        self.assertIsNone(composes({"documentary", "decisive"}))

    def test_one_channel_does_not_compose_with_itself(self):
        ok, why = field_is_established("number", ("physical_card",
                                                  "physical_card"))
        self.assertFalse(ok)
        self.assertIn("does not compose with itself", why)

    def test_the_checksum_is_required_not_decorative(self):
        """Agreement that is never checked is not agreement."""
        sources = ("physical_card", "shared_numbering_reference")
        without, why = field_is_established("number", sources,
                                            checksum_passed=False)
        self.assertFalse(without)
        self.assertIn("checksum did not run", why)
        with_it, _ = field_is_established("number", sources,
                                          checksum_passed=True)
        self.assertTrue(with_it)

    def test_the_checksum_states_how_it_can_fail(self):
        entry = CHECKSUM["name_against_number"]
        # The mechanism: a slip yields a number the record does not carry, or
        # one that names a different card.
        self.assertIn("names a different card", entry["what"])
        self.assertIn("constrain each other", entry["why_it_can_fail"])
        self.assertIn("READ FIRST", entry["protocol"])


class TheCompositeRowStandard(unittest.TestCase):

    SOURCES = ("physical_card", "shared_numbering_reference")

    def test_the_pair_with_a_checksum_reaches_verified(self):
        found = row_is_verifiable(self.SOURCES, checksum_passed=True)
        self.assertTrue(found["verified"])
        self.assertEqual(found["missing"], [])

    def test_without_the_checksum_the_number_is_not_established(self):
        found = row_is_verifiable(self.SOURCES, checksum_passed=False)
        self.assertFalse(found["verified"])
        self.assertEqual(found["missing"], ["number"])

    def test_a_card_alone_does_not_reach_verified(self):
        """The card settles the printing and cannot settle its own number."""
        found = row_is_verifiable(("physical_card",), checksum_passed=True)
        self.assertFalse(found["verified"])
        self.assertEqual(found["missing"], ["number"])

    def test_the_documentary_source_alone_reaches_nothing(self):
        found = row_is_verifiable(("shared_numbering_reference",),
                                  checksum_passed=True)
        self.assertFalse(found["verified"])
        self.assertIn("printing_exists", found["missing"])

    def test_the_composite_does_not_reach_the_simplified_chinese_name(self):
        """The gap this standard does NOT close, asserted so it cannot be
        quietly assumed closed later. The documentary side gives the EN or JP
        name for the number; confirming the SC characters render it is a
        translation, and a translation performed here is not a source."""
        found = row_is_verifiable(self.SOURCES, checksum_passed=True)
        self.assertTrue(found["verified"])
        self.assertFalse(found["name_established"])
        self.assertEqual(found["name_attestation"], "optical_only")

    def test_the_gap_is_registered_with_its_reason(self):
        gap = NOT_REACHED["cn_s_name"]
        self.assertEqual(gap["field"], "name")
        self.assertIn("no Simplified Chinese catalog source", gap["why"])
        self.assertIn("TRANSLATION", gap["not_mitigated_by"].upper())

    def test_the_name_is_not_an_identity_field(self):
        """It drives cross_language_name_disagreements, which has caught three
        errors, but it is not what the resolver is tested on."""
        self.assertNotIn("name", IDENTITY_FIELDS)
        self.assertEqual(set(IDENTITY_FIELDS),
                         {"printing_exists", "language", "treatment",
                          "number"})


class TheProtocolIsRecordedNotRemembered(unittest.TestCase):

    def test_confirming_a_drafted_row_is_forbidden_by_name(self):
        rule = PHYSICAL_CARD_PROTOCOL["reader_first"]
        self.assertIn("asking the holder to confirm", rule["forbidden"])
        self.assertIn("fixtures agreeing with the regexes", rule["why"])

    def test_an_unsure_reading_is_unresolved_not_guessed(self):
        rule = PHYSICAL_CARD_PROTOCOL["unsure_is_unresolved"]
        self.assertIn("UNRESOLVED", rule["rule"])
        self.assertIn("shorter set", rule["consequence_is_accepted"])

    def test_a_physical_card_row_must_carry_its_provenance(self):
        """A card in a hand is not re-checkable later. Unlike a URL, nobody
        can go and look again."""
        ok, problems = physical_card_row_is_well_formed({})
        self.assertFalse(ok)
        for field in PHYSICAL_CARD_PROVENANCE:
            self.assertIn(f"missing {field!r}", problems)

    def test_a_complete_row_passes(self):
        ok, problems = physical_card_row_is_well_formed(
            {"read_by": "Walton", "read_on": "2026-08-26",
             "checksum": "name_against_number",
             "name_attestation": "optical_only"})
        self.assertTrue(ok, problems)

    def test_an_unknown_checksum_is_refused_not_accepted(self):
        ok, problems = physical_card_row_is_well_formed(
            {"read_by": "Walton", "read_on": "2026-08-26",
             "checksum": "looked_right", "name_attestation": "optical_only"})
        self.assertFalse(ok)
        self.assertIn("unknown checksum 'looked_right'", problems)
