"""The hard-case taxonomy, and the bridge between two names for it.

TWO VOCABULARIES describe the same thing. The labelled rows arrive tagged
`C1`..`C6` -- a research taxonomy, defined by what the resolver is being asked
to keep apart. This repository has always tagged them `hard_case`, a kind name
describing the shape of the collision. Neither is wrong and both are needed:
the C class says why a row was collected, the kind says which gate requirement
it satisfies.

The mapping below is a TRANSLATION, not an inference. Each entry quotes the C
class definition it came from, so a later reader can check the two against each
other rather than trust that somebody once matched them up correctly.

C6 HAS NO KIND. It is named as a gap rather than folded into the nearest one --
`alt_art_variant` is C3, where the numbers DIFFER, and C6 is the case where
they are IDENTICAL. Folding them together would lose exactly the distinction
that makes C6 one of the three blocking failures.
"""

from __future__ import annotations

#: C class -> the `hard_case` kind that satisfies the same gate requirement.
#: `None` means no kind exists yet. Never map a class to "the nearest" kind.
CLASS_TO_KIND = {
    "C1": {
        "kind": "same_art_different_language",
        "definition": "The identical illustration printed in two or more "
                      "languages. Numbers may match (JP 201/165 and CN-T "
                      "201/165), differ (EN 199/165 and JP 201/165), or share "
                      "an index with different denominators (EN 173/165 and "
                      "CN-S 173/151).",
        "note": "Two existing kinds are NARROWER cases of this and are kept "
                "rather than collapsed into it: `same_number_three_languages` "
                "is C1 where the numbers match, and "
                "`renumbered_into_combined_set` is C1 where the denominators "
                "differ. A row may carry the specific kind, the general one, "
                "or both.",
    },
    "C2": {
        "kind": "reprint",
        "definition": "Same card, same language, printed in more than one set, "
                      "with different set codes and different collector "
                      "numbers. One language, two sets.",
        "note": "",
    },
    "C3": {
        "kind": "alt_art_variant",
        "definition": "Two printings of the same card in the SAME set where "
                      "one is the base and one is an alternate or secret "
                      "treatment. The numbers DIFFER but are related -- "
                      "095/203 base against 215/203 alt art.",
        "note": "The numbers differing is what separates this from C6.",
    },
    "C4": {
        "kind": "promo_vs_set",
        "definition": "The same character and art distributed both inside a "
                      "set and as a promo, with two different identifiers. "
                      "The promo identifier usually has its own set code.",
        "note": "",
    },
    "C5": {
        "kind": "name_is_not_unique",
        "definition": "Cards sharing an identical printed name that are "
                      "genuinely different cards -- different set, different "
                      "art, different effect. NOT printings of one card.",
        "note": "",
    },
    # NOT WIDENED to cover `same_number_new_set_new_variant`. A widened C6
    # would read "variant differs, set may or may not" -- a DISJUNCTION, and
    # disjunctive kinds are how C6 itself nearly got buried inside
    # `alt_art_variant`. A kind that means two things measures neither.
    "C6": {
        "kind": "same_printed_number_different_treatment",
        "definition": "Two or more printings that print the SAME collector "
                      "number and are distinguished only by treatment. "
                      "OP01-025 base SR and OP01-025 alt-art SR.",
        "note": "Verbose on purpose: it names the thing that matters and "
                "cannot be mistaken for `alt_art_variant`, which is C3 and "
                "requires the numbers to DIFFER. REQUIRED by the gate, "
                "because C6 is one of the three blocking failures and a gate "
                "that does not demand a case for it is missing the class it "
                "most needs to measure.\n\n"
                "Riftbound's `303/298` against `303*/298` is C6 even though "
                "the asterisk is printed INSIDE the number. The relationship "
                "is C6's -- two printings of one card, treatment the only "
                "difference -- and where the discriminator sits is a notation "
                "detail. Riftbound writes the treatment into the number; One "
                "Piece writes it nowhere and leaves it to an image filename. "
                "Same relationship, two conventions.",
    },
}

# WHICH VOCABULARY IS THE SCHEMA.
#
# `hard_case` kinds are. The C classes were an INPUT -- a research taxonomy
# built to decide what to go and collect -- and the kinds were derived from the
# failure modes this repository has actually hit. Where the two disagree, the
# disagreement is RECORDED rather than reconciled: forcing a kind into a class
# it does not fit would make the taxonomy tidier and the record worse.
#
# These two kinds have no C class. They are not gaps in the mapping to be
# closed; they are places where the repository knows something the research
# pass was not looking for.
KINDS_WITH_NO_CLASS = {
    "same_number_different_rarity": (
        "Two printings at one collector number whose RARITY STRINGS differ. "
        "Adjacent to C6 and not the same: C6 is distinguished only by "
        "treatment, and an OP01-025 base SR and its parallel both read `SR`. "
        "Here the provider itself reports two different rarities at one "
        "number, which is a different question -- whether the rarity can be "
        "trusted as a discriminator at all."),
    "box_code_vs_card_number": (
        "A product or box code arriving where a collector number is expected. "
        "Not a printing relationship at all, which is why no C class covers "
        "it: it is a parsing failure mode, found by ingest rather than by "
        "research."),
}


