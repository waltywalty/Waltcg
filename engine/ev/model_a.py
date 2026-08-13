"""MODEL A -- raw_to_graded_ev.

Given a raw card and a grading tier, what probability of the target grade
would the submission need in order to break even? That break-even probability
is the output that matters. The point EV is reported too, and is secondary,
because it multiplies a number you are guessing at by numbers you know and
then reads like a fact.

Cost side:      acquisition + tax + inbound shipping + supplies
                + grading fee + insured return shipping
Proceeds side:  sum over grades of P(g) * [ V_g * (1 - fvf - payment_pct)
                                            - fixed_fee - outbound_shipping ]

Zero learned parameters. Every number is either passed in, read from a dated
config, or derived by arithmetic that a person can reproduce on paper.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .breakeven import annualised, expected_proceeds, net_proceeds, solve_break_even_p
from .config import Config, ConfigIncomplete, business_days_to_calendar
from .grades import shrunk_grade_distribution
from .money import Money
from .results import CostBreakdown, EVResult, GradeDistribution, Provenance, Refusal

MODEL = "raw_to_graded_ev"


def required_paths(grader: str, tier: str, venue: str) -> list:
    return [
        "grading.meta.currency",
        f"grading.graders.{grader}.tiers.{tier}.fee",
        f"grading.graders.{grader}.tiers.{tier}.turnaround_business_days",
        f"grading.graders.{grader}.tiers.{tier}.availability",
        f"grading.graders.{grader}.tiers.{tier}.min_cards",
        "grading.submission_costs.inbound_shipping",
        "grading.submission_costs.return_shipping_insured",
        "grading.submission_costs.supplies_per_card",
        "grading.submission_costs.default_batch_size",
        f"fees.marketplaces.{venue}.final_value_fee_pct",
        f"fees.marketplaces.{venue}.payment_pct",
        f"fees.marketplaces.{venue}.payment_fixed",
        f"fees.marketplaces.{venue}.currency",
        "fees.region_defaults.default_days_to_sell",
        "assumptions.submission_selection_haircut.value",
        "assumptions.tax.acquisition_tax_pct.value",
        "assumptions.empirical_bayes.prior_strength_cards.value",
        "assumptions.empirical_bayes.min_card_pop_for_own_prior.value",
    ]


def raw_to_graded_ev(
    card_uid: str,
    acquisition_cost: Money,
    tier: str,
    comps_by_grade: dict,
    *,
    cfg: Config,
    grader: str = "PSA",
    venue: str = "ebay",
    target_grade: str = "10",
    grade_probs: Optional[GradeDistribution] = None,
    card_pop: Optional[dict] = None,
    set_pop: Optional[dict] = None,
    outbound_shipping: Optional[Money] = None,
    batch_size: Optional[int] = None,
    days_to_sell: Optional[int] = None,
):
    """Break-even probability for grading a raw card.

    `comps_by_grade` maps grade label -> Money sale comp. `grade_probs` may be
    supplied directly; otherwise it is derived from `card_pop` / `set_pop` by
    empirical-Bayes shrinkage plus the submission-selection haircut.
    """
    if not isinstance(acquisition_cost, Money):
        raise TypeError("acquisition_cost must be Money, not a bare number")

    cfg.require(required_paths(grader, tier, venue),
                context=f"{MODEL} for {card_uid} ({grader}/{tier} -> {venue})")

    currency = cfg.get("grading.meta.currency")
    venue_currency = cfg.get(f"fees.marketplaces.{venue}.currency")
    if venue_currency != currency:
        return Refusal(MODEL, "currency mismatch",
                       f"grading fees are quoted in {currency} but {venue} settles in "
                       f"{venue_currency}; supply an FX rate and convert explicitly",
                       subject=card_uid)
    if acquisition_cost.currency != currency:
        return Refusal(MODEL, "currency mismatch",
                       f"acquisition is {acquisition_cost.currency}, working currency is "
                       f"{currency}; convert with Money.to() and an explicit FxRate",
                       subject=card_uid)

    availability = cfg.get(f"grading.graders.{grader}.tiers.{tier}.availability")
    warnings = [str(w) for w in cfg.staleness_warnings()]
    if str(availability).lower() != "open":
        return Refusal(MODEL, "tier unavailable",
                       f"{grader} tier {tier!r} is {availability!r}; a submission cannot "
                       "be priced against a tier that is not accepting cards",
                       subject=card_uid)

    # -- grade distribution ---------------------------------------------
    if grade_probs is None:
        grade_probs = shrunk_grade_distribution(
            card_pop, set_pop,
            prior_strength=cfg.get("assumptions.empirical_bayes.prior_strength_cards.value"),
            selection_haircut=cfg.get("assumptions.submission_selection_haircut.value"),
            min_card_pop_for_own_prior=cfg.get(
                "assumptions.empirical_bayes.min_card_pop_for_own_prior.value"),
            target_grade=target_grade, subject=card_uid)
        if isinstance(grade_probs, Refusal):
            return grade_probs

    # -- costs ------------------------------------------------------------
    batch = int(batch_size or cfg.get("grading.submission_costs.default_batch_size"))
    if batch < 1:
        return Refusal(MODEL, "invalid batch size", f"batch_size={batch}", subject=card_uid)

    tax_pct = cfg.decimal("assumptions.tax.acquisition_tax_pct.value")
    fee_per_card = Money(str(cfg.decimal(
        f"grading.graders.{grader}.tiers.{tier}.fee")), currency)
    inbound_total = Money(str(cfg.decimal("grading.submission_costs.inbound_shipping")), currency)
    return_total = Money(str(cfg.decimal(
        "grading.submission_costs.return_shipping_insured")), currency)
    supplies = Money(str(cfg.decimal("grading.submission_costs.supplies_per_card")), currency)

    costs = CostBreakdown(
        acquisition=acquisition_cost,
        tax=acquisition_cost * tax_pct,
        inbound_shipping=inbound_total / batch,
        supplies=supplies,
        grading_fee=fee_per_card,
        return_shipping=return_total / batch,
    )
    total_cost = costs.total()

    # -- proceeds ---------------------------------------------------------
    fvf = cfg.decimal(f"fees.marketplaces.{venue}.final_value_fee_pct")
    pay_pct = cfg.decimal(f"fees.marketplaces.{venue}.payment_pct")
    fixed = Money(str(cfg.decimal(f"fees.marketplaces.{venue}.payment_fixed")), currency)
    ship_out = outbound_shipping or Money.zero(currency)
    if not isinstance(ship_out, Money):
        raise TypeError("outbound_shipping must be Money")

    proceeds_by_grade = {}
    for grade, value in comps_by_grade.items():
        if not isinstance(value, Money):
            raise TypeError(f"comp for grade {grade} must be Money, not a bare number")
        proceeds_by_grade[str(grade)] = net_proceeds(value, fvf, pay_pct, fixed, ship_out)

    probs = grade_probs.probs
    ev_proceeds = expected_proceeds(probs, proceeds_by_grade, currency)
    ev = ev_proceeds - total_cost

    roi = (ev.amount / total_cost.amount) if total_cost.amount != 0 else None

    # cfg.get() returns a MISSING sentinel for null, not None, so these
    # fallbacks must pass an explicit default rather than test for None.
    turn_bd = cfg.get(f"grading.graders.{grader}.tiers.{tier}.turnaround_observed_days", None)
    if turn_bd is None:
        turn_bd = cfg.get(f"grading.graders.{grader}.tiers.{tier}.turnaround_business_days")
    horizon = business_days_to_calendar(turn_bd) + int(
        days_to_sell if days_to_sell is not None
        else cfg.get("fees.region_defaults.default_days_to_sell"))
    ann = annualised(roi, horizon) if roi is not None else None

    # -- break-even probability (the headline) ----------------------------
    be = solve_break_even_p(target_grade, proceeds_by_grade, probs, total_cost)

    # -- downside branch: grade <= 8 --------------------------------------
    downside_grades = [g for g in probs
                       if _numeric(g) is not None and _numeric(g) <= Decimal(8)]
    p_down = sum((probs[g] for g in downside_grades), Decimal(0))
    if p_down > 0:
        cond = Money.zero(currency)
        for g in downside_grades:
            n = proceeds_by_grade.get(g)
            if n is not None:
                cond = cond + (n * (probs[g] / p_down))
        downside = {"p_grade_le_8": str(p_down),
                    "expected_proceeds_if_realised": (cond).as_dict(),
                    "ev_if_realised": (cond - total_cost).as_dict(),
                    "grades": sorted(downside_grades)}
    else:
        downside = {"p_grade_le_8": "0", "note": "no modelled mass at or below grade 8"}

    prov = Provenance(
        as_of=str(cfg.today),
        sources=[f"config/grading.yaml::{grader}.{tier}", f"config/fees.yaml::{venue}",
                 "contracts/assumptions.json"],
        warnings=warnings,
        notes=[grade_probs.prior_used] + list(grade_probs.notes)
        + [f"horizon = {business_days_to_calendar(turn_bd)} calendar days turnaround "
           f"+ {horizon - business_days_to_calendar(turn_bd)} days to sell",
           be.get("reason") or ""],
    )

    return EVResult(
        model=MODEL, subject=card_uid,
        break_even_p_target=be["p"], target_grade=str(target_grade),
        modelled_p_target=probs.get(str(target_grade)),
        ev=ev, roi=roi, annualised_roi=ann, horizon_days=horizon,
        costs=costs, downside_case=downside, grade_distribution=grade_probs,
        provenance=prov,
    )


def _numeric(grade) -> Optional[Decimal]:
    try:
        return Decimal(str(grade))
    except Exception:  # noqa: BLE001 - non-numeric grade labels are allowed
        return None
