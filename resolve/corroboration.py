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


# =========================================================================
# PER-FIELD ATTESTATION
#
# PRE-REGISTERED 2026-08-25, BEFORE ANY ROW WAS COLLECTED UNDER IT. Same
# discipline as the backtest pre-registration: a rule written while looking at
# the rows it will admit is a rule fitted to those rows. If this standard is
# ever edited after the CN-S batch arrives, the edit is the finding.
#
# WHY THE TIERS ABOVE WERE NOT ENOUGH. `number_only` means "attests the
# NUMBER, silent on the PRINTING". A physical card in hand is the opposite
# shape -- decisive about the printing, weak about the number, because
# transcription is where it can go wrong. Both are "partial", and calling both
# `number_only` would make `tier_counts_toward_verified` mean two different
# things depending on which source asked.
#
# So attestation is recorded PER FIELD. That separates two axes the tiers
# above ran together: WHICH field a source speaks to, and HOW STRONGLY.
# =========================================================================

#: How a source knows what it knows. The axis that matters for independence.
CHANNELS = {
    "optical": "Read off the physical artifact by a human eye. Fails by "
               "transcription -- a misread digit, an ambiguous glyph, a "
               "damaged card.",
    "documentary": "Read from a published record. Fails by consulting the "
                   "wrong record, or by the record being wrong.",
    "decisive": "Not an inference at all. The card is in a hand; whether a "
                "printing exists is not in question.",
}

#: What each source class can attest, field by field. `None` means SILENT --
#: which is a different thing from `weak`, and the distinction is the reason
#: this table exists rather than a per-source tier.
FIELD_ATTESTATION = {
    "physical_card": {
        "_what": "A copy of the card, in hand, read by a person.",
        "printing_exists": "decisive",
        "language": "decisive",
        "treatment": "decisive",
        "number": "optical",
        "name": "optical",
        "set_code": None,
        "_set_code_why": "One Piece encodes the set in the number's prefix, so "
                         "the set code is DERIVED from the number rather than "
                         "attested separately. It inherits the number's "
                         "standing and never exceeds it.",
    },
    "shared_numbering_reference": {
        "_what": "Bandai's own EN or JP card list, cited for a row in a "
                 "language that shares its collector numbering.",
        "printing_exists": None,
        "language": None,
        "treatment": None,
        "number": "documentary",
        "name": None,
        "_name_why": "It gives the EN or JP name for the number. It does NOT "
                     "give the Simplified Chinese name. Treating the two as "
                     "the same attestation requires a translation, and a "
                     "translation performed here is not a source.",
    },
    "limitless_variant_page": {
        "_what": "A per-printing page naming its own product in an HREF slug.",
        "printing_exists": "documentary",
        "language": "documentary",
        "treatment": "documentary",
        "number": "documentary",
        "name": "documentary",
    },
}

#: Channel pairs that compose to a full attestation of ONE field, and the
#: argument for each. A pair not listed here does NOT compose -- two partial
#: attestations are not automatically one whole, and the burden is on the
#: composition to say why the failure modes do not overlap.
COMPOSES_TO_FULL = {
    frozenset({"optical", "documentary"}): {
        "why": "The failure modes are disjoint. A transcription slip and a "
               "wrong-record error have no common cause, so agreement between "
               "them is informative in a way that two documentary sources "
               "citing each other is not.",
        "requires_checksum": True,
    },
}

#: Composing optical with documentary is only worth anything if the agreement
#: is CHECKED, and the check has to be capable of failing.
CHECKSUM = {
    "name_against_number": {
        "what": "The number and the name are read off the card TOGETHER, then "
                "looked up in the documentary record. A transcription slip in "
                "the number yields either a number the record does not carry "
                "or one that names a different card.",
        "why_it_can_fail": "The number and the name constrain each other. "
                           "Without this the composition is arithmetic on "
                           "tier labels -- two weak things called strong.",
        "protocol": "THE CARD IS READ FIRST AND THE RECORD CONSULTED AFTER. "
                    "A row drafted and then confirmed against the card is not "
                    "an observation; it is a prior being agreed with, which "
                    "is the same defect as fixtures agreeing with the regexes "
                    "they were written from.",
    },
}

