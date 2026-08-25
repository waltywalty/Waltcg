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

AND WHAT THE SECOND VERSION GOT WRONG, from the fetch that followed:

  4. IT TRUSTED THE RESPONSE TO BE THE REQUEST. `?v=3` was requested for
     OP01-120 and the `?v=2` page came back -- image `_p2`, body `Romance Dawn
     (OP01) Manga Art`, `Romance Dawn manga` unlinked. Redirect upstream or
     de-duping in the fetch path: indistinguishable from outside, and it does
     not need distinguishing, because the guard is the same either way.
     `verify_slot` reads the slot OFF THE PAGE and compares. A fetch that
     silently returns a neighbour is how a wrong (slot, product) pair enters
     the table with everything green.

  5. IT STATED A ONE-CARD OBSERVATION AS A MAPPING. `?v=N` <-> `_pN` is
     confirmed for exactly one pairing plus base/no-suffix. n=1 is an
     observation of a mapping, not the mapping, so `slot_binding_evidence`
     re-confirms it per card and a failure is evidence ABOUT THE MAPPING
     rather than about that card.

THE PAGE SHAPE IS STILL NOT FULLY OBSERVED. What reached this parser was
`web_fetch`'s RENDERED MARKDOWN, not Limitless's HTML. The slug structure and
the image filenames are real; the anchor nesting is not. So both
serialisations parse, nothing depends on which arrived, and signal 1 below is
read as a GAP IN A SEQUENCE rather than as "which element lacks an anchor" --
a missing integer is the same in either encoding.

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

    def card_page(self, set_code, number, variant=None):
        """The card's page, and the URL that served it.

        `variant` is for the BOUNDED follow-up only: the base fetch enumerates
        every printing from the print table, and a `?v=` is requested solely
        where that manifest left a product unattested. Walking every variant is
        still refetching a list the first response handed over.

        WHAT COMES BACK IS NOT ASSUMED TO BE WHAT WAS ASKED FOR. A request for
        `?v=3` was observed returning the `?v=2` page -- redirect, or de-duping
        somewhere in the fetch path; indistinguishable from outside, and it does
        not matter which. `verify_slot` compares the slot the page claims
        against the slot requested, and the caller records a mismatch as
        unresolved. A fetch that quietly returns a neighbour is exactly how a
        wrong pair enters the table with every check green.
        """
        index = str(number).split("-")[-1].lstrip("0") or "0"
        suffix = f"?v={variant}" if variant is not None else ""
        tried = []
        for shape in self.CARD_CANDIDATES:
            url = shape.format(set_code=set_code, index=index,
                               number=number) + suffix
            try:
                text = self._get_text(url)
            except (AdapterGaveUp, RateLimited, OSError) as exc:
                tried.append((url, str(exc)[:120]))
                continue
            self.endpoints_used[f"{set_code}-{number}"] = url
            return url, text
        raise AdapterGaveUp(
            f"{self.name}: no candidate URL answered for {set_code} {number}"
            + (f" v={variant}" if variant is not None else "") + ". "
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


_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _text(fragment) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).strip()


def _content(page) -> str:
    """The page with comments removed.

    A comment is not content, and one containing a `?v=` -- a note, a
    commented-out row, a fixture's own declaration -- otherwise lands in the
    print table and shifts every signal read off it.
    """
    return _COMMENT.sub(" ", page or "")


def anchors(page):
    """(href, text) for every link, in either serialisation."""
    body_text = _content(page)
    found = [(href, _text(body)) for href, body in _HTML_ANCHOR.findall(body_text)]
    found += [(href, _text(body)) for body, href in _MD_ANCHOR.findall(body_text)]
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
    found = _IMAGE.search(_content(page))
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
    found = _REPRINTED_IN.search(_content(page))
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


# -- which printing is this page? three signals, compared ------------------

# The page's own canonical URL. Shape NOT observed -- like the anchor nesting,
# this is inferred from ordinary HTML convention, so it stays one of three
# signals and never the only one consulted.
_CANONICAL = re.compile(
    r'<(?:link[^>]+rel="canonical"|meta[^>]+property="og:url")[^>]+'
    r'(?:href|content)="([^"]+)"', re.I)
