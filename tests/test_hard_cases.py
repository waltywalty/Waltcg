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


class ThreeShapesOfReprint(unittest.TestCase):
    """All three are C2 -- same card, one language, two sets -- and they fail
    three different ways, so the general kind is not enough on its own.

    The shapes are DECLARED from the research and CROSS-CHECKED against the
    rows: a pair claiming `same_number_new_set` must actually share a number,
    and the other two must not. A declaration nothing verifies is a comment."""

    def _pairs(self):
        from resolve.hard_cases import reprint_pair_of
        pairs = collections.defaultdict(list)
        for card in labelled():
            tag = reprint_pair_of(card)
            if tag:
                note = str(card.get("note") or "")
                full = note.split("pair ", 1)[1].split(";")[0].strip()
                pairs[full].append(card)
        return pairs

    def test_all_three_shapes_are_declared(self):
        from resolve.hard_cases import REPRINT_SHAPES
        self.assertEqual(set(REPRINT_SHAPES),
                         {"same_art_new_number", "same_number_new_set",
                          "new_art_new_number"})
        for name, entry in REPRINT_SHAPES.items():
            self.assertGreater(len(entry["what"]), 60, name)
            self.assertGreater(len(entry["risk"]), 60, name)

    def test_the_shape_declaration_matches_the_numbers(self):
        """THE CROSS-CHECK. `same_number_new_set` claims the pair shares a
        collector number; the other two claim it does not. If a pair was
        mis-declared this fails, and the declaration is worth exactly as much
        as this test."""
        from resolve.hard_cases import REPRINT_SHAPES, reprint_shape_of
        checked = 0
        for tag, cards in self._pairs().items():
            if len(cards) < 2:
                continue
            shape = reprint_shape_of(cards[0])
            if shape is None:
                continue
            declared = REPRINT_SHAPES[shape]["shares_number"]
            actual = len({c["number"] for c in cards}) == 1
            self.assertEqual(
                actual, declared,
                f"pair {tag} is declared {shape} (shares_number="
                f"{declared}) but the rows "
                + ("share" if actual else "do not share")
                + f" a number: {[c['number'] for c in cards]}")
            checked += 1
        self.assertGreater(checked, 4, "too few pairs to be checking anything")

    def test_every_pair_has_two_halves(self):
        """A reprint pair with one row in the set exercises nothing -- the
        collision needs both sides present to be a collision."""
        for tag, cards in self._pairs().items():
            self.assertGreaterEqual(len(cards), 2,
                                    f"pair {tag} has only {len(cards)} row(s)")

    def test_the_hard_shape_differs_in_exactly_one_field(self):
        """Base 4/102 against Celebrations 4/102: game, number, variant,
        language and name all identical, and ONLY `set_code` separates them.
        That is the field most likely to be dropped, defaulted or normalised
        on the way in."""
        for tag, cards in self._pairs().items():
            from resolve.hard_cases import reprint_shape_of
            if reprint_shape_of(cards[0]) != "same_number_new_set":
                continue
            self.assertEqual(len(cards), 2, tag)
            left, right = cards
            differing = [f for f in ("game", "number", "variant", "language",
                                     "name", "set_code")
                         if left[f] != right[f]]
            self.assertEqual(differing, ["set_code"],
                             f"pair {tag} differs in {differing}, not set_code "
                             "alone -- it is not this shape")

    def test_the_hard_shape_carries_its_own_kind(self):
        from resolve.hard_cases import hard_cases_of, reprint_shape_of
        rows = [c for c in labelled()
                if reprint_shape_of(c) == "same_number_new_set"]
        self.assertEqual(len(rows), 8)
        for card in rows:
            self.assertIn("same_number_different_product", hard_cases_of(card),
                          card["card_uid"])
            self.assertIn("reprint", hard_cases_of(card), card["card_uid"])

    def test_the_other_two_shapes_do_not(self):
        """`same_number_different_product` means the number was KEPT. A pair
        whose number moved must not claim it, or the kind stops meaning
        anything."""
        from resolve.hard_cases import hard_cases_of, reprint_shape_of
        for card in labelled():
            shape = reprint_shape_of(card)
            if shape in (None, "same_number_new_set"):
                continue
            self.assertNotIn("same_number_different_product",
                             hard_cases_of(card), card["card_uid"])

    def test_the_shape_is_recorded_on_the_row(self):
        from resolve.hard_cases import reprint_shape_of
        for card in labelled():
            shape = reprint_shape_of(card)
            if shape:
                self.assertEqual(card.get("reprint_shape"), shape,
                                 card["card_uid"])

    def test_all_three_shapes_are_present_in_the_set(self):
        from resolve.hard_cases import reprint_shape_of
        found = collections.Counter(reprint_shape_of(c) for c in labelled()
                                    if reprint_shape_of(c))
        self.assertEqual(set(found), {"same_art_new_number",
                                      "same_number_new_set",
                                      "new_art_new_number"},
                         f"only {sorted(found)} present")


class AMulticlassRowFillsEveryClassItCarries(unittest.TestCase):
    """The McDonald's rows are BOTH C2 and C4. A mapping that took the first
    class only would fill `reprint` and leave `promo_vs_set` short again --
    which is the bug the plural field exists to prevent, arriving from the
    other end."""

    def test_the_mcdonalds_rows_carry_both_kinds(self):
        from resolve.hard_cases import classes_of, hard_cases_of
        rows = [c for c in labelled() if classes_of(c) == ("C2", "C4")]
        self.assertGreaterEqual(len(rows), 12)
        for card in rows:
            kinds = hard_cases_of(card)
            self.assertIn("reprint", kinds, card["card_uid"])
            self.assertIn("promo_vs_set", kinds, card["card_uid"])

    def test_order_does_not_decide_which_one_survives(self):
        from resolve.hard_cases import kinds_for_classes
        forwards, _ = kinds_for_classes(("C2", "C4"))
        backwards, _ = kinds_for_classes(("C4", "C2"))
        self.assertEqual(set(forwards), set(backwards))
        self.assertEqual(len(forwards), 2)


