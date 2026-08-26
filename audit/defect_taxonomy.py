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

A test written for the wrong species passes and teaches nothing: exercising an
orphaned check directly proves it works, which was never in doubt, and asserting
that an inert check is reachable proves it is called, which was also never in
doubt.

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
                          "payload-key allowlist so it is scanned. Verified "
                          "by planting `market_price` in it: untracked, the "
                          "scan did not see it at all; tracked, the scan "
                          "fails.",
        "test": "tests/test_labelled_ingest.py::"
                "TheMutationHarnessIsInTheRepository -- a missing seal is a "
                "failure, not a pass.",
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
