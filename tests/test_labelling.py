"""The catalog builder and the candidate/review loop.

The property that matters most here is NEGATIVE: the labelled set must not be
generated from the catalogs the resolver reads, because scoring a resolver
against its own inputs measures agreement, not correctness. So these tests
assert that the tools PROPOSE and never LABEL, and that every accepted row
records a human verdict.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resolve.label_cli as CLI                                    # noqa: E402
from ingest.base import Adapter, AdapterGaveUp                     # noqa: E402
from ingest.adapters import ApiTcgAdapter, TcgApiAdapter  # noqa: E402
from ingest.catalog import CatalogBuilder, _variant_of, to_targets  # noqa: E402
from resolve.candidates import (MIN_PER_COMBO, TARGET_PER_COMBO,   # noqa: E402
                                TARGET_TOTAL, generate, shortfall)


def card(uid, game, set_code, number, variant, language, name,
         rarity="Special Illustration Rare"):
    return {"card_uid": uid, "game": game, "set_code": set_code,
            "number": number, "variant": variant, "language": language,
            "name": name, "rarity": rarity}


CATALOG = [
    card("pkmn:sv4:200/200:sir:EN", "pkmn", "sv4", "200/200", "sir", "EN", "Pikachu ex"),
    card("pkmn:sv4:200/200:sir:JP", "pkmn", "sv4", "200/200", "sir", "JP", "Pikachu ex"),
    card("pkmn:sv4:200/200:base:EN", "pkmn", "sv4", "200/200", "base", "EN", "Pikachu ex"),
    card("pkmn:sv5:015/015:sir:EN", "pkmn", "sv5", "015/015", "sir", "EN", "Pikachu ex"),
    card("pkmn:P:P-009:promo:EN", "pkmn", "P", "P-009", "promo", "EN", "Pikachu ex", "Promo"),
]


class TheCatalogFiltersToWhatIsWorthGrading(unittest.TestCase):

    def test_commons_are_dropped(self):
        """A $2 common cannot repay a $79.99 submission at any probability, so
        tracking it spends quota to learn nothing."""
        builder = CatalogBuilder(tcgapi=Adapter(), apitcg=Adapter())
        for rarity in ("Common", "Uncommon", "Rare", "Double Rare"):
            row = builder._row("pkmn", "EN", "sv4",
                               {"rarity": rarity, "number": "1/200",
                                "name": "Rattata"}, "tcgapi")
            self.assertIsNone(row, f"{rarity} should not be tracked")

    def test_chase_and_premium_are_kept(self):
        builder = CatalogBuilder(tcgapi=Adapter(), apitcg=Adapter())
        for rarity in ("Special Illustration Rare", "SAR", "Manga Rare",
                       "Illustration Rare", "Alt Art"):
            row = builder._row("pkmn", "EN", "sv4",
                               {"rarity": rarity, "number": "200/200",
                                "name": "Pikachu ex"}, "tcgapi")
            self.assertIsNotNone(row, f"{rarity} should be tracked")

    def test_the_variant_is_guessed_from_the_rarity(self):
        self.assertEqual(_variant_of("Manga Rare", ""), "manga_rare")
        self.assertEqual(_variant_of("Special Illustration Rare", ""), "sir")
        self.assertEqual(_variant_of("SAR", ""), "sar")
        self.assertEqual(_variant_of("Promo", ""), "promo")
        self.assertEqual(_variant_of("Double Rare", ""), "base")

    def test_a_combo_with_no_catalog_source_is_a_recorded_gap(self):
        """One Piece Japan is absent from tcgapi's game list entirely, and the
        three Chinese printings have no source at all. A shorter list is not
        the same fact as an unreachable source."""
        # The REAL adapter classes with a dead transport, not a bare Adapter
        # stub. A stub that lacks the methods the builder calls tests the stub.
        import tempfile

        def dead(_url, _headers):
            raise OSError("no network")

        def build_dead(cls):
            return cls(raw_root=tempfile.mkdtemp(), sleep=lambda _s: None,
                       transport=dead)

        builder = CatalogBuilder(tcgapi=build_dead(TcgApiAdapter),
                                 apitcg=build_dead(ApiTcgAdapter))
        builder.build([("optcg", "JP"), ("pkmn", "CN-T")])
        reasons = {g["combo"]: g["reason"] for g in builder.gaps}
        self.assertIn("optcg:JP", reasons)
        self.assertIn("pkmn:CN-T", reasons)

    def test_targets_route_pokemon_and_the_rest_to_different_sources(self):
        """PokemonPriceTracker is Pokemon-only by construction; PriceCharting
        covers what it does not. Sending every card to every source would burn
        quota on guaranteed misses."""
        catalog = {"pkmn:EN": {"sources": ["tcgapi"], "cards": [
                       dict(CATALOG[0], external_id="1")]},
                   "optcg:EN": {"sources": ["tcgapi"], "cards": [
                       dict(card("optcg:OP01:OP01-001:base:EN", "optcg", "OP01",
                                 "OP01-001", "base", "EN", "Luffy"),
                            external_id="2")]}}
        targets = to_targets(catalog, [])
        ppt = {c["card_uid"] for c in targets["pokemonpricetracker"]["cards"]}
        pc = {c["card_uid"] for c in targets["pricecharting"]["cards"]}
        self.assertEqual(ppt, {"pkmn:sv4:200/200:sir:EN"})
        self.assertEqual(pc, {"optcg:OP01:OP01-001:base:EN"})

    def test_targets_carry_identities_and_never_prices(self):
        """Checked on the CARD ENTRIES, not the whole document: the file's own
        note says "no prices" and one source is called pricecharting, so a
        substring scan of the blob flags itself."""
        catalog = {"pkmn:EN": {"sources": ["tcgapi"],
                               "cards": [dict(CATALOG[0], external_id="1")]}}
        targets = to_targets(catalog, [])
        allowed = {"card_uid", "game", "language", "name", "number",
                   "set_code", "external_id", "game_id"}
        for source, entry in targets.items():
            if not isinstance(entry, dict) or "cards" not in entry:
                continue
            for row in entry["cards"]:
                extra = set(row) - allowed
                self.assertFalse(extra, f"{source} target carries {extra}")


class CandidatesAreWeightedTowardWhatBreaksResolution(unittest.TestCase):

    def setUp(self):
        self.out = generate(CATALOG)
        self.ideas = [i for ideas in self.out.values() for i in ideas]

    def test_a_random_sample_is_not_what_is_proposed(self):
        """Every proposal carries a reason, and the reason is a known failure
        mode. A random sample of a card universe is overwhelmingly cards that
        resolve trivially."""
        self.assertTrue(self.ideas)
        for idea in self.ideas:
            self.assertTrue(idea.why)
            self.assertIn(idea.priority,
                          ("same_art_across_languages", "reprint_across_sets",
                           "alt_art_vs_base", "promo_vs_set",
                           "lowest_confidence"))

    def test_the_cross_language_pair_is_surfaced(self):
        kinds = {i.priority for i in self.ideas}
        self.assertIn("same_art_across_languages", kinds)

    def test_the_reprint_is_surfaced(self):
        self.assertIn("reprint_across_sets", {i.priority for i in self.ideas})

    def test_every_proposal_carries_the_resolvers_own_answer(self):
        """So the human adjudicates rather than types."""
        for idea in self.ideas:
            record = idea.as_dict()
            self.assertIn("resolver_proposed", record)
            self.assertIn("resolver_confidence", record)
            self.assertIsNone(record["verdict"],
                              "a proposal must not arrive pre-labelled")

    def test_cross_language_proposals_name_their_siblings(self):
        for idea in self.ideas:
            if idea.priority == "same_art_across_languages":
                self.assertTrue(idea.siblings,
                                "a merge candidate must show what it could "
                                "merge WITH")

    def test_already_labelled_cards_are_not_proposed_again(self):
        seen = {CATALOG[0]["card_uid"]}
        again = generate(CATALOG, seen=seen)
        proposed = {i.card["card_uid"] for ideas in again.values() for i in ideas}
        self.assertNotIn(CATALOG[0]["card_uid"], proposed)

    def test_a_combo_the_catalog_cannot_reach_reports_a_shortfall(self):
        short = shortfall(self.out)
        self.assertIn("optcg:CN-S", short)
        self.assertEqual(short["optcg:CN-S"]["have"], 0)


class TheHumanBreaksTheCircle(unittest.TestCase):
    """A set generated from the resolver's own inputs measures agreement, not
    correctness. Every row must record a human verdict."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.catalog = os.path.join(self.tmp, "catalog.json")
        self.queue = os.path.join(self.tmp, "queue.json")
        json.dump({"cards": CATALOG}, open(self.catalog, "w"))
        self._real = CLI.LABELLED
        CLI.LABELLED = os.path.join(self.tmp, "labelled.json")
        json.dump({"cards": []}, open(CLI.LABELLED, "w"))

    def tearDown(self):
        CLI.LABELLED = self._real

    def _run(self, answers):
        CLI.propose(self.catalog, self.queue)
        it = iter(answers)
        CLI.review(self.queue, decide=lambda c: next(it, None))
        return json.load(open(CLI.LABELLED))

    def test_a_confirmation_records_that_it_was_confirmed(self):
        out = self._run(["confirm"])
        self.assertEqual(out["cards"][0]["adjudication"], "confirmed")

    def test_a_correction_records_what_the_resolver_said(self):
        """The disagreement is the most valuable row in the set and must not be
        lost by overwriting it."""
        out = self._run(["pkmn:sv4:200/200:base:EN"])
        row = out["cards"][0]
        self.assertEqual(row["adjudication"], "corrected")
        self.assertNotEqual(row["card_uid"], row["resolver_proposed"])
        self.assertIsNotNone(row["resolver_proposed"])

    def test_a_rejection_adds_nothing(self):
        out = self._run(["reject"])
        self.assertEqual(out["cards"], [])

    def test_a_skip_leaves_it_pending(self):
        CLI.propose(self.catalog, self.queue)
        CLI.review(self.queue, decide=lambda c: None)
        queue = json.load(open(self.queue))
        self.assertTrue(all(c["verdict"] is None for c in queue["candidates"]))

    def test_every_accepted_row_says_a_human_reviewed_it(self):
        out = self._run(["confirm", "confirm", "confirm"])
        for row in out["cards"]:
            self.assertIn("human review", row["verified_from"])

    def test_the_priority_becomes_a_hard_case_tag(self):
        out = self._run(["confirm", "confirm", "confirm", "confirm", "confirm"])
        tags = {r.get("hard_case") for r in out["cards"]}
        self.assertIn("same_art_different_language", tags)


