"""The set totals, wired to the resolver.

`printed_from_bare` was written, tested and mutation-covered several sessions
ago. `_set_totals` has been collected from every adapter and written into
`targets.json` for just as long. Nothing joined them, so the catalog built
`pkmn:swsh10.5:011:base:EN` from tcgdex's bare `11` while the card -- and the
labelled row -- both say `011/078`. Two uids for one card: the price lands on
the one nothing else refers to.

Measured against the labelled set before the fix: of the five rows where the
catalog and the labels both spoke, five disagreed on the uid and four of the
five disagreed on the number alone. After it, four agree; the fifth disagrees
on the VARIANT (`base` against `ur`), which is a different defect and stays
open.
"""

import copy
import json
import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from ingest.catalog import bridge_numbers, to_targets            # noqa: E402
from resolve.resolver import Resolver                            # noqa: E402


def row(number, uid=None, name="Pikachu", set_code="swsh10.5",
        variant="base", language="EN", game="pkmn", external_id="x"):
    return {"card_uid": uid or f"{game}:{set_code}:{number}:{variant}:{language}",
            "game": game, "language": language, "set_code": set_code,
            "number": number, "variant": variant, "name": name,
            "rarity": "Rare", "external_id": external_id, "source": "tcgdex"}


def catalog_of(*rows, combo="pkmn:EN"):
    return {combo: {"sources": ["tcgdex"], "cards": list(rows)}}


TOTALS = {"EN": {"swsh10.5": 78, "swsh7": 203, "sv03.5": 165}}


class TheBridgeFires(unittest.TestCase):

    def test_a_bare_number_becomes_the_number_on_the_card(self):
        out, report = bridge_numbers(catalog_of(row("11")), TOTALS)
        card = out["pkmn:EN"]["cards"][0]
        self.assertEqual(card["number"], "011/078")
        self.assertEqual(card["card_uid"], "pkmn:swsh10.5:011/078:base:EN")
        self.assertEqual(report["pkmn:EN"]["bridged"], 1)

    def test_the_catalog_uid_now_equals_the_labelled_uid(self):
        """THE BUG, stated as the thing that was broken. A labelled row and a
        catalog row for one card produced two uids, so the price attached to
        neither the card I track nor anything else."""
        labelled = "pkmn:swsh10.5:011/078:base:EN"
        before = catalog_of(row("11"))["pkmn:EN"]["cards"][0]["card_uid"]
        self.assertNotEqual(before, labelled)
        out, _ = bridge_numbers(catalog_of(row("11")), TOTALS)
        self.assertEqual(out["pkmn:EN"]["cards"][0]["card_uid"], labelled)

    def test_padding_follows_the_total_not_the_provider(self):
        out, _ = bridge_numbers(catalog_of(row("95", set_code="swsh7")),
                                TOTALS)
        self.assertEqual(out["pkmn:EN"]["cards"][0]["number"], "095/203")

    def test_an_overnumbered_card_keeps_its_index(self):
        """`199/165` is not a typo -- secret rares run past the denominator,
        and a bridge that clamped them would rename the whole secret sheet."""
        out, _ = bridge_numbers(catalog_of(row("199", set_code="sv03.5")),
                                TOTALS)
        self.assertEqual(out["pkmn:EN"]["cards"][0]["number"], "199/165")


