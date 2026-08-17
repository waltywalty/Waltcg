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
import urllib.parse

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


def tcgdex_routes(code, cards, rarities=None, honour_filter=True):
    """Routes for the server-side-filter strategy, which is the one tcgdex
    takes when `?rarity=` is honoured.

    Order matters: the fake transport matches by substring, so the filtered
    `/cards?rarity=` route must come before the unfiltered `/cards?`.
    """
    rarities = rarities or sorted({c.get("rarity") for c in cards if c.get("rarity")})
    # `filter_is_honoured` requires the filtered list to be SHORTER than the
    # unfiltered one, so the unfiltered route returns cards plus a filler.
    unfiltered = list(cards) + [{"id": f"{code}-filler", "localId": "999",
                                 "name": "filler"}]
    routes = {}
    for rarity in rarities:
        routes[f"/{code}/cards?rarity={urllib.parse.quote(rarity)}"] = [
            c for c in cards if c.get("rarity") == rarity]
    routes[f"/{code}/cards?rarity="] = []          # any other rarity: empty
    routes[f"/{code}/cards?"] = unfiltered
    routes[f"/{code}/rarities"] = list(rarities)
    return routes


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
        adapter = build(TcgdexAdapter, tcgdex_routes("zh-tw", [
            {"id": "sv2aF-170", "localId": "170/165", "name": "皮卡丘",
             "rarity": "Illustration rare", "illustrator": "Oswaldo KATO",
             "set_id": "sv2aF"}]))
        rows = adapter.enumerate_combo("pkmn", "CN-T")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["card_uid"], "pkmn:sv2aF:170/165:ar:CN-T")
        self.assertEqual(rows[0]["name_jp"], "皮卡丘")
        self.assertNotIn("name_en", rows[0],
                         "a Traditional Chinese printing claimed an English name")
        self.assertEqual(adapter.strategy, "server_side_filter")


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

    # Rarities are tcgdex's normalised English enum, not AR/SAR abbreviations:
    # SAR is `Special illustration rare`, AR is `Illustration rare`.
    JP = tcgdex_routes("ja", [
        {"id": "sv2a-170", "localId": "170/165", "name": "ピカチュウ",
         "rarity": "Illustration rare", "illustrator": "Oswaldo KATO",
         "set_id": "sv2a"},
        {"id": "sv2a-201", "localId": "201/165", "name": "リザードンex",
         "rarity": "Special illustration rare", "illustrator": "Takumi Wada",
         "set_id": "sv2a"}])
    CN_T = tcgdex_routes("zh-tw", [
        {"id": "sv2aF-170", "localId": "170/165", "name": "皮卡丘",
         "rarity": "Illustration rare", "illustrator": "Oswaldo KATO",
         "set_id": "sv2aF"}])
    # 174/151 deliberately: 170-173/151 are already in the labelled set as
    # externally-researched seeds, and an already-labelled card is not
    # re-proposed. See test_an_already_labelled_card_is_not_proposed_again.
    CN_S = tcgdex_routes("zh-cn", [
        {"id": "151C-174", "localId": "174/151", "name": "皮卡丘",
         "rarity": "Illustration rare", "illustrator": "Oswaldo KATO",
         "set_id": "151C"},
        {"id": "151C-170", "localId": "170/151", "name": "皮卡丘",
         "rarity": "Illustration rare", "illustrator": "Oswaldo KATO",
         "set_id": "151C"}])

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


