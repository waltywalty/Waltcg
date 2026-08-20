"""Four documented ways the collector number stops being a key.

Every rule here is a real, published printing practice, and every one of them
breaks the obvious implementation -- match on (game, set, number) and you get a
confident wrong card. They are separated from tests/test_resolver.py because
they are not tests of the resolver's design; they are tests that four specific
facts about four specific printings are handled, and each will still be true
when the resolver is rewritten.

    1. One Piece Treasure Rares are printed AT the base card's number.
    2. Simplified Chinese One Piece carries a box code AND a card number from a
       different set, and the two do not correspond.
    3. Serialized parallels are printed at the base number too.
    4. Simplified Chinese Pokemon RENUMBERS; Traditional Chinese SHARES the
       Japanese numbers. Opposite behaviour, same game.

Plus the one that follows from (4): the Chinese name is never a unique key.

The catalogs below are built in the test rather than read from the labelled
set, on purpose. A rule needs both sides of the collision to be tested -- the
ordinary card AND the Treasure Rare at the same number -- and the labelled set
holds only identities that were externally verified. Constructing a collision
here tests the RULE; asserting the ordinary card exists would be a claim about
the world that nobody checked.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.identity import (NUMBERING_PARENT, RENUMBERED, SET_CODE_SUFFIX,  # noqa: E402
                              VARIANTS, card_uid, renumbers,
                              shares_numbering_with, variant_from_rarity)
from resolve.resolver import Resolver                                  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELLED = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")


def labelled():
    with open(LABELLED, encoding="utf-8") as handle:
        return json.load(handle)["cards"]


def card(game, set_code, number, variant, language, name, **extra):
    return {"card_uid": card_uid(game, set_code, number, variant, language),
            "game": game, "set_code": set_code, "number": number,
            "variant": variant, "language": language, "name": name, **extra}


def record(card_like, **overrides):
    """A labelled card presented the way a provider would present it."""
    row = {"source": "probe", "game": card_like["game"],
           "language": card_like["language"], "number": card_like["number"],
           "set_code": card_like["set_code"], "name": card_like["name"]}
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 1. A Treasure Rare shares its base card's collector number
# ---------------------------------------------------------------------------


class TreasureRaresShareTheBaseNumber(unittest.TestCase):
    """Sanji OP01-013 exists as an R and as a TR. Same number, two cards,
    very different prices. Rarity and foil are the only discriminators."""

    def setUp(self):
        self.base = card("optcg", "OP01", "OP01-013", "base", "CN-S",
                         "Sanji", foil=False)
        self.treasure = card("optcg", "OP01", "OP01-013", "treasure_rare",
                             "CN-S", "Sanji", foil=True)
        self.resolver = Resolver([self.base, self.treasure])

    def test_the_two_printings_are_different_cards(self):
        self.assertNotEqual(self.base["card_uid"], self.treasure["card_uid"])
        self.assertIn("treasure_rare", VARIANTS)

    def test_the_number_alone_resolves_to_neither(self):
        """The whole point. A record with the number, the language and the
        name -- everything except which printing -- must REFUSE, because
        picking either one is a coin flip on a large price difference."""
        result = self.resolver.resolve(record(self.base))
        self.assertIsNone(result.card_uid, result.why)
        self.assertFalse(result.usable_in_signals)
        self.assertIn("ambiguous", result.why)

    def test_the_stated_rarity_is_what_separates_them(self):
        """A provider states 'TR', never our variant token. If the rarity is
        not read, the number is all that is left and the answer is a guess."""
        self.assertEqual(variant_from_rarity("TR"), "treasure_rare")
        self.assertEqual(variant_from_rarity("Treasure Rare"), "treasure_rare")
        result = self.resolver.resolve(record(self.treasure, rarity="TR"))
        self.assertEqual(result.card_uid, self.treasure["card_uid"], result.why)
        self.assertTrue(result.usable_in_signals)

    def test_the_rarity_points_at_the_base_card_too(self):
        """Both directions, or the rule is only half implemented."""
        result = self.resolver.resolve(record(self.base, rarity="R"))
        self.assertEqual(result.card_uid, self.base["card_uid"], result.why)

    def test_foil_separates_them_when_the_rarity_is_missing(self):
        """Rarity AND foil, per the documented rule -- some feeds carry the
        foil flag and no rarity at all."""
        result = self.resolver.resolve(record(self.treasure, foil=True,
                                              variant="treasure_rare"))
        self.assertEqual(result.card_uid, self.treasure["card_uid"], result.why)

    def test_an_unobserved_foil_flag_is_not_read_as_not_foil(self):
        """NULL means unobserved. Scoring a missing flag as False would push
        every card with no foil data toward the non-foil printing."""
        silent = card("optcg", "OP01", "OP01-013", "treasure_rare", "CN-S",
                      "Sanji")                       # no foil key at all
        resolver = Resolver([silent])
        result = resolver.resolve(record(silent, foil=True,
                                         variant="treasure_rare"))
        self.assertEqual(result.card_uid, silent["card_uid"])
        self.assertGreaterEqual(result.confidence, 0.9,
                                "a missing foil flag was scored as a mismatch")

    def test_the_labelled_treasure_rares_carry_the_variant(self):
        rares = [c for c in labelled() if c["variant"] == "treasure_rare"]
        self.assertGreaterEqual(len(rares), 4)
        for row in rares:
            self.assertEqual(row["language"], "CN-S")
            self.assertTrue(row.get("foil"),
                            f"{row['card_uid']} is a TR with no foil flag")


# ---------------------------------------------------------------------------
# 2. Box code and card number do not correspond
# ---------------------------------------------------------------------------


class TheBoxCodeIsNotTheSetCode(unittest.TestCase):
    """Rebecca: box code OPC-07, printed number OP04-092. PSA slabs her under
    the box code, so a graded comp names a set code this card does not have."""

    def setUp(self):
        self.rebecca = card("optcg", "OP04", "OP04-092", "treasure_rare",
                            "CN-S", "Rebecca", box_code="OPC-07", foil=True)
        self.resolver = Resolver([self.rebecca])

    def test_the_box_code_is_not_in_the_uid(self):
        """The uid is built from what is printed as the card's own number. A
        box code in the uid would make the identifier depend on which product
        the card shipped in, and reprints in another product would fork it."""
        self.assertNotIn("OPC-07", self.rebecca["card_uid"])
        self.assertEqual(self.rebecca["card_uid"],
                         "optcg:OP04:OP04-092:treasure_rare:CN-S")

    def test_both_codes_are_stored(self):
        self.assertEqual(self.rebecca["set_code"], "OP04")
        self.assertEqual(self.rebecca["box_code"], "OPC-07")
        self.assertNotEqual(self.rebecca["set_code"], self.rebecca["box_code"])

    def test_a_comp_naming_the_box_code_resolves_to_the_card(self):
        """The failure this prevents: a PSA comp says OPC-07, the card says
        OP04, the set-mismatch penalty fires, the comp is discarded, and the
        card silently has no graded comps at all."""
        result = self.resolver.resolve(record(self.rebecca, set_code="OPC-07"))
        self.assertEqual(result.card_uid, self.rebecca["card_uid"], result.why)
        self.assertTrue(result.usable_in_signals)
        self.assertIn("box code", result.why)

    def test_a_third_set_code_is_still_penalised(self):
        """Accepting the box code must not become accepting anything."""
        result = self.resolver.resolve(record(self.rebecca, set_code="OP09"))
        self.assertFalse(result.usable_in_signals,
                         f"resolved a foreign set at {result.confidence:.2f}")

    def test_the_labelled_row_carries_it(self):
        rows = [c for c in labelled() if c.get("box_code")]
        self.assertTrue(rows, "no labelled card exercises the box-code rule")
        for row in rows:
            self.assertNotIn(row["box_code"], row["card_uid"])


# ---------------------------------------------------------------------------
# 3. Serialized parallels share the base number
# ---------------------------------------------------------------------------


class SerializedParallelsShareTheBaseNumber(unittest.TestCase):
    """Nami OP01-016, Hancock OP07-051, Yamato EB02-006 -- each printed at an
    ordinary card's number, each worth a multiple of it.

    The numbers come from the research; the LANGUAGE does not, so these
    catalogs are constructed rather than claimed. What is being tested is that
    a serialized parallel and its base card cannot collide.
    """

    NUMBERS = (("OP01", "OP01-016", "Nami"),
               ("OP07", "OP07-051", "Boa Hancock"),
               ("EB02", "EB02-006", "Yamato"))

    def _pair(self, set_code, number, name, language="EN"):
        return (card("optcg", set_code, number, "base", language, name),
                card("optcg", set_code, number, "serialized", language, name,
                     serialized=True))

    def test_serialized_is_a_variant_so_the_uids_cannot_collide(self):
        self.assertIn("serialized", VARIANTS)
        for set_code, number, name in self.NUMBERS:
            base, serial = self._pair(set_code, number, name)
            self.assertNotEqual(base["card_uid"], serial["card_uid"])

    def test_the_number_alone_resolves_to_neither(self):
        for set_code, number, name in self.NUMBERS:
            base, serial = self._pair(set_code, number, name)
            result = Resolver([base, serial]).resolve(record(base))
            self.assertIsNone(result.card_uid,
                              f"{number}: picked one of two printings blind")

    def test_the_boolean_and_the_variant_cannot_disagree(self):
        """The flag is redundant with the variant deliberately: the engine
        reads the boolean, the uid reads the variant. The store enforces the
        correspondence with a CHECK; this asserts the rule it enforces."""
        for set_code, number, name in self.NUMBERS:
            base, serial = self._pair(set_code, number, name)
            self.assertTrue(serial["serialized"])
            self.assertEqual(serial["variant"], "serialized")
            self.assertFalse(base.get("serialized", False))

    def test_the_store_refuses_a_flag_that_contradicts_the_variant(self):
        import duckdb
        con = duckdb.connect(":memory:")
        with open(os.path.join(REPO, "store", "schema.sql"),
                  encoding="utf-8") as handle:
            con.execute(handle.read())
        with self.assertRaises(Exception):
            con.execute(
                "INSERT INTO cards (card_uid, game, set_code, number, variant,"
                " language, serialized, observed_at, source) VALUES "
                "('optcg:OP01:OP01-016:base:EN', 'optcg', 'OP01', 'OP01-016',"
                " 'base', 'EN', TRUE, now(), 'test')")

    def test_a_stated_rarity_of_serial_numbered_derives_the_variant(self):
        self.assertEqual(variant_from_rarity("Serial Numbered"), "serialized")
        self.assertEqual(variant_from_rarity("Serialized Parallel"), "serialized")
        # And does not swallow Riftbound's overnumbered cards on the way past.
        self.assertEqual(variant_from_rarity("Overnumbered"), "overnumbered")


# ---------------------------------------------------------------------------
# 4. SC renumbers, TC shares the Japanese numbers
# ---------------------------------------------------------------------------


class TheTwoChinesePrintingsBehaveOppositely(unittest.TestCase):
    """One game, two Chinese printings, two opposite numbering rules.

    CN-T reuses the Japanese numbers, so naive matching MERGES it into its
    Japanese parent. CN-S renumbers, so naive matching MISSES it. Any code that
    handles "Chinese Pokemon" as one behaviour is wrong for half of it, which
    is why both directions are asserted here rather than one.
    """

    def test_the_two_rules_are_recorded_and_are_opposites(self):
        self.assertEqual(shares_numbering_with("CN-T"), "JP")
        self.assertIsNone(shares_numbering_with("CN-S"))
        self.assertTrue(renumbers("CN-S"))
        self.assertFalse(renumbers("CN-T"))
        self.assertFalse(set(NUMBERING_PARENT) & RENUMBERED,
                         "a printing cannot both share and renumber")

    def test_traditional_chinese_marks_its_set_code(self):
        self.assertEqual(SET_CODE_SUFFIX["CN-T"], "F")

    def test_no_simplified_chinese_naming_rule_is_asserted(self):
        """Both verified SC set codes (151C, csv6C) end in C. Two observations
        is not a rule, and encoding it as one would make the resolver reject a
        real set the day Pokemon Shanghai names one differently."""
        self.assertNotIn("CN-S", SET_CODE_SUFFIX)

    def test_a_traditional_chinese_card_sharing_a_japanese_number_stays_distinct(self):
        """The merge case. Same number, same art, F-suffixed set -- and it must
        still be a different card, because language is in the uid."""
        parent = card("pkmn", "sv2a", "170/165", "ar", "JP", "Pikachu")
        chinese = card("pkmn", "sv2aF", "170/165", "ar", "CN-T", "Pikachu")
        self.assertEqual(parent["number"], chinese["number"])
        self.assertNotEqual(parent["card_uid"], chinese["card_uid"])
        self.assertTrue(chinese["set_code"].endswith(SET_CODE_SUFFIX["CN-T"]))

        resolver = Resolver([parent, chinese])
        for row in (parent, chinese):
            result = resolver.resolve(record(row))
            self.assertEqual(result.card_uid, row["card_uid"],
                             f"{row['language']} collapsed into the other")

    def test_dropping_the_language_makes_the_shared_number_unresolvable(self):
        """And when the language is missing, refusing is the only right answer
        -- this is precisely the case where the number identifies two cards."""
        parent = card("pkmn", "sv2a", "170/165", "ar", "JP", "Pikachu")
        chinese = card("pkmn", "sv2aF", "170/165", "ar", "CN-T", "Pikachu")
        resolver = Resolver([parent, chinese])
        stated = record(parent)
        stated.pop("language")
        self.assertIsNone(resolver.resolve(stated).card_uid)

    def test_a_japanese_number_does_not_find_the_simplified_chinese_card(self):
        """The MISS case, and it must stay a miss. SC renumbers, so a lookup by
        the Japanese number is asking for a card that does not exist under that
        number -- and returning the SC card anyway would be the merge bug
        arriving from the other side."""
        chinese = card("pkmn", "csv6C", "152/128", "sar", "CN-S",
                       "Iron Hands ex")
        resolver = Resolver([chinese])
        result = resolver.resolve(
            {"source": "probe", "game": "pkmn", "language": "CN-S",
             "number": "129/101", "set_code": "csv6C", "name": "Iron Hands ex"})
        self.assertIsNone(result.card_uid, result.why)

    def test_the_labelled_simplified_chinese_rows_do_not_claim_a_parent_number(self):
        """The Japanese counterpart numbers came back unverified. Absent is the
        correct state; a plausible guess would be indistinguishable from a
        verified one six weeks from now."""
        for row in labelled():
            if row["language"] == "CN-S":
                self.assertNotIn("jp_number", row)
                self.assertNotIn("parent_number", row)


# ---------------------------------------------------------------------------
# 5. The Chinese name is never a unique key
# ---------------------------------------------------------------------------


class TheNameIsNotAKey(unittest.TestCase):
    """Four distinct Pikachu ARs at 151C 170/151 through 173/151, one name,
    one artist. Anything keyed on the name merges four cards into one."""

    def setUp(self):
        self.cards = [c for c in labelled()
                      if c.get("hard_case") == "name_is_not_unique"]
        self.resolver = Resolver(self.cards)

    def test_there_are_four_of_them(self):
        self.assertEqual(len(self.cards), 4)
        self.assertEqual({c["number"] for c in self.cards},
                         {"170/151", "171/151", "172/151", "173/151"})

    def test_they_share_a_name_and_an_artist_and_are_still_four_cards(self):
        self.assertEqual(len({c["name"] for c in self.cards}), 1)
        self.assertEqual(len({c.get("artist") for c in self.cards}), 1)
        self.assertEqual(len({c["card_uid"] for c in self.cards}), 4)

    def test_the_artist_is_not_a_discriminator_either(self):
        """Worth stating because artist is the field most likely to be reached
        for next: all four are Oswaldo KATO."""
        self.assertEqual({c.get("artist") for c in self.cards},
                         {"Oswaldo KATO"})

    def test_each_resolves_to_itself_by_number(self):
        for row in self.cards:
            result = self.resolver.resolve(record(row))
            self.assertEqual(result.card_uid, row["card_uid"], result.why)

    def test_the_name_without_a_number_resolves_to_nothing(self):
        result = self.resolver.resolve(
            {"source": "probe", "game": "pkmn", "language": "CN-S",
             "name": "Pikachu"})
        self.assertIsNone(result.card_uid)
        self.assertFalse(result.usable_in_signals)



class ThePublishersOwnIdSaysWhichPrinting(unittest.TestCase):
    """Non-negotiable 3: every printing is a different card, never merged.

    `EB01-006`, `EB01-006_p1` and `EB01-006_p2` are three printings of one card
    at ONE collector number, and all three carry rarity `SR`. Neither the
    number nor the rarity string can separate them, so with only those two they
    collapsed into a single card_uid: 234 collisions swallowing 286 rows, 39%
    of the One Piece catalog -- and the parallels are the expensive ones.

    The suffix is Bandai's, not a provider invention: the official card-list
    images are `EB01-006.png` and `EB01-006_p1.png`.
    """

    def test_the_base_printing_implies_nothing(self):
        from resolve.identity import variant_from_external_id
        self.assertIsNone(variant_from_external_id("EB01-006", "optcg"))
        self.assertIsNone(variant_from_external_id("", "optcg"))
        self.assertIsNone(variant_from_external_id(None, "optcg"))

    def test_each_parallel_is_its_own_printing(self):
        from resolve.identity import variant_from_external_id
        self.assertEqual(variant_from_external_id("EB01-006_p1", "optcg"),
                         "parallel")
        self.assertEqual(variant_from_external_id("EB01-006_p2", "optcg"),
                         "parallel2")
        self.assertEqual(variant_from_external_id("EB01-006_p7", "optcg"),
                         "parallel7")

    def test_p1_and_the_bare_parallel_are_the_same_token(self):
        """`variant_from_rarity` already returns `parallel` for rarity `PR`.
        A card is never both, and two names for one treatment would split a
        price series in half."""
        from resolve.identity import variant_from_external_id, variant_from_rarity
        self.assertEqual(variant_from_external_id("OP01-001_p1", "optcg"),
                         variant_from_rarity("PR", game="optcg"))

    def test_reprints_are_separated_too(self):
        from resolve.identity import variant_from_external_id
        self.assertEqual(variant_from_external_id("OP09-006_r1", "optcg"),
                         "reprint")

    def test_an_unrecognised_suffix_stays_distinct_and_says_so(self):
        """NOT `base`. Falling back to base is the merge this exists to stop,
        and inventing a name for a treatment nobody has identified is the other
        way to be wrong. It stays separable and it stays labelled unknown."""
        from resolve.identity import variant_from_external_id
        got = variant_from_external_id("OP01-001_x3", "optcg")
        self.assertEqual(got, "unknown_x3")
        self.assertNotEqual(got, "base")

    def test_pokemon_is_not_given_one_piece_s_convention(self):
        """THE REASON THIS IS GAME-SCOPED. `cel25c-15_A1` through `_A4` are
        Venusaur, Here Comes Team Rocket!, Rocket's Zapdos and Claydol -- four
        DIFFERENT CARDS that Celebrations printed at collector number 15. They
        are not parallels of each other, and saying they were would be worse
        than the collision it fixed."""
        from resolve.identity import variant_from_external_id
        self.assertIsNone(variant_from_external_id("cel25c-15_A1", "pkmn"))
        self.assertIsNone(variant_from_external_id("OGN-001_p1", "riftbound"))

    def test_the_numbered_tokens_are_recognised_as_variants(self):
        from resolve.identity import VARIANTS, is_variant
        for token in VARIANTS:
            self.assertTrue(is_variant(token))
        for token in ("parallel2", "parallel7", "reprint2"):
            self.assertTrue(is_variant(token), token)
        # `parallel1` is not a token this project produces -- the first one is
        # plain `parallel` -- so accepting it would let two names for one
        # printing through and split its price series.
        for token in ("parallel1", "parallel0", "parallels", "nonsense", ""):
            self.assertFalse(is_variant(token), token)

    def test_the_three_printings_get_three_card_uids(self):
        from ingest.catalog import CatalogBuilder
        builder = CatalogBuilder(tcgapi=object(), apitcg=object())
        uids = set()
        for ident in ("EB01-006", "EB01-006_p1", "EB01-006_p2"):
            row = builder._row("optcg", "EN", "eb01",
                               {"id": ident, "number": "EB01-006",
                                "name": "Tony Tony.Chopper", "rarity": "SR"},
                               "apitcg")
            self.assertIsNotNone(row, ident)
            uids.add(row["card_uid"])
        self.assertEqual(len(uids), 3,
                         "three printings of one card merged into one card_uid")

    def test_the_number_still_wins_where_it_encodes_the_treatment(self):
        """Riftbound bands and variants on the number, and the id suffix must
        not overtake it -- ordering is most-reliable-first, not last-writer."""
        from ingest.catalog import CatalogBuilder
        builder = CatalogBuilder(tcgapi=object(), apitcg=object())
        row = builder._row("riftbound", "EN", "origins",
                           {"id": "origins-299_p1", "number": "299*/298",
                            "name": "Jinx", "rarity": "Showcase"}, "apitcg")
        self.assertEqual(row["variant"], "signature")


class TheThreeNumberingRules(unittest.TestCase):
    """The rules are worth more than the rows. They are asserted in all three
    directions, because each one fails a different way and a rule tested only
    in the direction it was written in is a rule tested once.

    Sources: external research, independent of tcgdex and apitcg.
    """

    # -- 1. Traditional Chinese: Japanese set code + F, IDENTICAL numbers ----

    def test_the_tc_set_code_is_the_jp_one_with_an_f(self):
        from resolve.identity import (OBSERVED_TC_SET_CODES,
                                      same_traditional_chinese_set,
                                      traditional_chinese_set_code)
        for japanese, printed in OBSERVED_TC_SET_CODES.items():
            self.assertTrue(same_traditional_chinese_set(japanese, printed),
                            f"{printed} was not recognised as {japanese} + F")
            self.assertEqual(
                traditional_chinese_set_code(japanese).lower(),
                printed.lower())

    def test_the_casing_is_data_not_a_rule(self):
        """`sv2a -> SV2aF` uppercases the alphabetic prefix and leaves the
        trailing `a`. Two examples do not establish that, so the comparison is
        case-insensitive and the printed forms are kept as observations."""
        from resolve.identity import (OBSERVED_TC_SET_CODES,
                                      same_traditional_chinese_set)
        self.assertEqual(OBSERVED_TC_SET_CODES["sv2a"], "SV2aF")
        self.assertEqual(OBSERVED_TC_SET_CODES["s7R"], "S7RF")
        for spelling in ("SV2AF", "sv2af", "Sv2aF"):
            self.assertTrue(same_traditional_chinese_set("sv2a", spelling))

    def test_the_jp_parent_is_recoverable(self):
        from resolve.identity import japanese_set_code_of
        self.assertEqual(japanese_set_code_of("SV2aF").lower(), "sv2a")
        self.assertEqual(japanese_set_code_of("S7RF").lower(), "s7r")

    def test_a_code_with_no_f_has_no_parent(self):
        """None is a real answer -- "not a Traditional Chinese code we
        recognise" -- and must not be confused with a failure."""
        from resolve.identity import japanese_set_code_of
        self.assertIsNone(japanese_set_code_of("sv2a"))
        self.assertIsNone(japanese_set_code_of("F"))
        self.assertIsNone(japanese_set_code_of(""))
        self.assertIsNone(japanese_set_code_of(None))

    def test_tc_must_share_the_jp_collector_number(self):
        """DIRECTION 1. Charizard ex SIR is 201/165 in BOTH Japanese and
        Traditional Chinese. The number is not a distinguishing feature here,
        and a scheme that renumbers TC would invent a card."""
        from resolve.identity import (card_uid, shares_parent_numbering,
                                      traditional_chinese_set_code)
        self.assertTrue(shares_parent_numbering("CN-T"))
        number = "201/165"
        jp = card_uid("pkmn", "sv2a", number, "sar", "JP")
        tc = card_uid("pkmn", traditional_chinese_set_code("sv2a"), number,
                      "sar", "CN-T")
        self.assertIn(f":{number}:", jp)
        self.assertIn(f":{number}:", tc)
        self.assertNotEqual(jp, tc, "the two printings collapsed into one uid")

    def test_tc_and_jp_are_never_the_same_card(self):
        """DIRECTION 2. Same art, same number, different market, different
        price series. Only `language` and the set code keep them apart."""
        from resolve.identity import card_uid, parse_card_uid
        jp = parse_card_uid(card_uid("pkmn", "sv2a", "201/165", "sar", "JP"))
        tc = parse_card_uid(card_uid("pkmn", "SV2aF", "201/165", "sar", "CN-T"))
        self.assertEqual(jp["number"], tc["number"])
        self.assertNotEqual(jp["language"], tc["language"])
        self.assertNotEqual(jp["set_code"], tc["set_code"])

    def test_a_tc_row_whose_number_differs_from_jp_is_a_contradiction(self):
        """DIRECTION 3. The rule read backwards is a check: if a labelled TC
        row carries a number its Japanese parent does not, one of the two is
        wrong, and the set is where that has to surface."""
        from resolve.identity import shares_parent_numbering
        jp_numbers = {"201/165", "173/165"}
        tc_rows = [("SV2aF", "201/165"), ("SV2aF", "173/165")]
        self.assertTrue(shares_parent_numbering("CN-T"))
        for _code, number in tc_rows:
            self.assertIn(number, jp_numbers,
                          "a Traditional Chinese row carries a number its "
                          "Japanese parent does not")

    # -- 2. English DIVERGES from the JP family on secret rares -------------

    def test_english_secret_rares_do_not_share_the_jp_number(self):
        """Same card, same art: EN 199/165, JP and TC 201/165. Three
        printings, three numbers-and-languages, three cards."""
        from resolve.identity import card_uid
        en = card_uid("pkmn", "sv2a", "199/165", "sir", "EN")
        jp = card_uid("pkmn", "sv2a", "201/165", "sar", "JP")
        tc = card_uid("pkmn", "SV2aF", "201/165", "sar", "CN-T")
        self.assertEqual(len({en, jp, tc}), 3)

    def test_matching_english_to_japanese_on_art_alone_is_a_merge(self):
        """The number is not the bridge and neither is the art. Nothing in the
        identity says these are the same picture, and nothing should -- that
        relationship belongs in `card_xref`, with a confidence, not in the uid."""
        from resolve.identity import parse_card_uid
        en = parse_card_uid("pkmn:sv2a:199/165:sir:EN")
        jp = parse_card_uid("pkmn:sv2a:201/165:sar:JP")
        self.assertNotEqual(en["number"], jp["number"])
        self.assertNotEqual(en["variant"], jp["variant"],
                            "EN prints SIR where JP prints SAR; collapsing "
                            "the two loses which market a comp came from")

    def test_the_en_number_is_not_normalised_toward_jp(self):
        """DIRECTION 3 again: no code path may rewrite 199/165 to 201/165 on
        the grounds that they are the same art."""
        from resolve.identity import parse_collector_number
        en, jp = parse_collector_number("199/165"), parse_collector_number("201/165")
        self.assertEqual((en.index, en.total), (199, 165))
        self.assertEqual((jp.index, jp.total), (201, 165))
        self.assertNotEqual(en.index, jp.index)

    # -- 3. Simplified Chinese: own codes AND own denominators --------------

    def test_simplified_chinese_renumbers(self):
        from resolve.identity import renumbers, shares_parent_numbering
        self.assertTrue(renumbers("CN-S"))
        self.assertFalse(shares_parent_numbering("CN-S"),
                         "CN-S was given CN-T's behaviour; the two are "
                         "opposite and a scheme that handles one handles the "
                         "other wrong")

    def test_the_denominator_is_its_own(self):
        """Pikachu AR is 173/165 in EN, JP and TC, and 173/151 in SC 151C.
        The INDEX matches and the TOTAL does not, which is the trap: a
        comparison on the index alone calls them the same card."""
        from resolve.identity import card_uid, parse_collector_number
        family, simplified = "173/165", "173/151"
        a, b = parse_collector_number(family), parse_collector_number(simplified)
        self.assertEqual(a.index, b.index)
        self.assertNotEqual(a.total, b.total)
        self.assertNotEqual(card_uid("pkmn", "sv2a", family, "ar", "JP"),
                            card_uid("pkmn", "151C", simplified, "ar", "CN-S"))

    def test_the_sc_denominator_is_never_normalised_to_the_jp_one(self):
        """DIRECTION 3. Rewriting 173/151 to 173/165 to "match the family"
        would file a Simplified Chinese card as a Japanese one -- the CN-S
        failure mode is a MISS, and this is how a miss becomes a merge."""
        from resolve.identity import parse_card_uid
        uid = "pkmn:151C:173/151:ar:CN-S"
        parsed = parse_card_uid(uid)
        self.assertEqual(parsed["number"], "173/151")
        self.assertNotIn("165", parsed["number"])
        self.assertEqual(parsed["set_code"], "151C")

    def test_the_sc_set_code_is_not_an_f_suffix(self):
        from resolve.identity import japanese_set_code_of
        self.assertIsNone(japanese_set_code_of("151C"),
                          "a C-suffixed Simplified Chinese code was read as a "
                          "Traditional Chinese one")

    def test_all_four_printings_of_one_art_are_four_cards(self):
        """The whole rule set in one assertion, and non-negotiable 3 stated as
        code: EN, JP, CN-T and CN-S of the same picture are four cards with
        four price series."""
        from resolve.identity import card_uid
        uids = {
            card_uid("pkmn", "sv2a", "173/165", "ar", "EN"),
            card_uid("pkmn", "sv2a", "173/165", "ar", "JP"),
            card_uid("pkmn", "SV2aF", "173/165", "ar", "CN-T"),
            card_uid("pkmn", "151C", "173/151", "ar", "CN-S"),
        }
        self.assertEqual(len(uids), 4)


