"""The three open catalog sources, and the honesty machinery around them.

None of these adapters has ever reached its live service. The sandbox they were
written in cannot: the egress proxy answers 403 to CONNECT for all three hosts.
So what is tested here is NOT that the parsing is right -- it cannot be, until
a real payload arrives -- but that every path which does not know something
says so:

* a source that cannot be reached reports unreachable, not empty
* a source that answers but lists nothing reports empty, not unreachable
* a combination a source does not serve reports that, and does not silently
  return zero
* a first-contact failure on an UNVERIFIED source is a gap with the error
  attached, not a failed run

Every test injects its transport. No test may reach the network, and a test
that quietly did would be measuring the internet rather than this code.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.catalog_sources import (CrystAdapter, Poke52Adapter,     # noqa: E402
                                    TcgdexAdapter, _catalog_row)
from ingest.registry import CN_SOURCE_PRIORITY                       # noqa: E402
from ingest.base import AdapterGaveUp                                # noqa: E402
from ingest.catalog import CatalogBuilder                            # noqa: E402
from ingest.runner import STATUS, _write_card, render_summary        # noqa: E402


def transport(routes, misses=None):
    """(url, headers) -> (status, body). `routes` maps a URL substring to a
    payload; anything unmatched 404s, which is what a wrong guess looks like."""
    seen = []

    def send(url, headers):
        seen.append(url)
        for fragment, payload in routes.items():
            if fragment in url:
                return 200, json.dumps(payload).encode("utf-8")
        return 404, b'{"error": "not found"}'

    send.seen = seen
    return send


def build(cls, routes, misses=None):
    tmp = tempfile.mkdtemp()
    return cls(raw_root=tmp, sleep=lambda _s: None,
               transport=transport(routes))


class TcgdexDiscoversRatherThanAssumes(unittest.TestCase):
    """The user's instruction was to check /status before assuming a combo is
    covered. These assert that checking is what happens."""

    def test_the_status_endpoint_is_discovered_not_hardcoded(self):
        """Two candidate shapes were plausible and only one can be right. The
        adapter tries both rather than picking one and reporting its 404 as
        'the service has no Chinese data'."""
        adapter = build(TcgdexAdapter, {"/v2/status": {"languages": ["en", "zh-tw"]}})
        self.assertEqual(adapter.status()["endpoint"],
                         "https://api.tcgdex.net/v2/status")

        adapter = build(TcgdexAdapter, {"api.tcgdex.net/status":
                                        {"languages": ["en"]}})
        self.assertTrue(adapter.status()["endpoint"].endswith("/status"))

    def test_no_status_endpoint_at_all_names_every_url_tried(self):
        adapter = build(TcgdexAdapter, {})
        with self.assertRaises(AdapterGaveUp) as caught:
            adapter.status()
        for candidate in TcgdexAdapter.STATUS_CANDIDATES:
            self.assertIn(candidate, str(caught.exception))

    def test_live_languages_reads_the_services_own_list(self):
        adapter = build(TcgdexAdapter,
                        {"/v2/status": {"languages": ["en", "ja", "zh-tw"]}})
        self.assertEqual(adapter.live_languages(), ["en", "ja", "zh-tw"])

    def test_an_uninformative_status_returns_empty_not_a_conclusion(self):
        """A status payload that does not enumerate languages tells us nothing.
        Returning [] must mean 'status was silent', and the caller measures
        instead -- reading it as 'no languages' would mark every combo dead on
        the strength of a payload shape we guessed wrong."""
        adapter = build(TcgdexAdapter, {"/v2/status": {"uptime": 99.9}})
        self.assertEqual(adapter.live_languages(), [])

    def test_it_says_plainly_that_it_cannot_serve_one_piece(self):
        """All three new sources are Pokemon. The gap that stays open after
        this session is One Piece CN-S, and the error says so rather than
        returning an empty list that reads like 'no chase cards'."""
        adapter = build(TcgdexAdapter, {})
        with self.assertRaises(AdapterGaveUp) as caught:
            adapter.enumerate_combo("optcg", "CN-S")
        self.assertIn("One Piece CN-S", str(caught.exception))

    def test_a_reachable_but_empty_language_is_reported_as_empty(self):
        adapter = build(TcgdexAdapter, {"/zh-cn/sets": []})
        rows = adapter.coverage([("pkmn", "CN-S")])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["reachable"])
        self.assertEqual(rows[0]["cards"], 0)
        self.assertIn("lists no cards", rows[0]["detail"])

    def test_an_unreachable_language_is_not_reported_as_empty(self):
        """The distinction the whole ingest_gap table exists for."""
        adapter = build(TcgdexAdapter, {})
        rows = adapter.coverage([("pkmn", "CN-T")])
        self.assertFalse(rows[0]["reachable"])
        self.assertEqual(rows[0]["cards"], 0)
        self.assertTrue(rows[0]["detail"])

    def test_coverage_never_raises_so_later_combos_still_get_measured(self):
        adapter = build(TcgdexAdapter, {})
        rows = adapter.coverage([("pkmn", "CN-T"), ("pkmn", "CN-S")])
        self.assertEqual([r["combo"] for r in rows],
                         ["pkmn:CN-T", "pkmn:CN-S"])

    def test_cards_come_back_with_a_whole_identity(self):
        adapter = build(TcgdexAdapter, {
            "/zh-tw/sets/sv2aF": {"id": "sv2aF", "cards": [
                {"localId": "170/165", "name": "皮卡丘",
                 "rarity": "Art Rare", "illustrator": "Oswaldo KATO"}]},
            "/zh-tw/sets": [{"id": "sv2aF"}]})
        rows = adapter.enumerate_combo("pkmn", "CN-T")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["card_uid"], "pkmn:sv2aF:170/165:ar:CN-T")
        self.assertEqual(rows[0]["name_jp"], "皮卡丘")
        self.assertNotIn("name_en", rows[0],
                         "a Traditional Chinese printing claimed an English name")


class CrystProbesAndReportsWhatAnswered(unittest.TestCase):

    def test_it_tries_each_candidate_and_uses_the_one_that_answers(self):
        adapter = build(CrystAdapter, {
            "/data/sets.json": [{"code": "151C"}],
            "/data/151C.json": [{"number": "170/151", "name": "皮卡丘",
                                 "rarity": "AR"}]})
        rows = adapter.enumerate_combo("pkmn", "CN-S")
        self.assertEqual(rows[0]["card_uid"], "pkmn:151C:170/151:ar:CN-S")
        self.assertTrue(any("set endpoint resolved to" in line
                            for line in adapter.log))

    def test_no_endpoint_answering_names_every_url_tried(self):
        """So the next session starts from evidence instead of repeating this."""
        adapter = build(CrystAdapter, {})
        with self.assertRaises(AdapterGaveUp) as caught:
            adapter.enumerate_combo("pkmn", "CN-S")
        for candidate in CrystAdapter.SET_CANDIDATES:
            self.assertIn(candidate, str(caught.exception))

    def test_it_refuses_a_combination_it_does_not_serve(self):
        adapter = build(CrystAdapter, {})
        with self.assertRaises(AdapterGaveUp) as caught:
            adapter.enumerate_combo("pkmn", "CN-T")
        self.assertIn("Simplified Chinese", str(caught.exception))


class Poke52RefusesToEnumerate(unittest.TestCase):
    """The interesting one: a source that declines a capability rather than
    half-implementing it."""

    def test_it_does_not_pretend_to_enumerate(self):
        self.assertFalse(Poke52Adapter.can_enumerate)

    def test_coverage_states_the_reason_instead_of_returning_zero(self):
        """A zero here would read as 'no cards'. The reason is the finding."""
        adapter = build(Poke52Adapter, {})
        rows = adapter.coverage()
        self.assertTrue(rows)
        for row in rows:
            self.assertFalse(row["reachable"])
            self.assertIn("enrichment only", row["detail"])

    def test_it_supplies_names_for_identities_it_did_not_establish(self):
        adapter = build(Poke52Adapter,
                        {"api.php": {"query": {"search": [{"title": "皮卡丘"}]}}})
        records = adapter.names_for([{"card_uid": "pkmn:151C:170/151:ar:CN-S",
                                      "name": "Pikachu", "number": "170/151"}])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].payload["name_zh"], "皮卡丘")

    def test_a_card_with_no_hit_is_skipped_not_given_an_empty_name(self):
        adapter = build(Poke52Adapter, {"api.php": {"query": {"search": []}}})
        self.assertEqual(adapter.names_for([{"card_uid": "x", "name": "Nope",
                                             "number": "1/1"}]), [])


class PartialRowsAreDeclinedNotWritten(unittest.TestCase):

    def test_a_row_without_a_number_has_no_identity(self):
        self.assertIsNone(_catalog_row("pkmn", "CN-S", "151C",
                                       {"name": "皮卡丘"}, "cryst"))

    def test_a_row_without_a_set_has_no_identity(self):
        self.assertIsNone(_catalog_row("pkmn", "CN-S", "",
                                       {"localId": "170/151"}, "cryst"))

    def test_a_language_the_game_does_not_print_is_refused(self):
        """riftbound has no Japanese release. card_uid raises and the row is
        dropped rather than a uid being coerced into existence."""
        self.assertIsNone(_catalog_row("riftbound", "JP", "OGN",
                                       {"localId": "OGN-1", "name": "Jinx"},
                                       "tcgdex"))

    def test_the_runner_declines_an_enrichment_record(self):
        """52poke returns a name keyed on a card_uid and nothing else. The
        store is insert-or-ignore with no update path, so writing it would
        either be rejected or would become the card."""
        class Rec:
            kind, source = "card", "wiki52poke"
            payload = {"card_uid": "pkmn:151C:170/151:ar:CN-S", "name_zh": "皮卡丘"}
            observed_at = as_of = None
        self.assertIs(_write_card(None, Rec()), False)


class AnUnverifiedSourceFailingIsAGapNotAFailedRun(unittest.TestCase):

    def test_the_status_exists_and_does_not_fail_the_run(self):
        self.assertIn("unverified_failed", STATUS)
        self.assertFalse(STATUS["unverified_failed"]["failure"])
        self.assertFalse(STATUS["unverified_failed"]["ingested"])

    def test_the_summary_names_it_and_carries_the_error(self):
        """The error IS the coverage finding. A summary that swallowed it would
        make run #1 -- the only experiment that can settle the endpoint shape --
        produce nothing to act on."""
        summary = render_summary([
            {"source": "tcgapi", "status": "ok", "rows": 40, "gaps": 0},
            {"source": "tcgdex", "status": "unverified_failed", "rows": 0,
             "gaps": 1, "detail": "no status endpoint answered: 404 on /v2/status"},
        ])
        self.assertIn("Unverified sources", summary)
        self.assertIn("/v2/status", summary)
        self.assertIn("OK --", summary,
                      "an unverified source failing took the run down with it")


class TheFallbackStopsAtTheFirstSourceThatDelivers(unittest.TestCase):

    class Fake:
        can_enumerate = True
        cannot_enumerate_because = ""

        def __init__(self, serves, rows=None, boom=None):
            self.serves, self._rows, self._boom = serves, rows or [], boom
            self.calls = 0

        def enumerate_combo(self, game, language):
            self.calls += 1
            if self._boom:
                raise AdapterGaveUp(self._boom)
            return self._rows

    def _row(self):
        return {"card_uid": "pkmn:151C:170/151:ar:CN-S", "set_code": "151C",
                "number": "170/151", "variant": "ar", "rarity": "Art Rare",
                "name_jp": "皮卡丘"}

    def test_the_second_source_is_not_asked_once_the_first_delivers(self):
        """They are alternatives, not supplements. Merging two catalogs that
        disagree about a number manufactures cards neither of them lists."""
        first = self.Fake({("pkmn", "CN-S")}, rows=[self._row()])
        second = self.Fake({("pkmn", "CN-S")}, rows=[self._row()])
        builder = CatalogBuilder(tcgapi=object(), apitcg=object(),
                                 cn_sources={"tcgdex": first,
                                             "wiki52poke": second})
        rows, tried = builder.chinese_fallback("pkmn", "CN-S")
        self.assertEqual(len(rows), 1)
        self.assertEqual(tried["used"], ["tcgdex"])
        self.assertEqual(second.calls, 0)

    def test_a_failing_first_source_falls_through_and_both_are_recorded(self):
        first = self.Fake({("pkmn", "CN-S")}, boom="404 everywhere")
        second = self.Fake({("pkmn", "CN-S")}, rows=[self._row()])
        builder = CatalogBuilder(tcgapi=object(), apitcg=object(),
                                 cn_sources={"tcgdex": first,
                                             "wiki52poke": second})
        rows, tried = builder.chinese_fallback("pkmn", "CN-S")
        self.assertEqual(tried["used"], ["wiki52poke"])
        self.assertIn("tcgdex", [name for name, _why in tried["failed"]])
        self.assertIn("404 everywhere",
                      dict(tried["failed"])["tcgdex"])

    def test_a_superseded_source_is_never_asked(self):
        """cryst probed a wrong URL every run and filed the answer as a gap
        that reads like missing data. tcgdex covers everything it was for, so
        sources.yml supersedes it and the rotation must honour that."""
        builder = CatalogBuilder(tcgapi=object(), apitcg=object())
        live = builder.live_cn_sources()
        self.assertNotIn("cryst", live)
        self.assertEqual(live[0], "tcgdex")

    def test_superseding_is_recorded_rather_than_deleted(self):
        """'We tried this and it was superseded' is a different fact from
        'we never considered it'. The next session should not rediscover
        tcg.mik.moe from scratch."""
        from ingest.runner import load_expectations
        entry = load_expectations()["cryst"]
        self.assertEqual(entry["superseded_by"], "tcgdex")
        self.assertTrue(entry.get("superseded_note"))

    def test_priority_order_is_the_one_that_was_asked_for(self):
        self.assertEqual(CN_SOURCE_PRIORITY,
                         ("tcgdex", "cryst", "wiki52poke"))

    def test_no_open_source_covers_one_piece(self):
        """Stated as a test so it cannot quietly stop being reported. Every
        source added this session is a Pokemon database."""
        for cls in (TcgdexAdapter, CrystAdapter, Poke52Adapter):
            self.assertFalse([c for c in cls.serves if c[0] == "optcg"],
                             f"{cls.name} claims to serve One Piece")


class TheChaseRaritiesAreActuallyTracked(unittest.TestCase):
    """A regression guard on a bug the Chinese seeds exposed.

    `rarity_band` matched substrings, and every one of these abbreviations is a
    substring of the word `rare` -- `"ar" in "rare"` is True. So Art Rares were
    filed as ordinary rares and Treasure Rares fell through to `rare` as well.
    ingest/catalog.py tracks only `chase` and `premium`, which means the target
    builder was silently excluding the top chase rarity in One Piece and the
    whole Art Rare tier in Pokemon -- the cards the engine exists for.
    """

    def test_the_abbreviations_do_not_collide_with_the_word_rare(self):
        from store.cross_grader import rarity_band
        self.assertEqual(rarity_band("AR"), "premium")
        self.assertEqual(rarity_band("Art Rare"), "premium")
        self.assertEqual(rarity_band("TR"), "chase")
        self.assertEqual(rarity_band("Treasure Rare"), "chase")
        # And the ordinary rarities still land where they did.
        self.assertEqual(rarity_band("Double Rare"), "rare")
        self.assertEqual(rarity_band("Rare"), "rare")
        self.assertEqual(rarity_band("Common"), "base")

    def test_every_seeded_variant_lands_in_a_tracked_band(self):
        """The end-to-end version: if a rarity the labelled set contains is not
        tracked, the target builder will never fetch a price for it and the
        card is in the test set and nowhere else."""
        from ingest.catalog import TRACKED_BANDS
        from store.cross_grader import rarity_band
        for rarity in ("Treasure Rare", "Art Rare", "SAR", "SIR",
                       "Manga Rare", "Special Illustration Rare"):
            self.assertIn(rarity_band(rarity), TRACKED_BANDS,
                          f"{rarity} would never be fetched")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheChineseCombosNoLongerHaveToBeTyped(unittest.TestCase):
    """Run #5 established the coverage -- 877 CN-S, 7,436 CN-T -- so the 55
    cards those two combos need can be proposed rather than authored.

    This does NOT weaken the non-circularity argument, and the distinction is
    worth being precise about: ADR-0016 refuses *generating labels* from the
    catalog the resolver reads. This generates PROPOSALS from it, and the human
    verdict that breaks the circle is unchanged. What changed is only that the
    proposal no longer has to come from memory.
    """

    # NB: the more specific route must come FIRST -- the fake transport matches
    # by substring, and "/ja/sets" is a prefix of "/ja/sets/sv2a".
    JP = {"/ja/sets/sv2a": {"id": "sv2a", "cards": [
              {"localId": "170/165", "name": "ピカチュウ", "rarity": "Art Rare",
               "illustrator": "Oswaldo KATO"},
              {"localId": "201/165", "name": "リザードンex", "rarity": "SAR",
               "illustrator": "Takumi Wada"}]},
          "/ja/sets": [{"id": "sv2a"}]}
    CN_T = {"/zh-tw/sets/sv2aF": {"id": "sv2aF", "cards": [
                {"localId": "170/165", "name": "皮卡丘", "rarity": "Art Rare",
                 "illustrator": "Oswaldo KATO"}]},
            "/zh-tw/sets": [{"id": "sv2aF"}]}
    # 174/151 deliberately: 170-173/151 are already in the labelled set as
    # externally-researched seeds, and an already-labelled card is not
    # re-proposed. See test_an_already_labelled_card_is_not_proposed_again.
    CN_S = {"/zh-cn/sets/151C": {"id": "151C", "cards": [
                {"localId": "174/151", "name": "皮卡丘", "rarity": "Art Rare",
                 "illustrator": "Oswaldo KATO"},
                {"localId": "170/151", "name": "皮卡丘", "rarity": "Art Rare",
                 "illustrator": "Oswaldo KATO"}]},
            "/zh-cn/sets": [{"id": "151C"}]}

    def _catalog(self):
        from resolve.label_cli import _catalog_from_tcgdex
        adapter = build(TcgdexAdapter, {**self.JP, **self.CN_T, **self.CN_S})
        catalog, failures = _catalog_from_tcgdex(adapter=adapter)
        self.assertEqual(failures, [])
        return catalog

    def test_it_pulls_both_chinese_combos_and_the_japanese_parent(self):
        """JP is not a target. It is fetched because the sharpest test in the
        set is a Chinese card against its Japanese parent, and you cannot build
        that pair from one side of it."""
        languages = {c["language"] for c in self._catalog()}
        self.assertEqual(languages, {"CN-S", "CN-T", "JP"})

    def test_the_traditional_chinese_pair_is_found_by_its_shared_number(self):
        """CN-T reuses the Japanese numbers, so this is the MERGE case: two
        cards in one bucket that must not become one card."""
        from resolve.candidates import generate
        ideas = generate(self._catalog())
        cn_t = [i for i in ideas.get("pkmn:CN-T", [])]
        self.assertTrue(cn_t)
        self.assertEqual(cn_t[0].priority, "same_art_across_languages")
        self.assertIn("pkmn:sv2a:170/165:ar:JP", cn_t[0].siblings)

    def test_the_simplified_chinese_pair_is_found_despite_renumbering(self):
        """CN-S renumbers, so there is no shared number and the number-keyed
        rule finds nothing. The illustrator join is what surfaces it -- and the
        candidate says so, because it is a weaker join."""
        from resolve.candidates import generate
        ideas = generate(self._catalog())
        cn_s = ideas.get("pkmn:CN-S", [])
        self.assertTrue(cn_s)
        top = cn_s[0]
        self.assertEqual(top.priority, "same_art_across_languages")
        self.assertIn("RENUMBERS", top.why)
        self.assertIn("pkmn:sv2a:170/165:ar:JP", top.siblings)
        self.assertIn("illustrator", top.why)

    def test_an_ambiguous_illustrator_join_proposes_no_parent_and_says_so(self):
        """A wrong pairing accepted silently costs the measurement. A wrong
        pairing proposed costs one rejection. So where the join is ambiguous it
        proposes the card alone and names the ambiguity."""
        from resolve.candidates import generate
        catalog = self._catalog()
        catalog.append({"card_uid": "pkmn:sv2a:999/165:ar:JP", "game": "pkmn",
                        "language": "JP", "set_code": "sv2a",
                        "number": "999/165", "variant": "ar",
                        "name": "ピカチュウ", "artist": "Oswaldo KATO"})
        cn_s = generate(catalog).get("pkmn:CN-S", [])
        top = cn_s[0]
        self.assertEqual(top.siblings, [])
        self.assertIn("ambiguous", top.why)

    def test_the_japanese_printing_is_not_proposed_for_labelling(self):
        """It was fetched to pair against. Proposing it would quietly re-open
        a combo this run is not for."""
        from resolve.label_cli import _propose_from
        import tempfile
        catalog = self._catalog()
        out = os.path.join(tempfile.mkdtemp(), "queue.json")
        _propose_from(catalog, out, only={"pkmn:CN-S", "pkmn:CN-T"})
        with open(out, encoding="utf-8") as handle:
            queue = json.load(handle)["candidates"]
        self.assertTrue(queue)
        self.assertEqual({c["card"]["language"] for c in queue},
                         {"CN-S", "CN-T"})

    def test_an_already_labelled_card_is_not_proposed_again(self):
        """The generator is re-runnable as new sets drop. 170/151 is one of the
        externally-researched seeds, so it is settled and must not come back
        round for a second adjudication."""
        from resolve.label_cli import _propose_from
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "queue.json")
        _propose_from(self._catalog(), out, only={"pkmn:CN-S", "pkmn:CN-T"})
        with open(out, encoding="utf-8") as handle:
            queue = json.load(handle)["candidates"]
        proposed = {c["card"]["card_uid"] for c in queue}
        self.assertIn("pkmn:151C:174/151:ar:CN-S", proposed)
        self.assertNotIn("pkmn:151C:170/151:ar:CN-S", proposed,
                         "a card already in the labelled set was re-proposed")

    def test_one_piece_simplified_chinese_is_still_manual(self):
        """The gap that this session does NOT close, asserted so it cannot
        quietly stop being reported."""
        from resolve.label_cli import TCGDEX_COMBOS
        self.assertNotIn(("optcg", "CN-S"), TCGDEX_COMBOS)
        self.assertEqual(set(TCGDEX_COMBOS),
                         {("pkmn", "CN-S"), ("pkmn", "CN-T")})
