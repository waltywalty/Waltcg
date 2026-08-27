#!/usr/bin/env python3
"""Hard gate: every interval estimator in the repository passes ONE battery.

WHY THIS EXISTS: THE SAME BUG, TWICE. `tests/test_resolver_gate.py`
shipped a Wilson/beta lower bound with an inverted bisection at c333ec3 --
it returned 0.0 for every input, and `assertLess(bound, threshold)` passed
on it silently. That was caught, fixed, and written up. Three sessions later
`audit/checks/catalog_precision.py:clopper_pearson_lower` shipped with the
identical inversion -- inside a docstring warning about the first one.

Knowledge recorded is not a control. A comment saying "do not invert this"
sits next to the inverted code and reads exactly like a comment next to
correct code. So the control is a test that the function has to survive, and
the roster of functions is DISCOVERED rather than listed: a fourth interval
function added next session fails this check until it is covered, whether or
not anybody remembered this file existed.

WHAT THE PIN HAS TO INCLUDE. Both inversions returned a bound of 0.0 for
imperfect samples while the CLEAN-SWEEP case passed on a closed-form early
return (`alpha ** (1/n)`), which never touches the bisection. A pin that only
checks zero-error cases passes both bugs. The one-error cases from ADR-0015 --
250 rows surviving a single mistake at 0.9812, 200 rows at 0.9765 -- catch
both. Every entry in `PINS` below carries at least one error for that reason,
and the zero-error entries are kept only as company.

THE PINS ARE ANCHORED TO THE DEFINING EQUATION, NOT TO AN IMPLEMENTATION.
Each pinned constant p satisfies

    sum_{k >= n-e} C(n,k) p^k (1-p)^(n-k)  =  alpha

and `verify_pins()` checks exactly that, so the table cannot inherit an error
from whichever function produced it. A pin computed by running the code it is
meant to pin is not a pin.

ORIENTATION IS NORMALISED, NOT ASSUMED. A lower bound on precision and an
upper bound on an error rate are the same object read from opposite ends
(Clopper-Pearson duality: lower_success(n, n-e) = 1 - upper_error(n, e)).
Each contract declares its orientation and its second argument; the battery
converts every function to one shape, `L(n, errors)`, and applies one set of
properties. Declaring the orientation WRONG is not a way through -- the pins
are checked after normalisation, so a mis-declared function fails them.

WHAT THIS CHECK CANNOT SEE:

  * It tests the estimator, not its CALLERS. A correct bound compared with a
    `>` that should be a `<` passes here.
  * Discovery is by function NAME. An interval function called `spread()` is
    invisible; the name vocabulary is `NAME_PATTERN` and widening it is
    cheap, but nothing forces a new name into it.
  * It does not check that a two-sided interval's two ends belong to the same
    alpha. There are no two-sided estimators in the repository yet.
  * A function that is correct on the pinned grid and wrong off it passes.
    The monotonicity properties are what cover the space between pins, and
    they are properties, not proofs.
  * The all-errors case is probed only up to `ALL_ERROR_MAX_N`, because
    evaluating an estimator at errors=n costs n+1 binomial terms per bisection
    step. An estimator that misbehaves only at errors=250 passes.

Usage:  python -m audit.checks.interval_properties [--verbose]
Exit 0 clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import math
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

#: What makes a function an interval estimator, by name. Deliberately broad:
#: a false positive costs one contract entry, a false negative costs the whole
#: point of the check.
NAME_PATTERN = re.compile(
    r"clopper|pearson|wilson|agresti|jeffreys|binom"
    r"|(^|_)(lower|upper)_bound"
    r"|(^|_)(confidence_)?interval"
    r"|(^|_)ci$")

#: `test_*` is never an estimator -- it is a test ABOUT one, and several of
#: them mention `lower_bound` in their names. This is the only name-shaped
#: exclusion, and it is safe in the direction that matters: a test function
#: cannot be called with (n, errors).
TEST_PREFIX = "test_"

#: THE ROSTER. Key is `module:qualname`; a nested `Class.method` is reached
#: through the class. Every discovered estimator must appear here, and every
#: entry here must still resolve -- a stale entry is a guard that has silently
#: stopped testing anything.
#:
#: orientation: "lower_on_successes"  -> larger is a TIGHTER claim about precision
#:              "upper_on_errors"     -> smaller is a tighter claim about error rate
#: second_arg:  what the function's second parameter counts
#: alpha_param: True if the function takes alpha and honours it
CONTRACTS = {
    "audit.checks.catalog_precision:clopper_pearson_lower": {
        "orientation": "lower_on_successes",
        "second_arg": "successes",
        "alpha_param": True,
    },
    "audit.checks.reverification_sample:clopper_pearson_upper": {
        "orientation": "upper_on_errors",
        "second_arg": "errors",
        "alpha_param": True,
    },
    "tests.test_resolver_gate:PrecisionIsReportedWithItsInterval._lower_bound": {
        "orientation": "lower_on_successes",
        "second_arg": "errors",
        "alpha_param": False,
    },
}

#: One-sided 95% Clopper-Pearson lower bounds on a success rate, as
#: (n, errors, value). ADR-0015's sizing note supplies (250, 1) = 0.9812,
#: (200, 1) = 0.9765 and (200, 0) = 0.9851; the rest fill in the small-n end
#: where both inversions were most visible. NO n APPEARS ONLY AS A CLEAN
#: SWEEP -- see the module docstring for why a zero-error table is worthless.
#: n=1 is the single exception, where one error is the degenerate all-error
#: case that property 5 already pins at zero.
PINS = (
    (1, 0, 0.050000),
    (10, 0, 0.741134),
    (10, 3, 0.393376),
    (30, 0, 0.904966),
    (30, 1, 0.851404),
    (30, 2, 0.804674),
    (60, 0, 0.951297),
    (60, 1, 0.923360),
    (149, 0, 0.980095),
    (149, 1, 0.968559),
    (200, 0, 0.985133),
    (200, 1, 0.976502),
    (250, 0, 0.988089),
    (250, 1, 0.981166),
    (250, 2, 0.975032),
)

ALPHA = 0.05
#: How far a function may sit from a pin before it has failed.
TOLERANCE = 1e-4
#: How far a PIN may sit from the defining equation. This is the rounding of
#: the printed constants to six places, not slack in the check: at n=250 a
#: 1e-6 wobble in p moves the tail by about 5e-6, so this admits roughly 2e-6
#: of error in p -- fifty times tighter than TOLERANCE.
PIN_EQUATION_TOLERANCE = 1e-5

#: The grid the properties are checked on. Small n is where a closed form and
#: a bisection disagree; 250 is where the gate actually reads.
GRID_N = (1, 2, 3, 5, 10, 30, 60, 149, 200, 250)

#: Above this, the all-errors case is not probed. See property 2 for why --
#: it is a cost bound, not a claim that the property stops holding, and it is
#: stated here rather than buried so a future estimator that only misbehaves
#: at errors=n is a known blind spot rather than a surprise.
ALL_ERROR_MAX_N = 60

_MARKER = re.compile(
    r"#\s*INTERVAL-EXEMPT\((?P<claim>[a-z-]+)\)\s*:\s*(?P<why>.+)")

#: THE ROSTER SEAL, same instrument as `audit/mutant_seal.json`. Zero, and it
#: is meant to stay zero: an exemption is a function declared not to be an
#: estimator, and there is currently no such function. Raising this number is
#: a decision somebody has to make in a diff.
EXPECTED_EXEMPTIONS = 0


def tracked_files(root=REPO):
    """Every .py in the working tree, TRACKED OR NOT.

    A brand-new estimator is untracked at the moment it is written, and this
    check exists to catch a new estimator. `git ls-files` alone was the
    elevation audit's own inert bug; it is not repeated here.
    """
    listed = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                            capture_output=True, text=True)
    if listed.returncode != 0:
        raise SystemExit(f"git ls-files failed: {listed.stderr}")
    paths = {f for f in listed.stdout.splitlines() if f.strip()}
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "*.py"],
        cwd=root, capture_output=True, text=True)
    if untracked.returncode == 0:
        paths |= {f for f in untracked.stdout.splitlines() if f.strip()}
    return sorted(paths)


def module_name(path):
    return path[:-3].replace("/", ".").replace(os.sep, ".")


def discover(root=REPO):
    """Every function in the tree whose NAME says it estimates an interval.

    Returns {key: (path, lineno)} keyed `module:qualname`, plus the set of
    keys carrying an exemption marker.
    """
    found, exempt = {}, {}
    for rel in tracked_files(root):
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        lines = source.splitlines()
        stack = [("", tree)]
        while stack:
            prefix, node = stack.pop()
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.ClassDef)):
                    continue
                qual = f"{prefix}.{child.name}" if prefix else child.name
                stack.append((qual, child))
                if isinstance(child, ast.ClassDef):
                    continue
                if child.name.startswith(TEST_PREFIX):
                    continue
                if not NAME_PATTERN.search(child.name):
                    continue
                key = f"{module_name(rel)}:{qual}"
                found[key] = (rel, child.lineno)
                for offset in range(max(0, child.lineno - 3), child.lineno):
                    hit = _MARKER.search(lines[offset]) if offset < len(lines) else None
                    if hit:
                        exempt[key] = hit.group("why").strip()
    return found, exempt


def resolve(key):
    """Import the module and walk the qualname. A staticmethod on a test class
    is reached exactly like a module-level function."""
    module_path, qual = key.split(":", 1)
    obj = importlib.import_module(module_path)
    for part in qual.split("."):
        obj = getattr(obj, part)
    return obj


# -- the battery -----------------------------------------------------------

def normalise(fn, contract):
    """Every estimator, read as `L(n, errors)` -- a lower bound on the
    success rate. Duality does the conversion, so one battery covers both
    orientations and a mis-declared orientation fails the pins."""
    lower = contract["orientation"] == "lower_on_successes"
    successes = contract["second_arg"] == "successes"

    def L(n, errors, alpha=ALPHA):
        second = (n - errors) if successes else errors
        value = fn(n, second, alpha) if contract["alpha_param"] else fn(n, second)
        return value if lower else 1.0 - value
    return L


def tail(n, errors, p):
    """P(X >= n - errors | Bin(n, p)). The defining equation's left side."""
    return sum(math.comb(n, k) * p ** k * (1 - p) ** (n - k)
               for k in range(n - errors, n + 1))


