"""Resolver precision and recall against the hand-labelled set.

TWO tests, and they measure different things on purpose:

* `ResolverQuality` scores the resolver on whatever labelled cards exist. It
  passes or fails on the resolver's own merit.
* `TheLabelledSetIsComplete` asserts the SET is big enough for that score to
  mean anything. It fails until the set has 200 cards across all 8 combos with
  20 hard cases.

Both are needed because a precision of 1.00 on twelve cards is not evidence
about a resolver -- it is evidence about twelve cards. Reporting the first
without the second is how a gate gets marked passed while the thing it gates
was never tested.

The second test is EXPECTED TO FAIL until the set is built. It is a red test
that names exactly what is missing, which is the honest state of a gate that
has not been met.
"""

from __future__ import annotations

import collections
import inspect
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.resolver import Resolver, SIGNAL_THRESHOLD  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELLED = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")


# Only `verified` rows -- two INDEPENDENT external sources agreeing -- are
# ground truth. A single-source identity is one transcription error away from
# being wrong, and a precision figure computed over it measures the source
# rather than the resolver.
SCORED = ("verified",)


def load():
    with open(LABELLED, encoding="utf-8") as handle:
        return json.load(handle)


def scored_rows(data):
    """The rows precision may be computed on."""
    return [c for c in data["cards"] if c.get("confidence") in SCORED]


def pool_counts(data):
    """Every row, by confidence. Reported alongside the scored count so the
    size of the candidate pool is never hidden by the size of ground truth --
    and never mistaken for it."""
    return collections.Counter(c.get("confidence", "unstated")
                               for c in data["cards"])


def _counts_note(data):
    counts = pool_counts(data)
    return (f"scored on {len(scored_rows(data))} verified row(s); "
            f"pool is {len(data['cards'])} ("
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + ")")


