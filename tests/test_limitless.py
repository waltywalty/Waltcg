"""The Limitless variant-page parser, and its refusal.

Fetching cannot happen here -- the egress proxy answers 403 to CONNECT for
limitlesstcg.com, so the measurement is runner work. The parsing is not, and
the part worth guarding is not extraction but ABSTENTION: a page that does not
name a product must come back saying so, because the only reason this adapter
exists is that the cheaper source (a marketplace listing) answers confidently
and wrongly. An adapter that guesses when the page is silent is that source
with a better hostname.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.base import AdapterGaveUp  # noqa: E402
from ingest.limitless import (LimitlessAdapter, attest,  # noqa: E402
                              parse_variant_page, product_attestation,
                              render_attestation_report)

BASE_PAGE = """<html><head>
<title>Monkey.D.Luffy (OP01-120) &middot; Romance Dawn (OP01)</title>
</head><body>
<h1>Monkey.D.Luffy &mdash; Romance Dawn (OP01)</h1>
<p>Also reprinted in: One Piece The Best (PRB01)</p>
<div class="variants">
  <a href="/cards/OP01/120?v=1">Alternate Art</a>
  <a href="/cards/OP01/120?v=4">Manga</a>
</div>
</body></html>"""

REPRINT_PAGE = """<html><head>
<title>Monkey.D.Luffy (OP01-120) &middot; One Piece The Best (PRB01)</title>
</head><body>
<h1>Monkey.D.Luffy &mdash; One Piece The Best (PRB01)</h1>
</body></html>"""

SILENT_PAGE = """<html><head><title>Monkey.D.Luffy</title></head>
<body><h1>Monkey.D.Luffy</h1><p>Manga Rare</p></body></html>"""


class ThePageIsReadForWhatItSays(unittest.TestCase):

    def test_the_product_comes_off_the_title(self):
        parsed = parse_variant_page(BASE_PAGE)
        self.assertEqual(parsed["product_code"], "OP01")
        self.assertIn("Romance Dawn", parsed["product_title"])

    def test_the_reprint_relationship_is_read_separately(self):
        """The base page states where the card was reprinted. That is a
        different claim from what product THIS page is -- conflating them is
        how a base printing acquires its reprint's product code."""
        parsed = parse_variant_page(BASE_PAGE)
        self.assertEqual(parsed["product_code"], "OP01")
        self.assertEqual(parsed["reprinted_in_code"], "PRB01")

    def test_a_variant_page_names_its_own_product(self):
        """The whole reason this source class discriminates."""
        parsed = parse_variant_page(REPRINT_PAGE)
        self.assertEqual(parsed["product_code"], "PRB01")

    def test_variant_slots_keep_their_semantic_labels(self):
        parsed = parse_variant_page(BASE_PAGE)
        self.assertEqual(parsed["variants"],
                         [{"slot": 1, "label": "Alternate Art"},
                          {"slot": 4, "label": "Manga"}])

    def test_entities_are_unescaped(self):
        self.assertIn("·", parse_variant_page(BASE_PAGE)["product_title"])


class SilenceIsReportedAsSilence(unittest.TestCase):

    def test_every_field_is_none_when_the_page_does_not_say_it(self):
        parsed = parse_variant_page(SILENT_PAGE)
        self.assertIsNone(parsed["product_code"])
        self.assertIsNone(parsed["reprinted_in"])
        self.assertIsNone(parsed["reprinted_in_code"])
        self.assertEqual(parsed["variants"], [])

    def test_an_empty_page_does_not_raise_and_attests_nothing(self):
        parsed = parse_variant_page("")
        self.assertIsNone(parsed["product_code"])
        self.assertIsNone(parsed["product_title"])

    def test_attestation_says_not_attested_rather_than_guessing(self):
        claim = product_attestation(SILENT_PAGE, "OP01", "OP01-120")
        self.assertFalse(claim["attested"])
        self.assertIsNone(claim["product_code"])
        self.assertIsNone(claim["corroboration_tier"])

    def test_an_attested_page_carries_the_full_tier(self):
        claim = product_attestation(REPRINT_PAGE, "OP01", "OP01-120")
        self.assertTrue(claim["attested"])
        self.assertEqual(claim["corroboration_tier"], "full")
        self.assertEqual(claim["product_code"], "PRB01")