_ROW_BREAK = re.compile(r"</tr>|</li>|</p>|<br\s*/?>|\n", re.I)


def print_table_rows(page):
    """The print table, and which row is UNLINKED.

    Signal 1, and the only one of the three that assumes nothing about markup
    or filenames. Every row but the current printing carries a `?v=` link to
    go there, so on `?v=2` the links run 1, 3, 4 -- and the GAP names the page.
    On the base page nothing is missing from the run, because base has no `?v=`
    of its own to omit.

    Reading it as a gap rather than by locating unlinked text is deliberate:
    the page shape reaching this parser is rendered markdown in one path and
    raw HTML in another, and a rule about which element lacks an anchor has to
    be right about both. A missing integer is the same in either.

    `unlinked_slot` is None when the run has no gap AND no base row is
    evident, or when more than one is missing -- several missing is a page
    this cannot read, and reading it wrong is worse than not reading it.
    """
    linked = print_table(page)
    if not linked:
        return {"linked": [], "unlinked_slot": None, "unlinked_label": None,
                "why": "no ?v= links on the page; no print table found"}
    slots = sorted(row["slot"] for row in linked)
    missing = [n for n in range(1, max(slots) + 1) if n not in slots]
    label = _unlinked_label(page)
    if not missing:
        # A COMPLETE RUN CANNOT DISCRIMINATE, and this is the case that would
        # have made this signal vote wrong. Links 1..4 with nothing omitted is
        # equally the base page (base has no `?v=` of its own to omit) and the
        # `?v=5` page (nothing after the end is missing from 1..4). Abstaining
        # is the honest answer: a signal that cannot tell two printings apart
        # must not pick one, or it out-votes the signal that can.
        return {"linked": linked, "unlinked_slot": None,
                "unlinked_label": label,
                "why": f"run 1..{max(slots)} is complete, so the current "
                       f"printing is either the base or v={max(slots) + 1}; "
                       "this signal cannot tell those apart"}
    if len(missing) > 1:
        return {"linked": linked, "unlinked_slot": None,
                "unlinked_label": label,
                "why": f"{len(missing)} slots missing from the run "
                       f"({missing}); expected exactly one, the current "
                       "printing"}
    return {"linked": linked, "unlinked_slot": missing[0],
            "unlinked_label": label, "why": None}


def _unlinked_label(page):
    """The current printing's label, when it can be found as plain text.

    Best-effort and NON-VOTING: it names the printing for a human reading the
    report and is never what identifies the slot. Markup-dependent, which is
    exactly why it gets no vote -- the shape reaching this parser is rendered
    markdown in one path and raw HTML in another.
    """
    rows = _ROW_BREAK.split(_content(page))
    linked_at = [i for i, row in enumerate(rows)
                 if re.search(r"\?v=\d+", row)]
    if not linked_at:
        return None
    # One row either side of the linked run: the unlinked row is first on the
    # base page and last on the highest variant's.
    window = rows[max(min(linked_at) - 1, 0):max(linked_at) + 2]
    linked_text = {text for href, text in anchors(page) if "?v=" in href}
    candidates = []
    for row in window:
        if re.search(r"\?v=\d+", row) or "<a" in row.lower() or "](" in row:
            continue
        text = _text(row)
        if text and text not in linked_text and len(text) > 2:
            candidates.append(text)
    return candidates[0] if len(candidates) == 1 else None


def canonical_slot(page):
    """Signal 3: the `?v=` on the page's own canonical URL.

    Absent is reported as absent. This is the weakest of the three because the
    tag's presence is assumed rather than observed.
    """
    found = _CANONICAL.search(_content(page))
    if not found:
        return {"slot": None, "url": None, "why": "no canonical URL on page"}
    url = html.unescape(found.group(1))
    variant = _VARIANT_HREF.search(url)
    return {"slot": int(variant.group(1)) if variant else None, "url": url,
            "why": None if variant else "canonical URL carries no ?v="}


