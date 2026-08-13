"""Golden fixtures and property tests for engine/ev.

Every golden case uses round numbers chosen so the arithmetic can be checked
on paper. The expected values in the docstrings are the hand computation; the
assertions are the machine's answer. If they ever disagree, the docstring is
the specification and the code is wrong.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime as dt
import sys
import os
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ev import (Config, ConfigIncomplete, FxRate, Money, Refusal,  # noqa: E402
                       crossover_ev, grade_spread_residual, raw_to_graded_ev,
                       regrade_9_to_10_ev, sealed_ev, shrunk_grade_distribution)
from engine.ev.money import money_sum  # noqa: E402
from engine.ev.breakeven import net_proceeds  # noqa: E402

D = Decimal
TODAY = dt.date(2026, 8, 13)


def filled_config(**overrides) -> Config:
    """A complete config with deliberately round numbers.

    grading fee 20, inbound 10 over a batch of 10 => 1/card,
    return 20 over 10 => 2/card, supplies 1/card.
    Marketplace keeps 90%: fvf 10%, no payment cut, no fixed fee.
    """
    grading = {
        "meta": {"verified_on": "2026-08-01", "staleness_warn_days": 60, "currency": "USD"},
        "graders": {"PSA": {"tiers": {
            "regular": {"fee": 20, "min_cards": 1, "membership_required": False,
                        "turnaround_business_days": 50, "turnaround_observed_days": None,
                        "availability": "open", "effective_from": "2026-06-01"},
            "paused_tier": {"fee": 15, "min_cards": 20, "membership_required": False,
                            "turnaround_business_days": 65, "turnaround_observed_days": None,
                            "availability": "paused", "effective_from": "2026-06-01"},
        }}},
        "submission_costs": {"inbound_shipping": 10, "return_shipping_insured": 20,
                             "supplies_per_card": 1, "default_batch_size": 10,
                             "inbound_insurance": 0},
    }
    fees = {
        "meta": {"verified_on": "2026-08-01", "staleness_warn_days": 60,
                 "home_currency": "USD", "home_region": "US"},
        "marketplaces": {"ebay": {
            "currency": "USD", "final_value_fee_pct": 0.10, "payment_pct": 0.0,
            "payment_fixed": 0, "fx_conversion_pct": 0.0}},
        "region_defaults": {"default_days_to_sell": 30},
    }
    assumptions = {
        "meta": {"verified_on": "2026-08-01", "staleness_warn_days": 60},
        "submission_selection_haircut": {"value": 1.0},
        "regrade_conditional_prior": {
            "value": 0.10,
            "conditional_adjustments": {
                "centering_pct_ge_60_40": 1.0, "centering_pct_ge_55_45": 1.5,
                "corner_flag_clean": 1.2, "surface_flag_clean": 1.2,
                "edge_flag_clean": 1.0, "any_flag_dirty": 0.5},
            "p_downgrade_below_9": {"value": 0.05}},
        "empirical_bayes": {"prior_strength_cards": {"value": 20},
                            "min_card_pop_for_own_prior": {"value": 10},
                            "fallback_when_no_set_data": {"value": "refuse"}},
        "tax": {"acquisition_tax_pct": {"value": 0.0}},
        "min_comp_sample_size": {"value": 5, "window_days": 90},
        "days_to_sell": {"value": 30},
        "pull_rate_estimates": {"by_product": {}},
    }
    crossover = {
        "meta": {"verified_on": "2026-08-01", "staleness_warn_days": 60, "sample_size": 200},
        "rules": [
            {"id": "bgs_95_balanced", "match": {"bgs_overall": 9.5, "min_subgrade": 9.5},
             "p_psa_10": 0.60, "p_psa_9": 0.35, "p_psa_below_9": 0.05,
             "source": "test fixture"},
            {"id": "bgs_95_single_9_corners",
             "match": {"bgs_overall": 9.5, "single_9_category": "corners"},
             "p_psa_10": 0.15, "p_psa_9": 0.70, "p_psa_below_9": 0.15,
             "source": "test fixture"},
            {"id": "bgs_95_single_9_centering",
             "match": {"bgs_overall": 9.5, "single_9_category": "centering"},
             "p_psa_10": 0.45, "p_psa_9": 0.50, "p_psa_below_9": 0.05,
             "source": "test fixture"},
        ],
        "crack_and_resubmit": {"p_damage_during_crack": 0.02,
                               "damage_residual_value_pct": 0.10,
                               "source": "test fixture"},
        "psa_crossover_path": {"fee_charged_on_failure": False, "fee_on_failure": 0,
                               "original_slab_returned": True, "source": "test fixture"},
    }
    cfg = Config(grading=grading, fees=fees, assumptions=assumptions,
                 crossover_rules=crossover, today=TODAY)
    for path, value in overrides.items():
        node = cfg
        parts = path.split(".")
        target = getattr(cfg, parts[0])
        for p in parts[1:-1]:
            target = target[p]
        target[parts[-1]] = value
    return cfg


def usd(x):
    return Money(str(x), "USD")


class GoldenModelA(unittest.TestCase):
    """Hand-computable break-even cases for raw_to_graded_ev."""

    def test_obviously_worth_grading(self):
        """Acquisition 200. Costs 200+0+1+1+20+2 = 224.

        Keep 90%. Comps 10/9/8 = 1000/200/100 -> net 900/180/90.
        Probs .5/.4/.1  =>  EV proceeds = 450+72+9 = 531,  EV = 531-224 = 307.
        Non-target blend A = (.4*180 + .1*90)/.5 = 162.
        break-even p = (224-162)/(900-162) = 62/738 = 0.08401084...
        Modelled .5, so the card clears its bar by a wide margin.
        """
        cfg = filled_config()
        r = raw_to_graded_ev(
            "golden/worth-it", usd(200), "regular",
            {"10": usd(1000), "9": usd(200), "8": usd(100)}, cfg=cfg,
            grade_probs=_dist({"10": "0.5", "9": "0.4", "8": "0.1"}))
        self.assertTrue(r.ok)
        self.assertEqual(r.costs.total().quantized().amount, D("224.00"))
        self.assertEqual(r.ev.quantized().amount, D("307.00"))
        self.assertAlmostEqual(float(r.break_even_p_target), 62 / 738, places=12)
        self.assertGreater(r.margin, 0)

    def test_obviously_not_worth_grading(self):
        """Acquisition 500 -> costs 524. Comps 600/400/300 -> net 540/360/270.

        Probs .1/.6/.3 => EV proceeds = 54+216+81 = 351, EV = -173.
        A = (.6*360 + .3*270)/.9 = 330. break-even = (524-330)/(540-330)
          = 194/210 = 0.92380952...  Modelled .1: nowhere near.
        """
        cfg = filled_config()
        r = raw_to_graded_ev(
            "golden/not-worth-it", usd(500), "regular",
            {"10": usd(600), "9": usd(400), "8": usd(300)}, cfg=cfg,
            grade_probs=_dist({"10": "0.1", "9": "0.6", "8": "0.3"}))
        self.assertEqual(r.ev.quantized().amount, D("-173.00"))
        self.assertAlmostEqual(float(r.break_even_p_target), 194 / 210, places=12)
        self.assertLess(r.margin, 0)

    def test_exactly_break_even(self):
        """Tuned so EV == 0 and break-even p == modelled p exactly.

        No fees at all: net == comp. Comps 10 -> 500, 9 -> 100.
        Probs .25/.75 => proceeds = 125 + 75 = 200.
        Costs: acquisition 176 + inbound 1 + supplies 1 + fee 20 + return 2 = 200.
        EV = 0. break-even = (200-100)/(500-100) = 0.25 = modelled. Margin 0.
        """
        cfg = filled_config()
        cfg.fees["marketplaces"]["ebay"]["final_value_fee_pct"] = 0.0
        r = raw_to_graded_ev(
            "golden/break-even", usd(176), "regular",
            {"10": usd(500), "9": usd(100)}, cfg=cfg,
            grade_probs=_dist({"10": "0.25", "9": "0.75"}))
        self.assertEqual(r.ev.quantized().amount, D("0.00"))
        self.assertEqual(r.break_even_p_target, D("0.25"))
        self.assertEqual(r.margin, D("0"))

    def test_jpy_acquisition_sold_in_usd_round_trip_exact(self):
        """15000 JPY at a non-terminating rate, converted and converted back.

        Rate JPY->USD = 1/150, which has no exact decimal expansion. Forward
        gives 100.00 USD after quantisation. Converting back must return
        EXACTLY 15000 JPY -- not 15000.000000000000000000000001 -- which a
        naive multiply-back does not achieve. That is the whole point of
        carrying provenance on Money.
        """
        rate = FxRate("JPY", "USD", D(1) / D(150), as_of="2026-08-13", source="test")
        jpy = Money("15000", "JPY")
        usd_amount = jpy.to("USD", rate)
        self.assertEqual(usd_amount.quantized().amount, D("100.00"))

        back = usd_amount.to("JPY", rate.inverted())
        self.assertEqual(back.amount, D("15000"))       # provenance path is exact
        self.assertEqual(back.currency, "JPY")

        # And the converted acquisition drives the model in USD terms.
        cfg = filled_config()
        r = raw_to_graded_ev(
            "golden/jpy-acquisition", usd_amount.quantized(), "regular",
            {"10": usd(1000), "9": usd(200), "8": usd(100)}, cfg=cfg,
            grade_probs=_dist({"10": "0.5", "9": "0.4", "8": "0.1"}))
        # Costs 100 + 1 + 1 + 20 + 2 = 124; EV = 531 - 124 = 407.
        self.assertEqual(r.costs.total().quantized().amount, D("124.00"))
        self.assertEqual(r.ev.quantized().amount, D("407.00"))

    def test_fx_round_trip_exact_where_naive_arithmetic_fails(self):
        """A rate whose round-trip genuinely breaks under plain Decimal.

        At 1/150 the naive path happens to land back on 15000, so it proves
        nothing. At 1/7 it does not: multiplying back gives
        15000.00000000000000000000001. Provenance is what makes the round-trip
        exact, and this is the case that demonstrates it.
        """
        rate = FxRate("JPY", "USD", D(1) / D(7), as_of="2026-08-13")
        jpy = Money("15000", "JPY")
        usd_amount = jpy.to("USD", rate)

        naive = usd_amount.amount * D(7)
        self.assertNotEqual(naive, D("15000"))       # plain arithmetic drifts

        back = usd_amount.to("JPY", rate.inverted())
        self.assertEqual(back.amount, D("15000"))    # provenance is exact
        self.assertIs(back.origin, usd_amount)

    def test_currency_mismatch_is_refused_not_coerced(self):
        cfg = filled_config()
        r = raw_to_graded_ev("golden/mismatch", Money("15000", "JPY"), "regular",
                             {"10": usd(1000)}, cfg=cfg,
                             grade_probs=_dist({"10": "1.0"}))
        self.assertIsInstance(r, Refusal)
        self.assertIn("currency", r.reason)

    def test_missing_comp_for_a_weighted_grade_refuses(self):
        """ADR-0001: an EV is a claim about every branch carrying mass.

        Before this rule the model silently priced the un-comped PSA 10 branch
        at zero and returned EV -143.00 -- a confident number meaning "do not
        grade this", when the truth was "we do not know what a 10 sells for".
        """
        cfg = filled_config()
        r = raw_to_graded_ev(
            "golden/no-psa10-comp", usd(200), "regular",
            {"9": usd(200), "8": usd(100)}, cfg=cfg,
            grade_probs=_dist({"10": "0.5", "9": "0.4", "8": "0.1"}))
        self.assertIsInstance(r, Refusal)
        self.assertEqual(r.reason, "missing comps for graded outcomes")
        self.assertEqual(r.missing, ["comps_by_grade['10']"])

    def test_zero_weight_grade_needs_no_comp(self):
        """The rule is about branches that carry mass, not every conceivable grade."""
        cfg = filled_config()
        r = raw_to_graded_ev(
            "golden/zero-weight", usd(200), "regular",
            {"10": usd(1000), "9": usd(200)}, cfg=cfg,
            grade_probs=_dist({"10": "0.5", "9": "0.5", "8": "0"}))
        self.assertTrue(r.ok)

    def test_paused_tier_is_refused(self):
        cfg = filled_config()
        r = raw_to_graded_ev("golden/paused", usd(200), "paused_tier",
                             {"10": usd(1000)}, cfg=cfg,
                             grade_probs=_dist({"10": "1.0"}))
        self.assertIsInstance(r, Refusal)
        self.assertEqual(r.reason, "tier unavailable")


class GoldenRefusals(unittest.TestCase):

    def test_null_config_refuses_and_names_every_gap(self):
        """The real, unfilled config must refuse -- not warn, refuse."""
        cfg = Config.load(today=TODAY)
        with self.assertRaises(ConfigIncomplete) as ctx:
            raw_to_graded_ev("real/config", usd(100), "regular",
                             {"10": usd(500)}, cfg=cfg,
                             grade_probs=_dist({"10": "1.0"}))
        self.assertGreater(len(ctx.exception.missing), 10)
        self.assertIn("grading.meta.currency", ctx.exception.missing)
        self.assertIn("refusing to compute", str(ctx.exception))

    def test_zero_sample_size_refuses_rather_than_guessing(self):
        """Model D must suppress thin comps, then refuse to fit on what is left."""
        cfg = filled_config()
        cards = [
            {"card_uid": "thin-1", "game": "pokemon", "rarity_band": "SIR", "era": "sv",
             "p10_median": 500, "p9_median": 100, "p10_sample": 3, "p9_sample": 2,
             "pop10": 100, "pop9": 400},
            {"card_uid": "thin-2", "game": "pokemon", "rarity_band": "SIR", "era": "sv",
             "p10_median": 400, "p9_median": 120, "p10_sample": 1, "p9_sample": 4,
             "pop10": 90, "pop9": 300},
        ]
        r = grade_spread_residual(cards, cfg=cfg)
        self.assertIsInstance(r, Refusal)
        self.assertIn("not enough usable cards", r.reason)
        self.assertIn("suppressed 2", r.detail)

    def test_no_population_data_refuses(self):
        cfg = filled_config()
        r = raw_to_graded_ev("golden/no-pop", usd(100), "regular", {"10": usd(500)},
                             cfg=cfg, card_pop=None, set_pop=None)
        self.assertIsInstance(r, Refusal)
        self.assertEqual(r.reason, "no population data")

    def test_stale_config_warns_but_still_computes(self):
        """Stale is a warning attached to the result, not a refusal."""
        cfg = filled_config()
        for node in (cfg.grading, cfg.fees, cfg.assumptions, cfg.crossover_rules):
            node["meta"]["verified_on"] = "2026-01-01"        # 224 days before TODAY
        r = raw_to_graded_ev("golden/stale", usd(200), "regular",
                             {"10": usd(1000), "9": usd(200), "8": usd(100)}, cfg=cfg,
                             grade_probs=_dist({"10": "0.5", "9": "0.4", "8": "0.1"}))
        self.assertTrue(r.ok)
        self.assertTrue(r.provenance.warnings)
        self.assertTrue(any("224 days ago" in w for w in r.provenance.warnings))
        self.assertEqual(r.ev.quantized().amount, D("307.00"))


class GoldenModelB(unittest.TestCase):

    def test_no_condition_read_returns_refusal_not_a_number(self):
        cfg = filled_config()
        r = regrade_9_to_10_ev("golden/regrade", usd(300),
                               {"10": usd(1000), "9": usd(300), "below_9": usd(80)},
                               cfg=cfg, condition_read=None)
        self.assertIsInstance(r, Refusal)
        self.assertEqual(r.reason, "no condition read supplied")
        self.assertEqual(set(r.missing),
                         {"centering_pct", "corner_flag", "surface_flag", "edge_flag"})

    def test_partial_condition_read_also_refuses(self):
        cfg = filled_config()
        r = regrade_9_to_10_ev("golden/regrade", usd(300),
                               {"10": usd(1000), "9": usd(300), "below_9": usd(80)},
                               cfg=cfg,
                               condition_read={"centering_pct": 60, "corner_flag": "clean",
                                               "surface_flag": None, "edge_flag": "clean"})
        self.assertIsInstance(r, Refusal)
        self.assertEqual(r.reason, "incomplete condition read")
        self.assertEqual(r.missing, ["surface_flag"])

    def test_never_uses_base_gem_rate(self):
        """Prior comes from assumptions, never from the population gem rate.

        Default prior .10; centering >= 60 x1.0; corners clean x1.2;
        surface clean x1.2; edges clean x1.0  =>  .10 * 1.44 = .144
        P(<9) = .05, so P(9) = 1 - .144 - .05 = .806
        """
        cfg = filled_config()
        r = regrade_9_to_10_ev(
            "golden/regrade", usd(300),
            {"10": usd(1000), "9": usd(300), "below_9": usd(80)}, cfg=cfg,
            condition_read={"centering_pct": 60, "corner_flag": "clean",
                            "surface_flag": "clean", "edge_flag": "clean"})
        self.assertTrue(r.ok)
        self.assertEqual(r.grade_distribution.p("10"), D("0.144"))
        self.assertEqual(r.grade_distribution.p("below_9"), D("0.05"))
        self.assertEqual(r.grade_distribution.p("9"), D("0.806"))
        self.assertIn("FORBIDDEN", r.grade_distribution.prior_used)
        self.assertEqual(len(r.branches), 3)

    def test_dirty_flag_reduces_prior(self):
        cfg = filled_config()
        clean = regrade_9_to_10_ev(
            "c", usd(300), {"10": usd(1000), "9": usd(300), "below_9": usd(80)}, cfg=cfg,
            condition_read={"centering_pct": 60, "corner_flag": "clean",
                            "surface_flag": "clean", "edge_flag": "clean"})
        dirty = regrade_9_to_10_ev(
            "d", usd(300), {"10": usd(1000), "9": usd(300), "below_9": usd(80)}, cfg=cfg,
            condition_read={"centering_pct": 60, "corner_flag": "chipped",
                            "surface_flag": "clean", "edge_flag": "clean"})
        self.assertLess(dirty.grade_distribution.p("10"), clean.grade_distribution.p("10"))


class GoldenModelC(unittest.TestCase):

    def test_two_paths_never_merge_and_differ_in_downside(self):
        cfg = filled_config()
        subs = {"centering": 9.5, "corners": 9.5, "edges": 9.5, "surface": 9.5}
        comps = {"10": usd(1000), "9": usd(300), "below_9": usd(80),
                 "original_slab": usd(400)}
        cross = crossover_ev("golden/cross", "psa_crossover", usd(400), comps, cfg=cfg,
                             bgs_overall=9.5, subgrades=subs)
        crack = crossover_ev("golden/cross", "crack_resubmit", usd(400), comps, cfg=cfg,
                             bgs_overall=9.5, subgrades=subs)
        self.assertTrue(cross.ok and crack.ok)
        self.assertIn("psa_crossover", cross.model)
        self.assertIn("crack_resubmit", crack.model)
        # The crossover path's downside keeps the original slab; the crack
        # path's worst branch is a damaged card.
        self.assertEqual(cross.downside_case["branch"], "returned_in_original_slab")
        self.assertEqual(crack.downside_case["branch"], "damaged")
        self.assertLess(crack.ev.amount, cross.ev.amount)

    def test_corners_nine_is_worse_than_centering_nine(self):
        """The subgrade rules table must express PSA's asymmetry."""
        cfg = filled_config()
        comps = {"10": usd(1000), "9": usd(300), "below_9": usd(80),
                 "original_slab": usd(400)}
        corners = crossover_ev(
            "c", "psa_crossover", usd(400), comps, cfg=cfg, bgs_overall=9.5,
            subgrades={"centering": 9.5, "corners": 9.0, "edges": 9.5, "surface": 9.5})
        centering = crossover_ev(
            "c", "psa_crossover", usd(400), comps, cfg=cfg, bgs_overall=9.5,
            subgrades={"centering": 9.0, "corners": 9.5, "edges": 9.5, "surface": 9.5})
        self.assertLess(corners.modelled_p_target, centering.modelled_p_target)
        self.assertTrue(any("HARD RED FLAG" in n
                            for n in corners.grade_distribution.notes))

    def test_crack_path_requires_nonzero_damage_probability(self):
        cfg = filled_config()
        cfg.crossover_rules["crack_and_resubmit"]["p_damage_during_crack"] = 0
        r = crossover_ev("c", "crack_resubmit", usd(400),
                         {"10": usd(1000), "9": usd(300), "below_9": usd(80)},
                         cfg=cfg, bgs_overall=9.5,
                         subgrades={"centering": 9.5, "corners": 9.5,
                                    "edges": 9.5, "surface": 9.5})
        self.assertIsInstance(r, Refusal)
        self.assertIn("damage", r.reason)