class TheKoreanDenominatorIsNotTheJapaneseCard(unittest.TestCase):
    """Rayquaza VMAX s7R is 083/067. The 083/069 in listings is the KOREAN
    printing's denominator.

    Dangerous because it parses: it looks like a collector number, it reads
    like one, and it points at a printing in a market this project does not
    track. So it is not "a card we do not have" -- it is a number that must
    resolve to nothing at all."""

    def test_the_confusable_is_recorded_against_the_card(self):
        from resolve.identity import confusable_numbers
        self.assertEqual(confusable_numbers("pkmn", "s7R", "Rayquaza VMAX"),
                         ("083/069",))

    def test_the_correct_number_is_recorded_too(self):
        """A confusable with no correct value beside it tells you what is
        wrong and not what is right."""
        from resolve.identity import KNOWN_CONFUSABLE_NUMBERS
        entry = KNOWN_CONFUSABLE_NUMBERS[("pkmn", "s7R", "Rayquaza VMAX")]
        self.assertEqual(entry["correct"], "083/067")
        self.assertIn("Korean", entry["why"])
        self.assertEqual(entry["source"], "external_research")

    def test_korean_is_not_a_language_this_project_tracks(self):
        """Which is why 083/069 cannot resolve to anything. If Korean is ever
        added, this test fails and the confusable has to be re-decided."""
        from resolve.identity import LANGUAGES
        self.assertNotIn("KO", LANGUAGES)

    def test_the_two_numbers_are_not_the_same_card(self):
        from resolve.identity import card_uid
        self.assertNotEqual(card_uid("pkmn", "s7R", "083/067", "base", "JP"),
                            card_uid("pkmn", "s7R", "083/069", "base", "JP"))

    def test_a_labelled_row_for_this_card_carries_the_right_number(self):
        """The check that makes the record useful: if the card is in the
        labelled set, its number must be the Japanese one."""
        import json
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tests", "fixtures",
            "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            cards = json.load(handle)["cards"]
        from resolve.identity import KNOWN_CONFUSABLE_NUMBERS
        for (game, set_code, name), entry in KNOWN_CONFUSABLE_NUMBERS.items():
            matching = [c for c in cards
                        if (c["game"], c["set_code"], c["name"])
                        == (game, set_code, name)]
            if not matching:
                continue
            # NO row may carry a confusable. That is the invariant, and it
            # holds however many printings of the card are in the set --
            # Rayquaza VMAX s7R is here twice, 047/067 base and 083/067 alt
            # art, and both are legitimate.
            for card in matching:
                self.assertNotIn(card["number"], entry["confusable"],
                                 f"{card['card_uid']} carries a known "
                                 f"confusable number: {entry['why']}")
            # And the printing the entry is ABOUT must be the correct number,
            # not the confusable one -- otherwise the record guards nothing.
            self.assertIn(entry["correct"], {c["number"] for c in matching},
                          f"the set has {name} in {set_code} but not at "
                          f"{entry['correct']}, which is the number the "
                          "confusable record exists to protect")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheNumberBridgeGoesOneWayOnly(unittest.TestCase):
    """tcgdex sends `199`; the card says `199/165`; the labelled set records
    what the card says. Deriving printed FROM bare is exact when you know the
    set's official count.

    THE REVERSE IS FORBIDDEN and there is deliberately no function for it.
    Stripping `173/151` and `173/165` to `173` makes Simplified Chinese Pikachu
    and its English counterpart one string -- the denominator is the ONLY thing
    separating them, and discarding it recreates exactly the merge the blocking
    failures exist to catch."""

    def test_printed_is_derived_from_bare(self):
        from resolve.identity import printed_from_bare
        self.assertEqual(printed_from_bare("199", 165), "199/165")
        self.assertEqual(printed_from_bare("95", 203), "095/203")
        self.assertEqual(printed_from_bare("6", 165), "006/165")
        self.assertEqual(printed_from_bare("83", 67), "083/067")

    def test_an_already_printed_number_passes_through(self):
        """Rewriting it around a supplied total would let a wrong total
        overwrite a denominator the card itself supplied."""
        from resolve.identity import printed_from_bare
        self.assertEqual(printed_from_bare("199/165", 165), "199/165")
        self.assertEqual(printed_from_bare("173/151", 999), "173/151")

    def test_there_is_no_function_that_strips(self):
        """The absence is the guarantee. A `bare_from_printed` would be used,
        and using it once is the merge."""
        import resolve.identity as identity
        for name in dir(identity):
            self.assertNotIn(
                name.lower(),
                ("bare_from_printed", "strip_denominator", "to_bare",
                 "bare_number", "strip_total"),
                f"{name} looks like it strips a printed number to bare")

    def test_an_unknown_total_refuses_rather_than_falling_back(self):
        """A refusal is a MISS. A bare-vs-bare match is a MERGE. Only one of
        those is recoverable."""
        from resolve.identity import CannotBridge, printed_from_bare
        for total in (None, ""):
            with self.assertRaises(CannotBridge):
                printed_from_bare("199", total)

    def test_the_refusal_says_why(self):
        from resolve.identity import CannotBridge, printed_from_bare
        with self.assertRaises(CannotBridge) as caught:
            printed_from_bare("199", None)
        self.assertIn("official card count is unknown", str(caught.exception))
        self.assertIn("merge", str(caught.exception))

    def test_a_number_with_no_index_refuses(self):
        from resolve.identity import CannotBridge, printed_from_bare
        with self.assertRaises(CannotBridge):
            printed_from_bare("???", 165)


