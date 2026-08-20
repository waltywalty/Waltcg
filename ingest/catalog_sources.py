"""The three open catalog sources for the Chinese printings.

SEPARATE MODULE ON PURPOSE. Every adapter in here was written against
documentation and has never reached its live service, so this is the file most
likely to be wrong. Keeping it out of ingest/adapters.py means a broken import
here cannot take the five verified providers down with it -- ingest/registry.py
imports each module independently and records a failure as one source being
broken rather than as the run being over.

That is not hypothetical. Run #4 died in fifteen seconds, before any provider
ran, because of a single line these adapters were the first to reach.
"""

from __future__ import annotations

import urllib.parse
from typing import Optional

from .base import Adapter, AdapterGaveUp, RateLimited, Record, find
from .rarity import TRACKED_BANDS, band_of, resolve_rarity


# ---------------------------------------------------------------------------
# Catalog-only sources: the three Chinese printings
# ---------------------------------------------------------------------------
#
# These supply card IDENTITY and never a price, which is why they are a
# separate base. Until this session the three Chinese combos were recorded as
# having no catalog source at all; that was true of the five commercial
# providers and false of the open ecosystem.
#
# NONE OF THE ENDPOINT SHAPES BELOW HAVE BEEN EXERCISED against the live
# services. The sandbox this was written in cannot reach any of the three
# hosts -- the egress proxy answers 403 to CONNECT -- so every URL here is a
# candidate rather than a fact, and each adapter is built to DISCOVER which
# candidate answers rather than to assume. `verified = False` says so, and
# `ingest/sources.yml` marks them unverified so a wrong guess writes a loud gap
# instead of failing a run that four working providers completed.
#
# The honest headline: all three sources are POKÉMON. One Piece Simplified
# Chinese still has no catalog source, and calling these "the Chinese sources"
# would paper over that.


class CatalogSource(Adapter):
    """A source of card identity. Emits `card` records, never `price`."""

    # Combos this source is BELIEVED to serve. A claim from documentation, not
    # a measurement -- `coverage()` is the measurement, and the two are
    # reported side by side precisely so a claim that turns out to be false is
    # visible rather than absorbed.
    serves: tuple = ()
    verified = False
    can_enumerate = True

    def combos(self, requested=None):
        wanted = [tuple(c) if isinstance(c, (list, tuple)) else tuple(c.split(":"))
                  for c in (requested or [])]
        return [c for c in (wanted or list(self.serves))]

    def enumerate_combo(self, game, language) -> list[dict]:
        raise NotImplementedError

    def coverage(self, requested=None) -> list[dict]:
        """What this source ACTUALLY serves, per combo, measured now.

        Never raises: an unreachable source is a coverage finding, and a
        coverage report that dies on the first 404 reports nothing about the
        combos after it.
        """
        out = []
        for game, language in self.combos(requested):
            row = {"source": self.name, "combo": f"{game}:{language}",
                   "claimed": (game, language) in self.serves,
                   "reachable": False, "cards": 0, "detail": ""}
            if not self.can_enumerate:
                row["detail"] = self.cannot_enumerate_because
                out.append(row)
                continue
            try:
                cards = self.enumerate_combo(game, language)
                row["reachable"] = True
                row["cards"] = len(cards)
                if not cards:
                    row["detail"] = ("reached the source; it lists no cards for "
                                     "this combination")
            except (AdapterGaveUp, RateLimited) as exc:
                row["detail"] = str(exc)[:220]
            except Exception as exc:            # noqa: BLE001 - see docstring
                row["detail"] = f"{type(exc).__name__}: {exc}"[:220]
            out.append(row)
        return out

    def fetch(self, since=None, combos=None) -> list[Record]:
        observed = self._now()
        records = []
        for game, language in self.combos(combos):
            if not self.can_enumerate:
                continue
            for row in self.enumerate_combo(game, language):
                records.append(Record(kind="card", source=self.name,
                                      as_of=observed, observed_at=observed,
                                      payload=row))
        return records


