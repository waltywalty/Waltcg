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
    per_combo = collections.Counter(f"{c['game']}:{c['language']}" for c in cards)
    hard = [c for c in cards if c.get("hard_case")]
    adjudicated = collections.Counter(
        c.get("adjudication", "seeded") for c in cards)

    print(f"{'combo':14} {'have':>5} {'want':>5} {'floor':>6}  state")
    for combo, want in sorted(TARGET_PER_COMBO.items()):
        have = per_combo.get(combo, 0)
        state = ("ok" if have >= want else
                 "below floor" if have < MIN_PER_COMBO else "short")
        print(f"{combo:14} {have:>5} {want:>5} {MIN_PER_COMBO:>6}  {state}")
    print(f"\ntotal {len(cards)} of {TARGET_TOTAL}")
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
    parser.add_argument("command", choices=["propose", "review", "status"])
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
    if args.command == "review":
        return review(args.queue, limit=args.limit)
    return status()


if __name__ == "__main__":
    sys.exit(main())