class GoldenModelD(unittest.TestCase):

    def test_suppresses_thin_comps_and_reports_sample_size(self):
        cfg = filled_config()
        cards = [dict(card_uid=f"c{i}", game="pokemon", rarity_band="SIR", era="sv",
                      p10_median=400 + 10 * i, p9_median=100, p10_sample=10, p9_sample=10,
                      pop10=100 + 12 * i, pop9=400 + i) for i in range(8)]
        cards.append(dict(card_uid="thin", game="pokemon", rarity_band="SIR", era="sv",
                          p10_median=900, p9_median=100, p10_sample=2, p9_sample=9,
                          pop10=50, pop9=500))
        out = grade_spread_residual(cards, cfg=cfg)
        self.assertTrue(out["ok"])
        self.assertEqual(out["n_suppressed"], 1)
        self.assertEqual(out["suppressed"][0].card_uid, "thin")
        self.assertIn("PSA 10 comps 2 < 5", out["suppressed"][0].suppression_reason)
        for row in out["ranked"]:
            self.assertGreaterEqual(row.sample_size_p10, 5)
            self.assertGreaterEqual(row.sample_size_p9, 5)

    def test_ranked_most_negative_residual_first(self):
        cfg = filled_config()
        # Population ratio must VARY across the cross-section, otherwise the
        # regressor is constant, collinear with the intercept, and the model
        # correctly refuses rather than fitting a singular design.
        cards = [dict(card_uid=f"c{i}", game="pokemon", rarity_band="SIR", era="sv",
                      p10_median=500, p9_median=100, p10_sample=10, p9_sample=10,
                      pop10=100 + 10 * i, pop9=400) for i in range(6)]
        cards[3]["p10_median"] = 200          # cheap 10 relative to peers
        out = grade_spread_residual(cards, cfg=cfg)
        self.assertEqual(out["ranked"][0].card_uid, "c3")
        self.assertLess(out["ranked"][0].residual, 0)

    def test_collinear_cross_section_is_refused(self):
        """Identical population ratios make the regressor constant.

        With nothing but an intercept to explain the spread, every residual
        would be an artefact. Refuse rather than rank noise.
        """
        cfg = filled_config()
        cards = [dict(card_uid=f"c{i}", game="pokemon", rarity_band="SIR", era="sv",
                      p10_median=500, p9_median=100, p10_sample=10, p9_sample=10,
                      pop10=100, pop9=400) for i in range(6)]
        out = grade_spread_residual(cards, cfg=cfg)
        self.assertIsInstance(out, Refusal)
        self.assertEqual(out.reason, "singular design matrix")

    def test_deterministic_across_calls(self):
        cfg = filled_config()
        cards = [dict(card_uid=f"c{i}", game="pokemon", rarity_band="SIR", era="sv",
                      p10_median=400 + 7 * i, p9_median=100 + i, p10_sample=9, p9_sample=9,
                      pop10=100 + 3 * i, pop9=400 - 2 * i) for i in range(7)]
        a = grade_spread_residual(cards, cfg=cfg)
        b = grade_spread_residual(cards, cfg=cfg)
        self.assertEqual([r.residual for r in a["ranked"]],
                         [r.residual for r in b["ranked"]])


