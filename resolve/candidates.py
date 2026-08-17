"""Propose labelled-set candidates, weighted toward what breaks resolution.

The circularity problem, stated plainly: if the labelled set is generated from
the same catalogs the resolver reads, then scoring the resolver against it
measures agreement with its own inputs, not correctness. A card the catalog got
wrong would be labelled wrong and scored right.

So this module does NOT produce labels. It produces CANDIDATES, each carrying
the resolver's own proposed identity, for a human to confirm, correct or
reject. The human breaks the circle. The generator's only job is to put the
hardest cases in front of them first, because a random sample of a card
universe is overwhelmingly cards that resolve trivially, and 250 easy cards
measure nothing.

FIVE PRIORITIES, most dangerous first:

1. `same_art_across_languages` -- one collector number printed in two or more
   markets. The failure is silent and total: three assets merge into one, and
   every price, population and signal downstream inherits the blend.
2. `reprint_across_sets` -- one card, two set codes. Distinguished only by a
   field providers disagree about.
3. `alt_art_vs_base` -- one number, two variants, very different prices.
4. `promo_vs_set` -- shares a name with a set card and is a different asset.
5. `lowest_confidence` -- wherever the resolver is least sure of itself. Not a
   known trap, which is the point: it is the only priority that can surface a
   failure mode nobody thought to enumerate.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from typing import Optional

from .resolver import Resolver, name_similarity, normalise_number

# How many labelled cards each combination needs, and why it is not proportional
# to how many cards exist. See docs/decisions.md ADR-0015.
#
# The driver is which combos can resolve EXACTLY. A combo with a provider id
# has a path that cannot be wrong; a combo without one resolves fuzzily every
# time, so the fuzzy path -- the only path that can be wrong -- carries all of
# its load. Those combos are over-weighted despite being a smaller share of the
# universe.
TARGET_PER_COMBO = {
    "pkmn:EN": 40, "pkmn:JP": 35, "optcg:EN": 35, "optcg:JP": 35,
    "optcg:CN-S": 30, "pkmn:CN-S": 30, "pkmn:CN-T": 25, "riftbound:EN": 20,
}
TARGET_TOTAL = sum(TARGET_PER_COMBO.values())          # 250
# Below this a combo can be meaningfully broken and still show a clean sweep:
# a combo running at 80% precision goes undetected 4% of the time at n=14.
MIN_PER_COMBO = 20
# Share of the set that must be a known-hard case.
HARD_CASE_SHARE = 0.24

PRIORITIES = ("same_art_across_languages", "reprint_across_sets",
              "alt_art_vs_base", "promo_vs_set", "lowest_confidence")


@dataclass
class Idea:
    """One proposal. `proposed` is the resolver's answer, not a label."""

    card: dict
    priority: str
    why: str
    proposed: Optional[str] = None
    proposed_confidence: float = 0.0
    proposed_by: Optional[str] = None
    siblings: list = field(default_factory=list)

    def as_dict(self):
        return {"card": self.card, "priority": self.priority, "why": self.why,
                "resolver_proposed": self.proposed,
                "resolver_confidence": round(self.proposed_confidence, 4),
                "resolver_route": self.proposed_by,
                "siblings": self.siblings, "verdict": None}


def _key(card):
    return (card["game"], normalise_number(card["number"]))


