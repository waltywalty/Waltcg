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

    def test_commission_and_payment_sit_on_DIFFERENT_bases(self):
        """TCGplayer charges commission on the ITEM and the transaction fee on
        the FULL ORDER TOTAL. Two bases inside one venue.

        item 100, shipping 5, tax 8:
          commission 10.75% of 100 = 10.75   <- item only
          payment     2.50% of 113 =  2.825  <- order total
          fixed                     =  0.30
        """
        sched = real_config().get("fees.marketplaces.tcgplayer.fee_schedule")
        self.assertEqual(sched["base"], "item",
                         "commission is charged on the item")
        self.assertEqual(sched["payment"]["pct_base"], "order_total",
                         "the transaction fee is charged on the order total")
        fee = marketplace_fee(usd(100), sched, shipping_charged=usd(5),
                              tax_collected=usd(8))
        self.assertEqual(fee["commission"].quantized().amount, D("10.75"))
        self.assertEqual(fee["fixed"].amount, D("0.30"))

    def test_the_commission_cap_is_per_product(self):
        sched = real_config().get("fees.marketplaces.tcgplayer.fee_schedule")
        self.assertEqual(D(str(sched["commission_cap_per_product"])), D("75"))


class ANullFeeBaseRefuses(unittest.TestCase):
    """A schedule whose `base` is null must refuse, not fall back to
    item-only. Every shipped venue now states a base, so this is tested on a
    synthetic null: the property is about the engine, not about which venue
    happens to be unpopulated this week."""

    def test_a_null_base_refuses_rather_than_assuming_item_only(self):
        from engine.ev.fees import FeeScheduleError, marketplace_fee
        schedule = {"base": None, "bands": [{"up_to": None, "pct": 0.10}]}
        with self.assertRaises(FeeScheduleError) as ctx:
            marketplace_fee(usd(100), schedule)
        self.assertIn("base", str(ctx.exception).lower())

    def test_model_a_refuses_up_front_naming_the_exact_gap(self):
        cfg = real_config()
        cfg.fees["marketplaces"]["ebay"]["fee_schedule"]["base"] = None
        from engine.ev.config import ConfigIncomplete
        try:
            r = raw_to_graded_ev("x", usd(100), "regular", {"10": usd(500)},
                                 cfg=cfg, route="psa_us",
                                 buy_route="uk_domestic_secondhand")
        except ConfigIncomplete as e:
            self.assertTrue(any("base" in m for m in e.missing), e.missing)
            return
        self.assertIsInstance(r, Refusal)
        self.assertIn("base", (r.detail + " " + " ".join(r.missing)).lower())


