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

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingest.base import AdapterGaveUp, RateLimited          # noqa: E402
from ingest.registry import (ADAPTERS, ALL_SOURCE_NAMES,    # noqa: E402
                             BROKEN_ADAPTERS)
from store.db import Store, new_run_id                      # noqa: E402


SOURCES_YML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "sources.yml")

# Every status a source can end a run in, and whether it fails the run.
#
# The two that used to be one: a source absent BY CHOICE is a gap, and a source
# I meant to configure but did not is a failure. Collapsing them meant one
# deferred paid provider took down a run that four working providers should
# have completed.
# A third distinction joined them: a source that has NEVER been exercised
# against its live service. The three Chinese catalog sources were written
# against documentation, in a sandbox whose egress proxy refuses all three
# hosts, so their endpoint shapes are candidates rather than facts. The first
# real run is the experiment that settles it -- and an experiment that takes
# down four working providers when it comes back negative is a bad experiment.
#
# `unverified_failed` is therefore a gap that reports loudly, with the exact
# error, so run #1 tells us the true endpoint shape. Flipping `unverified` off
# in sources.yml promotes the source to a hard dependency.
STATUS = {
    "ok":                {"failure": False, "ingested": True},
    "empty":             {"failure": False, "ingested": False},
    "deferred":          {"failure": False, "ingested": False},
    "unverified_failed": {"failure": False, "ingested": False},
    "not_configured":    {"failure": True,  "ingested": False},
    "failed":            {"failure": True,  "ingested": False},
    "rate_limited":      {"failure": True,  "ingested": False},
}


def load_expectations(path=SOURCES_YML) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return (yaml.safe_load(handle) or {}).get("sources", {}) or {}


def _now():
    return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)


CARD_IDENTITY = ("card_uid", "game", "set_code", "number", "variant", "language")


def _write_card(store, record):
    """A catalog row, if it carries a whole identity.

    Enrichment records -- an artist, a Chinese name, anything keyed on a
    card_uid alone -- are NOT written and NOT counted. The store is
    insert-or-ignore with no update path, so a partial row would either be
    rejected by the uid CHECK or would win the race and become the card. Both
    are worse than declining, and declining is visible in the row count.
    """
    payload = dict(record.payload)
    if not all(payload.get(k) for k in CARD_IDENTITY):
        return False
    identity = {k: payload.pop(k) for k in CARD_IDENTITY}
    store.upsert_card(observed_at=record.observed_at, source=record.source,
                      **identity, **payload)
    return True


