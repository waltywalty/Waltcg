"""What a second source is corroborating, and what it silently is not.

The failure this guards against does not look like a failure. A row reaches
`verified` because two sources agree; the question nobody asks is what they
agreed ABOUT. Both instances here are cases where the second source confirms
the collector number and is structurally incapable of confirming anything
else -- and both look like confirmation of the whole row.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.corroboration import (STRUCTURALLY_NUMBER_ONLY,  # noqa: E402
                                   TIERS, is_structurally_number_only,
                                   tier_counts_toward_verified)


class OnlyFullCorroborationCounts(unittest.TestCase):

    def test_full_counts(self):
        self.assertTrue(tier_counts_toward_verified("full"))

    def test_number_only_does_not(self):
        self.assertFalse(tier_counts_toward_verified("number_only"))

    def test_an_unknown_tier_does_not_count(self):
        """A tier nobody has classified is not a licence to assume the
        strongest one. If a new source class arrives and nobody decides what
        it can attest, the answer is no, not yes."""
        for unknown in ("partial", "probably_full", "", None, "FULL"):
            with self.subTest(tier=unknown):
                self.assertFalse(tier_counts_toward_verified(unknown))

    def test_every_tier_states_what_it_attests(self):
        for name, tier in TIERS.items():
            with self.subTest(tier=name):
                self.assertTrue(tier["what"].strip())
                self.assertIn("counts_toward_verified", tier)

    def test_a_tier_that_does_not_count_says_why(self):
        for name, tier in TIERS.items():
            if not tier["counts_toward_verified"]:
                with self.subTest(tier=name):
                    self.assertTrue(tier.get("why", "").strip(),
                                    f"{name} refuses to count and does not "
                                    f"say why")


class TheTwoStructuralCases(unittest.TestCase):
    """Arrived at from opposite directions, identical in shape."""

    def test_shared_numbering_is_structural(self):
        self.assertTrue(
            is_structurally_number_only("shared_numbering_across_languages"))

    def test_retained_number_reprint_is_structural(self):
        self.assertTrue(is_structurally_number_only("retained_number_reprint"))

    def test_an_unlisted_situation_is_not_asserted_either_way(self):
        self.assertFalse(is_structurally_number_only("some_new_source_class"))
        self.assertFalse(is_structurally_number_only(None))

    def test_each_case_names_what_it_applies_to_and_why(self):
        for name, case in STRUCTURALLY_NUMBER_ONLY.items():
            with self.subTest(case=name):
                self.assertTrue(case["applies_to"].strip())
                self.assertTrue(case["why"].strip())
                self.assertTrue(case["example"].strip())

    def test_the_reprint_case_names_a_discriminating_source(self):
        """Saying a source class cannot answer the question is only half the
        finding. The other half is which source class can -- otherwise the
        entry reads as `unknowable` and the row never gets resolved."""
        case = STRUCTURALLY_NUMBER_ONLY["retained_number_reprint"]
        self.assertIn("Limitless", case["discriminating_source"])
        self.assertIn("per printing", case["discriminating_source"])

    def test_the_reprint_case_records_the_ebay_reasoning(self):
        """The specific mechanism, not a general caution. The seller reads the
        number; the number says OP01; the listing says Romance Dawn."""
        why = STRUCTURALLY_NUMBER_ONLY["retained_number_reprint"]["why"]
        self.assertIn("OP01", why)
        self.assertIn("Romance Dawn", why)
        self.assertIn("eBay", why)


if __name__ == "__main__":
    unittest.main()