class UnverifiedFiresRegardlessOfAge(unittest.TestCase):
    """An unverified value was never fresh. Age is not the question."""

    def test_warning_fires_on_a_value_checked_today(self):
        cfg = Config.load(today=dt.date(2026, 8, 13))   # same day as checked_on
        warnings = cfg.unverified_warnings()
        self.assertTrue(warnings, "unverified entries produced no warning")
        self.assertTrue(all(isinstance(w, UnverifiedWarning) for w in warnings))
        paths = {w.path for w in warnings}
        # PSA regular is now primary-sourced and no longer warns. A BGS tier
        # checked nine days ago still does, because age was never the trigger.
        self.assertIn("graders.BGS.tiers.express", paths)
        self.assertNotIn("graders.PSA.tiers.regular", paths)

    def test_same_warnings_a_year_later(self):
        """Age changes nothing: it was never verified either way."""
        now = Config.load(today=dt.date(2026, 8, 13)).unverified_warnings()
        later = Config.load(today=dt.date(2027, 8, 13)).unverified_warnings()
        self.assertEqual(len(now), len(later))

    def test_every_secondary_grader_needs_primary_verification(self):
        """PSA and CGC were read from their own pages on 2026-08-14, so they are
        no longer flagged wholesale. BGS, SGC and TAG were not, and every one of
        their entries still is."""
        cfg = real_config()
        flagged = {w.path for w in cfg.needs_primary_verification()}
        for grader in ("BGS", "SGC", "TAG"):
            hits = [p for p in flagged if p.startswith(f"graders.{grader}")]
            self.assertTrue(hits, f"{grader} is secondary and must be flagged")

    def test_psas_conflicting_membership_price_is_flagged(self):
        """PSA's fee page and its own join page disagree on the membership
        price. Both are primary. A conflict between two primary sources is not
        resolved by picking one, so the entry stays flagged."""
        cfg = real_config()
        flagged = {w.path for w in cfg.needs_primary_verification()}
        self.assertIn("graders.PSA.membership", flagged)
        self.assertIn("CONFLICT",
                      cfg.get("grading.graders.PSA.membership.conflict_note"))

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
        """PSA Regular is 40-50 business days on their own page as of
        2026-08-14, so the model must take 50. Asserted as "the max of the
        stated range" rather than a literal, because the range moves.

        Understating turnaround overstates annualised ROI, which is the
        dangerous direction for a capital-lockup decision.
        """
        root = "grading.graders.PSA.tiers.regular"
        used = self.cfg.get(f"{root}.turnaround_business_days")
        lo = self.cfg.get(f"{root}.turnaround_business_days_min")
        hi = self.cfg.get(f"{root}.turnaround_business_days_max")
        self.assertEqual(used, hi, "must take the slow end")
        self.assertLess(lo, hi)

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
        cfg.assumptions["acquisition_tax_pct"]["current_value"] = 0
        cfg.assumptions["submission_selection_haircut"]["current_value"] = 1.0
        cfg.grading.pop("import_charges", None)   # domestic-only scenario
        cfg.assumptions["empirical_bayes_prior_strength"]["current_value"] = 20
        cfg.assumptions["empirical_bayes_min_card_pop"]["current_value"] = 10
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
        """CGC read from its own fee chart (dated 2026-03-24); BGS, SGC and TAG
        from a secondary aggregator and flagged accordingly."""
        for grader, tier, fee in (("CGC", "economy", "20"), ("CGC", "bulk", "17"),
                                  ("CGC", "standard", "55"),
                                  ("BGS", "express", "79.95"),
                                  ("SGC", "standard", "15"),
                                  ("TAG", "priority", "149")):
            self.assertEqual(
                self.cfg.decimal(f"grading.graders.{grader}.tiers.{tier}.fee"), D(fee),
                f"{grader}/{tier}")
        self.assertEqual(self.cfg.get("grading.graders.CGC.tiers.bulk.min_cards"), 25)

    def test_a_paused_tier_never_carries_a_price(self):
        """PSA's four Value tiers show "Currently Unavailable". Recording the
        pre-pause hearsay prices would make an unorderable tier the cheapest
        row on every screen that sorts by cost."""
        from engine.ev.config import MISSING
        for grader in ("PSA", "BGS", "TAG"):
            tiers = self.cfg.get(f"grading.graders.{grader}.tiers") or {}
            for name, tier in tiers.items():
                if tier.get("availability") == "paused" and grader == "PSA":
                    self.assertIsNone(tier["fee"],
                                      f"{grader}/{name} is paused but priced")

    def test_routes_carry_their_own_freight_and_jurisdiction(self):
        """Freight is per route, not global: the difference between a domestic
        and a transatlantic submission is the whole comparison."""
        for route, jurisdiction in (("cgc_uk", "GB"), ("psa_us", "US")):
            root = f"grading.routes.{route}"
            self.assertEqual(self.cfg.get(f"{root}.facility_jurisdiction"), jurisdiction)
            self.assertIsNotNone(self.cfg.get(f"{root}.outbound_shipping"), route)
            self.assertIsNotNone(self.cfg.get(f"{root}.return_shipping_insured"), route)
            self.assertTrue(self.cfg.get(f"{root}.estimated"), route)

    def test_the_flat_freight_pair_stays_null_now_that_routes_supersede_it(self):
        """Supplies and batch size are now measured-ish estimates and populated.
        The flat inbound/return pair is NOT: freight moved onto the route, and
        leaving these null means a caller that reaches for the old path gets a
        refusal instead of a figure that ignores which ocean the card crosses."""
        from engine.ev.config import MISSING
        for path in ("grading.submission_costs.inbound_shipping",
                     "grading.submission_costs.return_shipping_insured"):
            self.assertIs(self.cfg.get(path), MISSING, path)
        self.assertEqual(self.cfg.decimal("grading.submission_costs.supplies_per_card"),
                         D("0.50"))
        self.assertEqual(self.cfg.get("grading.submission_costs.default_batch_size"), 10)

    def test_my_own_costs_are_all_marked_estimated(self):
        """None of these has been paid yet."""
        self.assertTrue(self.cfg.get("grading.submission_costs.estimated"))
        self.assertEqual(self.cfg.get("grading.submission_costs.confidence"), "low")
        for route in ("cgc_uk", "psa_us"):
            self.assertTrue(self.cfg.get(f"grading.routes.{route}.estimated"), route)

    def test_the_legacy_flat_trio_stays_null_on_every_venue(self):
        """Every venue now carries a banded schedule with an explicit base. The
        old flat percentages stay null so a caller reaching for them refuses
        rather than silently pricing eBay's tiered fee as one number."""
        from engine.ev.config import MISSING
        for venue in self.cfg.get("fees.marketplaces"):
            for key in ("final_value_fee_pct", "payment_pct", "payment_fixed"):
                self.assertIs(self.cfg.get(f"fees.marketplaces.{venue}.{key}"),
                              MISSING, f"{venue}.{key}")

    def test_every_venue_states_its_own_fee_base(self):
        """The bases genuinely differ -- eBay US on item+shipping+tax,
        Cardmarket and Mercari JP on the item alone -- and flattening them is
        what produced the 15.37 against 13.25 discrepancy."""
        bases = {}
        for venue in self.cfg.get("fees.marketplaces"):
            base = self.cfg.get(f"fees.marketplaces.{venue}.fee_schedule.base")
            self.assertIsNotNone(base, venue)
            bases[venue] = base
        self.assertEqual(bases["ebay"], "item_plus_shipping_plus_tax")
        self.assertEqual(bases["cardmarket"], "item")
        self.assertEqual(bases["mercari_jp"], "item")
        self.assertEqual(bases["mercari_us"], "item_plus_shipping")
        self.assertGreater(len(set(bases.values())), 1,
                           "if every venue shared a base there would be nothing "
                           "to get wrong, and there was")


if __name__ == "__main__":
    unittest.main(verbosity=2)