#: WHAT MUST BE WITHHELD FOR AN ART CALL TO BE INDEPENDENT.
#:
#: Blind to the NUMBER is not enough. The printed Simplified Chinese name is a
#: PHONETIC TRANSLITERATION of the character's name -- 索隆 is Suo-long is
#: Zoro -- so it leaks the answer to a reader who cannot read the script
#: reliably but can read it well enough to be led. That is the trap: the same
#: unreliability that disqualifies the glyph channel does NOT prevent the
#: glyphs from anchoring the art call.
ART_CALL_BLINDNESS = {
    "withhold": ("number", "card_uid", "set_code", "printed_name",
                 "documentary_name", "note"),
    "the_one_that_is_easy_to_miss": {
        "field": "printed_name",
        "why": "A Simplified Chinese card name is a phonetic transliteration. "
               "A partial read of it -- which is all this reader is credited "
               "with -- still carries the answer. Withholding the number and "
               "showing the name would leave the channel reading the answer "
               "off the card in the script we established it reads badly.",
    },
    "show": ("the card image, and nothing else",),
    "enforced_as": "SEQUENCE, NOT INTENTION. The art calls are recorded and "
                   "COMMITTED before the checksum is run, so the git history "
                   "is the evidence of ordering. A call whose commit does not "
                   "predate the checksum is not blind, whatever anyone "
                   "remembers.",
}

#: What an art call can produce, and what each outcome does to the row.
ART_CALL_OUTCOMES = {
    "agrees": "The character named from the picture matches the documentary "
              "name for the transcribed number. The Latin name is now "
              "INDEPENDENTLY attested and the detector is live on the row.",
    "disagrees": "Either the number was misread or the call was wrong. The "
                 "row is BLOCKED -- not admitted with either name -- until it "
                 "is resolved. A disagreement is the instrument working, not "
                 "a vote to break.",
    "abstains": "No name is recorded and the row lands identity-complete and "
                "name-absent, exactly as it would have without this channel. "
                "Abstention costs nothing and must never be discouraged.",
}

#: A NAME COPIED FROM THE RECORD IT WILL BE CHECKED AGAINST CANNOT DISAGREE
#: WITH IT. The fifth instance of this session's defect, and the most
#: expensive, because the check it disables is the one that has caught three
#: real errors.
DERIVED_NAME_IS_INERT = {
    "what": "Filling a CN-S row's Latin reference name from Bandai's EN or JP "
            "record for the same number.",
    "why_it_looks_fine": "The name is correct. The row validates. "
                         "`cross_language_name_disagreements` runs over it "
                         "and reports nothing.",
    "why_it_is_worse_than_an_absent_name": "It reports nothing BY "
        "CONSTRUCTION. The CN-S name was derived from the EN name, so the two "
        "agree no matter what is printed on the card -- the check cannot "
        "fail, which reads exactly like a check that passed. An ABSENT name "
        "makes the row visibly skipped instead.",
    "what_made_the_detector_work": "Batch 2's swap was catchable because the "
        "researcher transliterated from a CN-S source INDEPENDENTLY, and the "
        "result disagreed with EN and JP. Independence is the whole "
        "mechanism; a copy has none.",
    "so": "A CN-S row admitted on the number alone records NO name -- neither "
          "the printed characters nor a Latin reference copied from the "
          "documentary record.",
}

#: WHAT THIS COMPOSITE DOES NOT REACH, stated here rather than discovered
#: later. The gap is real and the rows carrying it must say so.
NOT_REACHED = {
    "cn_s_name": {
        "field": "name",
        "why": "There is no Simplified Chinese catalog source (OPEN_ISSUES: "
               "`One Piece CN-S has no catalog source`), so the documentary "
               "side gives the EN or JP name for the number and nothing else. "
               "The SC name is attested OPTICALLY ONLY, with no second "
               "channel, and the checksum does not cover it.",
        "not_mitigated_by": "Confirming that the SC characters render the EN "
                            "name is a TRANSLATION, and a translation "
                            "performed here is not a source. It would be this "
                            "repository corroborating itself.",
        "recorded_as": "`name_attestation: optical_only` on every row that "
                       "carries it.",
    },
}