class ResolverQuality(unittest.TestCase):
    """Precision: of the matches the resolver was willing to use in a signal,
    how many were right. Recall: of the cards it should have matched, how many
    it did.

    Precision is the gated number because the cost is asymmetric. A missed card
    is a card you do not trade. A wrongly matched card is a confident price on
    the wrong asset, and nothing downstream looks wrong."""

    @classmethod
    def setUpClass(cls):
        cls.data = load()
        # The resolver's INDEX may use every row -- knowing about a card is not
        # a claim about it. Only the scored rows are used as truth.
        cls.pool = cls.data["cards"]
        cls.cards = scored_rows(cls.data)
        cls.resolver = Resolver(cls.pool)

    def setUp(self):
        if not self.cards:
            self.skipTest(
                "no `verified` rows to score on -- " + _counts_note(self.data)
                + ". This is a SKIP rather than a pass: a precision of 1.00 "
                "over zero rows is not evidence, and reporting it as green is "
                "the failure this split exists to prevent. "
                "`python -m resolve.label_cli ingest --rows FILE`.")

    def _score(self, records):
        used = right = should = 0
        wrong = []
        for record, truth in records:
            should += 1
            result = self.resolver.resolve(record)
            if result.usable_in_signals:
                used += 1
                if result.card_uid == truth:
                    right += 1
                else:
                    wrong.append((truth, result.card_uid, result.confidence))
        precision = right / used if used else 1.0
        recall = right / should if should else 0.0
        return precision, recall, wrong

    def _self_records(self):
        """Each labelled card, presented as a provider would present it.

        WHAT THIS MEASURES, AND WHAT IT DOES NOT. The record is built FROM THE
        LABELLED ROW and the expected answer is that row's own `card_uid` --
        which is `{game}:{set_code}:{number}:{variant}:{language}`, derived
        from the same fields. Input and expectation are the same data twice.

        So this is a NO-MERGE / NO-COLLISION CHECK, not a resolution check. It
        proves the resolver keeps 290 distinct rows distinct and does not fold
        two printings into one -- which is a real property, and exactly the one
        that broke when `_p1`/`_p2` suffixes were dropped and 286 rows merged.
        It does NOT prove the resolver can identify a card, because nothing
        independent is being identified.

        Two consequences worth carrying wherever the number is quoted:

          * A LABEL ERROR IS INVISIBLE HERE. `name` is not in the uid, so a row
            naming the wrong character resolves exactly as well as a correct
            one. All three known errors in this set are of that class.
          * THEREFORE `e <= 1 - p` DOES NOT HOLD on this measurement. That
            bound needs the resolver's input to be independent of the label,
            and here it is the label. Correlated error is total, not residual.
            See ADR-0056.

        The bound becomes available when precision is measured CATALOG ENTRY IN
        -> LABELLED UID OUT, because then a wrong label disagrees with a
        correctly resolved catalog entry and lands in `1 - p`.
        """
        return [({"source": "probe", "game": c["game"], "language": c["language"],
                  "number": c["number"], "set_code": c["set_code"],
                  "variant": c["variant"], "name": c["name"]}, c["card_uid"])
                for c in self.cards]

    def test_precision_meets_the_gate(self):
        precision, recall, wrong = self._score(self._self_records())
        self.assertGreaterEqual(
            precision, self.data["_gate"]["precision_threshold"],
            f"self-record precision {precision:.4f} "
            f"({_counts_note(self.data)}); wrong matches: {wrong}. NOTE: this "
            "is a no-merge/no-collision check, not a resolution check -- the "
            "input is built from the labelled row and the expected uid is "
            "derived from the same fields. See `_self_records`.")

    def test_recall_is_reported_even_when_precision_passes(self):
        precision, recall, _ = self._score(self._self_records())
        self.assertGreaterEqual(recall, self.data["_gate"]["recall_threshold"],
                                f"recall {recall:.4f}")

    def test_every_language_printing_resolves_to_its_own_uid(self):
        """GOAL D1. The one that would be silently catastrophic: three
        printings of OP01-121 must not collapse into one card."""
        by_number = collections.defaultdict(set)
        for card in self.cards:
            by_number[(card["game"], card["number"])].add(card["card_uid"])
        multilingual = {k: v for k, v in by_number.items() if len(v) > 1}
        self.assertTrue(multilingual,
                        "no card in the set exists in more than one language, "
                        "so the merge this test guards against is untested")
        for (game, number), uids in multilingual.items():
            resolved = set()
            for card in self.cards:
                if (card["game"], card["number"]) != (game, number):
                    continue
                result = self.resolver.resolve(
                    {"source": "probe", "game": card["game"],
                     "language": card["language"], "number": card["number"],
                     "set_code": card["set_code"], "variant": card["variant"],
                     "name": card["name"]})
                resolved.add(result.card_uid)
            self.assertEqual(resolved, uids,
                             f"{game} {number}: printings collapsed")

    def test_a_record_without_a_language_is_never_resolved(self):
        """Language is part of the uid, so a record that omits it could be any
        printing. Refusing is the only correct answer."""
        for card in self.cards:
            result = self.resolver.resolve(
                {"source": "probe", "game": card["game"],
                 "number": card["number"], "set_code": card["set_code"],
                 "name": card["name"]})
            self.assertIsNone(result.card_uid, card["card_uid"])
            self.assertFalse(result.usable_in_signals)

    def test_a_low_confidence_fuzzy_match_is_excluded_from_signals(self):
        """It is still WRITTEN -- the review queue needs it -- but no signal
        may use it. card_uid.md: anything fuzzy below 0.9 is excluded."""
        from resolve.resolver import Resolution
        low = Resolution("pkmn:sv3:223/197:sir:EN", 0.85, "fuzzy", "test")
        self.assertFalse(low.usable_in_signals)
        self.assertTrue(low.needs_review)
        high = Resolution("pkmn:sv3:223/197:sir:EN", 0.95, "fuzzy", "test")
        self.assertTrue(high.usable_in_signals)
        self.assertEqual(SIGNAL_THRESHOLD, 0.90)

    def test_a_wrong_name_at_the_same_number_does_not_resolve(self):
        """The adversarial direction: right number, right language, wrong card.
        This is what a bad fuzzy match looks like in the wild."""
        card = self.cards[0]
        result = self.resolver.resolve(
            {"source": "probe", "game": card["game"], "language": card["language"],
             "number": card["number"], "set_code": card["set_code"],
             "name": "Completely Different Creature"})
        self.assertFalse(
            result.usable_in_signals,
            f"resolved a mismatched name at {result.confidence:.2f}")