class GoldenModelE(unittest.TestCase):

    def test_low_confidence_flag_is_immutable(self):
        cfg = filled_config()
        cfg.assumptions["pull_rate_estimates"]["by_product"]["sv3-booster-box"] = {
            "packs_per_box": 36, "cards_per_pack": 10,
            "rates": {"SIR": 0.02, "IR": 0.10}, "source": "community thread",
            "sample_size": 400}
        out = sealed_ev("sv3-booster-box", cfg=cfg, box_market_price=usd(150),
                        singles_basket_cost=usd(400),
                        value_by_rarity={"SIR": usd(120), "IR": usd(8)})
        self.assertTrue(out["ok"])
        self.assertEqual(out["confidence"], "low")
        self.assertTrue(out["confidence_immutable"])
        # per pack = .02*120 + .10*8 = 2.4 + 0.8 = 3.20; per box = 3.20*36 = 115.20
        self.assertEqual(out["expected_singles_value_per_pack"]["amount"], "3.20")
        self.assertEqual(out["expected_singles_value_per_box"]["amount"], "115.20")
        self.assertFalse(out["ripping_beats_buying_box"])   # 115.20 < 150

    def test_rates_summing_above_one_refuses(self):
        cfg = filled_config()
        cfg.assumptions["pull_rate_estimates"]["by_product"]["bad"] = {
            "packs_per_box": 36, "cards_per_pack": 10,
            "rates": {"A": 0.7, "B": 0.5}, "source": "x", "sample_size": 1}
        out = sealed_ev("bad", cfg=cfg, box_market_price=usd(150),
                        value_by_rarity={"A": usd(1), "B": usd(1)})
        self.assertIsInstance(out, Refusal)
        self.assertIn("inconsistent", out.reason)


