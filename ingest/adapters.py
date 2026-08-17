"""The five sources, each a thin parser over the shared base.

Everything that must be true of all of them -- raw-cache-before-parse, bounded
backoff, quota from the provider's own counter, a 2xx-with-error-body treated
as a failure -- lives in `Adapter`. What is left here is the shape of each
provider's JSON and the honest limits of what it can supply.

Coverage is uneven and these adapters do not pretend otherwise. Four of the
eight game/language combinations have no automated price source at all, and the
adapter for those is a person typing. See contracts/SOURCE_MAP.md.
"""

from __future__ import annotations

import datetime as _dt
import urllib.parse
from decimal import Decimal
from typing import Optional

from .base import Adapter, AdapterGaveUp, RateLimited, Record, find

# Grades we accept from a provider. Anything else is reported as a gap rather
# than coerced -- 'MINT 9' and '9' may or may not be the same claim.
GRADE_ALIASES = {
    "raw": "raw", "ungraded": "raw", "loose": "raw",
    **{str(g): str(g) for g in range(1, 11)},
    **{f"{g}.5": f"{g}.5" for g in range(1, 10)},
    "10.0": "10", "9.0": "9", "8.0": "8",
}


def _date(value) -> Optional[_dt.datetime]:
    if value in (None, ""):
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = _dt.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


class TcgApiAdapter(Adapter):
    """tcgapi.dev -- catalog and raw/market prices.

    Language is a SEPARATE GAME here (Pokémon is 55, Pokémon Japan is 19), and
    there is no One Piece Japan entry at all. That is a coverage fact, not a
    lookup failure, and it is reported as a gap with `no_source_for_this_language`
    rather than as an empty result.
    """

    name = "tcgapi"
    key_env = "TCGAPI_KEY"
    api_key_header = "X-API-Key"
    host = "api.tcgapi.dev"

    SEARCH = "https://api.tcgapi.dev/v1/search?q={name}&game={game}"
    GAMES = "https://api.tcgapi.dev/v1/games?page={page}&per_page=100"

    def note_quota(self, payload):
        limits = find(payload, "rate_limit", "rateLimit")
        if isinstance(limits, dict):
            remaining = find(limits, "daily_remaining", "dailyRemaining")
            if remaining is not None:
                self.quota.remaining = int(remaining)
                self.quota.reported_by_provider = True
            cap = find(limits, "daily_limit", "dailyLimit")
            if cap is not None:
                self.quota.limit = int(cap)

    def games(self) -> list:
        """Every game, read to the LAST page.

        A truncated enumeration proves nothing about what is missing from it
        (ADR-0001), so absence is only claimed once has_more is false.
        """
        out, page = [], 1
        while True:
            payload = self.get(self.GAMES.format(page=page), label=f"games-p{page}")
            batch = find(payload, "data", "games", "results") or []
            out.extend(batch)
            meta = find(payload, "meta") or {}
            if not (meta.get("has_more") or meta.get("hasMore")):
                break
            page += 1
            if page > 50:
                raise RuntimeError("games pagination did not terminate")
        return out

    def fetch(self, since=None, cards=()) -> list[Record]:
        observed = self._now()
        records = []
        for card in cards:
            payload = self.get(
                self.SEARCH.format(name=card["name"], game=card["game_id"]),
                label=f"search-{card['card_uid']}")
            for hit in find(payload, "data", "results", "cards") or []:
                as_of = _date(find(hit, "updated_at", "updatedAt", "as_of")) or observed
                records.append(Record(
                    kind="xref", source=self.name, as_of=as_of, observed_at=observed,
                    payload={"card_uid": card["card_uid"],
                             "external_id": str(find(hit, "id", "card_id") or ""),
                             "secondary_id": str(find(hit, "tcgplayer_id") or "") or None,
                             "name": find(hit, "name"),
                             "set_code": find(hit, "set_code", "setCode"),
                             "number": find(hit, "number", "collector_number"),
                             "rarity": find(hit, "rarity"),
                             "image_url": find(hit, "image_url", "imageUrl")}))
                price = find(hit, "market_price", "marketPrice", "market")
                if price is not None:
                    records.append(Record(
                        kind="price", source=self.name, as_of=as_of,
                        observed_at=observed,
                        payload={"card_uid": card["card_uid"], "grade": "raw",
                                 "condition": "nm", "marketplace": "tcgplayer",
                                 "amount": Decimal(str(price)),
                                 "currency": find(hit, "currency") or "USD",
                                 "sample_size": find(hit, "sales_count")}))
        return records


