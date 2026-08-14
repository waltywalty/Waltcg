"""Daily run: every adapter, every gap recorded, loud failure.

The design rule: **a source that produced nothing writes a row saying so.**
GOAL D1 wants zero SILENT gaps, which is not zero gaps -- an unreachable
provider is a fact about the day and belongs in the store. A run that skips a
source quietly is indistinguishable from a source with nothing to say, and the
difference is the whole point of a point-in-time store.

Exit code is non-zero when any source failed, so the scheduled workflow goes
red rather than green-with-a-note.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.adapters import ADAPTERS                       # noqa: E402
from ingest.base import AdapterGaveUp, RateLimited          # noqa: E402
from store.db import Store, new_run_id                      # noqa: E402


def _now():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


WRITERS = {
    "price": lambda s, r: s.add_price(as_of=r.as_of, observed_at=r.observed_at,
                                      source=r.source, **r.payload),
    "pop": lambda s, r: s.add_pop(as_of=r.as_of, observed_at=r.observed_at,
                                  source=r.source, **r.payload),
    "fx": lambda s, r: s.add_fx(as_of=r.as_of, observed_at=r.observed_at,
                                source=r.source, **r.payload),
    "sentiment": lambda s, r: s.add_sentiment(as_of=r.as_of,
                                              observed_at=r.observed_at,
                                              source=r.source, **r.payload),
}


def run_source(store: Store, name: str, adapter, targets) -> dict:
    run_id = new_run_id()
    started = _now()
    store.con.execute(
        "INSERT INTO ingest_run (run_id, source, started_at, status) "
        "VALUES (?, ?, ?, ?)", [run_id, name, started, "running"])

    preflight = adapter.preflight()
    if preflight["key_required"] and not preflight["ready"]:
        # Never send an unauthenticated request. It comes back as a generic
        # failure and gets recorded as "the source had nothing", which is the
        # one thing this store must not confuse.
        store.add_gap(source=name, kind="auth", reason="key absent",
                      detail=f"{preflight['env']} is not set",
                      as_of=started, observed_at=_now())
        _finish(store, run_id, "untested", 0, 1, adapter, "key absent")
        return {"source": name, "status": "untested", "reason": "key absent",
                "rows": 0, "gaps": 1}

    rows = gaps = 0
    try:
        records = adapter.fetch(since=None, **targets)
    except RateLimited as exc:
        store.add_gap(source=name, kind="quota", reason="rate limited",
                      detail=str(exc)[:400], as_of=started, observed_at=_now())
        _finish(store, run_id, "rate_limited", 0, 1, adapter, str(exc)[:400])
        return {"source": name, "status": "rate_limited", "rows": 0, "gaps": 1}
    except AdapterGaveUp as exc:
        store.add_gap(source=name, kind="unreachable", reason="adapter gave up",
                      detail=str(exc)[:400], as_of=started, observed_at=_now())
        _finish(store, run_id, "failed", 0, 1, adapter, str(exc)[:400])
        return {"source": name, "status": "failed", "rows": 0, "gaps": 1,
                "detail": str(exc)[:200]}

    for record in records:
        writer = WRITERS.get(record.kind)
        if writer is None:
            continue
        writer(store, record)
        rows += 1

    if rows == 0:
        # Reached the source and got nothing. A DIFFERENT fact from not
        # reaching it, and recorded as one.
        store.add_gap(source=name, kind="empty",
                      reason="source reachable, returned no rows",
                      as_of=started, observed_at=_now())
        gaps += 1

    _finish(store, run_id, "ok", rows, gaps, adapter, adapter.quota.note())
    return {"source": name, "status": "ok", "rows": rows, "gaps": gaps,
            "quota": adapter.quota.note()}


def _finish(store, run_id, status, rows, gaps, adapter, detail):
    store.con.execute(
        "INSERT INTO ingest_run (run_id, source, started_at, finished_at, "
        "status, rows_written, gaps_written, quota_remaining, detail) "
        "SELECT run_id || ':done', source, started_at, ?, ?, ?, ?, ?, ? "
        "FROM ingest_run WHERE run_id = ?",
        [_now(), status, rows, gaps, adapter.quota.remaining, detail, run_id])


def main(argv=None):
    parser = argparse.ArgumentParser(description="daily ingest run")
    parser.add_argument("--db", default=None)
    parser.add_argument("--sources", default="all")
    parser.add_argument("--targets", default=None,
                        help="JSON file of per-source fetch arguments")
    args = parser.parse_args(argv)

    targets = {}
    if args.targets and os.path.exists(args.targets):
        with open(args.targets, encoding="utf-8") as handle:
            targets = json.load(handle)

    names = list(ADAPTERS) if args.sources == "all" else args.sources.split(",")
    store = Store(args.db) if args.db else Store()

    results = []
    for name in names:
        adapter_cls = ADAPTERS.get(name)
        if adapter_cls is None:
            print(f"unknown source {name}", file=sys.stderr)
            return 2
        results.append(run_source(store, name, adapter_cls(),
                                  targets.get(name, {})))

    print(json.dumps(results, indent=2))
    seal = store.verify_seal()
    print(json.dumps({"seal": seal}, indent=2))

    failed = [r for r in results if r["status"] in ("failed", "rate_limited")]
    untested = [r for r in results if r["status"] == "untested"]
    if failed:
        print(f"\nFAILED: {[r['source'] for r in failed]} -- recorded as gaps, "
              "not skipped", file=sys.stderr)
        return 1
    if untested:
        print(f"\nUNTESTED: {[r['source'] for r in untested]} (no key). These "
              "are gaps, not zeroes.", file=sys.stderr)
        return 1
    if not seal["intact"]:
        print(f"\nSEAL BROKEN at {seal['broken_at']}: history was modified "
              "outside the store's writer.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