class MatchingACatalogRowToALabelledRow(unittest.TestCase):
    """Compared NUMERICALLY -- index, total, suffix, asterisk -- so a padding
    convention cannot decide the answer."""

    def test_bare_matches_its_printed_form(self):
        from resolve.identity import numbers_denote_same_printing as same
        self.assertTrue(same("199", "199/165", 165))
        self.assertTrue(same("95", "095/203", 203))
        self.assertTrue(same("6", "006/165", 165))

    def test_the_denominator_still_separates_them(self):
        """THE MERGE, in the form the bridge could have introduced. Pikachu AR
        is 173/165 in English and 173/151 in Simplified Chinese. Both catalogs
        would send `173`."""
        from resolve.identity import numbers_denote_same_printing as same
        self.assertTrue(same("173", "173/151", 151))
        self.assertFalse(same("173", "173/165", 151))
        self.assertTrue(same("173", "173/165", 165))
        self.assertFalse(same("173", "173/151", 165))

    def test_a_catalog_row_whose_set_has_no_official_count_cannot_match(self):
        """THE ASSERTION. Without the count there is nothing to compare but
        the index, and the index alone merges every printing that shares
        one."""
        from resolve.identity import CannotBridge
        from resolve.identity import numbers_denote_same_printing as same
        for labelled in ("173/151", "173/165", "199/165"):
            with self.assertRaises(CannotBridge):
                same("173", labelled, None)

    def test_two_printed_numbers_need_no_total(self):
        from resolve.identity import numbers_denote_same_printing as same
        self.assertTrue(same("199/165", "199/165"))
        self.assertFalse(same("199/165", "201/165"))
        self.assertFalse(same("173/151", "173/165"))

    def test_two_bare_numbers_are_never_compared_bare(self):
        """Both sides bare and no total is the bare-vs-bare comparison the
        whole design refuses. It must raise, not return True."""
        from resolve.identity import CannotBridge
        from resolve.identity import numbers_denote_same_printing as same
        with self.assertRaises(CannotBridge):
            same("173", "173", None)

    def test_the_asterisk_survives_the_bridge(self):
        from resolve.identity import numbers_denote_same_printing as same
        self.assertFalse(same("303/298", "303*/298"))
        self.assertTrue(same("303*/298", "303*/298"))
        self.assertFalse(same("303", "303*/298", 298))
        self.assertTrue(same("303", "303/298", 298))

    def test_set_prefixed_numbers_compare_as_given(self):
        """One Piece and Riftbound carry no denominator on either side, so
        there is nothing to bridge -- and nothing to strip."""
        from resolve.identity import numbers_denote_same_printing as same
        self.assertTrue(same("OP01-025", "OP01-025"))
        self.assertFalse(same("OP01-025", "OP01-024"))
        self.assertFalse(same("OGN-030", "OGN-030A"))

    def test_the_bridge_matches_the_real_catalog_once_totals_arrive(self):
        """End to end against the committed catalog and labelled set, with the
        counts the next Actions run will harvest. Three rows bridge; without
        the totals all three refuse, which is the state today."""
        import json
        from resolve.identity import CannotBridge
        from resolve.identity import numbers_denote_same_printing as same
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo, "ingest", "targets.json"),
                  encoding="utf-8") as handle:
            catalog = json.load(handle)
        rows = [c for k, v in catalog.items()
                if not k.startswith("_") and isinstance(v, dict)
                for c in (v.get("cards") or [])]
        pairs = [("199", "199/165", 165), ("205", "205/165", 165),
                 ("95", "095/203", 203)]
        for bare, printed, total in pairs:
            self.assertTrue(any(c["number"] == bare for c in rows),
                            f"the catalog no longer holds {bare}")
            self.assertTrue(same(bare, printed, total))
            with self.assertRaises(CannotBridge):
                same(bare, printed, None)