def generate(catalog, resolver=None, per_combo=None, seen=()):
    """Candidates for review, hardest first, capped per combo.

    `catalog` is the flat card list from ingest/catalog.py. `seen` is the set of
    card_uids already labelled, so the generator can be re-run as new sets drop
    without re-proposing settled cards.
    """
    resolver = resolver or Resolver(catalog)
    per_combo = per_combo or TARGET_PER_COMBO
    seen = set(seen)

    by_number = collections.defaultdict(list)
    by_name = collections.defaultdict(list)
    for card in catalog:
        by_number[_key(card)].append(card)
        by_name[(card["game"], card["language"],
                 (card.get("name") or "").lower())].append(card)

    ideas = []

    # 1 -- same number, more than one language.
    for (game, number), group in by_number.items():
        languages = {c["language"] for c in group}
        if len(languages) < 2:
            continue
        for card in group:
            others = sorted(c["card_uid"] for c in group
                            if c["card_uid"] != card["card_uid"])
            ideas.append(Idea(card, "same_art_across_languages",
                              f"{number} exists in {', '.join(sorted(languages))}. "
                              "A merge here is silent and total.",
                              siblings=others))

    # 2 -- same name and language, different set codes.
    for (game, language, name), group in by_name.items():
        codes = {c["set_code"] for c in group}
        if len(codes) < 2 or not name:
            continue
        for card in group:
            ideas.append(Idea(card, "reprint_across_sets",
                              f"'{name}' appears in {', '.join(sorted(codes))}. "
                              "Distinguished only by set_code, which providers "
                              "disagree about.",
                              siblings=sorted(c["card_uid"] for c in group
                                              if c["card_uid"] != card["card_uid"])))

    # 3 -- same number and language, different variants.
    for (game, number), group in by_number.items():
        for language in {c["language"] for c in group}:
            same = [c for c in group if c["language"] == language]
            variants = {c["variant"] for c in same}
            if len(variants) < 2:
                continue
            for card in same:
                ideas.append(Idea(card, "alt_art_vs_base",
                                  f"{number} has variants {', '.join(sorted(variants))} "
                                  "in one language, at very different prices.",
                                  siblings=sorted(c["card_uid"] for c in same
                                                  if c["card_uid"] != card["card_uid"])))

    # 4 -- a promo sharing a name with a set card.
    for (game, language, name), group in by_name.items():
        promos = [c for c in group if c["variant"] == "promo"
                  or str(c["set_code"]).upper().startswith("P")]
        if not promos or len(group) < 2:
            continue
        for card in promos:
            ideas.append(Idea(card, "promo_vs_set",
                              f"promo '{name}' shares a name with a set card and "
                              "is a different asset.",
                              siblings=sorted(c["card_uid"] for c in group
                                              if c["card_uid"] != card["card_uid"])))

    # 5 -- wherever the resolver is least sure. The only priority that can
    # surface a failure mode nobody enumerated.
    scored = []
    for card in catalog:
        result = resolver.resolve({
            "source": "catalog", "game": card["game"],
            "language": card["language"], "number": card["number"],
            "set_code": card["set_code"], "variant": card["variant"],
            "name": card.get("name", "")})
        scored.append((result.confidence, card, result))
    scored.sort(key=lambda row: row[0])
    for confidence, card, result in scored[:len(catalog) // 4 + 1]:
        ideas.append(Idea(card, "lowest_confidence",
                          f"resolver scored its own catalog entry {confidence:.3f}"
                          + (f" -- {result.why}" if result.card_uid is None else "")))

    # Attach the resolver's proposal to every idea, and de-duplicate keeping
    # the highest-priority reason for each card.
    order = {name: i for i, name in enumerate(PRIORITIES)}
    best = {}
    for idea in ideas:
        card = idea.card
        if card["card_uid"] in seen:
            continue
        result = resolver.resolve({
            "source": "catalog", "game": card["game"],
            "language": card["language"], "number": card["number"],
            "set_code": card["set_code"], "variant": card["variant"],
            "name": card.get("name", "")})
        idea.proposed = result.card_uid
        idea.proposed_confidence = result.confidence
        idea.proposed_by = result.resolved_by
        current = best.get(card["card_uid"])
        if current is None or order[idea.priority] < order[current.priority]:
            best[card["card_uid"]] = idea

    # Fill per combo, hardest priority first, so a combo's quota is spent on
    # its hard cases before its easy ones.
    per_combo_out = collections.defaultdict(list)
    for idea in sorted(best.values(),
                       key=lambda i: (order[i.priority], i.proposed_confidence)):
        combo = f"{idea.card['game']}:{idea.card['language']}"
        if len(per_combo_out[combo]) < per_combo.get(combo, MIN_PER_COMBO):
            per_combo_out[combo].append(idea)
    return per_combo_out


def shortfall(per_combo_out, per_combo=None):
    """What the generator could not fill, and for which combo.

    Reported rather than quietly returning fewer: a combo the catalog cannot
    reach produces zero candidates, and that is a coverage fact, not a shortage
    of hard cases."""
    per_combo = per_combo or TARGET_PER_COMBO
    return {combo: {"want": want, "have": len(per_combo_out.get(combo, [])),
                    "short": want - len(per_combo_out.get(combo, []))}
            for combo, want in per_combo.items()
            if len(per_combo_out.get(combo, [])) < want}