class TheCatalogStepReportsWhateverHappens(unittest.TestCase):
    """Run #7's catalog step produced no summary section at all.

    It was present and correctly ordered. It ran, found zero cards, and
    returned 1 -- and GitHub runs `bash -e`, so the script aborted on that exit
    code and the shell block that would have EXPLAINED the zero never
    executed. `continue-on-error` then hid the failed step.

    A step that produces the input for everything downstream and reports
    nothing is the same invisibility `no_targets` exists to prevent, one layer
    up. So: the report is Python, and it is written BEFORE the exit code.
    """

    def _targets(self, **over):
        base = {"_generated_at": "2026-08-17T06:15:00Z",
                "_counts": {"pkmn:EN": 0, "pkmn:CN-S": 40},
                "_combo_status": {
                    "pkmn:EN": {"status": "source_unreachable", "cards": 0,
                                "sources": [], "asked": ["tcgapi"]},
                    "pkmn:CN-S": {"status": "ok", "cards": 40,
                                  "sources": ["tcgdex"], "asked": ["tcgdex"]}},
                "_routing": {"pkmn:CN-S": {"manual": 40}},
                "_gaps": [{"combo": "pkmn:EN", "reason": "source_unreachable",
                           "detail": "no tcgapi set endpoint answered"}]}
        base.update(over)
        return base

    def test_the_summary_survives_a_nonzero_exit(self):
        """The actual regression. Written before `return 0 if total else 1`."""
        import subprocess
        import tempfile
        work = tempfile.mkdtemp()
        summary = os.path.join(work, "summary.md")
        result = subprocess.run(
            [sys.executable, "-m", "ingest.catalog", "--write",
             "--out", os.path.join(work, "targets.json"),
             "--summary", summary],
            capture_output=True, text=True, cwd=os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
        # No network here, so it finds nothing and exits 1 -- which is the
        # exact condition under which run #7 wrote nothing.
        self.assertEqual(result.returncode, 1)
        self.assertTrue(os.path.exists(summary), "no summary file was written")
        with open(summary, encoding="utf-8") as handle:
            text = handle.read()
        self.assertTrue(text.strip(), "the summary came back empty again")
        self.assertIn("Catalog -> targets", text)

    def test_it_reports_counts_per_combo_and_per_price_source(self):
        from ingest.catalog import render_catalog_summary
        text = render_catalog_summary(self._targets())
        self.assertIn("`pkmn:EN`", text)
        self.assertIn("source_unreachable", text)
        self.assertIn("`pkmn:CN-S`", text)
        self.assertIn("manual (40)", text)

    def test_zero_targets_says_what_will_happen_next(self):
        from ingest.catalog import render_catalog_summary
        text = render_catalog_summary(self._targets(_counts={"pkmn:EN": 0}))
        self.assertIn("ZERO cards tracked", text)
        self.assertIn("no_targets", text)

    def test_it_names_which_endpoints_answered(self):
        """The four tcgapi/apitcg catalog endpoints were never verified --
        probe/COVERAGE.md records a 200 only from /v1/games and /v1/search. A
        wrong URL came back as 'this combination has no chase cards'."""
        from ingest.catalog import CatalogBuilder, render_catalog_summary
        builder = CatalogBuilder(tcgapi=object(), apitcg=object())
        builder.endpoints_used = {"tcgapi.sets": "https://x/v1/sets"}
        text = render_catalog_summary(self._targets(), builder)
        self.assertIn("tcgapi.sets", text)
        self.assertIn("Endpoints that answered", text)

    def test_no_endpoint_answering_is_stated_as_the_cause(self):
        from ingest.catalog import CatalogBuilder, render_catalog_summary
        builder = CatalogBuilder(tcgapi=object(), apitcg=object())
        text = render_catalog_summary(self._targets(), builder)
        self.assertIn("NONE", text)

    def test_it_reports_its_own_call_counts(self):
        """Separate accounting from the ingest step. 'The ingest step made 0
        calls' says nothing about whether the CATALOG step called anything."""
        from ingest.catalog import CatalogBuilder, render_catalog_summary
        builder = CatalogBuilder()
        builder.tcgapi.quota.consumed_this_run = 12
        text = render_catalog_summary(self._targets(), builder)
        self.assertIn("12 calls", text)
        self.assertIn("not called", text)      # apitcg made none


class ZeroForACombinationHasFourMeanings(unittest.TestCase):
    """Request #4: "catalog ran and found nothing for pkmn:EN" is a different
    fact from "catalog never ran"."""

    class Fake:
        can_enumerate = True
        cannot_enumerate_because = ""

        def __init__(self, serves=()):
            self.serves = set(serves)

        def enumerate_combo(self, game, language):
            return []

    def _builder(self, serves=()):
        from ingest.adapters import TcgApiAdapter
        from ingest.catalog import CatalogBuilder
        return CatalogBuilder(tcgapi=build(TcgApiAdapter, {}), apitcg=object(),
                              cn_sources={"tcgdex": self.Fake(serves),
                                          "wiki52poke": self.Fake()})

    def test_nothing_serves_it_is_no_catalog_source(self):
        builder = self._builder()
        builder.sets_for = lambda g, l: []
        builder.apitcg_cards = lambda g, l: []
        builder.build([("optcg", "CN-S")])
        self.assertEqual(builder.combo_status["optcg:CN-S"]["status"],
                         "no_catalog_source")

    def test_asked_and_answered_with_nothing_trackable_is_catalog_ran_empty(self):
        builder = self._builder()
        builder.sets_for = lambda g, l: (builder.attempt((g, l), "tcgapi"), [])[1]
        builder.apitcg_cards = lambda g, l: []
        builder.build([("pkmn", "EN")])
        self.assertEqual(builder.combo_status["pkmn:EN"]["status"],
                         "catalog_ran_empty")

    def test_asked_and_not_answered_is_source_unreachable(self):
        builder = self._builder()

        def boom(game, language):
            builder.attempt((game, language), "tcgapi")
            raise AdapterGaveUp("no tcgapi set endpoint answered")

        builder.sets_for = boom
        builder.apitcg_cards = lambda g, l: []
        builder.build([("pkmn", "EN")])
        self.assertEqual(builder.combo_status["pkmn:EN"]["status"],
                         "source_unreachable")

    def test_the_tcgapi_game_gap_is_not_the_combo_verdict(self):
        """Naming tcgapi's missing game entry `no_catalog_source` made
        pkmn:CN-S report 'nothing serves this' while tcgdex was serving it 877
        cards. It is a fact about tcgapi, not about the combination."""
        builder = self._builder(serves={("pkmn", "CN-T")})
        builder.apitcg_cards = lambda g, l: []
        builder.build([("pkmn", "CN-T")])
        reasons = {g["reason"] for g in builder.gaps}
        self.assertIn("tcgapi_no_game_entry", reasons)
        self.assertNotEqual(builder.combo_status["pkmn:CN-T"]["status"],
                            "no_catalog_source")

    def test_the_runner_distinguishes_never_ran_from_ran_and_found_nothing(self):
        from ingest.runner import describe_target_absence
        never = describe_target_absence("tcgapi", {})
        self.assertIn("NEVER RAN", never)
        self.assertIn("ingest.catalog --write", never)

        ran = describe_target_absence("tcgapi", {
            "_generated_at": "2026-08-17T06:15:00Z", "_routing": {},
            "_combo_status": {"pkmn:EN": {"status": "source_unreachable"}}})
        self.assertIn("RAN", ran)
        self.assertNotIn("NEVER RAN", ran)
        self.assertIn("source_unreachable", ran)

    def test_a_routing_fault_is_named_as_one(self):
        """Catalog found cards and routed them here, but the list arrived
        empty. Different problem, different fix."""
        from ingest.runner import describe_target_absence
        text = describe_target_absence("tcgapi", {
            "_generated_at": "T", "_routing": {"pkmn:EN": {"tcgapi": 40}}})
        self.assertIn("ROUTING fault", text)


class NoStepPutsLogicInAShell(unittest.TestCase):
    """Runs #4 and #7 were both shell logic inside YAML that no test could
    reach. Two is a pattern, so this asserts the pattern is gone."""

    def _workflow(self):
        import yaml
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), ".github", "workflows", "ingest.yml")
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def test_no_step_embeds_a_heredoc(self):
        offenders = [s.get("name") for s in self._workflow()["jobs"]["snapshot"]["steps"]
                     if "<<" in (s.get("run") or "")]
        self.assertEqual(offenders, [],
                         "a workflow step embeds a heredoc no test can reach")

    def test_the_catalog_step_runs_before_the_ingest_step(self):
        names = [s.get("name", "") for s in
                 self._workflow()["jobs"]["snapshot"]["steps"]]
        catalog = next(i for i, n in enumerate(names) if n.startswith("Build targets"))
        ingest = next(i for i, n in enumerate(names) if n.startswith("Run adapters"))
        self.assertLess(catalog, ingest,
                        "targets are read before they are written")

    def test_the_catalog_step_passes_its_own_summary_flag(self):
        """Not a shell redirect after the command -- inside it, so no exit
        code can suppress the report."""
        step = next(s for s in self._workflow()["jobs"]["snapshot"]["steps"]
                    if s.get("name", "").startswith("Build targets"))
        self.assertIn("--summary", step["run"])
        self.assertNotIn(">>", step["run"])


