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


if __name__ == "__main__":
    unittest.main(verbosity=2)
