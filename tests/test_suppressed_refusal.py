"""The third species: a refusal caught and answered.

`audit/defect_taxonomy.py` had two species and both of their remedies pass
this defect cleanly. Given

    try:
        return numbers_denote_same_printing(a, b, set_total=total) is True
    except CannotBridge:
        return str(a) == str(b)

the INERT remedy passes (the bridge demonstrably raises) and the ORPHANED
remedy passes (`_numbers_agree` is demonstrably called at the decision point).
Neither asks what happens to the refusal after it is raised.

So these tests are written to the third shape: **at the caller, asserting the
refusal survives the handler.**
"""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from audit.checks import catalog_precision as C           # noqa: E402
from audit.checks import no_suppressed_refusal as NS      # noqa: E402
from audit.defect_taxonomy import SPECIES, instances_of   # noqa: E402
from ingest.base import AdapterGaveUp, RateLimited        # noqa: E402
from ingest.catalog_sources import (FILTER_UNMEASURED,   # noqa: E402
                                    TcgdexAdapter)


class TheCallerGetsCannotTellNotAVerdict(unittest.TestCase):
    """`SV001` against `001/122`: no total, no readable index, no bridge.
    The answer is not `False`."""

    ROW = {"card_uid": "pkmn:cel25cc:2/102:holo:EN", "game": "pkmn",
           "language": "EN", "set_code": "cel25cc", "number": "2/102",
           "variant": "holo", "name": "Venusaur"}
    ENTRY = {"source": "tcgdex", "game": "pkmn", "language": "EN",
             "set_code": "cel25cc", "number": "CC001", "name": "Venusaur"}

    def test_an_unbridgeable_pair_is_cannot_tell(self):
        self.assertIs(C._numbers_agree("CC001", "2/102"), C.CANNOT_TELL)
        self.assertIsNot(C._numbers_agree("CC001", "2/102"), False)

    def test_identical_strings_are_still_decidable(self):
        """Decided BEFORE the bridge is asked, so it is not the refusal being
        overruled."""
        self.assertIs(C._numbers_agree("SV001", "SV001"), True)

    def test_a_real_disagreement_is_still_false(self):
        self.assertIs(C._numbers_agree("11", "12/78", set_total=78), False)

    def test_the_caller_reports_could_not_tell_separately(self):
        """THE POINT. Counted as 'no catalog entry with this number', an
        unbridgeable row is indistinguishable from a card the catalog does not
        carry -- and the catalog's coverage is the thing being measured."""
        _pairs, unpaired = C.pair([self.ROW], [self.ENTRY], "field")
        self.assertEqual(len(unpaired), 1)
        self.assertIn("COULD NOT TELL", unpaired[0][1])

    def test_the_real_measurement_carries_the_bucket(self):
        result = C.measure()["joins"]["field"]
        self.assertIn("COULD NOT TELL", result["unpaired_reasons"],
                      "the bucket vanished -- either every number now bridges "
                      "or the refusal is being swallowed again")


class ARateLimitIsNotAMeasurement(unittest.TestCase):
    """`filter_is_honoured` returned `False` for a rate limit, and `False` is
    what it returns for a filter it measured and found ignored. The caller
    reads `False` as 'fall back', and the fallback is 8,313 single-card
    fetches -- begun because the source said stop."""

    class _Refusing(TcgdexAdapter):
        def __init__(self, exc):
            super().__init__()
            self._exc = exc

        def rarities(self, language):
            raise self._exc

    def test_a_rate_limit_propagates(self):
        """Answering "stop" with 8,313 requests is not a judgement call."""
        adapter = self._Refusing(RateLimited("429"))
        with self.assertRaises(RateLimited):
            adapter.filter_is_honoured("EN")
        self.assertTrue(any("rate limited" in line for line in adapter.log),
                        adapter.log)

    def test_an_unreachable_probe_is_unmeasured_not_ignored(self):
        """`AdapterGaveUp` covers both a missing `/rarities` route -- a fact
        about the source -- and a transient failure, and the adapter cannot
        tell them apart. So the caller still falls back; what it must not do
        is record the fallback as a MEASURED miss."""
        adapter = self._Refusing(AdapterGaveUp("no route"))
        self.assertIs(adapter.filter_is_honoured("EN"), FILTER_UNMEASURED)
        self.assertIsNot(adapter.filter_is_honoured("EN"), False)
        self.assertTrue(any("filter probe refused" in line
                            for line in adapter.log), adapter.log)

    # THE CALLER-SIDE ASSERTION lives in tests/test_catalog_sources.py::
    # TheEnglishFallbackIsNowThePrimaryRoute::test_the_index_is_built_and_used,
    # which drives a real adapter whose `/rarities` route 404s and asserts the
    # strategy comes back `graphql_filter_unmeasured` rather than `graphql`. A
    # measured miss and an unmeasured one used to produce the same string.


