"""One binomial interval, for the whole repository.

WHY THIS FILE EXISTS. The same bisection was written three times and inverted
twice -- Wilson/beta in the gate test at `c333ec3`, Clopper-Pearson in
`catalog_precision` at `ea2f9a4`, the second inside the docstring warning
about the first. `audit/checks/interval_properties.py` (ADR-0058) made the
duplication CHECKED: every estimator in the tree has to survive one battery.
Checked is not wise. Three copies of a function with a two-for-three failure
record is three chances to invert it, and the battery only ever proves that
the copies agree with the table, never that they are the same code.

So there is now one solver, and the two orientations are two views of it
rather than two implementations:

    P(X >= at_least | n, p) = alpha

is monotone increasing in p, so a single root-find answers both questions.
A lower bound on a success rate takes `at_least = successes`. An upper bound
on a failure rate is `1 - lower_bound(n, n - failures)` -- Clopper-Pearson
duality, written once, in code, instead of three times in comments.

The battery still applies. `interval_properties` discovers what is here by
name and pins both public functions against ADR-0015's table INCLUDING its
one-error rows, which is the property both inversions failed. Consolidating
does not retire the check; it reduces what the check has to cover from three
implementations to one.

WHERE IT LIVES. `audit/` holds the integrity checks and this is their
arithmetic. `tests/test_resolver_gate.py` imports it too, which is the point:
the gate's precision bound and the audit's precision bound are now provably
the same number, not two numbers that happen to agree.
"""

from __future__ import annotations

import math

#: The default one-sided confidence level, matching ADR-0015.
ALPHA = 0.05

#: Bisection steps. 200 halvings takes an interval of width 1 far below
#: double precision; the cost is linear and the margin is deliberate.
STEPS = 200


# INTERVAL-EXEMPT(not-an-estimator): a probability mass, not a bound. It
# matches the roster pattern on `binom` and is monotone the OTHER way in
# its second argument. Everything that calls it is on the roster.
def binomial_tail(n, at_least, p):
    """P(X >= at_least | X ~ Bin(n, p)).

    Increasing in p. That direction is the whole content of the bug this file
    exists to stop: a tail ABOVE alpha means the candidate p is too HIGH, so
    the upper half of the bracket is discarded. Written the other way round it
    returns 0.0 for every input, and 0.0 passes an `assertLess` silently.
    """
    if at_least <= 0:
        return 1.0
    if at_least > n:
        return 0.0
    return sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k)
               for k in range(at_least, n + 1))


def _root(n, at_least, alpha):
    """The p where `binomial_tail(n, at_least, p) == alpha`.

    ONE bisection, in one place, with one direction to get right.
    """
    lo, hi = 0.0, 1.0
    for _ in range(STEPS):
        mid = (lo + hi) / 2
        if binomial_tail(n, at_least, mid) > alpha:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def clopper_pearson_lower(n, successes, alpha=ALPHA):
    """One-sided lower bound on a SUCCESS rate.

    `clopper_pearson_lower(250, 249)` is 0.9812 -- ADR-0015's sizing note: a
    250-row set survives one error and a 200-row set does not.

    An empty sample bounds nothing, and 0.0 is the honest answer rather than a
    number that would read as a measurement.
    """
    if n <= 0:
        return 0.0
    if successes >= n:
        # Closed form. Kept because it is exact and cheap -- and named here
        # because it is also the reason a clean-sweep-only pin is worthless:
        # this branch never touches `_root`, so an inverted bisection
        # reproduces every zero-error bound perfectly.
        return alpha ** (1.0 / n)
    if successes <= 0:
        return 0.0
    return _root(n, successes, alpha)


def clopper_pearson_upper(n, failures=0, alpha=ALPHA):
    """One-sided upper bound on a FAILURE rate.

    The dual of the above, not a second implementation:
    `upper(n, e) = 1 - lower(n, n - e)`. `clopper_pearson_upper(30)` is 0.0950
    -- thirty clean re-derivations bound the error rate at about 10%, which is
    the arithmetic ADR-0055 sized its screen on.

    An empty sample bounds nothing, and for a failure rate that is 1.0.
    """
    if n <= 0:
        return 1.0
    return 1.0 - clopper_pearson_lower(n, n - failures, alpha)
