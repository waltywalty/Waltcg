"""MODEL C -- crossover_ev.

Two paths that are never merged, because their risk shapes are not comparable
and averaging them produces a number that describes neither.

    path='psa_crossover'
        A minimum grade is specified. If PSA will not award it, the card comes
        back in its original BGS slab, untouched. There is NO GRADE RISK on
        this path: the downside is fees, shipping, and the card being locked
        up for the turnaround. That is a real cost and it is modelled, but it
        is not the same species of risk as losing the grade.

    path='crack_resubmit'
        The slab is destroyed before submission. Full grade risk applies, and
        so does a non-zero probability of damaging the card while cracking it.
        A crossover model that omits crack damage is describing a different,
        safer activity than the one you are actually doing.

Subgrade heuristics live in config/crossover_rules.yaml with their source and
sample size attached. The structural claims -- balanced 9.5s cross well, a
single 9.0 on corners or surface is a hard red flag, centering is where PSA is
most forgiving -- are encoded as rule selection; the probabilities attached to
them must be supplied and sourced.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .breakeven import annualised, net_proceeds, solve_break_even_p
from .config import MISSING, Config, business_days_to_calendar
from .money import Money
from .results import CostBreakdown, EVResult, GradeDistribution, Provenance, Refusal

MODEL = "crossover_ev"

PATH_PSA_CROSSOVER = "psa_crossover"
PATH_CRACK_RESUBMIT = "crack_resubmit"
PATHS = (PATH_PSA_CROSSOVER, PATH_CRACK_RESUBMIT)

HARD_RED_FLAG = ("corners", "surface")


def select_rule(cfg: Config, bgs_overall, subgrades: dict):
    """Pick the crossover rule matching this slab. Structure, not probability.

    subgrades maps category -> subgrade, e.g.
        {"centering": 9.5, "corners": 9.0, "edges": 9.5, "surface": 9.5}
    """
    rules = cfg.crossover_rules.get("rules") or []
    overall = Decimal(str(bgs_overall))
    subs = {k: Decimal(str(v)) for k, v in (subgrades or {}).items()}
    nines = [k for k, v in subs.items() if v <= Decimal("9.0")]

    def match(rule):
        m = rule.get("match") or {}
        if "bgs_overall" in m and Decimal(str(m["bgs_overall"])) != overall:
            return False
        if "min_subgrade" in m:
            if not subs or min(subs.values()) < Decimal(str(m["min_subgrade"])):
                return False
        if "single_9_category" in m:
            if len(nines) != 1 or nines[0] != m["single_9_category"]:
                return False
        if "count_9_subgrades_min" in m and len(nines) < int(m["count_9_subgrades_min"]):
            return False
        return True

    # Most specific first: subgrade-pattern rules before the catch-alls.
    def specificity(rule):
        return len(rule.get("match") or {})

    for rule in sorted(rules, key=specificity, reverse=True):
        if match(rule):
            return rule
    return None


def red_flags(subgrades: dict) -> list:
    subs = {k: Decimal(str(v)) for k, v in (subgrades or {}).items()}
    return [k for k in HARD_RED_FLAG if subs.get(k, Decimal(99)) <= Decimal("9.0")]


def required_paths(path: str, rule_id: str, grader: str, tier: str, venue: str,
                   route: Optional[str] = None) -> list:
    # Freight lives on the route once routes are configured; the flat
    # submission_costs pair is the legacy path and stays null.
    freight = ([f"grading.routes.{route}.outbound_shipping",
                f"grading.routes.{route}.return_shipping_insured",
                f"grading.routes.{route}.currency"] if route else
               ["grading.submission_costs.inbound_shipping",
                "grading.submission_costs.return_shipping_insured"])
    base = freight + [
        "grading.meta.currency",
        f"grading.graders.{grader}.tiers.{tier}.fee",
        f"grading.graders.{grader}.tiers.{tier}.turnaround_business_days",
        f"grading.graders.{grader}.tiers.{tier}.availability",

        "grading.submission_costs.default_batch_size",
        f"fees.marketplaces.{venue}.final_value_fee_pct",
        f"fees.marketplaces.{venue}.payment_pct",
        f"fees.marketplaces.{venue}.payment_fixed",
        f"fees.marketplaces.{venue}.currency",
        "fees.region_defaults.default_days_to_sell",
        "crossover_rules.meta.sample_size",
    ]
    if path == PATH_CRACK_RESUBMIT:
        base += ["crossover_rules.crack_and_resubmit.p_damage_during_crack",
                 "crossover_rules.crack_and_resubmit.damage_residual_value_pct"]
    else:
        base += ["crossover_rules.psa_crossover_path.fee_charged_on_failure"]
    return base


def _rule_prob(cfg: Config, rule: dict, key: str, rule_index: int) -> Decimal:
    v = rule.get(key)
    if v is None:
        raise KeyError(f"crossover_rules.rules[{rule_index}].{key}")
    return Decimal(str(v))


def crossover_ev(
    card_uid: str,
    path: str,
    slab_market_value: Money,
    comps_by_grade: dict,
    *,
    cfg: Config,
    bgs_overall,
    subgrades: dict,
    minimum_grade: str = "10",
    grader: str = "PSA",
    tier: str = "regular",
    venue: str = "ebay",
    route: Optional[str] = None,
    route_fx=None,
    outbound_shipping: Optional[Money] = None,
    batch_size: Optional[int] = None,
    days_to_sell: Optional[int] = None,
):
    if cfg.get("grading.import_charges") is not MISSING and not route:
        return Refusal(
            MODEL, "no grading route supplied",
            "import charges are configured; a crossover ships the slab abroad "
            "and brings it back, so the route decides whether the return leg "
            "is charged.", missing=["route"], subject=card_uid)

    if path not in PATHS:
        return Refusal(MODEL, "unknown path",
                       f"path must be one of {PATHS}; these are never merged",
                       subject=card_uid)
    if not isinstance(slab_market_value, Money):
        raise TypeError("slab_market_value must be Money, not a bare number")

    rule = select_rule(cfg, bgs_overall, subgrades)
    if rule is None:
        return Refusal(MODEL, "no matching crossover rule",
                       f"BGS {bgs_overall} with subgrades {subgrades} matches no rule in "
                       "config/crossover_rules.yaml", subject=card_uid)
    rule_id = rule.get("id", "?")
    rule_index = (cfg.crossover_rules.get("rules") or []).index(rule)

    cfg.require(required_paths(path, rule_id, grader, tier, venue, route=route),
                context=f"{MODEL} [{path}] for {card_uid}")
    for key in ("p_psa_10", "p_psa_9", "p_psa_below_9", "source"):
        if rule.get(key) is None:
            return Refusal(MODEL, "crossover rule incomplete",
                           f"rule {rule_id!r} has no {key}; an unsourced crossover "
                           "probability is a guess and will not be used",
                           missing=[f"crossover_rules.rules[{rule_index}].{key}"],
                           subject=card_uid)

    currency = cfg.get("grading.meta.currency")
    if slab_market_value.currency != currency:
        return Refusal(MODEL, "currency mismatch",
                       f"slab value is {slab_market_value.currency}, working currency "
                       f"is {currency}", subject=card_uid)

    p10 = _rule_prob(cfg, rule, "p_psa_10", rule_index)
    p9 = _rule_prob(cfg, rule, "p_psa_9", rule_index)
    pbelow = _rule_prob(cfg, rule, "p_psa_below_9", rule_index)
    rule_total = p10 + p9 + pbelow
    if abs(rule_total - Decimal(1)) > Decimal("1e-9"):
        return Refusal(MODEL, "crossover rule probabilities do not sum to 1",
                       f"rule {rule_id!r} sums to {rule_total}", subject=card_uid)
    flags = red_flags(subgrades)

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
        ret = Money(str(cfg.decimal(
            "grading.submission_costs.return_shipping_insured")), currency) / batch

    fvf = cfg.decimal(f"fees.marketplaces.{venue}.final_value_fee_pct")
    pay_pct = cfg.decimal(f"fees.marketplaces.{venue}.payment_pct")
    fixed = Money(str(cfg.decimal(f"fees.marketplaces.{venue}.payment_fixed")), currency)
    ship_out = outbound_shipping or Money.zero(currency)

    def proceeds_for(label):
        comp = comps_by_grade.get(label)
        if comp is None:
            return None
        if not isinstance(comp, Money):
            raise TypeError(f"comp for {label} must be Money")
        return net_proceeds(comp, fvf, pay_pct, fixed, ship_out)

    costs = CostBreakdown(
        acquisition=slab_market_value, tax=Money.zero(currency),
        inbound_shipping=inbound, supplies=Money.zero(currency),
        grading_fee=fee, return_shipping=ret)
    total_cost = costs.total()

    notes = [f"rule {rule_id!r}", f"source: {rule.get('source')}"]
    if flags:
        notes.append("HARD RED FLAG: 9.0 subgrade on " + ", ".join(flags)
                     + " -- PSA is least forgiving on these two categories")
    if Decimal(str((subgrades or {}).get("centering", 99))) <= Decimal("9.0"):
        notes.append("9.0 centering only: PSA is most forgiving here, so this is "
                     "materially less damaging than a corners or surface 9.0")

    if path == PATH_PSA_CROSSOVER:
        # No grade risk. Either it crosses at or above the minimum, or the
        # original slab comes back and the only loss is fees, shipping and
        # the lockup.
        p_success = p10 if str(minimum_grade) == "10" else p10 + p9
        p_fail = Decimal(1) - p_success
        success_proceeds = proceeds_for(str(minimum_grade))
        if success_proceeds is None:
            return Refusal(MODEL, "missing comp",
                           f"no comp for the minimum grade {minimum_grade!r}",
                           subject=card_uid)
        # On failure the card is still the original slab, sellable as such.
        held_proceeds = proceeds_for("original_slab")
        if held_proceeds is None:
            held_proceeds = net_proceeds(slab_market_value, fvf, pay_pct, fixed, ship_out)
            notes.append("failure branch valued at the original slab's market value")

        fail_fee = Money.zero(currency)
        if cfg.get("crossover_rules.psa_crossover_path.fee_charged_on_failure") in (
                True, "true", "yes"):
            fail_fee = Money(str(cfg.decimal(
                "crossover_rules.psa_crossover_path.fee_on_failure")), currency)

        probs = {str(minimum_grade): p_success, "returned_in_original_slab": p_fail}
        proceeds = {str(minimum_grade): success_proceeds,
                    "returned_in_original_slab": held_proceeds - fail_fee}
        branches = [
            {"branch": f"crossed_to_{minimum_grade}", "p": str(p_success),
             "net_proceeds": success_proceeds.as_dict()},
            {"branch": "returned_in_original_slab", "p": str(p_fail),
             "net_proceeds": (held_proceeds - fail_fee).as_dict(),
             "note": "no grade risk on this path: the original slab is returned intact; "
                     "the loss is fees, shipping and lockup only"},
        ]
    else:
        p_damage = cfg.decimal("crossover_rules.crack_and_resubmit.p_damage_during_crack")
        if p_damage <= 0:
            return Refusal(MODEL, "invalid crack damage probability",
                           "p_damage_during_crack must be greater than zero on the "
                           "crack_resubmit path; cracking a slab is not risk-free",
                           subject=card_uid)
        residual_pct = cfg.decimal(
            "crossover_rules.crack_and_resubmit.damage_residual_value_pct")
        # Damage is resolved first; grade probabilities apply to survivors.
        survive = Decimal(1) - p_damage
        probs = {"10": p10 * survive, "9": p9 * survive,
                 "below_9": pbelow * survive, "damaged": p_damage}
        proceeds = {}
        for label in ("10", "9", "below_9"):
            pr = proceeds_for(label)
            if pr is None:
                return Refusal(MODEL, "missing comp",
                               f"no comp for branch {label!r}; the crack_resubmit path "
                               "carries full grade risk and every branch must be priced",
                               subject=card_uid)
            proceeds[label] = pr
        proceeds["damaged"] = net_proceeds(slab_market_value * residual_pct,
                                           fvf, pay_pct, fixed, ship_out)
        branches = [{"branch": k, "p": str(probs[k]),
                     "net_proceeds": proceeds[k].as_dict()} for k in probs]
        notes.append(f"crack damage probability {p_damage} applied before grade "
                     "probabilities; damaged cards retain "
                     f"{residual_pct} of raw value")

    # Import charges, per branch. What customs values is the object that comes
    # back -- a crossed slab, the original slab, or a damaged card -- so the
    # declared value differs by branch just as the proceeds do.
    declared = {}
    for label in proceeds:
        if label == "returned_in_original_slab":
            declared[label] = slab_market_value
        elif label == "damaged":
            # residual_pct exists only on the crack_resubmit path, which is the
            # only path with a damaged branch.
            declared[label] = slab_market_value * locals().get(
                "residual_pct", Decimal(0))
        else:
            declared[label] = comps_by_grade.get(label, slab_market_value)

    import_rule, import_applies, (import_note, _facility) = (
        resolve_rule(cfg, route) if route else (None, False, ("no route", None)))
    relief = cfg.get("assumptions.relief_scenario.current_value", "relief_none")
    import_charges = {}
    if import_applies:
        return_freight = ret
        try:
            import_charges = import_charge_by_grade(
                proceeds, declared, rule=import_rule, relief=relief,
                return_freight=return_freight, value_added=fee + return_freight)
        except ImportChargeError as e:
            return Refusal(MODEL, "import charge rule unusable", str(e),
                           missing=["grading.import_charges"], subject=card_uid)
        proceeds = {g: n - import_charges[g] for g, n in proceeds.items()}

    ev = Money.zero(currency)
    for label, p in probs.items():
        ev = ev + (proceeds[label] * p)
    ev = ev - total_cost
    roi = (ev.amount / total_cost.amount) if total_cost.amount != 0 else None

    turn_bd = (cfg.get(f"grading.graders.{grader}.tiers.{tier}.turnaround_observed_days", None)
               or cfg.get(f"grading.graders.{grader}.tiers.{tier}.turnaround_business_days"))
    horizon = business_days_to_calendar(turn_bd) + int(
        days_to_sell if days_to_sell is not None
        else cfg.get("fees.region_defaults.default_days_to_sell"))

    target = str(minimum_grade) if path == PATH_PSA_CROSSOVER else "10"
    be = solve_break_even_p(target, proceeds, probs, total_cost)

    return EVResult(
        import_charges={
            "applies": import_applies, "route": route, "note": import_note,
            "relief_scenario": relief if import_applies else None,
            "expected": (summarise(import_charges, probs, currency).as_dict()
                         if import_applies else None),
            "by_grade": {g: c.as_dict() for g, c in import_charges.items()},
            "effective_rate_on_goods": (str(effective_rate(import_rule))
                                        if import_applies else None),
        },
        model=f"{MODEL}[{path}]", subject=card_uid,
        break_even_p_target=be["p"],
        break_even_attainable=bool(be.get("attainable")),
        break_even_note=be.get("reason", ""), target_grade=target,
        modelled_p_target=probs.get(target),
        ev=ev, roi=roi, annualised_roi=(annualised(roi, horizon) if roi is not None else None),
        horizon_days=horizon, costs=costs, branches=branches,
        grade_distribution=GradeDistribution(probs=probs, prior_used=f"rule {rule_id}",
                                             notes=notes),
        downside_case=branches[-1],
        provenance=Provenance(
            as_of=str(cfg.today),
            sources=[f"config/crossover_rules.yaml::{rule_id}",
                     f"config/grading.yaml::{grader}.{tier}"],
            warnings=[str(w) for w in cfg.staleness_warnings()],
            notes=notes + [be.get("reason") or ""]),
    )