#: The identity a labelled row actually claims. The name is an annotation --
#: it drives `cross_language_name_disagreements`, which has caught three
#: errors -- but it is not what the resolver is being tested on.
IDENTITY_FIELDS = ("printing_exists", "language", "treatment", "number")


def attests(source_class, field):
    """What `source_class` can say about `field`. None means SILENT."""
    return FIELD_ATTESTATION.get(source_class, {}).get(field)


def composes(channels):
    """Do these channels compose to a full attestation of one field?

    Unlisted pairs do NOT compose. Two partial attestations are not
    automatically one whole, and a pair that has not been argued for has not
    earned the promotion.
    """
    return COMPOSES_TO_FULL.get(frozenset(channels))


def field_is_established(field, source_classes, checksum_passed=False):
    """Is `field` established to full standard by these sources together?

    Returns (established, why). A single `decisive` source settles it. A
    composition needs its channels listed in COMPOSES_TO_FULL and, where that
    entry demands one, a checksum that actually ran.
    """
    channels = [attests(source, field) for source in source_classes]
    speaking = [channel for channel in channels if channel]
    if not speaking:
        return False, f"no source attests {field}"
    if "decisive" in speaking:
        return True, f"{field} is attested decisively"
    if "full" in speaking:
        return True, f"{field} is attested in full by a single source"
    if len(set(speaking)) < 2:
        return False, (f"{field} is attested only by {speaking[0]!r}; one "
                       "partial channel does not compose with itself")
    rule = composes(set(speaking))
    if not rule:
        return False, (f"{field}: channels {sorted(set(speaking))} are not a "
                       "composition this standard has argued for")
    if rule["requires_checksum"] and not checksum_passed:
        return False, (f"{field}: {sorted(set(speaking))} would compose, but "
                       "the checksum did not run. Agreement that is never "
                       "checked is not agreement.")
    return True, f"{field} established by composition: {rule['why']}"


def row_is_verifiable(source_classes, checksum_passed=False):
    """Does this combination of sources reach `verified` for a row?

    Every IDENTITY field must be established. The name is reported separately
    with its own standing, because on a CN-S row it is optical-only and saying
    so is the point.
    """
    reasons, missing = {}, []
    for field in IDENTITY_FIELDS:
        ok, why = field_is_established(field, source_classes, checksum_passed)
        reasons[field] = why
        if not ok:
            missing.append(field)
    name_ok, name_why = field_is_established("name", source_classes,
                                             checksum_passed)
    return {
        "verified": not missing,
        "missing": missing,
        "by_field": reasons,
        "name_established": name_ok,
        "name_why": name_why,
        "name_attestation": None if name_ok else "optical_only",
    }


#: The collection protocol, recorded because the standard depends on it and a
#: protocol that lives only in someone's memory is not a control.
PHYSICAL_CARD_PROTOCOL = {
    "reader_first": {
        "rule": "The card's holder states the number and the name off the "
                "card. Only then is the documentary record consulted.",
        "forbidden": "Drafting a row and asking the holder to confirm it.",
        "why": "A confirmation against a prior is not an observation. It is "
               "the same defect as fixtures agreeing with the regexes they "
               "were written from -- the agreement is guaranteed by the "
               "construction and carries no information.",
        "breaks": "the checksum, which is the only thing making the "
                  "composition worth more than its parts",
    },
    "unsure_is_unresolved": {
        "rule": "Ambiguous, damaged, or uncertain printed text is recorded "
                "UNRESOLVED. Never guessed, never filled from the EN row.",
        "why": "A guess here is indistinguishable from a reading, and it "
               "would be laundered to `verified` by a checksum it was "
               "constructed to pass.",
        "consequence_is_accepted": "A shorter set. Twelve rows collected this "
                                   "way beats sixteen with four guesses in "
                                   "them, and the shortfall stays visible in "
                                   "the gate rather than being closed by the "
                                   "weakest four.",
    },
}

