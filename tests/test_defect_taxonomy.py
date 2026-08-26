"""The taxonomy has to verify itself, or it is the defect one level up.

A registry of `here is what went wrong and here is the test that would have
caught it` is worth nothing if the named test does not exist. That would be a
hand-maintained list going stale silently -- which is precisely the shape it
catalogues.

So: every instance names a remedy test, and this asserts the named test is
really there.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.defect_taxonomy import (INSTANCES, SPECIES,  # noqa: E402
                                   instances_of, remedy_for, species_of)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TheTwoSpeciesNeedDifferentTests(unittest.TestCase):
    """They read identically green. That is the only reason to separate
    them -- a test written for the wrong species passes and teaches nothing."""

    def test_the_remedies_differ(self):
        self.assertNotEqual(remedy_for("inert"), remedy_for("orphaned"))
        self.assertIn("can fail", remedy_for("inert"))
        self.assertIn("invokes it", remedy_for("orphaned"))

    def test_the_test_shapes_differ(self):
        self.assertNotEqual(SPECIES["inert"]["test_shape"],
                            SPECIES["orphaned"]["test_shape"])

    def test_the_orphaned_remedy_is_at_the_decision_point(self):
        """Exercising an orphaned check directly proves it works, which was
        never in doubt."""
        shape = SPECIES["orphaned"]["test_shape"]
        self.assertIn("DECISION POINT", shape)
        self.assertIn("never in doubt", shape)

    def test_the_inert_remedy_is_a_positive_case(self):
        """Asserting the clean case is what let these survive."""
        self.assertIn("catches it", SPECIES["inert"]["test_shape"])

    def test_both_read_as_a_passing_check(self):
        for name, species in SPECIES.items():
            with self.subTest(species=name):
                self.assertIn("passing check", species["reads_as"])

    def test_inert_has_two_shapes_with_different_remedies(self):
        shapes = SPECIES["inert"]["shapes"]
        self.assertIn("by_construction", shapes)
        self.assertIn("by_scope", shapes)
        self.assertIn("never pointed at", shapes["by_scope"])


class EveryInstanceNamesARemedyThatExists(unittest.TestCase):

    def _resolve(self, reference):
        """`tests/x.py::Class::method` or `tests/x.py descriptive text`."""
        path = reference.split("::")[0].split(" ")[0].strip()
        full = os.path.join(REPO, path)
        if not os.path.exists(full):
            return None, path
        with open(full, encoding="utf-8") as handle:
            return handle.read(), path

    def test_every_instance_is_classified(self):
        for entry in INSTANCES:
            with self.subTest(instance=entry["name"]):
                self.assertIn(entry["species"], SPECIES)
                if entry["species"] == "inert":
                    self.assertIn(entry["shape"],
                                  SPECIES["inert"]["shapes"])

    def test_every_instance_names_a_test_file_that_exists(self):
        for entry in INSTANCES:
            with self.subTest(instance=entry["name"]):
                body, path = self._resolve(entry["test"])
                self.assertIsNotNone(body, f"{path} does not exist")

    def test_every_named_symbol_is_really_in_that_file(self):
        """The assertion that stops this becoming a stale list."""
        for entry in INSTANCES:
            body, path = self._resolve(entry["test"])
            if body is None:
                continue
            reference = entry["test"].split(" ")[0]
            symbols = reference.split("::")[1:]
            self.assertTrue(symbols, f"{entry['test']!r} names no symbol; a "
                                     "reference with nothing to check is not "
                                     "a remedy")
            for symbol in symbols:
                with self.subTest(instance=entry["name"], symbol=symbol):
                    self.assertRegex(
                        body, rf"\b(class|def)\s+{re.escape(symbol)}\b",
                        f"{entry['test']} names {symbol!r}, which is not "
                        f"defined in {path}")

    def test_every_instance_says_what_it_read_as_and_what_it_was(self):
        for entry in INSTANCES:
            with self.subTest(instance=entry["name"]):
                self.assertTrue(entry["read_as"].strip())
                self.assertTrue(entry["actually"].strip())
                self.assertTrue(entry["remedy_applied"].strip())

    def test_the_orphaned_instance_is_the_upgrade_one(self):
        orphaned = instances_of("orphaned")
        self.assertEqual(len(orphaned), 1)
        self.assertIn("upgrade", orphaned[0]["name"])
        self.assertIn("decision point", orphaned[0]["test"])

    def test_the_by_scope_instance_names_the_universe_it_missed(self):
        by_scope = [e for e in instances_of("inert")
                    if e["shape"] == "by_scope"]
        self.assertEqual(len(by_scope), 1)
        self.assertIn("git ls-files", by_scope[0]["actually"])

    def test_lookup_by_name_works(self):
        self.assertEqual(
            species_of("upgrade() never called the corroboration standard"),
            "orphaned")
        self.assertIsNone(species_of("something that never happened"))


if __name__ == "__main__":
    unittest.main()
