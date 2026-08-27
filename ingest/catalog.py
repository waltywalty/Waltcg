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
from resolve.identity import (RIFTBOUND_SET_ALIASES,              # noqa: E402
                              RIFTBOUND_SETS, TCGAPI_GAME_ID,
                              TCGAPI_GAME_SLUG, TCGAPI_KNOWN_SLUGS,
                              CannotBridge, card_uid, normalise_name,
                              parse_collector_number, printed_from_bare,
                              variant_from_external_id,
                              variant_from_number, variant_from_rarity)
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
from ingest.rarity import (NUMBER_DEPENDENT_GAMES,  # noqa: E402
                           TRACKED_BANDS, UNKNOWN, band_of,
                           deliberately_unknown, string_band)

# apitcg has no language dimension, so it can only fill a combo whose language
# it actually serves. One Piece JP is its one genuine addition over tcgapi.
APITCG_LANGUAGES = {"optcg": ("EN", "JP"), "pkmn": ("EN",), "riftbound": ("EN",)}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


# How long a combination's catalog stays good. Sets release monthly, not
# hourly, so re-enumerating every combination every day spends the whole
# provider budget re-deriving yesterday's answer -- which is exactly what left
# run #11 with nothing when apitcg started refusing.
#
# Seven days is a starting point, not a measurement. The cost of being wrong is
# asymmetric and cheap in one direction: a set that dropped mid-week is missed
# until the refresh, and `--force` exists for the day a set drops.
DEFAULT_MAX_AGE_DAYS = 7


