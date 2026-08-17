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
VARIANTS = ("base", "parallel", "alt_art", "promo", "ar", "sar", "sir",
            "manga_rare", "treasure_rare", "serialized", "overnumbered",
            "signature")

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


def renumbers(language: str) -> bool:
    """True where the same art carries a different number from its parent."""
    return language in RENUMBERED


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


def variant_from_rarity(rarity, name=None, language=None) -> str:
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


class IdentityError(ValueError):
    """A provider vocabulary reached a place only internal codes may go."""


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
