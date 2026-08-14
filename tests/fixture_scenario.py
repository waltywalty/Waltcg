"""The one scenario every fixture is computed under.

The fixtures are synthetic -- `_fixture: true`, and no provider data ever
reaches them. But synthetic must not mean arbitrary. A fixture with invented
numbers teaches a designer the wrong *relationships*: if the ladder says a PSA 9
sells for 320 while the Grading Lab says a 224.54 submission loses 96.20 when it
comes back a 9, then whoever is tuning visual weight is tuning it against a
world where grading a card that doubles in value is a loss. That lesson survives
into the built app long after the numbers are replaced.

So: real structure, declared unknowns.

**Real, from dated config.** The PSA Regular fee (79.99), its 60 business day
turnaround, and eBay's whole banded fee schedule -- 13.25% on item plus shipping
plus tax, tiered fixed fees, the discount band at 1000 -- come from
`config/*.yaml` exactly as shipped. Fee arithmetic in the fixtures is therefore
the real fee arithmetic, provisional sourcing and all.

**Declared, because config ships them null.** Every value below is null in the
repository on purpose: the engine must refuse rather than default while a
required number is unknown, and it does. A fixture still needs *some* number to
exist at all, so this module states the ones it used, in one place, with the
reason each was chosen. They are illustrative. None of them is a claim about the
world, and none is a substitute for filling in `config/`.

Changing a number here changes every fixture, which is the point: run
`tests/regenerate_fixtures.py` and the derived figures move together.
"""

from __future__ import annotations

import copy
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ev import Config  # noqa: E402

# The date every fixture is generated as of. Fixed, so a fixture does not
# change meaning tomorrow.
AS_OF = _dt.date(2026, 8, 13)
GENERATED_AT = "2026-08-13T09:00:00Z"

# --------------------------------------------------------------- the unknowns

# Supplies, batch size and route freight are now REAL config (2026-08-14), so
# the scenario no longer supplies them. What is left here is only what config
# still ships null.
SUBMISSION_COSTS = {}

ROUTE = "psa_us"          # the fixtures price a US submission from the UK
GBPUSD = "1.27"           # illustrative, for the GBP-priced domestic route

ASSUMPTIONS = {
    # Pop-report gem rates are biased upward because people submit their best
    # copies. 0.80 moves a fifth of the modelled P(10) mass down to 9. It is a
    # guess until calibrated against my own submission results, and CLAUDE.md
    # lists it as known-fragile.
    "submission_selection_haircut": 0.80,
    # No sales tax on the illustrative acquisition.

    # Beta-Binomial prior strength, in pseudo-cards, for shrinking a card's
    # population toward its set distribution.
    "empirical_bayes_prior_strength": 20,
    # Below this graded population a card uses the set prior instead of its own.
    "empirical_bayes_min_card_pop": 10,
    "min_comp_sample_size": 5,
    "days_to_sell": 30,
}

DAYS_TO_SELL = 30          # fees.region_defaults.default_days_to_sell


def scenario_config(today=AS_OF) -> Config:
    """Shipped config with only the nulls filled, from the block above."""
    cfg = Config.load(today=today)
    cfg = Config(grading=copy.deepcopy(cfg.grading), fees=copy.deepcopy(cfg.fees),
                 assumptions=copy.deepcopy(cfg.assumptions),
                 crossover_rules=copy.deepcopy(cfg.crossover_rules), today=today)

    if SUBMISSION_COSTS:
        cfg.grading.setdefault("submission_costs", {}).update(SUBMISSION_COSTS)
    for key, value in ASSUMPTIONS.items():
        cfg.assumptions.setdefault(key, {})["current_value"] = value
    for key, value in REGRADE_ASSUMPTIONS.items():
        cfg.assumptions.setdefault(key, {})["current_value"] = value

    # Guard the guard: if config/ ever stops shipping the real PSA fee or the
    # real eBay schedule, the fixtures would quietly start describing a
    # different world while every test still passed.
    assert cfg.get("grading.graders.PSA.tiers.regular.fee") == 79.99, \
        "fixtures assume the shipped PSA Regular fee"
    assert cfg.get("fees.marketplaces.ebay.fee_schedule.base") == \
        "item_plus_shipping_plus_tax", "fixtures assume the shipped eBay schedule"
    assert cfg.get("grading.import_charges.home_jurisdiction") == "GB"
    return cfg


