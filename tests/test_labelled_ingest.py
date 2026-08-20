"""Ingesting externally-researched identities into the labelled set.

The loader REFUSES rather than repairs. An identity is the one thing in this
project that must not be guessed at, and a loader that fills in a plausible
variant is exactly how a wrong card enters ground truth wearing the costume of
a verified one.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.label_cli import CONFIDENCE, SCORED, ingest  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def row(**overrides):
    base = {"card_uid": "pkmn:sv2a:201/165:sar:JP", "game": "pkmn",
            "set_code": "sv2a", "number": "201/165", "variant": "sar",
            "language": "JP", "name": "Charizard ex",
            "source": "external_research", "confidence": "verified"}
    base.update(overrides)
    return base


class OnlyVerifiedRowsAreGroundTruth(unittest.TestCase):
    """Two independent sources, or it is a candidate. A single-source identity
    is one transcription error away from being wrong, and precision computed
    over it measures the source rather than the resolver."""

    def _fresh(self):
        path = os.path.join(tempfile.mkdtemp(), "labelled.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cards": []}, handle)
        return path

    def test_both_confidences_are_accepted_and_counted_apart(self):
        path = self._fresh()
        accepted, rejected, report = ingest([
            row(),
            row(card_uid="pkmn:sv2a:199/165:sir:EN", set_code="sv2a",
                number="199/165", variant="sir", language="EN",
                confidence="single_source"),
        ], labelled_path=path)
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 2)
        self.assertEqual(report["verified"], 1)
        self.assertEqual(report["single_source"], 1)

    def test_single_source_is_never_promoted(self):
        """The instruction, stated as code. A candidate stays a candidate; it
        is not upgraded by being ingested, by being alone in its combo, or by
        anything else the loader does."""
        path = self._fresh()
        accepted, _rejected, _report = ingest(
            [row(confidence="single_source")], labelled_path=path)
        self.assertEqual(accepted[0]["confidence"], "single_source")
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)["cards"]
        self.assertEqual(stored[0]["confidence"], "single_source")
        self.assertNotIn("single_source", SCORED)

    def test_only_verified_is_scored(self):
        self.assertEqual(SCORED, ("verified",))
        for value in ("single_source", "in_repo", "unstated"):
            self.assertIn(value, CONFIDENCE)
            self.assertNotIn(value, SCORED)

    def test_a_row_with_no_confidence_is_refused(self):
        """Not defaulted. A default here would silently mint ground truth."""
        bare = row()
        del bare["confidence"]
        _accepted, rejected, _report = ingest([bare],
                                              labelled_path=self._fresh())
        self.assertEqual(len(rejected), 1)
        self.assertIn("missing confidence", rejected[0]["why"][0])

    def test_an_unknown_confidence_is_refused(self):
        _a, rejected, _r = ingest([row(confidence="probably")],
                                  labelled_path=self._fresh())
        self.assertIn("is not one of", " ".join(rejected[0]["why"]))

    def test_a_row_with_no_source_is_refused(self):
        bare = row()
        del bare["source"]
        _a, rejected, _r = ingest([bare], labelled_path=self._fresh())
        self.assertIn("missing source", " ".join(rejected[0]["why"]))


class TheUidIsDerivedNotTrusted(unittest.TestCase):
    """A row whose stated uid disagrees with its own fields is a transcription
    error, and accepting either half would put a wrong identity into the set
    that defines identity."""

    def _fresh(self):
        path = os.path.join(tempfile.mkdtemp(), "labelled.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cards": []}, handle)
        return path

    def test_a_mismatched_uid_is_refused(self):
        _a, rejected, _r = ingest(
            [row(card_uid="pkmn:sv2a:999/165:sar:JP")],
            labelled_path=self._fresh())
        self.assertEqual(len(rejected), 1)
        self.assertIn("but its own fields build", " ".join(rejected[0]["why"]))

    def test_a_uid_that_will_not_build_is_refused(self):
        _a, rejected, _r = ingest([row(language="KO")],
                                  labelled_path=self._fresh())
        self.assertIn("card_uid", " ".join(rejected[0]["why"]))

    def test_an_unknown_variant_is_refused(self):
        _a, rejected, _r = ingest([row(variant="shiny_special")],
                                  labelled_path=self._fresh())
        self.assertIn("not a token this project produces",
                      " ".join(rejected[0]["why"]))

    def test_a_numbered_parallel_is_a_known_variant(self):
        accepted, rejected, _r = ingest([
            row(card_uid="optcg:op01:OP01-025:parallel2:EN", game="optcg",
                set_code="op01", number="OP01-025", variant="parallel2",
                language="EN", name="Nami")], labelled_path=self._fresh())
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)

    def test_nothing_is_written_when_every_row_is_refused(self):
        path = self._fresh()
        ingest([row(card_uid="wrong")], labelled_path=path)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cards"], [])

    def test_dry_run_writes_nothing(self):
        path = self._fresh()
        accepted, _rejected, _r = ingest([row()], labelled_path=path,
                                         dry_run=True)
        self.assertEqual(len(accepted), 1)
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cards"], [])


class AKnownConfusableNeverEntersTheSet(unittest.TestCase):
    """Rayquaza VMAX s7R is 083/067. The 083/069 in listings is the KOREAN
    printing's denominator -- a number that belongs to no card this project
    tracks, and that parses cleanly enough to be accepted by anything not
    looking for it."""

    def _fresh(self):
        path = os.path.join(tempfile.mkdtemp(), "labelled.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cards": []}, handle)
        return path

    def test_the_korean_denominator_is_refused(self):
        _a, rejected, _r = ingest([
            row(card_uid="pkmn:s7R:083/069:base:JP", set_code="s7R",
                number="083/069", variant="base", name="Rayquaza VMAX")],
            labelled_path=self._fresh())
        self.assertEqual(len(rejected), 1)
        why = " ".join(rejected[0]["why"])
        self.assertIn("KNOWN CONFUSABLE", why)
        self.assertIn("Korean", why)
        self.assertIn("083/067", why, "the refusal did not say what IS right")

    def test_the_japanese_number_is_accepted(self):
        accepted, rejected, _r = ingest([
            row(card_uid="pkmn:s7R:083/067:base:JP", set_code="s7R",
                number="083/067", variant="base", name="Rayquaza VMAX")],
            labelled_path=self._fresh())
        self.assertEqual(rejected, [], "the correct number was refused")
        self.assertEqual(len(accepted), 1)

    def test_another_card_at_that_number_is_not_blocked(self):
        """The rule is keyed on (game, set, name), not on the number alone.
        083/069 is only wrong for this card."""
        accepted, rejected, _r = ingest([
            row(card_uid="pkmn:s7R:083/069:base:JP", set_code="s7R",
                number="083/069", variant="base", name="Some Other Card")],
            labelled_path=self._fresh())
        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)


class ADuplicateIsNotSilentlyMerged(unittest.TestCase):

    def _seeded(self):
        path = os.path.join(tempfile.mkdtemp(), "labelled.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cards": [row()]}, handle)
        return path

    def test_the_same_row_twice_is_refused(self):
        _a, rejected, _r = ingest([row()], labelled_path=self._seeded())
        self.assertIn("already in the set", " ".join(rejected[0]["why"]))

    def test_a_promotion_is_refused_as_an_import(self):
        """Upgrading single_source to verified is a deliberate edit backed by
        a second source. Letting a re-import do it silently would make the
        distinction meaningless."""
        _a, rejected, _r = ingest([row(confidence="single_source")],
                                  labelled_path=self._seeded())
        why = " ".join(rejected[0]["why"])
        self.assertIn("deliberate edit", why)


class TheStoredSetKeepsItsShape(unittest.TestCase):

    def test_every_row_in_the_committed_set_states_a_confidence(self):
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        for card in data["cards"]:
            self.assertIn(card.get("confidence"), CONFIDENCE,
                          f"{card['card_uid']} states no confidence")

    def test_the_committed_set_documents_what_each_value_buys(self):
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["_confidence"]["scored_on"], ["verified"])
        for value in CONFIDENCE:
            self.assertIn(value, data["_confidence"]["values"])

    def test_no_seeded_row_claims_to_be_verified(self):
        """The nine externally-researched rows predate the field and their
        source count was never recorded. Back-filling `verified` would invent
        the very thing the field exists to state."""
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        for card in data["cards"]:
            if card.get("adjudication"):
                continue
            self.assertNotEqual(
                card.get("confidence"), "verified",
                f"{card['card_uid']} was seeded but claims two independent "
                "sources")


if __name__ == "__main__":
    unittest.main()


class TheGateCountsVerifiedRowsOnly(unittest.TestCase):
    """Directly, rather than only through the gate's failure messages. A gate
    that counted the whole pool would report the set as bigger than its ground
    truth -- which is how a gate gets marked passed while the thing it gates
    was never tested."""

    DATA = {"cards": [
        {"card_uid": "a", "confidence": "verified"},
        {"card_uid": "b", "confidence": "single_source"},
        {"card_uid": "c", "confidence": "in_repo"},
        {"card_uid": "d", "confidence": "unstated"},
        {"card_uid": "e"},
    ]}

    def test_only_verified_rows_are_scored(self):
        from tests.test_resolver_gate import scored_rows
        self.assertEqual([c["card_uid"] for c in scored_rows(self.DATA)], ["a"])

    def test_the_pool_is_counted_and_broken_down(self):
        from tests.test_resolver_gate import pool_counts
        counts = pool_counts(self.DATA)
        self.assertEqual(counts["verified"], 1)
        self.assertEqual(counts["single_source"], 1)
        self.assertEqual(counts["in_repo"], 1)
        self.assertEqual(counts["unstated"], 2,
                         "a row with no confidence field must land somewhere "
                         "visible, not vanish from the accounting")
        self.assertEqual(sum(counts.values()), len(self.DATA["cards"]))

    def test_both_numbers_reach_the_failure_message(self):
        """The pool size must never be hidden by the ground-truth size, and
        must never be mistaken for it."""
        from tests.test_resolver_gate import _counts_note
        note = _counts_note(self.DATA)
        self.assertIn("1 verified row", note)
        self.assertIn("pool is 5", note)
        self.assertIn("single_source=1", note)