def verify_pins():
    """The pins answer to the binomial, not to any function in this repo."""
    bad = []
    for n, errors, value in PINS:
        got = tail(n, errors, value)
        if abs(got - ALPHA) > PIN_EQUATION_TOLERANCE:
            bad.append(f"PIN ({n}, {errors}) = {value}: defining equation "
                       f"gives {got:.8f}, not {ALPHA}")
    return bad


def battery(key, fn, contract):
    """Every property, on one function. Returns a list of failure strings."""
    L = normalise(fn, contract)
    out = []

    def check(condition, message):
        if not condition:
            out.append(f"{key}: {message}")

    # 1. THE PINS, including the one-error cases. This is the property both
    #    inversions failed and the clean-sweep-only pin missed.
    for n, errors, expect in PINS:
        try:
            got = L(n, errors)
        except Exception as exc:                          # noqa: BLE001
            out.append(f"{key}: raised on (n={n}, errors={errors}): {exc!r}")
            continue
        check(abs(got - expect) <= TOLERANCE,
              f"pin (n={n}, errors={errors}) expected {expect:.6f}, "
              f"got {got:.6f}"
              + ("  <-- COLLAPSED TO ZERO: the bisection is inverted"
                 if got <= 1e-9 and expect > 1e-9 else ""))

    # 2. Range. A bound outside [0, 1] is not a probability. The all-error
    #    case is checked only up to ALL_ERROR_MAX_N: an estimator evaluated at
    #    errors=n sums n+1 binomial terms per bisection step, and at n=250
    #    that is 50,000 big-integer `comb` calls for a property that is
    #    qualitative and already decided by n=60.
    for n in GRID_N:
        cases = {0, 1, 2, min(n, 3)}
        if n <= ALL_ERROR_MAX_N:
            cases.add(n)
        for errors in sorted(cases):
            if errors > n:
                continue
            got = L(n, errors)
            check(0.0 <= got <= 1.0,
                  f"(n={n}, errors={errors}) = {got!r} is outside [0, 1]")

    # 3. Monotone in k: more errors can only lower the bound.
    for n in GRID_N:
        previous = None
        for errors in range(0, min(n, 5) + 1):
            got = L(n, errors)
            if previous is not None:
                check(got <= previous + 1e-12,
                      f"errors {errors - 1} -> {errors} at n={n} RAISED the "
                      f"bound ({previous:.6f} -> {got:.6f})")
            previous = got

    # 4. Monotone in n: more trials at the same error count can only raise it.
    for errors in (0, 1, 2):
        previous = None
        for n in GRID_N:
            if n <= errors:
                continue
            got = L(n, errors)
            if previous is not None:
                check(got >= previous - 1e-12,
                      f"n grew to {n} at errors={errors} and the bound FELL "
                      f"({previous:.6f} -> {got:.6f})")
            previous = got

    # 5. A lower bound sits below the point estimate, and an all-errors sample
    #    bounds nothing above zero.
    for n in GRID_N:
        for errors in range(0, min(n, 4) + 1):
            got, point = L(n, errors), (n - errors) / n
            check(got <= point + 1e-12,
                  f"(n={n}, errors={errors}) = {got:.6f} EXCEEDS the point "
                  f"estimate {point:.6f}")
        if n <= ALL_ERROR_MAX_N:
            check(abs(L(n, n)) <= 1e-6,
                  f"a sample of {n} with {n} errors bounds precision at "
                  f"{L(n, n):.6f}, not 0")

    # 6. An empty sample bounds nothing. Both orientations normalise to 0.0.
    check(abs(L(0, 0)) <= 1e-9,
          f"an empty sample returns {L(0, 0)!r}; nothing was observed, so "
          f"nothing is bounded")

    # 7. Alpha is honoured: more confidence demanded, less claimed.
    if contract["alpha_param"]:
        for n, errors in ((30, 1), (250, 1)):
            strict, loose = L(n, errors, 0.01), L(n, errors, 0.10)
            check(strict < loose,
                  f"alpha is ignored or inverted at (n={n}, errors={errors}): "
                  f"alpha=0.01 gives {strict:.6f}, alpha=0.10 gives "
                  f"{loose:.6f}")
    return out


