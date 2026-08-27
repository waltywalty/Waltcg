"""The catalog-in measurement. Uncertified by construction.

The gated precision figure is computed on self-records and cannot fail. This
one can, and on the current catalog it does. These tests assert its SHAPE --
that it pairs honestly, refuses to score an empty denominator, and reports its
own coverage -- not its value, which is a measurement and will move.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.checks import catalog_precision as C  # noqa: E402


class TheBoundIsPinned(unittest.TestCase):

    def test_a_clean_sweep_lower_bound_matches_adr_0015(self):
        """250/250 -> 0.9881 and 200/200 -> 0.9851, from ADR-0015's own
        table. Pinned because the last bisection here returned 0.0 for every
        input and passed `assertLess` for months."""
        self.assertAlmostEqual(C.clopper_pearson_lower(250, 250), 0.9881,
                               places=3)
        self.assertAlmostEqual(C.clopper_pearson_lower(200, 200), 0.9851,
                               places=3)

    def test_one_error_drops_it(self):
        self.assertAlmostEqual(C.clopper_pearson_lower(250, 249), 0.9812,
                               places=3)

    def test_an_empty_denominator_is_not_a_bound(self):
        self.assertEqual(C.clopper_pearson_lower(0, 0), 0.0)


class ThePairingRefusesAmbiguity(unittest.TestCase):
    """A set routinely holds several printings of one character, and
    non-negotiable 3 says those are different cards. Taking the first match
    paired the labelled `sv03.5` Venusaur ex with the one at 198 and would
    have scored the resolver wrong for being right."""

    ROWS = [{"card_uid": "pkmn:sv03.5:003/165:base:EN", "game": "pkmn",
             "language": "EN", "set_code": "sv03.5", "number": "003/165",
             "name": "Venusaur ex", "confidence": "verified"},
            {"card_uid": "pkmn:sv03.5:198/165:base:EN", "game": "pkmn",
             "language": "EN", "set_code": "sv03.5", "number": "198/165",
             "name": "Venusaur ex", "confidence": "verified"}]

    def _entry(self, number):
        return {"source": "probe", "game": "pkmn", "language": "EN",
                "set_code": "sv03.5", "number": number, "name": "Venusaur ex"}

    def test_two_labelled_rows_sharing_a_set_and_name_do_not_pair(self):
        pairs, unpaired = C.pair(self.ROWS, [self._entry("198")],
                                 "set_and_name")
        self.assertEqual(pairs, [])
        self.assertTrue(all("AMBIGUOUS" in why for _r, why in unpaired))

    def test_two_catalog_entries_sharing_a_set_and_name_do_not_pair(self):
        pairs, unpaired = C.pair(
            self.ROWS[:1], [self._entry("003"), self._entry("198")],
            "set_and_name")
        self.assertEqual(pairs, [])
        self.assertIn("AMBIGUOUS", unpaired[0][1])

    def test_a_unique_set_and_name_does_pair(self):
        pairs, unpaired = C.pair(self.ROWS[:1], [self._entry("003")],
                                 "set_and_name")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(unpaired, [])

    def test_a_row_with_no_catalog_entry_says_so(self):
        pairs, unpaired = C.pair(self.ROWS[:1], [], "set_and_name")
        self.assertEqual(pairs, [])
        self.assertIn("no catalog entry", unpaired[0][1])


class TheReportRefusesToInventANumber(unittest.TestCase):

    def test_an_empty_denominator_is_reported_as_undefined(self):
        """Not 1.0 and not 0.0. An empty denominator is not a result -- the
        same rule the labelled-set gate applies when it SKIPS rather than
        passing on zero rows."""
        report = C.render({"scored_rows": 10, "catalog_entries": 0,
                           "catalog_by_combo": {},
                           "joins": {"set_and_name": {
                               "paired": 0, "unpaired": 10, "used": 0,
                               "right": 0, "wrong": [], "refused": [],
                               "precision": None, "lower_bound": None,
                               "unpaired_by_combo": {}, "unpaired_reasons": {}}}})
        self.assertIn("precision UNDEFINED", report)
        self.assertIn("Not 1.0, and not 0.0", report)

    def test_it_names_what_limits_coverage(self):
        report = C.render(C.measure())
        self.assertIn("What limits coverage today", report)
        self.assertIn("rate-limited", report)
        self.assertIn("local script", report)

    def test_the_catalog_uid_is_never_fed_back(self):
        """The catalog carries a `card_uid` WE derived. Feeding it would
        rebuild the circularity this module exists to escape."""
        for entry in C.load_catalog():
            self.assertNotIn("card_uid", entry)


class ItActuallyRuns(unittest.TestCase):
    """Uncertified: it asserts no threshold. The 250-row count licenses a
    precision CLAIM; taking the measurement never needed to wait for it."""

    def test_the_measurement_completes_on_the_real_repository(self):
        result = C.measure()
        self.assertEqual(result["scored_rows"], 239)
        self.assertGreater(result["catalog_entries"], 0)
        for how in C.JOINS:
            self.assertIn(how, result["joins"])

    def test_it_can_fail_where_self_records_cannot(self):
        """The whole point. Self-records score 1.0000 on 239/239 and CANNOT
        score otherwise -- they are a no-merge check. This one resolves a
        provider's own presentation, and it spent its first run resolving
        nothing at all: every pairable row was refused because the set totals
        never reached the resolver.

        That is now wired (ADR-0060), so the assertion is no longer "it
        resolves nothing". It is that the denominator is SMALL and honestly
        reported: a handful of rows, a lower bound far from any threshold, and
        refusals that are visible rather than absent.
        """
        result = C.measure()["joins"]["set_and_name"]
        self.assertGreater(result["paired"], 0)
        self.assertLess(result["paired"], 30,
                        "coverage grew past the point where this test's "
                        "framing holds -- re-read the ADR before widening it")
        if result["used"]:
            self.assertLess(result["lower_bound"], 0.9,
                            "a lower bound this high on a denominator this "
                            "small would mean the arithmetic is wrong, not "
                            "that the resolver is good")
        self.assertEqual(result["used"] + len(result["refused"]),
                         result["paired"],
                         "a paired row that was neither used nor refused has "
                         "gone missing from the accounting")


if __name__ == "__main__":
    unittest.main()


class TheTotalsReachBothHalvesOfTheMeasurement(unittest.TestCase):
    """The orphaned wiring this module found in the resolver was present in
    this module too. `_numbers_agree` raised `CannotBridge` on every bare
    number and an `except Exception` swallowed it into a naked string
    comparison, and `score` built its Resolver without totals -- so all seven
    pairs were refused for want of wiring and that read as a measurement of
    the resolver's judgement.
    """

    ROW = {"card_uid": "pkmn:swsh10.5:011/078:base:EN", "game": "pkmn",
           "language": "EN", "set_code": "swsh10.5", "number": "011/078",
           "variant": "base", "name": "Pikachu"}
    ENTRY = {"source": "tcgdex", "game": "pkmn", "language": "EN",
             "set_code": "swsh10.5", "number": "11", "name": "Pikachu"}
    TOTALS = {"EN": {"swsh10.5": 78}}

    def test_the_field_join_pairs_a_bare_number_only_with_the_total(self):
        blind, _ = C.pair([self.ROW], [self.ENTRY], "field")
        self.assertEqual(blind, [], "paired without a total -- the bridge "
                                    "cannot have been consulted")
        wired, _ = C.pair([self.ROW], [self.ENTRY], "field", self.TOTALS)
        self.assertEqual(len(wired), 1)

    def test_score_passes_the_totals_to_the_resolver(self):
        pairs = [(self.ROW, self.ENTRY)]
        blind = C.score(pairs, [self.ROW])
        self.assertEqual(blind["used"], 0)
        self.assertEqual(len(blind["refused"]), 1)
        wired = C.score(pairs, [self.ROW], self.TOTALS)
        self.assertEqual(wired["used"], 1)
        self.assertEqual(wired["right"], 1)

    def test_cannot_bridge_still_falls_back_to_string_equality(self):
        """Two identical strings denote the same printing whether or not a
        total exists. What was dishonest was reaching that without trying."""
        self.assertTrue(C._numbers_agree("SV001", "SV001"))
        self.assertFalse(C._numbers_agree("SV001", "SV002"))
