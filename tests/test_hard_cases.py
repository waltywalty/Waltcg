"""The hard-case taxonomy, and the bridge between two names for it.

The labelled rows arrive tagged `C1`..`C6`; this repository has always tagged
them `hard_case`. Both are needed -- the C class says why a row was collected,
the kind says which gate requirement it satisfies -- so the mapping is a
TRANSLATION and each entry quotes the definition it came from.
"""

from __future__ import annotations

import collections
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.hard_cases import (CLASS_TO_KIND, KINDS_WITH_NO_CLASS,  # noqa: E402
                                classes_of, hard_cases_of, kinds_for_classes)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELLED = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")


def labelled():
    with open(LABELLED, encoding="utf-8") as handle:
        return json.load(handle)["cards"]


class EveryClassMapsOrIsNamed(unittest.TestCase):

    def test_the_five_that_map(self):
        self.assertEqual(CLASS_TO_KIND["C1"]["kind"],
                         "same_art_different_language")
        self.assertEqual(CLASS_TO_KIND["C2"]["kind"], "reprint")
        self.assertEqual(CLASS_TO_KIND["C3"]["kind"], "alt_art_variant")
        self.assertEqual(CLASS_TO_KIND["C4"]["kind"], "promo_vs_set")
        self.assertEqual(CLASS_TO_KIND["C5"]["kind"], "name_is_not_unique")

    def test_c6_is_a_named_gap_not_a_fold(self):
        """C6 is two printings at the IDENTICAL collector number. C3 is two
        printings whose numbers DIFFER. Folding C6 into `alt_art_variant`
        would lose exactly the distinction that makes it a blocking failure --
        and it would do so while making the gate look satisfied."""
        self.assertIsNone(CLASS_TO_KIND["C6"]["kind"])
        self.assertNotEqual(CLASS_TO_KIND["C6"]["kind"],
                            CLASS_TO_KIND["C3"]["kind"])
        self.assertIn("NO KIND EXISTS", CLASS_TO_KIND["C6"]["note"])

    def test_every_entry_quotes_the_definition_it_came_from(self):
        """A mapping with no definition beside it is a mapping somebody has to
        trust. Each one carries the words it was translated from so the two can
        be checked against each other."""
        for name, entry in CLASS_TO_KIND.items():
            self.assertTrue(entry.get("definition"), name)
            self.assertGreater(len(entry["definition"]), 60, name)

    def test_a_class_with_no_kind_is_reported_not_dropped(self):
        kinds, unmapped = kinds_for_classes(("C1", "C6"))
        self.assertEqual(kinds, ("same_art_different_language",))
        self.assertEqual(unmapped, ("C6",))

    def test_an_unknown_class_is_reported_too(self):
        """A tag nobody has defined is a finding. Silently ignoring it would
        let a whole class of rows go uncounted."""
        _kinds, unmapped = kinds_for_classes(("C9",))
        self.assertEqual(unmapped, ("C9",))

    def test_the_kinds_with_no_class_are_named_as_well(self):
        """The gap in the other direction. Two kinds this repository uses have
        no C class describing them, and that is worth knowing before somebody
        assumes the two vocabularies are the same size."""
        self.assertIn("same_number_different_rarity", KINDS_WITH_NO_CLASS)
        self.assertIn("box_code_vs_card_number", KINDS_WITH_NO_CLASS)

    def test_the_narrower_c1_kinds_are_kept_not_collapsed(self):
        """`same_number_three_languages` and `renumbered_into_combined_set`
        are C1 with the specific sub-case recorded. Collapsing them into the
        general kind would lose which of C1's three shapes a row exercises."""
        note = CLASS_TO_KIND["C1"]["note"]
        self.assertIn("same_number_three_languages", note)
        self.assertIn("renumbered_into_combined_set", note)