def observed_slot(page):
    """Which printing this page says it is, from three independent signals.

    The signals are compared, never merged. Where two speak and disagree, the
    answer is None WITH the disagreement attached -- a page that cannot say
    which printing it is must not be recorded as any printing.
    """
    image = image_slot(page)
    rows = print_table_rows(page)
    canonical = canonical_slot(page)

    from_label = rows["unlinked_slot"]

    signals = {
        "unlinked_print_row": {"slot": from_label,
                               "label": rows["unlinked_label"],
                               "why": rows["why"]},
        "image_filename": {"slot": image["slot"] if image["filename"] else None,
                           "filename": image["filename"],
                           "base": (image["filename"] is not None
                                    and image["slot"] is None),
                           "why": image["why"]},
        "canonical_url": canonical,
    }

    def _norm(value, is_base):
        if value == "base":
            return "base"
        if value is None:
            return "base" if is_base else None
        return value

    voted = {}
    for name, signal in signals.items():
        value = _norm(signal["slot"], signal.get("base", False))
        if value is not None:
            voted[name] = value
    distinct = set(voted.values())
    if not voted:
        return {"slot": None, "agreed": False, "signals": signals,
                "why": "no signal on the page identifies the printing"}
    if len(distinct) > 1:
        return {"slot": None, "agreed": False, "signals": signals,
                "why": "signals disagree: "
                       + ", ".join(f"{k}={v}" for k, v in sorted(voted.items()))}
    only = distinct.pop()
    return {"slot": None if only == "base" else only,
            "is_base": only == "base", "agreed": True,
            "voted_by": sorted(voted), "signals": signals, "why": None}


def verify_slot(page, requested):
    """Did the page that came back describe the printing that was asked for?

    A request for `?v=3` was observed returning the `?v=2` page. Whether that
    is a redirect on their side or de-duping in the fetch path cannot be told
    from outside, and does not need to be: either way the answer is to compare
    and refuse, never to trust the request as a description of the response.
    """
    observed = observed_slot(page)
    wanted = "base" if requested is None else requested
    got = "base" if observed.get("is_base") else observed["slot"]
    if not observed["agreed"]:
        return {"ok": False, "requested": requested, "observed": None,
                "why": f"page does not identify its printing ({observed['why']})",
                "signals": observed["signals"]}
    if got != wanted:
        return {"ok": False, "requested": requested, "observed": observed["slot"],
                "why": f"requested v={wanted} but the page describes v={got}. "
                       "A fetch that returns a neighbour puts a wrong pair in "
                       "the table with everything green.",
                "signals": observed["signals"]}
    return {"ok": True, "requested": requested, "observed": observed["slot"],
            "confirmed_by": observed["voted_by"], "why": None,
            "signals": observed["signals"]}


def slot_binding_evidence(page, requested):
    """Does `?v=N` equal `_pN` ON THIS CARD?

    CONFIRMED FOR n=1 PAIRINGS (`?v=2` / `_p2`, plus base / no suffix). One
    card is not the mapping; it is one observation of it. So the binding is
    re-confirmed per card from the image filename rather than assumed, and a
    card where it fails is evidence ABOUT THE MAPPING, not about that card.
    """
    image = image_slot(page)
    if not image["filename"]:
        return {"status": "no_evidence", "requested": requested,
                "why": "no card image on the page"}
    from_image = image["slot"]
    wanted = None if requested is None else int(requested)
    if from_image == wanted:
        return {"status": "confirms", "requested": requested,
                "image_slot": from_image, "filename": image["filename"]}
    return {"status": "contradicts", "requested": requested,
            "image_slot": from_image, "filename": image["filename"],
            "why": f"requested v={wanted} but the asset is "
                   f"{image['filename']}. Evidence about the ?v=N <-> _pN "
                   "mapping, not about this card."}


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
    return dict({
        "set_code_asked": set_code,
        "number": number,
        "product_set_code": parsed["set_code"],
        "product_name": parsed["product_name"],
        "treatment": parsed["treatment"],
        "reprint_note_is_card_level": bool(parsed["reprint_note"]),
        "attested": attested,
        "corroboration_tier": "full" if attested else None,
    }, **count_printings(page))


