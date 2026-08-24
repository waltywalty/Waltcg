"""Card identity, and the boundary between our codes and providers' codes.

There are two vocabularies in this system and they must never mix.

INTERNAL — ours, stable, ours to change only deliberately. These are the only
values that may appear in a `card_uid`:

    card_uid = {game}:{set_code}:{number}:{variant}:{language}
    game     in {optcg, pkmn, riftbound}
    language in {EN, JP, CN-S, CN-T}

EXTERNAL — whatever each provider happens to call the same game today.
apitcg.com uses hyphenated string slugs ("one-piece"). tcgapi.dev uses opaque
numeric ids discovered at runtime from /v1/games ("11", "55", "19"), and
models language as SEPARATE GAME ENTRIES rather than a parameter, so a
provider game id encodes language while ours does not.

These are both correct. The bug is not having two vocabularies; the bug is
letting one leak into the other. A provider slug inside a `card_uid` makes the
identifier unstable the moment a provider renames a game, and silently
repartitions history. So the mapping is explicit, one-directional at the
boundary, and `card_uid()` refuses anything that is not an internal code.
"""

from __future__ import annotations

import re
from typing import Optional

# -- internal vocabulary ---------------------------------------------------

class IdentityError(ValueError):
    """A provider vocabulary reached a place only internal codes may go."""


GAMES = ("optcg", "pkmn", "riftbound")
LANGUAGES = ("EN", "JP", "CN-S", "CN-T")

# Which physical printing of a collector number this is. `card_uid` does not
# validate against this list -- a new set can invent a treatment we have never
# seen and refusing it would lose the card -- but everything that GENERATES a
# variant draws from here, so a typo does not quietly create a second card.
#
# Four of these exist because the number alone does not identify the card:
# `treasure_rare` and `serialized` are printed AT the base card's number, and
# `ar`/`sar` are separate printings of art that also exists at a base number.
# Tokens every game may use. A printing treatment that means the same thing
# wherever it appears belongs here; anything whose meaning depends on the game
# belongs in GAME_VARIANTS below, and the difference is not stylistic.
SHARED_VARIANTS = ("base", "parallel", "alt_art", "promo", "serialized",
                   "reprint", "holo")

# PER GAME, exactly like the rarity band tables and for the third time the same
# reason. `SR` is a RARITY BAND in One Piece -- an ordinary Super Rare, one of
# the commonest cards worth tracking -- and a PRINTING TREATMENT in Pokemon,
# where a Super Rare is a specific full-art textured finish. A shared table
# would have to pick one meaning, and picking is guessing.
#
# The collisions this file has already survived say the same thing three times:
#   `R`, `P`, `L`, `PR`, `LR` mean different things per game  (rarity letters)
#   `Showcase` means nothing without a collector number       (band tables)
#   `SR` is a band here and a printing there                  (this table)
GAME_VARIANTS = {
    "pkmn": (
        # Japanese and Chinese printing tiers, as the market names them.
        "ar",              # Illustration Rare
        "sar",             # Special Illustration Rare, JP/CN convention
        "sir",             # the same art, EN convention -- see _SIR_BY_LANGUAGE
        "sr",              # Super Rare: full-art textured. NOT One Piece's SR
        "ur",              # Ultra Rare, gold
        "hr",              # Hyper Rare, rainbow. SM/SWSH era
        "ssr",             # Simplified Chinese
        "rainbow_secret",  # EN naming for the rainbow secret
        "gold_secret",     # EN naming for the gold secret
    ),
    "optcg": (
        "manga_rare",      # manga-panel alt art
        "treasure_rare",   # TR
    ),
    "riftbound": (
        "overnumbered",    # above the set size, no asterisk
        "signature",       # asterisk
        "sp",              # Vendetta SP
    ),
}

#: Every token, for reporting. NOT the validity test -- `is_variant` is
#: per-game, and a flat membership check is what let `sr` look valid for One
#: Piece in the first place.
VARIANTS = tuple(dict.fromkeys(
    SHARED_VARIANTS + tuple(t for tokens in GAME_VARIANTS.values()
                            for t in tokens)))


def variants_for(game=None) -> tuple:
    """Tokens valid for this game. Every token when `game` is None.

    None means "we do not know the game", and that has to accept everything --
    refusing would make a game-agnostic caller reject valid rows. Callers that
    know the game must pass it.
    """
    if game is None:
        return VARIANTS
    return tuple(dict.fromkeys(SHARED_VARIANTS + GAME_VARIANTS.get(game, ())))


def why_not_a_variant(token, game=None) -> str:
    """Why this token was refused, in words that name the next action.

    "unknown variant" sends you to guess. "`sr` is a Pokemon printing and this
    is a One Piece card; One Piece SR is a RARITY, not a variant" tells you
    the row is wrong rather than the vocabulary.
    """
    text = str(token or "")
    if is_variant(text, game):
        return ""
    elsewhere = sorted(other for other, tokens in GAME_VARIANTS.items()
                       if text in tokens and other != game)
    if elsewhere:
        return (f"variant {text!r} is valid for "
                + ", ".join(f"`{g}`" for g in elsewhere)
                + f" but not for `{game}`. The same letters mean different "
                  "things per game -- One Piece `SR` is a RARITY BAND, "
                  "Pokemon `SR` is a printing treatment -- so either the row "
                  "names the wrong game or it wants a different token. "
                  f"Valid for `{game}`: "
                + ", ".join(f"`{t}`" for t in variants_for(game)))
    return (f"variant {text!r} is not a token this project produces for "
            f"`{game}`. Valid: " + ", ".join(f"`{t}`" for t in variants_for(game)))

# A game may print the SAME collector number several times with different
# treatments -- One Piece prints up to seven parallels of one card, all at
# `EB01-006`. So `parallel` alone cannot separate them, and separating them is
# not optional: non-negotiable 3 says every printing is a different card.
# `parallel` is the first, `parallel2`..`parallelN` the rest.
_NUMBERED_VARIANTS = ("parallel", "reprint")


