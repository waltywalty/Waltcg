"""The shared battery, and proof that it catches the bug it exists for.

Two inverted bisections shipped in this repository -- Wilson/beta at c333ec3
and Clopper-Pearson at ea2f9a4 -- and the second one was written inside a
docstring warning about the first. These tests pin the three things that make
`audit/checks/interval_properties.py` a control rather than another warning:

  1. it catches an inverted bisection,
  2. a clean-sweep-only pin does NOT, so the one-error rows are load-bearing,
  3. a new estimator fails until somebody declares it.
"""

import math
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from audit.checks import interval_properties as IP        # noqa: E402

LOWER = {"orientation": "lower_on_successes", "second_arg": "successes",
         "alpha_param": True}


def inverted_lower(n, right, alpha=0.05):
    """The bug, verbatim in shape: the comparison the wrong way round, with
    the closed-form early return that let the clean-sweep cases through."""
    if n <= 0:
        return 0.0
    if right >= n:
        return alpha ** (1.0 / n)
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        t = sum(math.comb(n, k) * mid ** k * (1 - mid) ** (n - k)
                for k in range(right, n + 1))
        if t > alpha:
            lo = mid                      # <-- inverted
        else:
            hi = mid
    return (lo + hi) / 2


class TheRepositoryPasses(unittest.TestCase):

    def test_every_interval_function_in_the_tree_is_covered_and_clean(self):
        violations, report = IP.run()
        self.assertEqual(violations, [], "\n".join(violations))
        self.assertGreaterEqual(
            len(report), 3,
            "the roster shrank -- discovery is finding fewer estimators than "
            "the repository has, which reads exactly like passing")

    def test_the_pins_answer_to_the_binomial_not_to_our_code(self):
        self.assertEqual(IP.verify_pins(), [])

    def test_a_corrupted_pin_is_caught_by_the_defining_equation(self):
        original = IP.PINS
        try:
            IP.PINS = ((250, 1, 0.9),)
            self.assertTrue(IP.verify_pins())
        finally:
            IP.PINS = original


class TheBatteryCatchesTheInversion(unittest.TestCase):

    def test_an_inverted_bisection_fails(self):
        failures = IP.battery("inverted", inverted_lower, LOWER)
        self.assertTrue(failures, "the inverted bisection passed the battery")
        self.assertTrue(any("COLLAPSED TO ZERO" in f for f in failures),
                        "\n".join(failures))

    def test_a_clean_sweep_only_pin_would_have_missed_both_inversions(self):
        """The whole reason the one-error rows are in the table.

        The inverted function reproduces EVERY zero-error pin exactly, because
        those return from the closed form and never reach the bisection. A
        table of clean sweeps is green on the bug."""
        clean = [(n, e, v) for n, e, v in IP.PINS if e == 0]
        self.assertGreater(len(clean), 3)
        for n, _errors, expect in clean:
            self.assertAlmostEqual(inverted_lower(n, n), expect, places=5)
        one_error = [(n, e, v) for n, e, v in IP.PINS if e > 0]
        self.assertTrue(one_error, "the table has no error-carrying rows")
        for n, errors, expect in one_error:
            self.assertNotAlmostEqual(inverted_lower(n, n - errors), expect,
                                      places=3)

    def test_monotonicity_alone_also_catches_it(self):
        """Belt and braces: even without the pins, a bound that falls to zero
        the moment an error appears is not monotone in the way a bound is."""
        self.assertGreater(inverted_lower(250, 250), 0.9)
        self.assertLess(inverted_lower(250, 249), 1e-6)

    def test_a_wrong_orientation_is_not_a_way_through(self):
        """Declaring a lower bound as an upper one flips it into 1 - p, which
        the pins refuse. The contract cannot launder a function."""
        wrong = dict(LOWER, orientation="upper_on_errors")
        self.assertTrue(IP.battery("mis-declared", IP.resolve(
            "audit.checks.catalog_precision:clopper_pearson_lower"), wrong))

    def test_a_bound_that_ignores_alpha_fails(self):
        def deaf(n, right, alpha=0.05):
            return IP.resolve(
                "audit.checks.catalog_precision:clopper_pearson_lower")(
                    n, right, 0.05)
        failures = IP.battery("deaf", deaf, LOWER)
        self.assertTrue(any("alpha is ignored" in f for f in failures),
                        "\n".join(failures))

