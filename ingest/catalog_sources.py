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


CATALOG_SOURCES = {a.name: a for a in (TcgdexAdapter, CrystAdapter,
                                       Poke52Adapter)}

# Tried in this order for a combo none of the commercial providers cover.
CN_SOURCE_PRIORITY = ("tcgdex", "cryst", "wiki52poke")
