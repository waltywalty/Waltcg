"""`waft resolve review` -- walk the queue of matches nobody has confirmed.

Everything the resolver could not settle lands here: no match, an ambiguous
pair, or a fuzzy match below the 0.9 signal threshold. The queue is the reason
a low-confidence match is WRITTEN rather than discarded -- you cannot review a
row that was never recorded.

A decision made here is written as `resolved_by='manual'`, which outranks
everything and is never overwritten by a later automatic pass.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store.db import Store  # noqa: E402


def queue(store: Store, limit=50):
    """Rows a signal may not use, newest first."""
    return store.con.sql(f"""
        SELECT row_id, card_uid, source, external_id, confidence, resolved_by,
               observed_at
        FROM ({store.as_of_view('card_xref', _dt.datetime.utcnow()).sql_query()})
        WHERE resolved_by = 'fuzzy' AND confidence < 0.9
        ORDER BY observed_at DESC LIMIT {int(limit)}
    """).fetchall()


def review(store: Store, limit=50, decide=None):
    rows = queue(store, limit)
    if not rows:
        print("queue empty: every mapping is exact, manual, or fuzzy >= 0.9")
        return 0
    print(f"{len(rows)} mapping(s) excluded from signals pending review\n")
    for row_id, card_uid, source, external_id, confidence, _by, observed in rows:
        print(f"  #{row_id}  {source}:{external_id}")
        print(f"      -> {card_uid}   confidence {float(confidence):.3f}")
        print(f"      seen {observed}")
        if decide is None:
            continue
        answer = decide(row_id, card_uid, source, external_id, float(confidence))
        if answer in (None, "skip"):
            print("      skipped\n")
            continue
        store.add_xref(card_uid=answer, source=source, external_id=external_id,
                       confidence=1.0, resolved_by="manual",
                       as_of=observed, observed_at=_dt.datetime.utcnow(),
                       supersedes=row_id)
        print(f"      confirmed as {answer} (manual, supersedes #{row_id})\n")
    return 0


def _prompt(row_id, card_uid, source, external_id, confidence):
    reply = input("      [enter] skip / 'y' accept / paste a card_uid: ").strip()
    if not reply:
        return None
    return card_uid if reply.lower() == "y" else reply


def main(argv=None):
    parser = argparse.ArgumentParser(prog="waft resolve")
    parser.add_argument("command", choices=["review", "queue"])
    parser.add_argument("--db", default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args(argv)

    store = Store(args.db) if args.db else Store()
    if args.command == "queue":
        rows = queue(store, args.limit)
        if args.json:
            print(json.dumps([dict(zip(
                ("row_id", "card_uid", "source", "external_id", "confidence",
                 "resolved_by", "observed_at"), map(str, r))) for r in rows],
                indent=2))
        else:
            for r in rows:
                print(r)
        return 0
    return review(store, args.limit,
                  decide=None if args.non_interactive else _prompt)


if __name__ == "__main__":
    sys.exit(main())
