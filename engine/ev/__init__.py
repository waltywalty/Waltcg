"""Expected-value models. Five of them, zero learned parameters.

Every model is deterministic given its inputs, and every one is checkable by
hand. Nothing here is fitted from history or persisted between calls; Model D
solves an OLS at call time from the cross-section it is handed, which is
arithmetic, not training.

Two kinds of not-answering, deliberately distinct:

    ConfigIncomplete (raised)  a required config value is null. The engine
                               refuses to compute and names every gap.
    Refusal (returned)         the inputs cannot support an answer -- no
                               condition read, no population data, comps too
                               thin. A legitimate result, not an error.
"""

from .breakeven import annualised, net_proceeds, solve_break_even_p
from .config import Config, ConfigIncomplete, StalenessWarning, business_days_to_calendar
from .grades import shrunk_grade_distribution
from .model_a import raw_to_graded_ev
from .model_b import regrade_9_to_10_ev
from .model_c import crossover_ev
from .model_d import grade_spread_residual
from .model_e import sealed_ev
from .money import FxRate, Money
from .results import (CostBreakdown, EVResult, GradeDistribution, Provenance, Refusal,
                      ScreenRow)

__all__ = [
    "raw_to_graded_ev", "regrade_9_to_10_ev", "crossover_ev",
    "grade_spread_residual", "sealed_ev",
    "Config", "ConfigIncomplete", "StalenessWarning", "business_days_to_calendar",
    "Money", "FxRate", "Refusal", "EVResult", "CostBreakdown", "GradeDistribution",
    "Provenance", "ScreenRow", "shrunk_grade_distribution",
    "solve_break_even_p", "net_proceeds", "annualised",
]
