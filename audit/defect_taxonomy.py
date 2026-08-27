"""Checks that read green without being green, classified BY REMEDY.

This repository has now produced the same defect eight times, and the ADR-0045
table listed them as one kind. They are not one kind. They read identically --
a green check, a passing suite, a clean report -- and they need DIFFERENT
TESTS, which is the only reason the distinction is worth drawing.

    INERT     the check cannot fire. Nothing it could be run against would
              make it complain.
              REMEDY: prove it can fail. A test that feeds it the thing it is
              supposed to catch and asserts it catches it.

    ORPHANED  the check fires perfectly. Nothing calls it at the moment of
              decision.
              REMEDY: prove something invokes it. A test at the DECISION
              POINT, not at the check.

    SUPPRESSED the check fires, something calls it, and its REFUSAL is caught
              and converted into a verdict.
              REMEDY: prove the refusal PROPAGATES. A test that the CALLER
              receives "cannot tell" and does not receive an answer.

A test written for the wrong species passes and teaches nothing: exercising an
orphaned check directly proves it works, which was never in doubt, and asserting
that an inert check is reachable proves it is called, which was also never in
doubt.

The third species is the one both prior remedies pass cleanly, which is why it
took eight instances of the first two to notice it. Given

    try:
        return numbers_denote_same_printing(a, b, set_total=total) is True
    except CannotBridge:
        return str(a) == str(b)

the INERT remedy passes -- feed the bridge two numbers it cannot bridge and it
raises, demonstrably. The ORPHANED remedy passes -- `_numbers_agree` is called
at the decision point, demonstrably. And `CannotBridge`, whose entire purpose
is to stop a caller mistaking "we could not tell" for "they are different
cards", is four lines above a handler doing exactly that. Neither remedy looks
at what happens to the refusal after it is raised, so neither can see this.

Two shapes of inert are worth separating because their remedies differ:

    BY CONSTRUCTION  no input could ever make it fire -- an unreachable
                     branch, a signal wired to an element that does not
                     exist. Remedy: a positive test with an input that MUST
                     fire it.
    BY SCOPE         it fires, over a universe that excludes the thing it was
                     meant to cover -- a scanner that reads `git ls-files` and
                     therefore never sees an untracked file. Remedy: a test
                     that the universe contains the target, which is a
                     different assertion from the check working.
"""

from __future__ import annotations

SPECIES = {
    "inert": {
        "what": "The check cannot fire. No input would make it complain.",
        "reads_as": "A passing check.",
        "remedy": "Prove it can fail.",
        "test_shape": "Feed it the thing it exists to catch; assert it "
                      "catches it. A test that only asserts the clean case "
                      "is what let these survive.",
        "shapes": {
            "by_construction": "No input could ever fire it -- an unreachable "
                               "branch, a signal reading an element that is "
                               "not there.",
            "by_scope": "It fires, over a universe that excludes the target. "
                        "The check works; it was never pointed at the thing.",
        },
    },
    "orphaned": {
        "what": "The check fires correctly. Nothing calls it where the "
                "decision is made.",
        "reads_as": "A passing check, in a module nothing imports at the "
                    "moment that matters.",
        "remedy": "Prove something invokes it.",
        "test_shape": "A test AT THE DECISION POINT that the decision is "
                      "refused. Exercising the check directly proves it "
                      "works, which was never in doubt.",
    },
    "suppressed": {
        "what": "The check fires, something calls it, and its REFUSAL is "
                "caught and converted into a verdict.",
        "reads_as": "A passing check, called from the right place, whose "
                    "'cannot tell' reaches the caller as an answer.",
        "remedy": "Prove the refusal PROPAGATES.",
        "test_shape": "A test that the CALLER receives 'cannot tell' and "
                      "does NOT receive a decision. Asserting the check "
                      "raises proves it fires, which was never in doubt, and "
                      "asserting the caller invokes it proves it is wired, "
                      "which was also never in doubt. BOTH PRIOR REMEDIES "
                      "PASS THIS DEFECT CLEANLY -- that is why it needed its "
                      "own species.",
    },
}

