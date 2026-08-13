"""Grade distributions from population reports, with honest shrinkage.

A single card's population report is a small sample. Read literally, a card
with 3 tens out of 4 graded implies a 75% gem rate, which is nonsense. The fix
is empirical-Bayes shrinkage toward the set-level distribution: the card's own
counts are combined with a prior worth `prior_strength` pseudo-observations
drawn from its set.

Then a second, separate correction. Population reports count cards people
CHOSE to submit, after pre-screening. P(10 | submitted) is therefore higher
than P(10 | this card in my hands). The submission-selection haircut scales
P(10) down and reassigns the removed mass to 9 -- a card that would have been
a 10 in the population's selected pool is, in the wild, most often a 9.

Both steps are recorded on the returned distribution: which prior was used and
its effective sample size. Nothing here is learned or fitted from history; it
is arithmetic on the inputs you pass.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from .results import GradeDistribution, Refusal

MODEL = "grade_prior"


def _as_counts(pop) -> dict:
    out = {}
    for g, n in (pop or {}).items():
        out[str(g)] = Decimal(str(n))
    return out


def shrunk_grade_distribution(
    card_pop: Optional[dict],
    set_pop: Optional[dict],
    prior_strength,
    selection_haircut,
    min_card_pop_for_own_prior,
    target_grade: str = "10",
    adjacent_grade: str = "9",
    subject: str = "",
):
    """Beta-Binomial shrinkage, then the submission-selection haircut.

    Returns a GradeDistribution, or a Refusal when there is nothing to stand
    on. Guessing a grade distribution is how a break-even probability becomes
    fiction, so absent population data is refused rather than filled in.
    """
    card = _as_counts(card_pop)
    sets = _as_counts(set_pop)
    card_total = sum(card.values(), Decimal(0))
    set_total = sum(sets.values(), Decimal(0))

    if set_total <= 0 and card_total <= 0:
        return Refusal(MODEL, "no population data",
                       "neither the card nor its set has a population distribution; "
                       "a grade prior cannot be invented", subject=subject)

    prior_strength = Decimal(str(prior_strength))
    haircut = Decimal(str(selection_haircut))
    min_own = Decimal(str(min_card_pop_for_own_prior))
    notes = []

    if set_total > 0:
        set_p = {g: n / set_total for g, n in sets.items()}
    else:
        set_p = None

    if set_p is None:
        # Card data only. Usable, but say so loudly: there is no prior to
        # shrink toward, so a thin population goes straight through.
        probs = {g: n / card_total for g, n in card.items()}
        prior_used = "card population only (no set-level distribution available)"
        ess = card_total
        notes.append("no set-level prior; card counts used unshrunk")
    elif card_total < min_own:
        probs = dict(set_p)
        prior_used = (f"set-level distribution (card population {card_total} is below "
                      f"the {min_own} threshold for using its own counts)")
        ess = prior_strength
        notes.append("card population too thin to inform its own prior")
    else:
        grades = set(card) | set(set_p)
        denom = card_total + prior_strength
        probs = {}
        for g in grades:
            probs[g] = (card.get(g, Decimal(0))
                        + prior_strength * set_p.get(g, Decimal(0))) / denom
        prior_used = (f"empirical-Bayes shrinkage toward set distribution "
                      f"(prior strength {prior_strength} pseudo-cards)")
        ess = card_total + prior_strength

    # Submission-selection haircut on the target grade only.
    haircut_applied = None
    if target_grade in probs and haircut != 1:
        before = probs[target_grade]
        after = before * haircut
        moved = before - after
        probs[target_grade] = after
        probs[adjacent_grade] = probs.get(adjacent_grade, Decimal(0)) + moved
        haircut_applied = haircut
        notes.append(
            f"submission-selection haircut {haircut} applied to P({target_grade}): "
            f"{before} -> {after}, {moved} reassigned to P({adjacent_grade})")

    return GradeDistribution(probs=probs, prior_used=prior_used,
                             effective_sample_size=ess,
                             haircut_applied=haircut_applied, notes=notes)


def normalise(probs: dict) -> dict:
    total = sum(probs.values(), Decimal(0))
    if total <= 0:
        return dict(probs)
    return {g: p / total for g, p in probs.items()}
