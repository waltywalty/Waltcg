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


class CrossGraderCompsAreFlaggedNotRefused(unittest.TestCase):
    """A route comparison holds the comps fixed on purpose -- that is how fees,
    freight and import charges get isolated from slab premium. But a CGC 10 and
    a PSA 10 are different assets, so the comparison must never render as a
    choice of slab. Flag, not refusal: refusing would throw away the comparison
    the route work exists to support."""

    def _run(self, route, grader, tier, comps_grader):
        cfg = fs.scenario_config()
        return raw_to_graded_ev(
            "pkmn:sv3:223/197:sir:EN", Money("140.00", "USD"), tier, COMPS,
            cfg=cfg, grader=grader, venue="ebay", route=route,
            route_fx=fs.fx_gbp_usd(), buy_route="uk_domestic_secondhand",
            comps_grader=comps_grader, card_pop=fs.LADDER_POP,
            set_pop=fs.SET_POP)

    def test_same_grader_is_not_flagged(self):
        r = self._run("psa_us", "PSA", "regular", "PSA")
        self.assertTrue(r)
        self.assertEqual(r.comp_basis["state"], "match")
        self.assertFalse(r.comp_basis["flag"])

    def test_a_different_grader_is_flagged(self):
        r = self._run("cgc_uk", "CGC", "economy", "PSA")
        self.assertEqual(r.comp_basis["state"], "mismatch")
        self.assertTrue(r.comp_basis["flag"])

    def test_the_flag_names_which_grader_supplied_the_comps(self):
        """'Mismatch' on its own is not actionable. The reader has to know
        whose sales the number rests on."""
        r = self._run("cgc_uk", "CGC", "economy", "PSA")
        self.assertEqual(r.comp_basis["comps_grader"], "PSA")
        self.assertEqual(r.comp_basis["route_grader"], "CGC")
        self.assertIn("PSA", r.comp_basis["note"])
        self.assertIn("CGC", r.comp_basis["note"])

    def test_it_flags_rather_than_refusing(self):
        """The whole point. A mismatched comparison still computes."""
        r = self._run("cgc_uk", "CGC", "economy", "PSA")
        self.assertTrue(r, "a cross-grader comparison must still produce a number")
        self.assertIsNotNone(r.break_even_p_target)
        self.assertIsNotNone(r.ev)

    def test_an_unstated_comp_source_is_flagged_too(self):
        """Nobody said is not the same as they agree. Treating silence as a
        match would be the silent default this repo keeps refusing."""
        r = self._run("psa_us", "PSA", "regular", None)
        self.assertEqual(r.comp_basis["state"], "unstated")
        self.assertTrue(r.comp_basis["flag"])
        self.assertIsNone(r.comp_basis["comps_grader"])

    def test_the_note_warns_against_reading_it_as_a_slab_choice(self):
        for comps_grader in ("PSA", None):
            r = self._run("cgc_uk", "CGC", "economy", comps_grader)
            self.assertIn("slab", r.comp_basis["note"].lower(),
                          f"comps_grader={comps_grader}")

    def test_the_route_comparison_still_carries_the_flag_on_every_row(self):
        """The comparison is exactly where the mismatch bites, so it cannot be
        rendered on one route and omitted on the other."""
        for route, grader, tier in (("psa_us", "PSA", "regular"),
                                    ("cgc_uk", "CGC", "economy")):
            r = self._run(route, grader, tier, "PSA")
            self.assertIsNotNone(r.comp_basis, route)
            self.assertEqual(r.comp_basis["route"], route)

    def test_case_and_whitespace_do_not_decide_a_mismatch(self):
        """comps_grader is free text I type; the route grader is a config key.
        A flag raised by capitalisation would be noise, and noise gets ignored
        along with the real ones."""
        from engine.ev.comps import comp_basis
        for supplied in ("PSA", "psa", " PSA ", "Psa"):
            self.assertEqual(comp_basis("PSA", supplied)["state"], "match",
                             repr(supplied))
        self.assertEqual(comp_basis("PSA", "CGC")["state"], "mismatch")
        self.assertEqual(comp_basis("PSA", "   ")["state"], "unstated",
                         "blank is not a grader name")


class EbayUkChargesVatOnItsOwnFee(unittest.TestCase):
    """A fee-on-fee: 20% VAT on the 12.8% selling fee, so the cash cost is
    15.36% of the fee base. It multiplies the FEE, never the sale price, and a
    private seller cannot reclaim it. Leaving it out understated eBay UK by
    about 2.5 points of the sale."""

    def setUp(self):
        from engine.ev.fees import marketplace_fee
        self.fee = marketplace_fee
        self.schedule = fs.scenario_config().get(
            "fees.marketplaces.ebay_uk.fee_schedule")

    def gbp(self, amount):
        return Money(str(amount), "GBP")

    def test_the_vat_multiplies_the_fee_not_the_sale(self):
        f = self.fee(self.gbp(1000), self.schedule, shipping_charged=self.gbp(0))
        self.assertEqual(f["vat_on_fee"].amount,
                         (f["fee_before_vat"].amount * Decimal("0.20")))

    def test_the_headline_rate_becomes_15_36_percent(self):
        """12.8% * 1.2. Checked without the fixed fee so the ratio is clean."""
        schedule = dict(self.schedule)
        schedule["payment"] = {"pct": 0, "fixed_bands": [{"up_to": None, "fee": 0}]}
        f = self.fee(self.gbp(1000), schedule, shipping_charged=self.gbp(0))
        self.assertEqual((f["total"].amount / Decimal(1000)).quantize(
            Decimal("0.0001")), Decimal("0.1536"))

    def test_it_is_no_longer_understated(self):
        """The gap this closes: ~2.5 points of the sale on a 1000 card."""
        without = dict(self.schedule)
        without.pop("vat_on_fee_pct")
        with_vat = self.fee(self.gbp(1000), self.schedule,
                            shipping_charged=self.gbp(0))["total"].amount
        no_vat = self.fee(self.gbp(1000), without,
                          shipping_charged=self.gbp(0))["total"].amount
        gap = (with_vat - no_vat) / Decimal(1000)
        self.assertGreater(gap, Decimal("0.02"), f"gap only {gap}")
        self.assertLess(gap, Decimal("0.03"), f"gap {gap}")

    def test_a_venue_without_the_key_is_unaffected(self):
        us = fs.scenario_config().get("fees.marketplaces.ebay.fee_schedule")
        f = self.fee(Money("1000", "USD"), us, shipping_charged=Money("0", "USD"))
        self.assertEqual(f["vat_on_fee"].amount, Decimal(0))
        self.assertEqual(f["total"].amount, f["fee_before_vat"].amount)

    def test_a_percentage_written_as_20_is_rejected(self):
        from engine.ev.fees import FeeScheduleError
        schedule = dict(self.schedule)
        schedule["vat_on_fee_pct"] = 20
        with self.assertRaises(FeeScheduleError):
            self.fee(self.gbp(1000), schedule, shipping_charged=self.gbp(0))