class TheRoutingMapIsBuiltNotDeclared(unittest.TestCase):
    """`to_targets` must actually compute which price source each combo's
    cards go to. Asserting the renderer prints a routing map it was handed
    proves nothing about whether one is ever produced."""

    def _catalog(self):
        return {
            "pkmn:EN": {"sources": ["tcgapi"], "cards": [
                {"card_uid": "pkmn:sv3:223/197:sir:EN", "game": "pkmn",
                 "language": "EN", "name": "Charizard ex", "number": "223/197",
                 "set_code": "sv3", "external_id": "1"}]},
            "optcg:EN": {"sources": ["tcgapi"], "cards": [
                {"card_uid": "optcg:OP05:OP05-119:manga_rare:EN",
                 "game": "optcg", "language": "EN", "name": "Luffy",
                 "number": "OP05-119", "set_code": "OP05", "external_id": "2"}]},
            "pkmn:CN-S": {"sources": ["tcgdex"], "cards": [
                {"card_uid": "pkmn:151C:170/151:ar:CN-S", "game": "pkmn",
                 "language": "CN-S", "name": "Pikachu", "number": "170/151",
                 "set_code": "151C", "external_id": "3"}]},
        }

    def test_pokemon_routes_to_ppt_and_one_piece_to_pricecharting(self):
        from ingest.catalog import to_targets
        routing = to_targets(self._catalog(), [])["_routing"]
        self.assertIn("pokemonpricetracker", routing["pkmn:EN"])
        self.assertIn("pricecharting", routing["optcg:EN"])
        self.assertNotIn("pricecharting", routing["pkmn:EN"])

    def test_chinese_printings_route_only_to_manual(self):
        """No price source covers a Chinese printing. Routing them anywhere
        else spends quota on a guaranteed miss."""
        from ingest.catalog import to_targets
        routing = to_targets(self._catalog(), [])["_routing"]
        self.assertEqual(set(routing["pkmn:CN-S"]), {"manual"})

    def test_the_counts_match_the_card_lists(self):
        from ingest.catalog import to_targets
        targets = to_targets(self._catalog(), [])
        self.assertEqual(targets["_routing"]["pkmn:EN"]["tcgapi"], 1)
        self.assertEqual(len(targets["tcgapi"]["cards"]), 2)
        self.assertEqual(len(targets["pokemonpricetracker"]["cards"]), 1)

    def test_a_combo_with_no_cards_still_appears_in_the_routing_map(self):
        """A combo that routed nowhere must be distinguishable from one that
        was never considered."""
        from ingest.catalog import to_targets
        catalog = self._catalog()
        catalog["riftbound:EN"] = {"sources": [], "cards": []}
        routing = to_targets(catalog, [])["_routing"]
        self.assertIn("riftbound:EN", routing)
        self.assertEqual(routing["riftbound:EN"], {})


