#!/usr/bin/env python3
"""Run the admission gate over the rows that are ALREADY ground truth.

`ingest` is gated now. That is a claim about rows arriving tomorrow. The 239
already in the set were admitted while the check was not called, and nothing
has ever tested them against it -- so "the gate is wired" and "ground truth
passes the gate" are different statements, and only the first one was true.

THE VERDICT THIS SWEEP EXISTS TO REPORT IS NOT PASS OR FAIL. It is
PASS-VACUOUS: the gate returning True because there was nothing to examine.
A sweep that prints `239/239 PASS` without saying how many of those passes
were vacuous is the same clean-report-over-zero-comparisons this project keeps
finding, one layer up -- and it would be reassuring, which is worse than
useless.

So every row gets one of three verdicts:

    PASS      the gate read evidence and approved it
    VACUOUS   the gate approved because the row carries nothing to read
    FAIL      the gate read evidence and refused it

Usage:  python -m audit.checks.sweep_ground_truth [--verbose] [--json]
Exit 0 always. THIS IS A REPORT, NOT A GATE: it describes what is already in
the set, and a description that can fail a build gets silenced rather than
read. `no_unguarded_elevation` is the gate.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from resolve.corroboration import FIELD_ATTESTATION  # noqa: E402
from resolve.label_cli import (LABELLED, SCORED, row_is_admissible,  # noqa: E402
                               second_source_is_admissible)

PASS, VACUOUS, FAIL = "PASS", "VACUOUS", "FAIL"

#: What a row must carry for the gate to have anything to read. Absence is not
#: a defect in the row -- it is a fact about the regime the row was admitted
#: under -- but it IS the difference between a verdict and a formality.
EVIDENCE_FIELDS = ("source_class", "upgraded", "reader_reliability",
                   "checksum", "attested_by", "verified_from")


def verdict_for(row):
    """(verdict, why, evidence) for one row."""
    evidence = sorted(f for f in EVIDENCE_FIELDS if row.get(f))
    admissible, refusal = row_is_admissible(row)
    if not admissible:
        return FAIL, refusal, evidence
    if row.get("source_class"):
        return PASS, (f"source_class {row['source_class']!r} was read and "
                      "accepted"), evidence
    if row.get("upgraded"):
        second = (row["upgraded"] or {}).get("second_source")
        ok, why = second_source_is_admissible(second or "", row)
        if not ok:
            return FAIL, f"its recorded second source is inadmissible: {why}", evidence
        return PASS, (f"promoted with a recorded second source "
                      f"({second!r}), which the gate read"), evidence
    return VACUOUS, ("the gate approved because the row declares no "
                     "`source_class` and records no second source. There was "
                     "nothing to read. This is not the row passing a test; it "
                     "is the test having no input."), evidence


def sweep(path=LABELLED):
    with open(path, encoding="utf-8") as handle:
        cards = json.load(handle)["cards"]
    scored = [c for c in cards if c.get("confidence") in SCORED]
    results = []
    for row in scored:
        state, why, evidence = verdict_for(row)
        results.append({"card_uid": row.get("card_uid"), "verdict": state,
                        "why": why, "evidence": evidence,
                        "combo": f"{row.get('game')}:{row.get('language')}"})
    return results, len(cards)


def render(results, pool, verbose=False):
    tally = collections.Counter(r["verdict"] for r in results)
    total = len(results)
    lines = ["### Retroactive sweep of existing ground truth", "",
             f"**{total} rows at a SCORED confidence, out of {pool} in the "
             "pool.** Every one was admitted before `ingest` consulted the "
             "standard.", "",
             "| Verdict | Rows | What it means |", "|---|---:|---|",
             f"| PASS | {tally[PASS]} | the gate read evidence and approved "
             "it |",
             f"| **VACUOUS** | **{tally[VACUOUS]}** | the gate approved "
             "because the row carries nothing to read |",
             f"| FAIL | {tally[FAIL]} | the gate read evidence and refused "
             "it |", ""]

    vacuous_share = tally[VACUOUS] / total if total else 0
    if vacuous_share > 0.5:
        lines += [
            f"**{tally[VACUOUS]} of {total} rows cannot be tested by this "
            f"gate** ({vacuous_share * 100:.1f}%). Not `100%` -- the rounding "
            "matters when the whole point is not overstating. Not because the "
            "rows are wrong, either: because they do not "
            "carry the fields the gate reads. They were admitted under a "
            "regime that recorded `confidence` as an ASSERTION rather than as "
            "a derivation from named sources, so there is no machine-readable "
            "record of which two sources agreed.", "",
            "Reporting that as `PASS` would be a clean bill of health issued "
            "without an examination.", ""]

    if tally[FAIL]:
        lines += ["**Rows the gate refuses.** Listed, not demoted:", ""]
        for entry in results:
            if entry["verdict"] == FAIL:
                lines.append(f"- `{entry['card_uid']}` -- {entry['why']}")
        lines.append("")

    by_combo = collections.defaultdict(collections.Counter)
    for entry in results:
        by_combo[entry["combo"]][entry["verdict"]] += 1
    lines += ["**By combination.**", "",
              "| Combo | PASS | VACUOUS | FAIL |", "|---|---:|---:|---:|"]
    for combo in sorted(by_combo):
        counts = by_combo[combo]
        lines.append(f"| `{combo}` | {counts[PASS]} | {counts[VACUOUS]} "
                     f"| {counts[FAIL]} |")

    carrying = collections.Counter()
    for entry in results:
        for field in entry["evidence"]:
            carrying[field] += 1
    lines += ["", "**Evidence actually recorded**, across all "
              f"{total} rows:", ""]
    if carrying:
        for field, count in carrying.most_common():
            lines.append(f"- `{field}`: {count}")
    else:
        lines.append("- none. No row carries any of "
                     + ", ".join(f"`{f}`" for f in EVIDENCE_FIELDS) + ".")

    if verbose:
        lines += ["", "**Per row.**", ""]
        for entry in results:
            lines.append(f"- `{entry['card_uid']}` {entry['verdict']}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="audit.checks.sweep_ground_truth")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--path", default=LABELLED)
    args = parser.parse_args(argv)
    results, pool = sweep(args.path)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(render(results, pool, args.verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