class TheLabelledSetIsComplete(unittest.TestCase):
    """THE GATE. Fails until the set can support the claim made about it.

    This test is currently RED and that is the correct state: GOAL D1 requires
    200 hand-labelled cards across all 8 combos, and 12 exist. A resolver
    scored on 12 cards has not been scored.
    """

    def setUp(self):
        self.data = load()
        self.cards = scored_rows(self.data)
        self.gate = self.data["_gate"]

    def test_two_hundred_cards(self):
        self.assertGreaterEqual(
            len(self.cards), self.gate["required_cards"],
            f"{len(self.cards)} of {self.gate['required_cards']} VERIFIED "
            f"cards ({_counts_note(self.data)}). Single-source rows are "
            f"candidates and do not count. {self.data['_needed']['why']}")

    def test_all_eight_combinations_are_represented(self):
        present = {f"{c['game']}:{c['language']}" for c in self.cards}
        missing = sorted(set(self.gate["required_per_combo"]) - present)
        self.assertFalse(missing, f"no labelled cards for: {missing}")

    def test_no_combo_is_below_the_detection_floor(self):
        """Below 20 a combo running at 80% precision goes undetected 4% of the
        time. A per-combo count under the floor means that combo is untested,
        not lightly tested."""
        import collections
        have = collections.Counter(f"{c['game']}:{c['language']}"
                                   for c in self.cards)
        floor = self.gate["min_per_combo"]
        below = {combo: have.get(combo, 0)
                 for combo in self.gate["required_per_combo"]
                 if have.get(combo, 0) < floor}
        self.assertFalse(below, f"below the {floor}-card detection floor: {below}")

    def test_each_combo_meets_its_own_target(self):
        import collections
        have = collections.Counter(f"{c['game']}:{c['language']}"
                                   for c in self.cards)
        short = {combo: (have.get(combo, 0), want)
                 for combo, want in self.gate["required_per_combo"].items()
                 if have.get(combo, 0) < want}
        self.assertFalse(short, f"(have, want) per combo: {short}")

    def test_twenty_hard_cases(self):
        from resolve.hard_cases import hard_cases_of
        hard = [c for c in self.cards if hard_cases_of(c)]
        self.assertGreaterEqual(
            len(hard), self.gate["required_hard_cases"],
            f"{len(hard)} of {self.gate['required_hard_cases']} hard cases")

    def test_every_hard_case_kind_is_covered(self):
        from resolve.hard_cases import hard_cases_of
        kinds = {k for c in self.cards for k in hard_cases_of(c)}
        # `same_printed_number_different_treatment` is REQUIRED because C6 is
        # one of the three blocking failures, and a gate that does not demand a
        # case for it is missing the class it most needs to measure.
        # `same_number_different_product` is REQUIRED for the same reason as
        # C6's kind: it is the shape where two rows differ in exactly ONE
        # field, and here that field is `set_code` -- the one most likely to be
        # dropped, defaulted or normalised on the way in. C6 differs by
        # `variant`; this differs by `set_code`; both are one edit from a merge.
        for required in ("same_art_different_language", "reprint",
                         "alt_art_variant", "promo_vs_set",
                         "same_printed_number_different_treatment",
                         "same_number_different_product",
                         # Both axes moving at once. A resolver can pass
                         # set-only and variant-only and still mishandle this.
                         "same_number_new_set_new_variant"):
            self.assertIn(required, kinds, f"no {required} case in the set")