class TheCatalogEndpointsComeFromConfirmedSlugs(unittest.TestCase):
    """Run #8's three candidate query-string shapes all 404'd, and the reason
    was structural: tcgapi's set and card paths are SLUG-BASED AND NESTED.

        /v1/games/{gameSlug}/sets/{setSlug}/cards

    The numeric ids address `/v1/search` and `/v1/games` and nothing else. The
    obvious slug guesses are wrong in the quietest possible way -- `one-piece`
    is APITCG's slug for the same game; tcgapi calls it `one-piece-card-game`.
    """

    def _builder(self, routes):
        from ingest.adapters import TcgApiAdapter
        from ingest.catalog import CatalogBuilder
        return CatalogBuilder(tcgapi=build(TcgApiAdapter, routes),
                              apitcg=object())

    def test_the_confirmed_slug_is_used_not_the_obvious_guess(self):
        from resolve.identity import TCGAPI_GAME_SLUG
        self.assertEqual(TCGAPI_GAME_SLUG[("optcg", "EN")],
                         "one-piece-card-game")
        self.assertNotEqual(TCGAPI_GAME_SLUG[("optcg", "EN")], "one-piece")

    def test_sets_are_read_from_the_nested_slug_path(self):
        builder = self._builder(
            {"/v1/games/pokemon/sets": {"data": [{"code": "sv3"}]}})
        sets = builder.sets_for("pkmn", "EN")
        self.assertEqual(len(sets), 1)
        self.assertIn("games/{slug}/sets", builder.endpoints_used["tcgapi.sets"])

    def test_cards_are_read_from_the_nested_set_path(self):
        builder = self._builder(
            {"/v1/games/pokemon/sets/sv3/cards":
             {"data": [{"number": "223/197", "name": "Charizard ex",
                        "rarity": "Special Illustration Rare"}]}})
        cards = builder.cards_in_set("pkmn", "EN", "sv3")
        self.assertEqual(len(cards), 1)

    def test_an_unconfirmed_language_is_resolved_not_invented(self):
        """Only English slugs are confirmed. `pokemon-japan` is a plausible
        guess and plausible guesses are what cost run #7, so a slug that is not
        confirmed is looked up in the provider's own /v1/games."""
        from resolve.identity import TCGAPI_GAME_SLUG
        self.assertNotIn(("pkmn", "JP"), TCGAPI_GAME_SLUG)
        builder = self._builder({"/v1/games?": {
            "data": [{"id": "19", "slug": "pokemon-japanese"}], "meta": {}}})
        self.assertEqual(builder.game_slug("pkmn", "JP"), "pokemon-japanese")

    def test_an_unresolvable_slug_is_a_gap_not_a_guess(self):
        builder = self._builder({})
        self.assertIsNone(builder.game_slug("pkmn", "JP"))
        builder.sets_for("pkmn", "JP")
        reasons = {g["reason"] for g in builder.gaps}
        self.assertIn("tcgapi_no_game_entry", reasons)

    def test_the_games_list_is_read_once_not_per_combo(self):
        builder = self._builder({"/v1/games?": {
            "data": [{"id": "19", "slug": "pokemon-japanese"}], "meta": {}}})
        builder.game_slug("pkmn", "JP")
        before = builder.tcgapi.quota.consumed_this_run
        builder.game_slug("pkmn", "JP")
        self.assertEqual(builder.tcgapi.quota.consumed_this_run, before)


