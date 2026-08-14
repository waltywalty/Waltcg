"""Every derived figure in every fixture, recomputed and checked.

The fixtures shipped with numbers written by hand and never reconciled. The
Grading Lab priced a submission at 224.54 all-in and reported it losing 96.20 if
the card came back a 9, while Card Detail showed that same card's PSA 9 selling
for 320. Both screens were describing one card, and between them they said a
trade returning 43% on cost was a loss.

Wrong numbers in a fixture are not a cosmetic problem. A designer tuning
visual weight against them is learning the wrong *relationships* -- how big the
gap between "needed" and "likely" usually is, whether a negative EV is a near
miss or a rout, what a normal grade spread looks like. That lesson outlives the
numbers, because the numbers get replaced and the layout does not.

So: the engine is the authority. This module recomputes from each fixture's own
stated inputs and fails on any disagreement. Where a figure genuinely cannot be
recomputed from what the fixture contains, it is named in NOT_RECOMPUTABLE with
the reason -- an unchecked figure that nobody has written down is how this got
here in the first place.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ev import Money, raw_to_graded_ev  # noqa: E402
from engine.ev.fees import net_proceeds_from_schedule  # noqa: E402
from tests.fixture_scenario import (ACQUISITION, GRADER, LADDER_POP,  # noqa: E402
                                    LADDER_PRICES, SET_POP, TIER, VENUE,
                                    WORKED_CARD, scenario_config)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(REPO, "contracts", "fixtures")

# Figures no fixture can recompute from its own contents, and why. Each is a
# missing input, not a rounding question. Listing them is the point: a figure
# that is neither checked nor named here does not exist.
NOT_RECOMPUTABLE = {
    "home.portfolio_value":
        "no holdings list in the payload; the total is an input, not a result",
    "home.top_movers[].change_pct_24h":
        "no prior-day price per mover; the row carries today's ladder only",
    "signals.suppressed_count":
        "counts rows filtered before serialisation, which are by definition "
        "not in the payload",
}


def load(name):
    with open(os.path.join(FIX, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def dec(x):
    return Decimal(str(x))


class ModelAAgreesWithTheFixtures(unittest.TestCase):
    """The Grading Lab is model A run over Card Detail's ladder. Nothing in it
    is independent, so all of it is checkable."""

    @classmethod
    def setUpClass(cls):
        cls.lab = load("grading_lab")
        cls.cd = load("card_detail")
        cfg = scenario_config()
        comps = {g: Money(p, "USD") for g, p in LADDER_PRICES.items() if g != "raw"}
        cls.r = raw_to_graded_ev(
            WORKED_CARD, Money(ACQUISITION, "USD"), TIER, comps, cfg=cfg,
            grader=GRADER, venue=VENUE, card_pop=LADDER_POP, set_pop=SET_POP)

    def test_the_engine_computes_rather_than_refusing(self):
        self.assertTrue(self.r, getattr(self.r, "detail", ""))

    def test_the_lab_prices_the_card_the_ladder_shows(self):
        """Cross-fixture agreement. The comps model A is run against are the
        ladder prices Card Detail renders -- not a private copy of them."""
        ladder = {rung["grade"]: (rung["price"] or {}).get("amount")
                  for rung in self.cd["ladder"]}
        for grade, price in LADDER_PRICES.items():
            self.assertEqual(ladder.get(grade), price,
                             f"grade {grade}: the ladder and the lab disagree")
        self.assertEqual(self.lab["acquisition_cost"]["amount"],
                         ladder["raw"],
                         "acquisition should be the observed raw price")

    def test_cost_breakdown_matches_line_by_line(self):
        expected = {
            "acquisition": self.r.costs.acquisition, "tax": self.r.costs.tax,
            "inbound_shipping": self.r.costs.inbound_shipping,
            "supplies": self.r.costs.supplies,
            "grading_fee": self.r.costs.grading_fee,
            "return_shipping": self.r.costs.return_shipping,
        }
        for line, money in expected.items():
            self.assertEqual(dec(self.lab["cost_breakdown"][line]["amount"]),
                             money.amount, line)

    def test_the_cost_lines_sum_to_the_engine_total(self):
        total = sum(dec(v["amount"]) for v in self.lab["cost_breakdown"].values())
        self.assertEqual(total, self.r.costs.total().amount)

    def test_break_even_probability(self):
        self.assertEqual(dec(self.lab["break_even_p_target"]["value"]),
                         dec(self.r.break_even_p_target).quantize(dec("0.001")))
        self.assertEqual(self.lab["break_even_attainable"],
                         self.r.break_even_attainable)

    def test_modelled_probability(self):
        self.assertEqual(dec(self.lab["modelled_p_target"]["value"]),
                         dec(self.r.modelled_p_target).quantize(dec("0.001")))

    def test_ev_roi_and_annualised_roi(self):
        self.assertEqual(dec(self.lab["ev"]["amount"]),
                         self.r.ev.amount.quantize(dec("0.01")))
        self.assertEqual(dec(self.lab["roi"]["value"]),
                         dec(self.r.roi).quantize(dec("0.001")))
        self.assertEqual(dec(self.lab["annualised_roi"]["value"]),
                         dec(self.r.annualised_roi).quantize(dec("0.001")))
        self.assertEqual(self.lab["horizon_days"], self.r.horizon_days)

    def test_the_downside_branch(self):
        self.assertEqual(
            dec(self.lab["downside_case"]["amount"]),
            dec(self.r.downside_case["ev_if_realised"]["amount"]).quantize(dec("0.01")))

    def test_ev_and_roi_agree_on_sign(self):
        """Cheap, and it is the check the shipped fixture failed: EV -38.40 with
        a PSA 9 clearing cost by 43%."""
        ev = dec(self.lab["ev"]["amount"])
        roi = dec(self.lab["roi"]["value"])
        self.assertEqual(ev > 0, roi > 0)
        self.assertEqual(roi > 0, dec(self.lab["annualised_roi"]["value"]) > 0)

    def test_a_positive_ev_means_the_bar_is_already_cleared(self):
        """EV > 0 iff modelled probability exceeds the break-even probability.
        These are two views of one comparison and cannot disagree."""
        ev = dec(self.lab["ev"]["amount"])
        margin = (dec(self.lab["modelled_p_target"]["value"])
                  - dec(self.lab["break_even_p_target"]["value"]))
        self.assertEqual(ev > 0, margin > 0,
                         f"EV={ev} but modelled - needed = {margin}")


class TheHaircutOnlyEverMovesMassDown(unittest.TestCase):
    """CLAUDE.md non-negotiable 5. The shipped fixture had modelled 0.286
    against a pop-implied 0.249 -- the haircut applied backwards, which reads
    as 'the population understates your chances'."""

    def setUp(self):
        self.lab = load("grading_lab")

    def test_modelled_never_exceeds_pop_implied(self):
        self.assertLessEqual(dec(self.lab["modelled_p_target"]["value"]),
                             dec(self.lab["pop_implied_p_target"]["value"]))

    def test_pop_implied_is_the_raw_population_share(self):
        self.assertEqual(
            dec(self.lab["pop_implied_p_target"]["value"]),
            (dec(LADDER_POP["10"]) / dec(sum(LADDER_POP.values()))
             ).quantize(dec("0.001")))


class CardDetailIsInternallyConsistent(unittest.TestCase):

    def setUp(self):
        self.cd = load("card_detail")

    def test_population_total_is_the_sum_of_the_rungs(self):
        rungs = sum(r["population"]["value"] for r in self.cd["ladder"]
                    if r["population"]["value"] is not None)
        self.assertEqual(self.cd["population_total"]["value"], rungs)

    def test_population_by_grade_matches_the_rungs(self):
        by_rung = {r["grade"]: r["population"]["value"] for r in self.cd["ladder"]}
        for dv in self.cd["population_by_grade"]:
            grade = dv["unit"].rsplit(" ", 1)[-1]
            if grade in by_rung:
                self.assertEqual(dv["value"], by_rung[grade], f"grade {grade}")

    def test_the_series_ends_where_the_ladder_starts(self):
        """The chart and the rungs are on the same screen describing the same
        card. If the last point disagrees with the rung, one of them is wrong
        and the reader cannot tell which."""
        by_rung = {r["grade"]: (r["price"] or {}).get("amount")
                   for r in self.cd["ladder"]}
        latest = {}
        for point in self.cd["price_history"]:
            g = point["grade"]
            if g not in latest or point["as_of"] > latest[g]["as_of"]:
                latest[g] = point
        for grade, point in latest.items():
            if by_rung.get(grade):
                self.assertEqual(point["price"]["amount"], by_rung[grade],
                                 f"grade {grade}: last point vs ladder rung")

    def test_the_series_reports_its_own_length(self):
        self.assertEqual(self.cd["price_history_meta"]["sample_size"],
                         len(self.cd["price_history"]))

    def test_prices_rise_with_grade(self):
        order = ["8", "9", "10"]
        prices = [dec(r["price"]["amount"]) for g in order
                  for r in self.cd["ladder"] if r["grade"] == g and r["price"]]
        self.assertEqual(prices, sorted(prices),
                         "a PSA 9 selling above a PSA 10 needs a note, not silence")


class SignalsAgreeWithTheScreenBehindThem(unittest.TestCase):
    """A signal row's headline is the number the detail screen computes. If they
    drift, the feed is ranking on one figure and the card explains another."""

    def setUp(self):
        self.sig = load("signals")
        self.lab = load("grading_lab")

    def test_the_raw_to_10_headline_is_the_labs_break_even(self):
        rows = [r for r in self.sig["rows"]
                if r["card"]["card_uid"] == WORKED_CARD
                and r["play_type"] == "raw_to_10"]
        self.assertTrue(rows, "the worked card has no raw_to_10 row")
        for row in rows:
            self.assertEqual(dec(row["headline"]["value"]),
                             dec(self.lab["break_even_p_target"]["value"]))

    def test_the_rows_ladder_is_the_cards_ladder(self):
        cd = load("card_detail")
        for row in self.sig["rows"]:
            if row["card"]["card_uid"] != WORKED_CARD:
                continue
            self.assertEqual(
                [(r["grade"], (r["price"] or {}).get("amount")) for r in row["ladder"]],
                [(r["grade"], (r["price"] or {}).get("amount")) for r in cd["ladder"]])


class ArbitrageArithmetic(unittest.TestCase):

    def setUp(self):
        self.arb = load("arbitrage_board")
        self.schedule = scenario_config().get(
            f"fees.marketplaces.{VENUE}.fee_schedule")

    def test_net_is_gross_less_every_friction_line(self):
        for row in self.arb["rows"]:
            friction = sum(dec(v["amount"]) for v in row["friction"].values()
                           if isinstance(v, dict))
            self.assertEqual(dec(row["net_spread"]["amount"]),
                             dec(row["gross_spread"]["amount"]) - friction,
                             f"{row['card']['card_uid']} {row['path']}")

    def test_margin_is_net_over_the_buy_cost(self):
        for row in self.arb["rows"]:
            expected = (dec(row["net_spread"]["amount"])
                        / dec(row["buy_cost"]["amount"]) * 100)
            self.assertEqual(dec(row["net_margin_pct"]["value"]),
                             expected.quantize(dec("0.01")),
                             row["card"]["card_uid"])

    def test_the_ebay_fee_is_the_real_banded_schedule(self):
        """13.25% flat would be wrong above 1000, where the discount band cuts
        it to 6.625%. An invented flat percentage is exactly the error the
        expandable friction stack exists to make visible."""
        for row in self.arb["rows"]:
            if row["sell_venue"] != "ebay":
                continue
            sale = Money(str(dec(row["buy_cost"]["amount"])
                             + dec(row["gross_spread"]["amount"])), "USD")
            charged = sale.amount - net_proceeds_from_schedule(
                sale, self.schedule).amount
            stated = (dec(row["friction"]["marketplace_fee"]["amount"])
                      + dec(row["friction"]["payment_fee"]["amount"]))
            self.assertEqual(stated, charged.quantize(dec("0.01")),
                             row["card"]["card_uid"])

    def test_a_spread_never_nets_more_than_it_grosses(self):
        for row in self.arb["rows"]:
            self.assertLessEqual(dec(row["net_spread"]["amount"]),
                                 dec(row["gross_spread"]["amount"]))


class SmallIdentities(unittest.TestCase):
    """Figures that are one subtraction or one division from their inputs. Each
    was checkable all along and none had been checked."""

    def test_day_change_pct_is_the_change_over_the_previous_value(self):
        home = load("home")
        pv = dec(home["portfolio_value"]["amount"])
        dc = dec(home["day_change"]["amount"])
        self.assertEqual(dec(home["day_change_pct"]["value"]),
                         (dc / (pv - dc) * 100).quantize(dec("0.01")))

    def test_double_demeaned_z_is_own_minus_game(self):
        """The whole point of the trend screen: a card can be loudly discussed
        while being less discussed than its game."""
        for row in load("trend_radar")["rows"]:
            self.assertEqual(
                dec(row["double_demeaned_z"]["value"]),
                (dec(row["own_baseline_z"]["value"])
                 - dec(row["game_baseline_z"]["value"])).quantize(dec("0.01")),
                row["card"]["card_uid"])

    def test_the_worst_five_are_ordered_worst_first(self):
        returns = [dec(e["excess_return_90d"]["value"])
                   for e in load("track_record")["worst_five"]]
        self.assertEqual(returns, sorted(returns),
                         "the five worst calls are permanently visible, so their "
                         "order is load-bearing")

    def test_hit_rates_are_probabilities(self):
        tr = load("track_record")
        for key in ("hit_rate_7d", "hit_rate_30d", "hit_rate_90d"):
            value = dec(tr[key]["value"])
            self.assertGreaterEqual(value, 0, key)
            self.assertLessEqual(value, 1, key)

    def test_a_longer_horizon_never_covers_more_alerts(self):
        """The shipped fixture claimed all three hit rates rested on 31 alerts.
        They cannot: an alert fired ten days ago has no 90-day return yet. The
        90-day rate is the thinnest number on the screen and had been rendering
        as the most authoritative."""
        tr = load("track_record")
        sizes = [tr[f"hit_rate_{h}d"]["sample_size"] for h in (7, 30, 90)]
        self.assertEqual(sizes, sorted(sizes, reverse=True), sizes)
        for size in sizes:
            self.assertLessEqual(size, tr["scored_alert_count"])
        self.assertLess(sizes[2], sizes[0],
                        "no horizon has matured less than another, so the "
                        "fixture cannot show the case that matters")


class TheRefusalFixtureActuallyRefuses(unittest.TestCase):
    """The refusal payload must be what the engine does, not a mock-up of it."""

    def test_the_engine_refuses_the_card_the_fixture_refuses(self):
        cfg = scenario_config()
        result = raw_to_graded_ev(
            "optcg:OP05:OP05-119:manga_rare:EN", Money("62.00", "USD"), TIER,
            {}, cfg=cfg, grader=GRADER, venue=VENUE,
            card_pop=None, set_pop=None)
        self.assertFalse(result, "One Piece has no population source; model A "
                                 "must refuse rather than invent a distribution")

    def test_every_derived_figure_in_a_refusal_is_null(self):
        ref = load("grading_lab.refusal")
        for key in ("break_even_p_target", "modelled_p_target",
                    "pop_implied_p_target", "roi", "annualised_roi"):
            self.assertIsNone(ref[key]["value"], key)
            self.assertIsNotNone(ref[key]["unavailable_reason"], key)
        for key in ("ev", "downside_case", "horizon_days"):
            self.assertIsNone(ref[key], key)


class NothingIsUncheckedBySilence(unittest.TestCase):

    def test_unrecomputable_figures_are_named_with_a_reason(self):
        self.assertTrue(NOT_RECOMPUTABLE)
        for path, reason in NOT_RECOMPUTABLE.items():
            self.assertGreater(len(reason), 30,
                               f"{path} needs a reason, not a label")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ATypedProbabilityIsMarkedToo(unittest.TestCase):
    """entry_method marks a price I transcribed. estimate_basis marks a
    probability I invented. They are independent, and a Riftbound card usually
    needs both -- there is no population source, so the prior is mine, and often
    no price API either. One enum could not have said both."""

    def setUp(self):
        self.fixtures = {n[:-5]: load(n[:-5])
                         for n in sorted(os.listdir(FIX)) if n.endswith(".json")}

    def _derived(self):
        found = []

        def walk(node, path):
            if isinstance(node, dict):
                if {"value", "source", "as_of", "confidence",
                        "sample_size"} <= set(node):
                    found.append((path, node))
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for name, payload in self.fixtures.items():
            walk(payload, name)
        return found

    def test_every_derived_value_states_its_probability_basis(self):
        for path, dv in self._derived():
            self.assertIn("estimate_basis", dv, path)

    def test_a_price_or_population_rests_on_no_probability(self):
        """A grade probability cannot sit behind an observed price. Marking one
        'population' would imply the pop report priced the card."""
        for path, dv in self._derived():
            if (dv.get("unit") or "") in ("USD", "JPY", "cards", "z-score"):
                self.assertEqual(dv["estimate_basis"], "none", path)

    def test_the_two_markers_are_independent(self):
        """Both dimensions must actually vary, or one of them is decoration."""
        pairs = {(dv["entry_method"], dv["estimate_basis"])
                 for _, dv in self._derived()}
        self.assertGreater(len({e for e, _ in pairs}), 1, "entry_method never varies")
        self.assertGreater(len({b for _, b in pairs}), 1,
                           "estimate_basis never varies")

    def test_a_signal_row_can_rest_on_a_typed_probability(self):
        bases = {r["estimate_basis"] for r in self.fixtures["signals"]["rows"]}
        self.assertIn("user_estimate", bases,
                      "no signal row uses a supplied P(10), so the marker is "
                      "untested and the Grading Lab's second mode undesigned")

    def test_no_population_source_means_the_probability_must_be_mine(self):
        """Riftbound and One Piece have no population at any grade. A figure
        claiming a population-derived probability for one of them is claiming a
        source that does not exist."""
        rows = [("signals", r) for r in self.fixtures["signals"]["rows"]]
        rows += [("arbitrage_board", r)
                 for r in self.fixtures["arbitrage_board"]["rows"]]
        rows += [("track_record", e)
                 for e in self.fixtures["track_record"]["ledger"]]
        for name, row in rows:
            if row["card"]["game"] in ("riftbound", "optcg"):
                self.assertNotEqual(
                    row["estimate_basis"], "population",
                    f"{name}: {row['card']['card_uid']} has no population source")

    def test_the_worst_calls_say_what_they_rested_on(self):
        """The Track Record screen is where the marker earns its place: a bad
        call built on my own prior is a different lesson from a bad call built
        on a pop report.

        Asserted as a property, not a count. worst_five is now DERIVED from the
        ledger, so how many of them rest on a typed prior is an outcome, not a
        choice -- pinning it at three would be pinning a coincidence, and the
        next honest ledger change would 'fail' a test that was never testing
        anything."""
        tr = load("track_record")
        for entry in tr["worst_five"]:
            self.assertIn("estimate_basis", entry, entry["alert_id"])
            self.assertIn("entry_method", entry, entry["alert_id"])
        typed = [e for e in tr["ledger"]
                 if e["estimate_basis"] == "user_estimate"]
        self.assertTrue(typed, "no alert in the ledger rests on a typed prior")
        # The warning must state the true count, whatever it is.
        stated = int(tr["warnings"][0].split()[0])
        actual = sum(1 for e in tr["worst_five"]
                     if e["estimate_basis"] == "user_estimate")
        self.assertEqual(stated, actual, tr["warnings"][0])


class TheHandEstimatedCardComputes(unittest.TestCase):
    """Model A in its second mode: the grade distribution supplied, not
    derived. The only mode available for four of the eight combinations."""

    @classmethod
    def setUpClass(cls):
        from engine.ev.results import GradeDistribution
        from tests.fixture_scenario import (ESTIMATED_ACQUISITION, ESTIMATED_CARD,
                                            ESTIMATED_PRICES, USER_GRADE_PROBS)
        cls.card = ESTIMATED_CARD
        comps = {g: Money(p, "USD") for g, p in ESTIMATED_PRICES.items()
                 if g != "raw"}
        probs = GradeDistribution(
            probs={g: dec(p) for g, p in USER_GRADE_PROBS.items()},
            prior_used="user estimate", effective_sample_size=None,
            haircut_applied=None)
        cls.r = raw_to_graded_ev(
            ESTIMATED_CARD, Money(ESTIMATED_ACQUISITION, "USD"), TIER, comps,
            cfg=scenario_config(), grader=GRADER, venue=VENUE, grade_probs=probs)

    def test_the_engine_computes_from_a_supplied_distribution(self):
        self.assertTrue(self.r, getattr(self.r, "detail", ""))

    def test_the_signal_headline_matches_the_engine(self):
        rows = [r for r in load("signals")["rows"]
                if r["card"]["card_uid"] == self.card
                and r["play_type"] == "raw_to_10"]
        self.assertTrue(rows, "no hand-estimated raw_to_10 row")
        self.assertEqual(dec(rows[0]["headline"]["value"]),
                         dec(self.r.break_even_p_target).quantize(dec("0.001")))

    def test_a_supplied_prior_is_never_dressed_up_as_evidence(self):
        """sample_size must be null and confidence unvalidated. A typed prior
        with a sample size behind it is the single most misleading thing this
        screen could render."""
        for row in load("signals")["rows"]:
            if row["estimate_basis"] != "user_estimate":
                continue
            self.assertIsNone(row["headline"]["sample_size"],
                              row["card"]["card_uid"])
            self.assertEqual(row["headline"]["confidence"], "unvalidated")


class TheRegistryKnowsWhatDependsOnIt(unittest.TestCase):
    """Before changing a haircut I want to know what moves. The reverse index
    is derived from the forward references, never typed -- a hand-kept second
    list drifts from the first and fails silently."""

    def setUp(self):
        self.settings = load("settings")
        self.entries = {a["id"]: a for a in self.settings["assumptions"]}
        from tests.regenerate_fixtures import collect_usage
        self.observed = collect_usage()

    def test_count_matches_the_list(self):
        for aid, entry in self.entries.items():
            self.assertEqual(entry["used_by_count"], len(entry["used_by"]), aid)

    def test_every_citation_is_listed_back(self):
        """The assertion that matters. A figure citing an assumption the
        registry does not list is a dependency invisible at the moment of
        change."""
        for aid, places in self.observed.items():
            self.assertIn(aid, self.entries, f"{aid} is cited but not registered")
            declared = {(u["screen"], u["field"])
                        for u in self.entries[aid]["used_by"]}
            self.assertEqual(places, declared,
                             f"{aid}: cited in {sorted(places - declared)}, "
                             f"listed but uncited {sorted(declared - places)}")

    def test_no_entry_claims_a_dependency_that_does_not_exist(self):
        for aid, entry in self.entries.items():
            for use in entry["used_by"]:
                self.assertIn((use["screen"], use["field"]),
                              self.observed.get(aid, set()),
                              f"{aid} claims {use['screen']}.{use['field']}")

    def test_entries_feeding_nothing_are_surfaced_not_hidden(self):
        """An assumption with no dependants is either dead or a screen that has
        not been built. Both are worth seeing; neither should look like zero
        because the index is broken."""
        orphans = [a for a, e in self.entries.items() if e["used_by_count"] == 0]
        if orphans:
            self.assertTrue(self.settings["warnings"],
                            f"{orphans} feed no figure and nothing says so")

    def test_the_fragile_assumptions_have_dependants(self):
        """The four CLAUDE.md calls known-fragile are the ones most likely to
        be changed, so their reverse index is the one most likely to be read."""
        for aid in ("submission_selection_haircut",
                    "empirical_bayes_prior_strength", "pull_rate_estimates"):
            self.assertGreater(self.entries[aid]["used_by_count"], 0, aid)

    def test_labels_are_readable_rather_than_paths(self):
        for aid, entry in self.entries.items():
            for use in entry["used_by"]:
                self.assertTrue(use["label"], f"{aid} has an unlabelled dependant")


class ModelBComputesItsOwnFigures(unittest.TestCase):
    """The regrade play was half-present: `nine_to_10` in play_type,
    `crack_resubmit` in the arbitrage paths, three registry assumptions feeding
    nothing, and the design rendering model A's Charizard numbers under a
    regrade label. A play that looks live on another model's figures is worse
    than one that is absent, because nothing about it looks wrong."""

    @classmethod
    def setUpClass(cls):
        from engine.ev.model_b import regrade_9_to_10_ev
        from tests import fixture_scenario as fs
        cls.fs = fs
        comps = {g: Money(v, "USD") for g, v in fs.REGRADE_COMPS.items()}
        cls.r = regrade_9_to_10_ev(
            fs.REGRADE_CARD, Money(fs.REGRADE_SLAB_VALUE_9, "USD"), comps,
            cfg=scenario_config(), condition_read=fs.REGRADE_CONDITION_READ,
            tier=TIER, venue=VENUE)
        cls.unread = regrade_9_to_10_ev(
            fs.UNREAD_REGRADE_CARD, Money("300.00", "USD"), comps,
            cfg=scenario_config(), condition_read=None, tier=TIER, venue=VENUE)
        cls.crack = next(row for row in load("arbitrage_board")["rows"]
                         if row["path"] == "crack_resubmit")

    def test_model_b_runs_against_shipped_fee_config(self):
        """It could not, before this session. required_paths demanded the flat
        fee trio from a venue whose config supplies a banded schedule instead,
        so model B refused on eBay for a reason unrelated to the regrade prior
        it exists to apply."""
        self.assertTrue(self.r, getattr(self.r, "detail", ""))

    def test_the_regrade_prior_is_not_the_base_gem_rate(self):
        """Non-negotiable 6. The card is conditioned on PSA having declined a
        10; using the base rate double-counts what the grader already did."""
        lab = load("grading_lab")
        base = dec(lab["modelled_p_target"]["value"])
        regrade = dec(self.crack["regrade_detail"]["modelled_p_target"]["value"])
        self.assertNotEqual(regrade, base)
        self.assertLess(regrade, base,
                        "a card PSA already refused a 10 is not more likely to "
                        "get one than a random copy")

    def test_the_panel_carries_model_bs_numbers_not_model_as(self):
        detail = self.crack["regrade_detail"]
        self.assertEqual(dec(detail["break_even_p_target"]["value"]),
                         dec(self.r.break_even_p_target).quantize(dec("0.001")))
        self.assertEqual(dec(detail["modelled_p_target"]["value"]),
                         dec(self.r.modelled_p_target).quantize(dec("0.001")))
        lab = load("grading_lab")
        self.assertNotEqual(dec(self.crack["net_spread"]["amount"]),
                            dec(lab["ev"]["amount"]),
                            "the regrade EV is model A's EV again")

    def test_the_row_nets_to_the_engines_ev(self):
        self.assertEqual(dec(self.crack["net_spread"]["amount"]),
                         self.r.ev.amount.quantize(dec("0.01")))

    def test_all_three_branches_are_priced_and_sum_to_one(self):
        """The modal outcome of a resubmission is paying fees for the same slab
        back, and it has to be on screen."""
        branches = self.crack["regrade_detail"]["branches"]
        self.assertEqual({b["branch"] for b in branches},
                         {"upgrade_to_10", "regrade_9", "downgrade_below_9"})
        total = sum(dec(b["p"]) for b in branches)
        self.assertLess(abs(total - 1), dec("0.001"), total)

    def test_a_crack_resubmit_row_must_carry_the_detail(self):
        """Pinned in the schema too, so the half-present state cannot return."""
        for row in load("arbitrage_board")["rows"]:
            if row["path"] == "crack_resubmit":
                self.assertIsInstance(row["regrade_detail"], dict)
            else:
                self.assertIsNone(row["regrade_detail"])

    def test_no_condition_read_means_no_number(self):
        """Model B refuses rather than falling back to anything."""
        self.assertFalse(self.unread)
        self.assertEqual(set(self.unread.missing),
                         {"centering_pct", "corner_flag", "surface_flag",
                          "edge_flag"})

    def test_the_feed_shows_both_states(self):
        rows = [r for r in load("signals")["rows"]
                if r["play_type"] == "nine_to_10"]
        self.assertEqual(len(rows), 2, "the 9 -> 10 filter needs a priced row "
                                       "and a refusing one; most real rows refuse")
        priced = [r for r in rows if r["refusal"] is None]
        refused = [r for r in rows if r["refusal"] is not None]
        self.assertEqual(len(priced), 1)
        self.assertEqual(len(refused), 1)
        self.assertIsNone(refused[0]["headline"]["value"])
        self.assertEqual(refused[0]["headline"]["unavailable_reason"],
                         "engine_refused_insufficient_evidence")
        for item in refused[0]["refusal"]["missing"]:
            self.assertEqual(item["reason_code"], "condition_read_missing")
            self.assertTrue(item["fixable"])

    def test_the_play_type_is_filterable(self):
        self.assertIn("nine_to_10", load("signals")["filtered_by"])

    def test_the_regrade_assumptions_now_feed_something(self):
        """The orphan index is what found this. All three had zero dependants
        while the play rendered on screen with borrowed numbers."""
        entries = {a["id"]: a for a in load("settings")["assumptions"]}
        for aid in ("regrade_conditional_prior", "regrade_downgrade_probability",
                    "regrade_condition_adjustments"):
            self.assertGreater(entries[aid]["used_by_count"], 0, aid)


class TrackRecordIsDerivedFromItsLedger(unittest.TestCase):
    """The screen whose entire purpose is honesty cannot be the one screen
    whose numbers were typed."""

    def setUp(self):
        self.tr = load("track_record")

    def _scored(self, horizon):
        key = f"excess_return_{horizon}d"
        return [e for e in self.tr["ledger"] if e[key]["value"] is not None]

    def test_the_ledger_is_every_scored_alert(self):
        self.assertEqual(len(self.tr["ledger"]), self.tr["scored_alert_count"])

    def test_the_ledger_is_newest_first(self):
        fired = [e["fired_at"] for e in self.tr["ledger"]]
        self.assertEqual(fired, sorted(fired, reverse=True))

    def test_alert_ids_are_unique(self):
        ids = [e["alert_id"] for e in self.tr["ledger"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_hit_rate_recomputes_from_the_ledger(self):
        for horizon in (7, 30, 90):
            scored = self._scored(horizon)
            values = [dec(e[f"excess_return_{horizon}d"]["value"]) for e in scored]
            hits = sum(1 for v in values if v > 0)
            rate = self.tr[f"hit_rate_{horizon}d"]
            self.assertEqual(dec(rate["value"]),
                             (dec(hits) / dec(len(scored))).quantize(dec("0.001")),
                             f"{horizon}d")
            self.assertEqual(rate["sample_size"], len(scored), f"{horizon}d n")

    def test_the_median_excess_return_recomputes(self):
        from statistics import median
        values = sorted(dec(e["excess_return_30d"]["value"])
                        for e in self._scored(30))
        self.assertEqual(dec(self.tr["median_excess_return"]["value"]),
                         median(values).quantize(dec("0.0001")))

    def test_worst_five_are_the_five_worst_in_the_ledger(self):
        matured = [e for e in self.tr["ledger"]
                   if e["excess_return_90d"]["value"] is not None]
        expected = [e["alert_id"] for e in sorted(
            matured, key=lambda e: dec(e["excess_return_90d"]["value"]))[:5]]
        self.assertEqual([e["alert_id"] for e in self.tr["worst_five"]], expected)

    def test_an_unmatured_horizon_says_so_rather_than_reading_as_a_miss(self):
        """A null 90-day return is not a zero and not a loss. Counting it as
        either would quietly bias the rate the screen exists to report."""
        unmatured = [e for e in self.tr["ledger"]
                     if e["excess_return_90d"]["value"] is None]
        self.assertTrue(unmatured, "no alert is too young to have matured")
        for entry in unmatured:
            self.assertEqual(entry["excess_return_90d"]["unavailable_reason"],
                             "horizon_not_elapsed")


class EveryHitRateCarriesItsSampleSize(unittest.TestCase):
    """A 38% hit rate on n=5 and on n=200 are different claims. Every other
    figure in this app carries n; this one had not."""

    def setUp(self):
        self.tr = load("track_record")

    def test_per_play_rates_carry_n(self):
        self.assertTrue(self.tr["by_play_type"])
        for record in self.tr["by_play_type"]:
            for key in ("hit_rate_30d", "median_excess_return_30d"):
                size = record[key]["sample_size"]
                self.assertIsNotNone(size, f"{record['play_type']}.{key}")
                self.assertGreater(size, 0)

    def test_per_play_rates_recompute_from_the_ledger(self):
        by_play = {}
        for entry in self.tr["ledger"]:
            if entry["excess_return_30d"]["value"] is None:
                continue
            by_play.setdefault(entry["rule"], []).append(
                dec(entry["excess_return_30d"]["value"]))
        for record in self.tr["by_play_type"]:
            values = by_play[record["play_type"]]
            hits = sum(1 for v in values if v > 0)
            self.assertEqual(record["hit_rate_30d"]["sample_size"], len(values),
                             record["play_type"])
            self.assertEqual(dec(record["hit_rate_30d"]["value"]),
                             (dec(hits) / dec(len(values))).quantize(dec("0.001")),
                             record["play_type"])

    def test_the_per_play_counts_account_for_every_matured_alert(self):
        total = sum(r["hit_rate_30d"]["sample_size"] for r in self.tr["by_play_type"])
        matured = sum(1 for e in self.tr["ledger"]
                      if e["excess_return_30d"]["value"] is not None)
        self.assertEqual(total, matured, "a play type is missing from the split")

    def test_a_thin_sample_is_flagged_rather_than_rendered_bare(self):
        thin = [r["play_type"] for r in self.tr["by_play_type"]
                if r["hit_rate_30d"]["sample_size"] < 10]
        if thin:
            self.assertTrue(any("Thin per-play samples" in w
                                for w in self.tr["warnings"]), self.tr["warnings"])

    def test_low_confidence_on_a_thin_sample(self):
        for record in self.tr["by_play_type"]:
            if record["hit_rate_30d"]["sample_size"] < 10:
                self.assertEqual(record["hit_rate_30d"]["confidence"], "low",
                                 record["play_type"])


class FetchedAtIsNotAsOf(unittest.TestCase):
    """"as of 11:04" is a claim about the market. "fetched at 11:04" is a claim
    about us. CLAUDE.md Conventions/Time has always required both; the contract
    shipped only one, so an error state could not say which of the two it
    meant."""

    def setUp(self):
        self.fixtures = {n[:-5]: load(n[:-5])
                         for n in sorted(os.listdir(FIX)) if n.endswith(".json")}

    def _derived(self):
        found = []

        def walk(node, path):
            if isinstance(node, dict):
                if {"value", "source", "as_of", "confidence",
                        "sample_size"} <= set(node):
                    found.append((path, node))
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for name, payload in self.fixtures.items():
            walk(payload, name)
        return found

    def test_every_value_says_when_it_was_fetched(self):
        for path, dv in self._derived():
            self.assertIn("observed_at", dv, path)

    def test_observed_at_is_never_earlier_than_as_of(self):
        """We cannot have seen a value before it referred to anything."""
        for path, dv in self._derived():
            self.assertGreaterEqual(dv["observed_at"], dv["as_of"], path)

    def test_the_staleness_badge_carries_the_same_pair(self):
        for path, dv in self._derived():
            self.assertEqual(dv["staleness"]["observed_at"], dv["observed_at"], path)
            self.assertEqual(dv["staleness"]["as_of"], dv["as_of"], path)

    def test_at_least_one_value_shows_the_two_diverging(self):
        """A price refers to the last trade and is fetched later. If no fixture
        shows the gap, the design has no reason to render two timestamps and
        will render one."""
        diverging = [p for p, dv in self._derived()
                     if dv["observed_at"] != dv["as_of"]]
        self.assertTrue(diverging,
                        "as_of and observed_at are identical everywhere, so the "
                        "distinction is untested")
        # And specifically on a price, because that is the badge the design
        # renders hundreds of times. A ladder whose two timestamps always match
        # gives it no reason to draw both.
        ladder = self.fixtures["card_detail"]["ladder"]
        self.assertTrue(
            any(r["price_meta"]["observed_at"] != r["price_meta"]["as_of"]
                for r in ladder),
            "no ladder rung distinguishes when the price refers to from when "
            "we fetched it")