WRITERS = {
    "card": _write_card,
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


def broken_source(store, name, failure, expectation=None) -> dict:
    """A source whose module would not import, recorded as a result.

    Not raised, not skipped: a source that cannot load is a fact about the day
    exactly like an unreachable one, and it belongs in the store and in the
    summary. The traceback goes in the detail because it is the only thing that
    can fix it, and run #4 lost its traceback entirely -- the reporting step
    died alongside the code it was reporting on.
    """
    expectation = expectation or {}
    unverified = bool(expectation.get("unverified"))
    status = "unverified_failed" if unverified else "failed"
    detail = f"import of {failure['module']} failed -- {failure['error']}"
    if unverified:
        detail = ("UNVERIFIED SOURCE, code did not import. Contained to this "
                  "source; the others ran. " + detail)
    store.add_gap(source=name, kind="broken_import",
                  reason="adapter module failed to import",
                  detail=(detail + "\n" + failure["traceback"])[:2000],
                  as_of=_now(), observed_at=_now())
    return {"source": name, "status": status, "expected": True,
            "unverified": unverified, "rows": 0, "gaps": 1, "detail": detail,
            "traceback": failure["traceback"]}


def run_source(store: Store, name: str, adapter, targets,
               expectation=None) -> dict:
    run_id = new_run_id()
    started = _now()
    store.con.execute(
        "INSERT INTO ingest_run (run_id, source, started_at, status) "
        "VALUES (?, ?, ?, ?)", [run_id, name, started, "running"])

    expectation = expectation or {}
    expected = bool(expectation.get("expected", True))

    preflight = adapter.preflight()
    if preflight["key_required"] and not preflight["ready"]:
        # Never send an unauthenticated request: it comes back as a generic
        # failure and gets recorded as "the source had nothing", which is the
        # one thing this store must not confuse.
        #
        # But the run does NOT stop here. Whether this is a gap or a failure
        # depends entirely on whether I meant to configure it.
        status = "not_configured" if expected else "deferred"
        reason = ("key absent but the source is expected"
                  if expected else "deferred by choice")
        detail = f"{preflight['env']} is not set"
        if not expected and expectation.get("deferred_note"):
            detail += f" -- {expectation['deferred_note'].strip()}"
        store.add_gap(source=name, kind="auth", reason=reason, detail=detail,
                      as_of=started, observed_at=_now())
        _finish(store, run_id, status, 0, 1, adapter, detail)
        return {"source": name, "status": status, "reason": reason,
                "expected": expected, "rows": 0, "gaps": 1, "detail": detail}

    # A source whose endpoint shape has never been confirmed against the live
    # service downgrades a hard failure to a loud gap. See STATUS.
    unverified = bool(expectation.get("unverified"))

    rows = gaps = 0
    try:
        records = adapter.fetch(since=None, **targets)
    except (RateLimited, AdapterGaveUp) as exc:
        limited = isinstance(exc, RateLimited)
        status = ("unverified_failed" if unverified and not limited
                  else "rate_limited" if limited else "failed")
        detail = str(exc)[:400]
        if unverified and not limited:
            detail = ("UNVERIFIED SOURCE, first contact failed -- this is the "
                      "measurement, not a regression: " + detail)
        store.add_gap(source=name,
                      kind="quota" if limited else "unreachable",
                      reason="rate limited" if limited else "adapter gave up",
                      detail=detail, as_of=started, observed_at=_now())
        _finish(store, run_id, status, 0, 1, adapter, detail)
        return {"source": name, "status": status, "expected": expected,
                "unverified": unverified, "rows": 0, "gaps": 1,
                "detail": detail[:220]}

    for record in records:
        writer = WRITERS.get(record.kind)
        if writer is None:
            continue
        if writer(store, record) is False:
            continue
        rows += 1

    if rows == 0:
        # Reached the source and got nothing. A DIFFERENT fact from not
        # reaching it, and recorded as one.
        store.add_gap(source=name, kind="empty",
                      reason="source reachable, returned no rows",
                      as_of=started, observed_at=_now())
        gaps += 1

    status = "ok" if rows else "empty"
    _finish(store, run_id, status, rows, gaps, adapter, adapter.quota.note())
    return {"source": name, "status": status, "expected": expected,
            "rows": rows, "gaps": gaps, "quota": adapter.quota.note()}


def _finish(store, run_id, status, rows, gaps, adapter, detail):
    store.con.execute(
        "INSERT INTO ingest_run (run_id, source, started_at, finished_at, "
        "status, rows_written, gaps_written, quota_remaining, detail) "
        "SELECT run_id || ':done', source, started_at, ?, ?, ?, ?, ?, ? "
        "FROM ingest_run WHERE run_id = ?",
        [_now(), status, rows, gaps, adapter.quota.remaining, detail, run_id])


def render_preflight(expectations=None, adapters=None, broken=None) -> str:
    """The pre-run key report, as text.

    It lives here rather than in a heredoc inside the workflow because that is
    where run #4 died: a formatter that read `key_length` on the ready branch,
    correct for five key-bearing adapters and a KeyError on the first keyless
    one. Nothing tested it, because nothing could -- a shell heredoc in a YAML
    file is not reachable from the test suite. Moved here, it is.

    Never raises and never prints a key. A reporting step that can crash is
    worse than no reporting step, because it takes the run with it.
    """
    expectations = load_expectations() if expectations is None else expectations
    adapters = ADAPTERS if adapters is None else adapters
    broken = BROKEN_ADAPTERS if broken is None else broken

    # Every known source, plus anything the caller supplied that is not in the
    # spec list. A report that could only describe the sources it already knew
    # about would go quiet on exactly the one that had just been added.
    names = list(ALL_SOURCE_NAMES)
    names += [n for n in list(adapters) + list(broken) if n not in names]

    lines = []
    for name in names:
        expectation = expectations.get(name, {})
        expected = expectation.get("expected", True)
        if name in broken:
            state = f"CODE DID NOT IMPORT -- {broken[name]['error']}"
        elif name not in adapters:
            state = "not registered"
        else:
            try:
                info = adapters[name]().preflight()
            except Exception as exc:                        # noqa: BLE001
                state = f"preflight raised -- {type(exc).__name__}: {exc}"
            else:
                if not info["key_required"]:
                    state = "ready (no key required)"
                elif info["ready"]:
                    state = (f"ready (key {info['key_length']} chars, "
                             f"starts {info['key_prefix']!r})")
                elif expected:
                    state = (f"NO KEY and expected -- {info['env']} unset, "
                             "run will fail")
                else:
                    state = (f"no key, deferred by choice -- {info['env']} "
                             "unset")
        if expectation.get("unverified"):
            state += "  [unverified: a failure here is a gap, not a failed run]"
        lines.append(f"{name:22} {state}")
    return "\n".join(lines) + "\n"


SYMBOL = {"ok": "ingested", "empty": "reached, no rows",
          "deferred": "skipped by choice", "not_configured": "KEY MISSING",
          "failed": "FAILED", "rate_limited": "RATE LIMITED",
          "unverified_failed": "unverified, did not answer"}


def render_summary(results, seal=None, db_path=None) -> str:
    """The run, as Markdown, built ONLY from the results list.

    Deliberately does not read the database. The summary came back empty once
    because it was reading a store that a earlier step had prevented from being
    created -- so the one artefact whose job is explaining a failure failed
    alongside it. Anything that can fail is not allowed in here.
    """
    ingested = [r for r in results if STATUS[r["status"]]["ingested"]]
    failures = [r for r in results if STATUS[r["status"]]["failure"]]
    deferred = [r for r in results if r["status"] == "deferred"]
    rows = sum(r["rows"] for r in results)

    if failures:
        verdict = f"FAILED -- {len(failures)} configured source(s) did not deliver"
    elif not ingested:
        verdict = "FAILED -- zero sources ingested any rows"
    else:
        verdict = f"OK -- {len(ingested)} source(s) ingested {rows} row(s)"

    lines = [
        "### Ingest run", "", f"**{verdict}**", "",
        "| Source | Status | Rows | Gaps | Detail |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: (not STATUS[r["status"]]["failure"],
                                            r["source"])):
        detail = (r.get("detail") or r.get("quota") or r.get("reason") or "")
        detail = str(detail).replace("|", "\\|").replace("\n", " ")[:160]
        lines.append(f"| `{r['source']}` | {SYMBOL[r['status']]} | {r['rows']} "
                     f"| {r['gaps']} | {detail} |")

    no_import = [r for r in results if r.get("traceback")]
    if no_import:
        lines += ["", "**Sources whose code did not import.** Contained to the "
                  "source: everything else in the table above still ran. The "
                  "traceback is the fix:", ""]
        for r in no_import:
            lines += [f"- `{r['source']}` ({r['status']})", "", "```",
                      str(r["traceback"]).strip()[:1500], "```"]

    unverified = [r for r in results if r["status"] == "unverified_failed"]
    if unverified:
        lines += ["", "**Unverified sources that did not answer.** These were "
                  "written against documentation and have never reached their "
                  "live service. The error below IS the coverage finding -- "
                  "copy it into the adapter and re-run:", ""]
        lines += [f"- `{r['source']}` -- {r.get('detail', '')}"
                  for r in unverified]

    if deferred:
        lines += ["", "**Skipped by choice.** These have no key and "
                  "`ingest/sources.yml` says that is intentional. Each wrote a "
                  "gap row, so the store never implies the source was "
                  "consulted:", ""]
        lines += [f"- `{r['source']}` -- {r.get('detail', '')}" for r in deferred]

    if failures:
        lines += ["", "**Failures.** A source that was configured and did not "
                  "deliver:", ""]
        lines += [f"- `{r['source']}` ({r['status']}) -- {r.get('detail', '')}"
                  for r in failures]

    if seal is not None:
        state = "intact" if seal.get("intact") else f"BROKEN at {seal.get('broken_at')}"
        lines += ["", f"Ledger seal: {state} over {seal.get('sealed_rows', 0)} "
                  "sealed rows."]
    if db_path:
        lines += ["", f"Store: `{db_path}` (uploaded as an artifact, never "
                  "committed)."]
    return "\n".join(lines) + "\n"