class GoalD2Compliance(unittest.TestCase):
    """docs/GOAL.md D2: every calculator emits a break-even threshold."""

    def _cfg(self):
        cfg = filled_config()
        cfg.assumptions["pull_rate_estimates"]["by_product"]["box"] = {
            "packs_per_box": 36, "cards_per_pack": 10,
            "rates": {"SIR": 0.02, "IR": 0.10}, "source": "fixture",
            "sample_size": 400}
        return cfg

    def test_models_a_b_c_emit_break_even_probability(self):
        cfg = self._cfg()
        a = raw_to_graded_ev("a", usd(200), "regular",
                             {"10": usd(1000), "9": usd(200), "8": usd(100)}, cfg=cfg,
                             grade_probs=_dist({"10": "0.5", "9": "0.4", "8": "0.1"}))
        b = regrade_9_to_10_ev("b", usd(300),
                               {"10": usd(1000), "9": usd(300), "below_9": usd(80)},
                               cfg=cfg,
                               condition_read={"centering_pct": 60, "corner_flag": "clean",
                                               "surface_flag": "clean",
                                               "edge_flag": "clean"})
        c = crossover_ev("c", "psa_crossover", usd(400),
                         {"10": usd(1000), "9": usd(300), "below_9": usd(80),
                          "original_slab": usd(400)}, cfg=cfg, bgs_overall=9.5,
                         subgrades={"centering": 9.5, "corners": 9.5,
                                    "edges": 9.5, "surface": 9.5})
        for name, r in (("A", a), ("B", b), ("C", c)):
            self.assertTrue(r.ok, name)
            self.assertIsNotNone(r.break_even_p_target, f"Model {name} has no threshold")
            self.assertIsNotNone(r.margin, f"Model {name} has no margin")

    def test_model_d_emits_a_break_even_price_per_row(self):
        """The residual is the point estimate; the threshold is the fair price."""
        cfg = self._cfg()
        cards = [dict(card_uid=f"c{i}", game="pokemon", rarity_band="SIR", era="sv",
                      p10_median=500, p9_median=100, p10_sample=9, p9_sample=9,
                      pop10=100 + 10 * i, pop9=400) for i in range(6)]
        cards[2]["p10_median"] = 250
        out = grade_spread_residual(cards, cfg=cfg)
        self.assertTrue(out["ok"])
        for row in out["ranked"]:
            self.assertIsNotNone(row.break_even_p10_median)
            self.assertIsNotNone(row.pct_move_to_fair)
        cheap = next(r for r in out["ranked"] if r.card_uid == "c2")
        # The cheap card must need an UPWARD move to reach fair value.
        self.assertGreater(cheap.pct_move_to_fair, 0)

    def test_model_e_emits_a_break_even_pull_rate(self):
        """box 150 / 36 packs = 4.16667; IR contributes .10*8 = .80;
        break-even SIR rate = (4.16667 - .80) / 120 = 0.0280555...
        Modelled .02, so ripping does not clear the bar."""
        cfg = self._cfg()
        out = sealed_ev("box", cfg=cfg, box_market_price=usd(150),
                        value_by_rarity={"SIR": usd(120), "IR": usd(8)})
        be = out["break_even"]
        self.assertEqual(be["band"], "SIR")
        self.assertAlmostEqual(float(be["break_even_pull_rate"]),
                               (150 / 36 - 0.80) / 120, places=10)
        self.assertLess(D(be["margin"]), 0)
        self.assertTrue(be["attainable"])


