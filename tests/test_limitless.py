"""The Limitless parser, against the page shapes that were actually observed.

The first version of this file passed 20 tests against fixtures I invented,
and the parser it was testing was wrong on 100% of real pages -- it read the
product off the title, and a real title's first parenthesised token is the
CARD NUMBER. My fixtures agreeing with my regexes was not evidence, and the
mutants that "caught" a broken product read were confirming a broken read.

So the tests that matter here are the ones pinned to observations: the title
is not a product source, the reprint line is card-level, the print table is a
complete manifest, and the image filename is what binds `?v=N` to `_pN`.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.base import AdapterGaveUp  # noqa: E402
from ingest.limitless import (LimitlessAdapter, attest,  # noqa: E402
                              build_product_index, canonical_slot, image_slot,
                              observed_slot, parse_variant_page, print_table,
                              print_table_rows, product_line,
                              product_attestation, reconcile, reprint_note,
                              render_attestation_report, render_binding_report,
                              slot_binding_evidence, split_label, verify_slot)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "limitless")


def page(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


BASE = page("op01-120_base.html")
V2 = page("op01-120_v2.html")
V4 = page("op01-120_v4.html")
SILENT = page("no_product.html")
PRB_BASE = page("prb01-002_base.html")


class TheTitleIsNotAProductSource(unittest.TestCase):
    """The regression that mattered. `Shanks (OP01-120) - Romance Dawn` puts
    the CARD NUMBER in the first brackets, on every page."""

    def test_the_product_comes_off_the_href_slug(self):
        self.assertEqual(product_line(V2)["set_code"], "op01")
        self.assertEqual(product_line(V2)["slug"], "op01-romance-dawn")

    def test_the_card_number_never_appears_as_a_product_code(self):
        for name, html in (("base", BASE), ("v2", V2), ("v4", V4),
                           ("silent", SILENT)):
            with self.subTest(page=name):
                parsed = parse_variant_page(html)
                self.assertNotIn(parsed["set_code"],
                                 ("OP01-120", "op01-120"))

    def test_a_page_with_no_product_link_attests_nothing(self):
        """Its title still says `Shanks (OP01-120)`. Reading that gives the
        number as the product code, which is what the old parser did."""
        self.assertIsNone(product_line(SILENT))
        self.assertIsNone(parse_variant_page(SILENT)["set_code"])
        self.assertFalse(product_attestation(SILENT, "OP01",
                                             "OP01-120")["attested"])

    def test_the_bracketed_code_is_only_a_cross_check(self):
        line = product_line(V4)
        self.assertEqual(line["set_code"], "prb01")       # from the slug
        self.assertEqual(line["stated_code"], "PRB01")    # from the text

    def test_a_slug_disagreeing_with_its_text_is_refused_not_averaged(self):
        bad = ('<a href="/cards/prb01-premium-booster">Romance Dawn (OP01) '
               'Manga Art</a>')
        self.assertIsNone(product_line(bad))


class TheReprintLineIsCardLevel(unittest.TestCase):
    """It says "This variant has been reprinted in" and appears IDENTICALLY on
    the base page and on ?v=2. Read as variant attribution it attests the
    manga printing to prb01 -- the wrong answer, and the expensive one."""

    def test_the_line_is_identical_on_both_pages(self):
        self.assertEqual(reprint_note(BASE)["text"], reprint_note(V2)["text"])

    def test_it_is_labelled_card_scoped(self):
        self.assertEqual(reprint_note(V2)["scope"], "card")

    def test_the_manga_printing_is_op01_not_prb01(self):
        """S1's answer. The reprint line on this page names PRB01; the
        variant-scoped product link names op01. The link wins."""
        self.assertEqual(reprint_note(V2)["product_code"], "prb01")
        self.assertEqual(parse_variant_page(V2)["set_code"], "op01")

    def test_a_page_without_the_line_reports_none(self):
        self.assertIsNone(reprint_note(V4))


class OneFetchPerCard(unittest.TestCase):

    def test_the_print_table_lists_every_printing_but_its_own(self):
        """`?v=2` links 1, 3 and 4. The page omits the row you are on."""
        self.assertEqual(print_table(V2),
                         [{"slot": 1, "label": "Romance Dawn aa"},
                          {"slot": 3, "label": "Prize Cards serial"},
                          {"slot": 4, "label": "One Piece The Best aa"}])

    def test_the_base_page_omits_no_variant(self):
        """Base has no `?v=` of its own to leave out, so its run is complete
        -- which is exactly why a complete run cannot identify the page."""
        self.assertEqual([r["slot"] for r in print_table(BASE)], [1, 2, 3, 4])

    def test_five_printings_not_six_from_any_page(self):
        """op01 base, op01 aa, op01 manga, Prize Cards serial, prb01 aa. Each
        page undercounts by one on its links alone; adding the current
        printing back needs to know which one it is."""
        for name, html in (("base", BASE), ("v2", V2), ("v4", V4)):
            with self.subTest(page=name):
                claim = product_attestation(html, "OP01", "OP01-120")
                self.assertEqual(claim["printing_count"], 5)
                self.assertTrue(claim["printing_count_exact"])

    def test_a_page_that_cannot_place_itself_reports_a_lower_bound(self):
        blind = V2.replace("_p2_EN.webp", "_EN.webp")
        claim = product_attestation(blind, "OP01", "OP01-120")
        self.assertFalse(claim["printing_count_exact"])
        self.assertIn("AT LEAST", claim["printing_count_why"])

    def test_three_products_not_two(self):
        names = {split_label(r["label"])[0] for r in print_table(V2)}
        self.assertEqual(names, {"Romance Dawn", "Prize Cards",
                                 "One Piece The Best"})


class TheImageBindsTheSlotVocabulary(unittest.TestCase):
    """`OP01-120_p2_EN.webp` on ?v=2 is why `?v=N` and apitcg's `_pN` are one
    vocabulary as EVIDENCE rather than as an assumption about ordering."""

    def test_the_slot_comes_off_the_asset_url(self):
        found = image_slot(V2)
        self.assertEqual(found["slot"], 2)
        self.assertEqual(found["filename"], "OP01-120_p2_EN.webp")
        self.assertEqual(found["language"], "EN")

    def test_a_filename_with_no_suffix_reports_none_and_says_why(self):
        """`no suffix means base` is a convention we hold about apitcg, not
        something the page states."""
        found = image_slot(BASE)
        self.assertIsNone(found["slot"])
        self.assertIn("no _pN", found["why"])
        self.assertEqual(found["filename"], "OP01-120_EN.webp")

    def test_a_page_with_no_image_says_so(self):
        self.assertIn("no card image", image_slot("<p>nothing</p>")["why"])


class TheTreatmentIsWhatLimitlessCallsIt(unittest.TestCase):

    def test_manga_art_not_manga_alternate_art(self):
        """Marketplaces use the longer form; Limitless does not. Taking the
        marketplace's wording would reintroduce the source we rejected."""
        self.assertEqual(parse_variant_page(V2)["treatment"], "Manga Art")

    def test_the_base_treatment_is_read_too(self):
        self.assertEqual(parse_variant_page(BASE)["treatment"], "Secret Rare")

    def test_labels_split_into_product_and_short_treatment(self):
        self.assertEqual(split_label("Romance Dawn manga"),
                         ("Romance Dawn", "manga"))
        self.assertEqual(split_label("One Piece The Best aa"),
                         ("One Piece The Best", "aa"))
        self.assertEqual(split_label("Romance Dawn"), ("Romance Dawn", None))


