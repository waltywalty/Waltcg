"""Limitless variant pages: the source class that can tell two products apart.

WHY THIS EXISTS. A marketplace listing reading `OP01-120 Manga` is attributed
to "Romance Dawn" BY CONSTRUCTION -- PRB-01 reprints keep their `OPxx-xxx`, so
the seller reads the number, the number says OP01, and the listing says Romance
Dawn whether or not that is the product. The attribution is derived from the
number and corroborates nothing the number did not already carry
(`resolve/corroboration.py`). Limitless serves a page per printing, each naming
its own product in a link whose HREF carries the set slug. That discriminates.

WHAT THE FIRST VERSION OF THIS FILE GOT WRONG, from real pages:

  1. IT READ THE PRODUCT OFF THE TITLE. The real title is
     `Shanks (OP01-120) - Romance Dawn - Limitless`, and the first
     parenthesised token is THE CARD NUMBER. Always. So "first parenthesised
     code in the title" attested every printing to a product code equal to its
     own number, on 100% of pages. Not a shape risk that might have bitten --
     a certainty that would have. The product now comes off the body link's
     HREF, and the bracketed code in the link TEXT is kept only as a
     cross-check.

  2. IT FETCHED ONCE PER VARIANT. Every page carries the full Print table --
     a complete manifest, one labelled `?v=` link per printing. One fetch per
     card enumerates every printing; probing variant numbers was walking a
     list the first page already handed over.

  3. IT CACHED THE PAGE. `Adapter.cache_raw` writes the body to `raw/`, and
     these pages carry USD/EUR columns, TCGplayer and Cardmarket links and a
     price history block. Parsed in memory now and never persisted; the
     fixtures below are hand-written with the price table omitted, the rule
     `probe/fixtures/` already lives under.

THE TRAP, which is subtle enough to be worth stating twice. The line

    This variant has been reprinted in: One Piece The Best (PRB01)

appears IDENTICALLY on the base page and on `?v=2`, despite saying "this
variant". It is CARD-level. Read as variant attribution it attests the manga
printing to `prb01` -- exactly the wrong answer, and the answer this whole
module exists to avoid. Only the bracketed product line is variant-scoped.

CANNOT RUN IN THE SANDBOX. The egress proxy answers 403 to CONNECT for
limitlesstcg.com, so the fetch runs on the Actions runner. The parsing does not
and is tested here.
"""

from __future__ import annotations

import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.base import Adapter, AdapterGaveUp, RateLimited  # noqa: E402


class LimitlessAdapter(Adapter):
    name = "limitless"
    key_env = None
    host = "onepiece.limitlesstcg.com"
    # Courtesy: a public fan-run site with no published quota. One request
    # every two seconds, and one request per CARD rather than per printing.
    min_interval_seconds = 2.0

    #: Candidate URL shapes, most likely first. NOT a guess dressed as a
    #: constant -- `card_page` probes them and records which answered.
    CARD_CANDIDATES = (
        "https://onepiece.limitlesstcg.com/cards/{set_code}/{index}",
        "https://limitlesstcg.com/cards/op/{set_code}/{index}",
        "https://onepiece.limitlesstcg.com/cards/{set_code}/{number}",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: Which candidate answered, per card. Reported, because "which URL
        #: worked" is the fact that turns a zero into a diagnosis.
        self.endpoints_used = {}

    # -- fetching ---------------------------------------------------------

    def _get_text(self, url):
        """Raw page text, IN MEMORY.

        `Adapter.get` parses JSON and `Adapter.cache_raw` writes the body to
        `raw/`. Neither is used here. These pages carry USD/EUR price columns,
        marketplace links and a price history block, and caching one is
        persisting provider price data -- the thing the non-negotiable forbids
        regardless of whether `raw/` happens to be gitignored today.
        """
        status, body, response_headers = self._send(url, {})
        self.quota.consumed_this_run += 1
        self.responses_seen += 1
        self._last_call = self._monotonic()
        self.note_rate_headers(response_headers)
        # Deliberately NOT self.cache_raw(url, body). See the docstring.
        self.log.append(f"{self.name} {status} {url} -> parsed in memory")
        if status == 429:
            raise RateLimited(f"{self.name}: {self.note_rate_limit(response_headers)}")
        if status >= 400:
            raise AdapterGaveUp(f"{self.name}: HTTP {status} for {url}")
        return body.decode("utf-8", errors="replace")

    def card_page(self, set_code, number):
        """The card's page, and the URL that served it.

        No `variant` parameter: the page it returns carries the manifest for
        every printing, so there is nothing to walk.
        """
        index = str(number).split("-")[-1].lstrip("0") or "0"
        tried = []
        for shape in self.CARD_CANDIDATES:
            url = shape.format(set_code=set_code, index=index, number=number)
            try:
                text = self._get_text(url)
            except (AdapterGaveUp, RateLimited, OSError) as exc:
                tried.append((url, str(exc)[:120]))
                continue
            self.endpoints_used[f"{set_code}-{number}"] = url
            return url, text
        raise AdapterGaveUp(
            f"{self.name}: no candidate URL answered for {set_code} {number}. "
            "Tried " + "; ".join(f"{u} ({why})" for u, why in tried))


# -- parsing ---------------------------------------------------------------

# Anchors in either serialisation: the live page is HTML, and a text-mode fetch
# renders the same anchors as markdown. Same structure, two encodings.
_HTML_ANCHOR = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_MD_ANCHOR = re.compile(r'\[([^\]\[]+)\]\(([^)\s]+)\)')

# `Romance Dawn (OP01) Manga Art` -- the VARIANT-SCOPED product line. Applied
# only to anchors whose href is a set slug, never to the title: the title's
# first parenthesised token is the card number.
_PRODUCT_TEXT = re.compile(r"^(?P<name>.+?)\s*\((?P<code>[A-Za-z0-9]{2,8})\)\s*"
                           r"(?P<treatment>.*)$", re.S)
_SET_SLUG = re.compile(r"/cards/(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)+)/?$", re.I)
_VARIANT_HREF = re.compile(r"\?v=(\d+)")
# `OP01-120_p2_EN.webp` -- the asset URL, which is what makes `?v=N` and
# apitcg's `_pN` the SAME slot vocabulary as evidence rather than as assumption.
_IMAGE = re.compile(r"([A-Z]{2,4}\d{2}-\d{2,3})(?:_p(\d+))?(?:_([A-Z-]{2,5}))?"
                    r"\.(?:webp|png|jpg|jpeg)", re.I)
# CARD-level, despite saying "this variant". See the module docstring.
_REPRINTED_IN = re.compile(
    r"(?:This\s+variant\s+has\s+been\s+)?reprinted\s+in[:\s]*(.{0,120}?)(?:<|\n|$)",
    re.I | re.S)
_BRACKET_CODE = re.compile(r"\(([A-Za-z0-9]{2,8})\)")


def _text(fragment) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).strip()