class AuditLayer1(unittest.TestCase):
    """AUDIT_PROTOCOL Layer 1 requirements not covered elsewhere. Merge-blocking."""

    def test_break_even_p_is_bounded_or_declared_impossible(self):
        """In [0,1], or the result says plainly that no probability works."""
        cfg = filled_config()
        # Profitable case: bounded and attainable.
        ok = raw_to_graded_ev("bounded", usd(200), "regular",
                              {"10": usd(1000), "9": usd(200), "8": usd(100)}, cfg=cfg,
                              grade_probs=_dist({"10": "0.5", "9": "0.4", "8": "0.1"}))
        self.assertTrue(ok.break_even_attainable)
        self.assertGreaterEqual(ok.break_even_p_target, 0)
        self.assertLessEqual(ok.break_even_p_target, 1)

        # Hopeless case: acquisition far above what a 10 could ever net.
        bad = raw_to_graded_ev("impossible", usd(5000), "regular",
                               {"10": usd(600), "9": usd(400), "8": usd(300)}, cfg=cfg,
                               grade_probs=_dist({"10": "0.1", "9": "0.6", "8": "0.3"}))
        self.assertFalse(bad.break_even_attainable)
        self.assertTrue(bad.break_even_note)
        self.assertIn("cannot pay for itself", bad.break_even_note)

        # The contract, stated as one assertion over both.
        for r in (ok, bad):
            p = r.break_even_p_target
            self.assertTrue(
                p is None or (0 <= p <= 1) or not r.break_even_attainable,
                f"{r.subject}: p={p} out of range without declaring impossibility")

    def test_target_worth_no_more_than_alternatives_is_impossible_at_any_p(self):
        """When a 10 nets no more than a 9, no probability rescues the trade."""
        cfg = filled_config()
        r = raw_to_graded_ev("flat-comps", usd(200), "regular",
                             {"10": usd(200), "9": usd(200)}, cfg=cfg,
                             grade_probs=_dist({"10": "0.5", "9": "0.5"}))
        self.assertFalse(r.break_even_attainable)
        self.assertIsNone(r.break_even_p_target)
        self.assertIn("no probability", r.break_even_note)

    def test_grade_probs_must_sum_to_one(self):
        """sum(grade_probs) == 1 +/- 1e-9, else refuse."""
        cfg = filled_config()
        bad = raw_to_graded_ev("bad-dist", usd(200), "regular",
                               {"10": usd(1000), "9": usd(200)}, cfg=cfg,
                               grade_probs=_dist({"10": "0.5", "9": "0.3"}))
        self.assertIsInstance(bad, Refusal)
        self.assertIn("sum to 1", bad.reason)

        # Just inside tolerance is accepted.
        edge = raw_to_graded_ev("edge-dist", usd(200), "regular",
                                {"10": usd(1000), "9": usd(200)}, cfg=cfg,
                                grade_probs=_dist({"10": "0.5", "9": "0.4999999999"}))
        self.assertTrue(edge.ok)

    def test_shrunk_distribution_always_sums_to_one(self):
        d = shrunk_grade_distribution(
            card_pop={"10": 40, "9": 55, "8": 5}, set_pop={"10": 100, "9": 800, "8": 100},
            prior_strength=20, selection_haircut="0.7", min_card_pop_for_own_prior=10)
        self.assertLess(abs(d.total() - D(1)), D("1e-9"))

    def test_fee_stack_applied_exactly_once_in_both_directions(self):
        """Never zero times, never twice. The invisible error.

        Comp 1000, fvf 10%, payment 2%, fixed 3, outbound 5.
        Applied ONCE:  1000*0.88 - 3 - 5 = 872
        Applied TWICE: 872*0.88 - 3 - 5 = 759.36   (would look plausible)
        Applied ZERO:  1000                        (would look plausible)
        """
        once = net_proceeds(usd(1000), D("0.10"), D("0.02"), usd(3), usd(5))
        self.assertEqual(once.quantized().amount, D("872.00"))

        twice = net_proceeds(once, D("0.10"), D("0.02"), usd(3), usd(5))
        self.assertNotEqual(once.quantized().amount, twice.quantized().amount)
        self.assertEqual(twice.quantized().amount, D("759.36"))

        self.assertNotEqual(once.quantized().amount, D("1000.00"))  # not zero times

        # And end-to-end through Model A: the modelled proceeds for a single
        # grade must equal the single-application figure exactly.
        cfg = filled_config()
        cfg.fees["marketplaces"]["ebay"].update(
            {"final_value_fee_pct": 0.10, "payment_pct": 0.02, "payment_fixed": 3})
        r = raw_to_graded_ev("fee-once", usd(100), "regular", {"10": usd(1000)}, cfg=cfg,
                             grade_probs=_dist({"10": "1.0"}),
                             outbound_shipping=usd(5))
        # costs 100 + 1 + 1 + 20 + 2 = 124; proceeds 872; EV = 748
        self.assertEqual(r.costs.total().quantized().amount, D("124.00"))
        self.assertEqual(r.ev.quantized().amount, D("748.00"))

    def test_hkd_acquisition_gbp_sale_full_fx_round_trip(self):
        """Layer 1 golden: HKD buy, GBP sale. The September situation.

        HKD->GBP at 0.1 : 8000 HKD = 800 GBP exactly.
        Costs 800 + 1 + 1 + 20 + 2 = 824.
        Keep 90%: comps 2000/900/400 -> net 1800/810/360.
        Probs .4/.5/.1 => 720 + 405 + 36 = 1161. EV = 1161 - 824 = 337.
        Round trip back to HKD must return exactly 8000.
        """
        cfg = filled_config()
        cfg.grading["meta"]["currency"] = "GBP"
        cfg.fees["marketplaces"]["ebay"]["currency"] = "GBP"
        cfg.fees["meta"]["home_currency"] = "GBP"

        rate = FxRate("HKD", "GBP", D("0.1"), as_of="2026-09-01", source="test")
        hkd = Money("8000", "HKD")
        gbp = hkd.to("GBP", rate)
        self.assertEqual(gbp.amount, D("800.0"))
        self.assertEqual(gbp.currency, "GBP")

        back = gbp.to("HKD", rate.inverted())
        self.assertEqual(back.amount, D("8000"))       # exact round trip

        def g(x):
            return Money(str(x), "GBP")

        r = raw_to_graded_ev("golden/hkd-gbp", gbp, "regular",
                             {"10": g(2000), "9": g(900), "8": g(400)}, cfg=cfg,
                             grade_probs=_dist({"10": "0.4", "9": "0.5", "8": "0.1"}))
        self.assertTrue(r.ok)
        self.assertEqual(r.costs.total().currency, "GBP")
        self.assertEqual(r.costs.total().quantized().amount, D("824.00"))
        self.assertEqual(r.ev.quantized().amount, D("337.00"))