def is_variant(token, game=None) -> bool:
    """Is this a variant token this project can produce FOR THIS GAME?

    Not an equality test against a flat vocabulary, for two reasons. The
    numbered treatments are open-ended -- a set that ships an eighth parallel
    needs no code change to be identifiable, only to be understood. And the
    vocabulary is per game: `sr` is valid for Pokemon and invalid for One
    Piece, where those two letters name a rarity band instead.
    """
    text = str(token or "")
    allowed = variants_for(game)
    if text in allowed:
        return True
    stem = text.rstrip("0123456789")
    return (stem in _NUMBERED_VARIANTS and stem in allowed and stem != text
            and text[len(stem):] not in ("0", "1"))

# Which languages each game actually ships in. Riftbound is English-only;
# there is no Japanese release (see probe/COVERAGE.md).
GAME_LANGUAGES = {
    "optcg": ("EN", "JP", "CN-S"),
    "pkmn": ("EN", "JP", "CN-S", "CN-T"),
    "riftbound": ("EN",),
}

# -- how each printing numbers itself --------------------------------------
#
# The two Chinese Pokémon printings behave in OPPOSITE ways, and a scheme that
# handles one wrong-way-round is wrong for the other:
#
#   CN-T  reuses the Japanese collector numbers VERBATIM and marks the set code
#         with an F suffix. Same art, same number, different card. Matching on
#         (game, number) alone therefore MERGES a Traditional Chinese card into
#         its Japanese parent -- which is the exact failure card_uid.md exists
#         to prevent, and the only thing standing in the way is `language`.
#
#   CN-S  renumbers into combined sets, so the SAME art carries a DIFFERENT
#         number from its Japanese parent. Matching on (game, number) alone
#         therefore MISSES it entirely -- the opposite failure, from the same
#         naive rule, in the same game.
#
# Both are recorded because the useful thing is that they disagree. Any code
# that treats "Chinese Pokémon" as one behaviour is wrong for half of it.
NUMBERING_PARENT = {"CN-T": "JP"}
RENUMBERED = frozenset({"CN-S"})

# The exact set codes external research recorded for the Traditional Chinese
# printings, against their Japanese parents. Two observations, kept as DATA
# rather than folded into a casing rule -- `sv2a -> SV2aF` uppercases the
# alphabetic prefix and leaves the trailing `a` alone, and two examples is not
# enough to say whether that is the rule or a coincidence of these two codes.
# `traditional_chinese_set_code` therefore compares case-INSENSITIVELY and
# does not attempt to reproduce the casing.
OBSERVED_TC_SET_CODES = {"sv2a": "SV2aF", "s7R": "S7RF"}

# Denominators that appear in listings for a card and are NOT that card's.
#
# A wrong denominator is the most dangerous kind of near-miss: it looks like a
# collector number, it parses like one, and it points at a printing in another
# market with its own price series. Recorded per card so a labelled row can be
# checked against it rather than against memory.
#
#   Rayquaza VMAX, s7R -- the Japanese card is 083/067. Listings carrying
#   083/069 are quoting the KOREAN printing's denominator; Korean is not a
#   printing this project tracks, so 083/069 is not "a different card we have",
#   it is a number that must not resolve to the Japanese one either.
KNOWN_CONFUSABLE_NUMBERS = {
    ("pkmn", "s7R", "Rayquaza VMAX"): {
        "correct": "083/067",
        "confusable": ("083/069",),
        "why": ("083/069 is the Korean printing's denominator. Korean is not "
                "in LANGUAGES, so this number belongs to no card this project "
                "tracks and must resolve to none."),
        "source": "external_research",
    },
}


# Set codes a source spelled differently from the catalog.
#
# A labelled row's IDENTITY is non-circular -- it came from outside the
# catalogs the resolver reads -- but its set_code is a KEY, and a key that
# matches nothing scores nothing. So the code is normalised to whatever the
# catalog uses, and the normalisation is declared here rather than applied
# silently at the point of import: an alias is a claim that two spellings name
# one set, and a claim belongs somewhere it can be checked.
#
# Each entry records what it was VERIFIED against, because "SV: 151 is
# probably sv151" is a guess and "sv03.5 holds 199 Charizard ex and 205 Mew ex,
# which is what the row says" is a check.
SET_CODE_ALIASES = {
    ("pkmn", "EN", "sv151"): {
        "code": "sv03.5",
        "why": "source said `SV: 151`; a colon cannot survive a "
               "colon-delimited card_uid",
        "verified_against": "ingest/targets.json -- sv03.5 holds 199 Charizard "
                            "ex and 205 Mew ex, matching the rows",
    },
    ("pkmn", "EN", "sv1"): {
        "code": "sv01",
        "why": "the catalog numbers Scarlet & Violet sets `sv01`..`sv10`",
        "verified_against": "apitcg sv1.json holds 258 cards with 13 "
                            "Sprigatito, 36 Fuecoco, 52 Quaxly, 60 Cetitan, "
                            "120 Sandaconda and 122 Klawf -- the six rows; "
                            "ingest/targets.json carries the same set as sv01",
    },
    ("pkmn", "EN", "cel"): {
        "code": "cel25cc",
        "why": "Celebrations splits into the main set and the Classic "
               "Collection; these rows are the Classic Collection",
        "verified_against": "apitcg cel25c.json holds 4 Charizard, 2 "
                            "Blastoise, 8 Dark Gyarados and 17 Umbreon -- "
                            "exactly the four rows; ingest/targets.json "
                            "carries the Classic Collection as cel25cc. NOTE: "
                            "tcgdex RENUMBERS it CC001.. so the catalog will "
                            "not match these rows by number, and the bridge "
                            "refuses rather than guessing.",
    },
    ("pkmn", "EN", "tr"): {
        "code": "base5",
        "why": "Team Rocket is the fifth Base-era set",
        "verified_against": "apitcg base5.json holds 83 cards with 8 Dark "
                            "Gyarados -- the row",
    },
    ("pkmn", "EN", "pgo"): {
        "code": "swsh10.5",
        "why": "Pokemon GO is SWSH10.5",
        "verified_against": "ingest/targets.json holds swsh10.5 011 Radiant "
                            "Charizard -- the row exactly, index and all",
    },
    ("pkmn", "EN", "crz"): {
        "code": "swsh12.5",
        "why": "Crown Zenith is SWSH12.5",
        "verified_against": "ingest/targets.json holds swsh12.5 020 Radiant "
                            "Charizard -- the row exactly, index and all",
    },
    ("pkmn", "EN", "swsh07"): {
        "code": "swsh7",
        "why": "source said `SWSH07`; the catalog does not zero-pad",
        "verified_against": "ingest/targets.json -- swsh7 holds 94 Umbreon V, "
                            "95 Umbreon VMAX and 111 Rayquaza VMAX, which is "
                            "Evolving Skies",
    },
}


