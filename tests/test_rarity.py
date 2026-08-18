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


class EveryObservedRarityMapsToANamedBand(unittest.TestCase):
    """`rarity_band` was wrong twice. This is the assertion that pre-empts the
    third, and it found one waiting.

    The vocabularies in contracts/rarity_vocabulary.json are the DISTINCT
    `rarity` values across every card file in the apitcg per-game data
    repositories -- read from the games' own data rather than imagined. Every
    one of them must map to a named band.
    """

    # apitcg's repo name -> our game key. The two differ only where we have
    # our own code for the game (`one-piece` -> `optcg`).
    GAME_KEY = {"riftbound": "riftbound", "one-piece": "optcg",
                "pokemon": "pkmn", "gundam": "gundam", "digimon": "digimon",
                "union-arena": "union-arena",
                "dragon-ball-fusion": "dragon-ball-fusion",
                "star-wars-unlimited": "star-wars-unlimited"}

    @classmethod
    def setUpClass(cls):
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "contracts", "rarity_vocabulary.json")
        with open(path, encoding="utf-8") as handle:
            cls.vocab = json.load(handle)["games"]

    def test_the_vocabulary_covers_the_games_we_track(self):
        for game in ("riftbound", "one-piece", "pokemon"):
            self.assertIn(game, self.vocab)

    def test_every_game_in_the_vocabulary_has_a_key(self):
        """A game added by the refresher with no mapping here would be skipped
        by the coverage assertion below -- silently, which is the failure mode
        this whole file exists to prevent. `star-wars-unlimited` arrived
        exactly that way."""
        self.assertEqual(sorted(set(self.vocab) - set(self.GAME_KEY)), [])

    def test_star_wars_unlimited_is_recorded_as_empty(self):
        """The repository exists and has no cards in it. Recorded so its
        emptiness is a fact somebody read, not an omission somebody
        re-checks."""
        self.assertEqual(self.vocab["star-wars-unlimited"]["rarities"], [])

    def test_every_string_in_every_tracked_game_maps(self):
        """The headline. An unmapped string is `unknown` -- which is tracked
        and safe -- but an unmapped string in a game we KNOW about is an
        oversight, and this is where it surfaces."""
        from ingest.rarity import unmapped
        problems = {}
        for game, entry in self.vocab.items():
            missing = unmapped(entry["rarities"], game=self.GAME_KEY[game])
            if missing:
                problems[game] = missing
        self.assertEqual(problems, {},
                         "rarity strings that no table classifies: "
                         f"{problems}")

    def test_riftbound_commons_are_still_dropped(self):
        for rarity in ("Common", "Uncommon", "Rare", "Epic"):
            self.assertNotIn(
                band_of(rarity, game="riftbound", number="010/298"),
                TRACKED_BANDS, rarity)

    def test_one_piece_secret_and_treasure_rares_are_chase(self):
        for rarity in ("SEC", "TR", "SP CARD"):
            self.assertEqual(band_of(rarity, game="optcg"), "chase", rarity)

    def test_the_same_letter_means_different_things_per_game(self):
        """`L` is Leader in One Piece and Legend in Dragon Ball; `P` is Promo
        in both but `LR` is Gundam's chase and means nothing elsewhere. One
        shared table would have to pick, and picking is guessing."""
        self.assertEqual(band_of("LR", game="gundam"), "chase")
        self.assertEqual(band_of("LR", game="riftbound", number="010/298"),
                         UNKNOWN)
        self.assertEqual(band_of("Epic", game="optcg"), UNKNOWN)

    def test_gold_star_is_chase_not_rare(self):
        """`Rare Holo Star` is Gold Star -- among the most valuable Pokemon
        cards there are -- and it scored `rare` because the string contains
        the word `rare`."""
        self.assertEqual(band_of("Rare Holo Star", game="pkmn"), "chase")

    def test_trainer_gallery_exists_in_apitcgs_vocabulary(self):
        """tcgdex has no such string and apitcg does. Both are real, and a
        classifier that only knew one would drop the other."""
        self.assertNotIn("Trainer Gallery Rare Holo", TCGDEX_RARITIES)
        self.assertEqual(band_of("Trainer Gallery Rare Holo", game="pkmn"),
                         "premium")

    def test_digimon_has_no_rarity_data_at_all(self):
        """Not a classification failure -- a coverage fact. Every Digimon card
        classifies `unknown`, which is tracked, which is correct."""
        self.assertEqual(self.vocab["digimon"]["rarities"], [])
        self.assertTrue(self.vocab["digimon"]["cards_with_no_rarity"])

    def test_an_unlisted_string_is_named_not_dropped(self):
        """New sets add rarities. The correct response is to track them until
        someone classifies them, and to SAY which ones."""
        from ingest.rarity import unmapped
        self.assertEqual(unmapped(["Common", "Mythic Prismatic"],
                                  game="riftbound"), ["Mythic Prismatic"])
        self.assertEqual(
            band_of("Mythic Prismatic", game="riftbound", number="010/298"),
            UNKNOWN)
        self.assertIn(UNKNOWN, TRACKED_BANDS)