# THREE SHAPES OF REPRINT, and the resolver must not treat them alike.
#
# All three are C2 -- same card, one language, two sets -- and they fail in
# three different ways, so the general kind `reprint` is not enough on its own.
#
# Declared here from the research, and CROSS-CHECKED against the rows: a pair
# claiming `same_number_new_set` must actually share a number, and the other
# two must not. A declaration nothing verifies is a comment.
REPRINT_SHAPES = {
    "same_art_new_number": {
        "what": "Different set, different number, SAME art. SV1 013/198 "
                "Sprigatito against McDonald's 001/015.",
        "risk": "Two identifiers for one picture. Matching on art or name "
                "merges them; matching on number alone never finds the pair "
                "at all.",
        "shares_number": False,
    },
    "same_number_new_set": {
        "what": "SAME number, different set, near-identical art. Base Set "
                "4/102 Charizard against Celebrations Classic Collection "
                "4/102 -- the Classic Collection RETAINS the original "
                "numbering, so only the set code separates them.",
        "risk": "THE HARD ONE. Two rows differing in a single field, and it "
                "is the field most likely to be dropped, defaulted or "
                "normalised on the way in. Everything else about them is "
                "identical.",
        "shares_number": True,
        "kind": "same_number_different_product",
    },
    "same_number_new_set_new_variant": {
        "what": "SAME number, different set, AND a different treatment. One "
                "Piece PRB-01 reprints of OP05-119 and OP01-070 keep their "
                "`OPxx-xxx` and arrive as new parallels -- apitcg shows "
                "`OP05-119_p3`, `_p4`, `_p5`.",
        "risk": "BOTH AXES MOVE AT ONCE. A resolver can pass `set_code`-only "
                "(Celebrations 4/102) and `variant`-only (OP01-025 base "
                "against its parallel) and still mishandle the two together, "
                "because each of those tests holds one axis fixed. This is "
                "the case neither of them exercises.",
        "shares_number": True,
        "kind": "same_number_new_set_new_variant",
    },
    "new_art_new_number": {
        "what": "Different set, different number, DIFFERENT art. Radiant "
                "Charizard PGO 011/078 (Negishi) against CRZ 020/159 "
                "(Saitou).",
        "risk": "The inverse mistake: these share a NAME and nothing else, "
                "so treating the name as evidence of one card merges two "
                "genuinely different printings with different comps.",
        "shares_number": False,
    },
}

def reprint_pair_of(card):
    """The pair this row belongs to, from its `pair_id` field.

    THE NOTE PARSER IS GONE. It read `"pair MCD-1"` out of free prose, which
    meant a note reworded at source silently dropped the shape -- and the
    cross-check catches a WRONG shape, not a missing one. `pair_id` and
    `reprint_shape` are real fields now; the prose-derived values were
    migrated once and the parser deleted the same day.
    """
    return card.get("pair_id") or None


def reprint_shape_of(card):
    """Which of the four shapes this row's reprint pair is, or None."""
    shape = card.get("reprint_shape")
    return shape if shape in REPRINT_SHAPES else None


def hard_cases_of(card) -> tuple:
    """Every hard-case kind this row carries.

    PLURAL, because `hard_case` is one field and 18 of the 57 researched rows
    carry two classes -- `C1,C6`, `C3,C5`, `C2,C4`. A single-valued field has
    to drop one of them, and which one it drops decides which gate requirement
    goes unmet. Both fields are read so nothing already recorded is lost.
    """
    found = []
    for value in (card.get("hard_cases") or []):
        if value and value not in found:
            found.append(value)
    single = card.get("hard_case")
    if single and single not in found:
        found.append(single)
    return tuple(found)


def classes_of(card) -> tuple:
    """The `C1`..`C6` tags on a row, in order."""
    raw = str(card.get("difficulty_class") or "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def kinds_for_classes(classes, card=None):
    """(kinds, unmapped_classes). Unmapped is a finding, not an error.

    `card` adds the kinds a class alone cannot supply. C2 is `reprint`, but a
    C2 pair that keeps its number is ALSO
    `same_number_different_product` -- the same narrower-kind-alongside-the-
    general-one pattern `same_number_three_languages` follows under C1.
    """
    kinds, unmapped = [], []
    for name in classes:
        entry = CLASS_TO_KIND.get(name)
        if entry is None:
            unmapped.append(name)
        elif entry["kind"] is None:
            unmapped.append(name)
        elif entry["kind"] not in kinds:
            kinds.append(entry["kind"])
    if card is not None:
        shape = REPRINT_SHAPES.get(reprint_shape_of(card) or "", {})
        narrower = shape.get("kind")
        if narrower and narrower not in kinds:
            kinds.append(narrower)
    return tuple(kinds), tuple(unmapped)
