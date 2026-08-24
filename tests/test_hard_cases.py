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

    def test_c6_has_its_own_kind_rather_than_c3s(self):
        """C6 is two printings at the IDENTICAL collector number. C3 is two
        printings whose numbers DIFFER. It was carried as a named GAP until it
        had a kind of its own, precisely so it could never be folded into
        `alt_art_variant` -- which would have lost the distinction that makes
        it a blocking failure, while making the gate look satisfied."""
        self.assertEqual(CLASS_TO_KIND["C6"]["kind"],
                         "same_printed_number_different_treatment")
        self.assertNotEqual(CLASS_TO_KIND["C6"]["kind"],
                            CLASS_TO_KIND["C3"]["kind"])
        self.assertIn("cannot be mistaken for", CLASS_TO_KIND["C6"]["note"])

    def test_every_entry_quotes_the_definition_it_came_from(self):
        """A mapping with no definition beside it is a mapping somebody has to
        trust. Each one carries the words it was translated from so the two can
        be checked against each other."""
        for name, entry in CLASS_TO_KIND.items():
            self.assertTrue(entry.get("definition"), name)
            self.assertGreater(len(entry["definition"]), 60, name)

    def test_every_defined_class_now_has_a_kind(self):
        """C6 was the last one without. If a class is ever added without a
        kind, this fails and the gap gets named rather than absorbed."""
        for name, entry in CLASS_TO_KIND.items():
            self.assertIsNotNone(entry["kind"], f"{name} maps to nothing")

    def test_a_class_with_no_kind_would_be_reported_not_dropped(self):
        """The mechanism, kept alive with a synthetic class now that no real
        one exercises it. A tag that maps nowhere must surface as a finding."""
        kinds, unmapped = kinds_for_classes(("C1", "C99"))
        self.assertEqual(kinds, ("same_art_different_language",))
        self.assertEqual(unmapped, ("C99",))

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

    def test_a_c6_only_row_carries_exactly_its_own_kind(self):
        """Exactly one kind, and not C3's. A C6-only row picking up
        `alt_art_variant` would be the fold arriving by the back door."""
        for card in labelled():
            if classes_of(card) != ("C6",):
                continue
            kinds = set(hard_cases_of(card))
            self.assertIn("same_printed_number_different_treatment", kinds,
                          card["card_uid"])
            self.assertNotIn("alt_art_variant", kinds, card["card_uid"])

    def test_c6_rows_are_counted(self):
        """Ten One Piece base-vs-parallel pairs plus the four re-tagged
        Riftbound rows. If this ever drops, rows have gone missing or been
        re-tagged, and both need knowing."""
        c6 = [c for c in labelled() if "C6" in classes_of(c)]
        self.assertEqual(len(c6), 14)

    def test_the_gate_reads_the_plural_field(self):
        import inspect
        import tests.test_resolver_gate as gate
        source = inspect.getsource(gate.TheLabelledSetIsComplete)
        self.assertIn("hard_cases_of", source)
        self.assertNotIn('c.get("hard_case")', source,
                         "the gate still reads the single-valued field, so a "
                         "row with two classes only counts once")


