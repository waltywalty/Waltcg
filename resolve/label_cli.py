"""`waft label` -- adjudicate candidates, do not author them.

    python -m resolve.label_cli propose --catalog ingest/targets.json
    python -m resolve.label_cli review
    python -m resolve.label_cli status

The division of labour is the whole point. The generator proposes and the
resolver states its own answer; you confirm, correct or reject. That is what
keeps the score honest: a set generated from the catalogs the resolver reads
would measure agreement with its own inputs, and a human verdict is the only
thing that breaks the circle.

Every accepted row records HOW it was adjudicated -- `confirmed` means you
agreed with the resolver, `corrected` means you overrode it. A set made
entirely of confirmations is a warning sign, not a triumph: it means either the
candidates were too easy or the adjudication was not real, and `status` says so.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve.candidates import (HARD_CASE_SHARE, MIN_PER_COMBO,  # noqa: E402
                                TARGET_PER_COMBO, TARGET_TOTAL, generate,
                                shortfall)
from resolve.resolver import Resolver  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELLED = os.path.join(REPO, "tests", "fixtures", "labelled_200.json")
QUEUE = os.path.join(REPO, "tests", "fixtures", "label_queue.json")

# Which generator priority maps to which hard-case tag in the labelled set.
HARD_CASE = {
    "same_art_across_languages": "same_art_different_language",
    "reprint_across_sets": "reprint",
    "alt_art_vs_base": "alt_art_variant",
    "promo_vs_set": "promo_vs_set",
    "lowest_confidence": None,
}


# Every confidence a labelled row may carry, and what each one buys.
#
# `verified` is the ONLY one that scores. That asymmetry is the point: a
# single-source identity is one transcription error away from being wrong, and
# precision computed over it measures the source rather than the resolver.
CONFIDENCE = ("verified", "single_source", "in_repo", "unstated")
SCORED = ("verified",)

REQUIRED_FIELDS = ("card_uid", "game", "set_code", "number", "variant",
                   "language", "name", "source", "confidence")

# Fields a superseded row must NOT pass on. These are claims about provenance
# and standing, and the whole point of superseding is that the new row makes
# its own -- inheriting them would let a discarded claim survive its own
# replacement.
_NOT_INHERITED = frozenset({"confidence", "source", "verified_from",
                            "supersedes", "supersedes_confidence",
                            "inherited_fields", "adjudication"})


def ingest(rows, labelled_path=LABELLED, dry_run=False,
           supersede_unstated=False):
    """Merge externally-researched rows into the labelled set.

    Refuses rather than repairs. A row that will not validate is REPORTED and
    skipped, never coerced into shape -- an identity is the one thing in this
    project that must not be guessed at, and a loader that fills in a plausible
    variant is exactly how a wrong card enters ground truth wearing the costume
    of a verified one.

    Returns (accepted, rejected, report).
    """
    from resolve.identity import (KNOWN_CONFUSABLE_NUMBERS,
                                  canonical_set_code, card_uid as build_uid,
                                  is_variant, why_not_a_variant)

    labelled = _load(labelled_path, {"cards": []})
    existing = {c["card_uid"]: c for c in labelled.get("cards", [])}
    accepted, rejected, aliased, superseded = [], [], [], []

    for index, row in enumerate(rows):
        why = []
        # THE SET CODE IS A KEY, NOT A CLAIM. A row whose identity came from
        # outside the catalog is still non-circular when its set_code is
        # spelled the catalog's way -- and a key that matches nothing scores
        # nothing. The mapping is declared in `SET_CODE_ALIASES` and every
        # application is reported, so this is a normalisation you can audit
        # rather than a coercion you cannot see.
        canonical, alias = canonical_set_code(row.get("game"),
                                              row.get("language"),
                                              row.get("set_code"))
        if alias:
            row = dict(row, set_code=canonical,
                       set_code_as_sourced=row.get("set_code"))
            if row.get("card_uid"):
                row["card_uid"] = ":".join(
                    [row["game"], canonical, row["number"], row["variant"],
                     row["language"]])
            aliased.append((index, alias["code"], alias["why"]))
        missing = [f for f in REQUIRED_FIELDS if not row.get(f)]
        if missing:
            why.append("missing " + ", ".join(missing))
        if row.get("confidence") and row["confidence"] not in CONFIDENCE:
            why.append(f"confidence {row['confidence']!r} is not one of "
                       + ", ".join(CONFIDENCE))
        # PER GAME. `sr` is a Pokemon printing and a One Piece RARITY, and a
        # shared vocabulary would have to pick one -- the third time this
        # collision has appeared, after the rarity letters and the band tables.
        if row.get("variant") and not is_variant(row["variant"],
                                                 row.get("game")):
            why.append(why_not_a_variant(row["variant"], row.get("game")))
        if not why:
            try:
                expected = build_uid(row["game"], row["set_code"],
                                     row["number"], row["variant"],
                                     row["language"])
            except Exception as exc:                      # noqa: BLE001
                why.append(f"card_uid will not build: {exc}")
            else:
                # THE UID IS DERIVED, NOT TRUSTED. A row whose stated uid
                # disagrees with its own fields is a transcription error, and
                # accepting either half of it would put a wrong identity into
                # the set that scores identity.
                if row["card_uid"] != expected:
                    why.append(f"card_uid says {row['card_uid']!r} but its own "
                               f"fields build {expected!r}")
        # A NUMBER THAT BELONGS TO ANOTHER MARKET. `083/069` for Rayquaza
        # VMAX is the Korean printing's denominator, and it is dangerous
        # precisely because it parses: it looks like a collector number, reads
        # like one, and points at a printing this project does not track. A
        # loader that accepts it puts a card that does not exist here into the
        # set that defines what exists here.
        confusable = KNOWN_CONFUSABLE_NUMBERS.get(
            (row.get("game"), row.get("set_code"), row.get("name")))
        if confusable and row.get("number") in confusable["confusable"]:
            why.append(f"number {row['number']!r} is a KNOWN CONFUSABLE for "
                       f"this card -- {confusable['why']} The number for this "
                       f"card is {confusable['correct']!r}")

        if not why and row["card_uid"] in existing:
            previous = existing[row["card_uid"]]
            if (supersede_unstated
                    and previous.get("confidence") == "unstated"
                    and row.get("confidence") in ("verified", "single_source")):
                # `unstated` is not a competing claim. It means "seeded before
                # this field existed and the source count was never recorded" --
                # there is no information in it that a sourced row lacks. So
                # this is not a PROMOTION of an existing claim, it is a claim
                # replacing a non-claim, and the append-only convention applies:
                # the new row carries a `supersedes` reference rather than the
                # old one being edited in place.
                # CARRY FORWARD WHAT THE NEW ROW DOES NOT SUPPLY. Superseding
                # is a correction, not a deletion: the incoming row has better
                # provenance, and that is no reason to lose a `hard_case` tag or
                # an artist the old row recorded. The new row wins wherever it
                # has a value; the old one fills the gaps.
                inherited = {k: v for k, v in previous.items()
                             if k not in row and k not in _NOT_INHERITED}
                row = dict(inherited, **row)
                row.update(supersedes=previous.get("card_uid"),
                           supersedes_confidence="unstated",
                           inherited_fields=sorted(inherited) or None)
                row = {k: v for k, v in row.items() if v is not None}
                superseded.append(row["card_uid"])
            elif previous.get("confidence") == row.get("confidence"):
                why.append("already in the set at the same confidence")
            else:
                why.append(f"already in the set at confidence "
                           f"{previous.get('confidence')!r}; promoting or "
                           "demoting a row is a deliberate edit, not an import"
                           + ("" if previous.get("confidence") != "unstated"
                              else ". Pass --supersede-unstated: an `unstated` "
                                   "row is not a competing claim"))
        if why:
            rejected.append({"index": index, "row": row, "why": why})
        else:
            accepted.append(row)

    if accepted and not dry_run:
        replaced = {r["supersedes"] for r in accepted if r.get("supersedes")}
        kept = [c for c in labelled.get("cards", [])
                if c["card_uid"] not in replaced]
        labelled["cards"] = sorted(kept + accepted, key=lambda c: c["card_uid"])
        labelled["_status"] = _status_line(labelled)
        _save(labelled_path, labelled)

    report = collections.Counter(r.get("confidence") for r in accepted)
    report["_aliased"] = len(aliased)
    report["_superseded"] = len(superseded)
    return accepted, rejected, report


UPGRADE_PATH = {("single_source", "verified")}


def upgrade(card_uid, to, second_source, labelled_path=LABELLED,
            dry_run=False, date=None):
    """Promote one row's confidence, naming the source that earned it.

    NOT part of `ingest`. A re-import must never promote -- that is how a
    single-source row quietly becomes ground truth because somebody sent the
    same file twice. Promotion is a deliberate act with a name attached, and
    the name is the whole point: `verified` is a claim that TWO INDEPENDENT
    sources agree, so the second one has to be recorded or the claim is
    unauditable.

    Only single_source -> verified. Demotion is not an upgrade and does not
    belong here; `in_repo` and `unstated` are different provenance rather than
    a lower rung of the same ladder.
    """
    labelled = _load(labelled_path, {"cards": []})
    card = next((c for c in labelled.get("cards", [])
                 if c["card_uid"] == card_uid), None)
    if card is None:
        return None, f"{card_uid} is not in the set"
    was = card.get("confidence")
    if (was, to) not in UPGRADE_PATH:
        return None, (f"{card_uid} is {was!r}; only "
                      + " and ".join(f"{a} -> {b}" for a, b in
                                     sorted(UPGRADE_PATH))
                      + " is an upgrade. Anything else is a re-adjudication, "
                        "not a promotion.")
    if not second_source:
        return None, ("--second-source is required: `verified` claims two "
                      "independent sources agree, and an unnamed one cannot "
                      "be checked")
    card["confidence"] = to
    card["upgraded"] = {"from": was, "to": to, "second_source": second_source,
                        "date": date or _today()}
    if not dry_run:
        _save(labelled_path, labelled)
    return card, ""


def _today():
    import datetime
    return datetime.date.today().isoformat()


def map_classes(labelled_path=LABELLED, dry_run=False):
    """Translate `difficulty_class` tags into `hard_cases` kinds.

    A translation, not an inference: `resolve/hard_cases.py` quotes the C class
    definition each mapping came from. A class with no kind is REPORTED and
    left alone -- folding C6 into `alt_art_variant` would lose the distinction
    that makes it a blocking failure.

    Returns (changed, unmapped, report).
    """
    from resolve.hard_cases import (classes_of, hard_cases_of,
                                    kinds_for_classes, reprint_shape_of)

    labelled = _load(labelled_path, {"cards": []})
    changed, unmapped = [], collections.Counter()
    for card in labelled.get("cards", []):
        classes = classes_of(card)
        if not classes:
            continue
        kinds, missing = kinds_for_classes(classes, card)
        for name in missing:
            unmapped[name] += 1
        # `hard_cases` is DERIVED and fully recomputed, never merged into.
        # Merging would make a re-tag additive: correcting a row from C5 to C6
        # would leave the C5 kind behind, and the row would go on claiming a
        # gate requirement it no longer satisfies. `hard_case`, the legacy
        # hand-set field, is never touched -- `hard_cases_of` unions the two.
        before = tuple(card.get("hard_cases") or ())
        shape = reprint_shape_of(card)
        if tuple(kinds) != before or shape != card.get("reprint_shape"):
            card["hard_cases"] = list(kinds)
            if shape:
                # WHICH of the three reprint shapes, on the row. `reprint`
                # alone says two sets printed one card; it does not say
                # whether the number moved, and that is the difference
                # between a miss and a merge.
                card["reprint_shape"] = shape
            changed.append((card["card_uid"], classes, tuple(kinds), before))
    if changed and not dry_run:
        _save(labelled_path, labelled)
    return changed, unmapped, len(labelled.get("cards", []))


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _save(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _catalog_from(path):
    """Flatten ingest/targets.json into the card list the generator wants."""
    raw = _load(path, {})
    if "cards" in raw:                      # already a flat list
        return raw["cards"]
    seen, out = set(), []
    for key, value in raw.items():
        if not isinstance(value, dict) or "cards" not in value:
            continue
        for card in value["cards"]:
            uid = card.get("card_uid")
            if uid and uid not in seen:
                seen.add(uid)
                out.append(card)
    return out


# The two combinations tcgdex covers directly, plus the Japanese printing they
# are pinned against. JP is not a target -- it is there because the sharpest
# test in the set is a Chinese card against its Japanese parent, and you cannot
# build that pair from one side of it.
TCGDEX_COMBOS = (("pkmn", "CN-S"), ("pkmn", "CN-T"))
PAIRING_PARENT = ("pkmn", "JP")


def _catalog_from_tcgdex(combos=TCGDEX_COMBOS, adapter=None):
    """Candidates pulled live from tcgdex for the Chinese Pokemon printings.

    Run #5 established the coverage: 877 cards for CN-S and 7,436 for CN-T. So
    the 55 cards those two combos need no longer have to be typed.

    This does NOT weaken the non-circularity argument, and it is worth being
    precise about why. The circle ADR-0016 refuses is *generating labels* from
    the catalog the resolver reads. This generates PROPOSALS from it. The human
    verdict is what breaks the circle, and it is unchanged -- what changed is
    only that the proposal no longer has to be typed from memory.

    The Japanese printing comes too, because pairing is the point: CN-T shares
    the Japanese numbers and CN-S does not, so one of those pairs tests the
    merge failure and the other tests the miss.
    """
    from ingest.catalog_sources import TcgdexAdapter

    adapter = adapter or TcgdexAdapter()
    out, failures = [], []
    for game, language in list(combos) + [PAIRING_PARENT]:
        try:
            rows = adapter.enumerate_combo(game, language)
        except Exception as exc:                            # noqa: BLE001
            failures.append(f"{game}:{language}: {type(exc).__name__}: {exc}")
            continue
        for row in rows:
            out.append({"card_uid": row["card_uid"], "game": game,
                        "language": language, "set_code": row["set_code"],
                        "number": row["number"], "variant": row["variant"],
                        "name": row.get("name_jp") or row.get("name_en") or "",
                        "rarity": row.get("rarity"),
                        "artist": row.get("artist")})
    return out, failures


def propose(catalog_path, out_path=QUEUE, source="targets", combos=None):
    if source == "tcgdex":
        catalog, failures = _catalog_from_tcgdex(combos or TCGDEX_COMBOS)
        for line in failures:
            print(f"  tcgdex could not enumerate {line}", file=sys.stderr)
        if not catalog:
            print("tcgdex returned nothing. That is a coverage finding, not a "
                  "shortage of hard cases -- check `python -m ingest.catalog "
                  "--coverage`.", file=sys.stderr)
            return 1
        wanted = {f"{g}:{l}" for g, l in (combos or TCGDEX_COMBOS)}
        return _propose_from(catalog, out_path, only=wanted)
    catalog = _catalog_from(catalog_path)
    if not catalog:
        print(f"no cards in {catalog_path}. Run `python -m ingest.catalog "
              "--write` first -- the queue is generated FROM the catalog.",
              file=sys.stderr)
        return 1
    return _propose_from(catalog, out_path)


def _propose_from(catalog, out_path, only=None):
    labelled = _load(LABELLED, {"cards": []})
    seen = {c["card_uid"] for c in labelled.get("cards", [])}

    per_combo = generate(catalog, Resolver(catalog), seen=seen)
    if only is not None:
        # The Japanese printing was fetched to build pairs against, not to
        # label. Proposing it here would quietly re-open a combo that is not
        # what this run is for.
        per_combo = {k: v for k, v in per_combo.items() if k in only}
    queue = [idea.as_dict() for ideas in per_combo.values() for idea in ideas]
    _save(out_path, {"_generated_at": _dt.datetime.utcnow().isoformat() + "Z",
                     "_note": ("Proposals, NOT labels. Each carries the "
                               "resolver's own answer for you to adjudicate."),
                     "candidates": queue})

    for combo, ideas in sorted(per_combo.items()):
        kinds = collections.Counter(i.priority for i in ideas)
        print(f"  {combo:14} {len(ideas):>3}  {dict(kinds)}")
    short = shortfall(per_combo)
    if short:
        print("\nSHORT -- the catalog could not supply enough candidates:")
        for combo, gap in sorted(short.items()):
            print(f"  {combo:14} want {gap['want']:>3}, have {gap['have']:>3}")
        print("A combo the catalog cannot reach yields zero candidates. That "
              "is a coverage fact, not a shortage of hard cases.")
    print(f"\n{len(queue)} candidates -> {out_path}")
    return 0


def _render(index, total, candidate):
    card = candidate["card"]
    print(f"\n[{index}/{total}]  {candidate['priority']}")
    print(f"  {card['game']}:{card['language']}  {card['set_code']} "
          f"{card['number']}  {card.get('variant', '?')}")
    print(f"  name      {card.get('name') or '(none)'}")
    print(f"  rarity    {card.get('rarity') or '(none)'}")
    print(f"  why       {candidate['why']}")
    proposed = candidate["resolver_proposed"]
    route = candidate["resolver_route"] or "no match"
    print(f"  RESOLVER  {proposed or 'REFUSED'}  "
          f"({route}, {candidate['resolver_confidence']:.3f})")
    if candidate.get("siblings"):
        print(f"  siblings  {', '.join(candidate['siblings'])}")


def review(queue_path=QUEUE, decide=None, limit=None):
    queue = _load(queue_path, {"candidates": []})
    pending = [c for c in queue.get("candidates", []) if c.get("verdict") is None]
    if not pending:
        print("nothing pending. Run `propose` first.")
        return 0
    labelled = _load(LABELLED, {"cards": []})
    labelled.setdefault("cards", [])
    existing = {c["card_uid"] for c in labelled["cards"]}

    todo = pending[:limit] if limit else pending
    accepted = corrected = rejected = 0
    for index, candidate in enumerate(todo, 1):
        _render(index, len(todo), candidate)
        answer = (decide or _prompt)(candidate)
        if answer is None or answer == "skip":
            print("  skipped")
            continue
        if answer == "reject":
            candidate["verdict"] = "rejected"
            rejected += 1
            print("  rejected -- not a useful test case")
            continue

        uid = (candidate["resolver_proposed"] if answer == "confirm" else answer)
        if not uid:
            print("  the resolver proposed nothing, so there is nothing to "
                  "confirm. Paste a card_uid or reject.")
            continue
        card = candidate["card"]
        was_correction = uid != candidate["resolver_proposed"]
        candidate["verdict"] = "corrected" if was_correction else "confirmed"
        if uid not in existing:
            row = {"card_uid": uid, "game": card["game"],
                   "set_code": card["set_code"], "number": card["number"],
                   "variant": card.get("variant", "base"),
                   "language": card["language"], "name": card.get("name", ""),
                   "verified_from": "human review via resolve/label_cli",
                   "adjudication": candidate["verdict"],
                   "resolver_proposed": candidate["resolver_proposed"],
                   "resolver_confidence": candidate["resolver_confidence"]}
            hard = HARD_CASE.get(candidate["priority"])
            if hard:
                row["hard_case"] = hard
            labelled["cards"].append(row)
            existing.add(uid)
        accepted += 1
        corrected += 1 if was_correction else 0
        print(f"  {candidate['verdict']} as {uid}")

    _save(queue_path, queue)
    labelled["_status"] = _status_line(labelled)
    _save(LABELLED, labelled)
    print(f"\n{accepted} accepted ({corrected} corrections), {rejected} rejected")
    print(f"labelled set now {len(labelled['cards'])} of {TARGET_TOTAL}")
    return 0


def _prompt(candidate):
    reply = input("  [enter] skip / y confirm / r reject / paste a card_uid: ")
    reply = reply.strip()
    if not reply:
        return None
    if reply.lower() in ("y", "yes"):
        return "confirm"
    if reply.lower() in ("r", "reject", "n", "no"):
        return "reject"
    return reply


def _status_line(labelled):
    cards = labelled.get("cards", [])
    return (f"{'COMPLETE' if len(cards) >= TARGET_TOTAL else 'INCOMPLETE'} -- "
            f"{len(cards)} of {TARGET_TOTAL}")


def status():
    labelled = _load(LABELLED, {"cards": []})
    cards = labelled.get("cards", [])
    # THE GATE COUNTS `verified` ONLY. Reporting the pool size as though it
    # were the ground-truth size is how a set gets called complete while the
    # thing it gates was never tested -- and a single-source row is a candidate,
    # not a fact.
    scored = [c for c in cards if c.get("confidence") in SCORED]
    by_confidence = collections.Counter(c.get("confidence", "unstated")
                                        for c in cards)
    print(f"{len(cards)} rows in the set, of which {len(scored)} are "
          f"ground truth:")
    for value in CONFIDENCE:
        if by_confidence.get(value):
            mark = "  <- counted and scored" if value in SCORED else ""
            print(f"  {value:14} {by_confidence[value]:>4}{mark}")
    print()
    per_combo = collections.Counter(f"{c['game']}:{c['language']}"
                                    for c in scored)
    pool = collections.Counter(f"{c['game']}:{c['language']}" for c in cards)
    from resolve.hard_cases import hard_cases_of
    hard = [c for c in scored if hard_cases_of(c)]
    adjudicated = collections.Counter(
        c.get("adjudication", "seeded") for c in cards)

    print(f"{'combo':14} {'have':>5} {'want':>5} {'floor':>6} {'pool':>5}  state")
    for combo, want in sorted(TARGET_PER_COMBO.items()):
        have = per_combo.get(combo, 0)
        state = ("ok" if have >= want else
                 "below floor" if have < MIN_PER_COMBO else "short")
        print(f"{combo:14} {have:>5} {want:>5} {MIN_PER_COMBO:>6} "
              f"{pool.get(combo, 0):>5}  {state}")
    print("\n`have` is verified rows; `pool` is every row including "
          "single-source candidates and rows that score nothing.")
    print(f"\ntotal {len(scored)} of {TARGET_TOTAL} verified "
          f"({len(cards)} rows in the pool)")
    print(f"hard cases {len(hard)} of {int(TARGET_TOTAL * HARD_CASE_SHARE)} "
          f"({HARD_CASE_SHARE:.0%} of the set)")
    print(f"adjudication {dict(adjudicated)}")
    if adjudicated.get("corrected", 0) == 0 and adjudicated.get("confirmed", 0) > 20:
        print("\nWARNING: every adjudication agreed with the resolver. Either "
              "the candidates were too easy or the review was not real -- and "
              "a set with no corrections cannot distinguish those.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="waft label")
    parser.add_argument("command",
                        choices=["propose", "review", "status", "ingest",
                                 "map-classes", "upgrade"])
    parser.add_argument("--card-uid", default=None,
                        help="the row to upgrade")
    parser.add_argument("--to", default="verified",
                        help="the confidence to promote to")
    parser.add_argument("--second-source", default=None,
                        help="the independent source that earned the "
                             "promotion. Required, and recorded on the row")
    parser.add_argument("--rows", default=None,
                        help="JSON file of externally-researched rows to "
                             "ingest. A list, or an object with a `cards` key. "
                             "Every row needs `source` and `confidence`")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate and report without writing")
    parser.add_argument("--supersede-unstated", action="store_true",
                        help="let a sourced row replace an `unstated` one at "
                             "the same card_uid. `unstated` records no source "
                             "count, so it is not a competing claim -- the new "
                             "row carries a `supersedes` reference")
    parser.add_argument("--source", default="targets",
                        choices=["targets", "tcgdex"],
                        help="where candidates come from. `tcgdex` pulls the "
                             "two Chinese Pokemon combos live, with the "
                             "Japanese printing alongside for pairing")
    parser.add_argument("--combos", default=None,
                        help="comma-separated, e.g. pkmn:CN-S,pkmn:CN-T")
    parser.add_argument("--catalog", default=os.path.join(REPO, "ingest",
                                                          "targets.json"))
    parser.add_argument("--queue", default=QUEUE)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    if args.command == "propose":
        combos = None
        if args.combos:
            combos = tuple(tuple(c.split(":")) for c in args.combos.split(","))
        return propose(args.catalog, args.queue, source=args.source,
                       combos=combos)
    if args.command == "upgrade":
        if not args.card_uid:
            parser.error("upgrade needs --card-uid")
        card, why = upgrade(args.card_uid, args.to, args.second_source,
                            dry_run=args.dry_run)
        if card is None:
            print(f"REFUSED: {why}")
            return 1
        print(f"{args.card_uid}: {card['upgraded']['from']} -> "
              f"{card['upgraded']['to']}  (second source: "
              f"{card['upgraded']['second_source']})"
              + ("  [DRY RUN]" if args.dry_run else ""))
        return 0
    if args.command == "map-classes":
        changed, unmapped, total = map_classes(dry_run=args.dry_run)
        print(f"{len(changed)} of {total} rows given hard_cases"
              + ("  (DRY RUN, nothing written)" if args.dry_run else ""))
        for uid, classes, kinds, before in changed:
            dropped = [k for k in before if k not in kinds]
            note = f"   (dropped {', '.join(dropped)})" if dropped else ""
            print(f"  {uid:46} {','.join(classes):8} -> "
                  f"{', '.join(kinds) or '(none)'}{note}")
        if unmapped:
            print("\nCLASSES WITH NO KIND -- named, not folded into the "
                  "nearest one:")
            from resolve.hard_cases import CLASS_TO_KIND
            for name, count in sorted(unmapped.items()):
                entry = CLASS_TO_KIND.get(name, {})
                print(f"  {name}: {count} row(s). "
                      + (entry.get("note") or "no definition recorded"))
        return 0
    if args.command == "review":
        return review(args.queue, limit=args.limit)
    if args.command == "ingest":
        if not args.rows:
            parser.error("ingest needs --rows FILE")
        payload = _load(args.rows, None)
        if payload is None:
            parser.error(f"{args.rows} does not exist")
        rows = payload.get("cards") if isinstance(payload, dict) else payload
        accepted, rejected, report = ingest(
            rows or [], dry_run=args.dry_run,
            supersede_unstated=args.supersede_unstated)
        print(f"accepted {len(accepted)}  rejected {len(rejected)}"
              + ("  (DRY RUN, nothing written)" if args.dry_run else ""))
        for value in CONFIDENCE:
            if report.get(value):
                mark = "  <- scores" if value in SCORED else ""
                print(f"  {value:14} {report[value]:>4}{mark}")
        if report.get("_aliased"):
            print(f"  set codes normalised to the catalog: "
                  f"{report['_aliased']} (see SET_CODE_ALIASES)")
        if report.get("_superseded"):
            print(f"  superseded an `unstated` row: {report['_superseded']}")
        for entry in rejected:
            uid = entry["row"].get("card_uid", f"row {entry['index']}")
            print(f"  REJECTED {uid}: " + "; ".join(entry["why"]))
        # Rejections are a finding, not a failure: the report IS the
        # deliverable, and a non-zero exit would hide it behind a red step.
        return 0
    return status()


if __name__ == "__main__":
    sys.exit(main())
