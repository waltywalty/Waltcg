"""Ingesting externally-researched identities into the labelled set.

The loader REFUSES rather than repairs. An identity is the one thing in this
project that must not be guessed at, and a loader that fills in a plausible
variant is exactly how a wrong card enters ground truth wearing the costume of
a verified one.
"""

from __future__ import annotations

import collections
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

    def test_verified_means_researched_outside_this_repository(self):
        """`verified` is a claim about two INDEPENDENT external sources. A row
        whose provenance is `verified_from` -- somewhere in this repository --
        cannot be making it, whatever else is true of the row."""
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        for card in data["cards"]:
            if card.get("confidence") != "verified":
                continue
            self.assertEqual(
                card.get("source"), "external_research",
                f"{card['card_uid']} claims `verified` without naming an "
                "external source")
            self.assertNotIn(
                "verified_from", card,
                f"{card['card_uid']} claims both an in-repo provenance and "
                "two independent external sources")

    def test_a_superseded_row_keeps_the_annotations_it_replaced(self):
        """Superseding is a CORRECTION, not a deletion. The incoming row has
        better provenance; that is no reason to lose a `hard_case` tag the old
        row carried, and losing one silently broke a test class that selected
        on it."""
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        superseded = [c for c in data["cards"] if c.get("supersedes")]
        if not superseded:
            self.skipTest("nothing in the set supersedes anything")
        for card in superseded:
            self.assertTrue(card.get("inherited_fields") is not None
                            or card.get("hard_case") is not None,
                            f"{card['card_uid']} superseded a row and recorded "
                            "nothing about what it inherited")

    def test_a_superseded_row_does_not_inherit_a_claim(self):
        """Provenance is the one thing that must NOT carry forward -- the
        point of superseding is that the new row makes its own claim."""
        from resolve.label_cli import _NOT_INHERITED
        for field in ("confidence", "source", "verified_from", "supersedes"):
            self.assertIn(field, _NOT_INHERITED)


if __name__ == "__main__":
    unittest.main()


class TheMutationHarnessIsInTheRepository(unittest.TestCase):
    """"All mutations caught" was the verification backbone for weeks while the
    harness lived in a scratch directory -- unreviewable, un-re-runnable, and
    gone when the session ended. It compared against a HARDCODED failure count
    that the baseline had moved past, so an entire batch reported CAUGHT for
    mutants it had never tested.

    The harness is in the repository now and these are the two rules that
    failure produced."""

    def _source(self):
        path = os.path.join(REPO, "audit", "mutate.py")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_the_baseline_is_measured_not_hardcoded(self):
        """THE BUG, asserted. A literal failure count in the comparison is the
        whole fault -- it silently stops matching the moment the suite changes,
        and every mutant then looks different from a string that never
        appears."""
        import re
        source = self._source()
        self.assertIn("baseline = run_suite()", source)
        self.assertIn("caught = outcome != baseline", source)
        body = source[source.index("def _run("):]
        self.assertIsNone(
            re.search(r'failures=\d', body),
            "audit/mutate.py compares against a hardcoded failure count")

    def test_the_source_is_restored_in_a_finally(self):
        """A harness that times out mid-mutation leaves a sabotaged repository
        behind, and the next test run reports the sabotage as a regression in
        the code under test. That has happened."""
        source = self._source()
        self.assertIn("finally:", source)
        self.assertIn("path.write_text(source)", source)

    def test_a_stale_anchor_is_a_failure_not_a_pass(self):
        """A mutant whose anchor no longer matches is a guard that has quietly
        stopped testing anything -- the same silence in a different costume."""
        source = self._source()
        self.assertIn("errored.append(label)", source)
        self.assertIn("return 1 if (missed or errored) else 0", source)

    def test_it_refuses_to_run_alongside_itself(self):
        """It edits source files in place. A concurrent run -- or an ordinary
        test run started beside one -- reads a sabotaged tree."""
        self.assertIn("AlreadyRunning", self._source())

    def test_every_catalogued_anchor_still_matches_its_file(self):
        """The catalogue is only worth having if it still applies. This is the
        cheap half of a mutation run -- it does not execute anything, it just
        asserts that every mutant would still mutate something."""
        from audit.mutants import MUTANTS
        self.assertGreater(len(MUTANTS), 50)
        stale = []
        for label, relative, old, _new in MUTANTS:
            path = os.path.join(REPO, relative)
            with open(path, encoding="utf-8") as handle:
                if old not in handle.read():
                    stale.append(f"{label} [{relative}]")
        self.assertEqual(stale, [], "mutant anchors no longer in the source: "
                         + "; ".join(stale))

    def test_no_mutant_is_catalogued_twice(self):
        from audit.mutants import MUTANTS
        seen = [(m[0], m[1]) for m in MUTANTS]
        self.assertEqual(len(seen), len(set(seen)))


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


