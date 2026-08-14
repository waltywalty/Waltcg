"""Import charges on the return leg of a cross-border grading submission.

Sending a card from the UK to a US grader means the card coming back can be
treated as a fresh import: import VAT plus customs duty on the **full declared
value of the graded card**, not on the value the grading added.

Three reliefs, and which one applies is the single largest uncertainty in any
cross-border grading decision:

* ``relief_none`` -- the default, and the realistic outcome for an unprepared
  private sender. Charged on the whole declared value.
* ``relief_rgr`` -- Returned Goods Relief zeroes the charge, but requires the
  goods to be re-imported *unaltered* and *not upgraded to increase their
  value*. Grading is arguably exactly that, and HMRC publishes no card-specific
  guidance. Requires evidence of the prior export.
* ``relief_opr`` -- Outward Processing Relief charges only on the value added
  (grading fee plus return freight), but needs authorisation **before** export,
  which takes roughly thirty working days. Impractical for a one-off.

**The charge is not a flat percentage and not a fixed cost.**

Two things follow from that, and both matter to the arithmetic:

1. **It compounds.** Duty is charged on goods plus freight; VAT is charged on
   goods plus freight *plus the duty*. At 20% VAT and 2% duty the effective
   charge on the sticker price is above 22%, not equal to it.

2. **Under ``relief_none`` it is a per-outcome cost, not a fixed one.** The
   declared value is the value of the card *that comes back*, so a PSA 10 is
   charged more than a PSA 9 on the same submission. It therefore reduces each
   branch's net proceeds rather than sitting in the cost total, which is also
   what keeps the break-even solve linear in p and closed-form. Under
   ``relief_opr`` the base is the value added, which does not depend on the
   grade, so there it genuinely is a fixed cost.

The expected charge is reported separately so it can be shown on the cost side
without being double-counted in the total.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .money import Money

RELIEF_SCENARIOS = ("relief_none", "relief_rgr", "relief_opr")


class ImportChargeError(ValueError):
    """The configured import-charge rule cannot be applied as written."""


def _pct(raw, name):
    if raw is None:
        raise ImportChargeError(f"{name} is null")
    value = Decimal(str(raw))
    if value < 0 or value > 1:
        raise ImportChargeError(
            f"{name} = {value}; expected a fraction, not a percentage")
    return value


def charge_on(declared_value: Money, freight: Money, rule: dict) -> Money:
    """Duty then VAT, in that order, on a declared value.

    duty = duty_pct * (goods + freight)
    vat  = vat_pct  * (goods + freight + duty)

    The VAT base including the duty is what pushes the effective rate above the
    sum of the two headline percentages.
    """
    if not isinstance(declared_value, Money) or not isinstance(freight, Money):
        raise TypeError("declared_value and freight must be Money")
    if declared_value.currency != freight.currency:
        raise ImportChargeError(
            f"declared value is {declared_value.currency} but freight is "
            f"{freight.currency}; convert with an explicit FxRate first")

    duty_pct = _pct(rule.get("duty_pct"), "duty_pct")
    vat_pct = _pct(rule.get("vat_pct"), "vat_pct")

    dutiable = declared_value + freight
    duty = dutiable * duty_pct
    vat = (dutiable + duty) * vat_pct
    return duty + vat


def effective_rate(rule: dict) -> Decimal:
    """What the compounded charge actually costs, per unit of goods value,
    ignoring freight. Reported so the config's 20% + 2% cannot be read as 22%."""
    duty_pct = _pct(rule.get("duty_pct"), "duty_pct")
    vat_pct = _pct(rule.get("vat_pct"), "vat_pct")
    return duty_pct + vat_pct * (Decimal(1) + duty_pct)


