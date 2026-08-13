"""Identity boundary tests.

Scope note: AUDIT_PROTOCOL Layer 3 also requires precision >=0.98 and recall
>=0.90 against tests/fixtures/labelled_200.json, plus a manual-review-queue
depth check. That fixture does not exist yet, so Layer 3 is NOT satisfied by
this file. What is tested here is the vocabulary boundary: that no provider
identifier can reach a card_uid, and that every language printing is a
distinct card.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.identity import (AMBIGUOUS_TOKENS, APITCG_SLUG,  # noqa: E402
                              GAME_LANGUAGES, GAMES,
                              LANGUAGES, PROVIDER_TOKENS, IdentityError,
                              TCGAPI_GAME_ID, card_uid, from_provider_slug,
                              parse_card_uid, to_apitcg_slug, to_tcgapi_game_id)


class BoundaryTests(unittest.TestCase):

    def test_no_provider_slug_can_reach_card_uid(self):
        """The whole point of the boundary.

        Slugs that coincide with an internal code (apitcg calls Riftbound
        "riftbound", so do we) are excluded: the value is valid in both
        vocabularies, so rejecting it would reject a legitimate internal code.
        """
        unambiguous = [s for s in APITCG_SLUG.values() if s not in GAMES]
        self.assertTrue(unambiguous, "no unambiguous provider slug to test")
        for slug in unambiguous:
            with self.assertRaises(IdentityError) as ctx:
                card_uid(slug, "OP01", "121", "base", "EN")
            self.assertIn("provider identifier", str(ctx.exception))

    def test_coincident_slug_is_accepted_as_an_internal_code(self):
        for token in AMBIGUOUS_TOKENS:
            self.assertIn(token, GAMES)
            lang = GAME_LANGUAGES[token][0]
            self.assertTrue(card_uid(token, "OGN", "001", "base", lang))

    def test_no_tcgapi_numeric_id_can_reach_card_uid(self):
        for game_id in TCGAPI_GAME_ID.values():
            with self.assertRaises(IdentityError):
                card_uid(game_id, "OP01", "121", "base", "EN")

    def test_internal_codes_are_accepted(self):
        uid = card_uid("optcg", "OP01", "121", "base", "EN")
        self.assertEqual(uid, "optcg:OP01:121:base:EN")
        self.assertEqual(parse_card_uid(uid)["language"], "EN")

    def test_every_language_printing_is_a_distinct_card(self):
        """CLAUDE.md non-negotiable 3, extended to all four languages."""
        uids = {lang: card_uid("pkmn", "sv3", "108", "sar", lang)
                for lang in GAME_LANGUAGES["pkmn"]}
        self.assertEqual(len(set(uids.values())), len(uids))
        self.assertNotEqual(uids["EN"], uids["JP"])
        self.assertNotEqual(uids["CN-S"], uids["CN-T"])

    def test_language_enum_includes_chinese(self):
        self.assertEqual(set(LANGUAGES), {"EN", "JP", "CN-S", "CN-T"})

    def test_riftbound_has_no_japanese_printing(self):
        """There is no Riftbound JP release; the identity layer knows it."""
        with self.assertRaises(IdentityError) as ctx:
            card_uid("riftbound", "OGN", "001", "base", "JP")
        self.assertIn("no JP printing", str(ctx.exception))

    def test_unknown_game_and_language_are_refused(self):
        with self.assertRaises(IdentityError):
            card_uid("magic", "x", "1", "base", "EN")
        with self.assertRaises(IdentityError):
            card_uid("pkmn", "x", "1", "base", "KR")

    def test_delimiter_cannot_be_smuggled_into_a_part(self):
        with self.assertRaises(IdentityError):
            card_uid("pkmn", "sv3:evil", "108", "sar", "EN")

    def test_translation_is_one_directional_and_round_trips(self):
        for internal in GAMES:
            slug = to_apitcg_slug(internal)
            self.assertNotIn(slug, GAMES if slug != internal else [])
            self.assertEqual(from_provider_slug(slug), internal)

    def test_tcgapi_ids_are_language_specific(self):
        """tcgapi models language as separate games, so the key is (game, lang)."""
        self.assertEqual(to_tcgapi_game_id("pkmn", "EN"), "55")
        self.assertEqual(to_tcgapi_game_id("pkmn", "JP"), "19")
        self.assertNotEqual(to_tcgapi_game_id("pkmn", "EN"),
                            to_tcgapi_game_id("pkmn", "JP"))

    def test_missing_catalog_entry_returns_none_not_a_guess(self):
        """No One Piece Japan entry exists in the catalog; say so, don't invent."""
        self.assertIsNone(to_tcgapi_game_id("optcg", "JP"))
        self.assertIsNone(to_tcgapi_game_id("pkmn", "CN-S"))

    def test_live_resolution_overrides_the_static_fallback(self):
        resolved = {("pkmn", "EN"): "999"}
        self.assertEqual(to_tcgapi_game_id("pkmn", "EN", resolved), "999")

    def test_rejected_tokens_are_disjoint_from_internal_codes(self):
        """PROVIDER_TOKENS holds only unambiguously-external values."""
        self.assertFalse(PROVIDER_TOKENS & set(GAMES))
        self.assertTrue(AMBIGUOUS_TOKENS <= set(GAMES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