class TcgdexAdapter(CatalogSource):
    """TCGdex -- open REST/GraphQL Pokémon database, no key, no quota published.

    First choice for the Chinese printings because it is the only one of the
    three with a documented multi-language model: language is a path segment,
    so `zh-tw` and `zh-cn` are the same API as `en`.

    COVERAGE IS CHECKED, NOT ASSUMED. Traditional Chinese is documented as
    partial and Simplified as in progress, and "the language exists as a path
    segment" is not the same claim as "this set is populated in it". The
    adapter reads the status endpoint first and, when the status payload does
    not enumerate languages, falls back to asking each language for its sets
    and believing the answer. A combo that comes back empty is recorded as
    reachable-but-empty, which is a different fact from unreachable.
    """

    name = "tcgdex"
    key_env = None
    host = "api.tcgdex.net"
    # Set by `enumerate_combo`; declared here so a caller that reads them
    # after a combo that raised gets 0 rather than AttributeError.
    hits_seen = 0
    dropped_no_identity = 0
    # ALL FOUR Pokemon printings, not just the Chinese ones. Declaring only
    # CN-S and CN-T was a routing bug that cost pkmn:JP its entire catalog:
    # `LANG` mapped JP to `ja` and the rarities report showed 17 distinct
    # Japanese rarities, so the data was there -- but `serves` did not say so,
    # apitcg's pokemon slug is English-only, and the fallback only fired for
    # Chinese. The combo reported `no_catalog_source`, which was false.
    serves = (("pkmn", "EN"), ("pkmn", "JP"),
              ("pkmn", "CN-T"), ("pkmn", "CN-S"))
    verified = True
    # Which of the three strategies actually ran. Reported, not assumed.
    strategy = None

    # Printings whose rarity comes from the ENGLISH card of the same id.
    #
    # PROMOTED FROM BACKSTOP TO PRIMARY ROUTE, 2026-08-17. Run #9 measured it:
    # CN-S carries 5 distinct rarities and CN-T 6, against English's 40, and
    # between them they produced ONE tracked card. The Chinese datasets are
    # thin rather than absent, so borrowing English's rarity is not the rare
    # exception it was written as -- it is how a Chinese card gets classified
    # at all. Registered as `chinese_rarity_from_english`.
    NEEDS_ENGLISH_RARITY = frozenset({"CN-S", "CN-T"})

    # The user gave `api.tcgdex.net/status`; the versioned form is the shape
    # every other endpoint takes. Both are tried rather than guessed between.
    STATUS_CANDIDATES = ("https://api.tcgdex.net/v2/status",
                         "https://api.tcgdex.net/status")

    # Ours -> TCGdex path segment. Exact, not guessed: `zh-cn` Simplified,
    # `zh-tw` Traditional.
    LANG = {"EN": "en", "JP": "ja", "CN-T": "zh-tw", "CN-S": "zh-cn"}

    # tcgdex's own pagination spelling. Not `page`/`limit`.
    PAGE = "pagination:page={page}&pagination:itemsPerPage={size}"
    PAGE_SIZE = 250

    def rarities(self, language) -> list:
        """The distinct rarity strings actually PRESENT in this dataset.

        The documented enum and the populated one are different questions --
        `interfaces.d.ts` lists 43 members and says the vocabulary is still
        being aligned to official lists. This is the empirical answer, and it
        is why the filter is not hardcoded against the enum.
        """
        code = self.LANG.get(language)
        if code is None:
            raise AdapterGaveUp(f"{self.name}: no path segment for {language}")
        payload = self.get(f"https://api.tcgdex.net/v2/{code}/rarities",
                           label=f"rarities-{code}", attempts=2)
        if isinstance(payload, list):
            return [str(x) for x in payload]
        return [str(x) for x in (find(payload, "data", "rarities") or [])]

    def cards_by_rarity(self, language, rarity):
        """Server-side filter: one request per rarity instead of per card.

        THE FILTER IS VERIFIED, NOT ASSUMED. `?{field}={value}` is documented
        to work on list endpoints even though the brief object omits the field,
        but a query parameter a service silently ignores returns the FULL list
        and looks exactly like a filter that matched everything. So the caller
        compares the filtered count against the unfiltered one -- see
        `filter_is_honoured`.
        """
        code = self.LANG[language]
        quoted = urllib.parse.quote(str(rarity))
        return self.get(
            f"https://api.tcgdex.net/v2/{code}/cards?rarity={quoted}&"
            + self.PAGE.format(page=1, size=self.PAGE_SIZE),
            label=f"cards-{code}-rarity", attempts=2)

    def filter_is_honoured(self, language) -> bool:
        """Does `?rarity=` actually filter, or is it being ignored?

        An ignored parameter returns everything, which reads as "every card in
        the language is a Special Illustration Rare" -- a filter that matched
        far too much rather than one that did not run. The check is that a
        filtered list is SHORTER than an unfiltered one, and it decides whether
        the N+1 fallback is needed at all.
        """
        code = self.LANG[language]
        try:
            # Probe with a rarity the dataset ACTUALLY contains. Hardcoding
            # one -- `Special illustration rare` was the obvious pick -- makes
            # the check report "filter ignored" for any dataset that happens
            # not to hold that rarity, and the punishment for that wrong answer
            # is 8,313 single-card fetches.
            present = [r for r in self.rarities(language)
                       if band_of(r) in TRACKED_BANDS]
            if not present:
                self.log.append(f"{self.name} {code} lists no trackable "
                                "rarity; nothing to filter on")
                return False
            everything = self.get(
                f"https://api.tcgdex.net/v2/{code}/cards?"
                + self.PAGE.format(page=1, size=self.PAGE_SIZE),
                label=f"cards-{code}-unfiltered", attempts=2)
            filtered = self.cards_by_rarity(language, present[0])
        except (AdapterGaveUp, RateLimited):
            return False
        whole = len(everything if isinstance(everything, list) else [])
        part = len(filtered if isinstance(filtered, list) else [])
        honoured = 0 < part < whole
        self.log.append(
            f"{self.name} {code} ?rarity= "
            + (f"HONOURED ({part} of {whole})" if honoured
               else f"IGNORED or empty ({part} vs {whole}) -- falling back"))
        return honoured

    def status(self) -> dict:
        url, payload = self.probe(self.STATUS_CANDIDATES, label="status")
        if url is None:
            raise AdapterGaveUp(
                f"{self.name}: no status endpoint answered. Tried "
                + "; ".join(f"{u} ({why})" for u, why in payload))
        return {"endpoint": url, "payload": payload}

    def live_languages(self) -> list[str]:
        """Language codes the service says it serves, from its own status.

        Returns [] when the status payload does not enumerate them -- an empty
        list means "status told us nothing", NOT "no languages", and the caller
        falls back to measuring rather than concluding.
        """
        try:
            payload = self.status()["payload"]
        except AdapterGaveUp:
            return []
        found = find(payload, "languages", "langs", "available_languages")
        if isinstance(found, dict):
            return sorted(str(k) for k in found)
        if isinstance(found, list):
            return sorted(str(x.get("code", x) if isinstance(x, dict) else x)
                          for x in found)
        return []

    def set_totals(self, language) -> dict:
        """{set_code: official card count} for one language.

        THE BRIDGE DEPENDS ON THIS. tcgdex sends bare `localId`s and the cards
        themselves are printed `199/165`; deriving one from the other needs the
        set's official count, and without it the comparison must refuse rather
        than fall back to matching on the index alone.

        `cardCount.official` is the printed denominator -- `total` includes
        secret rares and is NOT what the card says. Reading the wrong one would
        make every secret rare fail to bridge while looking like it worked.

        A set that publishes no official count is OMITTED, not defaulted. An
        absent entry makes the bridge refuse, which is the correct outcome; a
        guessed one makes it match the wrong card.
        """
        out = {}
        for entry in self.sets(language):
            if not isinstance(entry, dict):
                continue
            code = entry.get("id") or entry.get("code")
            counts = entry.get("cardCount") or entry.get("card_count") or {}
            official = (counts.get("official") if isinstance(counts, dict)
                        else None)
            if code and isinstance(official, int) and official > 0:
                out[str(code)] = official
        return out

    def sets(self, language) -> list:
        code = self.LANG.get(language)
        if code is None:
            raise AdapterGaveUp(f"{self.name}: no path segment for {language}")
        payload = self.get(f"https://api.tcgdex.net/v2/{code}/sets",
                           label=f"sets-{code}", attempts=2)
        return payload if isinstance(payload, list) else (
            find(payload, "data", "sets") or [])

    def english_index_cached(self) -> dict:
        """Built once per adapter, reused for both Chinese printings.

        Two Chinese combos borrowing from English would otherwise build the
        same index twice, and it is the most expensive call in the run.
        """
        if getattr(self, "_english", None) is None:
            self._english = self.english_index()
        return self._english

    def enumerate_combo(self, game, language, english_by_id=None) -> list[dict]:
        """Every card in the combination, WITH its rarity.

        The rarity is the whole point and the reason this used to return
        nothing usable. `GET /v2/{lang}/cards` and the `cards[]` array inside
        `GET /v2/{lang}/sets/{setId}` return only `id`, `localId`, `name` and
        `image` -- no `rarity` -- and the catalog filtered on it anyway. 8,313
        cards, zero matches.

        Three strategies, cheapest first, and the choice is MEASURED:

        1. `?rarity=` server-side, one request per rarity per language, but
           only if `filter_is_honoured` proves the parameter is not being
           ignored.
        2. GraphQL at /v2/graphql, one query per set, selecting the fields the
           brief object omits.
        3. Per-card fetches. N+1, and only reached when both above fail.
        """
        if game != "pkmn":
            # A Pokémon database. Saying so is the point: it is why One Piece
            # Simplified Chinese is still uncovered after adding all three.
            raise AdapterGaveUp(
                f"{self.name} is a Pokemon-only database; it cannot serve "
                f"{game}. One Piece CN-S has no catalog source.")

        # THE FALLBACK WAS NEVER WIRED UP. `english_index()` existed and
        # nothing called it, so `resolve_rarity` was always handed None and
        # every Chinese card with no rarity of its own stayed unknown. Given
        # how thin the Chinese datasets turned out to be, that was most of them.
        if english_by_id is None and language in self.NEEDS_ENGLISH_RARITY:
            english_by_id = self.english_index_cached()

        if self.filter_is_honoured(language):
            hits = self._by_rarity(language)
            self.strategy = "server_side_filter"
        else:
            hits = self._by_graphql(language)
            self.strategy = "graphql" if hits else "per_card"
            if not hits:
                hits = self._per_card(language)

        rows = []
        self.rarity_origins = {}
        # COUNT WHAT NEVER LEAVES THIS METHOD. `_catalog_row` returns None for
        # a card it cannot identify, and the caller sees only the survivors --
        # so an adapter that dropped every row and one that fetched nothing
        # looked identical from outside. That is precisely how the missing set
        # field went unnoticed for a whole run.
        self.hits_seen = len(hits)
        self.dropped_no_identity = 0
        for hit in hits:
            rarity, origin = resolve_rarity(hit, english_by_id)
            self.rarity_origins[origin] = self.rarity_origins.get(origin, 0) + 1
            row = _catalog_row(game, language, _set_code_of(hit),
                               {**hit, "rarity": rarity}, self.name)
            if row is None:
                self.dropped_no_identity += 1
            if row:
                # Where the classification came from, carried into the row. A
                # borrowed rarity is a weaker claim than a printed one and the
                # difference has to survive.
                row["rarity_from"] = origin
                rows.append(row)
        return rows

    def _by_rarity(self, language) -> list:
        """One request per rarity present in the dataset. The cheap path."""
        out, seen = [], set()
        for rarity in self.rarities(language):
            if band_of(rarity) not in TRACKED_BANDS:
                # No point paying for a page of Commons.
                continue
            payload = self.cards_by_rarity(language, rarity)
            for hit in (payload if isinstance(payload, list)
                        else find(payload, "data") or []):
                key = find(hit, "id")
                if key in seen:
                    continue
                seen.add(key)
                # The filter is the only thing that knows this card's rarity --
                # the brief object still omits it -- so it is attached here.
                out.append({**hit, "rarity": rarity})
        return out

    GRAPHQL = "https://api.tcgdex.net/v2/graphql"

    def _by_graphql(self, language) -> list:
        """One query per language, selecting what the brief object omits."""
        code = self.LANG[language]
        query = ("{cards(filters:{}){id localId name rarity illustrator "
                 "set{id} variants{firstEdition holo reverse normal}}}")
        try:
            payload = self.get(
                f"{self.GRAPHQL}?query={urllib.parse.quote(query)}",
                label=f"graphql-{code}", attempts=2)
        except (AdapterGaveUp, RateLimited) as exc:
            self.log.append(f"{self.name} graphql unavailable: {str(exc)[:120]}")
            return []
        return find(payload, "cards") or []

    def _per_card(self, language) -> list:
        """N+1. The last resort, and it says so in the log because 8,313
        single-card fetches is a quota decision, not an implementation
        detail."""
        code = self.LANG[language]
        self.log.append(f"{self.name} {code} falling back to PER-CARD fetches "
                        "-- neither the rarity filter nor GraphQL answered")
        out = []
        for entry in self.sets(language):
            set_id = str(find(entry, "id", "code") or "")
            if not set_id:
                continue
            payload = self.get(f"https://api.tcgdex.net/v2/{code}/sets/{set_id}",
                               label=f"set-{code}-{set_id}", attempts=2)
            for brief in (find(payload, "cards") or []):
                card_id = find(brief, "id")
                if not card_id:
                    continue
                full = self.get(f"https://api.tcgdex.net/v2/{code}/cards/{card_id}",
                                label=f"card-{code}-{card_id}", attempts=1)
                out.append({**brief, **(full if isinstance(full, dict) else {}),
                            "set_id": set_id})
        return out

    def english_index(self) -> dict:
        """id -> English card, for the rarity fallback.

        tcgdex ids are stable across languages and English is the most complete
        dataset, so a Chinese card that omits `rarity` can borrow one. Built
        once per run and reused for both Chinese printings.
        """
        index = {}
        try:
            hits = self._by_rarity("EN") or self._by_graphql("EN")
        except (AdapterGaveUp, RateLimited) as exc:
            self.log.append(f"{self.name} no English index: {str(exc)[:120]}")
            return index
        for hit in hits:
            key = find(hit, "id")
            if key:
                index[key] = hit
        return index