class TheSpeciesIsInTheTaxonomy(unittest.TestCase):

    def test_it_has_its_own_remedy(self):
        remedies = {name: SPECIES[name]["remedy"] for name in SPECIES}
        self.assertEqual(len(set(remedies.values())), len(remedies),
                         "two species share a remedy, which is the same as "
                         "not having separated them")
        self.assertIn("PROPAGATES", SPECIES["suppressed"]["remedy"])

    def test_the_test_shape_says_both_prior_remedies_pass_it(self):
        shape = SPECIES["suppressed"]["test_shape"]
        self.assertIn("BOTH PRIOR REMEDIES", shape)
        self.assertIn("CALLER", shape)

    def test_both_instances_are_recorded(self):
        names = {entry["name"] for entry in instances_of("suppressed")}
        self.assertIn("CannotBridge was caught and answered", names)
        self.assertIn("a rate limit was answered with a measurement", names)


class TheAuditIsStructural(unittest.TestCase):

    SCRATCH = os.path.join(REPO, "audit", "checks", "_scratch_suppression.py")

    def tearDown(self):
        if os.path.exists(self.SCRATCH):
            os.remove(self.SCRATCH)

    def _scratch(self, body):
        with open(self.SCRATCH, "w", encoding="utf-8") as handle:
            handle.write(body)

    def test_the_repository_is_clean(self):
        violations, _report = NS.scan()
        self.assertEqual(violations, [], "\n".join(violations))

    def test_the_refusal_vocabulary_is_discovered_not_listed(self):
        _violations, report = NS.scan()
        for name in ("CannotBridge", "NumberRequired", "UnsupportedGame",
                     "AdapterGaveUp", "RateLimited"):
            self.assertIn(name, report["types"])

    def test_a_new_suppression_fails_the_check(self):
        """Untracked, because a new suppression is untracked when it is new."""
        self._scratch(
            "from resolve.identity import printed_from_bare\n"
            "from resolve.identity import CannotBridge\n"
            "\n"
            "def agree(a, b, total):\n"
            "    try:\n"
            "        return printed_from_bare(a, total) == b\n"
            "    except CannotBridge:\n"
            "        return a == b\n")
        violations, _report = NS.scan()
        self.assertTrue(any("_scratch_suppression.py" in v for v in violations),
                        "\n".join(violations) or "(clean)")

    def test_a_bare_except_is_in_scope_only_around_a_call_that_can_refuse(self):
        """The signature the check is named for -- and the reason it is not
        just a lint against `except Exception`."""
        self._scratch(
            "def harmless(a, b):\n"
            "    try:\n"
            "        return int(a) == int(b)\n"
            "    except Exception:\n"
            "        return a == b\n")
        violations, _report = NS.scan()
        self.assertFalse([v for v in violations
                          if "_scratch_suppression.py" in v], violations)

        self._scratch(
            "from resolve.identity import printed_from_bare\n"
            "\n"
            "def agree(a, b, total):\n"
            "    try:\n"
            "        return printed_from_bare(a, total) == b\n"
            "    except Exception:\n"
            "        return a == b\n")
        violations, _report = NS.scan()
        self.assertTrue([v for v in violations
                         if "_scratch_suppression.py" in v], violations)

    def test_binding_the_exception_and_using_it_is_accepted(self):
        self._scratch(
            "from resolve.identity import printed_from_bare, CannotBridge\n"
            "\n"
            "def agree(a, b, total):\n"
            "    try:\n"
            "        return printed_from_bare(a, total) == b\n"
            "    except CannotBridge as exc:\n"
            "        return {'unresolved': str(exc)}\n")
        violations, _report = NS.scan()
        self.assertFalse([v for v in violations
                          if "_scratch_suppression.py" in v], violations)

    def test_a_named_sentinel_counts_as_nothing_known(self):
        """`CANNOT_TELL = None` is better code than a bare `return None`, and
        a check that forced the bare literal would punish the clearer one."""
        self._scratch(
            "from resolve.identity import printed_from_bare, CannotBridge\n"
            "\n"
            "CANNOT_TELL = None\n"
            "\n"
            "def agree(a, b, total):\n"
            "    try:\n"
            "        return printed_from_bare(a, total) == b\n"
            "    except CannotBridge:\n"
            "        return CANNOT_TELL\n")
        violations, _report = NS.scan()
        self.assertFalse([v for v in violations
                          if "_scratch_suppression.py" in v], violations)

    def test_false_is_not_nothing_known(self):
        """The specimen returned a bool. Calling that 'empty' is the mistake."""
        self._scratch(
            "from resolve.identity import printed_from_bare, CannotBridge\n"
            "\n"
            "NOTHING = False\n"
            "\n"
            "def agree(a, b, total):\n"
            "    try:\n"
            "        return printed_from_bare(a, total) == b\n"
            "    except CannotBridge:\n"
            "        return NOTHING\n")
        violations, _report = NS.scan()
        self.assertTrue([v for v in violations
                         if "_scratch_suppression.py" in v], violations)

    def test_the_exemption_roster_is_sealed(self):
        _violations, report = NS.scan()
        self.assertEqual(len(report["exemptions"]), NS.EXPECTED_EXEMPTIONS)


if __name__ == "__main__":
    unittest.main()