class TheRiftboundAsteriskRowsAreC6(unittest.TestCase):
    """`299*/298`, `299/298`, `303*/298` and `303/298` were tagged C5 and were
    re-tagged C6 at source.

    C5 is cards that share a name and are GENUINELY DIFFERENT CARDS. These are
    two printings of ONE card, treatment the only difference -- their own notes
    say "asterisk only difference from 299/298" and "same art/rules as
    303/298". That is C6's shape exactly.

    The asterisk being printed INSIDE the number is a notation detail, not a
    different class. Riftbound writes the treatment into the number; One Piece
    writes it nowhere and leaves it to an image filename. Same relationship,
    two conventions.

    THIS TEST IS A WALL ON PURPOSE. It failed loudly while the rows were
    mis-tagged and it fails loudly if they are ever tagged back, so the next
    person to change them has to change this too and say why.
    """

    STARRED_PAIRS = ("299", "303")

    def _rows(self):
        return [c for c in labelled()
                if c["game"] == "riftbound"
                and any(c["number"].startswith(n) for n in self.STARRED_PAIRS)]

    def test_all_four_are_present(self):
        rows = self._rows()
        self.assertEqual(len(rows), 4,
                         f"expected four rows, found {[c['card_uid'] for c in rows]}")

    def test_all_four_are_c6(self):
        for card in self._rows():
            self.assertEqual(
                classes_of(card), ("C6",),
                f"{card['card_uid']} is no longer C6. If that is deliberate, "
                "say why here and in docs/OPEN_ISSUES.md -- these four were "
                "re-tagged from C5 because they are printings of ONE card, "
                "and C5 is explicitly not that.")

    def test_none_of_them_still_claims_c5s_kind(self):
        """The stale-kind check. `map-classes` recomputes `hard_cases` rather
        than merging into it, so a re-tag DROPS the kind the old class implied.
        Merging would leave these four claiming `name_is_not_unique` and
        satisfying a gate requirement they do not meet."""
        for card in self._rows():
            self.assertNotIn(
                "name_is_not_unique", card.get("hard_cases") or [],
                f"{card['card_uid']} kept C5's kind through a re-tag")

    def test_they_carry_the_c6_kind(self):
        for card in self._rows():
            self.assertIn("same_printed_number_different_treatment",
                          hard_cases_of(card), card["card_uid"])

    def test_the_correction_is_recorded_on_the_row(self):
        """Not silently rewritten. Each row says what it was and why it moved,
        because a re-tag with no trace is indistinguishable from data that was
        always that way."""
        for card in self._rows():
            self.assertIn("reclassification_note", card, card["card_uid"])
            self.assertIn("one card",
                          card["reclassification_note"].lower())

    def test_their_notes_still_say_they_are_one_card(self):
        """The evidence for the reclassification, asserted rather than
        asserted about. If these notes ever change, the reclassification loses
        its basis."""
        notes = " ".join(str(c.get("note") or "") for c in self._rows())
        self.assertIn("only difference", notes)
        self.assertIn("same art", notes)


class C6IsRequiredByTheGate(unittest.TestCase):
    """A gate that does not demand a case for C6 is missing the class it most
    needs to measure -- it is one of the three blocking failures."""

    def test_the_kind_is_in_the_required_list(self):
        import inspect
        import tests.test_resolver_gate as gate
        source = inspect.getsource(
            gate.TheLabelledSetIsComplete.test_every_hard_case_kind_is_covered)
        self.assertIn("same_printed_number_different_treatment", source)

    def test_the_set_can_satisfy_it(self):
        """Requiring a kind no row carries would make the gate unsatisfiable
        rather than demanding. Ten One Piece rows plus the four Riftbound ones
        carry it."""
        carrying = [c for c in labelled()
                    if "same_printed_number_different_treatment"
                    in hard_cases_of(c)]
        self.assertGreaterEqual(len(carrying), 14)

    def test_it_is_not_alt_art_variant(self):
        """The fold that must never happen. C3's numbers DIFFER; C6's are
        IDENTICAL, and that identity is the whole difficulty."""
        self.assertNotEqual(CLASS_TO_KIND["C6"]["kind"],
                            CLASS_TO_KIND["C3"]["kind"])


class TheKindsAreTheSchemaAndTheClassesWereAnInput(unittest.TestCase):
    """Where the two vocabularies disagree the disagreement is RECORDED, not
    reconciled. The C classes were built for a research pass; the kinds were
    derived from failure modes this repository has actually hit. Forcing a kind
    into a class it does not fit would make the taxonomy tidier and the record
    worse."""

    def test_the_two_unmatched_kinds_are_kept_and_explained(self):
        for kind in ("same_number_different_rarity", "box_code_vs_card_number"):
            self.assertIn(kind, KINDS_WITH_NO_CLASS)
            self.assertGreater(len(KINDS_WITH_NO_CLASS[kind]), 80,
                               f"{kind} is listed with no explanation of why "
                               "no class covers it")

    def test_neither_was_forced_into_a_class(self):
        mapped = {entry["kind"] for entry in CLASS_TO_KIND.values()}
        for kind in KINDS_WITH_NO_CLASS:
            self.assertNotIn(kind, mapped,
                             f"{kind} was forced into a C class")

    def test_same_number_different_rarity_is_distinguished_from_c6(self):
        """The nearest neighbour, and the reason it is not the same thing: an
        OP01-025 base SR and its parallel both read `SR`, so a differing rarity
        is a different question entirely."""
        why = KINDS_WITH_NO_CLASS["same_number_different_rarity"]
        self.assertIn("C6", why)
        self.assertIn("SR", why)


if __name__ == "__main__":
    unittest.main()
