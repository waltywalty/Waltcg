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
                                   ILLEGIBLE_GLYPH_ROUTE,
                                   READING_METHODS,
                                   SECOND_OPTICAL_READING,
                                   reading_is_re_checkable,
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
            {"reading_method": "direct", "read_by": "Walton",
             "read_on": "2026-08-26", "checksum": "name_against_number",
             "name_attestation": "optical_only"})
        self.assertTrue(ok, problems)

    def test_an_unknown_checksum_is_refused_not_accepted(self):
        ok, problems = physical_card_row_is_well_formed(
            {"reading_method": "direct", "read_by": "Walton",
             "read_on": "2026-08-26", "checksum": "looked_right",
             "name_attestation": "optical_only"})
        self.assertFalse(ok)
        self.assertIn("unknown checksum 'looked_right'", problems)


class PhotographingIsStillOneChannel(unittest.TestCase):
    """A photograph removes the holder's transcription step on the one field
    with no checksum. It does NOT add a channel: same optical evidence, one
    artifact, one reading."""

    PHOTO = {"reading_method": "photograph", "read_by": "Roger",
             "imaged_by": "Walton", "image_ref": "sha256:9f2c",
             "read_on": "2026-08-26", "checksum": "name_against_number",
             "name_attestation": "optical_only"}
    DIRECT = {"reading_method": "direct", "read_by": "Walton",
              "read_on": "2026-08-26", "checksum": "name_against_number",
              "name_attestation": "optical_only"}

    def test_both_methods_are_the_same_channel(self):
        """The tier does not move. `physical_card` is optical about the name
        however the glyphs reached the reader."""
        self.assertEqual(attests("physical_card", "name"), "optical")
        self.assertEqual(attests("physical_card", "number"), "optical")

    def test_a_second_optical_reading_does_not_promote_the_field(self):
        """Two eyes on one artifact share every failure the artifact has."""
        self.assertFalse(SECOND_OPTICAL_READING["raises_the_tier"])
        self.assertIsNone(composes({"optical", "optical"}))

    def test_the_photograph_records_two_roles_not_one_name(self):
        """The photographer owns WHICH CARD and whether it is legible; the
        reader owns transcription. One field for both would lose exactly the
        distinction that makes recording them worth anything."""
        self.assertEqual(READING_METHODS["photograph"]["roles"],
                         ("imaged_by", "read_by"))
        self.assertEqual(READING_METHODS["direct"]["roles"], ("read_by",))

    def test_a_photograph_without_a_photographer_is_refused(self):
        row = dict(self.PHOTO)
        del row["imaged_by"]
        ok, problems = physical_card_row_is_well_formed(row)
        self.assertFalse(ok)
        self.assertIn("missing 'imaged_by', required when reading_method is "
                      "'photograph'", problems)

    def test_a_direct_reading_may_not_claim_a_photographer(self):
        ok, problems = physical_card_row_is_well_formed(
            dict(self.DIRECT, imaged_by="Walton"))
        self.assertFalse(ok)
        self.assertIn("nothing was photographed", " ".join(problems))

    def test_an_unknown_method_is_refused_not_guessed(self):
        ok, problems = physical_card_row_is_well_formed(
            dict(self.DIRECT, reading_method="scanned"))
        self.assertFalse(ok)
        self.assertIn("unknown reading_method 'scanned'", problems)

    def test_the_method_must_be_stated_not_inferred_from_which_fields_exist(self):
        row = dict(self.PHOTO)
        del row["reading_method"]
        ok, problems = physical_card_row_is_well_formed(row)
        self.assertFalse(ok)
        self.assertIn("missing 'reading_method'", problems)

    def test_both_well_formed_shapes_pass(self):
        for name, row in (("photograph", self.PHOTO), ("direct", self.DIRECT)):
            with self.subTest(method=name):
                ok, problems = physical_card_row_is_well_formed(row)
                self.assertTrue(ok, problems)


class TheImageMakesTheReadingAuditable(unittest.TestCase):
    """The standard says a card in a hand is not re-checkable -- unlike a URL,
    nobody can go and look again. A photograph changes that."""

    def test_a_referenced_photograph_is_re_checkable(self):
        self.assertTrue(reading_is_re_checkable(
            PhotographingIsStillOneChannel.PHOTO))

    def test_a_direct_reading_is_not(self):
        self.assertFalse(reading_is_re_checkable(
            PhotographingIsStillOneChannel.DIRECT))

    def test_a_photograph_nobody_can_find_again_is_a_card_in_a_hand(self):
        row = dict(PhotographingIsStillOneChannel.PHOTO)
        del row["image_ref"]
        self.assertFalse(reading_is_re_checkable(row))

    def test_re_checkable_is_provenance_not_tier(self):
        """It makes the reading auditable. It does not make the evidence
        stronger, and nothing about the composition changes."""
        self.assertTrue(READING_METHODS["photograph"]["re_checkable"])
        self.assertIn("does not raise the tier",
                      READING_METHODS["photograph"]["why"])
        sources = ("physical_card", "shared_numbering_reference")
        found = row_is_verifiable(sources, checksum_passed=True)
        self.assertEqual(found["name_attestation"], "optical_only")


class TheIllegibleGlyphRouteIsClosed(unittest.TestCase):
    """A photograph is not the forbidden pattern -- it carries no prior of the
    reader's to agree with. But it opens a new route back to it, and the route
    is short enough to walk without noticing."""

    def test_asking_the_holder_to_confirm_a_candidate_is_named_and_forbidden(self):
        route = ILLEGIBLE_GLYPH_ROUTE
        self.assertIn("is this", route["the_temptation"])
        self.assertIn("confirmation against a prior",
                      route["why_it_is_forbidden"])

    def test_it_is_identified_as_the_same_defect_by_another_door(self):
        self.assertIn("drafted-row", ILLEGIBLE_GLYPH_ROUTE["why_it_is_forbidden"])

    def test_the_permitted_alternatives_are_stated(self):
        instead = ILLEGIBLE_GLYPH_ROUTE["what_to_do_instead"]
        self.assertIn("fresh photograph", instead)
        self.assertIn("UNRESOLVED", instead)

    def test_reading_aloud_without_a_candidate_is_still_a_reading(self):
        """The distinction that keeps the rule usable: being asked `what does
        this say` is a reading; being asked `is this X` is a confirmation."""
        instead = ILLEGIBLE_GLYPH_ROUTE["what_to_do_instead"]
        self.assertIn("WITHOUT being offered a candidate", instead)
        self.assertIn("not a confirmation", instead)
