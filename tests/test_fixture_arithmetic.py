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
    "track_record.hit_rate_*":
        "31 scored alerts, 6 visible. The screen shows the worst five and the "
        "most recent by design, so the rate cannot be re-derived from them",
    "track_record.median_excess_return":
        "same: the median is over 31 alerts, of which 6 are in the payload",
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

    def test_aggregates_agree_on_how_many_alerts_they_cover(self):
        tr = load("track_record")
        sizes = {tr[k]["sample_size"] for k in
                 ("hit_rate_7d", "hit_rate_30d", "hit_rate_90d",
                  "median_excess_return")}
        self.assertEqual(sizes, {tr["scored_alert_count"]},
                         "four aggregates over the same ledger, one count")


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
        rows += [("track_record", e) for e in
                 self.fixtures["track_record"]["worst_five"]
                 + self.fixtures["track_record"]["recent"]]
        for name, row in rows:
            if row["card"]["game"] in ("riftbound", "optcg"):
                self.assertNotEqual(
                    row["estimate_basis"], "population",
                    f"{name}: {row['card']['card_uid']} has no population source")

    def test_three_of_the_five_worst_calls_rest_on_a_typed_probability(self):
        """The Track Record screen is where the marker earns its place: a bad
        call built on my own prior is a different lesson from a bad call built
        on a pop report."""
        worst = load("track_record")["worst_five"]
        for entry in worst:
            self.assertIn("estimate_basis", entry, entry["alert_id"])
            self.assertIn("entry_method", entry, entry["alert_id"])
        typed = [e for e in worst if e["estimate_basis"] == "user_estimate"]
        self.assertEqual(len(typed), 3, [e["alert_id"] for e in worst])


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
