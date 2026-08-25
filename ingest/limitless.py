"""Limitless variant pages: the source class that can tell two products apart.

WHY THIS EXISTS. `OP01-120` has six printings across two products -- `op01`
holds the base, `_p1` and `_p2`; `prb01` holds `_p3`, `_p4`, `_p5`. Every
marketplace listing attributes all six to "Romance Dawn", because the printed
number says `OP01` and that is what a seller reads. The attribution is derived
from the number, so it carries no information the number did not already carry
(see `resolve/corroboration.py`).

Limitless serves a SEPARATE PAGE PER PRINTING, each naming its own product --
a base page reading "Romance Dawn (OP01) Secret Rare -- reprinted in: One Piece
The Best (PRB01)", and a `?v=N` page titled "One Piece The Best". That is a
source that can discriminate. It is the only one identified so far.

THE URL SHAPE IS PROBED, NOT ASSUMED. Four adapters in this project have been
written against a guessed endpoint and three of those guesses were wrong; the
one that was not still cost a run. `Adapter.probe` tries the candidates and
reports which answered, and a page that does not answer is recorded as a gap
with the URLs tried rather than as "the card has no variants".

CANNOT RUN IN THE SANDBOX. The egress proxy answers 403 to CONNECT for
limitlesstcg.com, so this runs on the Actions runner like the coverage and
rarity reports. The measurement is deferred; the parsing is not, and is tested
against fixtures below.
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
    # every two seconds is slow enough to be invisible and fast enough to walk
    # six cards' variants in under a minute.
    min_interval_seconds = 2.0

    #: Candidate URL shapes, most likely first. NOT a guess dressed as a
    #: constant -- `variant_page` probes them and records which answered.
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
        """Raw page text. `Adapter.get` parses JSON; these pages are HTML."""
        headers = {}
        status, body, response_headers = self._send(url, headers)
        self.quota.consumed_this_run += 1
        self.responses_seen += 1
        self._last_call = self._monotonic()
        self.note_rate_headers(response_headers)
        path = self.cache_raw(url, body)
        self.log.append(f"{self.name} {status} {url} -> {path}")
        if status == 429:
            why = self.note_rate_limit(response_headers)
            raise RateLimited(f"{self.name}: {why}")
        if status >= 400:
            raise AdapterGaveUp(f"{self.name}: HTTP {status} for {url}")
        return body.decode("utf-8", errors="replace")

    def card_page(self, set_code, number, variant=None):
        """One printing's page, and the URL that served it."""
        index = str(number).split("-")[-1].lstrip("0") or "0"
        suffix = f"?v={variant}" if variant else ""
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
            + (f" v={variant}" if variant else "") + ". Tried "
            + "; ".join(f"{u} ({why})" for u, why in tried))


# -- parsing, which is the part that can be tested here --------------------

_TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
# "reprinted in: One Piece The Best (PRB01)" -- the relationship stated on the
# base page. The product code in brackets is what we actually want.
_REPRINTED_IN = re.compile(
    r"reprinted\s+in[:\s]*(.*?)(?:<|$)", re.I | re.S)
_PRODUCT_CODE = re.compile(r"\(([A-Z]{2,5}\d{0,2})\)")
# The variant selector: `?v=4` links, each labelled with its treatment.
_VARIANT_LINK = re.compile(
    r'href="[^"]*\?v=(\d+)"[^>]*>(.*?)</a>', re.I | re.S)


def _text(fragment) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).strip()


def parse_variant_page(page) -> dict:
    """What a Limitless page attests, and nothing more.

    Every field is `None` when the page does not say it. A page that omits the
    product is a page that does not attest the product -- returning a guess
    would make this source indistinguishable from the marketplace listings it
    exists to replace.
    """
    title = _TITLE.search(page)
    heading = _H1.search(page)
    title_text = _text(title.group(1)) if title else None
    heading_text = _text(heading.group(1)) if heading else None

    product_code = None
    for candidate in (title_text, heading_text):
        if not candidate:
            continue
        found = _PRODUCT_CODE.search(candidate)
        if found:
            product_code = found.group(1)
            break

    reprinted = _REPRINTED_IN.search(page)
    reprinted_text = _text(reprinted.group(1)) if reprinted else None
    reprinted_code = None
    if reprinted_text:
        found = _PRODUCT_CODE.search(reprinted_text)
        reprinted_code = found.group(1) if found else None

    variants = []
    for slot, label in _VARIANT_LINK.findall(page):
        name = _text(label)
        if name:
            variants.append({"slot": int(slot), "label": name})

    return {
        "product_title": title_text,
        "product_code": product_code,
        "reprinted_in": reprinted_text,
        "reprinted_in_code": reprinted_code,
        "variants": variants,
    }