class CrystAdapter(CatalogSource):
    """Cryst's Card Database (tcg.mik.moe) -- Simplified Chinese Pokémon.

    Sourced from Pokémon Shanghai, which makes it the closest thing to a
    primary source for the combined-set renumbering that SC uses: the numbers
    that make SC identity hard come from the publisher this database follows.

    NO PUBLISHED API CONTRACT was available when this was written. The
    candidate paths below are guesses in the literal sense, and `probe()` tries
    each and reports which answered. If none do, the gap detail names every URL
    tried, so the next session starts from evidence instead of repeating this.
    """

    name = "cryst"
    key_env = None
    host = "tcg.mik.moe"
    serves = (("pkmn", "CN-S"),)
    verified = False

    SET_CANDIDATES = ("https://tcg.mik.moe/api/sets",
                      "https://tcg.mik.moe/api/v1/sets",
                      "https://tcg.mik.moe/data/sets.json")

    def card_candidates(self, set_code):
        return (f"https://tcg.mik.moe/api/sets/{set_code}/cards",
                f"https://tcg.mik.moe/api/cards?set={set_code}",
                f"https://tcg.mik.moe/data/{set_code}.json")

    def enumerate_combo(self, game, language) -> list[dict]:
        if (game, language) != ("pkmn", "CN-S"):
            raise AdapterGaveUp(
                f"{self.name} serves Simplified Chinese Pokemon only; "
                f"asked for {game}:{language}")
        url, payload = self.probe(self.SET_CANDIDATES, label="sets")
        if url is None:
            raise AdapterGaveUp(
                f"{self.name}: no set endpoint answered. Tried "
                + "; ".join(f"{u} ({why})" for u, why in payload))
        self.log.append(f"{self.name} set endpoint resolved to {url}")
        entries = payload if isinstance(payload, list) else (
            find(payload, "data", "sets", "results") or [])
        rows = []
        for entry in entries:
            set_code = str(find(entry, "code", "id", "set_code") or "")
            if not set_code:
                continue
            hit_url, cards = self.probe(self.card_candidates(set_code),
                                        label=f"cards-{set_code}")
            if hit_url is None:
                continue
            for hit in (cards if isinstance(cards, list)
                        else find(cards, "data", "cards", "results") or []):
                row = _catalog_row(game, language, set_code, hit, self.name)
                if row:
                    rows.append(row)
        return rows