def fx_gbp_usd():
    """Illustrative rate for the GBP-priced domestic route. Declared, dated and
    not a market observation -- the engine refuses to convert without one
    rather than assuming parity."""
    from engine.ev.money import FxRate
    return FxRate(base="GBP", quote="USD", rate=GBPUSD, as_of=str(AS_OF),
                  source="illustrative, fixture scenario")


# ------------------------------------------------------------ the worked card
#
# One card carries the arithmetic across three screens, so the screens have to
# agree about it. card_detail supplies the ladder; grading_lab prices a
# submission against that same ladder; signals leads with the break-even
# probability that falls out of it.

WORKED_CARD = "pkmn:sv3:223/197:sir:EN"

# Ladder observations. These are the *inputs*: prices observed, population
# observed. Everything else about this card in every fixture is derived.
#
# These were the incoherent half. The shipped ladder had the PSA 9 at 320
# against a 224.54 all-in cost, which makes the submission profitable on the 9
# alone -- break-even P(10) solves to zero, and the Grading Lab's whole gauge,
# "what you need against what is likely", has nothing to draw. The Lab's own
# figures (EV -38.40, ROI -0.152, annualised -0.418) describe a different and
# much more typical card, where a 9 sells for roughly what the card cost raw and
# only a 10 pays. Reconciled toward the Lab, because a marginal submission is
# the case the screen exists for; the prices below reproduce its story with
# arithmetic that holds (EV -35.67, ROI -0.158, annualised -0.425).
LADDER_PRICES = {"raw": "140.00", "8": "88.00", "9": "142.00", "10": "540.00"}
LADDER_POP = {"8": 410, "9": 5120, "10": 1830}
SET_POP = {"8": 21000, "9": 240000, "10": 96000}

ACQUISITION = "140.00"     # buy it at the observed raw price
TIER = "regular"
GRADER = "PSA"
VENUE = "ebay"


# ------------------------------------------------- the hand-estimated card
#
# Riftbound has no population source at all, so a grading play on it cannot
# derive a grade distribution -- the probability has to be typed in. This is
# the Grading Lab's second mode ("manual grade estimate") and the case
# estimate_basis: user_estimate exists to mark. It is not a rare path: two of
# the three games and four of the eight combinations land here.

ESTIMATED_CARD = "riftbound:OGN:OGN-042:signature:EN"
ESTIMATED_PRICES = {"raw": "45.00", "8": "30.00", "9": "60.00", "10": "240.00"}
ESTIMATED_ACQUISITION = "45.00"
# My own read, by eye. No population behind any of it.
USER_GRADE_PROBS = {"8": "0.30", "9": "0.55", "10": "0.15"}
USER_PROBS_NOTE = "condition read by eye, centering 60/40"


# ------------------------------------------------------ the regrade play
#
# Model B is FORBIDDEN from using the base gem rate: PSA already examined this
# card and declined a 10, so the base rate double-counts information the grader
# has acted on. It uses a conditional prior instead, and refuses outright
# without a complete condition read (CLAUDE.md non-negotiable 6).
#
# All three values are null in the registry, and all three are guesses here.
# The prior is deliberately conservative: whatever kept the card off a 10 is
# usually still true of it.

REGRADE_ASSUMPTIONS = {
    "regrade_conditional_prior": 0.12,        # P(10 | already slabbed 9)
    "regrade_downgrade_probability": 0.05,    # a different grader, a worse day
    "regrade_condition_adjustments": {
        "centering_pct_ge_60_40": 1.0,
        "centering_pct_ge_55_45": 1.5,
        "corner_flag_clean": 1.2,
        "surface_flag_clean": 1.2,
        "edge_flag_clean": 1.0,
        "any_flag_dirty": 0.5,
    },
}

