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

from typing import Optional

# -- internal vocabulary ---------------------------------------------------

GAMES = ("optcg", "pkmn", "riftbound")
LANGUAGES = ("EN", "JP", "CN-S", "CN-T")

# Which languages each game actually ships in. Riftbound is English-only;
# there is no Japanese release (see probe/COVERAGE.md).
GAME_LANGUAGES = {
    "optcg": ("EN", "JP", "CN-S"),
    "pkmn": ("EN", "JP", "CN-S", "CN-T"),
    "riftbound": ("EN",),
}

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