class Poke52Adapter(CatalogSource):
    """52poke Wiki -- MediaWiki, and deliberately NOT an enumeration source.

    It is the best Chinese-language reference for both printings and it has the
    standard MediaWiki action API at /api.php, so it can answer "what is this
    card called in Chinese" reliably.

    What it cannot do is enumerate a set, and the reason is worth stating
    rather than working around: enumeration means naming a category page, the
    category titles are in Chinese, and I have not verified a single one. A
    guessed category title returns an empty result that looks exactly like an
    empty set. So this adapter refuses to enumerate and offers `names_for()`
    instead -- an enrichment pass over identities another source established.

    Under CLAUDE.md's rule about fields a source cannot supply: rather than
    stub an enumerate path that half-works, there is no enumerate path.
    """

    name = "wiki52poke"
    key_env = None
    host = "wiki.52poke.com"
    serves = (("pkmn", "CN-S"), ("pkmn", "CN-T"))
    verified = False
    can_enumerate = False
    cannot_enumerate_because = (
        "enrichment only: 52poke has no set-catalog endpoint we have verified, "
        "and a guessed category title returns an empty page that is "
        "indistinguishable from an empty set. Supplies Chinese names for "
        "identities another source established.")

    API = ("https://wiki.52poke.com/api.php?action=query&format=json"
           "&list=search&srlimit=5&srsearch={q}")

    def names_for(self, cards) -> list[Record]:
        """Chinese name per card, by search. Cards with no hit are skipped --
        an absent name is absent, not an empty string."""
        observed = self._now()
        out = []
        for card in cards:
            query = urllib.parse.quote(f"{card.get('name') or ''} "
                                       f"{card.get('number') or ''}".strip())
            if not query:
                continue
            payload = self.get(self.API.format(q=query),
                               label=f"search-{card['card_uid']}", attempts=2)
            hits = find(payload, "search") or []
            if not hits:
                continue
            title = find(hits[0], "title")
            if not title:
                continue
            out.append(Record(kind="card", source=self.name, as_of=observed,
                              observed_at=observed,
                              payload={"card_uid": card["card_uid"],
                                       "name_zh": str(title)}))
        return out

    def fetch(self, since=None, combos=None, cards=()) -> list[Record]:
        return self.names_for(cards)