class TheSetCodeIsNormalisedToTheCatalog(unittest.TestCase):
    """A labelled row's IDENTITY is non-circular; its `set_code` is a KEY, and
    a key that matches nothing scores nothing.

    The mapping is declared in `SET_CODE_ALIASES` and every application is
    reported, so this is a normalisation you can audit rather than a coercion
    you cannot see."""

    def _fresh(self):
        path = os.path.join(tempfile.mkdtemp(), "labelled.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cards": []}, handle)
        return path

    def test_a_known_alias_is_rewritten(self):
        accepted, rejected, report = ingest([
            row(card_uid="pkmn:sv151:199/165:sir:EN", set_code="sv151",
                number="199/165", variant="sir", language="EN",
                name="Charizard ex")], labelled_path=self._fresh())
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["set_code"], "sv03.5")
        self.assertEqual(report["_aliased"], 1)

    def test_the_card_uid_is_rebuilt_around_the_new_code(self):
        """Renaming the field and leaving the uid alone would produce a row
        whose stated identity disagrees with its own fields -- the exact thing
        the uid check rejects, introduced by the fix for something else."""
        accepted, _r, _rep = ingest([
            row(card_uid="pkmn:swsh07:215/203:alt_art:EN", set_code="swsh07",
                number="215/203", variant="alt_art", language="EN",
                name="Umbreon VMAX")], labelled_path=self._fresh())
        self.assertEqual(accepted[0]["card_uid"],
                         "pkmn:swsh7:215/203:alt_art:EN")

    def test_the_original_spelling_is_kept(self):
        """What the source actually said survives, so the normalisation can be
        checked rather than trusted."""
        accepted, _r, _rep = ingest([
            row(card_uid="pkmn:sv151:199/165:sir:EN", set_code="sv151",
                number="199/165", variant="sir", language="EN",
                name="Charizard ex")], labelled_path=self._fresh())
        self.assertEqual(accepted[0]["set_code_as_sourced"], "sv151")

    def test_an_unknown_code_passes_through_untouched(self):
        """The table lists spellings we have RECONCILED, not sets that exist.
        A code absent from it is one nobody has checked, which is different
        from a wrong one -- rewriting or blanking it would invent a verdict."""
        accepted, rejected, report = ingest([row()],
                                            labelled_path=self._fresh())
        self.assertEqual(rejected, [])
        self.assertEqual(accepted[0]["set_code"], "sv2a")
        self.assertNotIn("set_code_as_sourced", accepted[0])
        self.assertEqual(report["_aliased"], 0)

    def test_the_alias_is_scoped_to_a_game_and_language(self):
        from resolve.identity import canonical_set_code
        self.assertEqual(canonical_set_code("pkmn", "EN", "sv151")[0], "sv03.5")
        self.assertEqual(canonical_set_code("pkmn", "JP", "sv151")[0], "sv151")
        self.assertEqual(canonical_set_code("optcg", "EN", "sv151")[0], "sv151")

    def test_every_alias_records_what_it_was_checked_against(self):
        """"SV: 151 is probably sv151" is a guess. "sv03.5 holds 199 Charizard
        ex, which is what the row says" is a check, and the difference has to
        be written down."""
        from resolve.identity import SET_CODE_ALIASES
        self.assertTrue(SET_CODE_ALIASES)
        for key, entry in SET_CODE_ALIASES.items():
            self.assertTrue(entry.get("code"), key)
            self.assertTrue(entry.get("why"), key)
            checked = entry.get("verified_against", "")
            # A source AND a card that was actually found in it. "probably
            # sv151" is a guess; "sv03.5 holds 199 Charizard ex" is a check,
            # and the difference is whether a name appears.
            self.assertTrue(
                any(src in checked for src in ("targets.json", "apitcg")),
                f"{key} names no source it was verified against")
            self.assertGreater(
                len(checked), 60,
                f"{key} was aliased without saying which cards confirmed it")

    def test_a_code_we_could_not_verify_is_recorded_as_such(self):
        """An unaliased code and an unverifiable one behave identically -- both
        pass through -- and only one of them is a decision. Recording the
        second is how you tell later that somebody looked."""
        from resolve.identity import (SET_CODE_ALIASES, UNVERIFIED_SET_CODES,
                                      canonical_set_code)
        self.assertTrue(UNVERIFIED_SET_CODES)
        for key, why in UNVERIFIED_SET_CODES.items():
            self.assertNotIn(key, SET_CODE_ALIASES,
                             f"{key} is both aliased and unverified")
            self.assertGreater(len(why), 40, f"{key} has no reason recorded")
            # And it must still pass through untouched.
            self.assertEqual(canonical_set_code(*key)[0], key[2])


