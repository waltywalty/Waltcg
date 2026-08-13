"""The break-even probability solver.

This is the headline output of the grading models, and the reason they exist.
A point EV hides the fact that the probability is the uncertain input: it
takes a number you are guessing at, multiplies it by a number you know, and
presents the product with false confidence. Inverting the question is more
honest -- given everything you DO know (costs, fees, comps, turnaround), what
probability of the target grade would this submission need in order to break
even? Then you compare that bar against your own read of the card.

The arithmetic is exact and hand-checkable. Holding the relative shape of the
non-target grades fixed, expected proceeds are linear in p:

    EV(p) = p * N_target + (1 - p) * A  -  costs
    where A = sum over non-target grades of (w_g * N_g), w normalised

so EV(p) = 0 solves in closed form:

    p* = (costs - A) / (N_target - A)

No search, no iteration, no tolerance. If N_target <= A the card is worth no
more at the target grade than below it and no probability rescues it, which
is reported as such rather than as a large number.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .money import Money


def net_proceeds(
    sale_value: Money,
    final_value_fee_pct: Decimal,
    payment_pct: Decimal,
    fixed_fee: Money,
    outbound_shipping: Money,
) -> Money:
    """V * (1 - fvf - payment_pct) - fixed_fee - outbound_shipping."""
    keep = Decimal(1) - Decimal(final_value_fee_pct) - Decimal(payment_pct)
    return (sale_value * keep) - fixed_fee - outbound_shipping


def expected_proceeds(probs: dict, proceeds_by_grade: dict, currency: str) -> Money:
    total = Money.zero(currency)
    for grade, p in probs.items():
        n = proceeds_by_grade.get(grade)
        if n is None:
            continue
        total = total + (n * p)
    return total


def solve_break_even_p(
    target_grade: str,
    proceeds_by_grade: dict,
    base_probs: dict,
    costs: Money,
) -> dict:
    """Probability of `target_grade` at which EV == 0.

    Returns a dict rather than a bare number so the caller can distinguish
    "needs 43%" from "no probability makes this work" from "profitable even
    if it never hits the target".
    """
    currency = costs.currency
    target = str(target_grade)
    n_target = proceeds_by_grade.get(target)
    if n_target is None:
        return {"p": None, "attainable": False,
                "reason": f"no comp for the target grade {target}"}

    # Relative shape of everything that is not the target grade.
    others = {g: p for g, p in base_probs.items() if g != target and p > 0}
    other_mass = sum(others.values(), Decimal(0))
    if other_mass > 0:
        a = Money.zero(currency)
        for g, p in others.items():
            n = proceeds_by_grade.get(g)
            if n is None:
                continue
            a = a + (n * (p / other_mass))
    else:
        # Degenerate: the base distribution puts everything on the target.
        # Falling to "no sale" is the only meaningful alternative.
        a = Money.zero(currency)

    spread = n_target - a
    if spread.amount <= 0:
        return {"p": None, "attainable": False,
                "a_non_target": a, "n_target": n_target,
                "reason": ("the target grade is worth no more than the alternatives "
                           "after fees; no probability makes this profitable")}

    p = (costs.amount - a.amount) / spread.amount

    if p <= 0:
        return {"p": Decimal(0), "attainable": True, "always_profitable": True,
                "a_non_target": a, "n_target": n_target,
                "reason": ("profitable even if the card never reaches the target grade")}
    if p > 1:
        return {"p": p, "attainable": False,
                "a_non_target": a, "n_target": n_target,
                "reason": ("break-even needs a probability above 1; the submission "
                           "cannot pay for itself at these comps and costs")}
    return {"p": p, "attainable": True, "a_non_target": a, "n_target": n_target,
            "reason": ""}


def annualised(roi: Decimal, horizon_days: int) -> Optional[Decimal]:
    """(1 + roi) ** (365 / days) - 1, via float only for the exponent.

    Kept deterministic and quantised so tests can assert on it. Returns None
    for a non-positive horizon, and for a total loss where the power is
    undefined over the reals.
    """
    if horizon_days is None or horizon_days <= 0:
        return None
    base = Decimal(1) + roi
    if base <= 0:
        return None
    import math
    scaled = math.pow(float(base), 365.0 / float(horizon_days)) - 1.0
    return Decimal(str(scaled)).quantize(Decimal("0.000001"))
