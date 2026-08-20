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
            self.assertIn("targets.json", entry.get("verified_against", ""),
                          f"{key} was aliased without naming what it was "
                          "verified against")


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