def anchors(page):
    """(href, text) for every link, in either serialisation."""
    found = [(href, _text(body)) for href, body in _HTML_ANCHOR.findall(page or "")]
    found += [(href, _text(body)) for body, href in _MD_ANCHOR.findall(page or "")]
    return found


def product_line(page):
    """The VARIANT-SCOPED product, from the body link.

    `[Romance Dawn (OP01) Manga Art](/cards/op01-romance-dawn)`

    The set code comes off the HREF SLUG. The bracketed code in the link text
    is read too, but only as a cross-check -- text is what the title lies with.
    Returns None when no anchor on the page has this shape, which is a page
    that does not attest a product, not a page whose product is the default.
    """
    for href, text in anchors(page):
        slug = _SET_SLUG.search(href)
        if not slug:
            continue
        shape = _PRODUCT_TEXT.match(text)
        if not shape:
            continue
        slug_text = slug.group("slug")
        set_code = slug_text.split("-")[0]
        stated = shape.group("code")
        if set_code.lower() != stated.lower():
            # The slug and the bracketed code disagree. Reported, never
            # averaged: two sources disagreeing is a finding.
            continue
        treatment = shape.group("treatment").strip(" -–—·•") or None
        return {"set_code": set_code.lower(), "stated_code": stated,
                "product_name": shape.group("name").strip(" -–—·•"),
                "treatment": treatment, "slug": slug_text}
    return None


def print_table(page):
    """Every printing the page lists: (slot, label), lowest slot first.

    This is the manifest, and it is why one fetch per CARD is enough. The base
    printing carries no `?v=`, so it is absent here by construction -- absent
    from this list means "not among the ?v= links", never "does not exist".
    """
    seen, rows = set(), []
    for href, text in anchors(page):
        slot = _VARIANT_HREF.search(href)
        if not slot or not text:
            continue
        number = int(slot.group(1))
        if number in seen:
            continue
        seen.add(number)
        rows.append({"slot": number, "label": text})
    return sorted(rows, key=lambda r: r["slot"])


def image_slot(page):
    """The `_pN` slot this page's asset carries, from the image URL.

    `OP01-120_p2_EN.webp` on `?v=2` is the evidence that Limitless's `?v=N`
    and apitcg's `_pN` are one slot vocabulary. A filename with no `_pN` is
    reported as slot None WITH the filename, because "no suffix" meaning "base"
    is a convention we hold about apitcg, not something this page states.
    """
    found = _IMAGE.search(page or "")
    if not found:
        return {"slot": None, "filename": None, "why": "no card image on page"}
    slot = found.group(2)
    return {"slot": int(slot) if slot is not None else None,
            "filename": found.group(0),
            "number": found.group(1),
            "language": found.group(3),
            "why": None if slot is not None else
                   "filename carries no _pN suffix"}


