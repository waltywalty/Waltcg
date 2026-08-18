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
from ingest.registry import ADAPTERS, CN_SOURCE_PRIORITY          # noqa: E402
from ingest.runner import load_expectations                       # noqa: E402
from resolve.identity import (RIFTBOUND_SETS, TCGAPI_GAME_ID,     # noqa: E402
                              TCGAPI_GAME_SLUG, TCGAPI_KNOWN_SLUGS,
                              card_uid, variant_from_number,
                              variant_from_rarity)
from store.cross_grader import rarity_band                        # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = os.path.join(REPO, "ingest", "targets.json")

COMBOS = [("optcg", "EN"), ("optcg", "JP"), ("optcg", "CN-S"),
          ("pkmn", "EN"), ("pkmn", "JP"), ("pkmn", "CN-S"), ("pkmn", "CN-T"),
          ("riftbound", "EN")]

# Bands kept. `rare` is deliberately excluded: an ordinary holo rare almost
# never clears a grading fee, and including it would triple the daily quota
# spend for cards no signal would ever surface.
#
# `unknown` IS kept, and that is the run #7 lesson: an absent rarity is not a
# common. Imported rather than redeclared so the catalog filter and the
# classifier cannot drift -- which is how the tcgdex zero survived a session.
from ingest.rarity import (TRACKED_BANDS, UNKNOWN,  # noqa: E402
                           band_of, string_band)

# apitcg has no language dimension, so it can only fill a combo whose language
# it actually serves. One Piece JP is its one genuine addition over tcgapi.
APITCG_LANGUAGES = {"optcg": ("EN", "JP"), "pkmn": ("EN",), "riftbound": ("EN",)}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


# The variant guess lives in resolve/identity.py so the catalog builder and the
# resolver cannot disagree about what a card is. They used to hold two copies
# and only one of them knew about Treasure Rares -- which meant the builder
# filed a TR at `base`, colliding with the ordinary card at the same number.
_variant_of = variant_from_rarity