class TheReconciliationRefuses(unittest.TestCase):

    def test_a_label_resolves_only_against_a_slug_attested_name(self):
        index = build_product_index([V2, V4])
        self.assertEqual(index["romance dawn"]["set_code"], "op01")
        self.assertEqual(index["one piece the best"]["set_code"], "prb01")
        self.assertNotIn("prize cards", index)

    def test_an_unattested_product_is_left_unresolved_not_defaulted(self):
        """`Prize Cards` appears in no slug on these pages. The entry must not
        inherit the page's own product -- that is how the manga printing would
        acquire prb01."""
        # From the BASE page, whose print table lists all four variants.
        entries = reconcile(parse_variant_page(BASE), "OP01", "OP01-120",
                            build_product_index([V2, V4]), "https://x")
        prize = [e for e in entries if e["slot"] == 3][0]
        self.assertIsNone(prize["product_set_code"])
        self.assertIn("Refusing to assume", prize["unresolved"])
        manga = [e for e in entries if e["slot"] == 2][0]
        self.assertEqual(manga["product_set_code"], "op01")

    def test_a_resolved_entry_cites_the_page_that_attested_it(self):
        entries = reconcile(parse_variant_page(BASE), "OP01", "OP01-120",
                            build_product_index([V2, V4]), "https://x")
        prb = [e for e in entries if e["slot"] == 4][0]
        self.assertEqual(prb["product_set_code"], "prb01")
        self.assertIn("prb01-premium-booster", prb["attested_by"])

    def test_ground_truth_keeps_the_semantic_token(self):
        entries = reconcile(parse_variant_page(BASE), "OP01", "OP01-120",
                            build_product_index([V2]), "https://x")
        for entry in entries:
            self.assertNotEqual(entry["label"], str(entry["slot"]))
            self.assertTrue(entry["label"][0].isalpha())


