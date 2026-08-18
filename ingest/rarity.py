"""Rarity: the field that was absent, filtered on anyway, and cost 8,313 cards.

WHAT WENT WRONG. tcgdex's brief card object -- what `GET /v2/{lang}/cards` and
the `cards[]` array inside `GET /v2/{lang}/sets/{setId}` return -- carries only
`id`, `localId`, `name` and `image`. There is no `rarity`. The catalog builder
filtered on `rarity` anyway, every card scored `base`, and 8,313 cards produced
zero matches. The filter was not too tight; it was reading a field that was
never there.

THE RULE THAT FOLLOWS, and it is the whole point: **an absent rarity is
UNKNOWN, never "not a chase card".** Those are different claims and only one of
them is true. `band_of(None)` returns `unknown`, `unknown` is a TRACKED band,
and the count of unresolved rarities is reported rather than absorbed. Tracking
a card we cannot classify costs quota; dropping one loses a chase card and says
nothing.

THE ENUM IS VERBATIM FROM SOURCE. Fetched from
tcgdex/cards-database/master/interfaces.d.ts on 2026-08-17, not transcribed
from documentation. It has **43** members, and the casing is inconsistent in
the source itself -- `Double rare` and `Ultra Rare` and `Shiny rare V` all
coexist -- so every comparison here is against a normalised form. The
maintainers note the vocabulary is still being aligned to official lists, so
an unrecognised string is `unknown`, never `base`.

WHAT IS NOT HERE. tcgdex normalises Japanese-system rarities into English
strings: SAR is `Special illustration rare`, AR is `Illustration rare`. There
is no `Trainer Gallery Rare Holo`, and no AR/SAR/SR/UR abbreviations. Other
providers do NOT do this -- apitcg returns One Piece's native `R` / `SR` /
`SEC` / `TR` in `attributes.Rarity` -- so provider-native strings fall through
to `store.cross_grader.rarity_band`.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.cross_grader import rarity_band                        # noqa: E402

UNKNOWN = "unknown"

# Verbatim from interfaces.d.ts. Grouped as the source groups them, including
# the comments that explain why a group exists.
TCGDEX_RARITIES = (
    # The main union, alphabetical in source.
    "ACE SPEC Rare", "Amazing Rare", "Classic Collection", "Common",
    "Double rare", "Full Art Trainer", "Holo Rare", "Holo Rare V",
    "Holo Rare VMAX", "Holo Rare VSTAR", "Hyper rare", "Illustration rare",
    "LEGEND", "None", "Radiant Rare", "Rare", "Rare Holo", "Rare Holo LV.X",
    "Rare PRIME", "Secret Rare", "Shiny Ultra Rare", "Shiny rare",
    "Shiny rare V", "Shiny rare VMAX", "Special illustration rare",
    "Ultra Rare", "Uncommon",
    # Black White rare
    "Black White Rare", "Mega Hyper Rare", "Triple Rare",
    # Japanese Character Rares (since SM11b Dream League)
    "Character Rare", "Character Super Rare",
    # Pokémon TCG Pocket Rarities
    "One Diamond", "Two Diamond", "Three Diamond", "Four Diamond",
    "One Star", "Two Star", "Three Star", "Crown", "One Shiny", "Two Shiny",
    "Promo",
)

# Which band each one falls in. A table, not a regex, because this vocabulary
# is closed and a regex over a closed set is a guess where a lookup is a fact.
#
# `chase` is where the gem premium is large relative to the grading fee.
# `premium` is the tier below. Everything else cannot repay a submission.
_CHASE = {
    "Special illustration rare", "Hyper rare", "Secret Rare", "Ultra Rare",
    "Shiny Ultra Rare", "Radiant Rare", "Amazing Rare", "ACE SPEC Rare",
    "LEGEND", "Classic Collection", "Mega Hyper Rare", "Black White Rare",
    "Rare Holo LV.X", "Rare PRIME",
    # Japanese-system chase. These matter more here than anywhere else: this
    # project tracks JP and both Chinese printings, and omitting them would
    # repeat the exact bug this module exists for.
    "Character Super Rare",
}
_PREMIUM = {
    "Illustration rare", "Triple Rare", "Shiny rare", "Shiny rare V",
    "Shiny rare VMAX", "Full Art Trainer", "Holo Rare V", "Holo Rare VMAX",
    "Holo Rare VSTAR", "Promo", "Character Rare",
}
# `Double rare` is the ordinary two-star `ex`, which sells for a couple of
# dollars and cannot repay a submission at any probability. It reads like a
# chase tier and is not one -- filing it as `premium` would have tracked
# several thousand cheap cards per set.
_RARE = {"Double rare", "Rare", "Rare Holo", "Holo Rare"}
_BASE = {"Common", "Uncommon", "None"}

# Pokémon TCG Pocket is a DIGITAL game. Its cards have no physical printing, so
# there is nothing to grade, nothing to submit and no population to read --
# they are not cheap cards, they are not cards. Given their own band rather
# than squeezed into `base`, so that a Pocket rarity appearing in a physical
# dataset is visible as the anomaly it would be.
_DIGITAL = {
    "One Diamond", "Two Diamond", "Three Diamond", "Four Diamond",
    "One Star", "Two Star", "Three Star", "Crown", "One Shiny", "Two Shiny",
}


# ---------------------------------------------------------------------------
# Per-game vocabularies, from the games' own data
# ---------------------------------------------------------------------------
#
# `rarity_band` was wrong twice -- Art Rares and Treasure Rares filed as
# ordinary rares, then One Piece `SR` and `SEC` filed as base. Both times a
# regex over an OPEN set of strings guessed, and guessed low. A third instance
# was waiting: three of Riftbound's seven rarities (`Epic`, `Showcase`,
# `Overnumbered`) scored `base`, and Overnumbered is its chase treatment.
#
# So the vocabularies are read from the games' own data rather than imagined:
# github.com/apitcg/{game}-tcg-data, observed 2026-08-17, distinct values of
# `rarity` across every card file. The strings are checked into
# contracts/rarity_vocabulary.json and tests/test_rarity.py asserts that EVERY
# one of them maps to a named band. An unmapped string is `unknown` -- tracked
# and NAMED in the summary -- never silently `base`.
#
# Each game gets its own table because the same letters mean different things:
# `R` is Rare in One Piece and Union Arena, `P` is Promo in One Piece and
# Gundam, `L` is Leader in One Piece and Legend in Dragon Ball.

GAME_BANDS = {
    # Riftbound. Its vocabulary is nothing like Pokemon's, and the tiers that
    # matter are treatments rather than rarities. CLAUDE.md holds Riftbound to
    # exploratory status -- the game launched late 2025 and there is not enough
    # history for a statistical claim -- so all four special tiers are tracked
    # and none is assumed cheap.
    # RIFTBOUND. Band is a function of the COLLECTOR NUMBER here, not the
    # rarity string -- see NUMBER_DEPENDENT_GAMES and `_riftbound_band`. This
    # table is only the fallback for cards whose number says nothing.
    #
    # Checked against market data 2026-08-17: of the top 16 most valuable
    # singles, every one is Metal, Signature, Ultimate or an event promo. No
    # plain Overnumbered until #17. Zero Epics and zero plain Alt-Art appear at
    # all, which is why Epic moved premium -> rare: Riot's designer puts it at
    # roughly one in four packs, about six a box, singles $5-55.
    "riftbound": {
        "Common": "base", "Uncommon": "base",
        "Rare": "rare",
        "Epic": "rare",
        # The umbrella. On its own it means nothing -- three treatments at
        # $40 to $3,090 all print this string -- so a Showcase whose number
        # cannot be read is UNKNOWN rather than banded on the word.
        "Showcase": UNKNOWN,
        "Alternate Art": "rare",
        "Overnumbered": "premium",
        # Added this session; absent from the observed apitcg data because that
        # repository stops at Spiritforged and these arrive later.
        "Signature": "chase",
        "Metal": "chase",
        "Prize Wall": "chase",
        "Ultimate Rare": "chase",      # Unleashed onward, Baron Nashor first
        "Promo": UNKNOWN,              # a few dollars to $1,300; see below
    },
    # One Piece, via apitcg's `attributes.Rarity`.
    "optcg": {
        "C": "base", "UC": "base", "R": "rare",
        # Parallel Rare -- a foil treatment of a card that also exists in a
        # plain printing, so it is BOTH a band and a variant. Note that
        # `PR` means Promo in Dragon Ball Fusion: the same two letters, two
        # games, two meanings, which is the whole reason these tables are
        # per-game rather than shared.
        "PR": "premium",
        "L": "rare",            # Leader; the ordinary printing
        "SR": "premium",
        "P": "premium",         # Promo
        "SEC": "chase",         # Secret Rare
        "TR": "chase",          # Treasure Rare
        "SP CARD": "chase",     # signed / special treatment
    },
    "dragon-ball-fusion": {
        "C": "base", "UC": "base", "R": "rare", "L": "rare",
        "SR": "premium", "PR": "premium",
        "SCR": "chase",         # Secret Rare -- `\bsec\b` never matched it
    },
    "gundam": {
        "C": "base", "U": "base", "R": "rare",
        "P": "premium",
        "LR": "chase",          # Legendary Rare
    },
    "union-arena": {
        "C": "base", "U": "base", "R": "rare",
        "SR": "premium",
        "UR": "chase",
    },
    # apitcg's Pokemon vocabulary is TCGplayer-style and is NOT tcgdex's. Both
    # are served, so both are mapped; normalisation makes the overlapping ones
    # (`Illustration Rare` / `Illustration rare`) one entry.
    "pkmn": {
        # Named by run #9's summary as unmapped. All real tiers except the last.
        "Rainbow Rare": "chase",
        # Shiny Vault / Gold Star territory. High value, and it reads like an
        # ordinary holo, which is precisely the trap this table exists for.
        "Shiny Holo Rare": "chase",
        "Prism Rare": "premium",
        # NOT a rarity. A placeholder the source writes when it does not know,
        # so it maps to UNKNOWN deliberately -- tracked, and no longer reported
        # as "nobody has classified this", because somebody has: it classifies
        # as "the source is not telling us".
        "Unconfirmed": UNKNOWN,
        "Rare Ultra": "chase", "Rare Secret": "chase",
        "Rare Rainbow": "chase", "Rare Shining": "chase",
        "Rare ACE": "chase",
        # Gold Star. Among the most valuable Pokemon cards there are, and it
        # scored `rare` because the string contains the word.
        "Rare Holo Star": "chase",
        "Rare Holo EX": "premium", "Rare Holo GX": "premium",
        "Rare Holo V": "premium", "Rare Holo VMAX": "premium",
        "Rare Holo VSTAR": "premium", "Rare Shiny": "premium",
        "Rare Shiny GX": "premium", "Rare Prism Star": "premium",
        # tcgdex has no such string; apitcg does. Both are real.
        "Trainer Gallery Rare Holo": "premium",
        "Rare BREAK": "rare",
    },
    # Digimon's repository carries no `rarity` on any card. Every one of them
    # classifies `unknown`, which is the correct and useful answer.
    "digimon": {},
}

# Markers that indicate a PARALLEL treatment rather than a rarity tier, and are
# stripped before the band lookup. Gundam writes `LR                +` and
# Union Arena writes `SR★★`; both are the same rarity with a different finish.
# Normalisation drops them for banding, and resolve.identity turns them into
# the `parallel` variant, so the information is moved rather than lost.
PARALLEL_MARKERS = ("+", "★", "☆", "*")


def normalise(rarity) -> str:
    """Case- and separator-insensitive form.

    The source casing is inconsistent (`Double rare`, `Ultra Rare`, `Shiny rare
    V`) and the maintainers say it is still being aligned, so nothing here may
    depend on the casing being what it is today.
    """
    return "".join(ch for ch in str(rarity or "").lower()
                   if ch.isalnum())


_BY_NORM = {}
for _group, _band in ((_CHASE, "chase"), (_PREMIUM, "premium"),
                      (_RARE, "rare"), (_BASE, "base"),
                      (_DIGITAL, "digital")):
    for _name in _group:
        _BY_NORM[normalise(_name)] = _band

# Every member of the enum must be classified. A new rarity added upstream and
# left out of the tables would silently become `unknown`, which is safe, but
# one already in the enum and unclassified is an oversight -- asserted in
# tests/test_rarity.py rather than trusted.
UNCLASSIFIED = tuple(r for r in TCGDEX_RARITIES if normalise(r) not in _BY_NORM)

# game -> {normalised rarity: band}
_BY_GAME = {game: {normalise(k): v for k, v in table.items()}
            for game, table in GAME_BANDS.items()}


# ---------------------------------------------------------------------------
# Games where the band cannot be read off the rarity string
# ---------------------------------------------------------------------------
#
# Riftbound's `Showcase` covers Signature ($300-3,090), Overnumbered ($75-660)
# and Alternate Art ($40-90). One string, a seventy-fold spread. The collector
# number is what separates them, so for these games the number is REQUIRED and
# calling without one raises rather than quietly banding on the word.
#
# Declaring it here rather than checking `if game == "riftbound"` at each call
# site is the point: the next game that does this gets added to one set, and
# every caller is already correct.
NUMBER_DEPENDENT_GAMES = frozenset({"riftbound"})


class NumberRequired(ValueError):
    """A band was asked for without the collector number that determines it."""


# Core champions whose Alternate Art sits at premium rather than rare. EMPTY,
# and deliberately so: the distinction is real -- the market separates a core
# champion's alt-art from an ordinary one -- but no champion list has been
# verified, and inventing one would be the guessing this module exists to stop.
# Until it is populated every Alt-Art bands `rare`.
RIFTBOUND_CORE_CHAMPIONS: frozenset = frozenset()


def string_band(rarity, game=None) -> str:
    """Table lookup only. No number, no inference.

    This is the question `unmapped()` asks -- "does any table know this
    string?" -- and it is a DIFFERENT question from what band a given card is
    in. For a number-dependent game the string alone genuinely cannot answer
    the second one.
    """
    if rarity is None or str(rarity).strip() == "":
        return UNKNOWN
    key = normalise(rarity)
    if game:
        hit = _BY_GAME.get(game, {}).get(key)
        if hit is not None:
            return hit
    hit = _BY_NORM.get(key)
    return UNKNOWN if hit is None else hit


def _riftbound_band(rarity, number, set_size=None) -> str:
    """Number first, string second. Never the other way round.

    Order matters and follows the market: an asterisk outranks everything, a
    suffix outranks position, and position outranks the printed rarity.
    """
    from resolve.identity import parse_collector_number

    parsed = parse_collector_number(number)

    if parsed.starred:
        return "chase"                      # Signature -- the booster chase
    if parsed.kind == "token":
        return "base"
    if parsed.kind == "rune":
        # A plain rune is bulk; a Showcase rune is not, but it is not a chase
        # either.
        return "rare" if parsed.suffix else "base"
    if parsed.suffix == "b":
        # Promo. The number says it is one and says nothing about which: the
        # range runs from a few dollars to $1,300, spanning three bands. So it
        # is UNKNOWN -- tracked and named -- rather than banded on a coin flip.
        return UNKNOWN
    if parsed.suffix == "a":
        return "premium" if _is_core_champion(rarity) else "rare"
    if parsed.above_set_size(set_size):
        return "premium"                    # Overnumbered, no asterisk

    # The number said nothing distinguishing. Fall back to the string, which
    # for `Showcase` and `Promo` correctly answers UNKNOWN.
    return string_band(rarity, "riftbound")


def _is_core_champion(_rarity) -> bool:
    # Placeholder for the unresolved distinction above. Always False while
    # RIFTBOUND_CORE_CHAMPIONS is empty; kept as a named function so the
    # question is findable rather than buried in a conditional.
    return False


def band_of(rarity, *, game=None, number=None, set_size=None,
            provider_native: bool = False) -> str:
    """Rarity -> band. Absent or unrecognised -> `unknown`, never `base`.

    For a game in `NUMBER_DEPENDENT_GAMES` the collector number is REQUIRED and
    its absence raises `NumberRequired`. That is deliberately noisy: banding a
    Riftbound card on its rarity string alone cannot distinguish a $3,000
    Signature from a $50 Alternate Art, and a wrong answer there is worth more
    than a crash.
    """
    if game in NUMBER_DEPENDENT_GAMES:
        if number in (None, ""):
            raise NumberRequired(
                f"{game} bands on the collector number, not the rarity string "
                f"-- `Showcase` alone covers Signature, Overnumbered and "
                f"Alternate Art at $40 to $3,090. band_of(rarity={rarity!r}, "
                f"game={game!r}) needs number=.")
        if game == "riftbound":
            return _riftbound_band(rarity, number, set_size)

    hit = string_band(rarity, game)
    if hit != UNKNOWN:
        return hit
    if provider_native and rarity not in (None, "") and str(rarity).strip():
        # The legacy regex. Kept for `store.cross_grader` bucketing, where a
        # coarse guess beats dropping a sale from a ratio -- but it answers
        # `base` for anything it does not know, so the catalog filter must NOT
        # use it.
        return rarity_band(rarity)
    return UNKNOWN


def unmapped(strings, game=None) -> list:
    """Which of these strings no table covers. The summary names them.

    An unmapped string is not an error -- new sets add rarities and the correct
    response is to track them until someone classifies them. It is a finding,
    and a finding that is not named is a finding that is lost.
    """
    return sorted({str(s) for s in strings
                   if s not in (None, "") and string_band(s, game) == UNKNOWN
                   and _BY_GAME.get(game, {}).get(normalise(s)) != UNKNOWN})


def every_known_string():
    """Every rarity string any table covers, for the coverage assertion."""
    out = set(TCGDEX_RARITIES)
    for table in GAME_BANDS.values():
        out |= set(table)
    return out


# Bands worth spending price quota on.
#
# `unknown` IS tracked, deliberately. It is the residue after the English
# fallback, and tracking it costs quota while dropping it loses chase cards
# silently -- which is exactly the trade run #7 got backwards. The count is
# reported prominently so a large residue is a visible decision rather than an
# invisible loss.
TRACKED_BANDS = ("chase", "premium", UNKNOWN)


def resolve_rarity(card, english_by_id=None):
    """(rarity, source). Falls back to the English card of the same id.

    tcgdex ids are stable across languages and English is the most complete
    dataset, so a Chinese card that omits `rarity` can usually borrow it. The
    source of the classification is returned alongside it and stored as
    `rarity_from`, because a borrowed rarity is a weaker claim than a printed
    one and the difference has to survive into the row.

    CAVEAT CARRIED FROM THE BRIEF: that rarity is a plain string enum rather
    than a localised `Languages<T>` -- and therefore identical across
    languages -- is derived from the schema, not from an observed Chinese
    response body. `ingest.catalog --rarities` is the empirical check.
    """
    rarity = card.get("rarity")
    if rarity not in (None, ""):
        return rarity, "self"
    parent = (english_by_id or {}).get(card.get("id") or card.get("card_id"))
    if parent and parent.get("rarity") not in (None, ""):
        return parent["rarity"], "en_fallback"
    return None, "absent"