class CatalogBuilder:
    def __init__(self, tcgapi=None, apitcg=None, cn_sources=None):
        self.tcgapi = tcgapi if tcgapi is not None else TcgApiAdapter()
        self.apitcg = apitcg if apitcg is not None else ApiTcgAdapter()
        self._cn = dict(cn_sources or {})
        self.gaps = []
        self.log = []
        # Which candidate URL actually answered, per endpoint. Populated by
        # discovery and reported, because "which endpoint worked" is the fact
        # that turns a zero into a diagnosis.
        self.endpoints_used = {}
        # Per combo: why it has the count it has. `ok` and `catalog_ran_empty`
        # and `no_catalog_source` are three different facts and only one of
        # them is "nothing to see here".
        self.combo_status = {}
        # combo -> {sources a request was actually issued to}
        self.attempted = {}
        self._slugs = None
        # Rarity strings no table classifies, per combo. Named in the summary:
        # an unmapped rarity is tracked (it is `unknown`) but a finding that is
        # not named is a finding that is lost.
        self.unmapped_rarities = {}

    def attempt(self, combo, source):
        """Record that a request was actually ISSUED for this combination.

        The difference between `no_catalog_source` and `source_unreachable` is
        whether anything was asked, and that cannot be reconstructed from the
        gap reasons -- a gap is written in both cases.
        """
        self.attempted.setdefault(f"{combo[0]}:{combo[1]}", set()).add(source)

    def gap(self, combo, reason, detail=""):
        game, language = combo
        self.gaps.append({"game": game, "language": language,
                          "combo": f"{game}:{language}", "reason": reason,
                          "detail": detail})

    # THESE FOUR ENDPOINTS WERE NEVER VERIFIED. probe/COVERAGE.md records a 200
    # from tcgapi's `/v1/games` and `/v1/search`, and from apitcg's
    # `/api/{game}/cards?name={name}`. It records nothing about `/v1/sets`,
    # `/v1/bulk`, `/v1/cards`, or apitcg enumeration by page -- those were
    # invented here and used as though they were facts.
    #
    # That is the same class of guess as the superseded `cryst` adapter, with
    # one difference that mattered: cryst was MARKED unverified, so its failure
    # read as a finding. These were not, so a wrong URL came back as "this
    # combination has no chase cards" and the catalog quietly wrote nothing.
    #
    # So they are probed, in the same way, and which candidate answered is
    # reported. `endpoints_used` is the record.
    # tcgapi's set and card paths are SLUG-based and nested. The numeric game
    # ids address /v1/search and /v1/games and nothing else, which is why the
    # three query-string shapes tried in run #8 all 404'd.
    SETS = ("https://api.tcgapi.dev/v1/games/{slug}/sets"
            "?page={page}&per_page=100")
    CARDS = ("https://api.tcgapi.dev/v1/games/{slug}/sets/{set}/cards"
             "?page={page}&per_page=100")

    def game_slug(self, game, language):
        """Slug for a combo, confirmed where known and RESOLVED where not.

        Only English slugs are confirmed. Rather than invent `pokemon-japan`,
        anything else is looked up in the provider's own `/v1/games` -- a
        verified endpoint -- and matched by numeric id. A slug that cannot be
        resolved is a gap, not a guess.
        """
        known = TCGAPI_GAME_SLUG.get((game, language))
        if known:
            return known
        if self._slugs is None:
            self._slugs = {}
            try:
                for entry in self.tcgapi.games():
                    ident = str(find(entry, "id", "game_id") or "")
                    slug = str(find(entry, "slug", "code") or "")
                    if ident and slug:
                        self._slugs[ident] = slug
            except (AdapterGaveUp, RateLimited) as exc:
                self.log.append(f"tcgapi /v1/games unavailable: {str(exc)[:120]}")
            except Exception as exc:                        # noqa: BLE001
                # A slug lookup that explodes must not take the build with it.
                # Its failure means "no slug", which is already a gap.
                self.log.append(f"tcgapi /v1/games raised "
                                f"{type(exc).__name__}: {str(exc)[:100]}")
        game_id = TCGAPI_GAME_ID.get((game, language))
        resolved = self._slugs.get(str(game_id)) if game_id else None
        if resolved and resolved not in TCGAPI_KNOWN_SLUGS:
            self.log.append(f"tcgapi slug {resolved!r} for {game}:{language} is "
                            "not in the confirmed list; using it anyway and "
                            "recording that it was resolved, not confirmed")
        return resolved

    def sets_for(self, game, language):
        """Every set for a combo, read to the LAST page."""
        slug = self.game_slug(game, language)
        if slug is None:
            self.gap((game, language), "tcgapi_no_game_entry",
                     "tcgapi has no game slug for this combination, and none "
                     "could be resolved from /v1/games")
            return []

        self.attempt((game, language), "tcgapi")
        out, page = [], 1
        while True:
            payload = self.tcgapi.get(self.SETS.format(slug=slug, page=page),
                                      label=f"sets-{slug}-p{page}")
            batch = find(payload, "data", "sets", "results") or []
            out.extend(batch)
            meta = find(payload, "meta") or {}
            if not (meta.get("has_more") or meta.get("hasMore")) or not batch:
                break
            page += 1
            if page > 100:
                raise AdapterGaveUp("set pagination did not terminate")
        self.endpoints_used["tcgapi.sets"] = self.SETS
        return out

    def cards_in_set(self, game, language, set_code):
        """Every card in one set, via the nested slug path."""
        slug = self.game_slug(game, language)
        if slug is None:
            return []
        out, page = [], 1
        while True:
            payload = self.tcgapi.get(
                self.CARDS.format(slug=slug, set=set_code, page=page),
                label=f"cards-{slug}-{set_code}-p{page}")
            batch = find(payload, "data", "cards", "results") or []
            out.extend(batch)
            meta = find(payload, "meta") or {}
            if not (meta.get("has_more") or meta.get("hasMore")) or not batch:
                break
            page += 1
            if page > 100:
                raise AdapterGaveUp("card pagination did not terminate")
        self.endpoints_used["tcgapi.cards"] = self.CARDS
        return out

    def apitcg_cards(self, game, language):
        """apitcg fills One Piece JP, which tcgapi's catalog cannot express.

        Paged through /api/products per the OpenAPI spec -- 100 per page, which
        is the documented cap, reading `total` to know when to stop rather than
        guessing from a short page.
        """
        if language not in APITCG_LANGUAGES.get(game, ()):
            return []
        self.attempt((game, language), "apitcg")
        out, page = [], 1
        while True:
            rows, total = self.apitcg.products(game, page=page)
            out.extend(rows)
            if not rows or len(out) >= int(total or 0) or page > 100:
                break
            page += 1
        self.endpoints_used["apitcg.products"] = ApiTcgAdapter.PRODUCTS
        return out

    def cn_source(self, name):
        """One open catalog source, built lazily and cached.

        Injectable for tests, and cached so a coverage report and a build in
        the same process do not pay for two probe rounds.
        """
        if name not in self._cn:
            self._cn[name] = ADAPTERS[name]()
        return self._cn[name]

    def live_cn_sources(self):
        """The priority order, minus anything sources.yml has superseded.

        Read from sources.yml rather than hardcoded here so there is one place
        that says a source is retired. A superseded source left in the rotation
        spends a request every run proving a known-wrong endpoint is still
        wrong, and files the answer as a gap that reads like missing data.
        """
        expectations = load_expectations()
        return [name for name in CN_SOURCE_PRIORITY
                if not expectations.get(name, {}).get("superseded_by")]

    def chinese_fallback(self, game, language):
        """First open source that lists cards for this combo, in priority order.

        Returns (rows, {"used": [...], "failed": [(source, why), ...]}).
        Stops at the first source that delivers -- the others are alternatives,
        not supplements, and merging two catalogs that disagree about a number
        would manufacture cards neither of them lists.
        """
        rows, used, failed = [], [], []
        for name in self.live_cn_sources():
            adapter = self.cn_source(name)
            if not adapter.can_enumerate:
                failed.append((name, adapter.cannot_enumerate_because))
                continue
            if (game, language) not in adapter.serves:
                failed.append((name, f"{name} does not serve {game}:{language}"))
                continue
            self.attempt((game, language), name)
            try:
                found = adapter.enumerate_combo(game, language)
            except (AdapterGaveUp, RateLimited) as exc:
                failed.append((name, str(exc)[:200]))
                continue
            kept = [r for r in (self._cn_row(game, language, hit)
                                for hit in found) if r]
            if kept:
                rows, used = kept, [name]
                break
            failed.append((name, "reachable, but no card in a tracked rarity "
                                 "band for this combination"))
        return rows, {"used": used, "failed": failed}

    def _cn_row(self, game, language, hit):
        """A catalog source row -> a targets row, filtered to tracked bands.

        `band_of`, not `rarity_band`: an absent rarity must classify as
        `unknown` and stay tracked. `rarity_band(None)` returns `base`, which
        is the substitution that produced 8,313 cards and zero matches.
        """
        self.note_rarity(game, language, hit.get("rarity"))
        number = hit.get("number")
        size = self.set_size(game, hit.get("set_code"))
        if band_of(hit.get("rarity"), game=game, number=number,
                   set_size=size) not in TRACKED_BANDS:
            return None
        return {"card_uid": hit["card_uid"], "game": game, "language": language,
                "set_code": hit["set_code"], "number": hit["number"],
                "variant": hit["variant"],
                "name": hit.get("name_jp") or hit.get("name_en") or "",
                "rarity": hit.get("rarity"),
                "external_id": str(hit.get("external_id") or ""),
                "source": hit.get("source", "")}

    def coverage(self, combos=None):
        """What the open sources ACTUALLY serve, measured, per combo.

        This is the answer to "report actual coverage rather than assuming".
        It is a measurement and it can only be taken where the hosts are
        reachable, which is the Actions runner and not the sandbox.
        """
        wanted = combos or [c for c in COMBOS if c[1] in ("CN-S", "CN-T")]
        out = []
        for name in CN_SOURCE_PRIORITY:
            adapter = self.cn_source(name)
            serves = [c for c in wanted if tuple(c) in adapter.serves]
            out.extend(adapter.coverage(serves or None))
            for combo in wanted:
                if tuple(combo) not in adapter.serves:
                    out.append({"source": name, "combo": f"{combo[0]}:{combo[1]}",
                                "claimed": False, "reachable": None, "cards": 0,
                                "detail": "source does not claim this combination"})
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
                    # rarity/number live in the dynamic `attributes` map, so
                    # the row is flattened before the shared filter sees it --
                    # `find(hit, "rarity")` would reach into attributes by
                    # accident and by luck, not by contract.
                    flat = {**hit,
                            "rarity": self.apitcg._attr(hit, "Rarity"),
                            "number": (self.apitcg._attr(hit, "Number")
                                       or find(hit, "cardNumber", "code")),
                            "artist": self.apitcg._attr(hit, "Artist")}
                    set_ref = find(hit, "set")
                    set_code = str((set_ref.get("_id") or set_ref.get("slug"))
                                   if isinstance(set_ref, dict)
                                   else (set_ref or ""))
                    row = self._row(game, language, set_code, flat, "apitcg")
                    if row:
                        rows.append(row)
                if extra:
                    sources.append("apitcg")
            except (AdapterGaveUp, RateLimited) as exc:
                self.gap((game, language), "apitcg_unreachable", str(exc)[:200])

            # The commercial providers cannot express the three Chinese
            # printings at all, so anything still empty here falls through to
            # the open sources, tried in priority order and stopping at the
            # first that delivers. Each failure is recorded separately: the
            # useful output of an empty combo is WHICH sources were asked.
            if not rows and language in ("CN-S", "CN-T"):
                rows, tried = self.chinese_fallback(game, language)
                sources.extend(tried["used"])
                for src, why in tried["failed"]:
                    self.gap((game, language), f"{src}_no_cards", why)

            deduped = {r["card_uid"]: r for r in rows}
            combo = f"{game}:{language}"
            reasons = [g["reason"] for g in self.gaps if g["combo"] == combo]
            asked = sorted(self.attempted.get(combo, ()))
            unreachable = [r for r in reasons
                           if "unreachable" in r or "no_cards" in r]
            if deduped:
                status = "ok"
            elif not asked:
                # Nothing serves this combination, so nothing was asked. The
                # honest verdict, and the only one that means "stop looking
                # here and enter it by hand".
                status = "no_catalog_source"
            elif unreachable:
                # Something was asked and did not answer. A wrong endpoint
                # lands here, which is where run #7's silence actually came
                # from -- four never-verified URLs reported as "no chase cards".
                status = "source_unreachable"
            else:
                # Asked, answered, and listed nothing in a tracked rarity band.
                # A real state, and NOT the same as never having asked.
                status = "catalog_ran_empty"
                self.gap((game, language), "no_tracked_cards",
                         "catalog reachable but nothing in a tracked rarity band")
                reasons.append("no_tracked_cards")
            self.combo_status[combo] = {
                "status": status, "cards": len(deduped), "sources": sources,
                "asked": asked, "reasons": sorted(set(reasons)),
            }
            catalog[combo] = {
                "sources": sources,
                "cards": sorted(deduped.values(), key=lambda r: r["card_uid"]),
            }
        return catalog

    def note_rarity(self, game, language, rarity):
        # The STRING question -- "does any table know this word?" -- which is
        # different from what band a given card is in. For a number-dependent
        # game the string alone genuinely cannot answer the second.
        if rarity not in (None, "") and string_band(rarity, game) == UNKNOWN:
            self.unmapped_rarities.setdefault(
                f"{game}:{language}", set()).add(str(rarity))

    def set_size(self, game, set_code):
        """Base card count, for deciding whether a number is above the set.

        Only Riftbound needs it, and only because a bare number like `OGN-301`
        carries no denominator to compare against. `None` is a real answer --
        `above_set_size` returns None rather than False, so an unknown ceiling
        cannot file a Signature as an ordinary card.
        """
        if game != "riftbound":
            return None
        return (RIFTBOUND_SETS.get(str(set_code).upper()) or {}).get("base")

    def _row(self, game, language, set_code, hit, source):
        rarity = find(hit, "rarity")
        number = str(find(hit, "number", "collector_number", "code") or "").strip()
        self.note_rarity(game, language, rarity)
        if not number or not set_code:
            return None
        size = self.set_size(game, set_code)
        # `game=` first: `R`, `P` and `L` mean different things per game, so
        # one shared table would have to pick, and picking is guessing. And
        # `number=` because for Riftbound the band IS the number -- `Showcase`
        # alone spans $40 to $3,090.
        if band_of(rarity, game=game, number=number,
                   set_size=size) not in TRACKED_BANDS:
            return None
        name = find(hit, "name") or ""
        # NUMBER FIRST. The number is the reliable signal and the string is the
        # unreliable one -- `299*/298` is a Signature and apitcg calls it
        # `Alternate Art`. One parser feeds both the variant and the band.
        variant = (variant_from_number(number, size, game)
                   or _variant_of(rarity, name, language))
        try:
            uid = card_uid(game, set_code, number, variant, language)
        except (ValueError, KeyError):
            return None
        return {"card_uid": uid, "game": game, "language": language,
                "set_code": set_code, "number": number, "variant": variant,
                "name": name, "rarity": rarity,
                "external_id": str(find(hit, "id", "card_id") or ""),
                "source": source}


