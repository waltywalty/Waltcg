"""Resolver precision and recall against the hand-labelled set.

TWO tests, and they measure different things on purpose:

* `ResolverQuality` scores the resolver on whatever labelled cards exist. It
  passes or fails on the resolver's own merit.
* `TheLabelledSetIsComplete` asserts the SET is big enough for that score to
  mean anything. It fails until the set has 200 cards across all 8 combos with
  20 hard cases.

Both are needed because a precision of 1.00 on twelve cards is not evidence
about a resolver -- it is evidence about twelve cards. Reporting the first
without the second is how a gate gets marked passed while the thing it gates
was never tested.

The second test is EXPECTED TO FAIL until the set is built. It is a red test
that names exactly what is missing, which is the honest state of a gate that
has not been met.
"""

from __future__ import annotations

import collections
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.resolver import Resolver, SIGNAL_THRESHOLD  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELLED = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")


def load():
    with open(LABELLED, encoding="utf-8") as handle:
        return json.load(handle)


class ResolverQuality(unittest.TestCase):
    """Precision: of the matches the resolver was willing to use in a signal,
    how many were right. Recall: of the cards it should have matched, how many
    it did.

    Precision is the gated number because the cost is asymmetric. A missed card
    is a card you do not trade. A wrongly matched card is a confident price on
    the wrong asset, and nothing downstream looks wrong."""

    @classmethod
    def setUpClass(cls):
        cls.data = load()
        cls.cards = cls.data["cards"]
        cls.resolver = Resolver(cls.cards)

    def _score(self, records):
        used = right = should = 0
        wrong = []
        for record, truth in records:
            should += 1
            result = self.resolver.resolve(record)
            if result.usable_in_signals:
                used += 1
                if result.card_uid == truth:
                    right += 1
                else:
                    wrong.append((truth, result.card_uid, result.confidence))
        precision = right / used if used else 1.0
        recall = right / should if should else 0.0
        return precision, recall, wrong

    def _self_records(self):
        """Each labelled card, presented as a provider would present it."""
        return [({"source": "probe", "game": c["game"], "language": c["language"],
                  "number": c["number"], "set_code": c["set_code"],
                  "variant": c["variant"], "name": c["name"]}, c["card_uid"])
                for c in self.cards]

    def test_precision_meets_the_gate(self):
        precision, recall, wrong = self._score(self._self_records())
        self.assertGreaterEqual(
            precision, self.data["_gate"]["precision_threshold"],
            f"precision {precision:.4f}; wrong matches: {wrong}")

    def test_recall_is_reported_even_when_precision_passes(self):
        precision, recall, _ = self._score(self._self_records())
        self.assertGreaterEqual(recall, self.data["_gate"]["recall_threshold"],
                                f"recall {recall:.4f}")

    def test_every_language_printing_resolves_to_its_own_uid(self):
        """GOAL D1. The one that would be silently catastrophic: three
        printings of OP01-121 must not collapse into one card."""
        by_number = collections.defaultdict(set)
        for card in self.cards:
            by_number[(card["game"], card["number"])].add(card["card_uid"])
        multilingual = {k: v for k, v in by_number.items() if len(v) > 1}
        self.assertTrue(multilingual,
                        "no card in the set exists in more than one language, "
                        "so the merge this test guards against is untested")
        for (game, number), uids in multilingual.items():
            resolved = set()
            for card in self.cards:
                if (card["game"], card["number"]) != (game, number):
                    continue
                result = self.resolver.resolve(
                    {"source": "probe", "game": card["game"],
                     "language": card["language"], "number": card["number"],
                     "set_code": card["set_code"], "variant": card["variant"],
                     "name": card["name"]})
                resolved.add(result.card_uid)
            self.assertEqual(resolved, uids,
                             f"{game} {number}: printings collapsed")

    def test_a_record_without_a_language_is_never_resolved(self):
        """Language is part of the uid, so a record that omits it could be any
        printing. Refusing is the only correct answer."""
        for card in self.cards:
            result = self.resolver.resolve(
                {"source": "probe", "game": card["game"],
                 "number": card["number"], "set_code": card["set_code"],
                 "name": card["name"]})
            self.assertIsNone(result.card_uid, card["card_uid"])
            self.assertFalse(result.usable_in_signals)

    def test_a_low_confidence_fuzzy_match_is_excluded_from_signals(self):
        """It is still WRITTEN -- the review queue needs it -- but no signal
        may use it. card_uid.md: anything fuzzy below 0.9 is excluded."""
        from resolve.resolver import Resolution
        low = Resolution("pkmn:sv3:223/197:sir:EN", 0.85, "fuzzy", "test")
        self.assertFalse(low.usable_in_signals)
        self.assertTrue(low.needs_review)
        high = Resolution("pkmn:sv3:223/197:sir:EN", 0.95, "fuzzy", "test")
        self.assertTrue(high.usable_in_signals)
        self.assertEqual(SIGNAL_THRESHOLD, 0.90)

    def test_a_wrong_name_at_the_same_number_does_not_resolve(self):
        """The adversarial direction: right number, right language, wrong card.
        This is what a bad fuzzy match looks like in the wild."""
        card = self.cards[0]
        result = self.resolver.resolve(
            {"source": "probe", "game": card["game"], "language": card["language"],
             "number": card["number"], "set_code": card["set_code"],
             "name": "Completely Different Creature"})
        self.assertFalse(
            result.usable_in_signals,
            f"resolved a mismatched name at {result.confidence:.2f}")


class TheLabelledSetIsComplete(unittest.TestCase):
    """THE GATE. Fails until the set can support the claim made about it.

    This test is currently RED and that is the correct state: GOAL D1 requires
    200 hand-labelled cards across all 8 combos, and 12 exist. A resolver
    scored on 12 cards has not been scored.
    """

    def setUp(self):
        self.data = load()
        self.cards = self.data["cards"]
        self.gate = self.data["_gate"]

    def test_two_hundred_cards(self):
        self.assertGreaterEqual(
            len(self.cards), self.gate["required_cards"],
            f"{len(self.cards)} of {self.gate['required_cards']} labelled cards. "
            f"{self.data['_needed']['why']}")

    def test_all_eight_combinations_are_represented(self):
        present = {f"{c['game']}:{c['language']}" for c in self.cards}
        missing = sorted(set(self.gate["required_combos"]) - present)
        self.assertFalse(missing, f"no labelled cards for: {missing}")

    def test_twenty_hard_cases(self):
        hard = [c for c in self.cards if c.get("hard_case")]
        self.assertGreaterEqual(
            len(hard), self.gate["required_hard_cases"],
            f"{len(hard)} of {self.gate['required_hard_cases']} hard cases")

    def test_every_hard_case_kind_is_covered(self):
        kinds = {c["hard_case"] for c in self.cards if c.get("hard_case")}
        for required in ("same_art_different_language", "reprint",
                         "alt_art_variant", "promo_vs_set"):
            self.assertIn(required, kinds, f"no {required} case in the set")


class TheSeededCardsAreTraceable(unittest.TestCase):
    """Nothing in the labelled set is invented. Each row names where in this
    repository its identity came from, so a later reader can check rather than
    trust."""

    def test_every_card_names_its_provenance(self):
        for card in load()["cards"]:
            self.assertTrue(card.get("verified_from"),
                            f"{card['card_uid']} has no provenance")

    def test_the_file_says_it_is_incomplete(self):
        data = load()
        self.assertIn("INCOMPLETE", data["_status"])
        self.assertGreater(data["_needed"]["short_by"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
