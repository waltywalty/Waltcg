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
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ev import Money, raw_to_graded_ev  # noqa: E402
from engine.ev.fees import net_proceeds_from_schedule  # noqa: E402
from engine.ev.results import GradeDistribution  # noqa: E402
from engine.ev.model_b import regrade_9_to_10_ev  # noqa: E402
from tests.fixture_scenario import (ACQUISITION, ESTIMATED_ACQUISITION,  # noqa: E402
                                    ESTIMATED_CARD, ESTIMATED_PRICES, GENERATED_AT,
                                    GRADER, LADDER_POP, LADDER_PRICES, SET_POP,
                                    TIER, USER_GRADE_PROBS, USER_PROBS_NOTE, VENUE,
                                    WORKED_CARD, scenario_config)
from tests import fixture_scenario as fs  # noqa: E402

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
    ("track_record", "ledger"): "Alert ledger",
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


def stamp_observed_at(node):
    """observed_at defaults to as_of -- we saw the value when it was current.
    Where the two genuinely differ (a price refers to the last trade, we
    fetched it later) the payload sets it explicitly and this leaves it."""
    if isinstance(node, dict):
        if {"value", "source", "as_of", "confidence", "sample_size"} <= set(node):
            node.setdefault("observed_at", node["as_of"])
            staleness = node.get("staleness")
            if isinstance(staleness, dict):
                staleness.setdefault("observed_at", node["observed_at"])
        for value in node.values():
            stamp_observed_at(value)
    elif isinstance(node, list):
        for value in node:
            stamp_observed_at(value)


def build_ledger():
    """Every alert ever fired, newest first. Returns are deterministic and
    untuned -- see fixture_scenario.ledger_excess."""
    entries = []
    for i in range(fs.LEDGER_SIZE):
        uid, game, set_code, number, variant, lang, name, rarity = \
            fs.LEDGER_CARDS[i % len(fs.LEDGER_CARDS)]
        play = fs.LEDGER_PLAYS[i % len(fs.LEDGER_PLAYS)]
        fired = fs.ledger_fired_on(i)
        # No population source for Riftbound or One Piece, so any play needing
        # a grade probability on one of those used a prior I typed.
        if play == "trending_early":
            basis = "none"
        elif play == "crossover":
            basis = "config_rule"
        elif play == "nine_to_10":
            basis = "config_rule"
        elif game in ("riftbound", "optcg"):
            basis = "user_estimate"
        else:
            basis = "population"
        method = "manual" if (game == "optcg" and lang != "EN") else "api"
        entry = {
            "alert_id": f"a-{i + 1:04d}",
            "fired_at": f"{fired.isoformat()}T08:00:00Z",
            "card": {"card_uid": uid, "game": game, "set_code": set_code,
                     "number": number, "variant": variant, "language": lang,
                     "name": name, "rarity": rarity, "artist": None,
                     "image_url": None},
            "rule": play,
            "thesis": f"{play.replace('_', ' ')} on {name}",
            "price_at_alert": usd(Decimal(60 + (i * 37) % 400)),
            "assumption_ids": (["submission_selection_haircut"]
                               if basis == "population" else []),
            "estimate_basis": basis, "entry_method": method,
        }
        for horizon in fs.HORIZONS:
            value = fs.ledger_excess(i, horizon)
            at = f"{fired.isoformat()}T08:00:00Z"
            entry[f"excess_return_{horizon}d"] = {
                "value": None if value is None else q(Decimal(str(value)), "0.0001"),
                "unit": "ratio", "source": "engine:ledger", "as_of": at,
                "observed_at": GENERATED_AT, "confidence": "medium",
                "sample_size": 1, "assumption_ids": [],
                "unavailable_reason": None if value is not None else "horizon_not_elapsed",
                "staleness": {"as_of": at, "observed_at": GENERATED_AT,
                              "age_seconds": 0, "is_stale": False,
                              "threshold_seconds": 86400, "kind": "derived"},
                "needs_primary_verification": False, "entry_method": method,
                "estimate_basis": basis,
            }
        entries.append(entry)
    return sorted(entries, key=lambda e: e["fired_at"], reverse=True)


