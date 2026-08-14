"""Result and refusal types shared by all five models.

A model returns one of two things: a result, or a Refusal. A Refusal is a
first-class outcome, not an error -- "there is not enough evidence to answer
this" is a legitimate and frequently correct answer, and it must survive into
the dashboard rather than being flattened into a zero or a None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from .money import Money


@dataclass
class Refusal:
    """The model declines to answer, and says exactly why."""

    model: str
    reason: str
    detail: str = ""
    missing: list = field(default_factory=list)
    subject: Optional[str] = None

    ok = False

    def __bool__(self):
        return False

    def as_dict(self):
        return {"ok": False, "model": self.model, "reason": self.reason,
                "detail": self.detail, "missing": list(self.missing),
                "subject": self.subject}

    def __str__(self):
        base = f"REFUSED [{self.model}] {self.reason}"
        return base + (f" -- {self.detail}" if self.detail else "")


@dataclass
class Provenance:
    """Where the numbers came from, carried on every result."""

    as_of: str
    sources: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def as_dict(self):
        return {"as_of": self.as_of, "sources": list(self.sources),
                "warnings": [str(w) for w in self.warnings], "notes": list(self.notes)}


@dataclass
class GradeDistribution:
    """A probability distribution over grades, with its own provenance."""

    probs: dict                      # grade label -> Decimal
    prior_used: str = ""             # which prior produced this
    effective_sample_size: Optional[Decimal] = None
    haircut_applied: Optional[Decimal] = None
    notes: list = field(default_factory=list)

    def p(self, grade) -> Decimal:
        return self.probs.get(str(grade), Decimal(0))

    def total(self) -> Decimal:
        return sum(self.probs.values(), Decimal(0))

    def as_dict(self):
        return {"probs": {k: str(v) for k, v in self.probs.items()},
                "prior_used": self.prior_used,
                "effective_sample_size": (None if self.effective_sample_size is None
                                          else str(self.effective_sample_size)),
                "haircut_applied": (None if self.haircut_applied is None
                                    else str(self.haircut_applied)),
                "notes": list(self.notes)}


@dataclass
class CostBreakdown:
    """Every cost line, each a Money. No bare floats anywhere."""

    acquisition: Money
    tax: Money
    inbound_shipping: Money
    supplies: Money
    grading_fee: Money
    return_shipping: Money

    def total(self) -> Money:
        return (self.acquisition + self.tax + self.inbound_shipping
                + self.supplies + self.grading_fee + self.return_shipping)

    def as_dict(self):
        return {k: getattr(self, k).as_dict() for k in
                ("acquisition", "tax", "inbound_shipping", "supplies",
                 "grading_fee", "return_shipping")} | {"total": self.total().as_dict()}


@dataclass
class EVResult:
    """Headline output. The break-even probability leads; point EV follows."""

    model: str
    subject: str

    # THE headline. Probability of the target grade at which EV == 0.
    break_even_p_target: Optional[Decimal]
    target_grade: str
    modelled_p_target: Optional[Decimal] = None
    # AUDIT_PROTOCOL Layer 1: break_even_p is in [0,1] or the result says
    # plainly that no probability works. An out-of-range number on its own is
    # not an answer.
    break_even_attainable: bool = True
    break_even_note: str = ""

    ev: Optional[Money] = None
    roi: Optional[Decimal] = None
    annualised_roi: Optional[Decimal] = None
    horizon_days: Optional[int] = None

    costs: Optional[CostBreakdown] = None
    # Import charges on the return leg. Reported rather than folded into
    # `costs`, because under relief_none the charge varies by realised grade
    # and is already deducted from each branch's proceeds -- adding it to the
    # cost total as well would double-count it. `applies: False` on a domestic
    # route is a result, not an absence: it is the main reason to prefer one.
    import_charges: Optional[dict] = None
    downside_case: Optional[dict] = None
    grade_distribution: Optional[GradeDistribution] = None
    branches: list = field(default_factory=list)
    provenance: Optional[Provenance] = None

    ok = True

    def __bool__(self):
        return True

    @property
    def margin(self) -> Optional[Decimal]:
        """Modelled probability minus the probability needed to break even.

        Positive means the submission clears its own bar. This is the number
        to act on -- not the point EV, because the probability is the
        uncertain input and the EV inherits all of that uncertainty.
        """
        if self.break_even_p_target is None or self.modelled_p_target is None:
            return None
        return self.modelled_p_target - self.break_even_p_target

    def as_dict(self):
        return {
            "ok": True, "model": self.model, "subject": self.subject,
            "break_even_p_target": (None if self.break_even_p_target is None
                                    else str(self.break_even_p_target)),
            "target_grade": self.target_grade,
            "modelled_p_target": (None if self.modelled_p_target is None
                                  else str(self.modelled_p_target)),
            "break_even_attainable": self.break_even_attainable,
            "break_even_note": self.break_even_note,
            "margin": None if self.margin is None else str(self.margin),
            "ev": None if self.ev is None else self.ev.as_dict(),
            "roi": None if self.roi is None else str(self.roi),
            "annualised_roi": (None if self.annualised_roi is None
                               else str(self.annualised_roi)),
            "horizon_days": self.horizon_days,
            "costs": None if self.costs is None else self.costs.as_dict(),
            "downside_case": self.downside_case,
            "grade_distribution": (None if self.grade_distribution is None
                                   else self.grade_distribution.as_dict()),
            "branches": self.branches,
            "provenance": None if self.provenance is None else self.provenance.as_dict(),
        }


@dataclass
class ScreenRow:
    """One row of Model D's cross-sectional screen."""

    card_uid: str
    residual: Decimal
    fitted: Decimal
    observed: Decimal
    sample_size_p10: int
    sample_size_p9: int
    pop9: int
    pop10: int
    suppressed: bool = False
    suppression_reason: str = ""
    # Break-even threshold for the screen (GOAL D2: every calculator emits a
    # threshold, not only a point estimate). The residual is the point
    # estimate; these say what the price would have to BE for the signal to
    # disappear, which is the number you act on.
    break_even_p10_median: Optional[Decimal] = None   # P10 price at residual 0
    pct_move_to_fair: Optional[Decimal] = None        # % move from observed to fair

    def as_dict(self):
        return {"card_uid": self.card_uid, "residual": str(self.residual),
                "fitted": str(self.fitted), "observed": str(self.observed),
                "sample_size_p10": self.sample_size_p10,
                "sample_size_p9": self.sample_size_p9,
                "pop9": self.pop9, "pop10": self.pop10,
                "suppressed": self.suppressed,
                "suppression_reason": self.suppression_reason,
                "break_even_p10_median": (None if self.break_even_p10_median is None
                                          else str(self.break_even_p10_median)),
                "pct_move_to_fair": (None if self.pct_move_to_fair is None
                                     else str(self.pct_move_to_fair))}
