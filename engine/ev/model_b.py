"""MODEL B -- regrade_9_to_10_ev.

A card already in a PSA 9 slab is not a random card. PSA examined it and
declined to give it a 10. Using the base gem rate as P(10) on a resubmission
therefore double-counts information the grader has already acted on, and it is
the single most common way this calculation is got wrong.

This model is FORBIDDEN from touching the base gem rate. It uses
`assumptions.regrade_conditional_prior`, which is deliberately conservative,
and it will not move off that default without an explicit condition read from
the user. No condition read, no number -- it returns a Refusal, because a
confident-looking EV derived from a prior nobody examined is worse than no
answer.

Three outcome branches, all of them real:
    upgrade to 10   the reason for doing it
    regrade 9       the modal outcome; you have paid fees for the same slab
    below 9         non-zero. A different grader on a different day can see
                    the card less generously, and the slab is gone.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .breakeven import annualised, net_proceeds, solve_break_even_p
from .comps import comp_basis
from .config import MISSING, Config, business_days_to_calendar
from .fees import FeeScheduleError, net_proceeds_from_schedule
from .imports import (ImportChargeError, effective_rate, import_charge_by_grade,
                      resolve_rule, route_freight, summarise)
from .money import Money
from .results import CostBreakdown, EVResult, GradeDistribution, Provenance, Refusal

MODEL = "regrade_9_to_10_ev"

CONDITION_FIELDS = ("centering_pct", "corner_flag", "surface_flag", "edge_flag")


def required_paths(grader: str, tier: str, venue: str, schedule: bool = False, route: Optional[str] = None) -> list:
    # A venue carries either a modern banded fee_schedule or the older flat
    # trio. Model A already branched on this; model B did not, so it demanded
    # `final_value_fee_pct` from a venue whose config supplies a schedule
    # instead -- and eBay is exactly that venue. The model could not run
    # against shipped config at all, for a reason that had nothing to do with
    # the regrade prior it exists to apply. Two models must also not price the
    # same venue's fees two different ways, or two screens disagree about eBay.
    venue_fee_paths = (
        [f"fees.marketplaces.{venue}.fee_schedule.base",
         f"fees.marketplaces.{venue}.fee_schedule.bands"]
        if schedule else
        [f"fees.marketplaces.{venue}.final_value_fee_pct",
         f"fees.marketplaces.{venue}.payment_pct",
         f"fees.marketplaces.{venue}.payment_fixed"])
    freight_paths = ([f"grading.routes.{route}.outbound_shipping",
                      f"grading.routes.{route}.return_shipping_insured",
                      f"grading.routes.{route}.currency"] if route else
                     ["grading.submission_costs.inbound_shipping",
                      "grading.submission_costs.return_shipping_insured"])
    return venue_fee_paths + freight_paths + [
        "grading.meta.currency",
        f"grading.graders.{grader}.tiers.{tier}.fee",
        f"grading.graders.{grader}.tiers.{tier}.turnaround_business_days",
        f"grading.graders.{grader}.tiers.{tier}.availability",

        "grading.submission_costs.supplies_per_card",
        "grading.submission_costs.default_batch_size",
        f"fees.marketplaces.{venue}.currency",
        "fees.region_defaults.default_days_to_sell",
        "assumptions.regrade_conditional_prior.current_value",
        "assumptions.regrade_downgrade_probability.current_value",
    ]


def _validate_condition_read(condition_read) -> Optional[Refusal]:
    if condition_read is None:
        return Refusal(
            MODEL, "no condition read supplied",
            "P(10) for a card already slabbed at 9 cannot come from the base gem rate -- "
            "PSA already saw this card and said no. Supply a condition read with "
            f"{', '.join(CONDITION_FIELDS)} so the conservative default can be adjusted, "
            "or accept that this model will not produce a number.",
            missing=list(CONDITION_FIELDS))
    absent = [f for f in CONDITION_FIELDS if condition_read.get(f) is None]
    if absent:
        return Refusal(
            MODEL, "incomplete condition read",
            "every condition field must be supplied; a partial read is how an optimistic "
            "prior sneaks in through the gap",
            missing=absent)
    return None


ADJ_ROOT = "assumptions.regrade_condition_adjustments.current_value"
CLEAN_WORDS = ("clean", "ok", "true", "yes")


def _adjustment_keys(condition_read: dict) -> list:
    """Which multiplier keys this particular condition read will consult.

    Computed before any arithmetic so the required-config check can name every
    value up front, rather than raising part-way through a calculation.
    """
    keys = []
    centering = condition_read.get("centering_pct")
    if centering is not None:
        c = Decimal(str(centering))
        if c >= Decimal("60"):
            keys.append("centering_pct_ge_60_40")
        elif c >= Decimal("55"):
            keys.append("centering_pct_ge_55_45")
    dirty = False
    for field_name, key in (("corner_flag", "corner_flag_clean"),
                            ("surface_flag", "surface_flag_clean"),
                            ("edge_flag", "edge_flag_clean")):
        if str(condition_read.get(field_name)).lower() in CLEAN_WORDS:
            keys.append(key)
        else:
            dirty = True
    if dirty:
        keys.append("any_flag_dirty")
    return keys


def _adjusted_prior(cfg: Config, condition_read: dict):
    """Apply condition multipliers to the conservative default prior."""
    p = cfg.decimal("assumptions.regrade_conditional_prior.current_value")
    applied = []
    for key in _adjustment_keys(condition_read):
        m = cfg.decimal(f"{ADJ_ROOT}.{key}")
        p = p * m
        applied.append(f"{key} x{m}")
    return (Decimal(1) if p > 1 else p), applied


def regrade_9_to_10_ev(
    card_uid: str,
    slab_market_value_9: Money,
    comps_by_grade: dict,
    *,
    cfg: Config,
    condition_read: Optional[dict] = None,
    grader: str = "PSA",
    tier: str = "regular",
    venue: str = "ebay",
    route: Optional[str] = None,
    route_fx=None,
    comps_grader: Optional[str] = None,
    outbound_shipping: Optional[Money] = None,
    batch_size: Optional[int] = None,
    days_to_sell: Optional[int] = None,
):
    """Break-even P(10) for cracking or resubmitting a PSA 9.

    `slab_market_value_9` is what the card is worth today, unmolested. It is
    the opportunity cost of the attempt, and it belongs on the cost side.
    """
    if not isinstance(slab_market_value_9, Money):
        raise TypeError("slab_market_value_9 must be Money, not a bare number")

    refusal = _validate_condition_read(condition_read)
    if refusal is not None:
        refusal.subject = card_uid
        return refusal

    if cfg.get("grading.import_charges") is not MISSING and not route:
        return Refusal(
            MODEL, "no grading route supplied",
            "import charges are configured; the route decides whether the "
            "return leg is charged. A regrade crosses the border twice for a "
            "card that may come back in the same slab.",
            missing=["route"], subject=card_uid)

    uses_schedule = cfg.get(f"fees.marketplaces.{venue}.fee_schedule") is not MISSING
    cfg.require(required_paths(grader, tier, venue, schedule=uses_schedule,
                               route=route)
                + [f"{ADJ_ROOT}.{k}" for k in _adjustment_keys(condition_read)],
                context=f"{MODEL} for {card_uid}")

    currency = cfg.get("grading.meta.currency")
    if slab_market_value_9.currency != currency:
        return Refusal(MODEL, "currency mismatch",
                       f"slab value is {slab_market_value_9.currency}, working currency "
                       f"is {currency}", subject=card_uid)

    availability = cfg.get(f"grading.graders.{grader}.tiers.{tier}.availability")
    if str(availability).lower() != "open":
        return Refusal(MODEL, "tier unavailable",
                       f"{grader} tier {tier!r} is {availability!r}", subject=card_uid)

    p10, applied = _adjusted_prior(cfg, condition_read)
    p_below9 = cfg.decimal("assumptions.regrade_downgrade_probability.current_value")
    if p10 + p_below9 > 1:
        return Refusal(MODEL, "inconsistent prior",
                       f"P(10)={p10} and P(<9)={p_below9} sum above 1", subject=card_uid)
    p9 = Decimal(1) - p10 - p_below9

    probs = {"10": p10, "9": p9, "below_9": p_below9}

    # -- costs. The slab you already own is the largest line item. --------
    batch = int(batch_size or cfg.get("grading.submission_costs.default_batch_size"))
    fee = Money(str(cfg.decimal(f"grading.graders.{grader}.tiers.{tier}.fee")), currency)
    if route:
        try:
            _out, _ret = route_freight(cfg, route, currency, route_fx)
        except ImportChargeError as e:
            return Refusal(MODEL, "route freight unusable", str(e),
                           missing=[f"grading.routes.{route}"], subject=card_uid)
        inbound, ret = _out / batch, _ret / batch
    else:
        inbound = Money(str(cfg.decimal(
            "grading.submission_costs.inbound_shipping")), currency) / batch
        ret = Money(str(cfg.decimal("grading.submission_costs.return_shipping_insured")),
                currency) / batch
    supplies = Money(str(cfg.decimal("grading.submission_costs.supplies_per_card")), currency)

    costs = CostBreakdown(
        acquisition=slab_market_value_9,   # opportunity cost of the intact slab
        tax=Money.zero(currency),
        inbound_shipping=inbound,
        supplies=supplies,
        grading_fee=fee,
        return_shipping=ret,
    )
    total_cost = costs.total()

    # -- proceeds ---------------------------------------------------------
    schedule = cfg.get(f"fees.marketplaces.{venue}.fee_schedule") if uses_schedule else None
    if not uses_schedule:
        fvf = cfg.decimal(f"fees.marketplaces.{venue}.final_value_fee_pct")
        pay_pct = cfg.decimal(f"fees.marketplaces.{venue}.payment_pct")
        fixed = Money(str(cfg.decimal(f"fees.marketplaces.{venue}.payment_fixed")),
                      currency)
    ship_out = outbound_shipping or Money.zero(currency)

    proceeds = {}
    for grade in ("10", "9", "below_9"):
        comp = comps_by_grade.get(grade)
        if comp is None:
            return Refusal(MODEL, "missing comp",
                           f"no sale comp supplied for branch {grade!r}; all three "
                           "branches must be priced", subject=card_uid)
        if not isinstance(comp, Money):
            raise TypeError(f"comp for {grade} must be Money")
        if schedule:
            try:
                proceeds[grade] = net_proceeds_from_schedule(
                    comp, schedule, outbound_shipping=ship_out)
            except FeeScheduleError as e:
                return Refusal(MODEL, "fee schedule unusable", str(e),
                               missing=[f"fees.marketplaces.{venue}.fee_schedule"],
                               subject=card_uid)
        else:
            proceeds[grade] = net_proceeds(comp, fvf, pay_pct, fixed, ship_out)

    import_rule, import_applies, (import_note, _facility) = (
        resolve_rule(cfg, route) if route else (None, False, ("no route", None)))
    relief = cfg.get("assumptions.relief_scenario.current_value", "relief_none")
    import_charges = {}
    if import_applies:
        return_freight = ret
        try:
            import_charges = import_charge_by_grade(
                proceeds, comps_by_grade, rule=import_rule, relief=relief,
                return_freight=return_freight, value_added=fee + return_freight)
        except ImportChargeError as e:
            return Refusal(MODEL, "import charge rule unusable", str(e),
                           missing=["grading.import_charges"], subject=card_uid)
        proceeds = {g: n - import_charges[g] for g, n in proceeds.items()}

    ev = Money.zero(currency)
    for grade, p in probs.items():
        ev = ev + (proceeds[grade] * p)
    ev = ev - total_cost

    roi = (ev.amount / total_cost.amount) if total_cost.amount != 0 else None
    turn_bd = (cfg.get(f"grading.graders.{grader}.tiers.{tier}.turnaround_observed_days", None)
               or cfg.get(f"grading.graders.{grader}.tiers.{tier}.turnaround_business_days"))
    horizon = business_days_to_calendar(turn_bd) + int(
        days_to_sell if days_to_sell is not None
        else cfg.get("fees.region_defaults.default_days_to_sell"))
    ann = annualised(roi, horizon) if roi is not None else None

    be = solve_break_even_p("10", proceeds, probs, total_cost)

    dist = GradeDistribution(
        probs=probs,
        prior_used=("assumptions.regrade_conditional_prior (base gem rate is FORBIDDEN "
                    "here: the card is already conditioned on PSA declining a 10)"),
        notes=[f"condition adjustments applied: {', '.join(applied) or 'none'}"])

    branches = [
        {"branch": "upgrade_to_10", "p": str(p10),
         "net_proceeds": proceeds["10"].as_dict(),
         "ev_if_realised": (proceeds["10"] - total_cost).as_dict()},
        {"branch": "regrade_9", "p": str(p9),
         "net_proceeds": proceeds["9"].as_dict(),
         "ev_if_realised": (proceeds["9"] - total_cost).as_dict(),
         "note": "modal outcome: fees paid for the same slab back"},
        {"branch": "downgrade_below_9", "p": str(p_below9),
         "net_proceeds": proceeds["below_9"].as_dict(),
         "ev_if_realised": (proceeds["below_9"] - total_cost).as_dict(),
         "note": "the intact 9 no longer exists in this branch"},
    ]

    return EVResult(
        model=MODEL, subject=card_uid,
        break_even_p_target=be["p"],
        break_even_attainable=bool(be.get("attainable")),
        break_even_note=be.get("reason", ""), target_grade="10", modelled_p_target=p10,
        ev=ev, roi=roi, annualised_roi=ann, horizon_days=horizon,
        costs=costs, grade_distribution=dist, branches=branches,
        downside_case=branches[2],
        comp_basis=comp_basis(grader, comps_grader, route=route),
        import_charges={
            "applies": import_applies, "route": route, "note": import_note,
            "relief_scenario": relief if import_applies else None,
            "expected": (summarise(import_charges, probs, currency).as_dict()
                         if import_applies else None),
            "by_grade": {g: c.as_dict() for g, c in import_charges.items()},
            "effective_rate_on_goods": (str(effective_rate(import_rule))
                                        if import_applies else None),
        },
        provenance=Provenance(
            as_of=str(cfg.today),
            sources=["contracts/assumptions.json::regrade_conditional_prior",
                     f"config/grading.yaml::{grader}.{tier}", f"config/fees.yaml::{venue}"],
            warnings=[str(w) for w in cfg.staleness_warnings()],
            notes=["base gem rate deliberately not used", be.get("reason") or ""]),
    )
