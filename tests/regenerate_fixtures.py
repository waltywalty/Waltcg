"""Recompute every derived figure in the fixtures and write them back.

Run after changing `tests/fixture_scenario.py` or anything in `engine/ev/`:

    python -m tests.regenerate_fixtures

`tests/test_fixture_arithmetic.py` recomputes the same figures independently and
fails if what is committed disagrees, so this script is a convenience, not the
authority. The authority is the engine.

Why this exists at all: the fixtures shipped with figures that had been written
by hand and never reconciled. `card_detail` showed a PSA 9 at 320 against a
224.54 all-in cost, while `grading_lab` reported that submission losing 96.20 if
it came back a 9 -- a card whose 9 sells for 43% more than the whole cost of
acquiring and grading it. A designer tuning visual weight against that is
learning that a strongly profitable trade looks like a loss.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ev import Money, raw_to_graded_ev  # noqa: E402
from engine.ev.fees import net_proceeds_from_schedule  # noqa: E402
from tests.fixture_scenario import (ACQUISITION, GENERATED_AT, GRADER,  # noqa: E402
                                    LADDER_POP, LADDER_PRICES, SET_POP, TIER,
                                    VENUE, WORKED_CARD, scenario_config)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "contracts", "fixtures")


def load(name):
    with open(os.path.join(FIX, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def save(name, payload):
    with open(os.path.join(FIX, f"{name}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def q(value, places="0.001"):
    """Round a Decimal for display in a fixture. Money keeps its own 2dp."""
    return str(Decimal(str(value)).quantize(Decimal(places)))


def usd(amount):
    """Money is always 2dp. An unquantised Decimal here would ship a
    28-significant-digit 'price' straight into the contract."""
    return {"amount": str(Decimal(str(amount)).quantize(Decimal("0.01"))),
            "currency": "USD", "fx_rate_used": None, "fx_as_of": None}


def model_a_result():
    cfg = scenario_config()
    comps = {g: Money(p, "USD") for g, p in LADDER_PRICES.items() if g != "raw"}
    result = raw_to_graded_ev(
        WORKED_CARD, Money(ACQUISITION, "USD"), TIER, comps, cfg=cfg,
        grader=GRADER, venue=VENUE, card_pop=LADDER_POP, set_pop=SET_POP)
    if not result:
        raise SystemExit(f"engine refused: {result.reason} -- {result.detail}")
    return result


def main():
    r = model_a_result()

    # ---------------------------------------------------------- card_detail
    cd = load("card_detail")
    for rung in cd["ladder"]:
        price = LADDER_PRICES.get(rung["grade"])
        if price is not None:
            rung["price"]["amount"] = price
            rung["price_meta"]["value"] = price
        pop = LADDER_POP.get(rung["grade"])
        if pop is not None:
            rung["population"]["value"] = pop
    # population_total is the sum of the rungs, not an independent observation.
    cd["population_total"]["value"] = sum(LADDER_POP.values())
    for dv in cd["population_by_grade"]:
        grade = dv["unit"].rsplit(" ", 1)[-1]
        if grade in LADDER_POP:
            dv["value"] = LADDER_POP[grade]
    # The series has to end where the ladder starts, or the chart and the rungs
    # disagree about the same card on the same screen.
    last = {"raw": LADDER_PRICES["raw"], "9": LADDER_PRICES["9"],
            "10": LADDER_PRICES["10"]}
    for point in cd["price_history"]:
        if point["as_of"] == max(p["as_of"] for p in cd["price_history"]
                                 if p["grade"] == point["grade"]):
            if point["grade"] in last:
                point["price"]["amount"] = last[point["grade"]]
    cd["price_history_meta"]["sample_size"] = len(cd["price_history"])
    save("card_detail", cd)

    # ----------------------------------------------------------- grading_lab
    lab = load("grading_lab")
    lab["acquisition_cost"] = usd(ACQUISITION)
    lab["cost_breakdown"] = {
        "acquisition": usd(r.costs.acquisition.amount),
        "tax": usd(r.costs.tax.amount),
        "inbound_shipping": usd(r.costs.inbound_shipping.amount),
        "supplies": usd(r.costs.supplies.amount),
        "grading_fee": usd(r.costs.grading_fee.amount),
        "return_shipping": usd(r.costs.return_shipping.amount),
    }
    lab["break_even_p_target"]["value"] = q(r.break_even_p_target)
    lab["break_even_attainable"] = r.break_even_attainable
    lab["break_even_note"] = r.break_even_note
    lab["modelled_p_target"]["value"] = q(r.modelled_p_target)
    # Pop-implied is the raw population share, before the haircut. It has to sit
    # ABOVE the modelled figure -- the haircut only ever moves mass down.
    pop_implied = Decimal(LADDER_POP["10"]) / Decimal(sum(LADDER_POP.values()))
    lab["pop_implied_p_target"]["value"] = q(pop_implied)
    lab["pop_implied_p_target"]["sample_size"] = sum(LADDER_POP.values())
    lab["modelled_p_target"]["sample_size"] = sum(LADDER_POP.values())
    lab["ev"] = usd(r.ev.amount)
    lab["roi"]["value"] = q(r.roi)
    lab["annualised_roi"]["value"] = q(r.annualised_roi)
    lab["horizon_days"] = r.horizon_days
    lab["downside_case"] = usd(
        Decimal(r.downside_case["ev_if_realised"]["amount"]))
    lab["warnings"] = [
        f"PSA {TIER} fee is provisional and needs primary verification",
        f"Needs P(10) = {q(r.break_even_p_target)}; modelled "
        f"{q(r.modelled_p_target)}. Do not submit.",
    ]
    save("grading_lab", lab)

    # -------------------------------------------------------------- signals
    # The raw_to_10 row for the worked card leads with the same break-even
    # probability the Grading Lab computes. Two screens, one number.
    sig = load("signals")
    for row in sig["rows"]:
        if (row["card"]["card_uid"] == WORKED_CARD
                and row["play_type"] == "raw_to_10"):
            row["headline"]["value"] = q(r.break_even_p_target)
            row["headline"]["sample_size"] = sum(LADDER_POP.values())
            row["ladder"] = json.loads(json.dumps(
                [rung for rung in cd["ladder"]]))
    save("signals", sig)

    # ------------------------------------------------------- arbitrage_board
    cfg = scenario_config()
    schedule = cfg.get(f"fees.marketplaces.{VENUE}.fee_schedule")
    arb = load("arbitrage_board")
    for row in arb["rows"]:
        buy = Decimal(row["buy_cost"]["amount"])
        gross = Decimal(row["gross_spread"]["amount"])
        sale = Money(str(buy + gross), "USD")
        if row["sell_venue"] == "ebay":
            # Fee on the real banded schedule, not a flat percentage.
            net_of_fees = net_proceeds_from_schedule(sale, schedule)
            fee_total = sale.amount - net_of_fees.amount
            payment = Decimal("0.40") if sale.amount > 10 else Decimal("0.30")
            row["friction"]["marketplace_fee"] = usd(
                (fee_total - payment).quantize(Decimal("0.01")))
            row["friction"]["payment_fee"] = usd(payment)
        friction = sum(Decimal(v["amount"]) for k, v in row["friction"].items()
                       if isinstance(v, dict))
        net = (gross - friction).quantize(Decimal("0.01"))
        row["net_spread"] = usd(net)
        row["net_margin_pct"]["value"] = q(net / buy * 100, "0.01")
    save("arbitrage_board", arb)

    # ----------------------------------------------------------------- home
    home = load("home")
    pv = Decimal(home["portfolio_value"]["amount"])
    dc = Decimal(home["day_change"]["amount"])
    home["day_change_pct"]["value"] = q(dc / (pv - dc) * 100, "0.01")
    save("home", home)

    # --------------------------------------------------------- trend_radar
    trend = load("trend_radar")
    for row in trend["rows"]:
        own = Decimal(row["own_baseline_z"]["value"])
        game = Decimal(row["game_baseline_z"]["value"])
        row["double_demeaned_z"]["value"] = q(own - game, "0.01")
    save("trend_radar", trend)

    print(f"regenerated against the engine: needed P(10)="
          f"{q(r.break_even_p_target)}, modelled={q(r.modelled_p_target)}, "
          f"EV={r.ev.amount}, ROI={q(r.roi)}, horizon={r.horizon_days}d")


if __name__ == "__main__":
    main()
