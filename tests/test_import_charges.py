"""Import charges on the return leg: the term, and the asymmetry it exposes.

The reason this exists is not that 22% is a big number. It is that the charge
lands on the FULL declared value of the graded card rather than on the value
grading added, it COMPOUNDS, and it varies by realised grade -- so it is not a
flat percentage, not a fixed cost, and not something a single "shipping" line
can absorb. Getting any of those three wrong flatters every cross-border
grading decision, and always in the same direction.
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ev import Money, raw_to_graded_ev            # noqa: E402
from engine.ev.imports import (ImportChargeError, charge_on,  # noqa: E402
                               effective_rate, import_charge_by_grade,
                               resolve_rule)
from tests import fixture_scenario as fs                  # noqa: E402

GB = {"vat_pct": 0.20, "duty_pct": 0.02}
COMPS = {"8": Money("88.00", "USD"), "9": Money("142.00", "USD"),
         "10": Money("540.00", "USD")}


def run(route, grader, tier, relief, **kw):
    cfg = fs.scenario_config()
    cfg.assumptions.setdefault("relief_scenario", {})["current_value"] = relief
    return raw_to_graded_ev(
        "pkmn:sv3:223/197:sir:EN", Money("140.00", "USD"), tier, COMPS, cfg=cfg,
        grader=grader, venue="ebay", route=route, route_fx=fs.fx_gbp_usd(),
        buy_route="uk_domestic_secondhand", card_pop=fs.LADDER_POP,
        set_pop=fs.SET_POP, **kw)


class TheChargeCompounds(unittest.TestCase):

    def test_twenty_and_two_is_not_twenty_two(self):
        """VAT is charged on the duty as well as on the goods."""
        self.assertEqual(effective_rate(GB), Decimal("0.224"))

    def test_the_arithmetic_is_duty_then_vat(self):
        # goods 100, freight 10 -> dutiable 110
        # duty 2% of 110  = 2.20
        # vat  20% of 112.20 = 22.44
        charge = charge_on(Money("100", "USD"), Money("10", "USD"), GB)
        self.assertEqual(charge.amount, Decimal("24.64"))

    def test_freight_is_in_the_base(self):
        with_freight = charge_on(Money("100", "USD"), Money("10", "USD"), GB)
        without = charge_on(Money("100", "USD"), Money("0", "USD"), GB)
        self.assertGreater(with_freight.amount, without.amount)

    def test_a_percentage_written_as_20_not_0_20_is_rejected(self):
        with self.assertRaises(ImportChargeError):
            charge_on(Money("100", "USD"), Money("0", "USD"),
                      {"vat_pct": 20, "duty_pct": 2})

    def test_a_null_rate_refuses_rather_than_defaulting_to_zero(self):
        with self.assertRaises(ImportChargeError):
            charge_on(Money("100", "USD"), Money("0", "USD"),
                      {"vat_pct": None, "duty_pct": 0.02})

    def test_mixed_currencies_refuse(self):
        with self.assertRaises(ImportChargeError):
            charge_on(Money("100", "USD"), Money("10", "GBP"), GB)


class TheChargeVariesByRealisedGrade(unittest.TestCase):
    """Customs values the card that comes back. A 10 is charged more than a 9
    on the same submission, so this cannot be a fixed cost line."""

    def setUp(self):
        self.charges = import_charge_by_grade(
            {g: Money("0", "USD") for g in COMPS}, COMPS, rule=GB,
            relief="relief_none", return_freight=Money("5", "USD"),
            value_added=Money("85", "USD"))

    def test_a_ten_is_charged_more_than_a_nine(self):
        self.assertGreater(self.charges["10"].amount, self.charges["9"].amount)
        self.assertGreater(self.charges["9"].amount, self.charges["8"].amount)

    def test_the_charge_tracks_the_declared_value_not_the_proceeds(self):
        """Proceeds are net of selling fees; customs does not care what eBay
        took. Passing proceeds here would understate the charge."""
        expected = charge_on(COMPS["10"], Money("5", "USD"), GB)
        self.assertEqual(self.charges["10"].amount, expected.amount)

    def test_a_missing_declared_value_refuses(self):
        with self.assertRaises(ImportChargeError):
            import_charge_by_grade(
                {"10": Money("0", "USD")}, {}, rule=GB, relief="relief_none",
                return_freight=Money("5", "USD"), value_added=Money("85", "USD"))


class TheThreeReliefs(unittest.TestCase):

    def test_rgr_zeroes_the_charge(self):
        charges = import_charge_by_grade(
            {g: Money("0", "USD") for g in COMPS}, COMPS, rule=GB,
            relief="relief_rgr", return_freight=Money("5", "USD"),
            value_added=Money("85", "USD"))
        self.assertTrue(all(c.amount == 0 for c in charges.values()))

    def test_opr_charges_the_value_added_only_and_is_grade_independent(self):
        charges = import_charge_by_grade(
            {g: Money("0", "USD") for g in COMPS}, COMPS, rule=GB,
            relief="relief_opr", return_freight=Money("5", "USD"),
            value_added=Money("85", "USD"))
        self.assertEqual(len({c.amount for c in charges.values()}), 1,
                         "OPR is charged on the value added, which does not "
                         "depend on the grade")
        self.assertEqual(charges["10"].amount,
                         charge_on(Money("85", "USD"), Money("0", "USD"), GB).amount)

    def test_none_is_the_most_expensive_and_is_the_default(self):
        none = run("psa_us", "PSA", "regular", "relief_none")
        rgr = run("psa_us", "PSA", "regular", "relief_rgr")
        opr = run("psa_us", "PSA", "regular", "relief_opr")
        self.assertLess(none.ev.amount, opr.ev.amount)
        self.assertLess(opr.ev.amount, rgr.ev.amount)
        registry_default = fs.scenario_config().get(
            "assumptions.relief_scenario.current_value")
        self.assertEqual(registry_default, "relief_none",
                         "the default must be the unprepared outcome: being "
                         "wrong that way costs nothing, and assuming relief "
                         "and not getting it costs 22.4% of the card")

    def test_an_unknown_relief_refuses(self):
        with self.assertRaises(ImportChargeError):
            import_charge_by_grade(
                {"10": Money("0", "USD")}, COMPS, rule=GB, relief="relief_hope",
                return_freight=Money("5", "USD"), value_added=Money("85", "USD"))


class TheDomesticAsymmetryIsVisible(unittest.TestCase):
    """The main reason to prefer a domestic grader, so it has to be a stated
    result rather than just a smaller number."""

    def test_a_domestic_route_says_why_it_is_not_charged(self):
        cfg = fs.scenario_config()
        rule, applies, (note, facility) = resolve_rule(cfg, "cgc_uk")
        self.assertFalse(applies)
        self.assertIsNone(rule)
        self.assertIn("domestic", note)
        self.assertEqual(facility, "GB")

    def test_a_cross_border_route_says_which_way_it_crosses(self):
        cfg = fs.scenario_config()
        rule, applies, (note, facility) = resolve_rule(cfg, "psa_us")
        self.assertTrue(applies)
        self.assertEqual(facility, "US")
        self.assertIn("US", note)

    def test_the_result_carries_the_asymmetry_either_way(self):
        domestic = run("cgc_uk", "CGC", "economy", "relief_none")
        crossing = run("psa_us", "PSA", "regular", "relief_none")
        self.assertFalse(domestic.import_charges["applies"])
        self.assertTrue(crossing.import_charges["applies"])
        self.assertIsNone(domestic.import_charges["expected"])
        self.assertIsNotNone(crossing.import_charges["expected"])

    def test_the_domestic_route_needs_a_lower_probability(self):
        """The whole point of the term."""
        domestic = run("cgc_uk", "CGC", "economy", "relief_none")
        crossing = run("psa_us", "PSA", "regular", "relief_none")
        self.assertLess(domestic.break_even_p_target,
                        crossing.break_even_p_target)


class TheRouteCannotBeAssumed(unittest.TestCase):

    def test_no_route_refuses_rather_than_defaulting_to_domestic(self):
        """Defaulting would default to the cheaper answer without saying so."""
        cfg = fs.scenario_config()
        r = raw_to_graded_ev("x", Money("140.00", "USD"), "regular", COMPS,
                             cfg=cfg, buy_route="uk_domestic_secondhand",
                             card_pop=fs.LADDER_POP, set_pop=fs.SET_POP)
        self.assertFalse(r)
        self.assertEqual(r.reason, "no grading route supplied")
        self.assertIn("route", r.missing)

    def test_a_gbp_route_will_not_convert_without_an_explicit_rate(self):
        """Assuming parity between GBP and USD would understate the domestic
        route by about a fifth, which is the direction that flatters it."""
        cfg = fs.scenario_config()
        r = raw_to_graded_ev("x", Money("140.00", "USD"), "economy", COMPS,
                             cfg=cfg, grader="CGC", route="cgc_uk",
                             buy_route="uk_domestic_secondhand",
                             card_pop=fs.LADDER_POP, set_pop=fs.SET_POP)
        self.assertFalse(r)
        self.assertEqual(r.reason, "route freight unusable")
        self.assertIn("FxRate", r.detail)


class AcquisitionTaxIsPerBuyRoute(unittest.TestCase):

    def test_a_uk_second_hand_buy_carries_no_acquisition_tax(self):
        r = run("psa_us", "PSA", "regular", "relief_none")
        self.assertEqual(r.costs.tax.amount, Decimal("0.00"))

    def test_an_import_over_135_carries_the_compounded_rate(self):
        cfg = fs.scenario_config()
        r = raw_to_graded_ev(
            "x", Money("140.00", "USD"), "regular", COMPS, cfg=cfg,
            route="psa_us", route_fx=fs.fx_gbp_usd(),
            buy_route="import_to_uk_over_135",
            card_pop=fs.LADDER_POP, set_pop=fs.SET_POP)
        self.assertTrue(r, getattr(r, "detail", ""))
        self.assertEqual(r.costs.tax.amount,
                         (Decimal("140.00") * Decimal("0.224")).quantize(
                             Decimal("0.0001")))

    def test_an_unknown_buy_route_refuses(self):
        cfg = fs.scenario_config()
        r = raw_to_graded_ev("x", Money("140.00", "USD"), "regular", COMPS,
                             cfg=cfg, route="psa_us", route_fx=fs.fx_gbp_usd(),
                             buy_route="somewhere_nice",
                             card_pop=fs.LADDER_POP, set_pop=fs.SET_POP)
        self.assertFalse(r)
        self.assertEqual(r.reason, "unknown buy route")

    def test_no_buy_route_refuses_rather_than_assuming_zero(self):
        cfg = fs.scenario_config()
        r = raw_to_graded_ev("x", Money("140.00", "USD"), "regular", COMPS,
                             cfg=cfg, route="psa_us", route_fx=fs.fx_gbp_usd(),
                             card_pop=fs.LADDER_POP, set_pop=fs.SET_POP)
        self.assertFalse(r)
        self.assertEqual(r.reason, "no buy route supplied")


class TheChargeIsNotDoubleCounted(unittest.TestCase):

    def test_the_cost_total_excludes_it(self):
        """Under relief_none it is already deducted from each branch's
        proceeds. Adding it to the cost total as well would charge it twice."""
        crossing = run("psa_us", "PSA", "regular", "relief_none")
        rgr = run("psa_us", "PSA", "regular", "relief_rgr")
        self.assertEqual(crossing.costs.total().amount, rgr.costs.total().amount)
        self.assertNotEqual(crossing.ev.amount, rgr.ev.amount)

    def test_the_expected_charge_is_probability_weighted(self):
        r = run("psa_us", "PSA", "regular", "relief_none")
        probs = r.grade_distribution.probs
        by_grade = r.import_charges["by_grade"]
        expected = sum(Decimal(by_grade[g]["amount"]) * probs[g] for g in probs)
        self.assertEqual(Decimal(r.import_charges["expected"]["amount"]),
                         expected.quantize(Decimal("0.01")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