class TheVariantVocabularyIsPerGame(unittest.TestCase):
    """The third time this collision has appeared. Rarity letters, then the
    band tables, now variants: One Piece `SR` is a RARITY BAND -- an ordinary
    Super Rare -- and Pokemon `SR` is a PRINTING TREATMENT, a full-art textured
    finish. A shared table has to pick one, and picking is guessing."""

    def test_sr_is_pokemon_only(self):
        from resolve.identity import is_variant
        self.assertTrue(is_variant("sr", "pkmn"))
        self.assertFalse(is_variant("sr", "optcg"))
        self.assertFalse(is_variant("sr", "riftbound"))

    def test_the_rejection_says_why_not_just_unknown(self):
        """"unknown variant" sends you to guess. Naming the other game tells
        you the row is wrong rather than the vocabulary."""
        from resolve.identity import why_not_a_variant
        message = why_not_a_variant("sr", "optcg")
        self.assertIn("valid for `pkmn`", message)
        self.assertIn("RARITY BAND", message)
        self.assertIn("optcg", message)
        # And it lists what WOULD be valid, so the next step is a choice
        # rather than a search.
        self.assertIn("manga_rare", message)

    def test_a_token_no_game_has_says_so_differently(self):
        from resolve.identity import why_not_a_variant
        message = why_not_a_variant("shiny_special", "pkmn")
        self.assertIn("not a token this project produces", message)
        self.assertNotIn("valid for", message)

    def test_each_game_keeps_its_own_treatments(self):
        from resolve.identity import is_variant
        self.assertTrue(is_variant("manga_rare", "optcg"))
        self.assertFalse(is_variant("manga_rare", "pkmn"))
        self.assertTrue(is_variant("treasure_rare", "optcg"))
        self.assertTrue(is_variant("signature", "riftbound"))
        self.assertFalse(is_variant("signature", "pkmn"))
        self.assertTrue(is_variant("sp", "riftbound"))
        self.assertFalse(is_variant("sp", "optcg"))

    def test_shared_tokens_work_everywhere(self):
        from resolve.identity import SHARED_VARIANTS, is_variant
        for game in ("pkmn", "optcg", "riftbound"):
            for token in SHARED_VARIANTS:
                self.assertTrue(is_variant(token, game), f"{token}/{game}")

    def test_the_eight_new_tokens_landed(self):
        from resolve.identity import is_variant
        for token in ("sr", "ur", "hr", "rainbow_secret", "gold_secret",
                      "ssr", "holo"):
            self.assertTrue(is_variant(token, "pkmn"), token)
        self.assertTrue(is_variant("sp", "riftbound"))

    def test_manga_was_renamed_not_added(self):
        """`manga_rare` already existed. Adding `manga` beside it would give
        one treatment two names and split its price series."""
        from resolve.identity import VARIANTS, is_variant
        self.assertIn("manga_rare", VARIANTS)
        self.assertNotIn("manga", VARIANTS)
        self.assertFalse(is_variant("manga", "optcg"))

    def test_no_game_declares_a_token_the_shared_table_already_has(self):
        """A token in both places would make `variants_for` depend on dict
        ordering to say which meaning wins."""
        from resolve.identity import GAME_VARIANTS, SHARED_VARIANTS
        for game, tokens in GAME_VARIANTS.items():
            overlap = set(tokens) & set(SHARED_VARIANTS)
            self.assertEqual(overlap, set(),
                             f"{game} redeclares shared token(s) {overlap}")

    def test_a_game_agnostic_caller_accepts_everything(self):
        """None means "we do not know the game", and refusing there would make
        a game-agnostic caller reject valid rows."""
        from resolve.identity import VARIANTS, is_variant
        for token in VARIANTS:
            self.assertTrue(is_variant(token))

    def test_numbered_parallels_stay_per_game_too(self):
        from resolve.identity import is_variant
        self.assertTrue(is_variant("parallel2", "optcg"))
        self.assertFalse(is_variant("parallel0", "optcg"))
        self.assertFalse(is_variant("parallel1", "optcg"))

    def test_every_variant_in_the_labelled_set_is_valid_for_its_game(self):
        """The set is where a wrong token would actually do damage."""
        import json
        from resolve.identity import is_variant, why_not_a_variant
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo, "tests", "fixtures",
                               "labelled_200.json"), encoding="utf-8") as handle:
            cards = json.load(handle)["cards"]
        for card in cards:
            self.assertTrue(
                is_variant(card["variant"], card["game"]),
                f"{card['card_uid']}: "
                + why_not_a_variant(card["variant"], card["game"]))


