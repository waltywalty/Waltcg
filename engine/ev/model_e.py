"""MODEL E -- sealed_ev.

Three numbers, compared:

    1. Pull-rate-weighted expected singles value per pack and per box
    2. The box's market price
    3. What the singles would cost to buy outright

Ripping only makes sense when (1) beats (2), and buying singles only makes
sense when (3) beats (1). Most of the time (3) wins, which is the useful and
unglamorous finding.

Every result is stamped low-confidence and that flag cannot be turned off.
Community pull-rate data is self-reported, biased toward people who hit
something worth posting, and usually quoted without a denominator. The model
will still compute -- the comparison is worth having -- but it refuses to let
the output be read as though the pull rates were measured.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .config import Config
from .money import Money
from .results import Provenance, Refusal

MODEL = "sealed_ev"


def sealed_ev(
    product_id: str,
    *,
    cfg: Config,
    box_market_price: Money,
    singles_basket_cost: Optional[Money] = None,
    value_by_rarity: Optional[dict] = None,
    venue: str = "ebay",
):
    """Expected singles value of a sealed product against its market price.

    `value_by_rarity` maps rarity_band -> Money, the expected sale value of one
    hit in that band. Pull rates come from
    assumptions.pull_rate_estimates.current_value[product_id].
    """
    if not isinstance(box_market_price, Money):
        raise TypeError("box_market_price must be Money, not a bare number")

    root = f"assumptions.pull_rate_estimates.current_value.{product_id}"
    cfg.require([
        "grading.meta.currency",
        f"{root}.packs_per_box",
        f"{root}.cards_per_pack",
        f"{root}.rates",
        f"{root}.source",
        f"{root}.sample_size",
    ], context=f"{MODEL} for {product_id}")

    currency = cfg.get("grading.meta.currency")
    if box_market_price.currency != currency:
        return Refusal(MODEL, "currency mismatch",
                       f"box price is {box_market_price.currency}, working currency is "
                       f"{currency}", subject=product_id)

    packs = int(cfg.get(f"{root}.packs_per_box"))
    rates = cfg.get(f"{root}.rates") or {}
    rates = {k: v for k, v in rates.items() if not str(k).startswith("_")}
    if not rates:
        return Refusal(MODEL, "no pull rates", f"{root}.rates is empty",
                       missing=[f"{root}.rates"], subject=product_id)

    missing_rates = [k for k, v in rates.items() if v is None]
    if missing_rates:
        return Refusal(MODEL, "incomplete pull rates",
                       "every rarity band needs a rate",
                       missing=[f"{root}.rates.{k}" for k in missing_rates],
                       subject=product_id)

    value_by_rarity = value_by_rarity or {}
    missing_values = [k for k in rates if k not in value_by_rarity]
    if missing_values:
        return Refusal(MODEL, "missing hit values",
                       f"no expected value supplied for: {', '.join(missing_values)}",
                       subject=product_id)

    total_rate = sum(Decimal(str(v)) for v in rates.values())
    if total_rate > 1:
        return Refusal(MODEL, "inconsistent pull rates",
                       f"rates across mutually exclusive bands sum to {total_rate} > 1",
                       subject=product_id)

    per_pack = Money.zero(currency)
    contributions = {}
    for band, rate in rates.items():
        v = value_by_rarity[band]
        if not isinstance(v, Money):
            raise TypeError(f"value for band {band} must be Money")
        contrib = v * Decimal(str(rate))
        contributions[band] = contrib.as_dict()
        per_pack = per_pack + contrib

    per_box = per_pack * packs
    rip_vs_buy = per_box - box_market_price

    # Break-even threshold (GOAL D2: every calculator emits one, not only a
    # point estimate). The pull rate is the least trustworthy input here, so
    # invert on it: what rate would the highest-value band need for ripping to
    # match the box price? Linear, so closed-form.
    #     packs * [ p*V_top + sum(other rate_i * V_i) ] = box_price
    #  => p* = (box_price/packs - sum_other) / V_top
    top_band = max(rates, key=lambda b: value_by_rarity[b].amount)
    v_top = value_by_rarity[top_band]
    others = Money.zero(currency)
    for band, rate in rates.items():
        if band != top_band:
            others = others + (value_by_rarity[band] * Decimal(str(rate)))
    if v_top.amount > 0:
        be_rate = ((box_market_price.amount / Decimal(packs)) - others.amount) / v_top.amount
        modelled_rate = Decimal(str(rates[top_band]))
        break_even = {
            "band": top_band,
            "break_even_pull_rate": str(be_rate),
            "modelled_pull_rate": str(modelled_rate),
            "margin": str(modelled_rate - be_rate),
            "attainable": bool(0 <= be_rate <= 1),
            "definition": (f"pull rate for {top_band} at which expected singles value per "
                           "box equals the box market price, holding the other bands fixed"),
        }
    else:
        break_even = {"band": top_band, "break_even_pull_rate": None,
                      "attainable": False,
                      "definition": "top band has no value; no rate makes ripping pay"}

    singles_cmp = None
    if singles_basket_cost is not None:
        if not isinstance(singles_basket_cost, Money):
            raise TypeError("singles_basket_cost must be Money")
        singles_cmp = {
            "singles_basket_cost": singles_basket_cost.as_dict(),
            "box_cheaper_than_singles": (box_market_price < singles_basket_cost),
            "delta": (singles_basket_cost - box_market_price).as_dict(),
        }

    return {
        "model": MODEL,
        "ok": True,
        "subject": product_id,
        "confidence": "low",
        "confidence_immutable": True,
        "confidence_reason": (
            "pull rates are community-reported: self-selected, biased toward posted "
            "hits, and usually quoted without a denominator. Treat the ranking as "
            "indicative and the magnitude as unreliable."),
        "packs_per_box": packs,
        "expected_singles_value_per_pack": per_pack.as_dict(),
        "expected_singles_value_per_box": per_box.as_dict(),
        "box_market_price": box_market_price.as_dict(),
        "rip_minus_box_price": rip_vs_buy.as_dict(),
        "break_even": break_even,
        "ripping_beats_buying_box": rip_vs_buy.amount > 0,
        "contribution_by_band": contributions,
        "singles_comparison": singles_cmp,
        "pull_rate_source": cfg.get(f"{root}.source"),
        "pull_rate_sample_size": cfg.get(f"{root}.sample_size"),
        "provenance": Provenance(
            as_of=str(cfg.today),
            sources=[f"contracts/assumptions.json::pull_rate_estimates.by_product.{product_id}"],
            warnings=[str(w) for w in cfg.staleness_warnings()]
            + ["pull rates are low-confidence by construction"],
            notes=[f"rates sum to {total_rate} across {len(rates)} bands"]).as_dict(),
    }