class SupersedingAnUnstatedRow(unittest.TestCase):
    """`unstated` records no source count, so it is not a competing claim --
    there is no information in it that a sourced row lacks. Replacing it is a
    claim replacing a non-claim, and it still has to be deliberate and
    visible."""

    def _seeded(self, confidence="unstated", **extra):
        path = os.path.join(tempfile.mkdtemp(), "labelled.json")
        existing = row(confidence=confidence, hard_case="name_is_not_unique",
                       artist="Oswaldo KATO", **extra)
        existing.pop("source", None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cards": [existing]}, handle)
        return path

    def test_it_does_not_happen_without_the_flag(self):
        _a, rejected, _r = ingest([row()], labelled_path=self._seeded())
        self.assertEqual(len(rejected), 1)
        self.assertIn("--supersede-unstated", " ".join(rejected[0]["why"]))

    def test_with_the_flag_the_sourced_row_wins(self):
        path = self._seeded()
        accepted, rejected, report = ingest([row()], labelled_path=path,
                                            supersede_unstated=True)
        self.assertEqual(rejected, [])
        self.assertEqual(report["_superseded"], 1)
        self.assertEqual(accepted[0]["confidence"], "verified")

    def test_the_old_row_is_removed_not_duplicated(self):
        """Two rows at one card_uid would double-count the combo and score the
        same card twice."""
        path = self._seeded()
        ingest([row()], labelled_path=path, supersede_unstated=True)
        with open(path, encoding="utf-8") as handle:
            cards = json.load(handle)["cards"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["confidence"], "verified")

    def test_a_supersedes_reference_is_recorded(self):
        """CLAUDE.md: corrections are new rows with a `supersedes` reference.
        Nothing is edited in place and nothing vanishes unrecorded."""
        accepted, _r, _rep = ingest([row()], labelled_path=self._seeded(),
                                    supersede_unstated=True)
        self.assertEqual(accepted[0]["supersedes"], row()["card_uid"])
        self.assertEqual(accepted[0]["supersedes_confidence"], "unstated")

    def test_annotations_carry_forward(self):
        """Superseding is a CORRECTION, not a deletion. Losing a `hard_case`
        tag silently broke a test class that selected on it."""
        accepted, _r, _rep = ingest([row()], labelled_path=self._seeded(),
                                    supersede_unstated=True)
        self.assertEqual(accepted[0]["hard_case"], "name_is_not_unique")
        self.assertEqual(accepted[0]["artist"], "Oswaldo KATO")
        self.assertEqual(accepted[0]["inherited_fields"],
                         ["artist", "hard_case"])

    def test_the_new_row_wins_where_it_has_a_value(self):
        path = self._seeded()
        accepted, _r, _rep = ingest([row(name="Corrected Name")],
                                    labelled_path=path,
                                    supersede_unstated=True)
        self.assertEqual(accepted[0]["name"], "Corrected Name")

    def test_provenance_is_never_inherited(self):
        """The point of superseding is that the new row makes its OWN claim.
        Inheriting `confidence` or `verified_from` would let a discarded claim
        survive its replacement."""
        path = self._seeded()
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["cards"][0]["verified_from"] = "contracts/fixtures"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        accepted, _r, _rep = ingest([row()], labelled_path=path,
                                    supersede_unstated=True)
        self.assertNotIn("verified_from", accepted[0])
        self.assertEqual(accepted[0]["confidence"], "verified")

    def test_a_stated_confidence_is_never_superseded(self):
        """`single_source` IS a claim. Overwriting it needs a human, not a
        flag -- otherwise a re-import silently promotes."""
        for confidence in ("single_source", "verified", "in_repo"):
            path = self._seeded(confidence=confidence)
            _a, rejected, _r = ingest([row()], labelled_path=path,
                                      supersede_unstated=True)
            self.assertEqual(
                len(rejected), 1,
                f"a {confidence!r} row was superseded by an import")


class TheCollapseDetectorDetectsACollapse(unittest.TestCase):
    """A guard on the blocking-failure guard. It currently passes because
    nothing in the set collapses; that is indistinguishable from a check that
    cannot fail, so the check is pointed at a set that DOES collapse."""

    def test_two_printings_at_one_identity_are_caught(self):
        from tests.test_resolver_gate import BlockingFailuresAgainstTheRealSet
        from resolve.resolver import Resolver

        merged = [
            {"card_uid": "optcg:op01:OP01-025:base:EN", "game": "optcg",
             "set_code": "op01", "number": "OP01-025", "variant": "base",
             "language": "EN", "name": "Roronoa Zoro"},
            # SAME uid, different variant: the merge, made real.
            {"card_uid": "optcg:op01:OP01-025:base:EN", "game": "optcg",
             "set_code": "op01", "number": "OP01-025", "variant": "parallel",
             "language": "EN", "name": "Roronoa Zoro"},
        ]

        case = BlockingFailuresAgainstTheRealSet("test_one_piece_op01_025")
        case.by_uid = {"optcg:op01:OP01-025:base:EN": merged[0],
                       "optcg:op01:OP01-025:parallel:EN": merged[1]}
        case.resolver = Resolver(merged)
        with self.assertRaises(AssertionError) as caught:
            case._check("synthetic collapse",
                        ("optcg:op01:OP01-025:base:EN",
                         "optcg:op01:OP01-025:parallel:EN"))
        self.assertIn("BLOCKING", str(caught.exception))


class OneNumberCannotNameTwoCards(unittest.TestCase):
    """THE CHECK THAT CAUGHT A TRANSCRIPTION SWAP.

    Bandai runs one code system across English, Japanese and Simplified
    Chinese, so `OP01-002` names one card in all three. Batch 2 had it as
    Monkey D. Luffy in Chinese where English and Japanese had Trafalgar Law --
    and nothing in either row was wrong on its own. The uid was right, the
    number was right, and the name was a real card's name. Only the pairing
    was wrong, and only across languages was it visible."""

    def _cards(self, *rows):
        return [dict({"game": "optcg", "set_code": "op01",
                      "number": "OP01-002", "variant": "base"}, **r)
                for r in rows]

    def test_a_swap_is_caught(self):
        from resolve.identity import cross_language_name_disagreements
        found = cross_language_name_disagreements(self._cards(
            {"card_uid": "a", "language": "EN", "name": "Trafalgar Law"},
            {"card_uid": "b", "language": "CN-S", "name": "Monkey D. Luffy"}))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][2], "OP01-002")

    def test_punctuation_is_not_a_disagreement(self):
        """`Monkey.D.Luffy` and `Monkey D. Luffy` are one card written two
        ways. Flagging that would bury the real ones in noise."""
        from resolve.identity import cross_language_name_disagreements
        self.assertEqual(cross_language_name_disagreements(self._cards(
            {"card_uid": "a", "language": "EN", "name": "Monkey.D.Luffy"},
            {"card_uid": "b", "language": "JP", "name": "Monkey D. Luffy"})), [])

    def test_a_translation_is_not_a_disagreement(self):
        """`路飞` IS `Monkey.D.Luffy`, and nothing here can know that -- it
        would need a translation table this project does not have. So a
        cross-script pair is NOT COMPARABLE, which is a third answer. Comparing
        anyway would report every correctly-translated card as a
        contradiction."""
        from resolve.identity import cross_language_name_disagreements
        self.assertEqual(cross_language_name_disagreements(self._cards(
            {"card_uid": "a", "language": "EN", "name": "Monkey.D.Luffy"},
            {"card_uid": "b", "language": "CN-S", "name": "路飞"},
            {"card_uid": "c", "language": "JP", "name": "モンキー・D・ルフィ"})), [])

    def test_pokemon_is_not_checked(self):
        """`173/165` and `173/151` are different cards -- the whole CN-S
        renumbering problem. Running this check there would report every
        Simplified Chinese card as a contradiction."""
        from resolve.identity import cross_language_name_disagreements
        rows = [{"card_uid": "a", "game": "pkmn", "set_code": "sv2a",
                 "number": "025/165", "variant": "base", "language": "JP",
                 "name": "Pikachu"},
                {"card_uid": "b", "game": "pkmn", "set_code": "151C",
                 "number": "025/165", "variant": "base", "language": "CN-S",
                 "name": "Something Else"}]
        self.assertEqual(cross_language_name_disagreements(rows), [])

    def test_set_code_case_does_not_hide_a_disagreement(self):
        """The two defects met: uppercase and lowercase spellings of one set
        put the rows in different buckets, so the name check could not see
        across them."""
        from resolve.identity import cross_language_name_disagreements
        found = cross_language_name_disagreements([
            {"card_uid": "a", "game": "optcg", "set_code": "OP01",
             "number": "OP01-121", "variant": "base", "language": "EN",
             "name": "Monkey.D.Luffy"},
            {"card_uid": "b", "game": "optcg", "set_code": "op01",
             "number": "OP01-121", "variant": "base", "language": "EN",
             "name": "Yamato"}])
        self.assertEqual(len(found), 1)

    def test_the_committed_set_is_clean(self):
        from resolve.identity import cross_language_name_disagreements
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            cards = json.load(handle)["cards"]
        found = cross_language_name_disagreements(cards)
        self.assertEqual(found, [], f"one number names two cards: {found}")