#: HOW the card was read. Both are the same channel -- `optical` -- and
#: neither adds a second one. What differs is where the human steps sit.
READING_METHODS = {
    "direct": {
        "what": "The card's holder reads the printed text off the card.",
        "roles": ("read_by",),
        "error_sources": "One person, two steps: choosing the copy and "
                         "transcribing its glyphs.",
        "re_checkable": False,
        "why_not": "Nobody can go and look again. Unlike a URL, the evidence "
                   "is a physical object in one person's hands at one moment.",
    },
    "photograph": {
        "what": "The holder photographs the card; a second person reads the "
                "printed text off the image.",
        "roles": ("imaged_by", "read_by"),
        "error_sources": "TWO PEOPLE, DIFFERENT FAILURES. The photographer "
                         "owns WHICH CARD and whether it is legible -- wrong "
                         "copy, cropped number, glare, focus. The reader owns "
                         "TRANSCRIPTION and nothing else. Recording one name "
                         "for both would lose the distinction, which is the "
                         "mistake the per-field table exists to avoid.",
        "re_checkable": True,
        "why": "The image is an ARTIFACT. The reading can be audited after "
               "the fact, which a card in a hand cannot be. That strengthens "
               "the PROVENANCE. It does not raise the tier -- it is the same "
               "optical channel, one artifact, one reading.",
    },
}

#: A photograph is not the forbidden pattern -- it carries no prior of the
#: reader's to agree with. But it opens a NEW ROUTE BACK TO IT, and the route
#: is short enough to walk without noticing.
ILLEGIBLE_GLYPH_ROUTE = {
    "the_temptation": "The reader cannot make out a character and asks the "
                      "holder `is this 阿?`",
    "why_it_is_forbidden": "That is a confirmation against a prior, arriving "
                           "through the photograph instead of through a "
                           "drafted row. The holder is now agreeing with a "
                           "candidate rather than reading, and the agreement "
                           "carries no information -- identical to the "
                           "drafted-row case the protocol already forbids.",
    "what_to_do_instead": ("take a fresh photograph -- better light, closer, "
                           "different angle -- and read that, or record the "
                           "field UNRESOLVED. Asking the holder to read the "
                           "character aloud WITHOUT being offered a candidate "
                           "is also fine; that is a reading, not a "
                           "confirmation."),
}

#: Two people reading the same card optically is still ONE channel. Recorded
#: when it happens, because it lowers the transcription error rate, but it
#: does NOT promote the field -- `composes` refuses optical with optical.
SECOND_OPTICAL_READING = {
    "raises_the_tier": False,
    "why": "Two eyes on one artifact share every failure mode that comes "
           "from the artifact -- a cropped number is cropped for both. "
           "Independence has to come from a different CHANNEL, not a second "
           "pass down the same one.",
    "worth_recording_anyway": "It lowers the practical transcription error "
                              "rate, and a disagreement between two readers "
                              "is a finding worth keeping.",
}