class ParallelMarkersAreMovedNotLost(unittest.TestCase):
    """Gundam writes `LR                +` and Union Arena writes `SR★★`. Both
    are the same rarity tier with a different finish, and the finish is worth
    more than the tier. Normalisation drops the marker for banding; the variant
    has to pick it up, or a parallel and its base card become one card."""

    def test_the_marker_does_not_change_the_band(self):
        self.assertEqual(band_of("LR                +", game="gundam"),
                         band_of("LR", game="gundam"))
        self.assertEqual(band_of("SR★★", game="union-arena"),
                         band_of("SR", game="union-arena"))

    def test_the_marker_becomes_a_parallel_variant(self):
        from resolve.identity import variant_from_rarity
        self.assertEqual(variant_from_rarity("LR                +"), "parallel")
        self.assertEqual(variant_from_rarity("SR★★"), "parallel")

    def test_an_unmarked_rarity_is_not_a_parallel(self):
        from resolve.identity import variant_from_rarity
        self.assertNotEqual(variant_from_rarity("LR"), "parallel")
        self.assertNotEqual(variant_from_rarity("SR"), "parallel")


class BandIsAFunctionOfTheCollectorNumber(unittest.TestCase):
    """Riftbound's `Showcase` is an umbrella covering three treatments at
    wildly different values, ALL printing the same rarity string:

        227*/221   asterisk            Signature       $300-3,090
        227/221    above the set size  Overnumbered    $75-660
        119a/298   `a` suffix          Alternate Art   $40-90

    A $3,000 card and a $50 card, indistinguishable by rarity. Checked against
    market data 2026-08-17: of the top 16 most valuable singles, every one is
    Metal, Signature, Ultimate or an event promo. No plain Overnumbered until
    #17, and zero Epics or plain Alt-Art anywhere in it.
    """

    def band(self, rarity, number, **kw):
        return band_of(rarity, game="riftbound", number=number, **kw)

    def test_the_asterisk_is_the_chase(self):
        self.assertEqual(self.band("Showcase", "227*/221"), "chase")

    def test_above_the_set_size_without_an_asterisk_is_premium(self):
        self.assertEqual(self.band("Showcase", "227/221"), "premium")

    def test_the_a_suffix_is_ordinary_alt_art(self):
        self.assertEqual(self.band("Showcase", "119a/298"), "rare")
        self.assertNotIn(self.band("Showcase", "119a/298"), TRACKED_BANDS)

    def test_one_string_three_bands(self):
        """The whole point, in one assertion."""
        bands = {self.band("Showcase", n)
                 for n in ("227*/221", "227/221", "119a/298")}
        self.assertEqual(len(bands), 3, f"the umbrella collapsed: {bands}")

    def test_the_number_outranks_a_wrong_rarity_string(self):
        """apitcg labels `299*/298` as `Alternate Art`. It is a Signature, and
        the number says so. The string is unreliable in BOTH directions."""
        self.assertEqual(self.band("Alternate Art", "299*/298"), "chase")

    def test_epic_dropped_from_premium_to_rare(self):
        """Riot's designer puts Epic at roughly one in four packs, about six a
        box, singles $5-55. My premium call was wrong."""
        self.assertEqual(self.band("Epic", "050/298"), "rare")
        self.assertNotIn(self.band("Epic", "050/298"), TRACKED_BANDS)

    def test_the_new_chase_rarities_are_chase(self):
        for rarity in ("Signature", "Metal", "Prize Wall", "Ultimate Rare"):
            self.assertEqual(self.band(rarity, "010/298"), "chase", rarity)

    def test_a_promo_is_unknown_because_the_range_spans_bands(self):
        """The `b` suffix says it is a promo and says nothing about which. A
        few dollars to $1,300 spans three bands, so it is tracked and named
        rather than banded on a coin flip."""
        self.assertEqual(self.band("Showcase", "119b/298"), UNKNOWN)
        self.assertIn(UNKNOWN, TRACKED_BANDS)
        # And the number OUTRANKS a string that would otherwise settle it: a
        # `b`-suffix Epic is a promo whose tier is unknown, not an Epic.
        self.assertEqual(self.band("Epic", "119b/298"), UNKNOWN)
        self.assertEqual(self.band("Epic", "119/298"), "rare")

    def test_tokens_and_plain_runes_are_base(self):
        self.assertEqual(self.band("Common", "T02"), "base")
        self.assertEqual(self.band("Common", "R04"), "base")

    def test_a_showcase_rune_is_not_bulk(self):
        self.assertEqual(self.band("Showcase", "R01a"), "rare")

    def test_a_bare_number_uses_the_declared_set_size(self):
        """`OGN-301` carries no denominator, so the ceiling comes from the set
        table. Origins has 298 base cards."""
        from resolve.identity import RIFTBOUND_SETS
        self.assertEqual(
            self.band("Showcase", "OGN-301",
                      set_size=RIFTBOUND_SETS["OGN"]["base"]), "premium")

    def test_without_a_set_size_a_bare_number_cannot_be_placed(self):
        """`None` is not `False`. An unknown ceiling must not file a card as
        ordinary -- it falls through to the string, which for `Showcase`
        correctly answers UNKNOWN."""
        self.assertEqual(self.band("Showcase", "OGN-301"), UNKNOWN)


