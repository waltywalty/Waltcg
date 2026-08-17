"""Build ingest/targets.json from the providers' own set catalogs.

Re-run this when new sets drop:

    python -m ingest.catalog --write

WHAT IT DOES. Walks every set from tcgapi and apitcg across all eight
game/language combinations, keeps the cards worth tracking, and writes the
target list the daily runner reads. Nothing is typed by hand.

WHAT "WORTH TRACKING" MEANS. Commons and uncommons are dropped. Grading EV is
only interesting where the gem premium is large relative to the fee, which is
chase rares, alt arts, SIRs, SARs, manga rares and promos. A $2 common cannot
repay a $79.99 submission at any probability, so tracking it spends quota to
learn nothing. The bands come from store.cross_grader.rarity_band so the
tracking filter and the ratio buckets cannot drift apart.

WHAT IT CANNOT DO. Four of the eight combinations have no catalog source at
all -- the three Chinese printings, and One Piece Japan is absent from tcgapi's
game list entirely. Those are recorded as explicit gaps in the output, with the
reason, rather than silently producing a shorter list. A combo with no source
and a combo with no chase cards are different facts.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.adapters import ApiTcgAdapter, TcgApiAdapter          # noqa: E402
from ingest.base import AdapterGaveUp, RateLimited, find          # noqa: E402
from resolve.identity import TCGAPI_GAME_ID, card_uid             # noqa: E402
from store.cross_grader import rarity_band                        # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = os.path.join(REPO, "ingest", "targets.json")

COMBOS = [("optcg", "EN"), ("optcg", "JP"), ("optcg", "CN-S"),
          ("pkmn", "EN"), ("pkmn", "JP"), ("pkmn", "CN-S"), ("pkmn", "CN-T"),
          ("riftbound", "EN")]

# Bands kept. `rare` is deliberately excluded: an ordinary holo rare almost
# never clears a grading fee, and including it would triple the daily quota
# spend for cards no signal would ever surface.
TRACKED_BANDS = ("chase", "premium")

# apitcg has no language dimension, so it can only fill a combo whose language
# it actually serves. One Piece JP is its one genuine addition over tcgapi.
APITCG_LANGUAGES = {"optcg": ("EN", "JP"), "pkmn": ("EN",), "riftbound": ("EN",)}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


def _variant_of(rarity, name) -> str:
    """Best guess at the variant token, from the rarity the provider states.

    A guess, and labelled as one -- the resolver treats a variant mismatch as
    evidence against, so a wrong guess here costs confidence rather than
    producing a wrong match.
    """
    text = f"{rarity or ''} {name or ''}".lower()
    for token, marker in (("manga_rare", "manga"), ("signature", "signature"),
                          ("overnumbered", "overnumber"), ("sar", "sar"),
                          ("sir", "special illustration"), ("promo", "promo"),
                          ("parallel", "parallel"), ("alt_art", "alt")):
        if marker in text:
            return token
    return "base"


class CatalogBuilder:
    def __init__(self, tcgapi=None, apitcg=None):
        self.tcgapi = tcgapi if tcgapi is not None else TcgApiAdapter()
        self.apitcg = apitcg if apitcg is not None else ApiTcgAdapter()
        self.gaps = []
        self.log = []

    def gap(self, combo, reason, detail=""):
        game, language = combo
        self.gaps.append({"game": game, "language": language,
                          "combo": f"{game}:{language}", "reason": reason,
                          "detail": detail})

    def sets_for(self, game, language):
        """Every set for a combo, read to the LAST page."""
        game_id = TCGAPI_GAME_ID.get((game, language))
        if game_id is None:
            self.gap((game, language), "no_catalog_source",
                     "tcgapi has no game entry for this combination")
            return []
        out, page = [], 1
        while True:
            payload = self.tcgapi.get(
                f"https://api.tcgapi.dev/v1/sets?game={game_id}"
                f"&page={page}&per_page=100", label=f"sets-{game}-{language}-p{page}")
            batch = find(payload, "data", "sets", "results") or []
            out.extend(batch)
            meta = find(payload, "meta") or {}
            if not (meta.get("has_more") or meta.get("hasMore")):
                break
            page += 1
            if page > 100:
                raise AdapterGaveUp("set pagination did not terminate")
        return out

    def cards_in_set(self, game, language, set_code):
        """Every card in one set. Prefers /bulk where the provider offers it --
        one call instead of one per page is the difference between a full
        catalog refresh fitting in the daily quota and not."""
        game_id = TCGAPI_GAME_ID.get((game, language))
        try:
            payload = self.tcgapi.get(
                f"https://api.tcgapi.dev/v1/bulk?game={game_id}&set={set_code}",
                label=f"bulk-{game}-{language}-{set_code}")
            cards = find(payload, "data", "cards", "results")
            if cards:
                return cards
        except AdapterGaveUp:
            self.log.append(f"{game}:{language}:{set_code} no /bulk, paging /cards")

        out, page = [], 1
        while True:
            payload = self.tcgapi.get(
                f"https://api.tcgapi.dev/v1/cards?game={game_id}&set={set_code}"
                f"&page={page}&per_page=250", label=f"cards-{set_code}-p{page}")
            batch = find(payload, "data", "cards", "results") or []
            out.extend(batch)
            meta = find(payload, "meta") or {}
            if not (meta.get("has_more") or meta.get("hasMore")):
                break
            page += 1
            if page > 100:
                raise AdapterGaveUp("card pagination did not terminate")
        return out

    def apitcg_cards(self, game, language):
        """apitcg fills One Piece JP, which tcgapi's catalog cannot express."""
        if language not in APITCG_LANGUAGES.get(game, ()):
            return []
        slug = ApiTcgAdapter.SLUG.get(game)
        out, page = [], 1
        while True:
            payload = self.apitcg.get(
                f"https://apitcg.com/api/{slug}/cards?page={page}&limit=100",
                label=f"apitcg-{game}-{language}-p{page}")
            batch = find(payload, "data", "cards") or []
            out.extend(batch)
            if len(batch) < 100 or page > 100:
                break
            page += 1
        return out

    def build(self, combos=COMBOS):
        catalog = {}
        for game, language in combos:
            rows, sources = [], []
            try:
                for entry in self.sets_for(game, language):
                    set_code = str(find(entry, "code", "set_code", "id") or "")
                    if not set_code:
                        continue
                    for hit in self.cards_in_set(game, language, set_code):
                        row = self._row(game, language, set_code, hit, "tcgapi")
                        if row:
                            rows.append(row)
                if rows:
                    sources.append("tcgapi")
            except (AdapterGaveUp, RateLimited) as exc:
                self.gap((game, language), "source_unreachable", str(exc)[:200])

            try:
                extra = self.apitcg_cards(game, language)
                for hit in extra:
                    row = self._row(game, language,
                                    str(find(hit, "set_code", "setCode",
                                             "set") or ""), hit, "apitcg")
                    if row:
                        rows.append(row)
                if extra:
                    sources.append("apitcg")
            except (AdapterGaveUp, RateLimited) as exc:
                self.gap((game, language), "apitcg_unreachable", str(exc)[:200])

            deduped = {r["card_uid"]: r for r in rows}
            if not deduped and not any(
                    g["combo"] == f"{game}:{language}" for g in self.gaps):
                self.gap((game, language), "no_tracked_cards",
                         "catalog reachable but nothing in a tracked rarity band")
            catalog[f"{game}:{language}"] = {
                "sources": sources,
                "cards": sorted(deduped.values(), key=lambda r: r["card_uid"]),
            }
        return catalog

    def _row(self, game, language, set_code, hit, source):
        rarity = find(hit, "rarity")
        if rarity_band(rarity) not in TRACKED_BANDS:
            return None
        number = str(find(hit, "number", "collector_number", "code") or "").strip()
        if not number or not set_code:
            return None
        name = find(hit, "name") or ""
        variant = _variant_of(rarity, name)
        try:
            uid = card_uid(game, set_code, number, variant, language)
        except (ValueError, KeyError):
            return None
        return {"card_uid": uid, "game": game, "language": language,
                "set_code": set_code, "number": number, "variant": variant,
                "name": name, "rarity": rarity,
                "external_id": str(find(hit, "id", "card_id") or ""),
                "source": source}