class EveryCorrectionIsLogged(unittest.TestCase):
    """Cross-batch disagreement is the mechanism working, so the catches are
    kept as events rather than quietly edited away. A correction with no record
    is indistinguishable from data that was always right."""

    def _data(self):
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_log_exists_and_has_the_three_events(self):
        events = {e["event"] for e in self._data().get("_corrections", [])}
        self.assertIn("batch2-name-swap", events)
        self.assertIn("seed-named-the-wrong-card-at-OP01-121", events)
        self.assertIn("one-piece-set-code-case", events)

    def test_every_event_names_what_caught_it_and_the_evidence(self):
        for entry in self._data().get("_corrections", []):
            self.assertTrue(entry.get("caught_by"), entry["event"])
            self.assertGreater(len(entry.get("evidence", "")), 60,
                               entry["event"])
            self.assertGreater(len(entry.get("what", "")), 60, entry["event"])

    def test_every_corrected_row_carries_its_previous_value(self):
        for card in self._data()["cards"]:
            correction = card.get("corrected")
            if not correction:
                continue
            self.assertIn("was", correction, card["card_uid"])
            self.assertIn("caught_by", correction, card["card_uid"])
            self.assertNotEqual(correction["was"],
                                card.get(correction["field"]),
                                card["card_uid"])

    def test_a_dropped_duplicate_is_recorded_not_just_deleted(self):
        entry = next(e for e in self._data()["_corrections"]
                     if e["event"] == "one-piece-set-code-case")
        self.assertEqual(len(entry["dropped_as_duplicate"]), 3)
        for row in entry["dropped_as_duplicate"]:
            self.assertEqual(row["confidence"], "in_repo",
                             "a scored row was dropped as a duplicate")


