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
                              build_product_index, image_slot,
                              parse_variant_page, print_table, product_line,
                              product_attestation, reconcile, reprint_note,
                              render_attestation_report, split_label)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "limitless")


def page(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


BASE = page("op01-120_base.html")
V2 = page("op01-120_v2.html")
V4 = page("op01-120_v4.html")
SILENT = page("no_product.html")


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

    def test_the_print_table_is_a_complete_manifest(self):
        self.assertEqual(print_table(V2),
                         [{"slot": 1, "label": "Romance Dawn aa"},
                          {"slot": 2, "label": "Romance Dawn manga"},
                          {"slot": 3, "label": "Prize Cards serial"},
                          {"slot": 4, "label": "One Piece The Best aa"}])

    def test_every_page_carries_the_same_manifest(self):
        self.assertEqual(print_table(BASE), print_table(V2))
        self.assertEqual(print_table(V4), print_table(V2))

    def test_five_printings_not_six(self):
        """op01 base, op01 aa, op01 manga, Prize Cards serial, prb01 aa."""
        self.assertEqual(
            product_attestation(V2, "OP01", "OP01-120")["printing_count"], 5)

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
        entries = reconcile(parse_variant_page(V2), "OP01", "OP01-120",
                            build_product_index([V2, V4]), "https://x")
        prize = [e for e in entries if e["slot"] == 3][0]
        self.assertIsNone(prize["product_set_code"])
        self.assertIn("Refusing to assume", prize["unresolved"])
        manga = [e for e in entries if e["slot"] == 2][0]
        self.assertEqual(manga["product_set_code"], "op01")

    def test_a_resolved_entry_cites_the_page_that_attested_it(self):
        entries = reconcile(parse_variant_page(V2), "OP01", "OP01-120",
                            build_product_index([V2, V4]), "https://x")
        prb = [e for e in entries if e["slot"] == 4][0]
        self.assertEqual(prb["product_set_code"], "prb01")
        self.assertIn("prb01-premium-booster", prb["attested_by"])

    def test_ground_truth_keeps_the_semantic_token(self):
        entries = reconcile(parse_variant_page(V2), "OP01", "OP01-120",
                            build_product_index([V2]), "https://x")
        for entry in entries:
            self.assertNotEqual(entry["label"], str(entry["slot"]))
            self.assertTrue(entry["label"][0].isalpha())


class _Pages:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def card_page(self, set_code, number):
        self.calls.append((set_code, number))
        if (set_code, number) not in self.pages:
            raise AdapterGaveUp(f"no candidate URL answered for {number}")
        return f"https://limitless/{number}", self.pages[(set_code, number)]


class Attesting(unittest.TestCase):

    def test_one_call_per_card(self):
        pages = _Pages({("OP01", "OP01-120"): V2, ("OP05", "OP05-119"): V4})
        attest(pages, [("OP01", "OP01-120"), ("OP05", "OP05-119")])
        self.assertEqual(pages.calls,
                         [("OP01", "OP01-120"), ("OP05", "OP05-119")])

    def test_the_index_spans_every_page_before_any_label_resolves(self):
        """prb01 is named only on OP05's page here, and it still resolves
        OP01-120's slot 4."""
        pages = _Pages({("OP01", "OP01-120"): V2, ("OP05", "OP05-119"): V4})
        _, entries, _ = attest(pages, [("OP01", "OP01-120"),
                                       ("OP05", "OP05-119")])
        slot4 = [e for e in entries
                 if e["number"] == "OP01-120" and e["slot"] == 4][0]
        self.assertEqual(slot4["product_set_code"], "prb01")

    def test_a_page_that_links_no_product_is_a_failure_not_an_attestation(self):
        pages = _Pages({("OP01", "OP01-120"): SILENT})
        attestations, entries, failures = attest(pages, [("OP01", "OP01-120")])
        self.assertFalse(attestations[0]["attested"])
        self.assertEqual(entries, [])
        self.assertIn("first parenthesised token is the card number",
                      failures[0]["why"])

    def test_an_unreachable_card_is_a_gap_not_an_absent_printing(self):
        attestations, entries, failures = attest(_Pages({}),
                                                 [("OP01", "OP01-120")])
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
        entries = reconcile(parse_variant_page(V2), "OP01", "OP01-120",
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