def run(root=REPO):
    """Returns (violations, report). Empty violations is a pass."""
    violations, report = [], []

    violations += verify_pins()

    found, exempt = discover(root)
    if len(exempt) != EXPECTED_EXEMPTIONS:
        violations.append(
            f"exemption roster: {len(exempt)} marker(s) present, seal says "
            f"{EXPECTED_EXEMPTIONS}. An allowlist that can grow quietly is "
            f"the defect this check is about.")

    uncovered = sorted(set(found) - set(CONTRACTS) - set(exempt))
    for key in uncovered:
        rel, line = found[key]
        violations.append(
            f"UNCOVERED: {key} ({rel}:{line}) is an interval function with no "
            f"contract. Add it to CONTRACTS with its orientation and second "
            f"argument, or mark it # INTERVAL-EXEMPT(not-an-estimator): why.")

    stale = sorted(set(CONTRACTS) - set(found))
    for key in stale:
        violations.append(
            f"STALE: contract {key} resolves to nothing. A roster entry for a "
            f"function that no longer exists is a guard that stopped testing.")

    for key in sorted(set(CONTRACTS) & set(found)):
        try:
            fn = resolve(key)
        except Exception as exc:                          # noqa: BLE001
            violations.append(f"{key}: cannot be resolved: {exc!r}")
            continue
        try:
            failures = battery(key, fn, CONTRACTS[key])
        except Exception as exc:                          # noqa: BLE001
            # A crash is a violation, not a traceback out of the audit. The
            # empty-sample ZeroDivisionError in the gate's own helper arrived
            # this way the first time this check ran.
            failures = [f"{key}: the battery raised {exc!r}"]
        violations += failures
        report.append((key, found[key][0], len(failures)))
    return violations, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    violations, report = run()
    print(f"interval estimators covered: {len(report)}  "
          f"pins: {len(PINS)}  exemptions: {EXPECTED_EXEMPTIONS}")
    if args.verbose:
        for key, rel, failures in report:
            mark = "ok " if not failures else f"{failures} FAIL"
            print(f"  [{mark}] {key}  ({rel})")
    for line in violations:
        print(f"VIOLATION: {line}")
    if violations:
        print(f"\n{len(violations)} violation(s).")
        return 1
    print("clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
