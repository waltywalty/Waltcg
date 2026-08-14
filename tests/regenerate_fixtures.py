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
from engine.ev.results import GradeDistribution  # noqa: E402
from tests.fixture_scenario import (ACQUISITION, ESTIMATED_ACQUISITION,  # noqa: E402
                                    ESTIMATED_CARD, ESTIMATED_PRICES, GENERATED_AT,
                                    GRADER, LADDER_POP, LADDER_PRICES, SET_POP,
                                    TIER, USER_GRADE_PROBS, USER_PROBS_NOTE, VENUE,
                                    WORKED_CARD, scenario_config)

# Which grade probability, if any, sits behind each figure. A break-even
# threshold is solved from prices and costs alone and rests on no probability at
# all -- that is why it is the half of the Grading Lab's gauge you can trust.
LAB_BASIS = {
    "break_even_p_target": "none",
    "modelled_p_target": "population",
    "pop_implied_p_target": "population",
    "roi": "population",
    "annualised_roi": "population",
}
# Three of the five worst calls rest on a probability I typed. Riftbound and One
# Piece have no population source, so a grading or float play on either had
# nothing else to use.
LEDGER_BASIS = {
    "a-0007": ("user_estimate", "api"),      # One Piece EN, no population
    "a-0012": ("none", "api"),               # trend play, no probability at all
    "a-0019": ("user_estimate", "manual"),   # One Piece JP: typed price AND prior
    "a-0003": ("user_estimate", "api"),      # Riftbound, no population
    "a-0022": ("config_rule", "api"),        # crossover, from dated rules
    "a-0031": ("population", "api"),         # Pokemon EN, pop report
}

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


# Field paths are how the API addresses a figure; labels are how a person
# recognises it. The reverse-dependency list needs both or it reads like a
# stack trace.
LABELS = {
    ("grading_lab", "break_even_p_target"): "Break-even P(10)",
    ("grading_lab", "modelled_p_target"): "Modelled P(10)",
    ("grading_lab", "pop_implied_p_target"): "Population-implied P(10)",
    ("grading_lab", ""): "Grading Lab, this submission",
    ("signals", "rows.headline"): "Signal headline number",
    ("signals", "rows"): "Signal row",
    ("signals", "rows.ladder.price_meta"): "Ladder rung price",
    ("card_detail", "buy_routes.landed_cost_meta"): "Buy route landed cost",
    ("arbitrage_board", "rows.net_margin_pct"): "Net margin",
    ("arbitrage_board", "rows"): "Arbitrage row",
    ("track_record", "worst_five"): "Worst five calls",
    ("track_record", "recent"): "Recent alerts",
}


def collect_usage():
    """Walk every fixture and index assumption id -> {(screen, field path)}.

    Array indices are dropped: 'rows[0].headline' and 'rows[3].headline' are one
    figure appearing twice, not two figures. The affordance answers "what moves
    if I change this", and the answer is a place in the app."""
    import collections
    usage = collections.defaultdict(set)

    def walk(node, screen, path):
        if isinstance(node, dict):
            for aid in node.get("assumption_ids") or []:
                usage[aid].add((screen, path))
            for key, value in node.items():
                if key == "assumption_ids":
                    continue
                walk(value, screen, f"{path}.{key}".strip("."))
        elif isinstance(node, list):
            for item in node:
                walk(item, screen, path)          # index dropped on purpose

    for name in ("home", "signals", "card_detail", "grading_lab",
                 "grading_lab.refusal", "arbitrage_board", "trend_radar",
                 "track_record", "manual_entry"):
        payload = load(name)
        walk(payload, payload["screen"], "")
    return usage


def model_a_result():
    cfg = scenario_config()
    comps = {g: Money(p, "USD") for g, p in LADDER_PRICES.items() if g != "raw"}
    result = raw_to_graded_ev(
        WORKED_CARD, Money(ACQUISITION, "USD"), TIER, comps, cfg=cfg,
        grader=GRADER, venue=VENUE, card_pop=LADDER_POP, set_pop=SET_POP)
    if not result:
        raise SystemExit(f"engine refused: {result.reason} -- {result.detail}")
    return result


def estimated_result():
    """Model A with the grade distribution supplied rather than derived. This
    is the only mode available for Riftbound and One Piece."""
    cfg = scenario_config()
    comps = {g: Money(p, "USD") for g, p in ESTIMATED_PRICES.items() if g != "raw"}
    probs = GradeDistribution(
        probs={g: Decimal(p) for g, p in USER_GRADE_PROBS.items()},
        prior_used="user estimate: no population source for riftbound",
        effective_sample_size=None, haircut_applied=None, notes=[USER_PROBS_NOTE])
    result = raw_to_graded_ev(
        ESTIMATED_CARD, Money(ESTIMATED_ACQUISITION, "USD"), TIER, comps, cfg=cfg,
        grader=GRADER, venue=VENUE, grade_probs=probs)
    if not result:
        raise SystemExit(f"engine refused: {result.reason} -- {result.detail}")
    return result