# Set codes a source spelled its own way that we could NOT reconcile, and why.
#
# Recorded rather than left silent: an unaliased code and an unverifiable one
# look identical from the outside, and only one of them is a decision. These
# pass through untouched, which is the same behaviour as any unknown code --
# the difference is that somebody has now looked.
UNVERIFIED_SET_CODES = {
    ("pkmn", "EN", "mcd2023"): "McDonald's 2023. The apitcg snapshot on hand "
                               "stops at mcd22 and the catalog tracks no "
                               "McDonald's set, so there is nothing to check "
                               "the spelling against.",
    ("pkmn", "JP", "s10b"): "Japanese Pokemon GO. The catalog's Japanese set "
                            "codes come from a different scheme entirely "
                            "(SM10, SM12a, SV11B), and the local snapshot "
                            "holds English only.",
    ("pkmn", "JP", "s12a"): "VSTAR Universe. Same reason as s10b -- the "
                            "catalog's Japanese codes are a different scheme "
                            "and the local snapshot is English only.",
}


def canonical_set_code(game, language, set_code):
    """(code, alias_entry_or_None). Unknown codes pass through unchanged.

    Passing through is the right default: this table is a list of spellings we
    have RECONCILED, not a whitelist of sets that exist. A code absent from it
    is a code nobody has checked, which is different from a wrong one.
    """
    entry = SET_CODE_ALIASES.get((game, language, str(set_code or "")))
    return (entry["code"], entry) if entry else (set_code, None)


def confusable_numbers(game, set_code, name) -> tuple:
    """Numbers seen in listings for this card that are not its number."""
    entry = KNOWN_CONFUSABLE_NUMBERS.get((game, set_code, name))
    return tuple(entry["confusable"]) if entry else ()

# Documented for CN-T. There is no equivalent entry for CN-S: both Simplified
# sets we have externally-verified identities for (151C, csv6C) happen to end
# in C, but two observations is not a naming rule and nothing enforces it.
SET_CODE_SUFFIX = {"CN-T": "F"}


def shares_numbering_with(language: str) -> Optional[str]:
    """The printing whose collector numbers this one reuses verbatim, if any.

    Returns None for a language that numbers itself, INCLUDING one that
    renumbers -- `renumbers(language)` is the separate question.
    """
    return NUMBERING_PARENT.get(language)


# Games where ONE COLLECTOR NUMBER DENOTES ONE CARD IN EVERY LANGUAGE.
#
# One Piece prints `OP01-002` on the English, Japanese and Simplified Chinese
# printings of the same card -- Bandai runs one code system across all three.
# So a number that names Trafalgar Law in English cannot name Monkey D. Luffy
# in Chinese, and if it does, one of the rows is wrong.
#
# NOT Pokemon: `173/165` is a different card from `173/151`, which is the whole
# CN-S renumbering problem. Applying this check there would report every
# Simplified Chinese card as a contradiction.
SHARED_NUMBERING_GAMES = frozenset({"optcg"})


def shares_numbering_across_languages(game) -> bool:
    return game in SHARED_NUMBERING_GAMES


def normalise_name(name) -> str:
    """A name reduced to what survives translation of punctuation.

    `Monkey.D.Luffy` and `Monkey D. Luffy` are one card written two ways; the
    comparison must not care. `Trafalgar Law` and `Monkey D. Luffy` are two
    cards, and it must.
    """
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def is_latin_name(name) -> bool:
    """Is this name written in the Latin script?

    `モンキーdルフィ` and `路飞` are `Monkey.D.Luffy` in two other scripts, and
    nothing here can tell you that -- it would need a translation table this
    project does not have. So a cross-script pair is NOT COMPARABLE, which is
    a third answer and not the same as agreeing or disagreeing. Comparing them
    anyway would report every correctly-translated card as a contradiction and
    bury the real one.
    """
    text = str(name or "")
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and all(ch.isascii() for ch in letters)


def cross_language_name_disagreements(cards):
    """Rows where one collector number names two different cards.

    THE CHECK THAT CATCHES A TRANSCRIPTION SWAP. Batch 2 recorded
    `OP01-002` as Monkey D. Luffy and `OP01-003` as Trafalgar Law in
    Simplified Chinese; English and Japanese had them the other way round.
    Nothing in a single row is wrong -- the uid is right, the number is right,
    the name is a real card's name -- and it is only visible across languages.

    Returns [(game, set_code, number, {normalised name: [card_uid, ...]}), ...].
    Only for games in `SHARED_NUMBERING_GAMES`; anywhere else a differing name
    at one number is expected rather than suspicious.
    """
    import collections as _collections
    groups = _collections.defaultdict(lambda: _collections.defaultdict(list))
    for card in cards:
        game = card.get("game")
        if not shares_numbering_across_languages(game):
            continue
        # LATIN ONLY. A Japanese or Chinese name for the same card is a
        # translation, not a contradiction, and this cannot tell the two
        # apart -- see `is_latin_name`.
        if not is_latin_name(card.get("name")):
            continue
        key = (game, str(card.get("set_code") or "").lower(),
               card.get("number"))
        groups[key][normalise_name(card.get("name"))].append(card["card_uid"])
    return [(key[0], key[1], key[2], dict(names))
            for key, names in sorted(groups.items()) if len(names) > 1]


# Games whose REPRINTS KEEP THE ORIGINAL COLLECTOR NUMBER.
#
# One Piece PRB-01 reprints of OP01-120, OP01-024, OP02-004, OP03-123 and
# OP04-044 all retain their `OPxx-xxx`. `PRB01-xxx` numbers are used ONLY for
# that set's new cards. So a One Piece reprint produces NO new identifier: it
# is the same number in a different product with a new treatment, and the only
# field separating the two rows is the set code.
#
# Structurally identical to Celebrations Classic Collection retaining Base Set
# numbering -- which is why both carry the kind
# `same_number_different_product` rather than each getting a game-specific one.
REPRINTS_KEEP_THEIR_NUMBER = frozenset({"optcg"})


def reprint_keeps_its_number(game) -> bool:
    return game in REPRINTS_KEEP_THEIR_NUMBER


