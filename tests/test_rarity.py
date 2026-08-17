"""The field that was absent, filtered on anyway, and cost 8,313 cards.

tcgdex's brief card object carries `id`, `localId`, `name` and `image`. No
`rarity`. The catalog filtered on `rarity` anyway, every card scored `base`,
and a dataset of 8,313 produced zero matches. The filter was not too tight; it
was reading a field that was never there.

The rule these tests exist to hold: **an absent rarity is UNKNOWN, never "not a
chase card".** Those are different claims and only one of them is true.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.rarity import (TCGDEX_RARITIES, TRACKED_BANDS,          # noqa: E402
                           UNCLASSIFIED, UNKNOWN, band_of, normalise,
                           resolve_rarity)


class AnAbsentRarityIsUnknown(unittest.TestCase):
    """The whole bug, in one property."""

    def test_absent_is_unknown_not_base(self):
        for absent in (None, "", "   "):
            self.assertEqual(band_of(absent), UNKNOWN,
                             f"{absent!r} classified as something knowable")

    def test_unknown_is_tracked(self):
        """Tracking a card we cannot classify costs quota. Dropping one loses a
        chase card and says nothing. The trade only goes one way."""
        self.assertIn(UNKNOWN, TRACKED_BANDS)

    def test_an_unrecognised_string_is_unknown_not_base(self):
        """The maintainers say the vocabulary is still being aligned to
        official lists, so a rarity we have never seen is a rarity we have
        never seen -- not a common."""
        self.assertEqual(band_of("Quadruple Prismatic Rare"), UNKNOWN)

    def test_the_old_behaviour_would_have_dropped_everything(self):
        """Pins the bug. `rarity_band` -- the function the catalog used to
        call -- answers `base` for an absent rarity, and `base` is not
        tracked."""
        from store.cross_grader import rarity_band
        self.assertEqual(rarity_band(None), "base")
        self.assertNotIn("base", TRACKED_BANDS)


class TheEnumIsVerbatimFromSource(unittest.TestCase):
    """Fetched from tcgdex/cards-database/master/interfaces.d.ts, not
    transcribed from documentation. The two differ."""

    def test_it_has_the_full_union(self):
        self.assertEqual(len(TCGDEX_RARITIES), 43)
        self.assertEqual(len(set(TCGDEX_RARITIES)), 43, "a duplicate crept in")

    def test_the_japanese_character_rares_are_present(self):
        """Absent from the transcribed list, and they matter more here than
        anywhere: this project tracks JP and both Chinese printings."""
        self.assertIn("Character Rare", TCGDEX_RARITIES)
        self.assertIn("Character Super Rare", TCGDEX_RARITIES)
        self.assertEqual(band_of("Character Super Rare"), "chase")

    def test_triple_rare_and_promo_are_present(self):
        self.assertIn("Triple Rare", TCGDEX_RARITIES)
        self.assertIn("Promo", TCGDEX_RARITIES)

    def test_every_member_is_classified(self):
        """A member of the enum with no band is an oversight. A string OUTSIDE
        the enum with no band is `unknown`, which is safe."""
        self.assertEqual(UNCLASSIFIED, ())

    def test_matching_is_case_insensitive(self):
        """The casing is inconsistent IN THE SOURCE -- `Double rare` and
        `Ultra Rare` and `Shiny rare V` coexist -- and the maintainers say it
        is still being aligned, so nothing may depend on today's casing."""
        for spelling in ("Special illustration rare",
                         "SPECIAL ILLUSTRATION RARE",
                         "special illustration rare",
                         "Special Illustration Rare",
                         "special_illustration_rare"):
            self.assertEqual(band_of(spelling), "chase", spelling)

    def test_the_abbreviations_are_not_in_the_enum(self):
        """tcgdex normalises the Japanese-system rarities into English strings.
        Expecting `SAR` back from tcgdex is expecting the wrong vocabulary."""
        for abbreviation in ("AR", "SAR", "SR", "UR"):
            self.assertNotIn(abbreviation, TCGDEX_RARITIES)

    def test_there_is_no_trainer_gallery_rare_holo(self):
        self.assertNotIn("Trainer Gallery Rare Holo", TCGDEX_RARITIES)