#: WHO READ IT IS AN ERROR-PROFILE FIELD, not attribution.
#:
#: This is deliberately NOT a tier. A tier says what a SOURCE CLASS can
#: establish; this says how a particular READER fails. Folding one into the
#: other is the conflation that has now been corrected twice -- `number_only`
#: meaning both "which field" and "how strongly", and then per-source tiers
#: unable to say SILENT versus WEAK. A third instance is not needed.
#:
#: `self_detecting` is the load-bearing entry. The protocol's main safeguard on
#: the name is `unsure_is_unresolved`, and that rule ASSUMES THE READER CAN
#: NOTICE BEING UNSURE. Where the failure mode is confident substitution, the
#: escape hatch is not weaker -- it is INOPERATIVE, and the row comes back
#: looking clean.
READER_PROFILES = {
    "human_holder": {
        "what": "A person reading the printed text off the card in hand.",
        "failure_mode": "Misreading, and fatigue on long runs.",
        "self_detecting": True,
        "why": "A person who cannot make out a character generally knows it. "
               "The stumble is visible to the person stumbling, which is what "
               "makes `unsure_is_unresolved` a working control.",
    },
    "human_from_image": {
        "what": "A person reading the printed text off a photograph.",
        "failure_mode": "Misreading, plus whatever the image lost -- glare, "
                        "focus, resolution, crop.",
        "self_detecting": True,
        "why": "Same as above, and an illegible image is legibly illegible.",
    },
    "human_nonnative_logographic": {
        "what": "A person copying characters from a script they do not read "
                "-- Simplified Chinese, for a non-native reader.",
        "failure_mode": "Confident substitution of a visually similar "
                        "character, from having no model of WHICH STROKES ARE "
                        "LOAD-BEARING. A smudge is noticed; a wrong radical "
                        "is not.",
        "self_detecting": False,
        "why": "Same shape as the model's failure, different cause. A reader "
               "who cannot read the script knows they are copying, and that "
               "feels like appropriate caution -- but the caution is about "
               "legibility, not about meaning, and the substitution happens "
               "in the part they cannot check.",
        "what_would_be_self_detecting": "A native reader of the script, or a "
                                        "Simplified Chinese catalog source. "
                                        "Neither is currently available; see "
                                        "NOT_REACHED.",
    },
    "ai_art_identification": {
        "what": "A model naming the CHARACTER DEPICTED, from the artwork "
                "alone. A different channel from reading glyphs: the evidence "
                "is the picture, not the text.",
        "failure_mode": "Confusing two visually similar CHARACTERS -- not two "
                        "similar strokes. Weakest on minor crew, background "
                        "figures and alternate-art stylisation; worst case is "
                        "a major character drawn unusually.",
        "self_detecting": "partial",
        "why_partial": "Unlike the glyph case, `I do not recognise this one` "
                       "is available and meaningful. But PARTIAL IS THE "
                       "DANGEROUS MIDDLE: the occasions when the abstention "
                       "fails to fire are exactly the confident-substitution "
                       "occasions. It is usable only where the abstention is "
                       "MEASURED rather than asserted -- see "
                       "`abstention_is_credible`.",
        "independent_of": "Bandai's record. The identification comes from the "
                          "picture, so a CN-S row named this way CAN disagree "
                          "with the EN or JP row at that number -- which is "
                          "what makes the detector live again.",
        "also_checks_the_number": "If the art call disagrees with the "
                                  "documentary name for the transcribed "
                                  "number, either the number was misread or "
                                  "the call was wrong. A finding either way, "
                                  "on the field that otherwise has one "
                                  "channel.",
    },
    "ai_from_image": {
        "what": "A model reading glyphs off card artwork.",
        "failure_mode": "CONFIDENT SUBSTITUTION of a visually similar "
                        "character. Not a visible stumble -- a clean, "
                        "assured, wrong answer.",
        "self_detecting": False,
        "weakest_case": "Dense-stroke Simplified Chinese characters at banner "
                        "size over foil.",
        "why": "The failure produces no uncertainty signal, so "
               "`unsure_is_unresolved` never fires. The reader does not "
               "abstain because it does not know it should.",
        "not_the_same_as": "Parsing text a server SENT us, as in "
                           "`ingest/limitless.py`. That is documentary and "
                           "this profile does not apply to it. The profile is "
                           "about reading GLYPHS OFF ARTWORK.",
    },
}

#: Fields whose reading has no checksum, so a confident substitution in them
#: is unrecoverable. The number is checksummed against the documentary record
#: -- a substituted digit yields a number that record does not carry, or one
#: naming a different card -- so it is not on this list.
UNCHECKSUMMED_FIELDS = ("name",)


#: Below this, a run of art calls is claiming a recognition rate the weak
#: cases do not support. NOT a quality target -- a FLOOR ON HONESTY. A batch
#: of One Piece cards contains minor crew and background figures, and a reader
#: that recognised every one of them recognised some it could not.
MIN_CREDIBLE_ABSTENTION = 0.05