# Languages whose set code is DERIVED from a parent language's, and the suffix.
#
# CN-T only, and the restriction is the point. Traditional Chinese mirrors the
# Japanese set exactly -- `sv2a` -> `SV2aF`, same collector numbers -- so its
# code can be derived. SIMPLIFIED CHINESE CANNOT: `151C` is not a suffixed
# `sv2a`. It is its own scheme, in National Pokedex order, 192 cards with a
# printed denominator of /151, so Pikachu is `025/165` in JP/EN/TC and
# `025/151` in SC.
#
# Deriving a CN-S code by suffixing a JP one would invent a set that does not
# exist and then fail to find any of its cards -- and `renumbers("CN-S")` is
# True precisely because the numbers do not carry across either.
DERIVED_SET_CODE_LANGUAGES = frozenset(SET_CODE_SUFFIX)


def set_code_is_derivable(language) -> bool:
    """Can this printing's set code be derived from its parent's?"""
    return language in DERIVED_SET_CODE_LANGUAGES


def traditional_chinese_set_code(japanese_set_code) -> str:
    """The Traditional Chinese set code for a Japanese one: JP code + `F`.

    `sv2a` -> `sv2aF`, `s7R` -> `s7RF`. The printed codes are `SV2aF` and
    `S7RF`; the casing is NOT reproduced here, because two observations do not
    establish a casing rule and `same_traditional_chinese_set` compares without
    it. See `OBSERVED_TC_SET_CODES`.
    """
    code = str(japanese_set_code or "").strip()
    if not code:
        raise IdentityError("a Japanese set code is required to derive its "
                            "Traditional Chinese counterpart")
    return code + SET_CODE_SUFFIX["CN-T"]


def japanese_set_code_of(traditional_chinese_set_code):
    """The Japanese parent of a Traditional Chinese set code, or None.

    None when the code carries no `F` suffix -- which is a real answer meaning
    "this is not a Traditional Chinese code we recognise", not a failure.
    """
    code = str(traditional_chinese_set_code or "").strip()
    suffix = SET_CODE_SUFFIX["CN-T"]
    if len(code) <= len(suffix) or not code.lower().endswith(suffix.lower()):
        return None
    return code[: -len(suffix)]


def same_traditional_chinese_set(japanese_set_code, tc_set_code) -> bool:
    """Are these the same set, one printing apart? Case-insensitive."""
    parent = japanese_set_code_of(tc_set_code)
    if parent is None:
        return False
    return parent.lower() == str(japanese_set_code or "").strip().lower()


def shares_parent_numbering(language: str) -> bool:
    """Does this printing use its parent's collector numbers verbatim?

    True for CN-T and ONLY CN-T. Charizard ex SIR is `201/165` in both
    Japanese and Traditional Chinese -- the number is not a distinguishing
    feature there, and `language` is the only thing keeping the two apart.
    """
    return language in NUMBERING_PARENT


def renumbers(language: str) -> bool:
    """True where the same art carries a different number from its parent."""
    return language in RENUMBERED


# -- the collector number, parsed once ------------------------------------
#
# BAND IS A FUNCTION OF THE COLLECTOR NUMBER, NOT THE RARITY STRING, and
# Riftbound is where that stops being a subtlety. `Showcase` is an umbrella
# covering three treatments at wildly different values, all printing the same
# rarity string:
#
#     227*/221   asterisk            Signature       $300-3,090
#     227/221    above the set size  Overnumbered    $75-660
#     119a/298   `a` suffix          Alternate Art   $40-90
#
# A $3,000 card and a $50 card, indistinguishable by rarity. The number is what
# separates them.
#
# The observed apitcg data makes the point twice over: `299*/298` -- asterisked
# AND above the set size, so a Signature by the rule above -- is labelled
# `Alternate Art` there, while `Showcase` appears on runes. The string is
# unreliable in BOTH directions, which is why nothing downstream may trust it
# alone.
#
# This parser is the single place the number is read. `variant_from_number`
# and `ingest.rarity` both consume it, rather than each growing their own
# half-correct copy -- which is how the variant token knew about
# `overnumbered` for three sessions while the band table scored it `base`.

# Riftbound base set sizes, needed because a bare number like `OGN-301` carries
# no denominator to compare against. Dated: sizes and release months as of
# 2026-08-17.
RIFTBOUND_SETS = {
    "OGN": {"name": "Origins",      "released": "2025-10", "base": 298},
    "SFD": {"name": "Spiritforged", "released": "2026-02", "base": 221},
    "UNL": {"name": "Unleashed",    "released": "2026-05", "base": 219},
    "VEN": {"name": "Vendetta",     "released": "2026-07", "base": 166},
    # Announced, not yet released; base count unknown rather than guessed.
    "RAD": {"name": "Radiance",     "released": "2026-10", "base": None},
}

# Simplified Chinese launched FIRST for Origins -- August 2025 against October
# 2025 for English -- with parity from Vendetta. RECORDED, NOT MODELLED:
# `GAME_LANGUAGES` still says Riftbound is English-only, sourced from
# probe/COVERAGE.md. Adding CN-S would create a ninth game/language combination
# and change the labelled-set targets, which is a scope decision rather than a
# correction. See docs/OPEN_QUESTIONS in decisions.md ADR-0028.
RIFTBOUND_CHINESE_LED = ("OGN",)

# apitcg returns set SLUGS, not printed set codes. `RIFTBOUND_SETS` is keyed by
# the printed code, so without this every riftbound card looked up `ORIGINS`,
# found nothing, and got `None` for its set size -- which meant no bare number
# could ever be placed above the set.
RIFTBOUND_SET_ALIASES = {
    "origins": "OGN",
    "origins-proving-grounds": "OGN",
    "spiritforged": "SFD",
    "unleashed": "UNL",
    "vendetta": "VEN",
    "radiance": "RAD",
}