def to_targets(catalog, gaps):
    """The shape the daily runner reads. Card identities only -- no prices."""
    per_source = {name: {"cards": []} for name in
                  ("tcgapi", "pokemonpricetracker", "apitcg", "pricecharting")}
    for combo, entry in catalog.items():
        for card in entry["cards"]:
            target = {"card_uid": card["card_uid"], "game": card["game"],
                      "language": card["language"], "name": card["name"],
                      "number": card["number"], "set_code": card["set_code"],
                      "external_id": card["external_id"],
                      "game_id": TCGAPI_GAME_ID.get((card["game"],
                                                     card["language"]))}
            per_source["tcgapi"]["cards"].append(target)
            per_source["apitcg"]["cards"].append(target)
            # PokemonPriceTracker is Pokemon-only by construction, and
            # PriceCharting covers the games it does not. Sending every card to
            # every source would burn quota on guaranteed misses.
            if card["game"] == "pkmn":
                per_source["pokemonpricetracker"]["cards"].append(target)
            else:
                per_source["pricecharting"]["cards"].append(target)
    return {
        "_note": ("Generated by ingest/catalog.py. Card IDENTITIES only -- no "
                  "prices, no populations, no provider payloads. Re-run when "
                  "new sets drop; do not hand-edit."),
        "_generated_at": _now().isoformat() + "Z",
        "_counts": {combo: len(entry["cards"]) for combo, entry in catalog.items()},
        "_gaps": gaps,
        "fx_alphavantage": {},
        **per_source,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="build ingest/targets.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--out", default=TARGETS)
    parser.add_argument("--combos", default="all")
    args = parser.parse_args(argv)

    combos = COMBOS
    if args.combos != "all":
        wanted = set(args.combos.split(","))
        combos = [c for c in COMBOS if f"{c[0]}:{c[1]}" in wanted]

    builder = CatalogBuilder()
    catalog = builder.build(combos)
    targets = to_targets(catalog, builder.gaps)

    total = sum(targets["_counts"].values())
    for combo, count in sorted(targets["_counts"].items()):
        print(f"  {combo:16} {count:>5} tracked")
    for gap in builder.gaps:
        print(f"  GAP {gap['combo']:12} {gap['reason']}: {gap['detail'][:70]}")
    print(f"\n{total} cards across {len(catalog)} combos")

    if args.write:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(targets, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"wrote {args.out}")

    # Zero everywhere means the daily run would fail its zero-rows gate, and
    # the reason is here rather than there.
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