class NoTwoRowsShareAnIdentity(unittest.TestCase):
    """Two rows at one card_uid double-count the combo and score one card
    twice. Two rows differing only in set-code CASE are the same thing with
    the collision hidden."""

    def _cards(self):
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)["cards"]

    def test_no_duplicate_card_uid(self):
        seen = collections.Counter(c["card_uid"] for c in self._cards())
        self.assertEqual([u for u, n in seen.items() if n > 1], [])

    def test_no_identity_differs_only_by_set_code_case(self):
        seen = collections.defaultdict(set)
        for card in self._cards():
            key = (card["game"], card["set_code"].lower(), card["number"],
                   card["variant"], card["language"])
            seen[key].add(card["set_code"])
        split = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
        self.assertEqual(split, {},
                         "one card exists under two set-code spellings")

    def test_one_piece_set_codes_match_the_catalogs_casing(self):
        """apitcg stores One Piece sets as `op01.json` and the catalog derives
        the code from that filename."""
        for card in self._cards():
            if card["game"] != "optcg":
                continue
            self.assertEqual(card["set_code"], card["set_code"].lower(),
                             card["card_uid"])


class PromotionIsDeliberateAndNamed(unittest.TestCase):
    """A re-import must never promote -- that is how a single-source row
    quietly becomes ground truth because somebody sent the same file twice."""

    def _seeded(self, confidence="single_source"):
        path = os.path.join(tempfile.mkdtemp(), "labelled.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cards": [row(confidence=confidence)]}, handle)
        return path

    def test_single_source_to_verified_is_the_only_upgrade(self):
        from resolve.label_cli import UPGRADE_PATH
        self.assertEqual(UPGRADE_PATH, {("single_source", "verified")})

    def test_it_records_the_second_source(self):
        from resolve.label_cli import upgrade
        path = self._seeded()
        card, why = upgrade(row()["card_uid"], "verified", "other:PriceCharting",
                            labelled_path=path, date="2026-08-18")
        self.assertEqual(why, "")
        self.assertEqual(card["confidence"], "verified")
        self.assertEqual(card["upgraded"]["second_source"], "other:PriceCharting")
        self.assertEqual(card["upgraded"]["from"], "single_source")

    def test_an_unnamed_source_is_refused(self):
        """`verified` claims two independent sources agree. An unnamed second
        source cannot be checked, so the claim would be unauditable."""
        from resolve.label_cli import upgrade
        card, why = upgrade(row()["card_uid"], "verified", None,
                            labelled_path=self._seeded())
        self.assertIsNone(card)
        self.assertIn("second-source is required", why)

    def test_other_confidences_are_not_a_lower_rung(self):
        """`in_repo` and `unstated` are different PROVENANCE, not less of the
        same thing. Promoting them would claim external corroboration that was
        never gathered."""
        from resolve.label_cli import upgrade
        for confidence in ("in_repo", "unstated", "verified"):
            card, why = upgrade(row()["card_uid"], "verified", "X",
                                labelled_path=self._seeded(confidence))
            self.assertIsNone(card, confidence)
            self.assertIn("not a promotion", why)

    def test_the_upgrade_that_happened_is_on_the_row(self):
        path = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
        with open(path, encoding="utf-8") as handle:
            cards = json.load(handle)["cards"]
        upgraded = [c for c in cards if c.get("upgraded")]
        self.assertTrue(upgraded, "no upgrade recorded in the set")
        for card in upgraded:
            self.assertEqual(card["confidence"], card["upgraded"]["to"])
            self.assertTrue(card["upgraded"]["second_source"])