def _set_code_of(hit) -> str:
    """The set code, whatever shape the strategy returned it in.

    THREE shapes, and getting this wrong drops every row silently:

    * GraphQL returns `set` as an object with an `id`. Stringifying it produced
      `{'id': '151C'}` as a set code, which `card_uid` rejected.
    * `?rarity=` and `sets/{id}.cards[]` return BRIEF objects -- `id`,
      `localId`, `name`, `image` and NOTHING ELSE. No set field at all, so the
      code came out empty and every row was dropped. That is what run #10's
      `no_tracked_cards` on pkmn:JP, CN-S and CN-T actually was.
    * REST detail returns `set_id` as a plain string.

    The brief object still carries the set: tcgdex ids are `{setId}-{localId}`,
    so stripping the localId suffix recovers it. Derived rather than requested,
    because requesting it would be a second call per card.
    """
    found = find(hit, "set_id")
    if found in (None, ""):
        found = find(hit, "set")
    if isinstance(found, dict):
        found = found.get("id") or found.get("code") or ""
    if found not in (None, ""):
        return str(found)

    # Brief object: recover the set from the id.
    ident = str(find(hit, "id") or "")
    local = str(find(hit, "localId", "local_id") or "")
    if ident and local and ident.endswith(f"-{local}"):
        return ident[: -(len(local) + 1)]
    if ident and "-" in ident:
        # No localId to strip against. A set id may itself contain hyphens
        # (`swshp-SWSH001`), so the LAST hyphen is the card boundary.
        return ident.rsplit("-", 1)[0]
    return ""


