#!/usr/bin/env python3
"""Precision measured CATALOG ENTRY IN -> LABELLED UID OUT.

WHY THIS EXISTS. The gated precision figure is computed on SELF-RECORDS: the
labelled row goes in and its own `card_uid` is expected back, and the uid is
derived from the same fields the record carries. Input and expectation are the
same data twice, so that measurement cannot fail for a reason that has
anything to do with resolution. It is a no-merge/no-collision check -- a real
property, and the one that broke when 286 rows merged into 234 collisions --
but it is not what the resolver is for. See ADR-0056.

This one feeds a PROVIDER'S OWN PRESENTATION of a card and expects our uid.
The provider says `bw10` / `102`; the labelled set says `sv03.5` / `002/165`.
Bridging that is the resolver's actual job, and unlike the self-record
measurement, this one CAN FAIL.

IT ALSO MAKES `e <= 1 - p` MEAN SOMETHING -- with one refinement worth stating
because it is easy to get backwards. A label error in a UID-BEARING field
(game, set_code, number, variant, language) makes a correctly-resolved catalog
entry disagree, so it lands in `1 - p`. A label error in the NAME does not:
`name` is not a component of the uid, so a row naming the wrong character
still has the right uid and the resolver still gets it right. That is not a
blind spot in this measurement -- a name error does not corrupt a uid
precision figure at all. But it does mean the `e` this bounds is the
UID-BEARING error rate, and the blind re-verification sample measures
something else. Two of the three known errors in this set are name-only.

UNCERTIFIED BY CONSTRUCTION. The 250-row threshold licenses a precision CLAIM;
it is not a prerequisite for taking a measurement. This module reports an
interval and never asserts a threshold, so it can run today and be quoted
honestly as what it is.

Usage:  python -m audit.checks.catalog_precision [--verbose] [--json]
Exit 0 always -- it is a measurement, not a gate.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from resolve.identity import (CannotBridge, canonical_set_code,  # noqa: E402
                              normalise_name, numbers_denote_same_printing)
from resolve.resolver import Resolver  # noqa: E402

# ONE IMPLEMENTATION, imported rather than repeated. This module used to hold
# its own copy of the bisection and shipped it inverted; see ADR-0061.
from audit.interval import clopper_pearson_lower  # noqa: E402

LABELLED = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
TARGETS = os.path.join(REPO, "ingest", "targets.json")
CATALOG_SOURCES = ("tcgapi", "apitcg", "pokemonpricetracker", "manual")

#: How a labelled row is matched to a catalog entry. The join must not be the
#: thing being measured, and neither of these is clean -- so both run and both
#: are reported with what they can and cannot see.
JOINS = {
    "set_and_name": {
        "what": "Same game, language and canonical SET, same normalised NAME. "
                "The NUMBER is deliberately left out of the join, so the "
                "resolver has to bridge the provider's `102` to our "
                "`002/165` -- that bridging is the thing being measured.",
        "independence": "GOOD for the number and the variant, which the join "
                        "does not touch. A name-only join was tried first and "
                        "is INVALID: it paired the labelled Base Set "
                        "Blastoise with a `bw8` Blastoise, because character "
                        "names repeat across dozens of sets. Set-scoped, "
                        "names are near-unique.",
        "blind_to": "A row whose NAME or SET is wrong does not join -- it is "
                    "reported uncovered, never scored wrong. And the catalog "
                    "names cards in the LOCAL SCRIPT while the labelled set "
                    "uses Latin, so this join reaches English rows only.",
    },
    "field": {
        "what": "Same game and language, canonical set code equal, numbers "
                "denoting the same printing.",
        "independence": "WEAK. The join uses uid-bearing fields, so it tests "
                        "the resolver's FORMAT BRIDGING -- bare `102` against "
                        "printed `002/165`, `sv151` against `sv03.5` -- and "
                        "not its identification.",
        "blind_to": "Any label error in the fields it joins on: a wrong "
                    "set_code simply fails to join.",
    },
}


def load_catalog(path=TARGETS):
    """Provider-presented entries, de-duplicated.

    `card_uid` and `variant` are OUR derivations and are deliberately not read
    here -- feeding either back would rebuild the circularity this module
    exists to escape.

    `rarity`, `artist` and `external_id` ARE read, and the distinction
    matters. All three are the provider's own words about the card and NONE is
    derived from the number, which is what this measurement measures. `artist`
    is the strongest of them: the illustrator has nothing to do with the
    number, the set or the name. That makes them the only
    channels available for pairing a catalog entry to a labelled row WITHOUT
    using the field under test -- see ADR-0062. They are carried on the ENTRY
    for that purpose; what reaches the RESOLVER is a separate decision, made
    in `score()`.
    """
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    seen, entries = set(), []
    for source in CATALOG_SOURCES:
        for card in (payload.get(source) or {}).get("cards", []):
            key = (card.get("game"), card.get("language"),
                   card.get("set_code"), card.get("number"))
            if key in seen:
                continue
            seen.add(key)
            entries.append({"source": source, "game": card.get("game"),
                            "language": card.get("language"),
                            "name": card.get("name"),
                            "number": card.get("number"),
                            "set_code": card.get("set_code"),
                            "rarity": card.get("rarity"),
                            "artist": card.get("artist"),
                            "external_id": card.get("external_id")})
    return entries


def _same_set(entry, row):
    """Canonical set codes equal. `canonical_set_code` returns
    `(code, alias_entry_or_None)` -- reading it as a bare string silently
    grouped every row by LANGUAGE and reported six shared sets that were not
    sets at all."""
    left = canonical_set_code(entry["game"], entry["language"],
                              entry["set_code"])[0]
    right = canonical_set_code(row.get("game"), row.get("language"),
                               row.get("set_code"))[0]
    return str(left).lower() == str(right).lower()


#: The third answer. Not `False`: a non-match is a fact and this is not one.
CANNOT_TELL = None


def _numbers_agree(catalog_number, labelled_number, set_total=None):
    """Do these two numbers denote one printing?

    THE SET TOTAL IS THE WHOLE POINT. Without it
    `numbers_denote_same_printing("11", "011/078")` raises `CannotBridge` --
    the same orphaned wiring this module found in the resolver, present in the
    module that found it. The bare `except Exception` below used to swallow
    that into a naked string comparison, which turned "we could not tell"
    into "different card" silently: exactly the confusion `CannotBridge`
    exists to prevent.

    RETURNS THREE THINGS, not two. `True`, `False`, and `CANNOT_TELL`. The
    first version of this returned a bool and a `CannotBridge` became `False`
    -- "we could not tell" silently becoming "different card", which is the
    exact confusion `CannotBridge` was created to prevent, four lines from its
    own docstring saying so. `audit/defect_taxonomy.py` calls that species
    SUPPRESSED, and `audit/checks/no_suppressed_refusal.py` is the check that
    found it here.
    """
    if str(catalog_number) == str(labelled_number):
        # DECIDABLE WITHOUT THE BRIDGE, so it is checked before the bridge is
        # asked. Two identical strings denote the same printing whether or not
        # a total exists to derive one from the other. Written as a fallback
        # inside the handler it read as the refusal being overruled, which is
        # a different thing and the wrong thing.
        return True
    try:
        return numbers_denote_same_printing(catalog_number, labelled_number,
                                            set_total=set_total) is True
    except CannotBridge:
        return CANNOT_TELL


def pair(rows, entries, how="set_and_name", set_totals=None):
    """(row, entry) pairs, the rows that did not pair, and why.

    AMBIGUITY IS NOT A PAIR. A set routinely holds several printings of one
    character -- `sv03.5` has Venusaur ex at `003/165` and again at `198`, and
    non-negotiable 3 says those are different cards. Joining set+name and
    taking the first match paired them, which would have scored the resolver
    wrong for being right. So a name matching more than one entry on either
    side is reported AMBIGUOUS and left out of the denominator.

    That is the fundamental difficulty of this measurement, stated rather than
    worked around: you cannot pair a catalog entry to a labelled row without
    using the number, and the number is the thing being measured. What is left
    is the subset where set+name happens to be unique.
    """
    by_combo = collections.defaultdict(list)
    for entry in entries:
        by_combo[(entry["game"], entry["language"])].append(entry)
    rows_by_key = collections.Counter(
        (r.get("game"), r.get("language"),
         str(_canonical(r)).lower(), normalise_name(r.get("name")))
        for r in rows)

    pairs, unpaired = [], []
    for row in rows:
        candidates = [e for e in by_combo.get(
            (row.get("game"), row.get("language")), ()) if _same_set(e, row)]
        undecided = []
        if how == "set_and_name":
            matches = [e for e in candidates
                       if normalise_name(e["name"]) == normalise_name(
                           row.get("name"))]
        else:
            verdicts = [(e, _numbers_agree(
                e["number"], row.get("number"),
                (set_totals or {}).get(e.get("language"), {}).get(
                    e.get("set_code")))) for e in candidates]
            matches = [e for e, agrees in verdicts if agrees is True]
            undecided = [e for e, agrees in verdicts
                         if agrees is CANNOT_TELL]
        key = (row.get("game"), row.get("language"),
               str(_canonical(row)).lower(), normalise_name(row.get("name")))
        if not matches and how != "set_and_name" and undecided:
            # THE REFUSAL, PROPAGATED. Reporting these as "no catalog entry
            # with this number" would be the suppression one level up: the
            # bridge said it could not tell, and the row would be counted as
            # a card the catalog does not carry.
            unpaired.append((row, f"COULD NOT TELL: {len(undecided)} catalog "
                                  "entr(y|ies) in this set whose numbers "
                                  "could not be bridged -- no set total, or "
                                  "no readable index. Not a non-match."))
        elif not matches:
            unpaired.append((row, "no catalog entry in this set with this "
                                  + ("name" if how == "set_and_name"
                                     else "number")))
        elif len(matches) > 1 or (how == "set_and_name"
                                  and rows_by_key[key] > 1):
            unpaired.append((row, f"AMBIGUOUS: {len(matches)} catalog "
                                  f"entr(y|ies) and {rows_by_key[key]} "
                                  "labelled row(s) share this set and name. "
                                  "Several printings of one character in one "
                                  "set are different cards."))
        else:
            pairs.append((row, matches[0]))
    return pairs, unpaired


def _canonical(card):
    return canonical_set_code(card.get("game"), card.get("language"),
                              card.get("set_code"))[0]


def score(pairs, pool, set_totals=None):
    """Feed the catalog entry; expect the labelled uid.

    `set_totals` is passed through to the resolver. Without it every bare
    provider number is refused for want of a printed counterpart, which is a
    property of the WIRING and not of the resolver's judgement -- and reading
    those refusals as a measurement of the resolver is how the gap stayed
    invisible.
    """
    resolver = Resolver(pool, set_totals=set_totals)
    used = right = 0
    wrong, refused = [], []
    for row, entry in pairs:
        # RARITY IS FED, external_id IS NOT, and the asymmetry is deliberate.
        # Rarity is what production has: `Resolver._fuzzy` derives a variant
        # from it, and withholding it measured a resolver working with less
        # than it really gets. `external_id` reaches the xref/override path,
        # and an xref table built from our own labelling would answer the
        # question with the answer. It stays on the entry, for pairing, and
        # out of the record.
        record = {"source": entry["source"], "game": entry["game"],
                  "language": entry["language"], "number": entry["number"],
                  "set_code": entry["set_code"], "name": entry["name"],
                  "rarity": entry.get("rarity")}
        result = resolver.resolve(record)
        if not result.usable_in_signals:
            refused.append((row["card_uid"], entry))
            continue
        used += 1
        if result.card_uid == row["card_uid"]:
            right += 1
        else:
            wrong.append((row["card_uid"], result.card_uid,
                          f"{entry['set_code']}/{entry['number']}"))
    return {"used": used, "right": right, "wrong": wrong, "refused": refused,
            "precision": (right / used) if used else None,
            "lower_bound": clopper_pearson_lower(used, right) if used else None}


def measure(labelled_path=LABELLED, targets_path=TARGETS):
    with open(labelled_path, encoding="utf-8") as handle:
        data = json.load(handle)
    pool = data["cards"]
    scored = [c for c in pool if c.get("confidence") in ("verified",)]
    entries = load_catalog(targets_path)
    with open(targets_path, encoding="utf-8") as handle:
        set_totals = json.load(handle).get("_set_totals") or {}
    out = {"scored_rows": len(scored), "catalog_entries": len(entries),
           "joins": {}}
    for how in JOINS:
        pairs, unpaired = pair(scored, entries, how, set_totals)
        result = score(pairs, pool, set_totals)
        result["paired"] = len(pairs)
        result["unpaired"] = len(unpaired)
        result["unpaired_by_combo"] = dict(collections.Counter(
            f"{r.get('game')}:{r.get('language')}" for r, _why in unpaired))
        result["unpaired_reasons"] = dict(collections.Counter(
            why.split(":")[0] for _r, why in unpaired))
        result["paired_by_combo"] = dict(collections.Counter(
            f"{r.get('game')}:{r.get('language')}" for r, _e in pairs))
        out["joins"][how] = result
    out["catalog_by_combo"] = dict(collections.Counter(
        f"{e['game']}:{e['language']}" for e in entries))
    return out


def headline(result):
    """THE ONE NUMBER TO QUOTE, with its denominator attached.

    A point estimate of 1.0000 on five resolutions is not a measurement of
    anything, and quoting it without `n` is how the self-record figure came to
    be read as evidence for four sessions. The honest headline is the LOWER
    BOUND and the count that produced it -- and it is the first precision
    figure in this project that could ever have come back bad.
    """
    best, chosen = None, None
    for how, entry in result["joins"].items():
        if entry["used"] and (best is None or entry["used"] > best):
            best, chosen = entry["used"], (how, entry)
    if chosen is None:
        return ("**HEADLINE: no precision figure.** Nothing resolved, so "
                "nothing was scored. Not 1.0, and not 0.0.")
    how, entry = chosen
    return (f"**HEADLINE: 95% lower bound {entry['lower_bound']:.4f} on "
            f"n={entry['used']}** (`{how}` join, {entry['right']} right of "
            f"{entry['used']}). Quote THIS, with the n. The point estimate is "
            f"{entry['precision']:.4f} and on this denominator it is "
            f"compatible with a resolver that is wrong "
            f"{1 - entry['lower_bound']:.0%} of the time.")


def render(result, verbose=False):
    total = result["scored_rows"]
    lines = ["### Precision, catalog entry in -> labelled uid out", "",
             f"**{total} verified rows, {result['catalog_entries']} catalog "
             "entries.** Unlike the gated self-record figure, this "
             "measurement CAN FAIL: the provider's presentation of a card is "
             "genuinely different from ours, and bridging it is the "
             "resolver's job.", "", headline(result), ""]

    for how, entry in result["joins"].items():
        join = JOINS[how]
        used, right = entry["used"], entry["right"]
        lines += [f"#### Join: `{how}`", "", join["what"], "",
                  f"- **paired: {entry['paired']} of {total}** "
                  f"({entry['paired'] / total:.1%})",
                  f"- resolved and usable: {used}",
                  f"- refused by the resolver: {len(entry['refused'])}",
                  f"- right: {right}"]
        if used:
            lines.append(f"- **precision {entry['precision']:.4f}**, 95% "
                         f"lower bound {entry['lower_bound']:.4f}")
        else:
            lines.append("- **precision UNDEFINED** -- nothing was resolved, "
                         "so nothing was scored. Not 1.0, and not 0.0: an "
                         "empty denominator is not a result.")
        if entry["paired"]:
            lines.append(f"- recall over the pairable subset: "
                         f"{right}/{entry['paired']} = "
                         f"{right / entry['paired']:.1%}")
        lines += ["", f"*Independence:* {join['independence']}", "",
                  f"*Blind to:* {join['blind_to']}", ""]
        if entry["unpaired_reasons"]:
            lines += ["Why rows did not pair:", ""]
            for reason, count in sorted(entry["unpaired_reasons"].items(),
                                        key=lambda kv: -kv[1]):
                lines.append(f"- {count}: {reason}")
            lines.append("")
        if entry["wrong"]:
            lines += ["**Wrong matches.** These are the ones that matter -- a "
                      "confident price on the wrong asset:", ""]
            for truth, got, presented in entry["wrong"][:10]:
                lines.append(f"- `{truth}` <- catalog `{presented}` resolved "
                             f"to `{got}`")
            lines.append("")
        if entry["refused"] and verbose:
            lines += ["Refused (the resolver declined to answer -- safer than "
                      "answering wrongly, and it means the card would carry "
                      "no price in production):", ""]
            for truth, presented in entry["refused"][:10]:
                lines.append(f"- `{truth}` <- catalog "
                             f"`{presented['set_code']}/{presented['number']}`")
            lines.append("")

    lines += ["#### What limits coverage today", "",
              "Catalog entries by combination: "
              + ", ".join(f"`{k}` {v}" for k, v in
                          sorted(result["catalog_by_combo"].items())) or "none",
              "",
              "Three separate blockers, none of them this measurement's "
              "design:", "",
              "1. **`optcg` and `riftbound` have no catalog at all.** apitcg "
              "rate-limited for several consecutive runs, so those combos "
              "enumerate zero cards -- 109 labelled rows have nothing to be "
              "measured against.",
              "2. **The catalog names cards in the local script**, the "
              "labelled set in Latin. `pkmn:JP`, `pkmn:CN-S` and `pkmn:CN-T` "
              "cannot join on name at all.",
              "3. **Set coverage barely overlaps.** The labelled set was "
              "built around specific chase cards; the catalog enumerates "
              "whatever the providers serve.", ""]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="audit.checks.catalog_precision")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = measure()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(render(result, args.verbose))
    # A MEASUREMENT, NOT A GATE. It reports an interval and asserts no
    # threshold: the 250-row count licenses a precision CLAIM, and taking the
    # measurement never needed to wait for it.
    return 0


if __name__ == "__main__":
    sys.exit(main())