def count_printings(page):
    """How many printings this card has, and whether that is exact.

    A page omits its OWN `?v=` link, so the links alone always undercount by
    one. Adding the current printing back needs to know which one it is, and
    where the signals cannot say, this reports a LOWER BOUND and says so
    rather than returning a count that reads as a total.
    """
    rows = print_table_rows(page)
    slots = [row["slot"] for row in rows["linked"]]
    if not slots:
        return {"printing_count": None, "printing_count_exact": False,
                "printing_count_why": "no print table on the page"}
    observed = observed_slot(page)
    base_and_links = len(slots) + 1          # every `?v=` row, plus the base
    if not observed["agreed"]:
        return {"printing_count": base_and_links,
                "printing_count_exact": False,
                "printing_count_why": "AT LEAST -- the page does not identify "
                                      "its own printing, so it cannot be added "
                                      f"back ({observed['why']})"}
    if observed.get("is_base"):
        return {"printing_count": base_and_links,
                "printing_count_exact": True, "printing_count_why": None}
    if observed["slot"] in slots:
        return {"printing_count": base_and_links,
                "printing_count_exact": False,
                "printing_count_why": "AT LEAST -- the current printing is "
                                      "also linked, so the page is not "
                                      "omitting its own row as expected"}
    return {"printing_count": base_and_links + 1,
            "printing_count_exact": True, "printing_count_why": None}


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


def attest(adapter=None, wanted=WANTED, resolve_slots=True):
    """One fetch per CARD, then a BOUNDED follow-up per unresolved product.

    Returns (attestations, entries, failures, binding).

    Every response is checked against what was asked for before it is used.
    A request for `?v=3` was observed coming back as the `?v=2` page; whether
    that is a redirect upstream or de-duping in the fetch path cannot be told
    from outside and does not need to be. Either way the response is compared
    to the request and a mismatch is recorded as unresolved, because a fetch
    that quietly returns a neighbour is how a wrong pair enters the table with
    every check green.
    """
    adapter = adapter or LimitlessAdapter()
    fetched, failures, binding = [], [], []
    for set_code, number in wanted:
        try:
            url, page = adapter.card_page(set_code, number)
        except (AdapterGaveUp, RateLimited) as exc:
            failures.append({"set_code": set_code, "number": number,
                             "why": str(exc)[:300]})
            continue
        check = verify_slot(page, None)
        binding.append(dict(slot_binding_evidence(page, None),
                            set_code=set_code, number=number))
        if not check["ok"]:
            failures.append({"set_code": set_code, "number": number,
                             "requested": "base", "observed": check["observed"],
                             "why": "slot mismatch on the card page: "
                                    + check["why"]})
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

    if resolve_slots:
        entries, more, evidence = _resolve_unattested(adapter, entries)
        failures.extend(more)
        binding.extend(evidence)
    return attestations, entries, failures, binding