def to_targets(catalog, gaps, combo_status=None, endpoints=None,
               unmapped_rarities=None):
    """The shape the daily runner reads. Card identities only -- no prices."""
    per_source = {name: {"cards": []} for name in
                  ("tcgapi", "pokemonpricetracker", "apitcg", "pricecharting",
                   "manual")}
    # combo -> {price source: how many of its cards route there}. The question
    # "which price source is supposed to price pkmn:EN" had no answer anywhere
    # in the output, so a combo that routed nowhere looked identical to one
    # that routed somewhere and got nothing.
    routing = {}
    for combo, entry in catalog.items():
        # Every combo appears, including the empty ones. A combo missing from
        # the routing map is indistinguishable from one that was never
        # considered, which is the distinction this map exists to make.
        routing.setdefault(combo, {})
        for card in entry["cards"]:
            target = {"card_uid": card["card_uid"], "game": card["game"],
                      "language": card["language"], "name": card["name"],
                      "number": card["number"], "set_code": card["set_code"],
                      "external_id": card["external_id"],
                      "game_id": TCGAPI_GAME_ID.get((card["game"],
                                                     card["language"]))}
            # No price source covers a Chinese printing -- not tcgapi, not
            # PPT, not PriceCharting. The open catalog sources added this
            # session supply IDENTITY only. Routing these anywhere would spend
            # quota on a guaranteed miss, so they are listed in their own
            # bucket: tracked, identified, and awaiting manual prices. Visible
            # rather than silently dropped.
            bucket = routing.setdefault(combo, {})
            if card["language"] in ("CN-S", "CN-T"):
                per_source["manual"]["cards"].append(target)
                bucket["manual"] = bucket.get("manual", 0) + 1
                continue
            per_source["tcgapi"]["cards"].append(target)
            per_source["apitcg"]["cards"].append(target)
            bucket["tcgapi"] = bucket.get("tcgapi", 0) + 1
            bucket["apitcg"] = bucket.get("apitcg", 0) + 1
            # PokemonPriceTracker is Pokemon-only by construction, and
            # PriceCharting covers the games it does not. Sending every card to
            # every source would burn quota on guaranteed misses.
            if card["game"] == "pkmn":
                per_source["pokemonpricetracker"]["cards"].append(target)
                bucket["pokemonpricetracker"] = bucket.get(
                    "pokemonpricetracker", 0) + 1
            else:
                per_source["pricecharting"]["cards"].append(target)
                bucket["pricecharting"] = bucket.get("pricecharting", 0) + 1
    return {
        "_note": ("Generated by ingest/catalog.py. Card IDENTITIES only -- no "
                  "prices, no populations, no provider payloads. Re-run when "
                  "new sets drop; do not hand-edit."),
        "_generated_at": _now().isoformat() + "Z",
        "_counts": {combo: len(entry["cards"]) for combo, entry in catalog.items()},
        # Per combo: WHY it has the count it has. `catalog_ran_empty` and
        # `no_catalog_source` and `source_unreachable` are three different
        # facts, and none of them is the fourth one -- catalog never ran, which
        # is the absence of this whole key.
        "_combo_status": combo_status or {},
        "_routing": routing,
        "_endpoints_used": endpoints or {},
        "_unmapped_rarities": unmapped_rarities or {},
        "_gaps": gaps,
        "fx_alphavantage": {},
        **per_source,
    }


