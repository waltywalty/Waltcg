"""The re-verification sampler, and the arithmetic it rests on.

The last bisection in this repository was inverted and returned 0.0 for every
input, which passes `assertLess` silently for months. So the bound is pinned
against values computed independently, and the sample-size claims in the
report are asserted rather than trusted.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.checks import reverification_sample as R  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TheBoundIsPinned(unittest.TestCase):

    def test_a_clean_sample_of_thirty_bounds_e_at_about_ten_percent(self):
        """And the gate needs 2%. This is the number that says N=30 screens
        rather than certifies."""
        self.assertAlmostEqual(R.clopper_pearson_upper(30), 0.095, places=2)

    def test_bounding_e_below_two_percent_takes_about_a_hundred_and_fifty(self):
        self.assertGreater(R.clopper_pearson_upper(100), 0.02)
        self.assertLessEqual(R.clopper_pearson_upper(149), 0.021)

    def test_the_bound_is_not_stuck_at_zero(self):
        """The failure mode the inverted bisection had."""
        values = [R.clopper_pearson_upper(n) for n in (10, 50, 200)]
        self.assertTrue(all(v > 0 for v in values))
        self.assertEqual(values, sorted(values, reverse=True))

    def test_more_errors_widen_the_bound(self):
        self.assertLess(R.clopper_pearson_upper(30, 0),
                        R.clopper_pearson_upper(30, 1))

    def test_a_zero_sample_bounds_nothing(self):
        self.assertEqual(R.clopper_pearson_upper(0), 1.0)


class TheDrawIsBlindAndReproducible(unittest.TestCase):

    def test_the_same_seed_draws_the_same_rows(self):
        first, _ = R.draw(30, seed=R.SEED)
        second, _ = R.draw(30, seed=R.SEED)
        self.assertEqual([c["card_uid"] for c in first],
                         [c["card_uid"] for c in second])

    def test_a_different_seed_draws_differently(self):
        first, _ = R.draw(30, seed=R.SEED)
        other, _ = R.draw(30, seed=R.SEED + 1)
        self.assertNotEqual([c["card_uid"] for c in first],
                            [c["card_uid"] for c in other])

    def test_the_request_never_contains_a_name(self):
        """The field every known error lives in, and the answer."""
        sample, _ = R.draw(30)
        request = R.render_request(sample)
        for card in sample:
            with self.subTest(card=card["card_uid"]):
                self.assertNotIn(card["name"], request)

    def test_the_request_carries_only_the_blinded_fields(self):
        self.assertNotIn("name", R.BLINDED_FIELDS)
        self.assertEqual(set(R.BLINDED_FIELDS),
                         {"game", "set_code", "number", "variant",
                          "language"})

    def test_it_only_ever_draws_scored_rows(self):
        from resolve.label_cli import SCORED
        with open(os.path.join(REPO, "tests", "fixtures",
                               "labelled_200.json"), encoding="utf-8") as h:
            by_uid = {c["card_uid"]: c for c in json.load(h)["cards"]}
        sample, _ = R.draw(30)
        for card in sample:
            self.assertIn(by_uid[card["card_uid"]]["confidence"], SCORED)

    def test_the_committed_draw_matches_the_seed(self):
        """The blinding is a SEQUENCE. If the committed draw and the seed
        disagree, the sample was chosen after something was seen."""
        path = os.path.join(REPO, "contracts", "reverification_draw.json")
        with open(path, encoding="utf-8") as handle:
            committed = json.load(handle)
        sample, _pool = R.draw(committed["n"], committed["seed"])
        self.assertEqual([c["card_uid"] for c in sample], committed["drawn"])

    def test_the_committed_draw_records_that_it_is_a_floor(self):
        path = os.path.join(REPO, "contracts", "reverification_draw.json")
        with open(path, encoding="utf-8") as handle:
            committed = json.load(handle)
        self.assertIn("bounds e from below",
                      committed["_this_estimate_is_a_floor"])
        self.assertIn("not even noise",
                      committed["_this_estimate_is_a_floor"])
        self.assertIn("screen", committed["_n_is_a_screen_not_a_certification"])


class TheComparisonIsMechanical(unittest.TestCase):

    def _sample(self):
        return R.draw(30)[0]

    def _answer(self, card, name):
        payload = {f: card[f] for f in R.BLINDED_FIELDS}
        payload["name"] = name
        return payload

    def test_an_exact_match_agrees(self):
        sample = self._sample()
        results, _ = R.compare(
            sample, [self._answer(sample[0], sample[0]["name"])])
        self.assertEqual(results[0]["verdict"], "agrees")

    def test_orthography_is_not_a_disagreement(self):
        """The claim under test is WHICH CARD, not which spelling."""
        sample = self._sample()
        card = next(c for c in sample if "." in c["name"])
        results, _ = R.compare(
            sample, [self._answer(card, card["name"].replace(".", " "))])
        self.assertEqual(results[0]["verdict"], "agrees")

    def test_a_different_character_disagrees(self):
        sample = self._sample()
        results, _ = R.compare(
            sample, [self._answer(sample[0], "Somebody Else Entirely")])
        self.assertEqual(results[0]["verdict"], "DISAGREES")

    def test_an_abstention_is_not_an_agreement(self):
        """Counting it as a pass is how a thin sample reads as a clean one."""
        sample = self._sample()
        answers = [self._answer(sample[0], None)]
        answers += [self._answer(c, c["name"]) for c in sample[1:5]]
        results, _ = R.compare(sample, answers)
        self.assertEqual(results[0]["verdict"], "abstained")
        report = R.render(results, [], len(sample))
        self.assertIn("Removed from the denominator", report)
        # 4 compared, not 5: the abstention is out of the denominator.
        self.assertIn("**4 of 30", report)

    def test_an_answer_matching_no_drawn_row_is_reported(self):
        sample = self._sample()
        stray = dict(self._answer(sample[0], "X"), number="ZZ99-999")
        results, unmatched = R.compare(sample, [stray])
        self.assertEqual(results, [])
        self.assertEqual(len(unmatched), 1)


class TheReportStatesItsOwnLimits(unittest.TestCase):

    def _report(self, wrong=0, n=30):
        sample = R.draw(n)[0]
        answers = []
        for index, card in enumerate(sample):
            payload = {f: card[f] for f in R.BLINDED_FIELDS}
            payload["name"] = ("Wrong Person" if index < wrong
                               else card["name"])
            answers.append(payload)
        results, unmatched = R.compare(sample, answers)
        return R.render(results, unmatched, len(sample))

    def test_a_clean_result_says_what_it_could_not_have_detected(self):
        report = self._report(0)
        self.assertIn("could and could not do", report)
        self.assertIn("SCREENS for a gross problem", report)
        self.assertIn("149", report)

    def test_the_estimate_is_always_labelled_a_floor(self):
        for wrong in (0, 2):
            with self.subTest(wrong=wrong):
                self.assertIn("FLOOR, not an unbiased estimate",
                              self._report(wrong))

    def test_contamination_is_described_as_targeted_not_as_noise(self):
        report = self._report(0)
        self.assertIn("not even noise", report)
        self.assertIn("error class all three known errors belong to", report)

    def test_disagreements_are_findings_not_fixes(self):
        report = self._report(2)
        self.assertIn("Findings, not fixes", report)
        self.assertIn("does not say which one is the error", report)

    def test_nothing_compared_is_not_a_clean_result(self):
        report = R.render([], [], 30)
        self.assertIn("nothing was measured", report)
        self.assertIn("different thing from a clean result", report)


if __name__ == "__main__":
    unittest.main()