def set_basis(node, basis):
    """Stamp estimate_basis on a derived_value in place."""
    node["estimate_basis"] = basis
    return node


def main():
    r = model_a_result()
    est = estimated_result()

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
    for key, basis in LAB_BASIS.items():
        lab[key]["estimate_basis"] = basis
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
    riftbound = next((row for row in sig["rows"]
                      if row["card"]["card_uid"] == ESTIMATED_CARD
                      and row["play_type"] == "raw_to_10"), None)
    if riftbound is None:
        template = next(row for row in sig["rows"]
                        if row["card"]["card_uid"] == ESTIMATED_CARD)
        riftbound = json.loads(json.dumps(template))
        riftbound["play_type"] = "raw_to_10"
        riftbound["headline_label"] = "break-even P(10)"
        sig["rows"].append(riftbound)
    riftbound["headline"]["value"] = q(est.break_even_p_target)
    riftbound["headline"]["unit"] = "probability"
    riftbound["headline"]["source"] = "engine:model_a"
    riftbound["headline"]["sample_size"] = None
    riftbound["headline"]["confidence"] = "unvalidated"
    riftbound["headline"]["estimate_basis"] = "user_estimate"
    riftbound["headline"]["assumption_ids"] = []
    riftbound["estimate_basis"] = "user_estimate"
    riftbound["ladder"] = [
        {"grade": g,
         "price": usd(ESTIMATED_PRICES[g]) if g in ESTIMATED_PRICES else None,
         "price_meta": {
             "value": ESTIMATED_PRICES.get(g), "unit": "USD",
             "source": "tcgapi.dev", "as_of": GENERATED_AT,
             "confidence": "low", "sample_size": 4, "assumption_ids": [],
             "unavailable_reason": None,
             "staleness": {"as_of": GENERATED_AT, "age_seconds": 0,
                           "is_stale": False, "threshold_seconds": 86400,
                           "kind": "price"},
             "needs_primary_verification": False, "entry_method": "api",
             "estimate_basis": "none"},
         "population": {
             "value": None, "unit": "cards", "source": "none",
             "as_of": GENERATED_AT, "confidence": "unvalidated", "sample_size": 0,
             "assumption_ids": [], "unavailable_reason": "no_source_for_this_game",
             "staleness": {"as_of": GENERATED_AT, "age_seconds": 0,
                           "is_stale": False, "threshold_seconds": 604800,
                           "kind": "population"},
             "needs_primary_verification": False, "entry_method": "api",
             "estimate_basis": "none"}}
        for g in ("raw", "8", "9", "10")]
    for row in sig["rows"]:
        row.setdefault("estimate_basis",
                       "population" if row["play_type"] == "raw_to_10" else "none")
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

    # -------------------------------------------------------- track_record
    tr = load("track_record")
    for entry in tr["worst_five"] + tr["recent"]:
        basis, method = LEDGER_BASIS[entry["alert_id"]]
        entry["estimate_basis"] = basis
        entry["entry_method"] = method
    typed = sum(1 for e in tr["worst_five"]
                if e["estimate_basis"] == "user_estimate")
    tr["warnings"] = [
        f"{typed} of the five worst calls rest on a grade probability I typed."]
    save("track_record", tr)

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

    # ------------------------------------------------------------- settings
    # used_by is the INVERSE of the assumption_ids every derived_value already
    # carries. Deriving it rather than typing it is the whole point: a hand-kept
    # reverse index is a second list that drifts from the first, and the failure
    # is silent -- you change a haircut believing four figures move when six do.
    usage = collect_usage()
    settings = load("settings")
    for entry in settings["assumptions"]:
        used = sorted(usage.get(entry["id"], set()))
        entry["used_by"] = [{"screen": screen, "field": field,
                             "label": LABELS.get((screen, field), field)}
                            for screen, field in used]
        entry["used_by_count"] = len(entry["used_by"])
    orphans = [e["id"] for e in settings["assumptions"] if e["used_by_count"] == 0]
    settings["warnings"] = (
        [f"{len(orphans)} assumptions feed no figure on any screen: "
         + ", ".join(orphans)] if orphans else [])
    save("settings", settings)

    print(f"regenerated against the engine: needed P(10)="
          f"{q(r.break_even_p_target)}, modelled={q(r.modelled_p_target)}, "
          f"EV={r.ev.amount}, ROI={q(r.roi)}, horizon={r.horizon_days}d")


if __name__ == "__main__":
    main()