class PokemonPriceTrackerAdapter(Adapter):
    """PokemonPriceTracker -- the ONLY source of per-grade population.

    Pokémon only, by construction. It is also the only source that gives sold
    prices BY GRADE AND BY GRADER together, which is what makes the CGC-10 /
    PSA-10 ratio computable at all -- see store/cross_grader.py.

    It bills per card, not per request: `metadata.apiCallsConsumed.costPerCard`.
    Counting our own requests would underestimate the spend, and the way you
    find that out is a 429 halfway through a run.
    """

    name = "pokemonpricetracker"
    key_env = "PPT_KEY"
    api_key_header = "Authorization"
    host = "www.pokemonpricetracker.com"

    CARD = "https://www.pokemonpricetracker.com/api/v2/cards?id={id}"

    @property
    def key(self):
        raw = super().key
        return f"Bearer {raw}" if raw and not raw.startswith("Bearer ") else raw

    def preflight(self):
        # Report on the raw secret, not on the "Bearer " we prepend, or the
        # logged length is always seven characters too long.
        info = super().preflight()
        import os
        raw = os.environ.get(self.key_env)
        info["key_length"] = len(raw) if raw else 0
        info["key_prefix"] = raw[:4] if raw else None
        return info

    def note_quota(self, payload):
        meta = find(payload, "metadata", "meta") or {}
        consumed = find(meta, "apiCallsConsumed", "api_calls_consumed")
        if isinstance(consumed, dict):
            per_card = consumed.get("costPerCard") or consumed.get("cost_per_card")
            total = consumed.get("total")
            if total is not None:
                self.quota.consumed_this_run = int(total)
            elif per_card is not None:
                self.quota.consumed_this_run += int(per_card)
        remaining = find(meta, "creditsRemaining", "credits_remaining",
                         "daily_remaining")
        if remaining is not None:
            self.quota.remaining = int(remaining)
            self.quota.reported_by_provider = True

    def fetch(self, since=None, cards=()) -> list[Record]:
        observed = self._now()
        records = []
        for card in cards:
            payload = self.get(self.CARD.format(id=card["external_id"]),
                               label=f"card-{card['card_uid']}")
            data = find(payload, "data") or payload
            as_of = _date(find(data, "updatedAt", "updated_at")) or observed

            sales = find(data, "salesByGrade") or {}
            for key, entry in (sales.items() if isinstance(sales, dict) else []):
                grader, grade = _split_grade_key(key)
                if grade is None:
                    continue
                price = find(entry, "median", "average", "price") if isinstance(entry, dict) else entry
                if price is None:
                    continue
                records.append(Record(
                    kind="price", source=self.name, as_of=as_of,
                    observed_at=observed,
                    payload={"card_uid": card["card_uid"], "grade": grade,
                             "grader": grader, "condition": "graded",
                             "marketplace": "ebay",
                             "amount": Decimal(str(price)), "currency": "USD",
                             "sample_size": (entry.get("count")
                                             if isinstance(entry, dict) else None)}))

            pops = find(data, "populationByGrader") or {}
            for grader, by_grade in (pops.items() if isinstance(pops, dict) else []):
                if not isinstance(by_grade, dict):
                    continue
                for grade_key, count in by_grade.items():
                    grade = GRADE_ALIASES.get(str(grade_key).lower())
                    if grade is None or grade == "raw" or count is None:
                        continue
                    records.append(Record(
                        kind="pop", source=self.name, as_of=as_of,
                        observed_at=observed,
                        payload={"card_uid": card["card_uid"],
                                 "grader": grader.upper(), "grade": grade,
                                 "count": int(count)}))
        return records