class PropertyTests(unittest.TestCase):

    def _ev_at(self, acquisition=200, p10="0.5", turnaround=50):
        cfg = filled_config()
        cfg.grading["graders"]["PSA"]["tiers"]["regular"][
            "turnaround_business_days"] = turnaround
        rest = (D(1) - D(p10)) / 2
        return raw_to_graded_ev(
            "prop", usd(acquisition), "regular",
            {"10": usd(1000), "9": usd(200), "8": usd(100)}, cfg=cfg,
            grade_probs=_dist({"10": p10, "9": str(rest), "8": str(rest)}))

    def test_ev_monotonically_decreasing_in_acquisition_cost(self):
        evs = [self._ev_at(acquisition=a).ev.amount for a in (50, 100, 200, 400, 800)]
        for earlier, later in zip(evs, evs[1:]):
            self.assertGreater(earlier, later)

    def test_ev_monotonically_increasing_in_p_target(self):
        evs = [self._ev_at(p10=p).ev.amount
               for p in ("0.0", "0.1", "0.25", "0.5", "0.9")]
        for earlier, later in zip(evs, evs[1:]):
            self.assertLess(earlier, later)

    def test_annualised_roi_decreases_as_turnaround_increases(self):
        anns = [self._ev_at(turnaround=t).annualised_roi for t in (5, 20, 50, 100, 200)]
        for earlier, later in zip(anns, anns[1:]):
            self.assertGreater(earlier, later)

    def test_break_even_p_increases_with_acquisition_cost(self):
        ps = [self._ev_at(acquisition=a).break_even_p_target
              for a in (200, 400, 600)]
        for earlier, later in zip(ps, ps[1:]):
            self.assertLess(earlier, later)

    def test_no_calculator_returns_a_bare_float_for_money(self):
        """Every monetary field is Money, and every serialised amount is a string.

        A bare float for money is how a currency gets lost and how 0.1 + 0.2
        stops being 0.3. The Money constructor rejects floats outright.
        """
        r = self._ev_at()
        self.assertIsInstance(r.ev, Money)
        for name in ("acquisition", "tax", "inbound_shipping", "supplies",
                     "grading_fee", "return_shipping"):
            self.assertIsInstance(getattr(r.costs, name), Money)
        self.assertIsInstance(r.costs.total(), Money)

        def walk(node, path="root"):
            if isinstance(node, dict):
                if set(node) >= {"amount", "currency"}:
                    self.assertIsInstance(node["amount"], str,
                                          f"{path}.amount is not a string")
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")
            else:
                self.assertNotIsInstance(node, float, f"{path} is a bare float")

        walk(r.as_dict())

        with self.assertRaises(TypeError):
            Money(12.34, "USD")
        with self.assertRaises(TypeError):
            usd(10) + Money("10", "JPY")