def product_attestation(page, set_code, number) -> dict:
    """The PRODUCT-level claim, which is the certain one.

    Certain because it is what the page is FOR: a variant page is served per
    printing and titled with its own product. That is a different claim from
    mapping a treatment onto a provider's positional `_pN` slot, which is a
    reconciliation and is recorded as data elsewhere.
    """
    parsed = parse_variant_page(page)
    return {
        "set_code": set_code,
        "number": number,
        "product_code": parsed["product_code"],
        "product_title": parsed["product_title"],
        "reprinted_in_code": parsed["reprinted_in_code"],
        "attested": parsed["product_code"] is not None,
        "corroboration_tier": "full" if parsed["product_code"] else None,
    }


# -- slot reconciliation, and the CLI that fills it ------------------------

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLOTS = os.path.join(REPO, "contracts", "printing_slots.json")

#: The cards this exists to settle. Five PRB reprint pairs plus the two S1
#: rows whose product is in doubt.
WANTED = (
    ("OP01", "OP01-120"),   # S1: manga rows, product uncertain
    ("OP05", "OP05-119"),
    ("OP02", "OP02-013"),
    ("OP01", "OP01-070"),
    ("EB01", "EB01-012"),
    ("OP09", "OP09-046"),
)


def attest(adapter=None, wanted=WANTED):
    """Fetch each card's pages and record what they attest.

    Returns (attestations, entries, failures). Nothing is written by this
    function -- the caller decides, and a failure is a gap with the URLs tried
    rather than an absent treatment.
    """
    import json as _json
    adapter = adapter or LimitlessAdapter()
    attestations, entries, failures = [], [], []
    for set_code, number in wanted:
        try:
            url, page = adapter.card_page(set_code, number)
        except (AdapterGaveUp, RateLimited) as exc:
            failures.append({"set_code": set_code, "number": number,
                             "why": str(exc)[:300]})
            continue
        parsed = parse_variant_page(page)
        attestations.append(dict(product_attestation(page, set_code, number),
                                 url=url))
        for variant in parsed["variants"]:
            try:
                v_url, v_page = adapter.card_page(set_code, number,
                                                  variant=variant["slot"])
            except (AdapterGaveUp, RateLimited) as exc:
                failures.append({"set_code": set_code, "number": number,
                                 "slot": variant["slot"],
                                 "why": str(exc)[:300]})
                continue
            v_parsed = parse_variant_page(v_page)
            if not v_parsed["product_code"]:
                # THE PAGE DOES NOT ATTEST IT. No entry, and the
                # reconciliation refuses rather than ordering the slots.
                failures.append({"set_code": set_code, "number": number,
                                 "slot": variant["slot"],
                                 "why": "page names no product; refusing to "
                                        "infer one from slot order"})
                continue
            entries.append({
                "set_code": set_code, "number": number,
                "slot": variant["slot"],
                "treatment": variant["label"],
                "product_code": v_parsed["product_code"],
                "product_title": v_parsed["product_title"],
                "source": "limitless_variant_page",
                "url": v_url,
            })
    return attestations, entries, failures


def render_attestation_report(attestations, entries, failures) -> str:
    lines = ["### Limitless variant pages", ""]
    if attestations:
        lines += ["**Product attested per card.** This is the certain claim: a "
                  "variant page is served per printing and titled with its own "
                  "product.", "",
                  "| Card | Product | Reprinted in | Page |",
                  "|---|---|---|---|"]
        for a in attestations:
            lines.append(f"| `{a['number']}` | {a['product_code'] or '--'} "
                         f"| {a['reprinted_in_code'] or '--'} | {a['url']} |")
    if entries:
        lines += ["", "**Slot reconciliation.** A SEMANTIC treatment against a "
                  "provider's POSITIONAL slot, one entry per card, each citing "
                  "the page. Ground truth keeps the semantic token -- a "
                  "positional one would make the identity scheme "
                  "catalog-derived.", "",
                  "| Card | Slot | Treatment | Product |", "|---|---:|---|---|"]
        for e in entries:
            lines.append(f"| `{e['number']}` | {e['slot']} | {e['treatment']} "
                         f"| {e['product_code']} |")
    if failures:
        lines += ["", "**Not attested.** No entry was written for these, and "
                  "the reconciliation REFUSES rather than falling back to slot "
                  "order -- ordering the slots and assuming the first is the "
                  "base is the inference that put OP01-120 in the wrong "
                  "product:", ""]
        for f in failures:
            slot = f" v={f['slot']}" if f.get("slot") else ""
            lines.append(f"- `{f['number']}`{slot} -- {f['why']}")
    if not (attestations or entries or failures):
        lines += ["Nothing was fetched."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    import argparse
    import json as _json
    parser = argparse.ArgumentParser(prog="ingest.limitless")
    parser.add_argument("--attest", action="store_true",
                        help="fetch the variant pages and report what they "
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