class TheMutantCountIsSealed(unittest.TestCase):
    """A run that discovers half the catalogue and reports every one of them
    CAUGHT looks exactly like a clean run. So the discovered count is asserted
    against a checked-in number before anything else happens, and a
    silently-skipped subset reads as FAILURE rather than as green.

    Same instrument as the ledger seal, pointed at the auditor."""

    def _seal(self):
        path = os.path.join(REPO, "audit", "mutant_seal.json")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def test_the_seal_matches_the_catalogue(self):
        from audit.mutants import MUTANTS
        self.assertEqual(len(MUTANTS), self._seal()["expected_mutants"],
                         "the catalogue and its seal disagree. Raise "
                         "`expected_mutants` in the SAME commit that adds "
                         "mutants -- a seal updated afterwards to match a "
                         "broken run is not a seal.")

    def test_the_seal_says_why_it_exists(self):
        note = self._seal()["_note"]
        self.assertIn("silently-skipped", note)
        self.assertIn("same commit", note)

    def test_a_wrong_count_fails(self):
        from audit.mutate import check_seal
        self.assertFalse(check_seal(1))
        self.assertFalse(check_seal(self._seal()["expected_mutants"] - 1))
        self.assertTrue(check_seal(self._seal()["expected_mutants"]))

    def test_a_missing_seal_fails_rather_than_passes(self):
        """A missing seal is exactly what a deleted catalogue looks like."""
        import audit.mutate as harness
        import pathlib
        original = harness.SEAL
        try:
            harness.SEAL = pathlib.Path("/nonexistent/mutant_seal.json")
            self.assertFalse(harness.check_seal(111))
        finally:
            harness.SEAL = original


