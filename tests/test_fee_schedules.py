"""Marketplace fee schedules, against the real provisional config.

Every expected figure is computed on paper in the docstring. These matter
more than most: a fee applied to the wrong base, or a marginal band applied
as a flat rate, is invisible in the output and wrong on every single trade.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ev import Config, Money, Refusal, raw_to_graded_ev  # noqa: E402
from engine.ev.config import UnverifiedWarning  # noqa: E402
from engine.ev.fees import (FeeScheduleError, marketplace_fee,  # noqa: E402
                            net_proceeds_from_schedule)

TODAY = dt.date(2026, 8, 13)


def usd(x):
    return Money(str(x), "USD")


def real_config():
    return Config.load(today=TODAY)


class EbayFeeSchedule(unittest.TestCase):
    """13.25% on item + shipping + tax, tiered fixed fee, banded discount."""

    def setUp(self):
        self.sched = real_config().get("fees.marketplaces.ebay.fee_schedule")

    def test_fee_base_includes_shipping_and_tax(self):
        """item 100, shipping 5, tax 8 -> base 113.

        FVF 13.25% of 113 = 14.9725. Item is over 10 so fixed = 0.40.
        Total fee = 15.3725.
        Applying 13.25% to the item alone would give 13.25 -- understating by
        1.7225 on a single 100 dollar sale, on every sale, forever.
        """
        fee = marketplace_fee(usd(100), self.sched,
                              shipping_charged=usd(5), tax_collected=usd(8))
        self.assertEqual(fee["base_amount"].amount, D("113"))
        self.assertEqual(fee["commission"].quantized().amount, D("14.97"))
        self.assertEqual(fee["fixed"].amount, D("0.40"))
        self.assertEqual(fee["total"].quantized().amount, D("15.37"))
        self.assertFalse(fee["discount_applied"])
        # The understatement the old flat model produced:
        self.assertNotEqual(fee["commission"].quantized().amount, D("13.25"))

    def test_fixed_fee_is_tiered_at_ten_dollars(self):
        """Under 10 -> 0.30. At or over 10 -> 0.40."""
        low = marketplace_fee(usd("9.99"), self.sched)
        high = marketplace_fee(usd("10.00"), self.sched)
        self.assertEqual(low["fixed"].amount, D("0.30"))
        self.assertEqual(high["fixed"].amount, D("0.40"))

    def test_discount_applies_at_one_thousand_not_below(self):
        """999.99 pays full rate; 1000.00 pays the discounted schedule."""
        below = marketplace_fee(usd("999.99"), self.sched)
        at = marketplace_fee(usd("1000.00"), self.sched)
        self.assertFalse(below["discount_applied"])
        self.assertTrue(at["discount_applied"])
        # below: 999.99 * 0.1325 = 132.498675
        self.assertEqual(below["commission"].quantized().amount, D("132.50"))
        # at:    1000 * 0.06625 = 66.25
        self.assertEqual(at["commission"].quantized().amount, D("66.25"))
        self.assertLess(at["commission"].amount, below["commission"].amount)

    def test_discount_bands_are_marginal_across_the_7500_breakpoint(self):
        """item 10000, no shipping or tax.

        Marginal:  7500 * 0.06625 = 496.875
                 + 2500 * 0.0235  =  58.75
                 = 555.625  (+ 0.40 fixed = 556.025)

        The two classic errors this rules out:
          whole amount at 0.06625 = 662.50   (overstates by ~107)
          whole amount at 0.0235  = 235.00   (understates by ~321)
        """
        fee = marketplace_fee(usd(10000), self.sched)
        self.assertEqual(fee["commission"].amount, D("555.625"))
        self.assertEqual(fee["total"].amount, D("556.025"))
        self.assertNotEqual(fee["commission"].amount, D("662.50"))
        self.assertNotEqual(fee["commission"].amount, D("235.00"))

    def test_net_proceeds_returns_item_plus_shipping_less_fees(self):
        """Tax is collected and remitted, so it is in the fee base but not revenue.

        item 100 + shipping 5 = 105 revenue; fee 15.3725; postage 4.
        net = 105 - 15.3725 - 4 = 85.6275
        """
        net = net_proceeds_from_schedule(
            usd(100), self.sched, shipping_charged=usd(5),
            tax_collected=usd(8), outbound_shipping=usd(4))
        self.assertEqual(net.quantized().amount, D("85.63"))


class TcgplayerFeeSchedule(unittest.TestCase):

    def test_commission_and_payment_both_on_full_order_total(self):
        """item 100, shipping 5, tax 8 -> base 113.

        commission 10.75% of 113 = 12.1475
        payment     2.50% of 113 =  2.825
        fixed                     =  0.30
        total                     = 15.2725
        """
        sched = real_config().get("fees.marketplaces.tcgplayer.fee_schedule")
        fee = marketplace_fee(usd(100), sched, shipping_charged=usd(5),
                              tax_collected=usd(8))
        self.assertEqual(fee["commission"].quantized().amount, D("12.15"))
        self.assertEqual(fee["payment_pct_amount"].quantized().amount, D("2.83"))
        self.assertEqual(fee["fixed"].amount, D("0.30"))
        self.assertEqual(fee["total"].amount, D("15.2725"))


class MercariUsRefuses(unittest.TestCase):

    def test_missing_fee_base_refuses_rather_than_assuming_item_only(self):
        """The source gave 10% + 2.9% + $0.50 but never said what they multiply.

        Assuming item-only would understate the stack on every shipped sale.
        A percentage without its base is not a fee.
        """
        sched = real_config().get("fees.marketplaces.mercari_us.fee_schedule")
        self.assertIsNone(sched.get("base"))
        with self.assertRaises(FeeScheduleError) as ctx:
            marketplace_fee(usd(100), sched)
        self.assertIn("no base", str(ctx.exception))

    def test_model_a_refuses_up_front_naming_the_exact_gap(self):
        """Refused at the config gate, before any arithmetic.

        Earlier and more precise than the runtime FeeScheduleError path, which
        remains as defence in depth for a schedule that is present but
        malformed.
        """
        cfg = real_config()
        # Fill everything else so the fee base is the only blocker.
        cfg.grading["submission_costs"].update(
            {"inbound_shipping": 10, "return_shipping_insured": 20,
             "supplies_per_card": 1, "default_batch_size": 10})
        cfg.fees["region_defaults"]["default_days_to_sell"] = 30
        cfg.assumptions["tax"]["acquisition_tax_pct"]["value"] = 0
        cfg.assumptions["submission_selection_haircut"]["value"] = 1.0
        cfg.assumptions["empirical_bayes"]["prior_strength_cards"]["value"] = 20
        cfg.assumptions["empirical_bayes"]["min_card_pop_for_own_prior"]["value"] = 10
        cfg.fees["marketplaces"]["mercari_us"]["currency"] = "USD"
        from engine.ev.results import GradeDistribution
        from engine.ev import ConfigIncomplete
        with self.assertRaises(ConfigIncomplete) as ctx:
            raw_to_graded_ev("x", usd(100), "regular", {"10": usd(500)},
                             cfg=cfg, venue="mercari_us",
                             grade_probs=GradeDistribution(probs={"10": D(1)},
                                                           prior_used="test"))
        self.assertEqual(ctx.exception.missing,
                         ["fees.marketplaces.mercari_us.fee_schedule.base"])


class UnverifiedFiresRegardlessOfAge(unittest.TestCase):
    """An unverified value was never fresh. Age is not the question."""

    def test_warning_fires_on_a_value_checked_today(self):
        cfg = Config.load(today=dt.date(2026, 8, 13))   # same day as checked_on
        warnings = cfg.unverified_warnings()
        self.assertTrue(warnings, "unverified entries produced no warning")
        self.assertTrue(all(isinstance(w, UnverifiedWarning) for w in warnings))
        paths = {w.path for w in warnings}
        self.assertIn("graders.PSA.tiers.regular", paths)

    def test_same_warnings_a_year_later(self):
        """Age changes nothing: it was never verified either way."""
        now = Config.load(today=dt.date(2026, 8, 13)).unverified_warnings()
        later = Config.load(today=dt.date(2027, 8, 13)).unverified_warnings()
        self.assertEqual(len(now), len(later))

    def test_every_psa_entry_needs_primary_verification(self):
        cfg = real_config()
        psa = [w for w in cfg.needs_primary_verification()
               if w.path.startswith("graders.PSA")]
        self.assertGreaterEqual(len(psa), 5)
        for w in psa:
            self.assertTrue(w.needs_primary_verification)

    def test_unverified_warnings_reach_the_result(self):
        cfg = real_config()
        self.assertTrue(any("UNVERIFIED" in str(w) for w in cfg.staleness_warnings()))


class GradingConfigValues(unittest.TestCase):

    def setUp(self):
        self.cfg = real_config()

    def test_psa_regular_is_populated_and_open(self):
        self.assertEqual(self.cfg.decimal("grading.graders.PSA.tiers.regular.fee"),
                         D("79.99"))
        self.assertEqual(self.cfg.get("grading.graders.PSA.tiers.regular.availability"),
                         "open")

    def test_turnaround_uses_the_conservative_end_of_the_range(self):
        """40-60 business days: the model must take 60.

        Understating turnaround overstates annualised ROI, which is the
        dangerous direction for a capital-lockup decision.
        """
        t = self.cfg
        self.assertEqual(t.get("grading.graders.PSA.tiers.regular.turnaround_business_days"), 60)
        self.assertEqual(
            t.get("grading.graders.PSA.tiers.regular.turnaround_business_days_min"), 40)

    def test_psa_value_tiers_are_paused_with_a_date_and_no_reinstatement(self):
        for tier in ("value", "value_plus", "value_bulk", "value_max"):
            root = f"grading.graders.PSA.tiers.{tier}"
            self.assertEqual(self.cfg.get(f"{root}.availability"), "paused", tier)
            self.assertEqual(self.cfg.get(f"{root}.availability_since"), "2026-06-02", tier)
            self.assertIsNone(self.cfg.get(f"{root}.reinstatement_date", None), tier)

    def test_paused_tier_refuses_even_though_it_is_configured(self):
        cfg = real_config()
        cfg.grading["submission_costs"].update(
            {"inbound_shipping": 10, "return_shipping_insured": 20,
             "supplies_per_card": 1, "default_batch_size": 10})
        cfg.fees["region_defaults"]["default_days_to_sell"] = 30
        cfg.assumptions["tax"]["acquisition_tax_pct"]["value"] = 0
        cfg.assumptions["submission_selection_haircut"]["value"] = 1.0
        cfg.assumptions["empirical_bayes"]["prior_strength_cards"]["value"] = 20
        cfg.assumptions["empirical_bayes"]["min_card_pop_for_own_prior"]["value"] = 10
        cfg.grading["graders"]["PSA"]["tiers"]["value"]["fee"] = 25
        cfg.grading["graders"]["PSA"]["tiers"]["value"]["turnaround_business_days"] = 90
        cfg.grading["graders"]["PSA"]["tiers"]["value"]["min_cards"] = 20
        from engine.ev.results import GradeDistribution
        r = raw_to_graded_ev("x", usd(100), "value", {"10": usd(500)}, cfg=cfg,
                             grade_probs=GradeDistribution(probs={"10": D(1)},
                                                           prior_used="test"))
        self.assertIsInstance(r, Refusal)
        self.assertEqual(r.reason, "tier unavailable")

    def test_other_graders_are_populated(self):
        for grader, tier, fee in (("CGC", "economy", "15.00"), ("CGC", "bulk", "12.00"),
                                  ("BGS", "economy", "20.00"), ("SGC", "economy", "25.00"),
                                  ("TAG", "bulk", "12.00")):
            self.assertEqual(
                self.cfg.decimal(f"grading.graders.{grader}.tiers.{tier}.fee"), D(fee),
                f"{grader}/{tier}")
        self.assertEqual(self.cfg.get("grading.graders.CGC.tiers.bulk.min_cards"), 25)

    def test_my_own_costs_are_still_null_and_refusing(self):
        from engine.ev.config import MISSING
        for path in ("grading.submission_costs.inbound_shipping",
                     "grading.submission_costs.supplies_per_card",
                     "grading.submission_costs.default_batch_size",
                     "assumptions.tax.acquisition_tax_pct.value"):
            self.assertIs(self.cfg.get(path), MISSING, path)

    def test_deliberately_unpopulated_marketplaces_stay_null(self):
        from engine.ev.config import MISSING
        for venue in ("mercari_jp", "snkrdunk", "xianyu", "cardmarket"):
            self.assertIs(self.cfg.get(f"fees.marketplaces.{venue}.fee_schedule"),
                          MISSING, venue)


if __name__ == "__main__":
    unittest.main(verbosity=2)