class ApitcgMatchesItsOpenApiSpec(unittest.TestCase):
    """Every previous run got a non-JSON body from apitcg, which is what a
    wrong endpoint looks like when the host serves an HTML SPA. Read from
    raw.githubusercontent.com/apitcg/docs.apitcg.com/main/openapi.json.

    Two things were wrong, and neither was a parsing bug.
    """

    def test_the_host_is_the_api_subdomain(self):
        """`apitcg.com` is the docs SPA. The API is `api.apitcg.com`."""
        from ingest.adapters import ApiTcgAdapter
        self.assertEqual(ApiTcgAdapter.host, "api.apitcg.com")
        self.assertTrue(ApiTcgAdapter.BASE.startswith("https://api.apitcg.com"))

    def test_there_is_no_cards_endpoint(self):
        """Absent from openapi.json means non-existent, not missing data.
        Cards are products."""
        from ingest.adapters import ApiTcgAdapter
        for template in (ApiTcgAdapter.PRODUCTS, ApiTcgAdapter.BY_CODE):
            self.assertIn("/api/products", template)
            self.assertNotIn("/cards", template)

    def test_it_paginates_with_the_documented_parameters(self):
        from ingest.adapters import ApiTcgAdapter
        self.assertIn("limit=", ApiTcgAdapter.PRODUCTS)
        self.assertIn("page=", ApiTcgAdapter.PRODUCTS)
        self.assertLessEqual(ApiTcgAdapter.PAGE_SIZE, 100,
                             "the spec caps limit at 100")

    def test_rarity_is_read_from_the_attributes_map(self):
        """`rarity` is not a top-level property. It lives in `attributes`, a
        free-form string map whose keys depend on the game."""
        from ingest.adapters import ApiTcgAdapter
        adapter = build(ApiTcgAdapter, {})
        hit = {"name": "Sanji", "attributes": {"Rarity": "SR",
                                               "Number": "OP01-013",
                                               "Artist": "Nekobayashi"}}
        self.assertEqual(adapter._attr(hit, "Rarity"), "SR")
        self.assertEqual(adapter._attr(hit, "Artist"), "Nekobayashi")

    def test_attribute_keys_are_read_case_insensitively(self):
        """The keys depend on the game, so a fixed spelling would work for One
        Piece and silently return nothing for anything else."""
        from ingest.adapters import ApiTcgAdapter
        adapter = build(ApiTcgAdapter, {})
        self.assertEqual(
            adapter._attr({"attributes": {"rarity": "TR"}}, "Rarity"), "TR")

    def test_its_slug_is_not_tcgapis_slug(self):
        """Two providers, two vocabularies for one game. Confusing them is
        what identity.py exists to prevent."""
        from ingest.adapters import ApiTcgAdapter
        from resolve.identity import TCGAPI_GAME_SLUG
        self.assertEqual(ApiTcgAdapter.SLUG["optcg"], "one-piece")
        self.assertEqual(TCGAPI_GAME_SLUG[("optcg", "EN")],
                         "one-piece-card-game")

    def test_products_reads_the_total_for_pagination(self):
        from ingest.adapters import ApiTcgAdapter
        adapter = build(ApiTcgAdapter, {"/api/products": {
            "success": True, "total": 128,
            "data": [{"name": "Sanji", "attributes": {"Rarity": "SR"}}]}})
        rows, total = adapter.products("optcg")
        self.assertEqual(total, 128)
        self.assertEqual(len(rows), 1)