class CollectorNumber:
    """A parsed collector number. Every field is `None` when unreadable."""

    __slots__ = ("raw", "index", "total", "suffix", "starred", "kind",
                 "prefix")

    def __init__(self, raw, index=None, total=None, suffix="", starred=False,
                 kind="card", prefix=""):
        self.raw, self.index, self.total = raw, index, total
        self.suffix, self.starred, self.kind = suffix, starred, kind
        # The set prefix, where the number carried one. Kept because the
        # parser used to discard it, which made `OGN-030` and `SFD-030`
        # compare equal -- a cross-set merge.
        self.prefix = prefix

    def above_set_size(self, set_size=None):
        """Is this numbered beyond the base set? None when unknowable.

        None is not False. A number with no denominator and no known set size
        cannot answer the question, and answering `False` would file a
        Signature as an ordinary card.
        """
        ceiling = self.total if self.total is not None else set_size
        if self.index is None or ceiling is None:
            return None
        return self.index > ceiling

    def __repr__(self):
        return (f"CollectorNumber({self.raw!r}, index={self.index}, "
                f"total={self.total}, suffix={self.suffix!r}, "
                f"starred={self.starred}, kind={self.kind})")


_NUM_CARD = re.compile(r"^(\d+)([a-z]?)(\*?)\s*/\s*(\d+)$", re.I)
_NUM_RUNE = re.compile(r"^R(\d+)([a-z]?)(\*?)$", re.I)
_NUM_TOKEN = re.compile(r"^T(\d+)([a-z]?)$", re.I)
_NUM_PREFIXED = re.compile(r"^[A-Z]{2,4}-(\d+)([a-z]?)(\*?)$", re.I)
# A SET PREFIX AND A DENOMINATOR AT ONCE -- `OGN-030a/298`.
#
# Marketplaces write Riftbound numbers both ways and the parser read this one
# as UNREADABLE, which meant a card offered in that form had no identity at
# all. The prefix and the denominator are redundant with each other here: both
# say which set, and either alone is enough.
_NUM_PREFIXED_TOTAL = re.compile(
    r"^([A-Z]{2,4})-(\d+)([a-z]?)(\*?)\s*/\s*(\d+)$", re.I)
_NUM_BARE = re.compile(r"^(\d+)([a-z]?)(\*?)$", re.I)


def parse_collector_number(number) -> CollectorNumber:
    """`227*/221`, `119a/298`, `OGN-301`, `R01a`, `T02` -> structure.

    Unreadable input returns a CollectorNumber with everything `None` rather
    than raising: a number we cannot parse is a card we cannot classify, and
    `unknown` is a real answer.
    """
    raw = str(number or "").strip()
    if not raw:
        return CollectorNumber(raw, kind="unreadable")

    hit = _NUM_CARD.match(raw)
    if hit:
        return CollectorNumber(raw, int(hit.group(1)), int(hit.group(4)),
                               hit.group(2).lower(), bool(hit.group(3)))
    hit = _NUM_RUNE.match(raw)
    if hit:
        return CollectorNumber(raw, int(hit.group(1)), None,
                               hit.group(2).lower(), bool(hit.group(3)),
                               kind="rune")
    hit = _NUM_TOKEN.match(raw)
    if hit:
        return CollectorNumber(raw, int(hit.group(1)), None,
                               hit.group(2).lower(), False, kind="token")
    hit = _NUM_PREFIXED_TOTAL.match(raw)
    if hit:
        # Both halves kept. The denominator is real information and the prefix
        # is what tells `numbers_denote_same_printing` this is the same scheme
        # as a bare `OGN-030a`.
        return CollectorNumber(raw, int(hit.group(2)), int(hit.group(5)),
                               hit.group(3).lower(), bool(hit.group(4)),
                               prefix=hit.group(1).upper())
    hit = _NUM_PREFIXED.match(raw)
    if hit:
        return CollectorNumber(raw, int(hit.group(1)), None,
                               hit.group(2).lower(), bool(hit.group(3)),
                               prefix=raw.split("-", 1)[0].upper())
    hit = _NUM_BARE.match(raw)
    if hit:
        return CollectorNumber(raw, int(hit.group(1)), None,
                               hit.group(2).lower(), bool(hit.group(3)),
                               kind="bare")
    return CollectorNumber(raw, kind="unreadable")


# What each number feature means as a printing treatment. Riftbound-specific
# today; the mechanism is general because the next game will differ again.
NUMBER_VARIANTS = {
    "starred": "signature",
    "a": "alt_art",
    "b": "promo",
    "above": "overnumbered",
}


class CannotBridge(IdentityError):
    """The printed number could not be derived, so nothing may be concluded.

    Raised rather than returning False so a caller cannot mistake "we could not
    tell" for "they are different cards". Both are non-matches; only one of
    them is a fact.
    """


def printed_from_bare(bare_number, set_total):
    """A provider's bare `localId` -> the number PRINTED on the card.

    ONE DIRECTION ONLY. tcgdex sends `199`; the card says `199/165`; the
    labelled set records what the card says. Deriving printed from bare needs
    the set's official card count and is exact when you have it.

    THE REVERSE IS FORBIDDEN and there is deliberately no function for it.
    Stripping `173/151` and `173/165` to `173` makes Simplified Chinese
    Pikachu and its English counterpart the same string -- the denominator is
    the ONLY thing separating them, and discarding it recreates precisely the
    merge the blocking failures exist to catch. A miss costs a comp. A merge
    costs the price series.

    Raises `CannotBridge` when the total is unknown. Falling back to comparing
    bare against bare would be that same merge, arrived at by giving up.
    """
    if set_total in (None, ""):
        raise CannotBridge(
            f"cannot derive a printed number for {bare_number!r}: the set's "
            "official card count is unknown. Comparing bare against bare "
            "instead would merge every printing that shares an index across "
            "sets -- refusing is a miss, and a miss is the cheaper error.")
    parsed = parse_collector_number(str(bare_number))
    if parsed.index is None:
        raise CannotBridge(
            f"cannot derive a printed number for {bare_number!r}: no index "
            "could be read from it.")
    if parsed.total is not None:
        # Already printed. Handing it back unchanged is right; rewriting it
        # around `set_total` would let a wrong total overwrite a correct
        # denominator that the card itself supplied.
        return parsed.raw
    # Zero-padded to the width of the total, which is how every printing in
    # the labelled set writes it -- `95` in Evolving Skies is `095/203`.
    # Compare NUMERICALLY wherever possible (`numbers_denote_same_printing`);
    # this string form is for display and for round-tripping, and padding
    # conventions are the sort of thing that varies by era.
    total = int(set_total)
    width = max(len(str(total)), 3)
    star = "*" if parsed.starred else ""
    return f"{parsed.index:0{width}d}{parsed.suffix}{star}/{total:0{width}d}"