class TheBandsReflectWhatIsWorthGrading(unittest.TestCase):

    def test_the_chase_tiers(self):
        for rarity in ("Special illustration rare", "Hyper rare",
                       "Secret Rare", "Ultra Rare", "ACE SPEC Rare"):
            self.assertEqual(band_of(rarity), "chase", rarity)

    def test_illustration_rare_is_premium_not_chase(self):
        self.assertEqual(band_of("Illustration rare"), "premium")

    def test_double_rare_is_not_tracked(self):
        """It reads like a chase tier and is not one -- the ordinary two-star
        `ex`, a couple of dollars, several thousand per set. Filing it as
        premium would have tracked all of them."""
        self.assertEqual(band_of("Double rare"), "rare")
        self.assertNotIn(band_of("Double rare"), TRACKED_BANDS)

    def test_pocket_rarities_are_digital_and_untracked(self):
        """Pokemon TCG Pocket is a DIGITAL game. There is no physical card to
        grade, no submission to make and no population to read. They are not
        cheap cards; they are not cards."""
        for rarity in ("One Diamond", "Crown", "Two Shiny", "Three Star"):
            self.assertEqual(band_of(rarity), "digital", rarity)
            self.assertNotIn(band_of(rarity), TRACKED_BANDS)

    def test_commons_are_still_dropped(self):
        for rarity in ("Common", "Uncommon", "None"):
            self.assertNotIn(band_of(rarity), TRACKED_BANDS, rarity)


class ProviderNativeVocabulariesAreSeparate(unittest.TestCase):
    """apitcg returns One Piece's OWN strings in `attributes.Rarity` -- `R`,
    `SR`, `SEC`, `TR` -- not tcgdex's normalised English enum. Two providers,
    two vocabularies, and `SR` scoring as `base` was the same class of bug as
    the tcgdex zero: a chase card filed as not worth tracking."""

    def test_one_piece_abbreviations_are_understood(self):
        self.assertEqual(band_of("SEC", provider_native=True), "chase")
        self.assertEqual(band_of("TR", provider_native=True), "chase")
        self.assertEqual(band_of("SR", provider_native=True), "premium")

    def test_they_are_tracked(self):
        for rarity in ("SEC", "TR", "SR"):
            self.assertIn(band_of(rarity, provider_native=True), TRACKED_BANDS,
                          rarity)

    def test_the_abbreviations_do_not_collide_with_the_word_rare(self):
        """Every one of them is a substring of `rare`."""
        self.assertEqual(band_of("Rare", provider_native=True), "rare")
        self.assertEqual(band_of("Common", provider_native=True), "base")

    def test_a_native_string_is_not_read_without_asking(self):
        """`provider_native` is opt-in. tcgdex never returns `SR`, so reading
        one from a tcgdex payload would mean something has gone wrong upstream
        and `unknown` is the honest answer."""
        self.assertEqual(band_of("SR"), UNKNOWN)


class TheEnglishFallbackIsMarked(unittest.TestCase):
    """A Chinese card that omits rarity can borrow the English card's -- ids
    are stable across languages and English is the most complete dataset. A
    borrowed rarity is a weaker claim than a printed one, and the difference
    has to survive into the row."""

    def test_a_card_with_its_own_rarity_uses_it(self):
        rarity, origin = resolve_rarity({"id": "151C-170", "rarity": "Rare"})
        self.assertEqual((rarity, origin), ("Rare", "self"))

    def test_a_card_without_one_borrows_from_english(self):
        rarity, origin = resolve_rarity(
            {"id": "151C-170"},
            {"151C-170": {"rarity": "Illustration rare"}})
        self.assertEqual(rarity, "Illustration rare")
        self.assertEqual(origin, "en_fallback")

    def test_no_english_parent_leaves_it_absent_not_guessed(self):
        rarity, origin = resolve_rarity({"id": "151C-999"}, {})
        self.assertIsNone(rarity)
        self.assertEqual(origin, "absent")
        self.assertEqual(band_of(rarity), UNKNOWN)

    def test_an_english_parent_with_no_rarity_does_not_count(self):
        rarity, origin = resolve_rarity({"id": "x"}, {"x": {"name": "no rarity"}})
        self.assertEqual(origin, "absent")

    def test_normalise_is_stable(self):
        self.assertEqual(normalise("Special illustration rare"),
                         normalise("SPECIAL_ILLUSTRATION-RARE"))
        self.assertEqual(normalise(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