def _split_grade_key(key: str):
    """'PSA10' / 'psa_10' / 'CGC 9.5' -> ('PSA', '10'). Unrecognised -> (None, None)."""
    text = str(key).replace("_", " ").replace("-", " ").strip()
    for grader in ("PSA", "CGC", "BGS", "SGC", "TAG"):
        if text.upper().startswith(grader):
            tail = text[len(grader):].strip()
            return grader, GRADE_ALIASES.get(tail.lower())
    return None, None


class ApiTcgAdapter(Adapter):
    """apitcg.com -- catalog and the only reliable ARTIST field.

    Answers auth failures with HTTP 200 and an error object, which the base
    class refuses to read as an empty result.
    """

    name = "apitcg"
    key_env = "APITCG_KEY"
    api_key_header = "x-api-key"
    host = "apitcg.com"

    CARDS = "https://apitcg.com/api/{game}/cards?property=code&value={number}"
    SLUG = {"optcg": "one-piece", "pkmn": "pokemon", "riftbound": "riftbound"}

    def fetch(self, since=None, cards=()) -> list[Record]:
        observed = self._now()
        records = []
        for card in cards:
            slug = self.SLUG.get(card["game"])
            if slug is None:
                continue
            payload = self.get(self.CARDS.format(slug=slug, game=slug,
                                                 number=card["number"]),
                               label=f"cards-{card['card_uid']}")
            for hit in find(payload, "data", "cards") or []:
                records.append(Record(
                    kind="card", source=self.name, as_of=observed,
                    observed_at=observed,
                    payload={"card_uid": card["card_uid"],
                             "artist": find(hit, "illustrator", "artist"),
                             "rarity": find(hit, "rarity"),
                             "name_en": find(hit, "name"),
                             "image_url": find(hit, "image", "images")}))
        return records


class PriceChartingAdapter(Adapter):
    """PriceCharting -- graded comps for the games PPT does not cover.

    The token goes in the query string as `t`, which means it lands in any URL
    we log. `cache_raw` therefore labels by card, never by URL.
    """

    name = "pricecharting"
    key_env = "PRICECHARTING_TOKEN"
    host = "www.pricecharting.com"

    PRODUCT = "https://www.pricecharting.com/api/product?t={token}&id={id}"

    GRADE_FIELDS = {
        "loose-price": ("raw", None), "graded-price": ("9", "PSA"),
        "manual-only-price": ("10", "PSA"), "bgs-10-price": ("10", "BGS"),
        "condition-17-price": ("10", "CGC"), "condition-18-price": ("10", "SGC"),
    }

    def get(self, url, *, headers=None, label=None):
        # Never let the token reach the raw-cache filename.
        return super().get(url, headers=headers, label=label or "product")

    def fetch(self, since=None, cards=()) -> list[Record]:
        observed = self._now()
        token = self.key or ""
        records = []
        for card in cards:
            payload = self.get(self.PRODUCT.format(token=token,
                                                   id=card["external_id"]),
                               label=f"product-{card['card_uid']}")
            as_of = _date(find(payload, "release-date")) or observed
            for field_name, (grade, grader) in self.GRADE_FIELDS.items():
                cents = payload.get(field_name)
                if cents in (None, "", 0):
                    continue
                records.append(Record(
                    kind="price", source=self.name, as_of=as_of,
                    observed_at=observed,
                    payload={"card_uid": card["card_uid"], "grade": grade,
                             "grader": grader,
                             "condition": "raw" if grade == "raw" else "graded",
                             "marketplace": "ebay",
                             # PriceCharting quotes pennies. Dividing by 100 in
                             # Decimal, never float.
                             "amount": Decimal(str(cents)) / Decimal(100),
                             "currency": "USD", "sample_size": None}))
        return records