def rarity_report(adapter=None, languages=("EN", "JP", "CN-S", "CN-T")):
    """What rarity strings each tcgdex dataset ACTUALLY contains.

    THE STEP THAT SHOULD HAVE COME FIRST. `rarity` is absent from tcgdex's
    brief card object, the catalog filtered on it anyway, and 8,313 cards
    produced zero matches. The fix is not a better filter -- it is asking the
    service what is in there before filtering on it.

    `interfaces.d.ts` documents 43 rarity strings and says the vocabulary is
    still being aligned to official lists, so the DOCUMENTED list and the
    POPULATED list are different questions. This answers the second one, and
    diffs each language against English.

    Cannot be run from the sandbox: the egress proxy refuses api.tcgdex.net.
    It runs on the Actions runner, like the coverage report.
    """
    from ingest.catalog_sources import TcgdexAdapter
    from ingest.rarity import TCGDEX_RARITIES, band_of, normalise

    adapter = adapter or TcgdexAdapter()
    found, errors = {}, {}
    for language in languages:
        try:
            found[language] = sorted(set(adapter.rarities(language)))
        except (AdapterGaveUp, RateLimited) as exc:
            errors[language] = str(exc)[:200]
        except Exception as exc:                            # noqa: BLE001
            errors[language] = f"{type(exc).__name__}: {exc}"[:200]

    known = {normalise(r) for r in TCGDEX_RARITIES}
    english = set(found.get("EN", []))
    rows = []
    for language, values in found.items():
        missing_here = sorted(english - set(values)) if language != "EN" else []
        extra_here = sorted(set(values) - english) if language != "EN" else []
        unknown = sorted(v for v in values if normalise(v) not in known)
        rows.append({
            "language": language, "count": len(values), "values": values,
            "absent_vs_english": missing_here, "extra_vs_english": extra_here,
            "not_in_our_enum": unknown,
            "tracked": sorted(v for v in values
                              if band_of(v) in ("chase", "premium")),
        })
    return {"rows": rows, "errors": errors,
            "enum_size": len(TCGDEX_RARITIES)}