class GradePriorTests(unittest.TestCase):

    def test_shrinkage_pulls_thin_card_toward_set(self):
        """Card 3/4 tens shrunk toward a set that gems 10% of the time.

        Card pop below the min-own threshold of 10, so the set distribution is
        used outright rather than believing a 75% gem rate from four cards.
        """
        d = shrunk_grade_distribution(
            card_pop={"10": 3, "9": 1}, set_pop={"10": 100, "9": 900},
            prior_strength=20, selection_haircut=1.0, min_card_pop_for_own_prior=10)
        self.assertEqual(d.p("10"), D("0.1"))
        self.assertIn("set-level", d.prior_used)

    def test_haircut_moves_mass_from_ten_to_nine(self):
        """Haircut 0.5 on P(10)=0.4 leaves 0.2, and 0.2 lands on 9."""
        d = shrunk_grade_distribution(
            card_pop={"10": 40, "9": 60}, set_pop={"10": 40, "9": 60},
            prior_strength=0, selection_haircut="0.5", min_card_pop_for_own_prior=1)
        self.assertEqual(d.p("10"), D("0.2"))
        self.assertEqual(d.p("9"), D("0.8"))
        self.assertEqual(d.total(), D("1.0"))
        self.assertEqual(d.haircut_applied, D("0.5"))

    def test_effective_sample_size_is_reported(self):
        d = shrunk_grade_distribution(
            card_pop={"10": 50, "9": 50}, set_pop={"10": 100, "9": 900},
            prior_strength=20, selection_haircut=1.0, min_card_pop_for_own_prior=10)
        self.assertEqual(d.effective_sample_size, D(120))
        self.assertIn("empirical-Bayes", d.prior_used)


def _dist(mapping):
    from engine.ev.results import GradeDistribution
    return GradeDistribution(probs={k: D(v) for k, v in mapping.items()},
                             prior_used="supplied directly by test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