class AHardCaseFieldMustBePlural(unittest.TestCase):
    """`hard_case` is one field, and 18 of the 57 researched rows carry two
    classes -- `C1,C6`, `C3,C5`, `C2,C4`. A single-valued field has to drop
    one, and which one it drops silently decides which gate requirement goes
    unmet."""

    def test_both_fields_are_read(self):
        self.assertEqual(hard_cases_of({"hard_case": "reprint"}), ("reprint",))
        self.assertEqual(hard_cases_of({"hard_cases": ["a", "b"]}), ("a", "b"))

    def test_a_row_can_carry_two(self):
        card = {"hard_cases": ["alt_art_variant", "name_is_not_unique"]}
        self.assertEqual(len(hard_cases_of(card)), 2)

    def test_the_legacy_single_field_is_not_lost(self):
        """Rows seeded before the plural field existed still count."""
        card = {"hard_case": "name_is_not_unique",
                "hard_cases": ["alt_art_variant"]}
        self.assertEqual(set(hard_cases_of(card)),
                         {"alt_art_variant", "name_is_not_unique"})

    def test_duplicates_collapse(self):
        card = {"hard_case": "reprint", "hard_cases": ["reprint"]}
        self.assertEqual(hard_cases_of(card), ("reprint",))

    def test_a_row_with_neither_has_none(self):
        self.assertEqual(hard_cases_of({}), ())

    def test_the_set_actually_contains_multi_class_rows(self):
        """If it did not, the plural field would be untested by the data and
        this whole change would be theoretical."""
        multi = [c for c in labelled() if len(classes_of(c)) > 1]
        self.assertGreater(len(multi), 10,
                           "no multi-class rows, so the plural field is "
                           "carrying nothing")


class TheTranslationWasApplied(unittest.TestCase):

    def test_every_mappable_class_produced_a_kind(self):
        """The check that the translation actually ran. A row tagged C3 with
        no `alt_art_variant` means `map-classes` was never run, or was run and
        silently skipped it."""
        for card in labelled():
            kinds = set(hard_cases_of(card))
            for name in classes_of(card):
                expected = CLASS_TO_KIND.get(name, {}).get("kind")
                if expected is None:
                    continue
                self.assertIn(expected, kinds,
                              f"{card['card_uid']} is {name} but carries no "
                              f"{expected}")

    def test_no_c6_row_was_given_a_kind_it_does_not_have(self):
        """The fold that must not have happened. A C6-only row must carry no
        kind at all rather than the nearest plausible one."""
        for card in labelled():
            classes = classes_of(card)
            if classes != ("C6",):
                continue
            self.assertEqual(
                hard_cases_of(card), (),
                f"{card['card_uid']} is C6-only and was given a kind anyway")

    def test_c6_rows_exist_and_are_counted(self):
        """Ten rows are waiting on a kind name. If this ever reads zero the
        gap has been closed or the rows have gone missing, and both need
        knowing."""
        c6 = [c for c in labelled() if "C6" in classes_of(c)]
        self.assertEqual(len(c6), 10)

    def test_the_gate_reads_the_plural_field(self):
        import inspect
        import tests.test_resolver_gate as gate
        source = inspect.getsource(gate.TheLabelledSetIsComplete)
        self.assertIn("hard_cases_of", source)
        self.assertNotIn('c.get("hard_case")', source,
                         "the gate still reads the single-valued field, so a "
                         "row with two classes only counts once")


class TheRiftboundAsteriskRowsContradictTheirOwnClass(unittest.TestCase):
    """FLAGGED, NOT FIXED.

    `299*/298`, `299/298`, `303*/298` and `303/298` are tagged C5. C5 is
    defined as "cards sharing an identical printed name that are genuinely
    different cards -- different set, different art, different effect. NOT
    printings of one card."

    These four are printings of one card: the rows' own notes say "asterisk
    only difference from 299/298" and "same art/rules as 303/298". By the C5
    definition they cannot be C5.

    Left alone because reclassifying somebody's research from the outside is
    exactly the coercion this session has refused four times. The test exists
    so the contradiction cannot be forgotten -- it will fail the moment the
    rows are re-tagged, which is the point.
    """

    def _rows(self):
        return [c for c in labelled()
                if c["game"] == "riftbound" and "*" in c["number"]]

    def test_the_asterisk_rows_are_still_tagged_c5(self):
        rows = self._rows()
        self.assertTrue(rows, "no starred Riftbound rows in the set")
        for card in rows:
            self.assertIn(
                "C5", classes_of(card),
                f"{card['card_uid']} is no longer C5 -- if it was re-tagged, "
                "update or delete this test and the OPEN_ISSUES entry with it")

    def test_their_notes_say_they_are_one_card(self):
        """The evidence for the contradiction, asserted rather than asserted
        about."""
        notes = " ".join(str(c.get("note") or "") for c in self._rows())
        self.assertIn("only difference", notes)
        self.assertIn("same art", notes)


if __name__ == "__main__":
    unittest.main()