class TheFullMutationRunHappensSomewhereUnskippable(unittest.TestCase):
    """Filtered local subsets are fine -- they are how the harness is actually
    used -- as long as the whole catalogue runs somewhere nobody can quietly
    not run it."""

    def _workflow(self):
        import yaml
        path = os.path.join(REPO, ".github", "workflows", "mutate.yml")
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _steps(self):
        return self._workflow()["jobs"]["full-run"]["steps"]

    def test_it_runs_weekly_and_on_a_change_to_the_auditor(self):
        workflow = self._workflow()
        triggers = workflow.get("on", workflow.get(True))
        self.assertIn("schedule", triggers)
        self.assertIn("push", triggers)
        paths = triggers["push"]["paths"]
        self.assertIn("audit/**", paths,
                      "the harness is the one thing that must be re-verified "
                      "after it is edited")

    def test_the_seal_is_checked_before_the_run(self):
        names = [s.get("name", "") for s in self._steps()]
        seal = names.index("Mutant-count seal")
        run = names.index("Full mutation run")
        self.assertLess(seal, run,
                        "an hour of mutants over an unsealed catalogue proves "
                        "nothing")

    def test_the_run_is_not_filtered(self):
        step = next(s for s in self._steps()
                    if s.get("name") == "Full mutation run")
        self.assertNotIn("--only", step["run"],
                         "the unskippable run is filtered, which is the thing "
                         "it exists to compensate for")

    def test_the_seal_step_can_fail_the_job(self):
        """`continue-on-error` here would make the seal decorative."""
        for name in ("Mutant-count seal", "Full mutation run"):
            step = next(s for s in self._steps() if s.get("name") == name)
            self.assertFalse(step.get("continue-on-error"), name)

    def test_the_report_survives_a_failed_run(self):
        step = next(s for s in self._steps()
                    if s.get("name") == "Upload the report")
        self.assertEqual(step.get("if"), "always()")

    def test_no_step_embeds_a_heredoc(self):
        """Runs #4 and #7 were both shell logic in YAML that no test could
        reach."""
        offenders = [s.get("name") for s in self._steps()
                     if "<<" in (s.get("run") or "")]
        self.assertEqual(offenders, [])