def model_a_result():
    cfg = scenario_config()
    comps = {g: Money(p, "USD") for g, p in LADDER_PRICES.items() if g != "raw"}
    result = raw_to_graded_ev(
        WORKED_CARD, Money(ACQUISITION, "USD"), TIER, comps, cfg=cfg,
        grader=GRADER, venue=VENUE, route=fs.ROUTE, route_fx=fs.fx_gbp_usd(),
        buy_route="uk_domestic_secondhand",
        card_pop=LADDER_POP, set_pop=SET_POP)
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
        grader=GRADER, venue=VENUE, route=fs.ROUTE, route_fx=fs.fx_gbp_usd(),
        buy_route="uk_domestic_secondhand", grade_probs=probs)
    if not result:
        raise SystemExit(f"engine refused: {result.reason} -- {result.detail}")
    return result


def regrade_result():
    """Model B with a condition read. Its numbers are NOT model A's: a card
    already slabbed at 9 is not a random card, so the base gem rate is
    forbidden here and the conditional prior replaces it."""
    comps = {g: Money(v, "USD") for g, v in fs.REGRADE_COMPS.items()}
    result = regrade_9_to_10_ev(
        fs.REGRADE_CARD, Money(fs.REGRADE_SLAB_VALUE_9, "USD"), comps,
        cfg=scenario_config(), condition_read=fs.REGRADE_CONDITION_READ,
        tier=TIER, venue=VENUE, route=fs.ROUTE)
    if not result:
        raise SystemExit(f"model B refused: {result.reason} -- {result.detail}")
    return result


def regrade_refusal():
    """The same model on a card I have not examined. Non-negotiable 6: no
    condition read, no number. Most rows in a 9 -> 10 feed are this."""
    comps = {g: Money(v, "USD") for g, v in fs.REGRADE_COMPS.items()}
    result = regrade_9_to_10_ev(
        fs.UNREAD_REGRADE_CARD, Money("300.00", "USD"), comps,
        cfg=scenario_config(), condition_read=None, tier=TIER, venue=VENUE,
        route=fs.ROUTE)
    if result:
        raise SystemExit("model B priced a regrade with no condition read")
    return result


def derived(value, unit, source, basis="none", sample=None, as_of=None,
       confidence="medium", reason=None, assumptions=None, kind="derived"):
    at = as_of or GENERATED_AT
    return {"value": value, "unit": unit, "source": source, "as_of": at,
            "observed_at": at, "confidence": confidence, "sample_size": sample,
            "assumption_ids": assumptions or [], "unavailable_reason": reason,
            "staleness": {"as_of": at, "observed_at": at, "age_seconds": 0,
                          "is_stale": False, "threshold_seconds": 86400,
                          "kind": kind},
            "needs_primary_verification": bool(
                set(assumptions or []) & {"grading_fee_schedule",
                                          "marketplace_fee_schedule"}),
            "entry_method": "api", "estimate_basis": basis}


def set_basis(node, basis):
    """Stamp estimate_basis on a derived_value in place."""
    node["estimate_basis"] = basis
    return node