class TheParserAnswersUnknowableWithNone(unittest.TestCase):
    """`above_set_size` returns None, not False, when the ceiling is unknown.

    The distinction is not currently observable through banding -- both fall
    through to the string -- so it is asserted where it IS observable. It
    matters because the next caller to ask the question will get a real answer
    or an honest None, rather than a False that means "we did not know"."""

    def parsed(self, number):
        from resolve.identity import parse_collector_number
        return parse_collector_number(number)

    def test_no_denominator_and_no_set_size_is_none(self):
        self.assertIsNone(self.parsed("OGN-301").above_set_size())

    def test_a_denominator_answers_it(self):
        self.assertIs(self.parsed("299/298").above_set_size(), True)
        self.assertIs(self.parsed("119/298").above_set_size(), False)

    def test_a_supplied_set_size_answers_it(self):
        self.assertIs(self.parsed("OGN-301").above_set_size(298), True)
        self.assertIs(self.parsed("OGN-119").above_set_size(298), False)

    def test_the_denominator_wins_over_a_supplied_size(self):
        """The number carries its own ceiling; a table is the fallback."""
        self.assertIs(self.parsed("299/298").above_set_size(9999), True)

    def test_an_unreadable_number_is_none_everywhere(self):
        parsed = self.parsed("not a number at all")
        self.assertEqual(parsed.kind, "unreadable")
        self.assertIsNone(parsed.index)
        self.assertIsNone(parsed.above_set_size(298))