class TheParserDropsSetPrefixesAndTheBridgeMustNot(unittest.TestCase):
    """`parse_collector_number("OGN-030")` reads index 30 and discards `OGN-`.
    That is fine for banding, which only ever asks about one set at a time, and
    it is a merge waiting to happen for a comparison across sets."""

    def test_the_parser_really_does_drop_it(self):
        from resolve.identity import parse_collector_number
        left = parse_collector_number("OGN-030")
        right = parse_collector_number("SFD-030")
        self.assertEqual(left.index, right.index)
        self.assertEqual(left.total, right.total)
        self.assertEqual(left.suffix, right.suffix)

    def test_the_bridge_compares_them_as_given(self):
        """Two set-prefixed numbers are compared as STRINGS, because the
        prefix is part of the number and the parse throws it away."""
        from resolve.identity import numbers_denote_same_printing as same
        self.assertFalse(same("OGN-030", "SFD-030"))
        self.assertTrue(same("OGN-030", "OGN-030"))
        self.assertTrue(same("OGN-030", "ogn-030"))

    def test_a_set_prefix_against_a_denominator_refuses(self):
        """Two different numbering schemes. Reconciling them would need a rule
        nobody has written, and inventing one silently is how the last three
        merges happened."""
        from resolve.identity import CannotBridge
        from resolve.identity import numbers_denote_same_printing as same
        with self.assertRaises(CannotBridge):
            same("OGN-030", "199/165", 165)