def load_cached_catalog(path=TARGETS) -> dict:
    """Yesterday's catalog, per combination, out of the committed targets file.

    Reconstructed from the per-source card lists rather than stored a second
    time: every target row already carries its own `game` and `language`, so
    the grouping is derivable and a duplicate copy would be one more thing that
    can disagree with itself.

    Returns {combo: {"cards": [...], "as_of": iso, "served_by": [...]}}.
    A missing or unreadable file is an empty cache, never an error -- the first
    run has no cache and that is not a fault.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}

    meta = raw.get("_catalog_cache") or {}
    by_combo: dict = {}
    seen: dict = {}
    for key, value in raw.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        for card in value.get("cards") or []:
            if not isinstance(card, dict):
                continue
            game, language = card.get("game"), card.get("language")
            uid = card.get("card_uid")
            if not (game and language and uid):
                continue
            combo = f"{game}:{language}"
            if uid in seen.setdefault(combo, set()):
                continue
            seen[combo].add(uid)
            by_combo.setdefault(combo, []).append(card)

    out = {}
    for combo in set(by_combo) | set(meta):
        entry = meta.get(combo) or {}
        out[combo] = {
            "cards": by_combo.get(combo, []),
            "as_of": entry.get("as_of"),
            "served_by": entry.get("served_by") or [],
            "primary": entry.get("primary"),
        }
    return out


def cache_age_days(entry, now=None):
    """Age in days, or None when the entry does not say when it was built.

    None is not zero. A cache with no `as_of` is a cache of unknown age, and
    treating unknown as fresh is how a stale catalog starts looking like a
    fresh one -- which is the one thing this whole mechanism must not do.
    """
    stamp = (entry or {}).get("as_of")
    if not stamp:
        return None
    text = str(stamp).rstrip("Z")
    try:
        when = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return max((( now or _now()) - when).total_seconds() / 86400.0, 0.0)


# What the cache had to say about a combination, at the moment the decision to
# call a provider was taken. SIX answers, because "--" in an age column was
# collapsing them into one and only one of them is a fault:
#
#   absent      no entry at all. First run, or a combination that has never
#               produced a card. Correct to enumerate.
#   empty       an entry with no cards. Same verdict, different history: we
#               have asked before and got nothing.
#   undated     cards, but no as_of. A cache of UNKNOWN age, which can never
#               satisfy a freshness test -- correct to enumerate, and worth
#               naming, because it means something wrote a stamp-less entry.
#   stale       cards and a date, past the threshold. Correct to enumerate.
#               This is the ordinary weekly refresh.
#   forced      cards and a date, INSIDE the threshold, re-enumerated because
#               --force was passed. Correct, and deliberate.
#   fresh       cards and a date, inside the threshold. Served from cache.
#
# A combination that reports `fresh` and was enumerated anyway is the seventh
# case and it is the bug -- `refreshed_despite_fresh`, raised in the summary
# rather than left to be inferred from a blank column.
CACHE_STATES = ("absent", "empty", "undated", "stale", "forced", "fresh")


def cache_state(cached, age, max_age_days, force=False) -> str:
    """Which of the six the cache was in for this combination."""
    if not cached:
        return "absent"
    if not cached.get("cards"):
        return "empty"
    if age is None:
        return "undated"
    if age >= max_age_days:
        return "stale"
    return "forced" if force else "fresh"


def primary_source(game, language) -> str:
    """Which source is SUPPOSED to serve this combination.

    Declared, not inferred from what happened, because the whole point is to
    notice when what happened differs. tcgdex carrying pkmn:EN is not the
    normal state of affairs -- it means apitcg was refused -- and a report that
    only names the source that answered cannot say so.
    """
    if language in APITCG_LANGUAGES.get(game, ()):
        return "apitcg"
    from ingest.catalog_sources import CATALOG_SOURCES
    for name in CN_SOURCE_PRIORITY:
        cls = CATALOG_SOURCES.get(name)
        if cls is not None and (game, language) in getattr(cls, "serves", ()):
            return name
    return ""


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
        # Rarity strings that ARE classified but whose card could not be
        # banded because its collector number would not parse. A NUMBER
        # problem, not a vocabulary problem, and reported separately -- a
        # `Showcase` in the unclassified list reads as "nobody has decided
        # what this word means", which is false and sends the reader to the
        # wrong file.
        self.unbandable_numbers = {}
        self.not_a_card = {}
        # Per combo, the count at every stage between fetch and target. Run #10
        # asked three separate "where did the cards go" questions that the
        # output could not answer; this is the answer.
        self.stages = {}
        # {set_code: official printed card count}, per language, harvested
        # while the catalogs are walked. The number bridge cannot derive a
        # printed number without it and must REFUSE where it is absent, so an
        # empty table is a real answer rather than a missing feature.
        self.set_totals = {}

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

    def live_open_sources(self):
        """The priority order, minus anything sources.yml has superseded.

        Read from sources.yml rather than hardcoded here so there is one place
        that says a source is retired. A superseded source left in the rotation
        spends a request every run proving a known-wrong endpoint is still
        wrong, and files the answer as a gap that reads like missing data.
        """
        expectations = load_expectations()
        return [name for name in CN_SOURCE_PRIORITY
                if not expectations.get(name, {}).get("superseded_by")]

    def open_catalog_fallback(self, game, language):
        """First open source that lists cards for this combo, in priority order.

        Returns (rows, {"used": [...], "failed": [(source, why), ...]}).
        Stops at the first source that delivers -- the others are alternatives,
        not supplements, and merging two catalogs that disagree about a number
        would manufacture cards neither of them lists.
        """
        rows, used, failed = [], [], []
        for name in self.live_open_sources():
            adapter = self.cn_source(name)
            if not adapter.can_enumerate:
                # Not asked. A capability statement, not a failure.
                failed.append((f"{name}_does_not_enumerate",
                               adapter.cannot_enumerate_because))
                continue
            if (game, language) not in adapter.serves:
                failed.append((f"{name}_does_not_serve",
                               f"{name} does not serve {game}:{language}"))
                continue
            self.attempt((game, language), name)
            try:
                found = adapter.enumerate_combo(game, language)
            except RateLimited as exc:
                # Refused, not broken. Also: stop asking this source for the
                # rest of the run -- the adapter's own breaker has tripped and
                # every further combo would spend a call to be told the same
                # thing.
                failed.append((f"{name}_rate_limited", str(exc)[:200]))
                continue
            except AdapterGaveUp as exc:
                # ASKED AND DID NOT ANSWER. The only one of the four that is
                # genuinely `source_unreachable`; the others used to share the
                # `_no_cards` reason and were all classified as unreachable,
                # which made "we asked and it had nothing" look like a broken
                # endpoint.
                failed.append((f"{name}_unreachable", str(exc)[:200]))
                continue
            # What the adapter itself threw away, before we ever see a row.
            # Without this the summary can only count survivors, and "fetched
            # 7,436 and dropped 7,436 for want of a set code" is indis-
            # tinguishable from "fetched nothing".
            try:
                found_totals = adapter.set_totals(language)
            except (AdapterGaveUp, RateLimited, AttributeError):
                found_totals = {}
            if found_totals:
                self.set_totals.setdefault(language, {}).update(found_totals)
            self.stage(game, language, "provider_hits",
                       getattr(adapter, "hits_seen", 0))
            self.stage(game, language, "dropped_no_identity",
                       getattr(adapter, "dropped_no_identity", 0))
            for origin, count in (getattr(adapter, "rarity_origins", None)
                                  or {}).items():
                self.stage(game, language, f"rarity_{origin}", count)
            kept = [r for r in (self._cn_row(game, language, hit)
                                for hit in found) if r]
            if kept:
                rows, used = kept, [name]
                break
            failed.append((f"{name}_empty",
                           "reachable, but no card in a tracked rarity band "
                           "for this combination"))
        return rows, {"used": used, "failed": failed}

    def _cn_row(self, game, language, hit):
        """An open-source row -> a targets row, filtered to tracked bands.

        `band_of`, not `rarity_band`: an absent rarity must classify as
        `unknown` and stay tracked. `rarity_band(None)` returns `base`, which
        is the substitution that produced 8,313 cards and zero matches.
        """
        self.stage(game, language, "fetched")
        self.note_rarity(game, language, hit.get("rarity"))
        number = hit.get("number")
        set_code = hit.get("set_code")
        if not number:
            self.stage(game, language, "dropped_no_number")
            return None
        if not set_code:
            self.stage(game, language, "dropped_no_set_code")
            return None
        self.stage(game, language, "parsed")

        size = self.set_size(game, set_code)
        if (game in NUMBER_DEPENDENT_GAMES
                and parse_collector_number(number).kind == "unreadable"):
            self.stage(game, language, "unreadable_number")
            self.note_unbandable(game, language, hit.get("rarity"), number)
        band = band_of(hit.get("rarity"), game=game, number=number,
                       set_size=size)
        self.stage(game, language, f"band_{band}")
        if band not in TRACKED_BANDS:
            return None
        self.stage(game, language, "tracked")
        return {"card_uid": hit["card_uid"], "game": game, "language": language,
                "set_code": hit["set_code"], "number": hit["number"],
                "variant": hit["variant"],
                "name": hit.get("name_jp") or hit.get("name_en") or "",
                "rarity": hit.get("rarity"),
                "rarity_from": hit.get("rarity_from"),
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

    def build(self, combos=COMBOS, cache=None,
              max_age_days=DEFAULT_MAX_AGE_DAYS, force=False, now=None):
        """Two catalog sources, in order: apitcg, then the open ones.

        TCGAPI IS NOT ONE OF THEM ANY MORE. Run #9 settled it: apitcg made 250
        calls and supplied every combination it serves, tcgapi made 1 and hit
        0/100. A source that contributes nothing to the catalog should not be
        able to fail the run on catalog quota, and burning its 100 daily calls
        here left none for the price rotation, where they buy something.
        See ingest/sources.yml -- tcgapi is `role: price` now.
        """
        cache = {} if cache is None else cache
        now = now or _now()
        catalog = {}
        for game, language in combos:
            combo = f"{game}:{language}"
            primary = primary_source(game, language)
            cached = cache.get(combo) or {}
            age = cache_age_days(cached, now)
            fresh = bool(cached.get("cards")) and age is not None \
                and age < max_age_days
            state = cache_state(cached, age, max_age_days, force)

            # SERVED FROM YESTERDAY, AND NO PROVIDER IS CALLED AT ALL. This is
            # the point of the cache: a throttled provider costs nothing,
            # because the answer we already have is still the answer. The
            # status can never be `ok` -- a cached catalog and a fresh one are
            # different facts even when the cards are identical.
            if fresh and not force:
                cards = list(cached["cards"])
                catalog[combo] = {"sources": list(cached.get("served_by") or []),
                                  "cards": cards}
                self.combo_status[combo] = {
                    "status": "catalog_from_cache", "cards": len(cards),
                    "sources": list(cached.get("served_by") or []),
                    "asked": [], "reasons": [],
                    "primary": primary, "age_days": round(age, 2),
                    "cache_max_age_days": max_age_days,
                    "cache_state": state,
                }
                self.log.append(
                    f"{combo}: served from cache, {age:.1f}d old "
                    f"(threshold {max_age_days}d); no provider called")
                continue

            rows, sources = [], []
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
                # A 429 is an ANSWER. Filing it as `unreachable` sends the
                # next session hunting for a broken endpoint that works fine,
                # and hides the one fact that matters: this is fixable by
                # waiting, and by not asking again tomorrow.
                kind = ("apitcg_rate_limited" if isinstance(exc, RateLimited)
                        else "apitcg_unreachable")
                self.gap((game, language), kind, str(exc)[:200])

            # ANY combination still empty falls through to the open sources.
            #
            # This used to be gated to CN-S and CN-T, and that gate was a bug
            # with a name: pkmn:JP reported `no_catalog_source` while tcgdex
            # was serving Japanese the whole time. apitcg's pokemon slug is
            # English-only, tcgdex was not REGISTERED for Japanese, and the
            # fallback that would have caught it only fired for Chinese. Three
            # separate things, all pointing the same way, and the output said
            # "nothing serves this" rather than "we did not look".
            if not rows:
                rows, tried = self.open_catalog_fallback(game, language)
                sources.extend(tried["used"])
                for src, why in tried["failed"]:
                    self.gap((game, language), f"{src}_no_cards", why)

            deduped = {r["card_uid"]: r for r in rows}
            reasons = [g["reason"] for g in self.gaps if g["combo"] == combo]
            asked = sorted(self.attempted.get(combo, ()))
            # ONLY genuine unreachability. `_empty`, `_does_not_serve` and
            # `_does_not_enumerate` are different answers and lumping them in
            # here reported "we asked and it had nothing" as a broken endpoint.
            unreachable = [r for r in reasons if "unreachable" in r]
            limited = [r for r in reasons if "rate_limited" in r]
            if deduped and primary and primary not in sources:
                # CARDS, BUT NOT FROM THE SOURCE THAT SHOULD HAVE SUPPLIED
                # THEM. Run #11 read `tcgdex` against pkmn:EN and that looked
                # like ordinary operation; it meant apitcg had been refused and
                # the fallback caught it. The fallback working is good news and
                # it is still news.
                status = "ok_via_fallback"
            elif deduped:
                status = "ok"
            elif cached.get("cards"):
                # NOTHING CAME BACK, BUT WE HAVE YESTERDAY'S. Serve it -- that
                # is what it is for -- and say loudly that it is past its
                # threshold, so a stale catalog can never pass for a fresh one.
                status = "catalog_from_cache_stale"
                cards = list(cached["cards"])
                self.combo_status[combo] = {
                    "status": status, "cards": len(cards),
                    "sources": list(cached.get("served_by") or []),
                    "asked": asked, "reasons": sorted(set(reasons)),
                    "primary": primary,
                    "age_days": None if age is None else round(age, 2),
                    "cache_max_age_days": max_age_days,
                    "cache_state": state,
                    "refresh_failed": True,
                }
                catalog[combo] = {
                    "sources": list(cached.get("served_by") or []),
                    "cards": cards,
                }
                self.log.append(
                    f"{combo}: refresh failed; serving the cached catalog "
                    + (f"({age:.1f}d old)" if age is not None
                       else "(age unknown)"))
                continue
            elif limited:
                # THE PROVIDER ANSWERED, AND SAID NOT NOW. Fixable by waiting,
                # which `source_unreachable` is not, and the two must not share
                # a row -- one sends you to the code and the other sends you to
                # bed.
                status = "rate_limited"
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
                "primary": primary,
                "as_of": now.isoformat() + "Z",
                # WHY THIS COMBINATION WAS RE-ENUMERATED. An empty age column
                # collapsed three different answers into one dash, and only
                # one of the three is a fault -- see `cache_state`.
                "cache_state": state,
                "age_days": None if age is None else round(age, 2),
                "cache_max_age_days": max_age_days,
            }
            catalog[combo] = {
                "sources": sources,
                "cards": sorted(deduped.values(), key=lambda r: r["card_uid"]),
            }
        return catalog

    def stage(self, game, language, name, count=1):
        self.stages.setdefault(f"{game}:{language}",
                               {}).setdefault(name, 0)
        self.stages[f"{game}:{language}"][name] += count

    def note_not_a_card(self, game, language, number, name):
        self.not_a_card.setdefault(f"{game}:{language}", []).append(
            {"number": str(number), "name": str(name or "")})

    def note_unbandable(self, game, language, rarity, number):
        self.unbandable_numbers.setdefault(f"{game}:{language}", []).append(
            {"rarity": str(rarity), "number": str(number)})

    def note_rarity(self, game, language, rarity):
        # The STRING question -- "does any table know this word?" -- which is
        # different from what band a given card is in. For a number-dependent
        # game the string alone genuinely cannot answer the second.
        #
        # A string the table maps to UNKNOWN ON PURPOSE is classified: it
        # classifies as "the word cannot say". `Showcase` and `Promo` are both
        # that, and reporting them as unclassified sent the reader to the
        # vocabulary when the problem was the number.
        if rarity in (None, "") or deliberately_unknown(rarity, game):
            return
        if string_band(rarity, game) == UNKNOWN:
            self.unmapped_rarities.setdefault(
                f"{game}:{language}", set()).add(str(rarity))

    def set_size(self, game, set_code):
        """Base card count, for deciding whether a number is above the set.

        The lookup was broken and silently so: `RIFTBOUND_SETS` is keyed by
        printed set code (`OGN`, `SFD`) and apitcg returns SLUGS (`origins`,
        `spiritforged`), so every riftbound card got `None` and no bare number
        could ever be placed. `RIFTBOUND_SET_ALIASES` maps them.

        `None` is still a real answer -- `above_set_size` returns None rather
        than False when the ceiling is unknown, so an unknown ceiling cannot
        file a Signature as an ordinary card.
        """
        if game != "riftbound":
            return None
        key = str(set_code or "").strip()
        code = RIFTBOUND_SET_ALIASES.get(key.lower(), key.upper())
        return (RIFTBOUND_SETS.get(code) or {}).get("base")

    def _row(self, game, language, set_code, hit, source):
        combo = (game, language)
        self.stage(game, language, "fetched")
        rarity = find(hit, "rarity")
        number = str(find(hit, "number", "collector_number", "code") or "").strip()
        self.note_rarity(game, language, rarity)
        if not number:
            # No number means no card_uid -- identity, not banding. It has to
            # be dropped and it has to be COUNTED, because "we could not
            # identify it" and "it was not worth tracking" are different facts
            # and only one of them is a decision.
            self.stage(game, language, "dropped_no_number")
            return None
        if not set_code:
            self.stage(game, language, "dropped_no_set_code")
            return None
        if _is_sealed_product(hit):
            # NOT A CARD PRINTING. `Origins - Booster Display Case` has a
            # number, a set and no card_uid worth having, and it was becoming
            # a price target on the strength of "absent rarity is unknown and
            # unknown is tracked" -- a rule about CARDS, applied to a box.
            #
            # The test is narrow on purpose: the provider's own card-type field
            # must be PRESENT AND NULL, alongside a null rarity. A payload that
            # omits the field entirely says nothing, and reading silence as
            # "not a card" would delete every tcgdex brief and every Chinese
            # card waiting on the English fallback. Counted, never silent.
            self.stage(game, language, "dropped_not_a_card")
            self.note_not_a_card(game, language, number, find(hit, "name"))
            return None
        self.stage(game, language, "parsed")
        # An absent rarity is UNKNOWN and TRACKED, never `base`. Counting it
        # separately is how we can tell "this provider omits rarity" from
        # "these cards are commons".
        self.stage(game, language,
                   "rarity_self" if rarity not in (None, "") else "rarity_absent")

        size = self.set_size(game, set_code)
        if (game in NUMBER_DEPENDENT_GAMES
                and parse_collector_number(number).kind == "unreadable"):
            # Banded UNKNOWN by `band_of`, which is TRACKED -- never dropped.
            # Counted and sampled so the summary can say what those numbers
            # looked like rather than leaving it to be asked again.
            self.stage(game, language, "unreadable_number")
            self.note_unbandable(game, language, rarity, number)
        # `game=` first: `R`, `P` and `L` mean different things per game, so
        # one shared table would have to pick, and picking is guessing. And
        # `number=` because for Riftbound the band IS the number -- `Showcase`
        # alone spans $40 to $3,090.
        band = band_of(rarity, game=game, number=number, set_size=size)
        self.stage(game, language, f"band_{band}")
        if band not in TRACKED_BANDS:
            return None
        name = find(hit, "name") or ""
        external_id = str(find(hit, "id", "card_id") or "")
        # NUMBER FIRST, then the publisher's own id, then the rarity string --
        # most reliable to least. `299*/298` is a Signature that apitcg calls
        # `Alternate Art`; `EB01-006_p1` is a parallel that apitcg calls `SR`,
        # exactly like the base card it would otherwise merge into.
        variant = (variant_from_number(number, size, game)
                   or variant_from_external_id(external_id, game)
                   or _variant_of(rarity, name, language, game))
        try:
            uid = card_uid(game, set_code, number, variant, language)
        except (ValueError, KeyError):
            self.stage(game, language, "dropped_bad_uid")
            return None
        self.stage(game, language, "tracked")
        return {"card_uid": uid, "game": game, "language": language,
                "set_code": set_code, "number": number, "variant": variant,
                "name": name, "rarity": rarity,
                "external_id": external_id,
                "source": source}


# Card-type fields, in the spellings the providers actually use.
_TYPE_KEYS = ("cardType", "card_type", "type")


def _is_sealed_product(hit) -> bool:
    """Sealed product masquerading as a card.

    apitcg's Riftbound set lists carry booster packs, display cases, champion
    decks and bulk rune bags alongside the cards, with a collector number and
    a set like everything else. They are marked by the provider: `cardType`
    is present and null, and so is `rarity`.

    PRESENT AND NULL is the whole test. A payload that does not carry the
    field at all -- every tcgdex brief, every Pokemon row in apitcg -- is
    saying nothing about card-ness, and treating silence as a verdict would
    delete the entire Pokemon catalog.
    """
    if not isinstance(hit, dict):
        return False
    present = [k for k in _TYPE_KEYS if k in hit]
    if not present:
        return False
    return (all(hit[k] in (None, "") for k in present)
            and hit.get("rarity") in (None, ""))


def bridge_numbers(catalog, set_totals):
    """The provider's bare `localId` -> the number PRINTED on the card.

    THE GAP THIS CLOSES. `printed_from_bare` has existed and been tested for
    several sessions; `_set_totals` has been collected from every adapter and
    written into `targets.json` for as long. Nothing joined them. So the
    catalog built `pkmn:swsh10.5:011:base:EN` from tcgdex's bare `11` while
    the card says `011/078` and the labelled row says `011/078` -- two uids
    for one card, and the price lands on the one nothing else refers to.
    Measured against the labelled set before the fix: of the five rows where
    the catalog and the labels both spoke, five disagreed, and four of the
    five disagreed on the number alone.

    A POST-PASS, NOT A STEP IN `_row`. Totals arrive per adapter, per
    language, while rows are being built -- so a row built before its set's
    total landed would silently stay bare, and which rows those were would
    depend on adapter ordering. And `preserve_from_cache` reinstates rows from
    the persisted catalog after the build, which a step inside `_row` never
    sees at all. Run once, over everything, when every total is known.

    THREE THINGS THIS REFUSES TO DO:

      * It never strips a denominator. `printed_from_bare` is one-directional
        for the reason its docstring gives, and this only ever adds.
      * It never bridges without a total. An unknown total leaves the row bare
        and COUNTED -- `no_set_total` in the report -- because a bare number
        that is honest about being bare can still be fixed later, and a
        defaulted one cannot.
      * IT NEVER MERGES. If bridging two rows lands them on one card_uid and
        they carry different names, both are left bare and the collision is
        reported. Bridging is a rename, and a rename that collides is exactly
        the merge non-negotiable 3 exists to prevent -- a silent one, arriving
        through a fix.

    Returns `(catalog, report)` with the catalog rebuilt, never mutated in
    place: `preserve_from_cache` and `_cache_stamps` both read the original.
    """
    bridged_catalog, report = {}, {}
    for combo, entry in (catalog or {}).items():
        counts = {"bridged": 0, "self_printed": 0, "no_set_total": 0,
                  "unreadable": 0, "refused_collision": 0}
        missing, rows = set(), []
        for card in entry.get("cards", []):
            # THE LANGUAGE COMES FROM THE CARD, not from the combo key.
            # Splitting `"pkmn:CN-S"` works and splitting `("pkmn", "CN-S")`
            # does not, and the failure would be a silent one -- every row
            # counted `no_set_total` and nothing bridged, which reads as a
            # provider gap rather than as a key-shape bug.
            totals = (set_totals or {}).get(card.get("language")) or {}
            number = str(card.get("number") or "")
            total = totals.get(card.get("set_code"))
            if parse_collector_number(number).total is not None:
                counts["self_printed"] += 1
                rows.append((card, card))
                continue
            if total in (None, ""):
                counts["no_set_total"] += 1
                missing.add(str(card.get("set_code")))
                rows.append((card, card))
                continue
            try:
                printed = printed_from_bare(number, total)
                uid = card_uid(card["game"], card["set_code"], printed,
                               card["variant"], card["language"])
            except (CannotBridge, KeyError, ValueError):
                # No index in the number, or a uid the builder would have
                # refused. Unreadable is TRACKED, never defaulted.
                counts["unreadable"] += 1
                rows.append((card, card))
                continue
            rows.append((card, dict(card, number=printed, card_uid=uid)))

        # THE MERGE CHECK, before anything is adopted. Grouped by the uid each
        # row WOULD take, so a collision between a bridged row and a row that
        # already carried its denominator is caught too.
        by_uid = {}
        for original, candidate in rows:
            by_uid.setdefault(candidate["card_uid"], []).append(
                (original, candidate))
        collisions = []
        final = []
        for uid, group in by_uid.items():
            names = {normalise_name(str(c.get("name") or ""))
                     for _o, c in group}
            if len(group) > 1 and len(names) > 1:
                collisions.append({"card_uid": uid,
                                   "names": sorted(names)[:4],
                                   "numbers": sorted(
                                       {str(o.get("number")) for o, _c in group})})
                for original, candidate in group:
                    if original is not candidate:
                        counts["refused_collision"] += 1
                    final.append(original)
                continue
            for original, candidate in group:
                if original is not candidate:
                    counts["bridged"] += 1
                final.append(candidate)

        deduped = {row["card_uid"]: row for row in final}
        bridged_catalog[combo] = dict(
            entry, cards=sorted(deduped.values(),
                                key=lambda r: r["card_uid"]))
        counts["sets_without_totals"] = sorted(missing)
        counts["collisions"] = collisions[:10]
        report[combo] = counts
    return bridged_catalog, report


def to_targets(catalog, gaps, combo_status=None, endpoints=None,
               unmapped_rarities=None, unbandable=None,
               stages=None, not_a_card=None, cache=None,
               set_totals=None):
    """The shape the daily runner reads. Card identities only -- no prices."""
    # BEFORE ANYTHING IS ROUTED. A target's card_uid is what the price lands
    # on, so the bridge has to run on the way out, not on the way in.
    catalog, number_bridge = bridge_numbers(catalog, set_totals)
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
        "_unbandable_numbers": unbandable or {},
        "_not_a_card": not_a_card or {},
        "_stages": stages or {},
        # Official printed card counts, per language and set. Card counts are
        # not card data -- no price, no population, no provider payload -- and
        # without them the number bridge has to refuse every comparison
        # between a bare provider number and a printed one.
        "_set_totals": set_totals or {},
        # WHAT THE TOTALS WERE ACTUALLY USED FOR, per combo. A bare number
        # that could not be bridged is `no_set_total` with its set named, not
        # a silently-bare uid; a bridge that would have merged two cards is
        # `refused_collision` with both names. The totals sat in this file for
        # sessions with nothing reading them, and a count of zero bridges
        # would have said so on the first run.
        "_number_bridge": number_bridge,
        # WHEN EACH COMBINATION'S CATALOG WAS ACTUALLY BUILT. The card lists
        # below are grouped by source for the runner; this is the same data
        # asked the other question, and it is what `load_cached_catalog` reads
        # next run to decide whether to spend a provider call at all.
        #
        # A combination served from cache carries FORWARD its original as_of,
        # never today's -- restamping it would make a stale catalog immortal,
        # refreshing its own timestamp every run without ever being rebuilt.
        "_catalog_cache": _cache_stamps(catalog, combo_status or {},
                                        cache or {}),
        "_gaps": gaps,
        "fx_alphavantage": {},
        **per_source,
    }


def _cache_stamps(catalog, combo_status, cache) -> dict:
    out = {}
    for combo in sorted(set(catalog) | set(combo_status)):
        entry = combo_status.get(combo, {})
        served = list((catalog.get(combo) or {}).get("sources")
                      or entry.get("sources") or [])
        cards = len((catalog.get(combo) or {}).get("cards") or [])
        if entry.get("status", "").startswith("catalog_from_cache"):
            as_of = (cache.get(combo) or {}).get("as_of")
        else:
            as_of = entry.get("as_of")
        if not cards:
            # Nothing to remember. Stamping an empty combination would let a
            # `no_catalog_source` -- or a combination whose provider refused --
            # sit unasked for a week behind a fresh-looking date, with no cards
            # to show for it. A zero is always worth re-checking, and there is
            # nothing to serve from cache anyway.
            continue
        out[combo] = {"as_of": as_of, "cards": cards, "served_by": served,
                      "primary": entry.get("primary")}
    return out


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


def _refreshed_despite_fresh(entry) -> bool:
    """A combination the cache could have served, enumerated anyway.

    The only cache state that is a FAULT rather than a fact. `--force` is
    reported as `forced` and is not this.
    """
    return (entry.get("cache_state") == "fresh"
            and not str(entry.get("status", "")).startswith("catalog_from_cache"))


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

    lines += ["| Combo | Cards | Status | Cache | Age | Expected | Served by "
              "| Prices routed to |",
              "|---|---:|---|---|---:|---|---|---|"]
    for combo in sorted(set(counts) | set(statuses) | set(routes)):
        entry = statuses.get(combo, {})
        status = entry.get("status", "not attempted")
        served = entry.get("sources") or []
        primary = entry.get("primary") or ""
        # WHICH SOURCE ACTUALLY SERVED THIS, against which one was supposed
        # to. `tcgdex` under pkmn:EN is not routine -- it means apitcg was
        # refused -- and a column that only names the answerer cannot say so.
        if served and primary and primary not in served:
            served_cell = ", ".join(f"**{s}**" for s in served) + " (fallback)"
        else:
            served_cell = ", ".join(served) or "--"
        age = entry.get("age_days")
        # AN EMPTY AGE MEANT THREE DIFFERENT THINGS and rendered as one dash:
        # no entry, an entry with no date, and an entry that was re-enumerated
        # anyway. Only the last is a fault. The cache column is the answer and
        # the age column is now only ever a number or a genuine "no date".
        age_cell = "no date" if age is None else f"{age:.1f}d"
        state = entry.get("cache_state")
        if state is None:
            cache_cell = "--"
            age_cell = "--"
        elif state in ("absent", "empty"):
            cache_cell = state
            age_cell = "--"
        else:
            cache_cell = state
        if _refreshed_despite_fresh(entry):
            cache_cell = "**fresh, REFRESHED ANYWAY**"
        routed = ", ".join(f"{name} ({n})"
                           for name, n in sorted(routes.get(combo, {}).items())) or "--"
        lines.append(f"| `{combo}` | {counts.get(combo, 0)} | {status} | "
                     f"{cache_cell} | {age_cell} | {primary or '--'} "
                     f"| {served_cell} | {routed} |")

    lines += ["", "`Cache` is what the persisted catalog had to say when the "
              "decision to call a provider was taken. `absent` no entry; "
              "`empty` an entry with no cards; `no date` cards with no "
              "`as_of`, which can never be fresh; `stale` past the threshold; "
              "`forced` inside it but `--force` was passed; `fresh` served "
              "without calling anything. Only a `fresh` combination that was "
              "enumerated anyway is a fault."]

    wrong = [c for c, e in sorted(statuses.items())
             if _refreshed_despite_fresh(e)]
    if wrong:
        lines += ["", "**BUG: enumerated a combination the cache could have "
                  "served.** The entry was present, dated, and inside the "
                  "threshold, and a provider was called anyway. That is the "
                  "one cache state that should be impossible, and it is spelt "
                  "out here rather than left to be inferred from a blank "
                  "column:", ""]
        lines += [f"- `{c}` -- {statuses[c].get('age_days')}d old against a "
                  f"{statuses[c].get('cache_max_age_days')}d threshold"
                  for c in wrong]

    undated = [c for c, e in sorted(statuses.items())
               if e.get("cache_state") == "undated"]
    if undated:
        lines += ["", "**Cached with no date.** These carry cards and no "
                  "`as_of`, so their age is unknowable and they are "
                  "re-enumerated every run -- correctly, because unknown age "
                  "must never satisfy a freshness test. It also means "
                  "something wrote a stamp-less entry, which is worth "
                  "finding: " + ", ".join(f"`{c}`" for c in undated)]

    fallbacks = [c for c, e in sorted(statuses.items())
                 if e.get("status") == "ok_via_fallback"]
    if fallbacks:
        lines += ["", "**Served by a fallback, not by the expected source.** "
                  "This is the fallback working, and it is still news: the "
                  "primary was asked and did not deliver. Read the reason "
                  "before treating the count as normal:", ""]
        for combo in fallbacks:
            entry = statuses[combo]
            why = ", ".join(r for r in entry.get("reasons") or []
                            if entry.get("primary", "") in r) or "see gaps below"
            lines.append(f"- `{combo}` -- expected `{entry.get('primary')}`, "
                         f"served by "
                         + ", ".join(f"`{s}`" for s in entry.get("sources") or [])
                         + f". {why}")

    cached = {c: e for c, e in sorted(statuses.items())
              if str(e.get("status", "")).startswith("catalog_from_cache")}
    if cached:
        lines += ["", "**Served from the persisted catalog.** Sets release "
                  "monthly, so a combination younger than its threshold is "
                  "not re-enumerated and costs no provider call at all. These "
                  "never read as `ok`, because a cached catalog and a fresh "
                  "one are different facts even when the cards are identical:",
                  "", "| Combo | Age | Threshold | Why |", "|---|---:|---:|---|"]
        for combo, entry in cached.items():
            age = entry.get("age_days")
            if entry.get("preserved"):
                why = ("PRODUCED NOTHING THIS RUN (`"
                       + str(entry.get("preserved_over") or "unknown")
                       + "`) -- yesterday's cards were kept rather than "
                         "committing the zero over them")
            elif entry.get("refresh_failed"):
                why = ("REFRESH FAILED -- this is past its threshold and is "
                       "being served anyway, which is what the cache is for")
            else:
                why = "within threshold; no provider called"
            lines.append(
                f"| `{combo}` | "
                + ("unknown" if age is None else f"{age:.1f}d")
                + f" | {entry.get('cache_max_age_days', '--')}d | {why} |")
        lines += ["", "Force a full re-enumeration with "
                  "`python -m ingest.catalog --write --force`."]

    limited = [c for c, e in sorted(statuses.items())
               if e.get("status") == "rate_limited"]
    if limited:
        lines += ["", "**Rate limited.** The provider ANSWERED, and the answer "
                  "was 'not now'. This is not `source_unreachable` and must "
                  "not be read as one -- there is nothing to fix in the code, "
                  "and the adapter stopped calling after its second refusal "
                  "rather than spending the run being told the same thing: "
                  "", ""]
        lines += [f"- `{c}`" for c in limited]
        lines += ["", "`config/rate_limits.yaml` is where the observed ceiling "
                  "accumulates. Add this run's numbers from the ingest step's "
                  "rate-limit table."]

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

    stages = targets.get("_stages") or {}
    if stages:
        # WHERE THE CARDS WENT, per combination. Run #10 asked three separate
        # versions of that question and the output could not answer any of
        # them: `no_tracked_cards` says a filter rejected everything, and says
        # nothing about whether the filter was even reached.
        order = ["provider_hits", "dropped_no_identity", "fetched",
                 "dropped_no_number", "dropped_no_set_code",
                 "dropped_not_a_card", "parsed", "unreadable_number",
                 "dropped_bad_uid", "tracked"]
        lines += ["", "**Where the cards went.** Counts at each stage between "
                  "fetch and target:", "",
                  "| Combo | " + " | ".join(order) + " | bands |",
                  "|---" * (len(order) + 2) + "|"]
        for combo, counts in sorted(stages.items()):
            bands = ", ".join(f"{k[5:]}={v}" for k, v in sorted(counts.items())
                              if k.startswith("band_")) or "--"
            cells = " | ".join(str(counts.get(k, 0)) for k in order)
            lines.append(f"| `{combo}` | {cells} | {bands} |")
        borrowed = {c: counts["rarity_en_fallback"]
                    for c, counts in stages.items()
                    if counts.get("rarity_en_fallback")}
        lines += ["", "**Rarity borrowed from the English card** "
                  "(`rarity_from: en_fallback`): "
                  + (", ".join(f"`{c}` {n}" for c, n in sorted(borrowed.items()))
                     if borrowed else
                     "NONE. Either no Chinese card needed it, or the English "
                     "index did not run.")]

    sealed = targets.get("_not_a_card") or {}
    if sealed:
        lines += ["", "**Not a card printing.** Booster packs, display cases "
                  "and champion decks arrive in the same set list as the "
                  "cards, with a collector number and no rarity. They were "
                  "being tracked, because absent-rarity-is-unknown-is-tracked "
                  "is a rule about CARDS and these are boxes. Dropped, and "
                  "listed here because a silent drop is how a real card would "
                  "one day leave by the same door:", ""]
        for combo, entries in sorted(sealed.items()):
            sample = ", ".join(f"`{e['name'] or e['number']}`"
                               for e in entries[:4])
            more = f" (+{len(entries) - 4} more)" if len(entries) > 4 else ""
            lines.append(f"- `{combo}` -- {len(entries)}: {sample}{more}")

    unbandable = targets.get("_unbandable_numbers") or {}
    if unbandable:
        lines += ["", "**Classified rarity, unreadable number.** These are a "
                  "NUMBER problem, not a vocabulary one: the rarity is a known "
                  "umbrella (`Showcase`, `Promo`) and the collector number "
                  "could not place it, so the card is `unknown` and TRACKED. "
                  "Listing them with the unclassified strings would send you "
                  "to the wrong file:", ""]
        for combo, entries in sorted(unbandable.items()):
            sample = ", ".join(f"`{e['rarity']}` at `{e['number']}`"
                               for e in entries[:5])
            more = f" (+{len(entries) - 5} more)" if len(entries) > 5 else ""
            lines.append(f"- `{combo}` -- {len(entries)}: {sample}{more}")

    gaps = targets.get("_gaps", [])
    if gaps:
        lines += ["", "**Gaps.** Each is a combination that produced nothing, "
                  "and why:", "", "| Combo | Reason | Detail |", "|---|---|---|"]
        for gap in gaps:
            detail = str(gap.get("detail", "")).replace("|", "\\|")[:160]
            lines.append(f"| `{gap['combo']}` | {gap['reason']} | {detail} |")
    return "\n".join(lines) + "\n"


def preserve_from_cache(catalog, combo_status, previous) -> list:
    """Put back any combination that came back EMPTY and had cards before.

    THE TRAP THIS CLOSES. The persist step is not gated on the run's exit code
    -- run #12 failed on a throttled apitcg and still committed the 2,673 cards
    the other three combinations produced, which is correct. But the file it
    commits is written from THIS run's catalog, and a combination that failed
    contributes zero cards to it. Committing that zero would erase yesterday's
    good answer for that combination, and the next run would re-enumerate it,
    and a provider having a bad morning would cost the catalog permanently.

    `build()` already falls back to the cache when a refresh fails -- but only
    when it was GIVEN a cache. This is the same rule applied at the file
    boundary, where it holds regardless: PRESERVATION and FRESHNESS are
    different questions, and `--no-cache` answers only the second.

    Zero is the failure signature, and only zero. A combination that comes back
    smaller has genuinely shrunk -- a set delisted, a rarity reclassified --
    and that must land.
    """
    restored = []
    for combo, entry in sorted((previous or {}).items()):
        cards = entry.get("cards") or []
        if not cards:
            continue
        if (catalog.get(combo) or {}).get("cards"):
            continue
        catalog[combo] = {"sources": list(entry.get("served_by") or []),
                          "cards": list(cards)}
        status = dict(combo_status.get(combo) or {})
        status.update({
            "status": "catalog_from_cache_preserved",
            "cards": len(cards),
            "sources": list(entry.get("served_by") or []),
            "preserved": True,
            # The reason it produced nothing is the interesting part and it is
            # kept: `rate_limited` preserved is a provider having a bad day,
            # `source_unreachable` preserved is a bug that has not surfaced yet
            # because the cache is hiding it.
            "preserved_over": (combo_status.get(combo) or {}).get("status"),
        })
        combo_status[combo] = status
        restored.append(combo)
    return restored


def persistable(path=TARGETS):
    """Is this targets file safe to commit as next run's catalog cache?

    THE FAILURE MODE THIS EXISTS FOR is worse than any it prevents. A run where
    every provider refused writes a targets file with zero cards; committing
    that would overwrite the cache with the emptiness, and tomorrow's run --
    which would have been fine, because yesterday's answer was still good --
    starts from nothing. One bad day would become permanent.

    So: commit only a file that is readable, carries cards, and stamps them.
    Anything else leaves the previous cache exactly where it is.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError as exc:
        return False, f"NOT PERSISTABLE: cannot read {path} ({exc})"
    except ValueError as exc:
        return False, f"NOT PERSISTABLE: {path} is not valid JSON ({exc})"
    if not isinstance(raw, dict):
        return False, f"NOT PERSISTABLE: {path} is not an object"

    counts = raw.get("_counts") or {}
    total = sum(v for v in counts.values() if isinstance(v, int))
    if total <= 0:
        return False, ("NOT PERSISTABLE: zero cards across every combination. "
                       "Committing this would overwrite the cache with the "
                       "emptiness and make one bad day permanent -- the "
                       "previous catalog stays exactly where it is.")
    stamps = raw.get("_catalog_cache") or {}
    undated = sorted(c for c, e in stamps.items()
                     if (e or {}).get("cards") and not (e or {}).get("as_of"))
    if undated:
        return False, ("NOT PERSISTABLE: these combinations carry cards with "
                       "no as_of, and a cache of unknown age reads as fresh "
                       "forever: " + ", ".join(undated))
    return True, (f"persistable: {total} cards across "
                  f"{sum(1 for v in counts.values() if v)} combinations, "
                  f"{len(stamps)} stamped")


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
    parser.add_argument("--force", action="store_true",
                        help="re-enumerate every combination, ignoring the "
                             "cached catalog. Use it the day a set drops")
    parser.add_argument("--max-age-days", type=float,
                        default=DEFAULT_MAX_AGE_DAYS,
                        help="re-enumerate a combination only when its cached "
                             f"catalog is older than this "
                             f"(default {DEFAULT_MAX_AGE_DAYS})")
    parser.add_argument("--persist-check", action="store_true",
                        help="is the written targets file safe to commit as "
                             "next run's cache? Exit 0 yes, 1 no, with the "
                             "reason on stdout. Nothing else -- no network")
    parser.add_argument("--no-cache", action="store_true",
                        help="do not READ the cache at all. Differs from "
                             "--force only in that --force still lets a failed "
                             "refresh fall back to yesterday's answer")
    args = parser.parse_args(argv)

    if args.persist_check:
        ok, why = persistable(args.out)
        print(why)
        return 0 if ok else 1

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
    # THE CATALOG IS READ BEFORE IT IS REBUILT. Sets release monthly; run #11
    # spent its entire apitcg budget re-deriving a catalog that had not changed
    # and ended with nothing when the provider started refusing.
    # TWO DIFFERENT QUESTIONS, and `--no-cache` only answers one of them.
    # `previous` is read unconditionally, because nothing justifies erasing a
    # combination that worked yesterday; `cache` is what freshness decisions
    # are allowed to consult, and that is what --no-cache suppresses.
    previous = load_cached_catalog(args.out)
    cache = {} if args.no_cache else previous
    catalog = builder.build(combos, cache=cache,
                            max_age_days=args.max_age_days, force=args.force)
    restored = preserve_from_cache(catalog, builder.combo_status, previous)
    for combo in restored:
        print(f"  PRESERVED {combo:14} produced nothing this run; kept "
              f"{len(catalog[combo]['cards'])} cards from the persisted "
              "catalog rather than committing the zero")
    targets = to_targets(catalog, builder.gaps, builder.combo_status,
                         builder.endpoints_used,
                         {k: sorted(v)
                          for k, v in builder.unmapped_rarities.items()},
                         builder.unbandable_numbers, builder.stages,
                         builder.not_a_card, cache=previous,
                         set_totals=builder.set_totals)

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