class _Pages:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def card_page(self, set_code, number, variant=None):
        self.calls.append((set_code, number, variant))
        key = (set_code, number, variant)
        if key not in self.pages:
            raise AdapterGaveUp(f"no candidate URL answered for {number}")
        return (f"https://limitless/{number}"
                + (f"?v={variant}" if variant is not None else ""),
                self.pages[key])


class Attesting(unittest.TestCase):

    def test_one_call_per_card(self):
        pages = _Pages({("OP01", "OP01-120", None): BASE,
                        ("PRB01", "PRB01-002", None): PRB_BASE})
        attest(pages, [("OP01", "OP01-120"), ("PRB01", "PRB01-002")],
               resolve_slots=False)
        self.assertEqual(pages.calls,
                         [("OP01", "OP01-120", None),
                          ("PRB01", "PRB01-002", None)])

    def test_the_index_spans_every_page_before_any_label_resolves(self):
        """prb01 is named in a slug only on PRB01-002's page, and that is
        what resolves OP01-120's slot 4 label."""
        pages = _Pages({("OP01", "OP01-120", None): BASE,
                        ("PRB01", "PRB01-002", None): PRB_BASE})
        _, entries, _, _ = attest(pages, [("OP01", "OP01-120"),
                                          ("PRB01", "PRB01-002")],
                                  resolve_slots=False)
        slot4 = [e for e in entries
                 if e["number"] == "OP01-120" and e["slot"] == 4][0]
        self.assertEqual(slot4["product_set_code"], "prb01")

    def test_a_page_that_links_no_product_is_a_failure_not_an_attestation(self):
        pages = _Pages({("OP01", "OP01-120", None): SILENT})
        attestations, entries, failures, _ = attest(pages, [("OP01", "OP01-120")], resolve_slots=False)
        self.assertFalse(attestations[0]["attested"])
        self.assertEqual(entries, [])
        self.assertIn("first parenthesised token is the card number",
                      failures[0]["why"])

    def test_an_unreachable_card_is_a_gap_not_an_absent_printing(self):
        attestations, entries, failures, _ = attest(
            _Pages({}), [("OP01", "OP01-120")])
        self.assertEqual((attestations, entries), ([], []))
        self.assertIn("no candidate URL answered", failures[0]["why"])