class TheBridgeRefuses(unittest.TestCase):

    def test_an_unknown_total_leaves_the_row_bare_and_names_the_set(self):
        out, report = bridge_numbers(catalog_of(row("11", set_code="base1")),
                                     TOTALS)
        self.assertEqual(out["pkmn:EN"]["cards"][0]["number"], "11")
        self.assertEqual(report["pkmn:EN"]["no_set_total"], 1)
        self.assertEqual(report["pkmn:EN"]["sets_without_totals"], ["base1"])

    def test_a_number_with_no_readable_index_is_counted_not_guessed(self):
        """`SV001`, `TG15`, `CC001` -- 168 rows in the live catalog. They print
        as `SV001/SV122`, a lettered denominator the totals do not supply. A
        miss that is counted can be fixed; a guess cannot."""
        out, report = bridge_numbers(catalog_of(row("SV001")), TOTALS)
        self.assertEqual(out["pkmn:EN"]["cards"][0]["number"], "SV001")
        self.assertEqual(report["pkmn:EN"]["unreadable"], 1)

    def test_a_printed_number_is_never_re_derived(self):
        """One direction only. A card that already says `2/102` keeps saying
        it -- rewriting it around the total would let a wrong total overwrite
        a denominator the card itself supplied."""
        out, report = bridge_numbers(
            catalog_of(row("2/102", set_code="swsh10.5")), TOTALS)
        self.assertEqual(out["pkmn:EN"]["cards"][0]["number"], "2/102")
        self.assertEqual(report["pkmn:EN"]["self_printed"], 1)
        self.assertEqual(report["pkmn:EN"]["bridged"], 0)

    def test_a_bridge_that_would_merge_two_cards_is_refused(self):
        """NON-NEGOTIABLE 3, arriving through a fix. Bridging is a rename, and
        a rename that collides is a merge -- here between a bare `11` and a
        row that already carries `011/078`. Both stay bare, both survive, and
        the collision is named."""
        cat = catalog_of(row("11", name="Pikachu"),
                         row("011/078", name="Raichu", external_id="y"))
        out, report = bridge_numbers(cat, TOTALS)
        uids = sorted(c["card_uid"] for c in out["pkmn:EN"]["cards"])
        self.assertEqual(len(uids), 2, "a card was lost to the merge")
        self.assertIn("pkmn:swsh10.5:11:base:EN", uids)
        self.assertEqual(report["pkmn:EN"]["refused_collision"], 1)
        self.assertEqual(report["pkmn:EN"]["bridged"], 0)
        self.assertEqual(len(report["pkmn:EN"]["collisions"]), 1)
        self.assertEqual(report["pkmn:EN"]["collisions"][0]["names"],
                         ["pikachu", "raichu"])

    def test_the_same_card_from_two_sources_still_dedupes(self):
        """The other side of the collision rule: identical names are the
        existing cross-source dedupe, not a merge, and refusing them would
        double the catalog."""
        cat = catalog_of(row("11", external_id="a"),
                         row("011/078", external_id="b"))
        out, report = bridge_numbers(cat, TOTALS)
        self.assertEqual(len(out["pkmn:EN"]["cards"]), 1)
        self.assertEqual(report["pkmn:EN"]["refused_collision"], 0)


class TheBridgeIsWiredIn(unittest.TestCase):

    def test_the_input_catalog_is_not_mutated(self):
        """`preserve_from_cache` and `_cache_stamps` both read the original
        catalog after this runs."""
        cat = catalog_of(row("11"))
        snapshot = copy.deepcopy(cat)
        bridge_numbers(cat, TOTALS)
        self.assertEqual(cat, snapshot)

    def test_to_targets_bridges_before_it_routes(self):
        """A target's card_uid is what the price lands on."""
        targets = to_targets(catalog_of(row("11")), [], set_totals=TOTALS)
        served = [c for entry in targets.values()
                  if isinstance(entry, dict) and "cards" in entry
                  for c in entry["cards"]]
        self.assertTrue(served)
        for card in served:
            self.assertEqual(card["number"], "011/078")
            self.assertEqual(card["card_uid"],
                             "pkmn:swsh10.5:011/078:base:EN")

    def test_the_report_reaches_the_runner_file(self):
        """A count of zero bridges would have said, on the first run, that the
        totals were sitting in this file with nothing reading them."""
        targets = to_targets(catalog_of(row("11")), [], set_totals=TOTALS)
        self.assertIn("_number_bridge", targets)
        self.assertEqual(targets["_number_bridge"]["pkmn:EN"]["bridged"], 1)
        json.dumps(targets)          # the report has to survive the write

    def test_the_language_comes_from_the_card_not_the_combo_key(self):
        """A tuple combo key -- `("pkmn", "EN")` rather than `"pkmn:EN"` --
        would have made every row `no_set_total`, which reads as a provider
        gap rather than as a key-shape bug. The card carries its own language
        and that is what the totals are keyed by."""
        out, report = bridge_numbers(catalog_of(row("11"), combo=("pkmn", "EN")),
                                     TOTALS)
        card = out[("pkmn", "EN")]["cards"][0]
        self.assertEqual(card["card_uid"], "pkmn:swsh10.5:011/078:base:EN")
        self.assertEqual(report[("pkmn", "EN")]["bridged"], 1)

    def test_no_totals_at_all_is_a_no_op_not_a_crash(self):
        targets = to_targets(catalog_of(row("11")), [])
        self.assertEqual(targets["_number_bridge"]["pkmn:EN"]["no_set_total"], 1)


