"""MODEL D -- grade_spread_residual.

A cross-sectional screen. Fit

    log(P10_median / P9_median) ~ log(pop9 / pop10) + rarity + era + game

across comparable cards, then rank by residual. A negative residual means the
10 is cheap relative to what its scarcity implies -- the market has not priced
the gap that the population report says exists.

"Zero learned parameters" holds: nothing is trained and nothing persists. The
coefficients are solved by ordinary least squares from the cross-section you
pass in, at call time, by closed-form normal equations. Same input, same
output, forever, and you can check it by hand on a small case.

Suppression is not optional. A card whose either-grade comp sample is below
`min_sample` in the window is dropped from the fit AND from the output, with
its sample size reported. A screen built on three sales is noise wearing a
suit, and the fastest way to lose money with a model like this is to let a
thin comp masquerade as a signal.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Optional

from .config import Config
from .results import Provenance, Refusal, ScreenRow

MODEL = "grade_spread_residual"


def _solve(matrix, target):
    """Gaussian elimination with partial pivoting. Returns None if singular."""
    n = len(matrix)
    aug = [list(row) + [target[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            return None
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pv = aug[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col] / pv
            if factor == 0:
                continue
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def _ols(x_rows, y):
    """Closed-form OLS via normal equations (X'X)b = X'y."""
    k = len(x_rows[0])
    xtx = [[sum(x_rows[i][a] * x_rows[i][b] for i in range(len(x_rows)))
            for b in range(k)] for a in range(k)]
    xty = [sum(x_rows[i][a] * y[i] for i in range(len(x_rows))) for a in range(k)]
    return _solve(xtx, xty)


def grade_spread_residual(
    cards: list,
    *,
    cfg: Config,
    game: Optional[str] = None,
    rarity_band: Optional[str] = None,
    era: Optional[str] = None,
    min_sample: Optional[int] = None,
    window_days: Optional[int] = None,
):
    """Rank a cross-section by grade-spread residual.

    Each entry in `cards` needs:
        card_uid, game, rarity_band, era,
        p10_median, p9_median      (numbers; medians of graded sale comps)
        p10_sample, p9_sample      (int; comps in the window)
        pop10, pop9                (int; population counts)

    Medians are plain numbers, not Money: this model works in the ratio
    log(P10/P9), which is dimensionless, and never reports a monetary amount.
    """
    if min_sample is None:
        min_sample = cfg.get("assumptions.min_comp_sample_size.value")
        if min_sample is None:
            return Refusal(MODEL, "no minimum sample size configured",
                           missing=["assumptions.min_comp_sample_size.value"])
    min_sample = int(min_sample)
    window_days = int(window_days or cfg.get("assumptions.min_comp_sample_size.window_days") or 90)

    pool = [c for c in cards
            if (game is None or c.get("game") == game)
            and (rarity_band is None or c.get("rarity_band") == rarity_band)
            and (era is None or c.get("era") == era)]
    if not pool:
        return Refusal(MODEL, "empty cross-section",
                       "no cards matched the requested game / rarity band / era")

    suppressed, usable = [], []
    for c in pool:
        s10, s9 = int(c.get("p10_sample", 0)), int(c.get("p9_sample", 0))
        reasons = []
        if s10 < min_sample:
            reasons.append(f"PSA 10 comps {s10} < {min_sample} in {window_days}d")
        if s9 < min_sample:
            reasons.append(f"PSA 9 comps {s9} < {min_sample} in {window_days}d")
        if float(c.get("p9_median", 0)) <= 0 or float(c.get("p10_median", 0)) <= 0:
            reasons.append("non-positive median")
        if int(c.get("pop10", 0)) <= 0 or int(c.get("pop9", 0)) <= 0:
            reasons.append("non-positive population")
        if reasons:
            suppressed.append(ScreenRow(
                card_uid=c["card_uid"], residual=Decimal(0), fitted=Decimal(0),
                observed=Decimal(0), sample_size_p10=s10, sample_size_p9=s9,
                pop9=int(c.get("pop9", 0)), pop10=int(c.get("pop10", 0)),
                suppressed=True, suppression_reason="; ".join(reasons)))
        else:
            usable.append(c)

    # Design matrix: intercept, log(pop9/pop10), then one dummy per extra
    # level of rarity / era / game. Dummies are dropped-first to stay full rank.
    def levels(key):
        return sorted({c.get(key) for c in usable if c.get(key) is not None})

    rarities, eras, games = levels("rarity_band"), levels("era"), levels("game")
    columns = 2 + max(0, len(rarities) - 1) + max(0, len(eras) - 1) + max(0, len(games) - 1)

    if len(usable) <= columns:
        return Refusal(
            MODEL, "not enough usable cards to fit",
            detail=(f"{len(usable)} cards survive suppression but the design needs more "
                    f"than {columns} to estimate {columns} coefficients; suppressed "
                    f"{len(suppressed)} of {len(pool)} for thin comps. Widen the "
                    "cross-section or loosen the band rather than fitting noise."))

    def row_for(c):
        row = [1.0, math.log(float(c["pop9"]) / float(c["pop10"]))]
        for lvl in rarities[1:]:
            row.append(1.0 if c.get("rarity_band") == lvl else 0.0)
        for lvl in eras[1:]:
            row.append(1.0 if c.get("era") == lvl else 0.0)
        for lvl in games[1:]:
            row.append(1.0 if c.get("game") == lvl else 0.0)
        return row

    x_rows = [row_for(c) for c in usable]
    y = [math.log(float(c["p10_median"]) / float(c["p9_median"])) for c in usable]
    beta = _ols(x_rows, y)
    if beta is None:
        return Refusal(MODEL, "singular design matrix",
                       "the cross-section is collinear -- typically every card shares one "
                       "rarity band or era, so the dummies carry no information")

    rows = []
    for c, xr, obs in zip(usable, x_rows, y):
        fitted = sum(b * v for b, v in zip(beta, xr))
        rows.append(ScreenRow(
            card_uid=c["card_uid"],
            residual=Decimal(str(obs - fitted)).quantize(Decimal("0.000001")),
            fitted=Decimal(str(fitted)).quantize(Decimal("0.000001")),
            observed=Decimal(str(obs)).quantize(Decimal("0.000001")),
            sample_size_p10=int(c["p10_sample"]), sample_size_p9=int(c["p9_sample"]),
            pop9=int(c["pop9"]), pop10=int(c["pop10"])))

    rows.sort(key=lambda r: r.residual)   # most negative first: P10 cheapest
    return {
        "model": MODEL,
        "ok": True,
        "ranked": rows,
        "suppressed": suppressed,
        "coefficients": {"intercept": beta[0], "log_pop_ratio": beta[1],
                         "dummies": beta[2:]},
        "levels": {"rarity_band": rarities, "era": eras, "game": games},
        "n_fitted": len(usable),
        "n_suppressed": len(suppressed),
        "min_sample": min_sample,
        "window_days": window_days,
        "provenance": Provenance(
            as_of=str(cfg.today),
            sources=["caller-supplied cross-section"],
            warnings=[str(w) for w in cfg.staleness_warnings()],
            notes=[f"OLS refitted at call time from {len(usable)} cards; nothing learned "
                   "or persisted between calls",
                   f"{len(suppressed)} cards suppressed for comps below {min_sample} "
                   f"in {window_days} days"]).as_dict(),
    }
