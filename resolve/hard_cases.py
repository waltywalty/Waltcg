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
    "C6": {
        "kind": None,
        "definition": "Two or more printings that print the SAME collector "
                      "number and are distinguished only by treatment. "
                      "OP01-025 base SR and OP01-025 alt-art SR.",
        "note": "NO KIND EXISTS. Not folded into `alt_art_variant`, which is "
                "C3 and requires the numbers to DIFFER -- the identical number "
                "is the whole difficulty here, and it is one of the three "
                "blocking failures. Needs a kind name before these rows can "
                "count toward the gate.",
    },
}

#: Kinds this repository uses that no C class describes. The gap in the other
#: direction, named for the same reason.
KINDS_WITH_NO_CLASS = ("same_number_different_rarity", "box_code_vs_card_number")


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


def kinds_for_classes(classes):
    """(kinds, unmapped_classes). Unmapped is a finding, not an error."""
    kinds, unmapped = [], []
    for name in classes:
        entry = CLASS_TO_KIND.get(name)
        if entry is None:
            unmapped.append(name)
        elif entry["kind"] is None:
            unmapped.append(name)
        elif entry["kind"] not in kinds:
            kinds.append(entry["kind"])
    return tuple(kinds), tuple(unmapped)