class TheSizingIsDeliberate(unittest.TestCase):

    def test_the_target_is_250_not_200(self):
        """200 clears 0.98 only on a ZERO-error sweep (lower bound 0.9851).
        One wrong match drops it to 0.9765 and the claim fails. 250 survives
        one error at 0.9812."""
        self.assertEqual(TARGET_TOTAL, 250)
        self.assertEqual(sum(TARGET_PER_COMBO.values()), TARGET_TOTAL)

    def test_no_combo_is_below_the_detection_floor(self):
        for combo, want in TARGET_PER_COMBO.items():
            self.assertGreaterEqual(want, MIN_PER_COMBO, combo)

    def test_the_fuzzy_only_combos_are_over_weighted_relative_to_universe(self):
        """The three Chinese printings are a tiny share of the card universe
        and get 34% of the labelled set, because no Western source carries
        them -- so they can ONLY resolve fuzzily, and the fuzzy path is the
        only path that can be wrong."""
        fuzzy_only = ("optcg:CN-S", "pkmn:CN-S", "pkmn:CN-T")
        share = sum(TARGET_PER_COMBO[c] for c in fuzzy_only) / TARGET_TOTAL
        self.assertGreater(share, 0.3, f"fuzzy-only combos are {share:.0%}")

    def test_riftbound_is_smallest_because_it_cannot_merge_across_languages(self):
        """EN only, so the most dangerous failure mode does not apply to it."""
        self.assertEqual(TARGET_PER_COMBO["riftbound:EN"], MIN_PER_COMBO)
        self.assertEqual(min(TARGET_PER_COMBO.values()), MIN_PER_COMBO)


if __name__ == "__main__":
    unittest.main(verbosity=2)