def numbers_denote_same_printing(catalog_number, labelled_number,
                                 set_total=None) -> bool:
    """Do a catalog row and a labelled row name the same printing?

    Compared NUMERICALLY where both sides carry a denominator -- index, total,
    suffix, asterisk -- so a padding convention cannot decide the answer. `95`
    against `095/203` is a match when the set total is 203 and REFUSES when the
    total is unknown.

    Raises `CannotBridge` rather than returning False when the bridge cannot be
    built. "We could not tell" and "they are different cards" are both
    non-matches and only one of them is a fact.
    """
    left = parse_collector_number(str(catalog_number))
    right = parse_collector_number(str(labelled_number))

    # TWO NAKED INDICES. `173` against `173` says nothing: the denominator is
    # the only thing separating Simplified Chinese Pikachu from the English
    # one, and comparing indices is that merge with the evidence removed.
    if left.kind == "bare" and right.kind == "bare":
        raise CannotBridge(
            f"{catalog_number!r} and {labelled_number!r} are both bare "
            "indices with no denominator. Comparing them would merge every "
            "printing that shares an index.")

    def _same_card(a, b):
        return (a.index == b.index and a.suffix.lower() == b.suffix.lower()
                and a.starred == b.starred)

    if left.total is None and right.total is None:
        # Both carry their set prefix -- `OP01-025`, `OGN-030A`. Nothing to
        # bridge and nothing to strip, so compare AS GIVEN.
        #
        # As given, not by parsed index: `OGN-030` and `SFD-030` share an index
        # and are different cards. The prefix is part of the number here.
        return (str(catalog_number).strip().lower()
                == str(labelled_number).strip().lower())

    if left.total is not None and right.total is not None:
        # Where BOTH carry a prefix it must agree -- `OGN-030a/298` is not
        # `SFD-030a/298`. Where only one does, the denominators still have to
        # match, so nothing is lost by not comparing it.
        if left.prefix and right.prefix and left.prefix != right.prefix:
            return False
        return _same_card(left, right) and left.total == right.total

    # One side has no denominator.
    bare, printed = (left, right) if left.total is None else (right, left)

    if bare.prefix:
        # A SET-PREFIXED NUMBER AGAINST A DENOMINATED ONE, in a game that
        # writes both. `OGN-030A` and `OGN-030a/298` are one printing written
        # two ways -- the prefix and the denominator are REDUNDANT here, each
        # saying which set, and marketplaces use both.
        #
        # This is a reconciliation, not a normalisation: neither form is
        # rewritten, and it holds only where the two sides can be shown to name
        # the same set. Where the prefix belongs to a different set, or the
        # denominator to a different set size, they are simply not the same
        # card.
        if printed.prefix and printed.prefix != bare.prefix:
            return False
        if set_total not in (None, "") and int(set_total) != printed.total:
            return False
        return _same_card(bare, printed)

    if bare.kind != "bare":
        # Neither a bare index nor a prefixed one: two different schemes, and
        # nothing here can reconcile them without inventing a rule.
        raise CannotBridge(
            f"{bare.raw!r} and {printed.raw!r} are written in different "
            "numbering schemes and no rule here converts between them.")
    if set_total in (None, ""):
        raise CannotBridge(
            f"{catalog_number!r} carries no denominator and the set's official "
            "card count is unknown, so it cannot be compared with "
            f"{labelled_number!r}. Matching on the index alone would merge "
            "printings whose only difference is the denominator.")
    if bare.index is None:
        raise CannotBridge(f"no index could be read from {bare.raw!r}")
    return (bare.index == printed.index and int(set_total) == printed.total
            and bare.suffix.lower() == printed.suffix.lower()
            and bare.starred == printed.starred)


# Games whose collector number encodes the PRINTING TREATMENT. Riftbound only,
# and the restriction is load-bearing rather than cautious: in Pokemon a number
# above the set size is ORDINARY -- every secret rare is numbered that way, and
# `170/151` is an Art Rare, not an overnumbered chase card. Applying Riftbound's
# rule to Pokemon relabels the entire secret-rare tier.
NUMBER_VARIANT_GAMES = frozenset({"riftbound"})


def variant_from_number(number, set_size=None, game=None):
    """Variant implied by the number alone, or None if it implies nothing.

    Checked BEFORE the rarity string for the games in `NUMBER_VARIANT_GAMES`,
    because there the string is the unreliable one. Returns None for every
    other game rather than exporting one game's conventions to the rest.
    """
    if game is not None and game not in NUMBER_VARIANT_GAMES:
        return None
    parsed = parse_collector_number(number)
    if parsed.starred:
        return NUMBER_VARIANTS["starred"]
    if parsed.suffix in NUMBER_VARIANTS:
        return NUMBER_VARIANTS[parsed.suffix]
    if parsed.above_set_size(set_size):
        return NUMBER_VARIANTS["above"]
    return None


# -- variant, derived from what the provider calls the rarity ---------------
#
# Providers state a rarity ("TR", "Special Illustration Rare"), never our
# variant token. Deriving one from the other in a single place is what keeps
# the catalog builder and the resolver from disagreeing about what a card is --
# they used to hold two copies of this and only one knew about Treasure Rares.

# Applied to the rarity string. Order matters: the first match wins, so the
# longer, more specific phrase is listed above the abbreviation it contains.
_RARITY_RULES = (
    ("treasure_rare", r"treasure|\btr\b"),
    ("manga_rare",    r"\bmanga\b"),
    ("signature",     r"\bsignature\b"),
    # `overnumbered` first: it contains the word `serialized` looks for, and
    # a Riftbound overnumbered card is not a serial-numbered parallel.
    ("overnumbered",  r"overnumber"),
    ("serialized",    r"serial|\bnumbered\b"),
    ("sir",           r"special illustration|\bsir\b"),
    ("sar",           r"special art rare|\bsar\b"),
    # tcgdex normalises the Japanese-system rarities into English strings:
    # SAR arrives as `Special illustration rare` (caught by the `sir` rule
    # above) and AR as `Illustration rare`.
    ("ar",            r"\billustration rare\b|\bart rare\b|\bar\b"),
    ("promo",         r"\bpromo\b"),
    ("parallel",      r"parallel"),
    ("alt_art",       r"\balt(?:ernate)?\b|\bshowcase\b"),
)