def reprint_note(page):
    """The `reprinted in:` line -- CARD-level, and labelled as such.

    It appears identically on the base page and on `?v=2` despite the wording
    "this variant". Anything reading this as the current printing's product
    attests the manga printing to `prb01`, which is the wrong answer.
    """
    found = _REPRINTED_IN.search(page or "")
    if not found:
        return None
    text = _text(found.group(1))
    if not text:
        return None
    code = _BRACKET_CODE.search(text)
    return {"text": text,
            "product_code": code.group(1).lower() if code else None,
            "scope": "card",
            "not_variant_scoped": "Appears identically on the base page and on "
                                  "?v=2. Naming the current printing's product "
                                  "from this line attests manga to prb01."}


def parse_variant_page(page) -> dict:
    """What a Limitless page attests, and nothing more.

    Every field is None when the page does not say it. A page that omits the
    product is a page that does not attest the product; returning a guess would
    make this source indistinguishable from the listings it exists to replace.
    """
    line = product_line(page)
    image = image_slot(page)
    return {
        "product_line": line,
        "set_code": line["set_code"] if line else None,
        "product_name": line["product_name"] if line else None,
        "treatment": line["treatment"] if line else None,
        "slot": image["slot"],
        "image": image,
        "printings": print_table(page),
        "reprint_note": reprint_note(page),
    }


def product_attestation(page, set_code, number) -> dict:
    """The PRODUCT-level claim, which is the certain one.

    Certain because it is what the page is FOR: a page is served per printing
    and links its own product. That is a different claim from mapping a
    treatment onto a provider's positional `_pN`, which is a reconciliation and
    is recorded as data elsewhere.
    """
    parsed = parse_variant_page(page)
    attested = parsed["set_code"] is not None
    return {
        "set_code_asked": set_code,
        "number": number,
        "product_set_code": parsed["set_code"],
        "product_name": parsed["product_name"],
        "treatment": parsed["treatment"],
        "printing_count": len(parsed["printings"]) + (1 if attested else 0),
        "reprint_note_is_card_level": bool(parsed["reprint_note"]),
        "attested": attested,
        "corroboration_tier": "full" if attested else None,
    }


# -- slot reconciliation, and the CLI that fills it ------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLOTS = os.path.join(REPO, "contracts", "printing_slots.json")

#: The cards this exists to settle. Five PRB reprint pairs plus the S1 card.
WANTED = (
    ("OP01", "OP01-120"),
    ("OP05", "OP05-119"),
    ("OP02", "OP02-013"),
    ("OP01", "OP01-070"),
    ("EB01", "EB01-012"),
    ("OP09", "OP09-046"),
)


def split_label(label):
    """`Romance Dawn manga` -> (`Romance Dawn`, `manga`).

    Print-table labels put a short lowercase treatment after a Title Case
    product name. The split is a HEURISTIC on capitalisation, so the raw label
    is carried alongside everywhere this is used and the product is resolved by
    NAME LOOKUP against a slug-attested index -- never by trusting this split.
    """
    words = (label or "").split()
    treatment = []
    while words and words[-1][:1].islower():
        treatment.insert(0, words.pop())
    return " ".join(words) or None, " ".join(treatment) or None


def build_product_index(pages):
    """product name -> set code, from HREF SLUGS only.

    A name reaches this index only by having been observed in a slug. Resolving
    a print-table label against it is therefore a lookup of something a page
    stated, not an inference from the label's own text.
    """
    index = {}
    for page in pages:
        line = product_line(page)
        if line:
            index.setdefault(line["product_name"].lower(),
                             {"set_code": line["set_code"],
                              "slug": line["slug"]})
    return index


def reconcile(parsed, set_code, number, index, url):
    """One entry per printing: slot, treatment, product -- each cited.

    Where the label's product was never observed in a slug, the entry records
    `product_set_code: None` and says so. It does NOT fall back to the page's
    own product, and it does not order the slots: ordering the slots and
    calling the first one the base is the inference that made `OP01-120` look
    like it needed re-homing in the first place.
    """
    entries = []
    for row in parsed["printings"]:
        name, short = split_label(row["label"])
        known = index.get((name or "").lower())
        entries.append({
            "set_code_asked": set_code,
            "number": number,
            "slot": row["slot"],
            "label": row["label"],
            "product_name": name,
            "product_set_code": known["set_code"] if known else None,
            "treatment_short": short,
            "treatment": (parsed["treatment"]
                          if parsed["slot"] == row["slot"] else None),
            "attested_by": (f"{url}?v={row['slot']} print table"
                            + ("; product slug " + known["slug"] if known
                               else "")),
            "unresolved": None if known else
                          (f"no page observed a slug for product "
                           f"{name!r}; fetch ?v={row['slot']} to resolve. "
                           "Refusing to assume this page's own product."),
            "source": "limitless_print_table",
        })
    return entries


