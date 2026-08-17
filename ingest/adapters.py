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
import json
import os
from decimal import Decimal
from typing import Optional

from .base import Adapter, AdapterGaveUp, Record, find

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
    requires_targets = True
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
    requires_targets = True
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
    requires_targets = True
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
    requires_targets = True
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

    WHAT RUN #5 GOT WRONG. Rate limited, on five pairs, against a free tier of
    25 requests a day and **5 a minute**. The daily cap was never the problem;
    the per-minute one was, and three things conspired:

    * five pairs, not the three the day actually needs
    * `max_attempts = 4` behind each, so up to twenty requests in a couple of
      seconds against a 5/min ceiling
    * a retry on a throttle response, which is the one error where retrying
      immediately is guaranteed to fail and to deepen the hole

    So: an explicit 13-second floor between calls, at most ONE request per pair
    per run, no retry on a throttle, and a same-day cache so that a run which
    loses the last pair does not also lose the four it already had.

    The throttle arrives as **HTTP 200 with an `Information` key**. That is now
    detected in the base class for every adapter rather than here for one --
    it is the ninth time this project has met that shape.
    """

    name = "fx_alphavantage"
    key_env = "ALPHAVANTAGE_KEY"
    host = "www.alphavantage.co"
    daily_free_calls = 25

    # 5 requests/minute = one per 12s. 13 buys a second of headroom against
    # clock skew, which costs 39 seconds a run and is worth it.
    min_interval_seconds = 13.0
    # One attempt per pair. A throttle is not a transient network error; the
    # correct response is to stop asking, not to ask harder.
    max_attempts = 1

    SERIES = ("https://www.alphavantage.co/query?function=FX_DAILY"
              "&from_symbol={base}&to_symbol={quote}&apikey={key}")

    # The pairs the engine actually converts through. GBP/USD because I buy in
    # USD and live in GBP; USD/JPY for the Japanese market; USD/CNY for the
    # Chinese printings. EUR and HKD were speculative and cost two of the five
    # per-minute slots for rates nothing reads.
    PAIRS = (("GBP", "USD"), ("USD", "JPY"), ("USD", "CNY"))

    # Alpha Vantage's own dialect, ADDED to the shared set rather than
    # replacing it. `Information` is what a throttle looks like.
    EXTRA_ERROR_KEYS = ("Error Message", "Note", "Information")

    def cache_path(self, day: str) -> str:
        return os.path.join(self.raw_root, self.name, f"rates-{day}.json")

    def load_cached(self, day: str) -> dict:
        """Rates already fetched today. A run that dies on pair three keeps
        pairs one and two -- losing the whole day to one throttle is how a
        single 200-with-an-error-body becomes a gap in every converted
        figure."""
        try:
            with open(self.cache_path(day), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return {}

    def save_cached(self, day: str, rates: dict):
        path = self.cache_path(day)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(rates, handle, indent=2)
        except OSError as exc:                              # noqa: BLE001
            # A cache that cannot be written is a slower run, not a failed one.
            self.log.append(f"{self.name} could not write rate cache: {exc}")

    def fetch(self, since=None, pairs=None) -> list[Record]:
        observed = self._now()
        day = observed.date().isoformat()
        cached = self.load_cached(day)
        records, fresh, failures = [], dict(cached), []

        for base, quote in (pairs or self.PAIRS):
            pair = f"{base}/{quote}"
            hit = cached.get(pair)
            if hit:
                # Already have today's. Not re-requested: one call per pair per
                # run is the cap, and a cached rate is the same rate.
                self.log.append(f"{self.name} {pair} from today's cache")
                records.append(Record(
                    kind="fx", source=self.name, as_of=_date(hit["as_of"]),
                    observed_at=observed,
                    payload={"pair": pair, "rate": Decimal(str(hit["rate"]))}))
                continue

            try:
                payload = self.get(
                    self.SERIES.format(base=base, quote=quote,
                                       key=self.key or ""),
                    label=f"fx-{base}{quote}")
            except AdapterGaveUp as exc:
                # Keep going. The remaining pairs are independent, and a run
                # that abandons them turns one throttled pair into no FX at all.
                failures.append(f"{pair}: {str(exc)[:120]}")
                continue

            series = find(payload, "Time Series FX (Daily)") or {}
            for stamp, values in sorted(series.items(), reverse=True)[:1]:
                as_of = _date(stamp)
                if as_of is None:
                    continue
                rate = Decimal(str(values["4. close"]))
                fresh[pair] = {"rate": str(rate), "as_of": as_of.isoformat()}
                records.append(Record(
                    kind="fx", source=self.name, as_of=as_of,
                    observed_at=observed,
                    payload={"pair": pair, "rate": rate}))

        if fresh != cached:
            self.save_cached(day, fresh)
        if failures:
            self.log.append(f"{self.name} pairs that did not answer: "
                            + "; ".join(failures))
            if not records:
                # Nothing at all, cache included. That IS a failed source.
                raise AdapterGaveUp(
                    f"{self.name}: no pair returned a rate. " + "; ".join(failures))
        return records


# The five verified providers. The registry in ingest/registry.py is what the
# runner reads; it also pulls in ingest/catalog_sources.py, independently, so
# a break there does not reach this module.
ADAPTERS = {a.name: a for a in (
    TcgApiAdapter, PokemonPriceTrackerAdapter, ApiTcgAdapter,
    PriceChartingAdapter, FxAlphaVantageAdapter)}