# The worked card, already in a PSA 9 slab. The 9 is worth what the ladder says
# a 9 is worth -- that intact slab is the opportunity cost of the attempt.
REGRADE_CARD = WORKED_CARD
REGRADE_SLAB_VALUE_9 = LADDER_PRICES["9"]
REGRADE_COMPS = {"10": LADDER_PRICES["10"], "9": LADDER_PRICES["9"],
                 "below_9": LADDER_PRICES["8"]}
# I have actually looked at this card. Model B will not move off its prior
# without this, and will not produce a number at all.
REGRADE_CONDITION_READ = {"centering_pct": "60", "corner_flag": "clean",
                          "surface_flag": "clean", "edge_flag": "clean"}
# A second card in the 9 -> 10 feed that I have NOT looked at. It must refuse.
UNREAD_REGRADE_CARD = "pkmn:sv3:108/108:sar:JP"


# ------------------------------------------------------------- the ledger
#
# The Track Record screen's whole purpose is honesty, so its numbers cannot be
# the invented ones. The brief says "every alert ever fired and what happened",
# and shipping the whole ledger is what makes every rate on the screen
# checkable instead of asserted.
#
# The returns below are DETERMINISTIC AND UNTUNED. They come from an integer
# sequence, not from a target hit rate -- picking numbers to land on a
# flattering 52% would be the same failure as the invented EV, one layer up.

LEDGER_SIZE = 31
LEDGER_START = _dt.date(2026, 2, 1)
LEDGER_STEP_DAYS = 6
HORIZONS = (7, 30, 90)


def ledger_fired_on(i):
    return LEDGER_START + _dt.timedelta(days=i * LEDGER_STEP_DAYS)


def ledger_excess(i, horizon):
    """Excess return over the game index, or None if the horizon has not
    elapsed. A 90-day rate resting on fewer alerts than the 7-day one is a
    fact about the ledger, and the screen has to be able to show it."""
    if ledger_fired_on(i) + _dt.timedelta(days=horizon) > AS_OF:
        return None
    h = HORIZONS.index(horizon)
    spread = 400 // (1 + h)
    return (((i * 73 + h * 29) % 101) - 50) / spread


# Alerts cycle through the cards already in the fixture set, so no card appears
# on Track Record that appears nowhere else.
LEDGER_CARDS = [
    ("pkmn:sv3:223/197:sir:EN", "pkmn", "sv3", "223/197", "sir", "EN",
     "Charizard ex", "Special Illustration Rare"),
    ("optcg:OP05:OP05-119:manga_rare:EN", "optcg", "OP05", "OP05-119",
     "manga_rare", "EN", "Monkey.D.Luffy", "Manga Rare"),
    ("riftbound:OGN:OGN-301:overnumbered:EN", "riftbound", "OGN", "OGN-301",
     "overnumbered", "EN", "Jinx", "Overnumbered"),
    ("optcg:OP01:OP01-078:parallel:JP", "optcg", "OP01", "OP01-078",
     "parallel", "JP", "Boa Hancock", "Parallel Rare"),
    ("pkmn:SM-P:070/SM-P:promo:JP", "pkmn", "SM-P", "070/SM-P", "promo", "JP",
     "Yu Nagaba Eevee", "Promo"),
    ("riftbound:VDT:VDT-017:base:EN", "riftbound", "VDT", "VDT-017", "base",
     "EN", "Vendetta", "Base"),
]
LEDGER_PLAYS = ["raw_to_10", "nine_to_10", "crossover", "grade_gap",
                "thin_float", "trending_early"]


# Which grader's slabs the ladder comps describe. The worked card's ladder is
# PSA-priced, so a PSA route matches and a CGC route does not -- and the CGC
# route comparison is still worth running, which is why the mismatch is a flag
# rather than a refusal.
COMPS_GRADER = "PSA"