def _resolve_unattested(adapter, entries):
    """Fetch ONLY the slots whose product no page has named.

    Bounded by construction: a slot already resolved is never refetched, so
    this is a follow-up on gaps rather than a walk of the manifest.
    """
    failures, evidence = [], []
    for entry in entries:
        if entry["product_set_code"]:
            continue
        set_code, number, slot = (entry["set_code_asked"], entry["number"],
                                  entry["slot"])
        try:
            url, page = adapter.card_page(set_code, number, variant=slot)
        except (AdapterGaveUp, RateLimited) as exc:
            entry["unresolved"] = f"could not fetch ?v={slot}: {str(exc)[:160]}"
            failures.append({"set_code": set_code, "number": number,
                             "slot": slot, "why": str(exc)[:300]})
            continue
        evidence.append(dict(slot_binding_evidence(page, slot),
                             set_code=set_code, number=number))
        check = verify_slot(page, slot)
        if not check["ok"]:
            entry["unresolved"] = (
                f"requested ?v={slot}; the page that came back is not it "
                f"({check['why']}). Left unresolved rather than credited to "
                "the printing that answered.")
            entry["slot_mismatch"] = {"requested": slot,
                                      "observed": check["observed"]}
            failures.append({"set_code": set_code, "number": number,
                             "slot": slot, "requested": slot,
                             "observed": check["observed"],
                             "why": check["why"]})
            continue
        line = product_line(page)
        if not line:
            entry["unresolved"] = (f"?v={slot} links no product slug; refusing "
                                   "to read a product off the title")
            failures.append({"set_code": set_code, "number": number,
                             "slot": slot,
                             "why": "page links no product slug"})
            continue
        entry["product_set_code"] = line["set_code"]
        entry["product_name"] = line["product_name"]
        entry["treatment"] = line["treatment"]
        entry["attested_by"] = f"{url} product slug {line['slug']}"
        entry["unresolved"] = None
        entry["source"] = "limitless_variant_page"
    return entries, failures, evidence


def render_binding_report(binding) -> str:
    """What the fetch says about `?v=N` <-> `_pN`, per card.

    CONFIRMED AT n=1 when this was written -- `?v=2`/`_p2` on one card, plus
    base/no-suffix. One pairing is one observation of the mapping, not the
    mapping, so the adapter re-confirms it from the image filename on every
    page it reads and a card where it fails is evidence ABOUT THE MAPPING.
    """
    confirms = [b for b in binding if b["status"] == "confirms"]
    contradicts = [b for b in binding if b["status"] == "contradicts"]
    silent = [b for b in binding if b["status"] == "no_evidence"]
    lines = ["", "**`?v=N` <-> `_pN` binding**, re-confirmed per card from the "
             "asset URL rather than assumed. "
             f"{len(confirms)} confirm, {len(contradicts)} contradict, "
             f"{len(silent)} silent.", ""]
    if contradicts:
        lines += ["A contradiction is evidence about the MAPPING, not about "
                  "the card:", ""]
        for b in contradicts:
            lines.append(f"- `{b['number']}` requested v={b['requested']}, "
                         f"asset {b['filename']}")
    if not contradicts and confirms:
        lines.append(f"No contradiction across {len(confirms)} pairing(s).")
    return "\n".join(lines)


def render_attestation_report(attestations, entries, failures,
                              binding=()) -> str:
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
        mismatched = [e for e in entries if e.get("slot_mismatch")]
        lines += ["", f"**Slot reconciliation** -- {len(resolved)} of "
                  f"{len(entries)} printings resolved to a product"
                  + (f", {len(mismatched)} refused on a slot mismatch"
                     if mismatched else "")
                  + ". A SEMANTIC treatment against a provider's POSITIONAL "
                  "slot, each citing the page. Ground truth keeps the semantic "
                  "token: a positional one would make the identity scheme "
                  "catalog-derived.", "",
                  "| Card | Slot | Label | Product | Treatment |",
                  "|---|---:|---|---|---|"]
        for e in entries:
            product = (e["product_set_code"] or
                       ("**slot mismatch**" if e.get("slot_mismatch")
                        else "**unresolved**"))
            lines.append(f"| `{e['number']}` | {e['slot']} | {e['label']} "
                         f"| {product} "
                         f"| {e['treatment'] or e['treatment_short'] or '--'} |")
    if binding:
        lines.append(render_binding_report(binding))
    if failures:
        lines += ["", "**Not attested.** No entry was written for these, and "
                  "the reconciliation REFUSES rather than falling back to slot "
                  "order or to whichever printing happened to answer:", ""]
        for f in failures:
            slot = f" v={f['slot']}" if f.get("slot") is not None else ""
            lines.append(f"- `{f['number']}`{slot} -- {f['why']}")
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

    attestations, entries, failures, binding = attest()
    report = render_attestation_report(attestations, entries,
                                       failures, binding)
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