def render_rarity_report(report) -> str:
    lines = ["### tcgdex rarities, as populated", "",
             f"Our enum carries {report['enum_size']} strings, verbatim from "
             "`tcgdex/cards-database/interfaces.d.ts`. This is what the live "
             "datasets actually contain -- the documented list and the "
             "populated list are different questions, and filtering on the "
             "first cost 8,313 cards.", ""]
    if not report["rows"]:
        lines += ["**No language answered.** The diff below is unavailable; "
                  "the errors are the finding.", ""]
    else:
        lines += ["| Language | Distinct rarities | Tracked (chase+premium) | "
                  "Absent vs EN | Extra vs EN | Not in our enum |",
                  "|---|---:|---:|---:|---:|---|"]
        for row in report["rows"]:
            lines.append(
                f"| `{row['language']}` | {row['count']} | "
                f"{len(row['tracked'])} | {len(row['absent_vs_english'])} | "
                f"{len(row['extra_vs_english'])} | "
                + (", ".join(f"`{v}`" for v in row["not_in_our_enum"]) or "--")
                + " |")
        for row in report["rows"]:
            if row["extra_vs_english"] or row["not_in_our_enum"]:
                lines += ["", f"**`{row['language']}` divergence.**"]
                if row["extra_vs_english"]:
                    lines.append("- present here and not in English: "
                                 + ", ".join(f"`{v}`" for v in
                                             row["extra_vs_english"]))
                if row["not_in_our_enum"]:
                    lines.append("- NOT in our enum, so classified `unknown` "
                                 "and still tracked: "
                                 + ", ".join(f"`{v}`" for v in
                                             row["not_in_our_enum"]))
    if report["errors"]:
        lines += ["", "**Languages that did not answer:**", ""]
        lines += [f"- `{lang}` -- {why}"
                  for lang, why in sorted(report["errors"].items())]
    return "\n".join(lines) + "\n"