class SimplifiedChineseIsNotASuffixedJapaneseSet(unittest.TestCase):
    """TC `SV2aF` mirrors JP `sv2a` exactly -- same collector numbers -- so its
    set code can be derived. SC `151C` cannot: it is its own scheme, National
    Pokedex order, 192 cards with a printed denominator of /151.

    Pikachu is `025/165` in JP, EN and TC, and `025/151` in SC. Deriving a CN-S
    code by suffixing a JP one would invent a set that does not exist and then
    fail to find any of its cards."""

    def test_only_traditional_chinese_derives_its_code(self):
        from resolve.identity import set_code_is_derivable
        self.assertTrue(set_code_is_derivable("CN-T"))
        self.assertFalse(set_code_is_derivable("CN-S"))
        self.assertFalse(set_code_is_derivable("EN"))
        self.assertFalse(set_code_is_derivable("JP"))

    def test_a_simplified_chinese_code_is_not_a_suffixed_japanese_one(self):
        from resolve.identity import japanese_set_code_of
        self.assertIsNone(japanese_set_code_of("151C"))
        self.assertIsNone(japanese_set_code_of("csv3C"))
        self.assertIsNone(japanese_set_code_of("CSM1aC"))

    def test_simplified_chinese_renumbers_and_traditional_does_not(self):
        from resolve.identity import renumbers, shares_parent_numbering
        self.assertTrue(renumbers("CN-S"))
        self.assertFalse(renumbers("CN-T"))
        self.assertTrue(shares_parent_numbering("CN-T"))
        self.assertFalse(shares_parent_numbering("CN-S"))

    def test_pikachu_has_the_same_index_and_a_different_denominator(self):
        """The assertion, in the set rather than in the abstract."""
        rows = {c["language"]: c for c in labelled()
                if c["game"] == "pkmn" and c["name"] == "Pikachu"
                and c["variant"] == "base"
                and c["number"].startswith("025")}
        for language in ("JP", "EN", "CN-T", "CN-S"):
            self.assertIn(language, rows, f"no base Pikachu 025 for {language}")
        self.assertEqual(rows["JP"]["number"], "025/165")
        self.assertEqual(rows["EN"]["number"], "025/165")
        self.assertEqual(rows["CN-T"]["number"], "025/165")
        self.assertEqual(rows["CN-S"]["number"], "025/151")
        self.assertEqual(len({c["card_uid"] for c in rows.values()}), 4)

    def test_the_simplified_chinese_set_follows_national_pokedex_order(self):
        """The evidence for "its own scheme". Two independently sourced
        batches, no overlapping numbers, and every index matching the National
        Pokedex."""
        DEX = {1: "Bulbasaur", 2: "Ivysaur", 3: "Venusaur", 4: "Charmander",
               5: "Charmeleon", 6: "Charizard", 7: "Squirtle", 8: "Wartortle",
               9: "Blastoise", 10: "Caterpie", 24: "Arbok", 25: "Pikachu",
               26: "Raichu", 34: "Nidoking", 38: "Ninetales"}
        checked = 0
        for card in labelled():
            if card["set_code"] != "151C" or card["variant"] != "base":
                continue
            index = int(card["number"].split("/")[0])
            if index not in DEX:
                continue
            self.assertEqual(card["name"].replace(" ex", ""), DEX[index],
                             f"{card['card_uid']} breaks Pokedex order")
            checked += 1
        self.assertGreaterEqual(checked, 15)


class OnePieceReprintsKeepTheirNumber(unittest.TestCase):
    """PRB-01 reprints of OP01-120, OP01-024, OP02-004, OP03-123 and OP04-044
    all retain their `OPxx-xxx`. `PRB01-xxx` is used ONLY for that set's new
    cards.

    So a One Piece reprint produces NO new identifier: the same number in a
    different product, with only the set code separating the two rows --
    structurally identical to Celebrations retaining Base Set numbering, which
    is why both carry `same_number_different_product` rather than each getting
    a game-specific kind."""

    def test_the_rule_is_recorded_and_scoped(self):
        from resolve.identity import reprint_keeps_its_number
        self.assertTrue(reprint_keeps_its_number("optcg"))
        self.assertFalse(reprint_keeps_its_number("pkmn"))
        self.assertFalse(reprint_keeps_its_number("riftbound"))

    def test_it_shares_a_kind_with_the_pokemon_case(self):
        """One rule, two games. A game-specific kind would have split one
        failure mode into two and hidden that they are the same shape."""
        from resolve.hard_cases import REPRINT_SHAPES
        self.assertEqual(REPRINT_SHAPES["same_number_new_set"]["kind"],
                         "same_number_different_product")

    def test_no_row_in_the_set_uses_a_prb01_number_for_a_reprint(self):
        """The rule read as a check. A row carrying `PRB01-xxx` for a card that
        exists as `OPxx-xxx` would be the invented identifier this rule says
        does not exist."""
        prb = [c for c in labelled()
               if c["game"] == "optcg" and c["number"].upper().startswith("PRB")]
        others = {c["number"] for c in labelled() if c["game"] == "optcg"}
        for card in prb:
            self.assertNotIn(
                card["number"].upper().replace("PRB01-", "OP01-"), others,
                f"{card['card_uid']} numbers a reprint in the PRB-01 scheme")