# Applied to the card NAME only when the rarity said nothing. Abbreviations are
# deliberately absent here: a two-letter token inside a card name is a
# coincidence far more often than it is a rarity.
_NAME_SAFE = frozenset({"treasure_rare", "manga_rare", "signature",
                        "serialized", "overnumbered", "promo", "parallel",
                        "alt_art"})


# tcgdex collapses two DIFFERENT market conventions into one string. A
# `Special illustration rare` is called a SIR in English sets and a SAR in
# Japanese ones, and this repository has always kept them apart --
# `pkmn:sv3:223/197:sir:EN` and `pkmn:sv3:108/108:sar:JP` are the same art in
# two markets. The provider cannot tell them apart, so the LANGUAGE does; it is
# the only information that survives the normalisation.
_SIR_BY_LANGUAGE = {"EN": "sir", "JP": "sar", "CN-S": "sar", "CN-T": "sar"}

# Rarity strings whose variant meaning is GAME-SPECIFIC, checked before the
# shared rules. `PR` is One Piece's Parallel Rare -- a foil treatment of a card
# that also exists plain, so it is a parallel in exactly the sense the Gundam
# `+` and Union Arena `★` markers are. It is also Dragon Ball Fusion's PROMO.
# Two letters, two games, two meanings; a shared rule would have to pick.
_VARIANT_BY_GAME = {
    "optcg": {"pr": "parallel"},
}


# Games whose PROVIDER ID encodes the printing treatment.
#
# One Piece only, and the restriction is load-bearing rather than cautious.
#
# WHAT THE SUFFIX IS, PRECISELY. `_p1` / `_p2` / `_r1` are BANDAI IMAGE
# FILENAMES, surfaced by apitcg in its card ids. They are a PROVIDER
# CONVENTION, not a printed identifier -- nothing on the physical card says
# `_p1`, and a seller reading the card in hand will never type it. Marketplaces
# render the same distinction as an `a` suffix on the number, or as
# "(Parallel)" appended to the name.
#
# Splitting on it is still right, and the reason is worth being exact about:
# the suffix is EVIDENCE of a distinct printing, not the NAME of one. Two
# printings exist, the publisher's own asset naming is the only machine-readable
# trace of which is which in this feed, and merging them because the trace is
# informal would lose the more valuable card. What the suffix must never do is
# reach a user-facing field or a matching key that a marketplace record could be
# expected to carry -- a record saying `OP01-025a` or `OP01-025 (Parallel)` is
# describing the same printing as `_p1`, and the resolver has to accept all
# three spellings of it.
#
# 1,165 of apitcg's 3,188 One Piece cards carry one.
#
# Pokemon uses the same-looking suffix for something completely different:
# `cel25c-15_A1` through `_A4` are Venusaur, Here Comes Team Rocket!, Rocket's
# Zapdos and Claydol -- four DIFFERENT CARDS that Celebrations printed at
# collector number 15. That is a broken numbering the provider is patching
# around, not a treatment of one card, and calling those four "parallels of
# each other" would be worse than the collision it fixed. Recorded in
# docs/OPEN_ISSUES.md; not guessed at here.
ID_SUFFIX_VARIANT_GAMES = frozenset({"optcg"})

# The letter, as the publisher writes it.
_ID_SUFFIX_VARIANTS = {"p": "parallel", "r": "reprint"}

_ID_SUFFIX = re.compile(r"_([a-zA-Z])(\d*)$")


def variant_from_external_id(external_id, game=None):
    """Variant implied by the provider's own card id, or None.

    The id is apitcg's, and the suffix inside it is Bandai's image-filename
    convention. It is NOT printed on the card. See the note above
    `ID_SUFFIX_VARIANT_GAMES`: this reads a provider artifact as evidence of a
    printing, which is sound, and must not be mistaken for reading an
    identifier off the card.

    THE COLLISION THIS EXISTS FOR. `EB01-006`, `EB01-006_p1` and
    `EB01-006_p2` are three printings of one card at one collector number, and
    all three carry rarity `SR`. Neither the number nor the rarity string can
    tell them apart, so with only those two the three collapsed into one
    card_uid -- 234 collisions swallowing 286 rows, 39% of the One Piece
    catalog, and the parallels are the expensive ones.

    Returns None for every game not in `ID_SUFFIX_VARIANT_GAMES`, rather than
    exporting one publisher's convention to the rest.
    """
    if game is not None and game not in ID_SUFFIX_VARIANT_GAMES:
        return None
    match = _ID_SUFFIX.search(str(external_id or ""))
    if match is None:
        return None
    stem = _ID_SUFFIX_VARIANTS.get(match.group(1).lower())
    if stem is None:
        # A suffix we have not seen. NOT `base` -- that is the merge this
        # function exists to stop -- and not a guessed name either. `unknown`
        # keeps the card distinct from its base printing while saying plainly
        # that we cannot name the treatment.
        return "unknown_" + match.group(1).lower() + match.group(2)
    index = match.group(2)
    return stem if index in ("", "1") else f"{stem}{index}"


def variant_from_rarity(rarity, name=None, language=None, game=None) -> str:
    """Rarity (and, failing that, name) -> a variant token. `base` if neither says.

    A guess, and treated as one downstream: the resolver scores a variant
    disagreement as evidence AGAINST a match rather than as a disqualification,
    so a wrong guess here costs confidence instead of producing a wrong card.

    `language` resolves one specific collapse and nothing else: see
    `_SIR_BY_LANGUAGE`.
    """
    # A PARALLEL MARKER is a finish, not a tier. Gundam writes
    # `LR                +` and Union Arena writes `SR★★`; both are the same
    # rarity with a different treatment, and the treatment is worth more than
    # the tier. The band lookup normalises the marker away, so if the variant
    # did not pick it up the parallel and its base card would become one card.
    if any(marker in str(rarity or "") for marker in ("+", "\u2605", "\u2606")):
        return "parallel"

    game_rule = _VARIANT_BY_GAME.get(game, {}).get(
        str(rarity or "").strip().lower())
    if game_rule:
        return game_rule

    def settle(token):
        if token == "sir" and language:
            return _SIR_BY_LANGUAGE.get(language, "sir")
        return token

    text = str(rarity or "").lower()
    for token, pattern in _RARITY_RULES:
        if re.search(pattern, text):
            return settle(token)
    text = str(name or "").lower()
    for token, pattern in _RARITY_RULES:
        if token in _NAME_SAFE and re.search(pattern, text):
            return settle(token)
    return "base"