def decide_exit(results) -> tuple:
    """(exit_code, reason). Three outcomes, three different meanings.

    * a configured source failed        -> 1
    * zero sources ingested any rows    -> 1
    * anything else                     -> 0, including a run where a deferred
                                           source was skipped
    """
    failures = [r for r in results if STATUS[r["status"]]["failure"]]
    if failures:
        return 1, ("configured sources did not deliver: "
                   + ", ".join(f"{r['source']}({r['status']})" for r in failures))
    if not any(STATUS[r["status"]]["ingested"] for r in results):
        return 1, ("zero sources ingested any rows. Every source was skipped, "
                   "empty, or absent -- a day with no data is a failure even "
                   "when nothing errored")
    return 0, "ok"


def main(argv=None):
    parser = argparse.ArgumentParser(description="daily ingest run")
    parser.add_argument("--db", default=None)
    parser.add_argument("--sources", default="all")
    parser.add_argument("--targets", default=None,
                        help="JSON file of per-source fetch arguments")
    parser.add_argument("--summary", default=None,
                        help="write a Markdown summary here (GITHUB_STEP_SUMMARY)")
    parser.add_argument("--results", default=None,
                        help="write the raw results JSON here")
    parser.add_argument("--preflight", action="store_true",
                        help="report key presence and exit 0. Never aborts: "
                             "which absences matter is the runner's decision, "
                             "not this step's")
    args = parser.parse_args(argv)

    if args.preflight:
        report = render_preflight()
        print(report, end="")
        if args.summary:
            with open(args.summary, "a", encoding="utf-8") as handle:
                handle.write("### Preflight\n\n```\n" + report + "```\n\n")
        return 0

    targets = {}
    if args.targets and os.path.exists(args.targets):
        with open(args.targets, encoding="utf-8") as handle:
            targets = json.load(handle)

    expectations = load_expectations()
    # ALL_SOURCE_NAMES, not ADAPTERS: a source whose module failed to import is
    # absent from ADAPTERS, and iterating that would make it vanish from the
    # run entirely -- no row, no gap, no line in the summary. Disappearing
    # quietly is the one outcome this runner exists to prevent.
    names = (list(ALL_SOURCE_NAMES) if args.sources == "all"
             else args.sources.split(","))

    # The store is opened BEFORE anything can go wrong with a source, so the
    # database file exists even on a run where every source is skipped. An
    # artifact upload that finds nothing is a second failure hiding the first.
    store = Store(args.db) if args.db else Store()

    results = []
    for name in names:
        if name in BROKEN_ADAPTERS:
            results.append(broken_source(store, name, BROKEN_ADAPTERS[name],
                                         expectations.get(name)))
            continue
        adapter_cls = ADAPTERS.get(name)
        if adapter_cls is None:
            print(f"unknown source {name}", file=sys.stderr)
            return 2
        # Constructing an adapter can fail too -- a class attribute evaluated
        # at first instantiation, a bad default. Same containment.
        try:
            adapter = adapter_cls()
        except Exception as exc:                            # noqa: BLE001
            import traceback as _tb
            results.append(broken_source(
                store, name,
                {"module": adapter_cls.__module__,
                 "error": f"{type(exc).__name__}: {exc}",
                 "traceback": _tb.format_exc()},
                expectations.get(name)))
            continue
        results.append(run_source(store, name, adapter,
                                  targets.get(name, {}),
                                  expectations.get(name)))

    seal = store.verify_seal()
    print(json.dumps({"results": results, "seal": seal}, indent=2))

    if args.results:
        with open(args.results, "w", encoding="utf-8") as handle:
            json.dump({"results": results, "seal": seal}, handle, indent=2)

    code, reason = decide_exit(results)
    if not seal["intact"]:
        code, reason = 1, f"ledger seal broken at {seal['broken_at']}"

    summary = render_summary(results, seal, args.db)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(summary)
    print(summary)

    if code:
        print(f"\nEXIT 1: {reason}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