class TheCatalogFilterUsesTheRarityAwareClassifier(unittest.TestCase):
    """`rarity_band(None)` is `base`, and `base` is not tracked. That single
    substitution is what turned 8,313 tcgdex cards into zero targets, so the
    catalog builder must use `band_of`, which answers `unknown`."""

    def _builder(self):
        from ingest.catalog import CatalogBuilder
        return CatalogBuilder(tcgapi=object(), apitcg=object())

    def _hit(self, rarity):
        return {"card_uid": "pkmn:151C:170/151:ar:CN-S", "set_code": "151C",
                "number": "170/151", "variant": "ar", "rarity": rarity,
                "name_jp": "皮卡丘"}

    def test_a_card_with_no_rarity_survives_the_filter(self):
        """The regression. It is not classifiable, so it is tracked and
        counted -- not silently discarded as if it were a common."""
        row = self._builder()._cn_row("pkmn", "CN-S", self._hit(None))
        self.assertIsNotNone(row, "a card with unknown rarity was dropped")

    def test_a_common_is_still_dropped(self):
        """The exemption is for UNKNOWN, not for everything."""
        self.assertIsNone(
            self._builder()._cn_row("pkmn", "CN-S", self._hit("Common")))

    def test_a_chase_card_is_kept(self):
        self.assertIsNotNone(self._builder()._cn_row(
            "pkmn", "CN-S", self._hit("Special illustration rare")))

    def test_a_digital_pocket_card_is_dropped(self):
        """Nothing to grade, so nothing to track."""
        self.assertIsNone(
            self._builder()._cn_row("pkmn", "CN-S", self._hit("Crown")))


class TheSirSarCollapseIsResolvedByLanguage(unittest.TestCase):
    """tcgdex normalises two DIFFERENT market conventions into one string.

    A `Special illustration rare` is a SIR in English sets and a SAR in
    Japanese ones, and this repository has always kept them apart --
    `pkmn:sv3:223/197:sir:EN` and `pkmn:sv3:108/108:sar:JP` are the same art in
    two markets with two price series. The provider cannot tell them apart, so
    the language does; it is the only information that survives the
    normalisation.
    """

    def _uid(self, code, language):
        adapter = build(TcgdexAdapter, tcgdex_routes(code, [
            {"id": f"{code}-1", "localId": "198/165", "name": "x",
             "rarity": "Special illustration rare", "set_id": "sv2a"}]))
        rows = adapter.enumerate_combo("pkmn", language)
        self.assertEqual(len(rows), 1)
        return rows[0]["card_uid"]

    def test_english_gets_sir(self):
        self.assertIn(":sir:EN", self._uid("en", "EN"))

    def test_japanese_gets_sar(self):
        self.assertIn(":sar:JP", self._uid("ja", "JP"))

    def test_both_chinese_printings_follow_the_japanese_convention(self):
        self.assertIn(":sar:CN-T", self._uid("zh-tw", "CN-T"))
        self.assertIn(":sar:CN-S", self._uid("zh-cn", "CN-S"))

    def test_the_two_are_different_cards(self):
        self.assertNotEqual(self._uid("en", "EN"), self._uid("ja", "JP"))

    def test_illustration_rare_is_ar_in_every_language(self):
        """Only the SIR/SAR pair collapses. AR does not, and inventing a
        second language rule would be a guess."""
        from resolve.identity import variant_from_rarity
        for language in ("EN", "JP", "CN-S", "CN-T"):
            self.assertEqual(
                variant_from_rarity("Illustration rare", None, language), "ar")