# -- external vocabulary ---------------------------------------------------
#
# apitcg.com: hyphenated slugs, no language dimension -- one slug serves every
# printing, so it cannot distinguish EN from JP and is an English-only second
# opinion in practice.
APITCG_SLUG = {
    "optcg": "one-piece",
    "pkmn": "pokemon",
    "riftbound": "riftbound",
}

# tcgapi.dev: numeric ids, resolved at runtime from /v1/games. Language is
# expressed as a separate game entry, so the key is (game, language). Values
# here are the ids observed in the 2026-08-13 catalog read; the probe
# re-resolves them every run and these are only a fallback for offline work.
TCGAPI_GAME_ID = {
    ("optcg", "EN"): "11",
    ("pkmn", "EN"): "55",
    ("pkmn", "JP"): "19",
    ("riftbound", "EN"): "5",
}

# tcgapi.dev's SET and CARD paths are slug-based and nested, not numeric:
#
#     /v1/games/{gameSlug}/sets/{setSlug}/cards
#
# The numeric ids above address `/v1/search` and `/v1/games`; they do not
# address these. The obvious guesses are wrong in a way that returns a 404
# rather than an error -- `one-piece` is apitcg's slug, and tcgapi calls the
# same game `one-piece-card-game`.
#
# CONFIRMED, not inferred. Slugs for languages other than English are NOT
# listed, because none has been confirmed and inventing `pokemon-japan` would
# be exactly the guess that cost run #7. `ingest.catalog` resolves the rest at
# runtime from `/v1/games`, which is a verified endpoint.
TCGAPI_GAME_SLUG = {
    ("optcg", "EN"): "one-piece-card-game",
    ("pkmn", "EN"): "pokemon",
    ("riftbound", "EN"): "riftbound",
}

# Every slug the provider is known to serve. Used to sanity-check a slug
# resolved at runtime, and to keep the confirmed list somewhere a future
# session can find it.
TCGAPI_KNOWN_SLUGS = (
    "one-piece-card-game", "dragon-ball-super-fusion-world",
    "digimon-card-game", "lorcana-tcg", "pokemon", "magic", "yugioh",
    "riftbound", "union-arena", "star-wars-unlimited", "gundam-card-game",
)

# External tokens that must never appear in a card_uid.
#
# One subtlety: a provider slug can COINCIDE with an internal code -- apitcg
# calls Riftbound "riftbound" and so do we. Such a value is indistinguishable
# at the boundary and harmless either way, because it is valid in both
# vocabularies. Only tokens that are unambiguously external are rejected;
# treating the coincident ones as leaks would reject a legitimate internal
# code, which is exactly what the first run of tests/test_resolver.py caught.
_ALL_EXTERNAL = frozenset(list(APITCG_SLUG.values()) + list(TCGAPI_GAME_ID.values()))
AMBIGUOUS_TOKENS = frozenset(_ALL_EXTERNAL & frozenset(GAMES))
PROVIDER_TOKENS = frozenset(_ALL_EXTERNAL - frozenset(GAMES))


def card_uid(game: str, set_code: str, number: str, variant: str, language: str) -> str:
    """Build a card_uid, refusing anything that is not an internal code.

    This is the only sanctioned way to build one. It rejects provider slugs
    explicitly rather than merely failing the enum check, because the failure
    mode worth naming is a provider slug arriving here and looking plausible.
    """
    if game in PROVIDER_TOKENS:
        raise IdentityError(
            f"provider identifier {game!r} reached card_uid. Provider slugs and ids are "
            f"external vocabulary; map to an internal game code {GAMES} at the ingest "
            "boundary with from_provider_slug()."
        )
    if game not in GAMES:
        raise IdentityError(f"unknown game {game!r}; expected one of {GAMES}")
    if language not in LANGUAGES:
        raise IdentityError(f"unknown language {language!r}; expected one of {LANGUAGES}")
    if language not in GAME_LANGUAGES[game]:
        raise IdentityError(
            f"{game} has no {language} printing; known printings are "
            f"{GAME_LANGUAGES[game]}"
        )
    for name, part in (("set_code", set_code), ("number", number), ("variant", variant)):
        if part is None or str(part) == "":
            raise IdentityError(f"{name} is required in a card_uid")
        if ":" in str(part):
            raise IdentityError(f"{name}={part!r} contains ':', which delimits card_uid")
    return f"{game}:{set_code}:{number}:{variant}:{language}"


def parse_card_uid(uid: str) -> dict:
    parts = uid.split(":")
    if len(parts) != 5:
        raise IdentityError(f"card_uid must have 5 parts, got {len(parts)}: {uid!r}")
    game, set_code, number, variant, language = parts
    if game not in GAMES:
        raise IdentityError(f"unknown game {game!r} in {uid!r}")
    if language not in LANGUAGES:
        raise IdentityError(f"unknown language {language!r} in {uid!r}")
    return {"game": game, "set_code": set_code, "number": number,
            "variant": variant, "language": language}


# -- boundary translation --------------------------------------------------


def to_apitcg_slug(game: str) -> str:
    if game not in APITCG_SLUG:
        raise IdentityError(f"no apitcg.com slug for internal game {game!r}")
    return APITCG_SLUG[game]


def to_tcgapi_game_id(game: str, language: str, resolved: Optional[dict] = None):
    """Internal (game, language) -> tcgapi.dev numeric game id.

    `resolved` is the live mapping from the probe's /v1/games read, which wins
    over the static fallback. Returns None when the catalog has no entry for
    that printing -- which is a finding, not an error: it means tcgapi.dev
    cannot express that language at all.
    """
    if resolved:
        hit = resolved.get((game, language))
        if hit:
            return str(hit)
    return TCGAPI_GAME_ID.get((game, language))


def from_provider_slug(slug: str) -> str:
    """apitcg.com slug -> internal game code. The only inbound direction."""
    for internal, external in APITCG_SLUG.items():
        if external == slug:
            return internal
    raise IdentityError(f"unknown provider slug {slug!r}")


# Probe-facing aliases: the coverage probe names games by provider slug
# because it talks to providers. This is the translation it should use when
# handing anything to the store.
PROBE_GAME_TO_INTERNAL = {v: k for k, v in APITCG_SLUG.items()}
