"""CGC-10 / PSA-10 and friends: the ratio that closes the cross-grader comp gap.

The route comparison currently prices a CGC submission against PSA comps and
raises a mismatch flag, because a CGC 10 and a PSA 10 are different assets and
nothing here knows by how much. This is the number that would close it.

PokemonPriceTracker returns `salesByGrade` keyed by grader AND grade, so the
ratio is computable from one source at one moment -- no cross-source price
alignment, no FX, no as-of mismatch. That is the only reason it is trustworthy
enough to try.

**It refuses until there is enough history**, per game / rarity band / era, and
reports sample size on everything it does emit. A ratio computed from three
sales is not a discount rate, it is three sales, and a route comparison that
silently used it would be worse than one that flags the gap honestly.

This is a store-level aggregate, not a model: no learned parameters, no fitting,
just paired medians with their counts. It belongs here because it is a fact
about the data, and the engine is not built this session.
"""

from __future__ import annotations

import datetime as _dt
import re
import statistics
from decimal import Decimal
from typing import Optional

# A ratio needs paired observations of the SAME card at the SAME grade from two
# graders, on the same day. Below this many pairs it is not published.
MIN_PAIRS = 20
# And below this many distinct cards, one card's quirk drives the whole number.
MIN_CARDS = 8
# Pairs must be observed within this window of each other, or the "ratio" is
# partly a price move.
MAX_PAIR_LAG_DAYS = 3


class NotEnoughHistory(RuntimeError):
    """Raised rather than returning a thin number. The route comparison's
    mismatch flag is the correct output until this stops firing."""

    def __init__(self, bucket, pairs, cards):
        self.bucket, self.pairs, self.cards = bucket, pairs, cards
        super().__init__(
            f"{bucket}: {pairs} paired sales across {cards} cards; need "
            f"{MIN_PAIRS} pairs across {MIN_CARDS} cards. Until then the "
            "cross-grader comp gap stays flagged rather than estimated.")


# Matched in order, first band wins. Regexes rather than substrings because
# the abbreviations are all substrings of the word `rare`: `"ar" in "rare"` is
# True, and matching that way filed every Art Rare as an ordinary rare. It also
# quietly dropped One Piece Treasure Rares, which are the top chase rarity in
# the game -- ingest/catalog.py tracks only `chase` and `premium`, so both were
# excluded from the target list they most belong in.
_BANDS = (
    ("chase",   r"secret|hyper|special illustration|\bsar\b|\bsir\b|manga|"
                r"signature|treasure|\btr\b|serial"),
    ("premium", r"illustration|ultra|\balt\b|alternate|parallel|full art|"
                r"art rare|\bar\b"),
    ("rare",    r"holo|rare|leader"),
)


def rarity_band(rarity: Optional[str]) -> str:
    """Coarse bands. Finer ones split the sample faster than they add signal,
    and the sample is the binding constraint here."""
    text = (rarity or "").lower()
    for band, pattern in _BANDS:
        if re.search(pattern, text):
            return band
    return "base"


def era_of(release_date) -> str:
    """Calendar-year era. Grading standards and slab preferences move over
    years, not months, so a finer bucket would be noise."""
    if release_date is None:
        return "unknown"
    year = release_date.year if hasattr(release_date, "year") else int(str(release_date)[:4])
    return str(year)


def ratio_table(store, evaluation_timestamp, *, base_grader="PSA",
                other_graders=("CGC", "BGS", "SGC"), grade="10"):
    """Median price ratio of each grader's slab against the base, per bucket.

    Reads through `store.as_of_view`, so nothing observed after the evaluation
    timestamp can reach the number (CLAUDE.md non-negotiable 1).
    """
    prices = store.as_of_view("price_snapshot", evaluation_timestamp)
    rows = store.con.sql(f"""
        SELECT p.card_uid, p.grader, p.grade, p.amount, p.currency,
               CAST(p.as_of AS DATE) AS day, p.sample_size,
               c.game, c.rarity, c.release_date
        FROM ({prices.sql_query()}) p
        JOIN cards c USING (card_uid)
        WHERE p.grade = '{grade}' AND p.grader IS NOT NULL
    """).fetchall()

    # (card, day) -> {grader: (amount, currency)}
    by_card_day = {}
    meta = {}
    for uid, grader, _g, amount, currency, day, _n, game, rarity, release in rows:
        by_card_day.setdefault((uid, day), {})[grader] = (Decimal(str(amount)), currency)
        meta[uid] = (game, rarity_band(rarity), era_of(release))

    buckets = {}
    for (uid, day), by_grader in by_card_day.items():
        base = by_grader.get(base_grader)
        if base is None or base[0] <= 0:
            continue
        game, band, era = meta[uid]
        for grader in other_graders:
            other = by_grader.get(grader)
            if other is None:
                continue
            if other[1] != base[1]:
                # Two currencies is a conversion, not a ratio. Skipped rather
                # than converted: an FX rate applied here would silently become
                # part of a "grader premium".
                continue
            key = (game, band, era, grader)
            buckets.setdefault(key, {"ratios": [], "cards": set()})
            buckets[key]["ratios"].append(float(other[0] / base[0]))
            buckets[key]["cards"].add(uid)

    table = {}
    for (game, band, era, grader), data in buckets.items():
        ratios, cards = data["ratios"], data["cards"]
        entry = {
            "game": game, "rarity_band": band, "era": era,
            "grader": grader, "base_grader": base_grader, "grade": grade,
            "pairs": len(ratios), "cards": len(cards),
            "sufficient": len(ratios) >= MIN_PAIRS and len(cards) >= MIN_CARDS,
        }
        if entry["sufficient"]:
            entry["median_ratio"] = round(statistics.median(ratios), 4)
            entry["iqr"] = round(
                statistics.quantiles(ratios, n=4)[2]
                - statistics.quantiles(ratios, n=4)[0], 4) if len(ratios) >= 4 else None
        else:
            entry["median_ratio"] = None
            entry["iqr"] = None
            entry["unavailable_reason"] = "sample_below_minimum"
        table[f"{game}|{band}|{era}|{grader}"] = entry
    return table


def ratio_for(store, evaluation_timestamp, *, game, rarity, release_date,
              grader, base_grader="PSA", grade="10"):
    """One bucket, or a refusal naming what is missing.

    Refuses rather than falling back to a coarser bucket. A national average
    used as a per-card discount is the kind of number that looks like evidence
    and is not.
    """
    table = ratio_table(store, evaluation_timestamp, base_grader=base_grader,
                        other_graders=(grader,), grade=grade)
    key = f"{game}|{rarity_band(rarity)}|{era_of(release_date)}|{grader}"
    entry = table.get(key)
    if entry is None:
        raise NotEnoughHistory(key, 0, 0)
    if not entry["sufficient"]:
        raise NotEnoughHistory(key, entry["pairs"], entry["cards"])
    return entry