class _Pages:
    """An adapter stand-in. `attest` takes any object with `card_page`."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def card_page(self, set_code, number, variant=None):
        self.asked.append((set_code, number, variant))
        key = (set_code, number, variant)
        if key not in self.pages:
            raise AdapterGaveUp(f"no candidate URL answered for {number}")
        return f"https://limitless/{number}" + (f"?v={variant}" if variant
                                                else ""), self.pages[key]


class TheReconciliationRefuses(unittest.TestCase):

    def test_a_slot_whose_page_names_a_product_becomes_an_entry(self):
        pages = _Pages({("OP01", "OP01-120", None): BASE_PAGE,
                        ("OP01", "OP01-120", 1): BASE_PAGE,
                        ("OP01", "OP01-120", 4): REPRINT_PAGE})
        _, entries, failures = attest(pages, [("OP01", "OP01-120")])
        manga = [e for e in entries if e["slot"] == 4]
        self.assertEqual(len(manga), 1)
        self.assertEqual(manga[0]["product_code"], "PRB01")
        self.assertEqual(manga[0]["treatment"], "Manga")
        self.assertEqual(manga[0]["source"], "limitless_variant_page")
        self.assertIn("v=4", manga[0]["url"])
        self.assertEqual(failures, [])

    def test_a_silent_slot_writes_no_entry_and_says_why(self):
        """Ordering the slots and assuming the first is the base is exactly
        the inference that put OP01-120 in the wrong product."""
        pages = _Pages({("OP01", "OP01-120", None): BASE_PAGE,
                        ("OP01", "OP01-120", 1): SILENT_PAGE,
                        ("OP01", "OP01-120", 4): SILENT_PAGE})
        _, entries, failures = attest(pages, [("OP01", "OP01-120")])
        self.assertEqual(entries, [])
        self.assertEqual(len(failures), 2)
        for failure in failures:
            self.assertIn("refusing to infer", failure["why"])
            self.assertIn(failure["slot"], (1, 4))

    def test_an_unreachable_card_is_a_gap_not_an_absent_variant(self):
        """Zero variants because the page 404'd and zero variants because the
        card has none are different findings and must not render the same."""
        pages = _Pages({})
        attestations, entries, failures = attest(pages, [("OP01", "OP01-120")])
        self.assertEqual(attestations, [])
        self.assertEqual(entries, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("no candidate URL answered", failures[0]["why"])

    def test_the_treatment_stays_semantic_not_positional(self):
        """Ground truth keeps `manga_rare`. If the entry recorded the slot as
        the treatment, the identity scheme would be catalog-derived."""
        pages = _Pages({("OP01", "OP01-120", None): BASE_PAGE,
                        ("OP01", "OP01-120", 4): REPRINT_PAGE,
                        ("OP01", "OP01-120", 1): REPRINT_PAGE})
        _, entries, _ = attest(pages, [("OP01", "OP01-120")])
        for entry in entries:
            self.assertNotEqual(entry["treatment"], str(entry["slot"]))
            self.assertTrue(entry["treatment"][0].isalpha())


class TheUrlShapeIsProbed(unittest.TestCase):

    def _adapter(self, answers):
        tried = []

        def transport(url, headers):
            tried.append(url)
            status, body = answers(url)
            return status, body.encode("utf-8"), {}

        adapter = LimitlessAdapter(raw_root=self.raw, sleep=lambda _s: None,
                                   transport=transport, monotonic=lambda: 0.0)
        return adapter, tried

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_the_second_candidate_answers_and_is_recorded(self):
        """Which URL worked is the fact that turns a zero into a diagnosis."""
        def answers(url):
            if url.startswith("https://onepiece."):
                return 404, "nope"
            return 200, BASE_PAGE

        adapter, tried = self._adapter(answers)
        url, page = adapter.card_page("OP01", "OP01-120")
        self.assertTrue(url.startswith("https://limitlesstcg.com/"))
        self.assertEqual(adapter.endpoints_used["OP01-OP01-120"], url)
        self.assertGreaterEqual(len(tried), 2)
        self.assertEqual(parse_variant_page(page)["product_code"], "OP01")

    def test_the_leading_zeros_are_stripped_for_the_index_shape(self):
        adapter, tried = self._adapter(lambda url: (200, BASE_PAGE))
        adapter.card_page("OP01", "OP01-070")
        self.assertIn("/OP01/70", tried[0])

    def test_giving_up_names_every_url_it_tried(self):
        adapter, tried = self._adapter(lambda url: (404, "nope"))
        with self.assertRaises(AdapterGaveUp) as caught:
            adapter.card_page("OP01", "OP01-120")
        message = str(caught.exception)
        for url in tried:
            self.assertIn(url, message)

    def test_the_variant_suffix_is_carried_onto_the_candidate(self):
        adapter, tried = self._adapter(lambda url: (200, REPRINT_PAGE))
        adapter.card_page("OP01", "OP01-120", variant=4)
        self.assertTrue(tried[0].endswith("?v=4"))


class TheReportDistinguishesTheThreeOutcomes(unittest.TestCase):

    def test_a_refusal_is_rendered_as_a_refusal(self):
        report = render_attestation_report(
            [], [], [{"number": "OP01-120", "slot": 4,
                      "why": "page names no product; refusing to infer one "
                             "from slot order"}])
        self.assertIn("Not attested", report)
        self.assertIn("v=4", report)
        self.assertIn("REFUSES", report)

    def test_nothing_fetched_is_stated_not_rendered_as_success(self):
        self.assertIn("Nothing was fetched",
                      render_attestation_report([], [], []))

    def test_an_unattested_product_renders_as_a_dash_not_a_blank(self):
        report = render_attestation_report(
            [{"number": "OP01-120", "product_code": None,
              "reprinted_in_code": None, "url": "https://limitless/x"}], [], [])
        self.assertIn("| `OP01-120` | -- | -- |", report)


if __name__ == "__main__":
    unittest.main()