class ThePageIsNeverPersisted(unittest.TestCase):
    """The pages carry USD/EUR columns, marketplace links and a price history
    block. Caching one is persisting provider price data."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _adapter(self, answers):
        tried = []

        def transport(url, headers):
            tried.append(url)
            status, body = answers(url)
            return status, body.encode("utf-8"), {}

        return LimitlessAdapter(raw_root=self._tmp.name, sleep=lambda _s: None,
                                transport=transport,
                                monotonic=lambda: 0.0), tried

    def test_nothing_is_written_to_the_raw_root(self):
        adapter, _ = self._adapter(lambda url: (200, V2))
        adapter.card_page("OP01", "OP01-120")
        self.assertEqual(os.listdir(self._tmp.name), [])

    def test_cache_raw_is_not_called_at_all(self):
        adapter, _ = self._adapter(lambda url: (200, V2))
        adapter.cache_raw = lambda *a, **k: self.fail(
            "cache_raw called: the page carries prices")
        adapter.card_page("OP01", "OP01-120")

    def test_the_log_records_that_it_was_parsed_in_memory(self):
        adapter, _ = self._adapter(lambda url: (200, V2))
        adapter.card_page("OP01", "OP01-120")
        self.assertIn("parsed in memory", adapter.log[0])


class TheUrlShapeIsProbed(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _adapter(self, answers):
        tried = []

        def transport(url, headers):
            tried.append(url)
            status, body = answers(url)
            return status, body.encode("utf-8"), {}

        return LimitlessAdapter(raw_root=self._tmp.name, sleep=lambda _s: None,
                                transport=transport,
                                monotonic=lambda: 0.0), tried

    def test_the_second_candidate_answers_and_is_recorded(self):
        adapter, tried = self._adapter(
            lambda url: (404, "nope") if url.startswith("https://onepiece.")
            else (200, V2))
        url, body = adapter.card_page("OP01", "OP01-120")
        self.assertTrue(url.startswith("https://limitlesstcg.com/"))
        self.assertEqual(adapter.endpoints_used["OP01-OP01-120"], url)
        self.assertEqual(parse_variant_page(body)["set_code"], "op01")

    def test_leading_zeros_are_stripped_for_the_index_shape(self):
        adapter, tried = self._adapter(lambda url: (200, V2))
        adapter.card_page("OP01", "OP01-070")
        self.assertIn("/OP01/70", tried[0])

    def test_giving_up_names_every_url_it_tried(self):
        adapter, tried = self._adapter(lambda url: (404, "nope"))
        with self.assertRaises(AdapterGaveUp) as caught:
            adapter.card_page("OP01", "OP01-120")
        for url in tried:
            self.assertIn(url, str(caught.exception))

    def test_no_variant_suffix_is_ever_requested(self):
        """One fetch per card. Walking ?v= links is fetching a list the first
        page already handed over."""
        adapter, tried = self._adapter(lambda url: (200, V2))
        adapter.card_page("OP01", "OP01-120")
        self.assertEqual([u for u in tried if "?v=" in u], [])


class TheReportDistinguishesTheOutcomes(unittest.TestCase):

    def test_an_unresolved_slot_is_marked_not_blanked(self):
        entries = reconcile(parse_variant_page(BASE), "OP01", "OP01-120",
                            build_product_index([V2]), "https://x")
        report = render_attestation_report([], entries, [])
        self.assertIn("**unresolved**", report)

    def test_nothing_fetched_is_stated_not_rendered_as_success(self):
        self.assertIn("Nothing was fetched",
                      render_attestation_report([], [], []))

    def test_the_report_says_the_product_is_not_from_the_title(self):
        report = render_attestation_report(
            [dict(product_attestation(V2, "OP01", "OP01-120"),
                  url="https://x")], [], [])
        self.assertIn("card number", report)


class TheFixturesCarryNoPrices(unittest.TestCase):
    """A fixture with a price table would put on disk exactly what the adapter
    is written never to put on disk."""

    def test_no_fixture_mentions_a_marketplace_or_a_price(self):
        import re
        money = re.compile(r"[$€£]\s?\d|\b\d+\.\d{2}\b", re.I)
        # Comments stripped first: each fixture DECLARES that it omits the
        # price table, and scanning the declaration for the word it declares
        # about fails every file that is doing the right thing.
        comment = re.compile(r"<!--.*?-->", re.S)
        for name in os.listdir(FIXTURES):
            if not name.endswith(".html"):
                continue
            markup = comment.sub(" ", page(name)).lower()
            with self.subTest(fixture=name):
                self.assertIsNone(money.search(markup))
                for banned in ("tcgplayer", "cardmarket", "price",
                               "usd", "eur"):
                    self.assertNotIn(banned, markup)

    def test_every_fixture_declares_itself_synthetic(self):
        for name in os.listdir(FIXTURES):
            if name.endswith(".html"):
                with self.subTest(fixture=name):
                    self.assertIn("SYNTHETIC", page(name))


if __name__ == "__main__":
    unittest.main()


class ThePageSaysWhichPrintingItIs(unittest.TestCase):
    """Three independent signals, compared and never merged."""

    def test_the_gap_in_the_run_names_the_page(self):
        """On ?v=2 the links run 1, 3, 4. The missing integer is the page,
        and a missing integer reads the same in HTML and in markdown -- which
        is why this signal, not `which element lacks an anchor`."""
        rows = print_table_rows(V2)
        self.assertEqual(rows["unlinked_slot"], 2)
        self.assertEqual(rows["unlinked_label"], "Romance Dawn manga")

    def test_a_complete_run_abstains_instead_of_guessing_base(self):
        """Links 1..4 with nothing omitted is equally the base page and the
        ?v=5 page. A signal that cannot tell two printings apart must not pick
        one, or it out-votes the signal that can."""
        rows = print_table_rows(BASE)
        self.assertIsNone(rows["unlinked_slot"])
        self.assertIn("cannot tell those apart", rows["why"])

    def test_several_missing_slots_is_a_page_this_cannot_read(self):
        thin = V2.replace('<a href="/cards/OP01/120?v=3">Prize Cards serial</a>',
                          "Prize Cards serial")
        rows = print_table_rows(thin)
        self.assertIsNone(rows["unlinked_slot"])
        self.assertIn("expected exactly one", rows["why"])

    def test_the_image_filename_places_the_page(self):
        self.assertEqual(observed_slot(V2)["slot"], 2)
        self.assertIn("image_filename", observed_slot(V2)["voted_by"])

    def test_a_canonical_url_is_read_when_present(self):
        with_canonical = V4.replace(
            "<title>", '<link rel="canonical" href="/cards/OP01/120?v=4">\n<title>')
        self.assertEqual(canonical_slot(with_canonical)["slot"], 4)
        self.assertIn("canonical_url", observed_slot(with_canonical)["voted_by"])

    def test_an_absent_canonical_is_reported_absent_not_assumed(self):
        self.assertIsNone(canonical_slot(V2)["slot"])
        self.assertIn("no canonical URL", canonical_slot(V2)["why"])

    def test_disagreeing_signals_produce_no_answer_at_all(self):
        """Two signals speaking and disagreeing is not a vote to break. A page
        that cannot say which printing it is must not be recorded as any."""
        lying = V2.replace("_p2_EN.webp", "_p4_EN.webp")
        found = observed_slot(lying)
        self.assertIsNone(found["slot"])
        self.assertFalse(found["agreed"])
        self.assertIn("signals disagree", found["why"])

    def test_the_base_page_is_identified_as_base_not_as_slot_one(self):
        found = observed_slot(BASE)
        self.assertTrue(found["is_base"])
        self.assertIsNone(found["slot"])


class RequestedMustEqualObserved(unittest.TestCase):
    """A request for ?v=3 came back as the ?v=2 page. Redirect upstream or
    de-duping in the fetch path -- indistinguishable from outside, and it does
    not matter: compare and refuse either way."""

    def test_the_observed_redirect_is_refused(self):
        check = verify_slot(V2, 3)
        self.assertFalse(check["ok"])
        self.assertEqual(check["observed"], 2)
        self.assertIn("requested v=3", check["why"])

    def test_a_matching_page_passes_and_names_its_witnesses(self):
        check = verify_slot(V2, 2)
        self.assertTrue(check["ok"])
        self.assertIn("image_filename", check["confirmed_by"])

    def test_the_base_fetch_is_verified_too(self):
        self.assertTrue(verify_slot(BASE, None)["ok"])
        self.assertFalse(verify_slot(V2, None)["ok"])

    def test_a_page_that_cannot_place_itself_is_refused_not_trusted(self):
        """No image, no print table, no canonical: nothing on the page says
        which printing it is, so it is refused rather than credited to the
        slot that was asked for."""
        mute = ('<title>Shanks (OP01-120) &bull; Romance Dawn</title>'
                '<a href="/cards/op01-romance-dawn">Romance Dawn (OP01) '
                'Manga Art</a>')
        check = verify_slot(mute, 2)
        self.assertFalse(check["ok"])
        self.assertIn("does not identify its printing", check["why"])

    def test_a_page_answering_as_the_base_is_refused_for_a_variant(self):
        """The other half of the same guard: the bare page answering a `?v=`
        request is as wrong as a neighbouring variant answering it."""
        check = verify_slot(BASE, 2)
        self.assertFalse(check["ok"])
        self.assertIn("describes v=base", check["why"])

    def test_a_mismatched_follow_up_leaves_the_entry_unresolved(self):
        """The whole point: the wrong page answering must not credit its
        product to the slot that was asked for."""
        pages = _Pages({("OP01", "OP01-120", None): BASE,
                        ("OP01", "OP01-120", 3): V2})   # v=3 answers with v=2
        _, entries, failures, _ = attest(pages, [("OP01", "OP01-120")])
        slot3 = [e for e in entries if e["slot"] == 3][0]
        self.assertIsNone(slot3["product_set_code"])
        self.assertEqual(slot3["slot_mismatch"],
                         {"requested": 3, "observed": 2})
        self.assertIn("not it", slot3["unresolved"])
        self.assertTrue(any(f.get("observed") == 2 for f in failures))

    def test_a_matching_follow_up_does_resolve_the_entry(self):
        pages = _Pages({("OP01", "OP01-120", None): BASE,
                        ("OP01", "OP01-120", 3): V2.replace(
                            "_p2_EN.webp", "_p3_EN.webp").replace(
                            '<a href="/cards/OP01/120?v=3">Prize Cards serial</a>',
                            "Prize Cards serial").replace(
                            "Romance Dawn manga",
                            '<a href="/cards/OP01/120?v=2">Romance Dawn manga</a>')})
        _, entries, _, _ = attest(pages, [("OP01", "OP01-120")])
        slot3 = [e for e in entries if e["slot"] == 3][0]
        self.assertEqual(slot3["product_set_code"], "op01")
        self.assertEqual(slot3["source"], "limitless_variant_page")

    def test_only_unresolved_slots_are_followed_up(self):
        """Slots 1 and 2 are labelled `Romance Dawn`, which the base page's
        own slug already attests, so they are never refetched. Slots 3 and 4
        name products no slug has attested, so they are."""
        pages = _Pages({("OP01", "OP01-120", None): BASE,
                        ("OP01", "OP01-120", 3): V2})
        attest(pages, [("OP01", "OP01-120")])
        followups = sorted(c[2] for c in pages.calls if c[2] is not None)
        self.assertEqual(followups, [3, 4])


class TheSlotBindingIsReconfirmedNotAssumed(unittest.TestCase):
    """`?v=N` <-> `_pN` was confirmed at n=1: one pairing (v=2/_p2) plus
    base/no-suffix. One pairing is one observation of the mapping."""

    def test_a_matching_asset_confirms(self):
        found = slot_binding_evidence(V2, 2)
        self.assertEqual(found["status"], "confirms")
        self.assertEqual(found["filename"], "OP01-120_p2_EN.webp")

    def test_base_with_no_suffix_confirms(self):
        self.assertEqual(slot_binding_evidence(BASE, None)["status"], "confirms")

    def test_a_mismatch_is_evidence_about_the_mapping_not_the_card(self):
        found = slot_binding_evidence(V2, 3)
        self.assertEqual(found["status"], "contradicts")
        self.assertIn("about the ?v=N <-> _pN mapping", found["why"])
        self.assertIn("not about this card", found["why"])

    def test_a_page_with_no_image_yields_no_evidence_either_way(self):
        self.assertEqual(slot_binding_evidence("<p>x</p>", 2)["status"],
                         "no_evidence")

    def test_the_report_counts_confirmations_rather_than_asserting_the_rule(self):
        report = render_binding_report([
            {"status": "confirms", "number": "OP01-120", "requested": 2},
            {"status": "contradicts", "number": "OP05-119", "requested": 3,
             "filename": "OP05-119_p1_EN.webp"}])
        self.assertIn("re-confirmed per card", report)
        self.assertIn("1 confirm, 1 contradict", report)
        self.assertIn("about the MAPPING", report)
        self.assertIn("OP05-119", report)


class TheAnchorNestingIsNotObserved(unittest.TestCase):
    """The page shape that reached this parser was web_fetch's RENDERED
    markdown, not Limitless's raw HTML. Slug structure and image filenames are
    real; the anchor nesting is not. So both serialisations must parse, and
    nothing may depend on which one arrived."""

    def test_markdown_and_html_produce_the_same_reading(self):
        markdown = (
            "Shanks (OP01-120)\n"
            "![](https://x/OP01-120_p2_EN.webp)\n"
            "[Romance Dawn (OP01) Manga Art](/cards/op01-romance-dawn)\n"
            "This variant has been reprinted in: One Piece The Best (PRB01)\n"
            "[Romance Dawn](/cards/OP01/120)\n"
            "[Romance Dawn aa](/cards/OP01/120?v=1)\n"
            "Romance Dawn manga\n"
            "[Prize Cards serial](/cards/OP01/120?v=3)\n"
            "[One Piece The Best aa](/cards/OP01/120?v=4)\n")
        self.assertEqual(product_line(markdown)["set_code"], "op01")
        self.assertEqual(product_line(markdown)["treatment"], "Manga Art")
        self.assertEqual(print_table_rows(markdown)["unlinked_slot"], 2)
        self.assertEqual(observed_slot(markdown)["slot"], 2)
        self.assertTrue(verify_slot(markdown, 2)["ok"])
        self.assertFalse(verify_slot(markdown, 3)["ok"])

    def test_a_comment_carrying_a_variant_link_does_not_enter_the_table(self):
        """A comment is not content, and one containing a `?v=` shifts every
        signal read off the print table."""
        noisy = V2.replace("<title>", "<!-- see ?v=7 -->\n<title>")
        self.assertEqual(print_table_rows(noisy)["unlinked_slot"], 2)
        self.assertEqual([r["slot"] for r in print_table(noisy)], [1, 3, 4])