def main():
    r = model_a_result()
    est = estimated_result()
    reg = regrade_result()
    unread = regrade_refusal()

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
    ic = r.import_charges
    lab["import_charges"] = {
        "applies": ic["applies"],
        "route": ic["route"],
        "note": ic["note"],
        "relief_scenario": ic["relief_scenario"],
        "expected": (usd(Decimal(ic["expected"]["amount"]))
                     if ic["expected"] else None),
        "effective_rate_on_goods": (q(Decimal(ic["effective_rate_on_goods"]), "0.0001")
                                    if ic["effective_rate_on_goods"] else None),
        "by_grade": ({g: usd(Decimal(v["amount"]))
                      for g, v in ic["by_grade"].items()} or None),
    }
    for key, basis in LAB_BASIS.items():
        lab[key]["estimate_basis"] = basis
    save("grading_lab", lab)

    # ------------------------------------------------- grading_lab.refusal
    # The refusal payload is hand-authored, but it shares the Lab's envelope
    # and must not drift from it. A refusal still has to say whether the route
    # would have been charged: "we could not price this" and "and it crosses a
    # border" are separate facts, and the second one survives the first.
    ref = load("grading_lab.refusal")
    ref["import_charges"] = json.loads(json.dumps(lab["import_charges"]))
    ref["import_charges"]["expected"] = None
    ref["import_charges"]["by_grade"] = None
    save("grading_lab.refusal", ref)

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
        row.setdefault("refusal", None)

    # The 9 -> 10 play. It was in play_type and in no payload, so the design
    # rendered it with model A's figures under a regrade label. Two rows now:
    # one I have examined, one I have not.
    ladder = json.loads(json.dumps(cd["ladder"]))
    priced = {
        "card": json.loads(json.dumps(cd["card"])),
        "play_type": "nine_to_10",
        "headline": derived(q(reg.break_even_p_target), "probability",
                       "engine:model_b", basis="config_rule",
                       confidence="unvalidated",
                       assumptions=["regrade_conditional_prior",
                                    "regrade_downgrade_probability",
                                    "regrade_condition_adjustments",
                                    "grading_fee_schedule"]),
        "headline_label": "break-even P(10) on regrade",
        "ladder": ladder,
        "assumption_ids": ["regrade_conditional_prior",
                           "regrade_downgrade_probability"],
        "entry_method": "api", "estimate_basis": "config_rule", "refusal": None,
    }
    unread_card = next(row["card"] for row in sig["rows"]
                       if row["card"]["card_uid"] == fs.UNREAD_REGRADE_CARD)
    refused = {
        "card": json.loads(json.dumps(unread_card)),
        "play_type": "nine_to_10",
        "headline": derived(None, "probability", "engine:model_b",
                       basis="config_rule", confidence="unvalidated",
                       reason="engine_refused_insufficient_evidence"),
        "headline_label": "break-even P(10) on regrade",
        "ladder": ladder,
        "assumption_ids": ["regrade_conditional_prior"],
        "entry_method": "api", "estimate_basis": "config_rule",
        "refusal": {
            "reason": unread.reason,
            "detail": unread.detail,
            "missing": [
                {"id": f"condition_read.{field}",
                 "title": {"centering_pct": "Measure centering",
                           "corner_flag": "Rate the corners",
                           "surface_flag": "Rate the surface",
                           "edge_flag": "Rate the edges"}[field],
                 "reason_code": "condition_read_missing", "fixable": True,
                 "deep_link": {"screen": "grading_lab", "anchor": "condition_read",
                               "card_uid": fs.UNREAD_REGRADE_CARD,
                               "assumption_id": None}}
                for field in unread.missing],
        },
    }
    sig["rows"] = [row for row in sig["rows"] if row["play_type"] != "nine_to_10"]
    sig["rows"] += [priced, refused]
    sig["filtered_by"] = sorted({row["play_type"] for row in sig["rows"]})
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
        row.setdefault("regrade_detail", None)
        row["friction"].setdefault("supplies", None)
        row["friction"].setdefault("import_charges", None)

    # CRACK & RESUBMIT. Previously this panel showed model A's Charizard
    # figures under a regrade label. Model B's are different because the card
    # is conditioned on PSA having already declined a 10: modelled P(10) falls
    # from 0.199 to 0.173, and the intact slab becomes the cost side.
    slab = Decimal(fs.REGRADE_SLAB_VALUE_9)
    expected_gross = sum(
        Decimal(reg.grade_distribution.probs[g]) * Decimal(fs.REGRADE_COMPS[g])
        for g in fs.REGRADE_COMPS)
    expected_net = sum(
        (Decimal(b["p"]) * (Decimal(b["ev_if_realised"]["amount"])
                            + reg.costs.total().amount))
        for b in reg.branches)
    # The branch proceeds are already net of the import charge, so subtracting
    # them from gross would fold customs into "marketplace fee". Two different
    # deductions to two different parties; the stack itemises both.
    reg_import = reg.import_charges
    expected_import = (Decimal(reg_import["expected"]["amount"])
                       if reg_import["expected"] else Decimal(0))
    selling_fees = expected_gross - expected_net - expected_import
    crack = {
        "card": json.loads(json.dumps(cd["card"])),
        "path": "crack_resubmit",
        "buy_venue": "hold", "sell_venue": "ebay",
        "buy_cost": usd(slab),
        "gross_spread": usd(expected_gross - slab),
        "net_spread": None,   # filled below from the ROUNDED friction lines
        "friction": {
            "marketplace_fee": usd(selling_fees - Decimal("0.40")),
            "payment_fee": usd("0.40"),
            "shipping": usd(reg.costs.inbound_shipping.amount
                            + reg.costs.return_shipping.amount),
            "grading_fee": usd(reg.costs.grading_fee.amount),
            "supplies": usd(reg.costs.supplies.amount),
            "fx_spread": None, "tax": None,
            "import_charges": (usd(expected_import) if reg_import["applies"]
                               else None),
            "needs_primary_verification": True,
        },
        "net_margin_pct": derived(q(reg.ev.amount / slab * 100, "0.01"), "percent",
                             "engine:model_b", basis="config_rule",
                             confidence="unvalidated",
                             assumptions=["regrade_conditional_prior",
                                          "grading_fee_schedule"]),
        "assumption_ids": ["regrade_conditional_prior",
                           "regrade_downgrade_probability",
                           "regrade_condition_adjustments"],
        "estimate_basis": "config_rule",
        "regrade_detail": {
            "break_even_p_target": derived(
                q(reg.break_even_p_target), "probability", "engine:model_b",
                basis="none", confidence="medium"),
            "modelled_p_target": derived(
                q(reg.modelled_p_target), "probability", "engine:model_b",
                basis="config_rule", confidence="unvalidated",
                assumptions=["regrade_conditional_prior",
                             "regrade_condition_adjustments"]),
            "condition_read": dict(fs.REGRADE_CONDITION_READ),
            "branches": [{"branch": b["branch"], "p": q(b["p"], "0.0001"),
                          "ev_if_realised": usd(b["ev_if_realised"]["amount"]),
                          "note": b.get("note")} for b in reg.branches],
            "refusal": None,
        },
    }
    # An itemised stack has to add up as displayed. Each line is rounded to
    # cents, so net is derived from the rounded lines rather than from the
    # engine's unrounded EV -- otherwise the column sums to a cent off on
    # screen, which reads as a bug in the arithmetic rather than in the
    # rounding. The test asserts the two agree to within a cent.
    crack_friction = sum(Decimal(v["amount"]) for v in crack["friction"].values()
                         if isinstance(v, dict))
    crack["net_spread"] = usd(Decimal(crack["gross_spread"]["amount"]) - crack_friction)
    crack["net_margin_pct"]["value"] = q(
        Decimal(crack["net_spread"]["amount"]) / slab * 100, "0.01")
    arb["rows"] = [row for row in arb["rows"] if row["path"] != "crack_resubmit"]
    arb["rows"].append(crack)
    arb["warnings"] = [
        "Crack & resubmit uses the regrade conditional prior, not the base gem "
        "rate. The two are different numbers on purpose."]
    save("arbitrage_board", arb)

    # -------------------------------------------------------- track_record
    # Every figure on this screen is now derived from the ledger below it.
    # The screen exists to be honest about the app's record; it cannot be the
    # one screen whose numbers were typed.
    tr = load("track_record")
    tr["ledger"] = build_ledger()
    tr.pop("recent", None)
    tr["scored_alert_count"] = len(tr["ledger"])

    for horizon in fs.HORIZONS:
        key = f"excess_return_{horizon}d"
        scored = [e for e in tr["ledger"] if e[key]["value"] is not None]
        values = [Decimal(e[key]["value"]) for e in scored]
        hits = sum(1 for v in values if v > 0)
        rate = tr[f"hit_rate_{horizon}d"]
        rate["value"] = q(Decimal(hits) / Decimal(len(scored)))
        rate["sample_size"] = len(scored)
        rate["estimate_basis"] = "none"
        if horizon == 30:
            tr["median_excess_return"]["value"] = q(median(values), "0.0001")
            tr["median_excess_return"]["sample_size"] = len(scored)

    # Per play type, each carrying its own n. A 38% hit rate on five alerts and
    # on two hundred are not the same claim.
    tr["by_play_type"] = []
    for play in sorted({e["rule"] for e in tr["ledger"]}):
        scored = [e for e in tr["ledger"]
                  if e["rule"] == play and e["excess_return_30d"]["value"] is not None]
        if not scored:
            continue
        values = [Decimal(e["excess_return_30d"]["value"]) for e in scored]
        hits = sum(1 for v in values if v > 0)
        tr["by_play_type"].append({
            "play_type": play,
            "hit_rate_30d": derived(q(Decimal(hits) / Decimal(len(scored))), "ratio",
                               "engine:ledger", sample=len(scored),
                               confidence="low" if len(scored) < 10 else "medium"),
            "median_excess_return_30d": derived(q(median(values), "0.0001"), "ratio",
                                           "engine:ledger", sample=len(scored),
                                           confidence="low" if len(scored) < 10
                                           else "medium"),
        })

    # Worst five by realised 90-day excess return, worst first. Derived, so it
    # cannot drift from the ledger it claims to summarise.
    matured = [e for e in tr["ledger"] if e["excess_return_90d"]["value"] is not None]
    tr["worst_five"] = sorted(
        matured, key=lambda e: Decimal(e["excess_return_90d"]["value"]))[:5]
    typed = sum(1 for e in tr["worst_five"]
                if e["estimate_basis"] == "user_estimate")
    thin = [b["play_type"] for b in tr["by_play_type"]
            if b["hit_rate_30d"]["sample_size"] < 10]
    tr["warnings"] = [
        f"{typed} of the five worst calls rest on a grade probability I typed.",
        f"90-day hit rate covers {tr['hit_rate_90d']['sample_size']} of "
        f"{tr['scored_alert_count']} alerts; the rest have not matured.",
    ] + ([f"Thin per-play samples: {', '.join(thin)}."] if thin else [])
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
    # Mirror the registry rather than maintaining a second copy of it. The
    # contract test asserts the two match; deriving it is how they stay matched
    # when an assumption is added.
    registry = json.load(open(os.path.join(FIX, "..", "assumptions.json"),
                              encoding="utf-8"))
    by_id = {a["id"]: a for a in settings["assumptions"]}
    settings["assumptions"] = []
    for key, entry in registry.items():
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        current = entry["current_value"]
        view = by_id.get(key, {})
        view.update({
            "id": entry["id"], "description": entry["description"],
            "current_value": (current if isinstance(current, (str, type(None)))
                              else json.dumps(current, ensure_ascii=False)),
            "unit": entry["unit"], "confidence": entry["confidence"],
            "source": entry.get("source"),
            "last_reviewed": entry.get("last_reviewed"),
            "calibration_plan": entry["calibration_plan"],
            "ui_chip_required": entry.get("ui_chip_required", False),
            "editable": entry.get("editable", True),
        })
        settings["assumptions"].append(view)
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

    # Last pass, over every fixture: CLAUDE.md Conventions/Time requires both
    # halves of the pair, and the contract had shipped only one. Applied here
    # rather than at each call site so a hand-built payload cannot skip it.
    for name in ("home", "signals", "card_detail", "grading_lab",
                 "grading_lab.refusal", "arbitrage_board", "trend_radar",
                 "track_record", "settings", "manual_entry"):
        payload = load(name)
        stamp_observed_at(payload)
        save(name, payload)

    print(f"regenerated against the engine: needed P(10)="
          f"{q(r.break_even_p_target)}, modelled={q(r.modelled_p_target)}, "
          f"EV={r.ev.amount}, ROI={q(r.roi)}, horizon={r.horizon_days}d")


if __name__ == "__main__":
    main()