class TheSeededCardsAreTraceable(unittest.TestCase):
    """Nothing in the labelled set is invented. Each row names where in this
    repository its identity came from, so a later reader can check rather than
    trust."""

    def test_every_card_names_its_provenance(self):
        for card in load()["cards"]:
            self.assertTrue(card.get("verified_from") or card.get("source"),
                            f"{card['card_uid']} has no provenance")

    def test_externally_researched_rows_are_marked_as_such(self):
        """The non-circularity marker. A card sourced from the same catalogs
        the resolver reads cannot score the resolver -- it scores the catalog.
        `source: external_research` is the claim that a row came from outside,
        and it has to be visible to be checkable."""
        external = [c for c in load()["cards"]
                    if c.get("source") == "external_research"]
        self.assertTrue(external, "no externally-researched rows in the set")
        for card in external:
            self.assertNotIn("verified_from", card,
                             f"{card['card_uid']} claims both an in-repo "
                             "provenance and external research; one of them "
                             "is wrong")

    def test_the_file_says_it_is_incomplete(self):
        data = load()
        self.assertIn("INCOMPLETE", data["_status"])
        self.assertGreater(data["_needed"]["short_by"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class BlockingFailures(unittest.TestCase):
    """THREE MERGES THAT FAIL THE RESOLVER OUTRIGHT.

    Not scored, not averaged, not traded off against precision. A resolver at
    0.99 that commits any one of these is not a resolver at 0.99 with a rough
    edge -- it is a resolver that produces a confident price on the wrong
    asset, and nothing downstream looks wrong. An aggregate can absorb one
    error in a hundred. These are the errors an aggregate must not be allowed
    to absorb.

    Each one is a MERGE: two printings that share every field the naive key
    looks at, differing only in the one this project insists on keeping.

    They run against a synthetic three-card set, deliberately, so they hold
    from the first commit -- before the labelled set exists, and regardless of
    what is in it. A blocking failure that only fires once you have 250 rows is
    a blocking failure that was never armed.
    """

    def _resolver(self, cards):
        return Resolver(cards)

    def _card(self, uid, game, set_code, number, variant, language, name):
        return {"card_uid": uid, "game": game, "set_code": set_code,
                "number": number, "variant": variant, "language": language,
                "name": name}

    def _record(self, card):
        return {"source": "probe", "game": card["game"],
                "language": card["language"], "number": card["number"],
                "set_code": card["set_code"], "variant": card["variant"],
                "name": card["name"]}

    # -- 1 -----------------------------------------------------------------

    def test_english_199_does_not_resolve_to_japanese_201(self):
        """EN 199/165 and JP 201/165 are the same art in two markets. Same
        set code, same name, same rarity tier -- and two price series that
        have moved apart by triple digits before now."""
        cards = [
            self._card("pkmn:sv2a:199/165:sir:EN", "pkmn", "sv2a", "199/165",
                       "sir", "EN", "Charizard ex"),
            self._card("pkmn:sv2a:201/165:sar:JP", "pkmn", "sv2a", "201/165",
                       "sar", "JP", "Charizard ex"),
        ]
        resolver = self._resolver(cards)
        for card in cards:
            got = resolver.resolve(self._record(card))
            self.assertEqual(
                got.card_uid, card["card_uid"],
                f"BLOCKING: {card['card_uid']} resolved to {got.card_uid}. "
                "The English secret rare and its Japanese counterpart were "
                "merged; every comp for one is now a comp for the other.")

    def test_the_english_number_never_reaches_the_japanese_card(self):
        """The adversarial direction: an English number offered as Japanese
        must not find the Japanese card by falling back on the name."""
        cards = [self._card("pkmn:sv2a:201/165:sar:JP", "pkmn", "sv2a",
                            "201/165", "sar", "JP", "Charizard ex")]
        got = self._resolver(cards).resolve(
            {"source": "probe", "game": "pkmn", "language": "JP",
             "number": "199/165", "set_code": "sv2a", "name": "Charizard ex"})
        self.assertNotEqual(
            got.card_uid, "pkmn:sv2a:201/165:sar:JP",
            "BLOCKING: the English collector number resolved to the Japanese "
            "card on the strength of a matching name.")

    # -- 2 -----------------------------------------------------------------

    def test_a_one_piece_base_and_its_parallel_stay_apart(self):
        """OP01-025 exists as a base SR and as an alt-art SR. BOTH are printed
        OP01-025 -- the number on the card is identical, the rarity string is
        identical, and the alt art is worth several times the base.

        The only trace of the difference in the provider feed is Bandai's
        image-filename suffix; on a marketplace it is an `a` on the number or
        `(Parallel)` on the name. All three spellings describe one printing and
        none of them may collapse into the other."""
        cards = [
            self._card("optcg:op01:OP01-025:base:EN", "optcg", "op01",
                       "OP01-025", "base", "EN", "Nami"),
            self._card("optcg:op01:OP01-025:parallel:EN", "optcg", "op01",
                       "OP01-025", "parallel", "EN", "Nami"),
        ]
        resolver = self._resolver(cards)
        seen = set()
        for card in cards:
            got = resolver.resolve(self._record(card))
            seen.add(got.card_uid)
            self.assertEqual(
                got.card_uid, card["card_uid"],
                f"BLOCKING: {card['card_uid']} resolved to {got.card_uid}. "
                "A One Piece base printing and its parallel share a printed "
                "number; merging them prices an alt art at its base's comp.")
        self.assertEqual(len(seen), 2, "BLOCKING: two printings, one identity")

    def test_a_parallel_with_no_variant_stated_is_not_silently_the_base(self):
        """The realistic failure. A marketplace record says `OP01-025` and
        nothing else. It could be either printing, so the honest answer is to
        refuse -- guessing `base` is right roughly half the time and wrong
        expensively the other half."""
        cards = [
            self._card("optcg:op01:OP01-025:base:EN", "optcg", "op01",
                       "OP01-025", "base", "EN", "Nami"),
            self._card("optcg:op01:OP01-025:parallel:EN", "optcg", "op01",
                       "OP01-025", "parallel", "EN", "Nami"),
        ]
        got = self._resolver(cards).resolve(
            {"source": "probe", "game": "optcg", "language": "EN",
             "number": "OP01-025", "set_code": "op01", "name": "Nami"})
        self.assertFalse(
            got.usable_in_signals,
            f"BLOCKING: an ambiguous OP01-025 was resolved to "
            f"{got.card_uid} at {got.confidence:.2f} and used in a signal. "
            "Two printings share that number; nothing in the record says "
            "which.")

    # -- 3 -----------------------------------------------------------------

    def test_riftbound_303_and_303_starred_stay_apart(self):
        """Same art, same rules text. The asterisk and a foil signature are
        the only difference between them, and the difference is worth
        hundreds -- a Signature against an Overnumbered."""
        cards = [
            self._card("riftbound:OGN:303/298:overnumbered:EN", "riftbound",
                       "OGN", "303/298", "overnumbered", "EN", "Jinx"),
            self._card("riftbound:OGN:303*/298:signature:EN", "riftbound",
                       "OGN", "303*/298", "signature", "EN", "Jinx"),
        ]
        resolver = self._resolver(cards)
        seen = set()
        for card in cards:
            got = resolver.resolve(self._record(card))
            seen.add(got.card_uid)
            self.assertEqual(
                got.card_uid, card["card_uid"],
                f"BLOCKING: {card['card_uid']} resolved to {got.card_uid}. "
                "A Riftbound Signature and the plain Overnumbered at the same "
                "index were merged.")
        self.assertEqual(len(seen), 2, "BLOCKING: two printings, one identity")

    def test_the_asterisk_survives_the_number_parser(self):
        """The mechanical half. If the parser drops the asterisk on the way
        in, nothing downstream can tell the two apart no matter how careful it
        is -- so the parser is asserted directly rather than only through the
        resolver."""
        from resolve.identity import parse_collector_number
        plain = parse_collector_number("303/298")
        starred = parse_collector_number("303*/298")
        self.assertFalse(plain.starred)
        self.assertTrue(starred.starred,
                        "BLOCKING: the signature asterisk was parsed away")
        self.assertEqual(plain.index, starred.index)
        self.assertNotEqual(plain.raw, starred.raw)

    def test_the_asterisk_reaches_the_variant(self):
        from resolve.identity import variant_from_number
        self.assertEqual(
            variant_from_number("303*/298", 298, "riftbound"), "signature")
        self.assertEqual(
            variant_from_number("303/298", 298, "riftbound"), "overnumbered")

    # -- and the rule that ties all three together -------------------------

    def test_none_of_the_three_is_scored_away(self):
        """A guard on the guards. These must not be reachable through the
        precision threshold -- if someone moves them into `ResolverQuality`
        they become one error in a hundred, which is exactly what they must
        never be."""
        # Every test method EXCEPT this one -- reading its own source would
        # match on the very strings it is looking for.
        others = "\n".join(
            inspect.getsource(getattr(BlockingFailures, name))
            for name in dir(BlockingFailures)
            if name.startswith("test_") and name != "test_none_of_the_three_"
                                                    "is_scored_away")
        for forbidden in ("precision_threshold", "_gate", "load()", "self.data"):
            self.assertNotIn(
                forbidden, others,
                f"a blocking failure reads {forbidden!r}. These must not be "
                "reachable through the aggregate score, and must hold before "
                "the labelled set exists.")
        self.assertNotIn(ResolverQuality, BlockingFailures.__mro__)


class BlockingFailuresAgainstTheRealSet(BlockingFailures):
    """The same three merges, checked against the LABELLED SET rather than a
    synthetic pair.

    `BlockingFailures` proves the resolver can keep two well-formed printings
    apart. This proves it does so for the rows actually in the set, which are
    the ones a score will be computed over -- a merge here is a blocking
    failure with real data, and it is not permitted to show up as one wrong
    match in an aggregate.

    Each group SKIPS when the set does not yet contain both halves. A skip says
    "not yet tested"; a pass over one row would say "tested and fine", and only
    one of those is true.
    """

    #: Groups that must resolve to as many distinct identities as they have rows.
    GROUPS = {
        "One Piece OP01-025 base and parallel, EN and JP -- all four printed "
        "OP01-025": (
            "optcg:op01:OP01-025:base:EN", "optcg:op01:OP01-025:parallel:EN",
            "optcg:op01:OP01-025:base:JP", "optcg:op01:OP01-025:parallel:JP"),
        "One Piece OP01-001 base and parallel, EN and JP": (
            "optcg:op01:OP01-001:base:EN", "optcg:op01:OP01-001:parallel:EN",
            "optcg:op01:OP01-001:base:JP", "optcg:op01:OP01-001:parallel:JP"),
        "Riftbound 303/298 against 303*/298 -- an asterisk apart": (
            "riftbound:OGN:303/298:overnumbered:EN",
            "riftbound:OGN:303*/298:signature:EN"),
        "Riftbound 299/298 against 299*/298": (
            "riftbound:OGN:299/298:overnumbered:EN",
            "riftbound:OGN:299*/298:signature:EN"),
        "Pokemon 173/165 against 173/151 -- same index, different total": (
            "pkmn:sv03.5:173/165:ar:EN", "pkmn:SV2aF:173/165:ar:CN-T",
            "pkmn:151C:173/151:ar:CN-S"),
        "Pokemon EN 199/165 against JP and CN-T 201/165 -- same art": (
            "pkmn:sv03.5:199/165:sir:EN", "pkmn:sv2a:201/165:sar:JP",
            "pkmn:SV2aF:201/165:sar:CN-T"),
    }

    @classmethod
    def setUpClass(cls):
        cls.data = load()
        cls.by_uid = {c["card_uid"]: c for c in cls.data["cards"]}
        cls.resolver = Resolver(cls.data["cards"])

    def _check(self, label, uids):
        present = [u for u in uids if u in self.by_uid]
        if len(present) < 2:
            self.skipTest(f"{label}: the set has {len(present)} of "
                          f"{len(uids)} rows, so the merge is untested")
        got = {}
        for uid in present:
            card = self.by_uid[uid]
            got[uid] = self.resolver.resolve(self._record(card)).card_uid
        # Each printing must resolve to ITSELF. That is the whole check: if
        # every row returns its own uid then the results are distinct by
        # construction, so a separate "did they collapse" count would be a
        # line that cannot fail on its own -- decoration, and this project
        # does not keep guards nothing catches. A collapse shows up here, as
        # one row returning another's identity.
        for uid, resolved in got.items():
            self.assertEqual(
                resolved, uid,
                f"BLOCKING ({label}): {uid} resolved to {resolved}. "
                f"{len(present)} printings share a printed number here and "
                "only their identities keep them apart.")

    def test_one_piece_op01_025(self):
        label = ("One Piece OP01-025 base and parallel, EN and JP -- all four "
                 "printed OP01-025")
        self._check(label, self.GROUPS[label])

    def test_one_piece_op01_001(self):
        label = "One Piece OP01-001 base and parallel, EN and JP"
        self._check(label, self.GROUPS[label])

    def test_riftbound_303(self):
        label = "Riftbound 303/298 against 303*/298 -- an asterisk apart"
        self._check(label, self.GROUPS[label])

    def test_riftbound_299(self):
        label = "Riftbound 299/298 against 299*/298"
        self._check(label, self.GROUPS[label])

    def test_pokemon_173(self):
        label = ("Pokemon 173/165 against 173/151 -- same index, different "
                 "total")
        self._check(label, self.GROUPS[label])

    def test_pokemon_199_against_201(self):
        label = "Pokemon EN 199/165 against JP and CN-T 201/165 -- same art"
        self._check(label, self.GROUPS[label])

    def test_every_group_is_reachable(self):
        """A guard on the guards, again. If a set-code alias changes and these
        uids stop matching anything, every group above would SKIP and the file
        would go quiet -- which reads exactly like passing."""
        reachable = sum(1 for uids in self.GROUPS.values()
                        if sum(1 for u in uids if u in self.by_uid) >= 2)
        self.assertGreater(
            reachable, 0,
            "not one blocking group is present in the labelled set. Either "
            "the rows were never ingested or their card_uids no longer match "
            "-- a set-code alias change would do this silently.")


class PrecisionIsReportedWithItsInterval(unittest.TestCase):
    """A precision of 1.0000 is not a passing gate; it is a point estimate, and
    on a small set it is a weak one.

    `_gate.sizing_note` sized the set on the ERROR BUDGET rather than the count:
    at n=250 a zero-error sweep gives a 95% lower bound of 0.9881 and survives
    one mistake. Reporting the point estimate without the bound is how "1.00"
    gets read as "met"."""

    @staticmethod
    def _lower_bound(n, errors=0):
        """One-sided 95% Clopper-Pearson lower bound on precision.

        Zero errors collapses to `0.05 ** (1/n)`; one error needs the beta
        quantile, and the difference between the two is the whole reason the
        set is sized at 250 rather than at whatever clears the threshold
        today.
        """
        if errors == 0:
            return 0.05 ** (1.0 / n)
        try:
            from statistics import NormalDist            # noqa: F401
            import math
            # Beta(n - errors, errors + 1) 5th percentile, by bisection --
            # exact enough here and it avoids a scipy dependency.
            def cdf(x):
                total = 0.0
                for k in range(n - errors, n + 1):
                    total += (math.comb(n, k) * x ** k * (1 - x) ** (n - k))
                return total
            # `cdf` is P(X >= n-errors | p), which INCREASES with p. We want
            # the p where it equals 0.05, so a value above the target means
            # the answer is lower. Getting this backwards returns 0.0 for
            # every input -- and 0.0 passes a `assertLess(bound, threshold)`
            # check, so the test goes green while measuring nothing.
            lo, hi = 0.0, 1.0
            for _ in range(200):
                mid = (lo + hi) / 2
                if cdf(mid) > 0.05:
                    hi = mid
                else:
                    lo = mid
            return lo
        except Exception:                                # noqa: BLE001
            return 0.0

    def test_the_interval_arithmetic_matches_the_sizing_note(self):
        """A guard on the guard. ADR-0015 sized the set by computing that 250
        rows survive ONE error at 0.9812 and 200 do not (0.9765). If this
        helper cannot reproduce those two numbers it is not measuring what the
        gate is sized against -- and a broken bound returns 0.0, which passes
        an `assertLess` silently."""
        self.assertAlmostEqual(self._lower_bound(250, 1), 0.9812, places=3)
        self.assertAlmostEqual(self._lower_bound(200, 1), 0.9765, places=3)
        self.assertAlmostEqual(self._lower_bound(200, 0), 0.9851, places=3)
        self.assertGreater(self._lower_bound(250, 1), 0.9,
                           "the bound collapsed to zero -- the bisection is "
                           "inverted and every comparison against it is "
                           "passing for the wrong reason")

    def test_the_lower_bound_is_computable_and_reported(self):
        data = load()
        n = len(scored_rows(data))
        if not n:
            self.skipTest("no scored rows")
        threshold = data["_gate"]["precision_threshold"]
        clean = self._lower_bound(n)
        self.assertGreater(clean, 0.0)
        if n >= data["_gate"]["required_cards"]:
            return
        # THE SET IS SIZED ON THE ERROR BUDGET, NOT THE COUNT. ADR-0015:
        # "250 survives one error (0.9812). The binding constraint is the
        # error budget, not the sample size." So a clean sweep clearing the
        # threshold early proves nothing -- the question is whether ONE wrong
        # match would still clear it, and below the required count it must not.
        one_error = self._lower_bound(n, errors=1)
        self.assertLess(
            one_error, threshold,
            f"n={n} survives one error at {one_error:.4f}, which clears "
            f"{threshold} below the required "
            f"{data['_gate']['required_cards']}. If that holds, the required "
            "count is larger than the error budget needs and ADR-0015 should "
            "be revisited rather than the gate quietly left redundant.")

    def test_a_clean_sweep_alone_does_not_justify_the_claim(self):
        """The trap this guards. At n=170 with zero errors the bound is
        0.9825 and clears 0.98 -- and one wrong match drops it below. Reading
        the clean number as "the gate is met" is exactly the mistake the
        sizing note was written to prevent."""
        data = load()
        n = len(scored_rows(data))
        if not n or n >= data["_gate"]["required_cards"]:
            self.skipTest("set is at or past its required count")
        threshold = data["_gate"]["precision_threshold"]
        clean = self._lower_bound(n)
        one_error = self._lower_bound(n, errors=1)
        self.assertLess(one_error, clean,
                        "one error must lower the bound, or the arithmetic is "
                        "wrong")
        if clean >= threshold:
            self.assertLess(
                one_error, threshold,
                f"n={n}: a clean sweep gives {clean:.4f} and one error gives "
                f"{one_error:.4f}. Both clear {threshold}, so the count is no "
                "longer the binding constraint.")
