"""Marketplace fee schedules.

A flat percentage is not what marketplaces actually charge, and modelling one
understates the fee stack silently. Three things the flat model got wrong:

  * **The base differs.** eBay's final value fee applies to item + shipping +
    tax, not to the item price. Applying 13.25% to the item alone understates
    the fee on every sale that ships.
  * **Fixed fees are tiered.** eBay charges $0.30 under $10 and $0.40 over.
  * **Rates are banded.** eBay discounts the FVF by half on singles at or
    above $1000, for the portion up to $7500, then charges 2.35% above that.
    A single card can straddle the breakpoint.

So a schedule is: a base, a set of marginal bands, an optional discount
schedule that replaces the bands above a threshold, and tiered fixed fees.
Marginal means each band's rate applies only to the portion of value inside
it -- the same shape as a tax bracket, and the same classic error if you apply
the top rate to the whole amount.

Everything here is arithmetic on config values. Nothing is learned, and every
worked example in the tests can be checked on paper.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .money import Money

# What the percentage applies to.
BASE_ITEM = "item"
BASE_ITEM_SHIPPING = "item_plus_shipping"
BASE_ITEM_SHIPPING_TAX = "item_plus_shipping_plus_tax"
VALID_BASES = (BASE_ITEM, BASE_ITEM_SHIPPING, BASE_ITEM_SHIPPING_TAX)


class FeeScheduleError(ValueError):
    """The schedule cannot be applied as written."""


def fee_base_amount(base: str, item: Money, shipping_charged: Money,
                    tax_collected: Money) -> Money:
    if base == BASE_ITEM:
        return item
    if base == BASE_ITEM_SHIPPING:
        return item + shipping_charged
    if base == BASE_ITEM_SHIPPING_TAX:
        return item + shipping_charged + tax_collected
    raise FeeScheduleError(
        f"unknown fee base {base!r}; expected one of {VALID_BASES}. The base is not "
        "guessable -- a percentage means nothing without knowing what it multiplies."
    )


def _banded_amount(amount: Money, bands: list) -> Money:
    """Apply marginal bands. Each rate applies to the portion inside its band."""
    if not bands:
        raise FeeScheduleError("fee schedule has no bands")
    total = Money.zero(amount.currency)
    lower = Decimal(0)
    for band in bands:
        pct = band.get("pct")
        if pct is None:
            raise FeeScheduleError(f"band {band} has no pct")
        upper = band.get("up_to")
        cap = amount.amount if upper is None else min(amount.amount, Decimal(str(upper)))
        portion = cap - lower
        if portion > 0:
            total = total + Money(portion, amount.currency) * Decimal(str(pct))
        lower = cap
        if upper is not None and amount.amount <= Decimal(str(upper)):
            break
    return total


def _fixed_fee(item: Money, fixed_bands: Optional[list], flat_fixed) -> Money:
    """Tiered fixed fee, keyed on the item price. Falls back to a flat value."""
    if fixed_bands:
        for band in fixed_bands:
            upper = band.get("up_to")
            if upper is None or item.amount < Decimal(str(upper)):
                return Money(str(band["fee"]), item.currency)
        return Money(str(fixed_bands[-1]["fee"]), item.currency)
    return Money(str(flat_fixed or 0), item.currency)


def marketplace_fee(
    item: Money,
    schedule: dict,
    *,
    shipping_charged: Optional[Money] = None,
    tax_collected: Optional[Money] = None,
) -> dict:
    """Total marketplace + payment fee for one sale, itemised.

    Returns the components as well as the total, because a fee stack you
    cannot see the parts of is a fee stack you cannot check.
    """
    cur = item.currency
    shipping_charged = shipping_charged or Money.zero(cur)
    tax_collected = tax_collected or Money.zero(cur)

    base_name = schedule.get("base")
    if base_name is None:
        raise FeeScheduleError(
            "fee schedule has no base. What the percentage multiplies was not "
            "recorded, so the fee cannot be computed and must not be assumed."
        )
    base = fee_base_amount(base_name, item, shipping_charged, tax_collected)

    # A discount schedule replaces the standard bands entirely above its
    # threshold -- it is not applied on top of them.
    bands = schedule.get("bands")
    discount = schedule.get("discount")
    discount_applied = False
    if discount and discount.get("applies_at_or_above") is not None:
        if item.amount >= Decimal(str(discount["applies_at_or_above"])):
            bands = discount.get("bands")
            discount_applied = True

    commission = _banded_amount(base, bands)

    payment = schedule.get("payment") or {}
    pay_pct = Decimal(str(payment.get("pct", 0) or 0))
    if pay_pct:
        pay_base_name = payment.get("base", base_name)
        pay_base = fee_base_amount(pay_base_name, item, shipping_charged, tax_collected)
        payment_pct_amount = pay_base * pay_pct
    else:
        payment_pct_amount = Money.zero(cur)

    fixed = _fixed_fee(item, payment.get("fixed_bands") or schedule.get("fixed_bands"),
                       payment.get("fixed"))

    total = commission + payment_pct_amount + fixed
    return {
        "base_name": base_name,
        "base_amount": base,
        "commission": commission,
        "payment_pct_amount": payment_pct_amount,
        "fixed": fixed,
        "total": total,
        "discount_applied": discount_applied,
    }


def net_proceeds_from_schedule(
    item: Money,
    schedule: dict,
    *,
    shipping_charged: Optional[Money] = None,
    tax_collected: Optional[Money] = None,
    outbound_shipping: Optional[Money] = None,
) -> Money:
    """What actually lands: item + shipping charged, less fees, less postage.

    `shipping_charged` is what the buyer pays and is revenue. `outbound_shipping`
    is what postage costs us. They are different numbers and both matter.
    """
    cur = item.currency
    shipping_charged = shipping_charged or Money.zero(cur)
    outbound_shipping = outbound_shipping or Money.zero(cur)
    fee = marketplace_fee(item, schedule, shipping_charged=shipping_charged,
                          tax_collected=tax_collected)
    # Tax collected is remitted, never ours, so it is not revenue -- but it is
    # in the fee base, which is precisely why eBay's fee is larger than 13.25%
    # of the item price.
    return item + shipping_charged - fee["total"] - outbound_shipping