def render_catalog_summary(targets, builder=None) -> str:
    """The catalog step's own report: what it asked, and what it got.

    WHY THIS IS PYTHON AND NOT A SHELL BLOCK. Run #7's catalog step wrote
    nothing to the job summary at all. The step was present and correctly
    ordered; it ran, found zero cards, and returned 1 -- and GitHub runs
    `bash -e`, so the script aborted on that exit code and the `{ ... } >>
    $GITHUB_STEP_SUMMARY` block that would have explained the zero never
    executed. `continue-on-error` then hid the failed step.

    A step that produces the input for everything downstream and reports
    nothing is the same invisibility `no_targets` exists to prevent, one layer
    up. So the report is built here, it is written BEFORE the exit code is
    returned, and no exit code can suppress it.
    """
    counts = targets.get("_counts", {})
    statuses = targets.get("_combo_status", {})
    routes = targets.get("_routing", {})
    lines = ["### Catalog -> targets", ""]

    total = sum(counts.values())
    if total:
        lines += [f"**{total} cards tracked across "
                  f"{sum(1 for c in counts.values() if c)} combinations.**", ""]
    else:
        lines += ["**ZERO cards tracked.** Every price source will report "
                  "`no_targets` and the run will fail. The per-combo status "
                  "below is the diagnosis.", ""]

    lines += ["| Combo | Cards | Status | Catalog source | Prices routed to |",
              "|---|---:|---|---|---|"]
    for combo in sorted(set(counts) | set(statuses) | set(routes)):
        entry = statuses.get(combo, {})
        status = entry.get("status", "not attempted")
        sources = ", ".join(entry.get("sources") or []) or "--"
        routed = ", ".join(f"{name} ({n})"
                           for name, n in sorted(routes.get(combo, {}).items())) or "--"
        lines.append(f"| `{combo}` | {counts.get(combo, 0)} | {status} | "
                     f"{sources} | {routed} |")

    if builder is not None:
        lines += ["", "**Endpoints that answered.** These were never verified "
                  "against the live service before run #8 -- probe/COVERAGE.md "
                  "records a 200 only from tcgapi `/v1/games` and `/v1/search`, "
                  "so the set and card endpoints below were discovered, not "
                  "assumed:", ""]
        if builder.endpoints_used:
            lines += [f"- `{name}` -> `{url}`"
                      for name, url in sorted(builder.endpoints_used.items())]
        else:
            lines += ["- NONE. No candidate URL answered, which is why the "
                      "catalog is empty. The gaps below name what was tried."]

        calls = {"tcgapi": builder.tcgapi, "apitcg": builder.apitcg}
        lines += ["", "**Calls made by the catalog step** (separate accounting "
                  "from the ingest step, which reports its own):", ""]
        for name, adapter in calls.items():
            made = getattr(getattr(adapter, "quota", None),
                           "consumed_this_run", None)
            lines.append(f"- `{name}` -- "
                         + ("not called" if not made else f"{made} calls"))

    unmapped_rarities = targets.get("_unmapped_rarities") or {}
    if unmapped_rarities:
        lines += ["", "**Rarity strings no table classifies.** These are "
                  "TRACKED as `unknown`, not dropped -- but they are named "
                  "here because a rarity nobody has classified is a decision "
                  "waiting to be made, and `rarity_band` has now been wrong "
                  "three times by making it silently:", ""]
        for combo, values in sorted(unmapped_rarities.items()):
            lines.append(f"- `{combo}` -- "
                         + ", ".join(f"`{v}`" for v in sorted(values)))
        lines += ["", "Add them to `GAME_BANDS` in ingest/rarity.py, or "
                  "re-run `python tools/rarity_vocabulary.py` to refresh the "
                  "checked-in vocabulary."]

    gaps = targets.get("_gaps", [])
    if gaps:
        lines += ["", "**Gaps.** Each is a combination that produced nothing, "
                  "and why:", "", "| Combo | Reason | Detail |", "|---|---|---|"]
        for gap in gaps:
            detail = str(gap.get("detail", "")).replace("|", "\\|")[:160]
            lines.append(f"| `{gap['combo']}` | {gap['reason']} | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="build ingest/targets.json")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--out", default=TARGETS)
    parser.add_argument("--combos", default="all")
    parser.add_argument("--summary", default=None,
                        help="append a Markdown report here "
                             "(GITHUB_STEP_SUMMARY). Written BEFORE the exit "
                             "code, so a zero-target run still explains itself")
    parser.add_argument("--rarities", action="store_true",
                        help="ask tcgdex which rarity strings each dataset "
                             "actually contains, and diff each language "
                             "against English. Runs on the Actions runner")
    parser.add_argument("--coverage", action="store_true",
                        help="measure what the open Chinese sources actually "
                             "serve, per combo, and report it without building")
    args = parser.parse_args(argv)

    combos = COMBOS
    if args.combos != "all":
        wanted = set(args.combos.split(","))
        combos = [c for c in COMBOS if f"{c[0]}:{c[1]}" in wanted]

    builder = CatalogBuilder()

    if args.rarities:
        report = rarity_report()
        text = render_rarity_report(report)
        print(text)
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as handle:
                handle.write(text)
        # Reporting zero is a finding, not a failure. Same rule as --coverage.
        return 0

    if args.coverage:
        rows = builder.coverage([c for c in combos if c[1] in ("CN-S", "CN-T")])
        print(f"{'source':12} {'combo':14} {'claims':>7} {'reached':>8} "
              f"{'cards':>6}  detail")
        for row in rows:
            reached = {True: "yes", False: "NO", None: "-"}[row["reachable"]]
            print(f"{row['source']:12} {row['combo']:14} "
                  f"{'yes' if row['claimed'] else '-':>7} {reached:>8} "
                  f"{row['cards']:>6}  {row['detail'][:80]}")
        served = {r["combo"] for r in rows if r["cards"]}
        unserved = sorted({r["combo"] for r in rows} - served)
        print(f"\ncovered: {sorted(served) or 'none'}")
        print(f"NOT covered by any open source: {unserved or 'none'}")
        # Zero coverage is the honest answer when it is the true one, so this
        # does not fail. The report IS the deliverable.
        return 0
    catalog = builder.build(combos)
    targets = to_targets(catalog, builder.gaps, builder.combo_status,
                         builder.endpoints_used,
                         {k: sorted(v)
                          for k, v in builder.unmapped_rarities.items()})

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

    # BEFORE the exit code, always. Run #7's summary block sat after a command
    # that returned 1 under `bash -e`, so the step aborted and the one report
    # that could have explained the zero never ran. Nothing downstream of this
    # line may be able to prevent it.
    summary = render_catalog_summary(targets, builder)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(summary)
    print("\n" + summary)

    # Zero everywhere means the daily run would fail its zero-rows gate, and
    # the reason is here rather than there.
    return 0 if total else 1


if __name__ == "__main__":
    sys.exit(main())
