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
from resolve.identity import (TCGAPI_GAME_ID, card_uid,           # noqa: E402
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
TRACKED_BANDS = ("chase", "premium")

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
    SET_CANDIDATES = (
        "https://api.tcgapi.dev/v1/sets?game={game}&page={page}&per_page=100",
        "https://api.tcgapi.dev/v1/sets?game_id={game}&page={page}",
        "https://api.tcgapi.dev/v1/games/{game}/sets?page={page}",
    )
    CARD_CANDIDATES = (
        "https://api.tcgapi.dev/v1/cards?game={game}&set={set}&page={page}&per_page=250",
        "https://api.tcgapi.dev/v1/cards?game={game}&set_code={set}&page={page}",
        "https://api.tcgapi.dev/v1/sets/{set}/cards?game={game}&page={page}",
    )

    def sets_for(self, game, language):
        """Every set for a combo, read to the LAST page."""
        game_id = TCGAPI_GAME_ID.get((game, language))
        if game_id is None:
            # A fact about TCGAPI, not about the combination. Naming it
            # `no_catalog_source` made pkmn:CN-S report "nothing serves this"
            # while tcgdex was serving it 877 cards -- the combo-level verdict
            # is computed at the end, from every source that was asked.
            self.gap((game, language), "tcgapi_no_game_entry",
                     "tcgapi has no game entry for this combination")
            return []

        self.attempt((game, language), "tcgapi")
        template = self.endpoints_used.get("tcgapi.sets")
        if template is None:
            url, payload = self.tcgapi.probe(
                [c.format(game=game_id, page=1) for c in self.SET_CANDIDATES],
                label=f"sets-{game}-{language}-discover")
            if url is None:
                raise AdapterGaveUp(
                    "no tcgapi set endpoint answered. Tried "
                    + "; ".join(f"{u} ({why})" for u, why in payload))
            template = self.SET_CANDIDATES[
                [c.format(game=game_id, page=1) for c in self.SET_CANDIDATES].index(url)]
            self.endpoints_used["tcgapi.sets"] = template
            self.log.append(f"tcgapi sets endpoint resolved to {template}")

        out, page = [], 1
        while True:
            payload = self.tcgapi.get(template.format(game=game_id, page=page),
                                      label=f"sets-{game}-{language}-p{page}")
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
        if self.endpoints_used.get("tcgapi.bulk") != "unavailable":
            try:
                payload = self.tcgapi.get(
                    f"https://api.tcgapi.dev/v1/bulk?game={game_id}&set={set_code}",
                    label=f"bulk-{game}-{language}-{set_code}", attempts=1)
                cards = find(payload, "data", "cards", "results")
                if cards:
                    self.endpoints_used["tcgapi.bulk"] = "/v1/bulk"
                    return cards
            except AdapterGaveUp:
                # Ruled out ONCE, not once per set. Re-probing a known-absent
                # endpoint for every set in the game is how a catalog refresh
                # spends its whole quota discovering the same 404.
                self.endpoints_used["tcgapi.bulk"] = "unavailable"
                self.log.append("tcgapi /v1/bulk did not answer; paging /cards")

        template = self.endpoints_used.get("tcgapi.cards")
        if template is None:
            candidates = [c.format(game=game_id, set=set_code, page=1)
                          for c in self.CARD_CANDIDATES]
            url, payload = self.tcgapi.probe(
                candidates, label=f"cards-{set_code}-discover")
            if url is None:
                raise AdapterGaveUp(
                    "no tcgapi card endpoint answered. Tried "
                    + "; ".join(f"{u} ({why})" for u, why in payload))
            template = self.CARD_CANDIDATES[candidates.index(url)]
            self.endpoints_used["tcgapi.cards"] = template
            self.log.append(f"tcgapi cards endpoint resolved to {template}")

        out, page = [], 1
        while True:
            payload = self.tcgapi.get(
                template.format(game=game_id, set=set_code, page=page),
                label=f"cards-{set_code}-p{page}")
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
        self.attempt((game, language), "apitcg")
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
        """A catalog source row -> a targets row, filtered to tracked bands."""
        if rarity_band(hit.get("rarity")) not in TRACKED_BANDS:
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
                    row = self._row(game, language,
                                    str(find(hit, "set_code", "setCode",
                                             "set") or ""), hit, "apitcg")
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


def to_targets(catalog, gaps, combo_status=None, endpoints=None):
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
        "_gaps": gaps,
        "fx_alphavantage": {},
        **per_source,
    }


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
    parser.add_argument("--coverage", action="store_true",
                        help="measure what the open Chinese sources actually "
                             "serve, per combo, and report it without building")
    args = parser.parse_args(argv)

    combos = COMBOS
    if args.combos != "all":
        wanted = set(args.combos.split(","))
        combos = [c for c in COMBOS if f"{c[0]}:{c[1]}" in wanted]

    builder = CatalogBuilder()

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
                         builder.endpoints_used)

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
