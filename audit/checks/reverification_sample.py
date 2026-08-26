#!/usr/bin/env python3
"""Blind re-verification: measure the error rate IN ground truth.

ADR-0015 sets the gate at 0.98 measured precision and never says what it
assumes: THAT THE LABELS ARE RIGHT. Measured precision is capped at (1 - e),
where e is the ground-truth error rate, because a perfect resolver disagrees
with a wrong label. Three errors are already known in this set -- the
OP01-002/003 name swap, OP01-121 named as the wrong character, and the same
card under two set-code spellings -- all found by cross-batch comparison
rather than by any check. The uncaught rate is unmeasured.

At 250 rows the 0.98 threshold allows 5 errors. If e is around 1%, label noise
alone consumes half that budget before the resolver is asked anything. The
gate's central number rests on an unestimated quantity.

THE PROTOCOL, same shape as the art calls:

  1. This module draws the sample from a COMMITTED SEED and prints the
     selection. The draw is committed before any answer comes back.
  2. It emits `game / set_code / number / language` and WITHHOLDS THE NAME --
     the field the known errors live in, and therefore the answer.
  3. The researcher re-derives the names from sources.
  4. `compare()` does the comparison mechanically. Orthography is normalised;
     the claim under test is WHICH CARD, not which spelling.
  5. Disagreements are FINDINGS and the rate is an ESTIMATE WITH AN INTERVAL.
     Not a fix, and not a licence to demote anything.

WHAT N=30 CAN AND CANNOT DO. A zero-disagreement sample of 30 bounds e at
9.5%, and the gate needs e < 2%. Thirty rows cannot certify the threshold --
it would take 149. What it CAN do is screen: if e were 10%, a clean sample of
30 happens only 4% of the time. So a small sample is a cheap way to find a
gross problem, and a clean one licenses nothing except moving on to a real
sample. `render()` prints this alongside every result, because a rate without
its interval reads as a measurement.

CONTAMINATION, AND WHY IT IS WORSE THAN OPTIMISTIC. The researcher assembled
most of this set and may recall a name rather than re-derive it. That biases
the estimate optimistic -- a FLOOR on e, never an unbiased estimate. Sharper:
if the recalled memory is of the ORIGINAL MISTAKE, the re-derivation
reproduces it and the comparison agrees. Contamination does not add noise
evenly; it is blind precisely to errors that came from the researcher's own
systematic habits -- and all three known errors are exactly that. A fresh
researcher, or a session with no access to this project, is the clean
instrument. This one is a floor.

Usage:
    python -m audit.checks.reverification_sample --draw [--n 30] [--seed ...]
    python -m audit.checks.reverification_sample --compare answers.json
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from resolve.identity import normalise_name  # noqa: E402
from resolve.label_cli import LABELLED, SCORED  # noqa: E402

#: Pinned so the draw is reproducible and can be committed before any answer
#: arrives. Changing it after seeing results is re-rolling the dice.
SEED = 20260825

#: What the researcher is shown. The NAME is absent by construction -- it is
#: the answer, and the field every known error lives in.
BLINDED_FIELDS = ("game", "set_code", "number", "variant", "language")


def clopper_pearson_upper(n, errors=0, alpha=0.05):
    """Upper bound on the error rate. Bisection, pinned by a test -- the last
    bisection in this repository was inverted and returned 0.0 for every
    input, which passes `assertLess` silently."""
    if n <= 0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        tail = sum(math.comb(n, k) * mid ** k * (1 - mid) ** (n - k)
                   for k in range(errors + 1))
        if tail > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def detectable(n, e, alpha=0.05):
    """P(a sample of n sees ZERO disagreements | true rate e)."""
    return (1 - e) ** n


def draw(n=30, seed=SEED, path=LABELLED):
    """A stratified sample, proportional to each combination's size."""
    with open(path, encoding="utf-8") as handle:
        cards = json.load(handle)["cards"]
    scored = [c for c in cards if c.get("confidence") in SCORED]
    by_combo = collections.defaultdict(list)
    for card in scored:
        by_combo[f"{card.get('game')}:{card.get('language')}"].append(card)

    rng = random.Random(seed)
    total = len(scored)
    picked, allocated = [], 0
    combos = sorted(by_combo)
    for index, combo in enumerate(combos):
        rows = sorted(by_combo[combo], key=lambda c: c["card_uid"])
        if index == len(combos) - 1:
            take = min(n - allocated, len(rows))
        else:
            take = min(round(n * len(rows) / total), len(rows))
        allocated += take
        picked.extend(rng.sample(rows, take))
    return sorted(picked, key=lambda c: c["card_uid"]), total


def render_request(sample):
    """What the researcher sees. No names."""
    lines = ["### Blind re-verification request", "",
             f"**{len(sample)} identities.** Re-derive the NAME for each from "
             "sources. The name is deliberately absent: it is the field the "
             "known errors live in, so showing it would make this a "
             "confirmation rather than a re-derivation.", "",
             "| # | game | set_code | number | variant | language |",
             "|---:|---|---|---|---|---|"]
    for index, card in enumerate(sample, start=1):
        lines.append(f"| {index} | {card['game']} | {card['set_code']} "
                     f"| {card['number']} | {card['variant']} "
                     f"| {card['language']} |")
    lines += ["", "Return JSON: a list of "
              '`{"game":…, "set_code":…, "number":…, "variant":…, '
              '"language":…, "name":…}`. Use `null` for a name you cannot '
              "derive -- an abstention costs nothing and is not a "
              "disagreement."]
    return "\n".join(lines) + "\n"