if __name__ == "__main__":
    unittest.main()


CARD = {"card_uid": "pkmn:swsh10.5:011/078:base:EN", "game": "pkmn",
        "language": "EN", "set_code": "swsh10.5", "number": "011/078",
        "variant": "base", "name": "Pikachu"}


def record(number="11", name="Pikachu", set_code="swsh10.5"):
    return {"source": "tcgdex", "game": "pkmn", "language": "EN",
            "set_code": set_code, "number": number, "name": name}


class TheResolverBridgesABareNumber(unittest.TestCase):
    """The half `ingest` cannot fix.

    `bridge_numbers` makes the catalog's own uids agree with the labels, but a
    PRICE SOURCE answers with whatever it calls the card. tcgdex says `11` for
    a card printed `011/078`, the resolver's key lookup missed, and it reported
    "no card in pkmn/EN with number '11'" -- true, and useless. Five of the
    seven pairs in the catalog-in measurement were refused for exactly this.
    """

    def test_without_totals_a_bare_number_is_still_refused(self):
        """The absence of totals is the OLD BEHAVIOUR EXACTLY. A resolver that
        quietly got looser when nobody configured it would be a change nobody
        asked for, arriving in the safest-looking way."""
        result = Resolver([CARD]).resolve(record())
        self.assertIsNone(result.card_uid)
        self.assertEqual(result.why,
                         "no card in pkmn/EN with number '11'")

    def test_with_totals_it_resolves_to_the_printed_uid(self):
        result = Resolver([CARD], set_totals={"EN": {"swsh10.5": 78}}
                          ).resolve(record())
        self.assertEqual(result.card_uid, CARD["card_uid"])
        self.assertTrue(result.usable_in_signals)

    def test_a_bridged_match_says_so(self):
        """Never silent. A match that exists only because the number was
        bridged is a weaker claim than one that matched outright."""
        result = Resolver([CARD], set_totals={"EN": {"swsh10.5": 78}}
                          ).resolve(record())
        self.assertIn("bridging the bare number", result.why)
        self.assertIn("011/078", result.why)

    def test_the_bridge_only_runs_when_the_exact_lookup_missed(self):
        """It can ADD a match and can never change one."""
        exact = dict(CARD, card_uid="pkmn:swsh10.5:11:base:EN", number="11")
        result = Resolver([exact, CARD],
                          set_totals={"EN": {"swsh10.5": 78}}).resolve(record())
        self.assertEqual(result.card_uid, "pkmn:swsh10.5:11:base:EN")
        self.assertNotIn("bridging", result.why)

    def test_it_never_bridges_backwards(self):
        """A printed record against a bare catalog stays unresolved. Stripping
        `173/151` and `173/165` to `173` is the merge `printed_from_bare`
        refuses to have a function for, and it would arrive here instead."""
        bare = dict(CARD, card_uid="pkmn:swsh10.5:11:base:EN", number="11")
        result = Resolver([bare], set_totals={"EN": {"swsh10.5": 78}}
                          ).resolve(record("011/078"))
        self.assertIsNone(result.card_uid)

    def test_an_unknown_total_names_the_missing_count(self):
        """"We have no total" and "there is no such card" are different facts,
        and the refusal has to say which one it is."""
        result = Resolver([CARD], set_totals={"EN": {"base1": 102}}
                          ).resolve(record())
        self.assertIsNone(result.card_uid)
        self.assertIn("no official card count", result.why)

    def test_a_bridged_candidate_still_has_to_clear_the_threshold(self):
        """CANDIDATES, not an answer. The pool the bridge produces is scored
        on name and set_code like any other."""
        result = Resolver([CARD], set_totals={"EN": {"swsh10.5": 78}}
                          ).resolve(record(name="Charizard"))
        self.assertFalse(result.usable_in_signals)