class FxAlphaVantageAdapter(Adapter):
    """Alpha Vantage -- FX only.

    Every cross-currency figure in the app rests on this one source, so a gap
    here is not cosmetic: the engine refuses to convert without a rate rather
    than assuming parity.
    """

    name = "fx_alphavantage"
    key_env = "ALPHAVANTAGE_KEY"
    host = "www.alphavantage.co"
    daily_free_calls = 25

    SERIES = ("https://www.alphavantage.co/query?function=FX_DAILY"
              "&from_symbol={base}&to_symbol={quote}&apikey={key}")

    PAIRS = (("GBP", "USD"), ("USD", "JPY"), ("USD", "CNY"),
             ("EUR", "USD"), ("USD", "HKD"))

    ERROR_KEYS = ("Error Message", "Note", "Information")

    def fetch(self, since=None, pairs=None) -> list[Record]:
        observed = self._now()
        records = []
        for base, quote in (pairs or self.PAIRS):
            payload = self.get(
                self.SERIES.format(base=base, quote=quote, key=self.key or ""),
                label=f"fx-{base}{quote}")
            series = find(payload, "Time Series FX (Daily)") or {}
            for day, values in sorted(series.items(), reverse=True)[:1]:
                as_of = _date(day)
                if as_of is None:
                    continue
                records.append(Record(
                    kind="fx", source=self.name, as_of=as_of,
                    observed_at=observed,
                    payload={"pair": f"{base}/{quote}",
                             "rate": Decimal(str(values["4. close"]))}))
        return records


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
    serves = (("pkmn", "CN-T"), ("pkmn", "CN-S"))
    verified = False

    # The user gave `api.tcgdex.net/status`; the versioned form is the shape
    # every other endpoint takes. Both are tried rather than guessed between.
    STATUS_CANDIDATES = ("https://api.tcgdex.net/v2/status",
                         "https://api.tcgdex.net/status")

    # Ours -> TCGdex path segment.
    LANG = {"EN": "en", "JP": "ja", "CN-T": "zh-tw", "CN-S": "zh-cn"}

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

    def sets(self, language) -> list:
        code = self.LANG.get(language)
        if code is None:
            raise AdapterGaveUp(f"{self.name}: no path segment for {language}")
        payload = self.get(f"https://api.tcgdex.net/v2/{code}/sets",
                           label=f"sets-{code}", attempts=2)
        return payload if isinstance(payload, list) else (
            find(payload, "data", "sets") or [])

    def enumerate_combo(self, game, language) -> list[dict]:
        if game != "pkmn":
            # A Pokémon database. Saying so is the point: it is why One Piece
            # Simplified Chinese is still uncovered after adding all three.
            raise AdapterGaveUp(
                f"{self.name} is a Pokemon-only database; it cannot serve "
                f"{game}. One Piece CN-S has no catalog source.")
        code = self.LANG[language]
        rows = []
        for entry in self.sets(language):
            set_id = str(find(entry, "id", "code") or "")
            if not set_id:
                continue
            payload = self.get(f"https://api.tcgdex.net/v2/{code}/sets/{set_id}",
                               label=f"set-{code}-{set_id}", attempts=2)
            set_code = str(find(payload, "id", "code") or set_id)
            for hit in (find(payload, "cards") or []):
                row = _catalog_row(game, language, set_code, hit, self.name)
                if row:
                    rows.append(row)
        return rows


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


def _catalog_row(game, language, set_code, hit, source) -> Optional[dict]:
    """Provider card object -> the identity columns, or None if it lacks them.

    Returns None rather than a partial row. A card with no collector number
    cannot have a `card_uid`, and inventing one to keep the count up is the
    failure mode the whole labelled set exists to measure.
    """
    from resolve.identity import card_uid as _uid, variant_from_rarity

    number = str(find(hit, "localId", "number", "collector_number",
                      "code") or "").strip()
    if not number or not set_code:
        return None
    rarity = find(hit, "rarity")
    name = find(hit, "name") or ""
    variant = variant_from_rarity(rarity, name)
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


ADAPTERS = {a.name: a for a in (
    TcgApiAdapter, PokemonPriceTrackerAdapter, ApiTcgAdapter,
    PriceChartingAdapter, FxAlphaVantageAdapter,
    TcgdexAdapter, CrystAdapter, Poke52Adapter)}

# Tried in this order for a combo none of the commercial providers cover.
CN_SOURCE_PRIORITY = ("tcgdex", "cryst", "wiki52poke")