#: Reference shape for `test`: `path::Symbol[::Symbol]`, optionally followed
#: by prose after a space. The symbols are ASSERTED to exist --
#: `tests/test_defect_taxonomy.py` refuses a reference naming something that
#: is not defined, because a registry of remedies whose remedies have been
#: renamed away is the stale list this file exists to catalogue.

#: Every instance this project has produced, with the remedy actually applied.
#: Not a historical curiosity: each entry names the test that would have caught
#: it, and `tests/test_defect_taxonomy.py` asserts that test exists.
INSTANCES = [
    {
        "name": "the mutant seal was never committed",
        "species": "inert",
        "shape": "by_scope",
        "read_as": "`seal intact: 133 mutants`, printed locally.",
        "actually": "The seal file was gitignored by a blanket `*.json` and "
                    "was never in the repository. `check_seal` fired against "
                    "a local-only file, so its green said nothing about the "
                    "shipped repo -- and `no_provider_data`, which reads "
                    "`git ls-files`, could not see it either.",
        "remedy_applied": "The seal is tracked, and deliberately outside the "
                          "payload-key allowlist so it is scanned. AND THE "
                          "SCOPE BUG ITSELF IS FIXED: `no_provider_data` and "
                          "`no_pdf_provenance` now read tracked files PLUS "
                          "untracked-not-ignored ones -- the files the next "
                          "`git add -A` would take. It was NOTED in ADR-0042 "
                          "and left unfixed for three sessions, then "
                          "reproduced verbatim in `no_unguarded_elevation`. "
                          "Noting a defect is not fixing it, and this entry "
                          "said `remedy applied` while the remedy was a "
                          "sentence in a document.",
        "test": "tests/test_pdf_provenance.py::"
                "TheScopeIncludesFilesNotYetTracked -- plants an untracked "
                "payload and an undeclared doc and asserts both are caught.",
    },
    {
        "name": "signal 3 was wired to a rel=canonical that does not exist",
        "species": "inert",
        "shape": "by_construction",
        "read_as": "A third signal, present and abstaining.",
        "actually": "The head holds description, og:*, twitter:*, viewport "
                    "and title. The signal returned absent on every page, "
                    "forever -- and `absent is reported as absent` is exactly "
                    "what a well-behaved abstaining signal looks like.",
        "remedy_applied": "Rebuilt on the body self-reference links, plus a "
                          "test asserting no fixture contains `canonical` -- "
                          "if one appears, the replaced assumption is back.",
        "test": "tests/test_limitless.py::TheSelfReferenceChecksItself::"
                "test_disagreeing_language_links_are_a_page_level_anomaly",
    },
    {
        "name": "the bare-link voting branch was unreachable",
        "species": "inert",
        "shape": "by_construction",
        "read_as": "A handled case.",
        "actually": "Print rows share the header link's URL shape, so bare "
                    "slots are never unanimous and the branch could not be "
                    "taken on any real page.",
        "remedy_applied": "Branch deleted. The abstention that replaced it is "
                          "tested with an input that reaches it.",
        "test": "tests/test_limitless.py::"
                "test_with_no_language_link_and_no_repeat_nothing_distinguishes",
    },
    {
        "name": "CARD_CANDIDATES was three guesses called a probe",
        "species": "inert",
        "shape": "by_construction",
        "read_as": "`the URL shape is probed, not assumed`.",
        "actually": "No candidate could have answered. The probe fired and "
                    "reported three failures, while the working endpoint was "
                    "already in the parser as signal 3's href.",
        "remedy_applied": "The observed shape is first and labelled the only "
                          "non-guess. A test asserts the adapter's own URL is "
                          "recognised by `_SELF_REF` -- endpoint and "
                          "self-reference must be the same shape.",
        "test": "tests/test_limitless.py::"
                "TheEndpointWasInTheObservedDataAllAlong",
    },
    {
        "name": "a name copied from the record it is checked against",
        "species": "inert",
        "shape": "by_construction",
        "read_as": "`cross_language_name_disagreements` reporting nothing.",
        "actually": "It reports nothing BY CONSTRUCTION -- the CN-S name "
                    "would have been derived from the EN name, so the two "
                    "agree whatever is printed on the card.",
        "remedy_applied": "Rows admitted on the number carry NO name. The "
                          "detector also reports what it EXAMINED, so a clean "
                          "result over zero comparisons is visible.",
        "test": "tests/test_identity_rules.py::"
                "TheDetectorReportsWhatItLookedAt",
    },
    {
        "name": "the abstention floor would have failed a correct reader",
        "species": "inert",
        "shape": "by_construction",
        "read_as": "A calibration control on the art-call channel.",
        "actually": "5% of 16 cards is 0.8 cards. A reader whose true rate "
                    "was exactly the floor would have failed it 44% of the "
                    "time, and zero abstentions is significant at n=16 only "
                    "above a 17% true rate.",
        "remedy_applied": "Demoted to a report that gates nothing and prints "
                          "the rate at which zero would have been surprising. "
                          "The per-row disagreement rule carries the weight.",
        "test": "tests/test_corroboration.py::"
                "TheAbstentionRateIsWeakAtThisSampleSize",
    },
    {
        "name": "upgrade() never called the corroboration standard",
        "species": "orphaned",
        "shape": None,
        "read_as": "Four ADRs of composite rules, fully tested and "
                   "mutation-covered.",
        "actually": "`second_source` was a free string. The standard fired "
                    "perfectly, in a module nothing imported at the moment of "
                    "decision. `--second-source \"looked about right\"` "
                    "promoted a row exactly as readily as a physical card.",
        "remedy_applied": "`second_source_is_admissible` on both paths, and "
                          "the structural audit below so the NEXT write path "
                          "fails until it is wired.",
        "test": "tests/test_labelling.py::UpgradeIsWiredToTheStandard -- at "
                "the decision point, not at the check.",
    },
    {
        "name": "CannotBridge was caught and answered",
        "species": "suppressed",
        "shape": None,
        "read_as": "A refusal type with a docstring explaining why it exists, "
                   "raised correctly, caught correctly.",
        "actually": "`catalog_precision._numbers_agree` wrapped the bridge in "
                    "`except CannotBridge: return str(a) == str(b)`. "
                    "`CannotBridge`'s own docstring says it is raised rather "
                    "than returning False so a caller cannot mistake 'we "
                    "could not tell' for 'they are different cards'. Four "
                    "lines later the handler did exactly that, and every "
                    "row whose number could not be bridged was reported as "
                    "a card the catalog does not carry.",
        "remedy_applied": "`_numbers_agree` returns THREE values and `pair()` "
                          "reports COULD NOT TELL as its own bucket -- 4 rows "
                          "on the current catalog that were being counted as "
                          "non-matches. AND THE SPECIES IS NOW AUDITED: "
                          "`audit/checks/no_suppressed_refusal.py` discovers "
                          "every handler that catches a repo-defined "
                          "exception, or a bare `except Exception` around a "
                          "call that can refuse, and fails on any that throws "
                          "the exception away and produces a verdict. It "
                          "found a second one on its first run: a rate-limit "
                          "refusal returning `False` from tcgdex's filter "
                          "probe, which sent the caller to an 8,313-request "
                          "per-card fallback because the source had just said "
                          "stop.",
        "test": "tests/test_suppressed_refusal.py::"
                "TheCallerGetsCannotTellNotAVerdict -- at the CALLER, "
                "asserting the refusal survives the handler.",
    },
    {
        "name": "a rate limit was answered with a measurement",
        "species": "suppressed",
        "shape": None,
        "read_as": "A probe that measures whether `?rarity=` filters, with a "
                   "documented fallback when it does not.",
        "actually": "`filter_is_honoured` caught `AdapterGaveUp` and "
                    "`RateLimited` and returned False, which is the same "
                    "value it returns for a filter it MEASURED and found "
                    "ignored. The caller reads False as 'fall back', and the "
                    "fallback is 8,313 single-card fetches -- started because "
                    "the source had just told us to stop.",
        "remedy_applied": "The refusal is logged and re-raised. The runner "
                          "already knows how to skip a source that gave up.",
        "test": "tests/test_suppressed_refusal.py::"
                "ARateLimitIsNotAMeasurement",
    },
]


def instances_of(species):
    return [entry for entry in INSTANCES if entry["species"] == species]


def remedy_for(species):
    return SPECIES[species]["remedy"]


def species_of(name):
    for entry in INSTANCES:
        if entry["name"] == name:
            return entry["species"]
    return None