def abstention_is_credible(calls):
    """Did the partial abstention actually fire?

    `self_detecting: partial` is worth nothing as a label. It is worth
    something as a MEASUREMENT, and this is the measurement: a reader claiming
    partial self-detection must be seen abstaining, on a set that contains
    cases it should abstain on.

    ZERO ABSTENTIONS IS THE RED FLAG, not the success. A set of One Piece
    cards is not all Luffy and Zoro; recognising every card in it is the
    signature of confident substitution, which is the failure this profile
    exists to bound.
    """
    total = len(calls)
    if not total:
        return {"credible": False, "calls": 0, "abstentions": 0, "rate": None,
                "why": "no calls were made, so nothing was measured"}
    abstained = sum(1 for call in calls if call.get("outcome") == "abstains")
    rate = abstained / total
    if abstained == 0:
        return {"credible": False, "calls": total, "abstentions": 0,
                "rate": 0.0,
                "why": "ZERO abstentions across the batch. A reader claiming "
                       "partial self-detection that never abstained did not "
                       "exercise the property it is credited with -- and a "
                       "One Piece set is not all major characters. Treat the "
                       "run as unmeasured, not as a clean sweep."}
    if rate < MIN_CREDIBLE_ABSTENTION:
        return {"credible": False, "calls": total, "abstentions": abstained,
                "rate": rate,
                "why": f"abstention rate {rate:.1%} is below "
                       f"{MIN_CREDIBLE_ABSTENTION:.0%}; the abstention fired "
                       "too rarely to be evidence that it works"}
    return {"credible": True, "calls": total, "abstentions": abstained,
            "rate": rate, "why": None}


def art_call_outcome(named_character, documentary_name, normalise=None):
    """agrees / disagrees / abstains, from one art call.

    `named_character` is what the picture was called; None or empty means the
    reader abstained. `documentary_name` is what the record says for the
    TRANSCRIBED NUMBER -- consulted only after the call was committed.
    """
    if not named_character:
        return "abstains"
    if not documentary_name:
        return "disagrees"
    clean = normalise or (lambda text: " ".join(
        str(text).lower().replace(".", " ").replace("-", " ").split()))
    return ("agrees" if clean(named_character) == clean(documentary_name)
            else "disagrees")


def art_call_admits_a_name(call):
    """May this row carry a Latin name on the strength of its art call?

    Only on `agrees`, and only when the call was committed BEFORE the checksum
    ran. A disagreement blocks the row rather than choosing a side; an
    abstention leaves it name-absent, which costs nothing.
    """
    if call.get("outcome") != "agrees":
        return False, ART_CALL_OUTCOMES.get(call.get("outcome"),
                                            "unknown art call outcome")
    if not call.get("committed_before_checksum"):
        return False, ("the art call is not evidenced as blind: its commit "
                       "does not predate the checksum. Ordering is enforced "
                       "as SEQUENCE, not intention -- what anyone remembers "
                       "about the order is not the record.")
    return True, ART_CALL_OUTCOMES["agrees"]


def failure_is_self_detecting(reader_profile) -> bool:
    """Can this reader notice its own failure?

    An unknown profile is NOT assumed to be self-detecting. Same defaulting
    rule as an unknown corroboration tier: unclassified is not a licence to
    assume the favourable case.
    """
    profile = READER_PROFILES.get(reader_profile)
    # `partial` is NOT True. It is a claim that has to be measured before it
    # counts, and `may_read` routes it through the art-call protocol rather
    # than through this predicate. Returning True here would let a partial
    # reader supply an unchecksummed field on the strength of a label.
    return bool(profile and profile["self_detecting"] is True)


def may_read(reader_profile, field):
    """May this reader's reading of `field` be recorded at all?

    Returns (allowed, why). The rule: a reader whose failure is not
    self-detecting may read fields that carry a CHECKSUM, because the checksum
    catches what the reader cannot. It may not supply a field where nothing
    would catch it -- there the reading is indistinguishable from a
    fabrication, and `unsure_is_unresolved` will not fire to save it.
    """
    if reader_profile not in READER_PROFILES:
        return False, (f"unknown reader profile {reader_profile!r}; an "
                       "unclassified reader is not assumed to be a reliable "
                       "one")
    if failure_is_self_detecting(reader_profile):
        return True, "the reader can notice its own failure and abstain"
    if READER_PROFILES[reader_profile]["self_detecting"] == "partial":
        return False, (
            f"{reader_profile!r} claims PARTIAL self-detection, which is not "
            "a licence -- it is a claim to be measured. A row may carry a "
            f"{field} from this reader only through the art-call protocol: "
            "blind ordering evidenced by commit order, an outcome of "
            "`agrees`, and a batch whose abstention rate shows the "
            "abstention actually fires. See `art_call_admits_a_name`.")
    if field not in UNCHECKSUMMED_FIELDS:
        return True, (f"{field} is checksummed against the documentary "
                      "record, which catches what this reader cannot")
    return False, (
        f"{field} carries no checksum and this reader's failure mode is not "
        "self-detecting, so `unsure_is_unresolved` would never fire. Read it "
        "with a self-detecting reader or record it UNRESOLVED -- a confident "
        "substitution here is indistinguishable from a correct reading and "
        "nothing downstream would catch it.")