class ANumberDependentGameRefusesToGuess(unittest.TestCase):
    """Declaring it in one set is the point: the next game that bands on its
    number gets added there, and every call site is already correct."""

    def test_riftbound_is_declared(self):
        from ingest.rarity import NUMBER_DEPENDENT_GAMES
        self.assertIn("riftbound", NUMBER_DEPENDENT_GAMES)

    def test_calling_without_a_number_raises(self):
        from ingest.rarity import NumberRequired
        with self.assertRaises(NumberRequired) as caught:
            band_of("Showcase", game="riftbound")
        self.assertIn("collector number", str(caught.exception))

    def test_an_empty_number_is_not_a_number(self):
        from ingest.rarity import NumberRequired
        for empty in ("", None):
            with self.assertRaises(NumberRequired):
                band_of("Showcase", game="riftbound", number=empty)

    def test_a_string_only_game_is_unaffected(self):
        """Pokemon and One Piece band on the string, and requiring a number
        there would be ceremony."""
        from ingest.rarity import NUMBER_DEPENDENT_GAMES
        self.assertNotIn("pkmn", NUMBER_DEPENDENT_GAMES)
        self.assertEqual(band_of("SEC", game="optcg"), "chase")

    def test_the_string_question_is_still_answerable_without_a_number(self):
        """`unmapped()` asks "does any table know this word", which is a
        different question and must not raise."""
        from ingest.rarity import string_band, unmapped
        self.assertEqual(string_band("Epic", "riftbound"), "rare")
        self.assertEqual(unmapped(["Epic", "Nonsense"], game="riftbound"),
                         ["Nonsense"])

    def test_a_deliberately_unknown_string_is_not_reported_as_unmapped(self):
        """`Showcase` and `Promo` map to UNKNOWN on purpose -- they are
        classified, and what they classify as is 'the string cannot say'."""
        from ingest.rarity import unmapped
        self.assertEqual(unmapped(["Showcase", "Promo"], game="riftbound"), [])


class TheRiftboundSetTableIsRecorded(unittest.TestCase):
    """Two main sets sat between Origins and Vendetta and neither was in our
    list. The apitcg data repository stops at Spiritforged, so the catalog
    source is two sets behind the game."""

    def test_all_five_sets_are_present(self):
        from resolve.identity import RIFTBOUND_SETS
        self.assertEqual(sorted(RIFTBOUND_SETS),
                         ["OGN", "RAD", "SFD", "UNL", "VEN"])

    def test_the_base_counts_are_recorded(self):
        from resolve.identity import RIFTBOUND_SETS
        self.assertEqual(RIFTBOUND_SETS["OGN"]["base"], 298)
        self.assertEqual(RIFTBOUND_SETS["SFD"]["base"], 221)
        self.assertEqual(RIFTBOUND_SETS["UNL"]["base"], 219)
        self.assertEqual(RIFTBOUND_SETS["VEN"]["base"], 166)

    def test_an_unreleased_set_has_no_invented_count(self):
        """Radiance is announced, not out. `None` rather than a guess, and
        `above_set_size` returns None rather than False when the ceiling is
        unknown."""
        from resolve.identity import RIFTBOUND_SETS
        self.assertIsNone(RIFTBOUND_SETS["RAD"]["base"])

    def test_the_chinese_first_launch_is_recorded_not_modelled(self):
        """Simplified Chinese led Origins by two months. Recorded as a fact;
        NOT added to GAME_LANGUAGES, because a ninth game/language combination
        changes the labelled-set targets and that is a scope decision."""
        from resolve.identity import (GAME_LANGUAGES, RIFTBOUND_CHINESE_LED)
        self.assertIn("OGN", RIFTBOUND_CHINESE_LED)
        self.assertEqual(GAME_LANGUAGES["riftbound"], ("EN",))