def compare(sample, answers):
    """Mechanical. Orthography is normalised; the claim is WHICH CARD."""
    by_key = {}
    for card in sample:
        by_key[tuple(str(card.get(f)) for f in BLINDED_FIELDS)] = card
    results, unmatched = [], []
    for answer in answers:
        key = tuple(str(answer.get(f)) for f in BLINDED_FIELDS)
        card = by_key.get(key)
        if card is None:
            unmatched.append(answer)
            continue
        returned = answer.get("name")
        if not returned:
            verdict = "abstained"
        elif normalise_name(returned) == normalise_name(card.get("name")):
            verdict = "agrees"
        else:
            verdict = "DISAGREES"
        results.append({"card_uid": card["card_uid"], "verdict": verdict,
                        "in_file": card.get("name"), "returned": returned})
    return results, unmatched


def render(results, unmatched, n_drawn):
    compared = [r for r in results if r["verdict"] != "abstained"]
    wrong = [r for r in compared if r["verdict"] == "DISAGREES"]
    abstained = [r for r in results if r["verdict"] == "abstained"]
    n = len(compared)
    lines = ["### Blind re-verification result", "",
             f"**{n} of {n_drawn} drawn identities were re-derived and "
             f"compared.** {len(abstained)} abstained. "
             f"{len(wrong)} disagree.", ""]

    if not n:
        lines += ["Nothing was compared, so nothing was measured. That is a "
                  "different thing from a clean result and must not be read "
                  "as one."]
        return "\n".join(lines) + "\n"

    point = len(wrong) / n
    upper = clopper_pearson_upper(n, len(wrong))
    lines += [f"**Ground-truth error rate: point estimate {point:.1%}, "
              f"95% upper bound {upper:.1%}.**", "",
              "This is a FLOOR, not an unbiased estimate. See the "
              "contamination note in this module's docstring: the researcher "
              "assembled most of this set, and where a recalled memory is of "
              "the ORIGINAL MISTAKE the re-derivation reproduces it and the "
              "comparison agrees. The bias is not even noise -- it is blind "
              "to exactly the error class all three known errors belong to.",
              ""]

    lines += ["**What this sample size could and could not do.**", "",
              "| If the true rate were | chance this sample saw nothing |",
              "|---:|---:|"]
    for rate in (0.02, 0.05, 0.10, 0.20):
        lines.append(f"| {rate:.0%} | {detectable(n, rate):.0%} |")
    need = math.ceil(math.log(0.05) / math.log(0.98))
    lines += ["",
              f"ADR-0015 needs `e < 2%`, because measured precision is capped "
              f"at `(1 - e)`. A ZERO-disagreement sample bounds `e` at "
              f"{clopper_pearson_upper(n):.1%}; bounding it below 2% takes "
              f"**{need}** identities. This sample "
              + ("SCREENS for a gross problem and cannot certify the "
                 "threshold." if n < need else
                 "is large enough to certify the threshold."), ""]

    if wrong:
        lines += ["**Disagreements. Findings, not fixes -- nothing is "
                  "corrected or demoted on the strength of this.**", "",
                  "| Card | In the file | Re-derived |", "|---|---|---|"]
        for entry in wrong:
            lines.append(f"| `{entry['card_uid']}` | {entry['in_file']} "
                         f"| {entry['returned']} |")
        lines.append("")
        lines.append("Each needs adjudicating from a third source before "
                     "anyone decides which side is wrong. A disagreement says "
                     "the two readings differ; it does not say which one is "
                     "the error.")
    if abstained:
        lines += ["", f"**{len(abstained)} abstained.** Removed from the "
                  "denominator rather than counted as agreement -- counting "
                  "an abstention as a pass is how a thin sample reads as a "
                  "clean one."]
    if unmatched:
        lines += ["", f"**{len(unmatched)} returned rows matched no drawn "
                  "identity.** Reported rather than dropped: a mismatch here "
                  "means the request and the answer disagree about what was "
                  "asked."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="audit.checks.reverification_sample")
    parser.add_argument("--draw", action="store_true")
    parser.add_argument("--compare", metavar="ANSWERS")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", default=None,
                        help="write the drawn sample here, to be committed "
                             "BEFORE any answer arrives")
    args = parser.parse_args(argv)

    sample, pool = draw(args.n, args.seed)
    if args.draw:
        print(render_request(sample))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump({"seed": args.seed, "n": args.n, "pool": pool,
                           "drawn": [c["card_uid"] for c in sample]},
                          handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            print(f"\nwrote the draw to {args.out} -- commit it before any "
                  "answer arrives, or the sample is not blind")
        return 0
    if args.compare:
        with open(args.compare, encoding="utf-8") as handle:
            payload = json.load(handle)
        answers = payload if isinstance(payload, list) else payload.get("cards")
        results, unmatched = compare(sample, answers or [])
        print(render(results, unmatched, len(sample)))
        return 0
    parser.error("pass --draw or --compare")


if __name__ == "__main__":
    sys.exit(main())