class DiscoveryIsStructural(unittest.TestCase):

    NEW = os.path.join(REPO, "audit", "checks", "_scratch_new_estimator.py")
    KEY = "audit.checks._scratch_new_estimator:wilson_lower"

    def tearDown(self):
        if os.path.exists(self.NEW):
            os.remove(self.NEW)
        IP.CONTRACTS.pop(self.KEY, None)
        sys.modules.pop("audit.checks._scratch_new_estimator", None)

    def _scratch(self, body):
        with open(self.NEW, "w", encoding="utf-8") as handle:
            handle.write(body)

    def test_a_crashing_estimator_is_a_violation_not_a_traceback(self):
        """The gate's own helper crashed on an empty sample the first time
        this battery ran. A traceback out of an audit is an audit that did not
        report, which is indistinguishable from an audit nobody ran."""
        self._scratch("def wilson_lower(n, right, alpha=0.05):\n"
                      "    raise ZeroDivisionError('float division by zero')\n")
        IP.CONTRACTS[self.KEY] = LOWER
        violations, report = IP.run()
        self.assertTrue(any(self.KEY in v and "raised" in v
                            for v in violations), "\n".join(violations))
        self.assertTrue(any(key == self.KEY for key, _rel, _n in report),
                        "the crashing estimator vanished from the report "
                        "instead of failing in it")

    def test_an_exemption_is_visible_and_breaks_the_seal(self):
        """The escape hatch exists and is sealed shut. Marking a function
        not-an-estimator removes it from UNCOVERED and immediately fails the
        roster count, so the allowlist cannot grow in silence."""
        self._scratch("# INTERVAL-EXEMPT(not-an-estimator): scratch\n"
                      "def wilson_lower(n, right, alpha=0.05):\n"
                      "    return 0.0\n")
        found, exempt = IP.discover()
        self.assertIn(self.KEY, exempt)
        violations, _ = IP.run()
        self.assertFalse(any(self.KEY in v and "UNCOVERED" in v
                             for v in violations))
        self.assertTrue(any("exemption roster" in v for v in violations),
                        "\n".join(violations))

    def test_a_new_estimator_fails_until_it_is_declared(self):
        """The property the elevation audit taught: the roster is discovered,
        so a function added next session is a FAILURE and not an omission."""
        self._scratch("def wilson_lower(n, right, alpha=0.05):\n"
                      "    return 0.0\n")
        found, _exempt = IP.discover()
        key = self.KEY
        self.assertIn(key, found, "an untracked new file was not discovered -- "
                                  "the same by_scope defect as `git ls-files`")
        violations, _ = IP.run()
        self.assertTrue(any(key in v and "UNCOVERED" in v for v in violations),
                        "\n".join(violations))

    def test_a_stale_contract_is_a_violation(self):
        original = dict(IP.CONTRACTS)
        try:
            IP.CONTRACTS["audit.checks.nowhere:gone_lower_bound"] = LOWER
            violations, _ = IP.run()
            self.assertTrue(any("STALE" in v for v in violations))
        finally:
            IP.CONTRACTS.clear()
            IP.CONTRACTS.update(original)

    def test_tests_are_excluded_by_prefix_only(self):
        """`test_the_lower_bound_is_computable_and_reported` matches the name
        pattern. Excluding it by prefix is safe -- a test method cannot be
        called with (n, errors) -- and it is the ONLY name-shaped exclusion."""
        self.assertTrue(IP.NAME_PATTERN.search(
            "test_the_lower_bound_is_computable_and_reported"))
        found, _ = IP.discover()
        self.assertFalse([k for k in found if ":test_" in k
                          or k.rsplit(".", 1)[-1].startswith("test_")])

    def test_the_exemption_roster_is_sealed_at_zero(self):
        _found, exempt = IP.discover()
        self.assertEqual(len(exempt), IP.EXPECTED_EXEMPTIONS)
        self.assertEqual(IP.EXPECTED_EXEMPTIONS, 0,
                         "an estimator has been declared not-an-estimator; "
                         "that is a decision, and it belongs in an ADR")


if __name__ == "__main__":
    unittest.main()