def import_charge_by_grade(
    proceeds_by_grade: dict,
    declared_by_grade: dict,
    *,
    rule: dict,
    relief: str,
    return_freight: Money,
    value_added: Money,
) -> dict:
    """Charge per outcome branch. Returns {grade: Money}, always non-negative.

    `declared_by_grade` is what customs would see on the returned parcel -- the
    graded card's market value -- which is why it varies by grade. It is
    deliberately a separate argument from `proceeds_by_grade`: proceeds are net
    of selling fees, and customs does not care what you later pay eBay.
    """
    if relief not in RELIEF_SCENARIOS:
        raise ImportChargeError(
            f"unknown relief scenario {relief!r}; expected one of "
            f"{', '.join(RELIEF_SCENARIOS)}")

    currency = return_freight.currency
    if relief == "relief_rgr":
        return {g: Money.zero(currency) for g in proceeds_by_grade}

    if relief == "relief_opr":
        # Charged on the value added only, which does not depend on the grade.
        flat = charge_on(value_added, Money.zero(currency), rule)
        return {g: flat for g in proceeds_by_grade}

    charges = {}
    for grade in proceeds_by_grade:
        declared = declared_by_grade.get(grade)
        if declared is None:
            raise ImportChargeError(
                f"no declared value for grade {grade!r}; an import charge "
                "cannot be computed from the net proceeds, because customs "
                "values the card and not what you clear after selling fees")
        charges[grade] = charge_on(declared, return_freight, rule)
    return charges


def resolve_rule(cfg, route: str, *, home_key="grading.import_charges.home_jurisdiction"):
    """Look up the import rule for a grading route.

    Returns (rule, applies, detail). `applies` is False for a domestic route --
    the asymmetry that is the main reason to prefer a domestic grader, and it
    is reported rather than silently producing a smaller number.
    """
    from .config import MISSING

    home = cfg.get(home_key)
    facility = cfg.get(f"grading.routes.{route}.facility_jurisdiction")
    if home is MISSING or facility is MISSING:
        return None, False, ("route or home jurisdiction not configured", None)
    if facility == home:
        return None, False, (
            f"domestic route: {route} grades in {facility} and home is {home}, "
            "so the card never re-enters the country and no import charge "
            "arises", facility)
    rule = cfg.get(f"grading.import_charges.{home}")
    if rule is MISSING:
        return None, False, (f"no import-charge rule configured for {home}", facility)
    return rule, True, (
        f"cross-border route: graded in {facility}, returned to {home}", facility)


def summarise(charges: dict, probs: dict, currency: str) -> Optional[Money]:
    """Probability-weighted expected charge, for display on the cost side.

    Not added to the cost total: under relief_none the charge is already
    deducted per branch, and adding it again would double-count it.
    """
    if not charges:
        return None
    total = Money.zero(currency)
    for grade, charge in charges.items():
        weight = probs.get(grade)
        if weight is None:
            continue
        total = total + (charge * Decimal(str(weight)))
    return total


def route_freight(cfg, route: str, currency: str, fx=None):
    """(outbound, return) freight for a route, in the working currency.

    A route can be priced in its own currency -- the UK route is quoted in GBP
    while the working currency is USD -- so this either converts with an
    explicit rate or raises. It never assumes parity, because assuming parity
    between GBP and USD understates the domestic route by about a fifth and the
    whole point of the comparison is which route is cheaper.
    """
    from .config import MISSING
    from .money import Money

    route_currency = cfg.get(f"grading.routes.{route}.currency")
    if route_currency is MISSING:
        raise ImportChargeError(f"grading.routes.{route}.currency is not set")

    def read(field):
        raw = cfg.get(f"grading.routes.{route}.{field}")
        if raw is MISSING or raw is None:
            raise ImportChargeError(f"grading.routes.{route}.{field} is null")
        return Money(str(raw), route_currency)

    outbound, ret = read("outbound_shipping"), read("return_shipping_insured")
    if route_currency == currency:
        return outbound, ret
    if fx is None:
        raise ImportChargeError(
            f"route {route} is priced in {route_currency} but the working "
            f"currency is {currency}; supply an explicit FxRate. There is no "
            "implicit conversion here on purpose.")
    return outbound.to(currency, fx), ret.to(currency, fx)