#: Fields every `physical_card` row must carry, whatever the method.
#: `reader_reliability` is the profile key -- WHO read it, as an error
#: profile rather than as attribution. Required, because an unrecorded reader
#: is an unclassified one and `may_read` refuses those.
PHYSICAL_CARD_PROVENANCE = ("reading_method", "read_by", "read_on",
                            "checksum", "name_attestation",
                            "reader_reliability")
#: Extra fields required per method.
METHOD_PROVENANCE = {
    "direct": (),
    # `image_ref` identifies WHICH image was read -- a filename or a content
    # hash the holder keeps. THE IMAGE ITSELF IS NEVER COMMITTED: it is a
    # photograph of copyrighted card art, which is the same redistribution
    # rule the provider data lives under. The reference is what makes the
    # reading auditable without putting the artwork in a public repository.
    "photograph": ("imaged_by", "image_ref"),
}


def physical_card_row_is_well_formed(row):
    """Does a `physical_card` row carry what the standard requires?

    Returns (ok, problems). Refuses rather than repairing, like `ingest`.
    """
    problems = []
    for field in PHYSICAL_CARD_PROVENANCE:
        if not row.get(field):
            problems.append(f"missing {field!r}")
    method = row.get("reading_method")
    if method is not None and method not in READING_METHODS:
        problems.append(f"unknown reading_method {method!r}")
    for field in METHOD_PROVENANCE.get(method, ()):
        if not row.get(field):
            problems.append(f"missing {field!r}, required when "
                            f"reading_method is {method!r}")
    if method == "direct" and row.get("imaged_by"):
        problems.append("`imaged_by` on a `direct` reading: nothing was "
                        "photographed, so there is no photographer to blame "
                        "for the wrong copy")
    if row.get("checksum") not in (None, *CHECKSUM):
        problems.append(f"unknown checksum {row['checksum']!r}")
    if row.get("name_attestation") not in (None, "optical_only",
                                           "unresolved", "full"):
        problems.append(f"unknown name_attestation "
                        f"{row['name_attestation']!r}")
    problems.extend(_reader_problems(row))
    return not problems, problems


def _reader_problems(row):
    """Does the reader's error profile permit the fields this row supplies?

    The name is the one that matters. A reader whose failure is not
    self-detecting cannot supply it, because nothing downstream would catch a
    confident substitution and `unsure_is_unresolved` will not fire -- the
    reader does not abstain because it does not know it should.
    """
    profile = row.get("reader_reliability")
    if profile is None:
        return []                       # already reported as missing
    if profile not in READER_PROFILES:
        return [f"unknown reader_reliability {profile!r}; an unclassified "
                "reader is not assumed to be a reliable one"]
    problems = []
    supplies_name = (row.get("name")
                     and row.get("name_attestation") != "unresolved")
    if supplies_name:
        allowed, why = may_read(profile, "name")
        if not allowed:
            problems.append(f"reader {profile!r} supplied a name: {why}")
    return problems


def reading_is_re_checkable(row):
    """Can anyone go back and look at what was read?

    True only for a photograph WITH a reference identifying which image. A
    photograph nobody can find again is a card in a hand.
    """
    method = READING_METHODS.get(row.get("reading_method"))
    if not method or not method["re_checkable"]:
        return False
    return bool(row.get("image_ref"))
