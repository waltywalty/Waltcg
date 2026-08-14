"""Card identity resolution: provider record in, `card_uid` out, or nothing.

Three routes, in strict order of trust:

1. **Exact** on a provider's own id, via an existing `card_xref` row. Confidence
   is 1 by definition and the schema enforces that -- an "exact" match at 0.85
   is a contradiction.
2. **Fuzzy** on (game, set_code, number) with normalised name similarity.
3. **Manual** override, which outranks everything.

The rule that shapes all of it (contracts/card_uid.md): **anything fuzzy below
0.9 confidence is EXCLUDED from every signal.** Excluded, not discarded -- the
row is still written, because the review queue is how a wrong match gets found.
A fuzzy match at 0.85 that reaches a screen is a wrong card with a confident
price on it, which is worse than no card at all.

The other rule, and the one this file exists to protect: **language is part of
identity.** Bandai prints OP01-121 in English, Japanese and Simplified Chinese.
Matching on (set_code, number) alone merges three assets that trade in three
separate markets, and nothing downstream would look wrong.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .identity import GAMES, LANGUAGES, card_uid, parse_card_uid

# Below this, a fuzzy match is written but never used in a signal.
SIGNAL_THRESHOLD = 0.90
# Below this it is not even offered as a candidate; it goes to the queue with
# no suggestion rather than a bad one, because a plausible wrong suggestion is
# accepted more often than an obviously absent one.
CANDIDATE_FLOOR = 0.60

# Tokens that carry no identifying information and would otherwise inflate
# similarity between every card in a set.
NOISE = frozenset({
    "the", "a", "of", "and", "card", "tcg", "trading", "game", "promo",
    "holo", "foil", "reverse", "parallel", "alt", "alternate", "art",
    "full", "rare", "sr", "sar", "sir", "ur", "hr",
})

# Variant markers that must NOT be normalised away: they are the difference
# between two real, separately-priced printings of one number.
VARIANT_MARKERS = ("manga", "signature", "overnumbered", "sar", "sir",
                   "parallel", "promo", "base")


def normalise_name(name: str) -> str:
    """Fold case, accents and punctuation; drop noise words.

    Deliberately does NOT fold Japanese to romaji. `リザードン` and `Charizard`
    are the same character on two different cards, and treating them as the
    same string is exactly the language merge this module exists to prevent --
    name similarity is compared within a language, never across one.
    """
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = [t for t in text.split() if t and t not in NOISE]
    return " ".join(tokens)


def name_similarity(left: str, right: str) -> float:
    a, b = normalise_name(left), normalise_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    # Token overlap catches reordering ("Luffy Monkey D" vs "Monkey D Luffy")
    # that a pure sequence ratio scores badly.
    ta, tb = set(a.split()), set(b.split())
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return max(ratio, jaccard * 0.95 + ratio * 0.05)


def normalise_number(number: str) -> str:
    """`223/197`, `OP05-119`, `070/SM-P` -> a comparable form.

    Leading zeros go, because providers disagree about them; the denominator
    stays, because `223/197` and `223/165` are different cards.
    """
    text = str(number or "").strip().upper().replace(" ", "")
    text = re.sub(r"^0+(?=\d)", "", text)
    return re.sub(r"(?<=[/-])0+(?=\d)", "", text)


@dataclass
class Candidate:
    card_uid: str
    confidence: float
    resolved_by: str
    why: str


@dataclass
class Resolution:
    """What the resolver decided, and whether a signal may use it."""

    card_uid: Optional[str]
    confidence: float
    resolved_by: Optional[str]
    why: str
    candidates: list = field(default_factory=list)

    @property
    def usable_in_signals(self) -> bool:
        if self.card_uid is None:
            return False
        if self.resolved_by in ("manual", "exact"):
            return True
        return self.confidence >= SIGNAL_THRESHOLD

    @property
    def needs_review(self) -> bool:
        return self.card_uid is None or not self.usable_in_signals


class Resolver:
    """Resolves against a catalog of known cards.

    `catalog` is an iterable of dicts with card_uid, game, set_code, number,
    variant, language and a name. `xrefs` maps (source, external_id) ->
    card_uid. `overrides` maps (source, external_id) -> card_uid and wins
    outright.
    """

    def __init__(self, catalog, xrefs=None, overrides=None):
        self.catalog = [dict(c) for c in catalog]
        self.xrefs = dict(xrefs or {})
        self.overrides = dict(overrides or {})
        self._by_key = {}
        for card in self.catalog:
            key = (card["game"], card["language"],
                   normalise_number(card["number"]))
            self._by_key.setdefault(key, []).append(card)

    def resolve(self, record: dict) -> Resolution:
        source = record.get("source")
        external_id = record.get("external_id")

        if external_id is not None and (source, str(external_id)) in self.overrides:
            return Resolution(
                card_uid=self.overrides[(source, str(external_id))],
                confidence=1.0, resolved_by="manual",
                why=f"manual override for {source}:{external_id}")

        if external_id is not None and (source, str(external_id)) in self.xrefs:
            return Resolution(
                card_uid=self.xrefs[(source, str(external_id))],
                confidence=1.0, resolved_by="exact",
                why=f"exact match on {source} id {external_id}")

        return self._fuzzy(record)

    def _fuzzy(self, record) -> Resolution:
        game = record.get("game")
        language = record.get("language")
        number = normalise_number(record.get("number"))

        if game not in GAMES:
            return Resolution(None, 0.0, None,
                              f"unknown game {game!r}; cannot resolve")
        if language not in LANGUAGES:
            # Never guessed. A provider that does not state language cannot be
            # used to identify a card whose identity INCLUDES language.
            return Resolution(
                None, 0.0, None,
                f"no language on the record. Language is part of card_uid, so "
                f"a record without one cannot be resolved -- it could be any "
                f"of {len(LANGUAGES)} printings.")

        pool = self._by_key.get((game, language, number), [])
        if not pool:
            return Resolution(
                None, 0.0, None,
                f"no card in {game}/{language} with number {number!r}")

        scored = []
        for card in pool:
            similarity = name_similarity(record.get("name", ""),
                                         card.get("name", ""))
            confidence = similarity
            # A stated set_code that disagrees is strong evidence against, and
            # is the signal that separates a reprint from its original.
            record_set = str(record.get("set_code") or "").upper()
            if record_set and record_set != str(card["set_code"]).upper():
                confidence *= 0.55
                why = (f"number and language match but set_code differs "
                       f"({record_set} vs {card['set_code']}): likely a reprint "
                       "or a different print run")
            else:
                why = f"fuzzy on ({game}, {card['set_code']}, {number})"
            # A stated variant that disagrees is the alt-art trap.
            record_variant = str(record.get("variant") or "").lower()
            if record_variant and record_variant != str(card["variant"]).lower():
                confidence *= 0.65
                why += f"; variant differs ({record_variant} vs {card['variant']})"
            scored.append(Candidate(card["card_uid"], round(confidence, 4),
                                    "fuzzy", why))

        scored.sort(key=lambda c: c.confidence, reverse=True)
        best = scored[0]

        # Two candidates within a whisker of each other is an ambiguity, not a
        # winner. Picking the first is how the promo and the set version of one
        # card get merged.
        if len(scored) > 1 and (best.confidence - scored[1].confidence) < 0.05:
            return Resolution(
                None, best.confidence, None,
                f"ambiguous: {scored[0].card_uid} and {scored[1].card_uid} "
                f"score within 0.05 of each other",
                candidates=scored[:5])

        if best.confidence < CANDIDATE_FLOOR:
            return Resolution(None, best.confidence, None,
                              f"best candidate scored {best.confidence:.2f}, "
                              f"below the {CANDIDATE_FLOOR} floor",
                              candidates=scored[:5])

        return Resolution(best.card_uid, best.confidence, "fuzzy", best.why,
                          candidates=scored[:5])
