"""What a second source is actually corroborating.

`verified` claims two INDEPENDENT sources agree. Agree about WHAT is the
question this file exists to answer, because a source can confirm one field of
a row and say nothing about the rest — and counting that as agreement inflates
ground truth with rows only half of which was ever checked.

Two instances, arrived at from opposite directions and identical in shape:

  SHARED NUMBERING. One Piece prints `OP01-032` on the English, Japanese and
  Simplified Chinese printings. So an English source confirms that the NUMBER
  exists and names Ashura Doji, and says nothing whatever about whether a
  Simplified Chinese printing of it was ever made. Number-only.

  RETAINED-NUMBER REPRINTS. PRB-01 reprints keep their `OPxx-xxx`, so a
  marketplace listing reading `OP01-120 Manga` is attributed to "Romance Dawn"
  BY CONSTRUCTION -- the seller reads the number, the number says OP01, and
  live eBay listings do exactly this. The listing confirms the number. It is
  not evidence of the product, and it cannot be, because the number it is
  reasoning from is the same in both products.

The second is the more dangerous because it looks like product attribution.
The first announces itself; this one arrives wearing the answer.
"""

from __future__ import annotations

#: What a corroborating source is capable of establishing.
TIERS = {
    "full": {
        "what": "The source attests the whole identity -- this printing, in "
                "this product, in this language.",
        "counts_toward_verified": True,
    },
    "number_only": {
        "what": "The source attests that the collector NUMBER exists and what "
                "card it names, and nothing about which printing or product "
                "the row is describing.",
        "counts_toward_verified": False,
        "why": "A row whose second source is number-only has been checked in "
               "one field and asserted in the rest. Counting it as `verified` "
               "would make the confidence label mean 'somebody looked at part "
               "of this'.",
    },
}

#: Situations where a source class is number-only BY CONSTRUCTION -- not
#: because this particular source was thin, but because the inference it is
#: making cannot distinguish what we need distinguished.
STRUCTURALLY_NUMBER_ONLY = {
    "shared_numbering_across_languages": {
        "applies_to": "A non-native-language source cited for a row in a "
                      "language that shares its collector numbering.",
        "why": "One Piece prints one number across EN, JP and CN-S. An "
               "English source confirms the number exists; it is silent on "
               "whether a Simplified Chinese printing was made.",
        "example": "optcg:op01:OP01-032:base:CN-S -- 8 rows in batch 4 are "
                   "single_source for exactly this reason.",
    },
    "retained_number_reprint": {
        "applies_to": "A marketplace or listing-tier source cited for the "
                      "PRODUCT of a card whose reprint keeps the original "
                      "number.",
        "why": "The seller reads the number, the number says `OP01`, and the "
               "listing says Romance Dawn -- for a card that may be a PRB-01 "
               "printing. The attribution is DERIVED FROM the number, so it "
               "carries no information the number did not already carry. "
               "Live eBay listings attribute manga OP01-120 to Romance Dawn "
               "on precisely this reasoning.",
        "example": "optcg:op01:OP01-120:manga_rare:EN and :JP -- both sourced "
                   "from listings of this kind. See _disputes.",
        "discriminating_source": "Limitless serves a separate variant page per "
                                 "printing, each naming its own product. That "
                                 "is a source that can tell the two apart; a "
                                 "marketplace listing is not.",
    },
}


def is_structurally_number_only(situation) -> bool:
    return situation in STRUCTURALLY_NUMBER_ONLY


def tier_counts_toward_verified(tier) -> bool:
    """Unknown tiers do NOT count. A tier nobody has classified is not a
    licence to assume the strongest one."""
    return bool(TIERS.get(tier, {}).get("counts_toward_verified", False))