def _catalog_row(game, language, set_code, hit, source) -> Optional[dict]:
    """Provider card object -> the identity columns, or None if it lacks them.

    Returns None rather than a partial row. A card with no collector number
    cannot have a `card_uid`, and inventing one to keep the count up is the
    failure mode the whole labelled set exists to measure.
    """
    from resolve.identity import (card_uid as _uid,
                                  variant_from_external_id,
                                  variant_from_number, variant_from_rarity)

    number = str(find(hit, "localId", "number", "collector_number",
                      "code") or "").strip()
    if not number or not set_code:
        return None
    rarity = hit.get("rarity") if isinstance(hit, dict) else None
    if rarity in (None, ""):
        rarity = find(hit, "rarity")
    name = find(hit, "name") or ""
    # Number first, then the publisher's own id, then the rarity string. See
    # resolve.identity.variant_from_number and variant_from_external_id: a
    # `_p1` printing carries its base card's number AND its base card's
    # rarity, so neither of the other two can keep them apart.
    variant = (variant_from_number(number, None, game)
               or variant_from_external_id(find(hit, "id", "card_id"), game)
               or variant_from_rarity(rarity, name, language, game))
    try:
        uid = _uid(game, set_code, number, variant, language)
    except (ValueError, KeyError):
        return None
    row = {"card_uid": uid, "game": game, "set_code": set_code,
           "number": number, "variant": variant, "language": language,
           "rarity": rarity, "artist": find(hit, "illustrator", "artist"),
           "image_url": find(hit, "image", "image_url")}
    # Chinese printings carry the Chinese name; there is no name_en to claim.
    row["name_jp" if language in ("JP", "CN-S", "CN-T") else "name_en"] = name
    box_code = find(hit, "box_code", "boxCode", "product_code")
    if box_code:
        row["box_code"] = str(box_code)
    return {k: v for k, v in row.items() if v not in (None, "")}


CATALOG_SOURCES = {a.name: a for a in (TcgdexAdapter, CrystAdapter,
                                       Poke52Adapter)}

# Tried in this order for a combo none of the commercial providers cover.
CN_SOURCE_PRIORITY = ("tcgdex", "cryst", "wiki52poke")