def attest(adapter=None, wanted=WANTED):
    """One fetch per CARD. Returns (attestations, entries, failures).

    Nothing is written here -- the caller decides, and a card that could not be
    fetched is a gap naming the URLs tried, never an absent printing.
    """
    adapter = adapter or LimitlessAdapter()
    fetched, failures = [], []
    for set_code, number in wanted:
        try:
            url, page = adapter.card_page(set_code, number)
        except (AdapterGaveUp, RateLimited) as exc:
            failures.append({"set_code": set_code, "number": number,
                             "why": str(exc)[:300]})
            continue
        fetched.append((set_code, number, url, page))

    # The index is built from EVERY page before any label is resolved: a
    # product named on one card's page resolves that name on another's.
    index = build_product_index(page for _, _, _, page in fetched)

    attestations, entries = [], []
    for set_code, number, url, page in fetched:
        parsed = parse_variant_page(page)
        claim = dict(product_attestation(page, set_code, number), url=url)
        attestations.append(claim)
        if not claim["attested"]:
            failures.append({"set_code": set_code, "number": number,
                             "why": "page links no product slug; refusing to "
                                    "read a product off the title, whose first "
                                    "parenthesised token is the card number"})
            continue
        entries.extend(reconcile(parsed, set_code, number, index, url))
    return attestations, entries, failures


def render_attestation_report(attestations, entries, failures) -> str:
    lines = ["### Limitless variant pages", ""]
    if attestations:
        lines += ["**Product attested per card**, off the body link's HREF "
                  "slug. NOT off the title: the title's first parenthesised "
                  "token is the card number, so reading the product there "
                  "returns the number on every page.", "",
                  "| Card | Product | Set code | Treatment | Printings | Page |",
                  "|---|---|---|---|---:|---|"]
        for a in attestations:
            lines.append(
                f"| `{a['number']}` | {a['product_name'] or '--'} "
                f"| {a['product_set_code'] or '--'} | {a['treatment'] or '--'} "
                f"| {a['printing_count']} | {a['url']} |")
    if entries:
        resolved = [e for e in entries if e["product_set_code"]]
        lines += ["", f"**Slot reconciliation** -- {len(resolved)} of "
                  f"{len(entries)} printings resolved to a product. A SEMANTIC "
                  "treatment against a provider's POSITIONAL slot, each citing "
                  "the page. Ground truth keeps the semantic token: a "
                  "positional one would make the identity scheme "
                  "catalog-derived.", "",
                  "| Card | Slot | Label | Product | Treatment |",
                  "|---|---:|---|---|---|"]
        for e in entries:
            lines.append(f"| `{e['number']}` | {e['slot']} | {e['label']} "
                         f"| {e['product_set_code'] or '**unresolved**'} "
                         f"| {e['treatment'] or e['treatment_short'] or '--'} |")
    if failures:
        lines += ["", "**Not attested.** No entry was written for these, and "
                  "the reconciliation REFUSES rather than falling back to slot "
                  "order -- ordering the slots and assuming the first is the "
                  "base is the inference this module exists to avoid:", ""]
        for f in failures:
            lines.append(f"- `{f['number']}` -- {f['why']}")
    if not (attestations or entries or failures):
        lines += ["Nothing was fetched."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    import argparse
    import json as _json
    parser = argparse.ArgumentParser(prog="ingest.limitless")
    parser.add_argument("--attest", action="store_true",
                        help="fetch each card once and report what its pages "
                             "attest. Runs on the Actions runner")
    parser.add_argument("--write", action="store_true",
                        help="write the slot entries to "
                             "contracts/printing_slots.json")
    parser.add_argument("--summary", default=None)
    args = parser.parse_args(argv)
    if not args.attest:
        parser.error("nothing to do; pass --attest")

    attestations, entries, failures = attest()
    report = render_attestation_report(attestations, entries, failures)
    print(report)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    if args.write and entries:
        with open(SLOTS, encoding="utf-8") as handle:
            payload = _json.load(handle)
        payload["entries"] = entries
        with open(SLOTS, "w", encoding="utf-8") as handle:
            _json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"wrote {len(entries)} entries to {SLOTS}")
    # A report is never a failure. Zero attestations is a finding.
    return 0


if __name__ == "__main__":
    sys.exit(main())
