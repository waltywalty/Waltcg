#!/usr/bin/env python3
"""Offline regression harness for the coverage probe.

Why this exists
---------------
Every logic bug this probe has shipped -- absence inferred from a 200 that
wrapped an error object, a paginated game list read as if complete, discovery
retried across 21 cards, a cross-provider key fallback -- was visible in the
response payloads. None of them needed a live request to find. They were found
instead by spending a day of provider quota each.

replay.py runs the complete pipeline against saved payloads with zero network
access: same parsing, same body classification, same scoring, same verdicts,
same report generation. It asserts an expected outcome per fixture, so an
instrument regression fails in CI in about a second instead of costing a day.

Usage
-----
  python -m probe.replay                 # every fixture in probe/fixtures/
  python -m probe.replay --fixture 429-mid-run
  python -m probe.replay --from-out      # replay real payloads in probe/out/
  python -m probe.replay -v              # show per-assertion detail
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from probe import coverage as cov  # noqa: E402

FIXTURE_DIR = os.path.join(HERE, "fixtures")


class Failure(Exception):
    pass


def _args(scenario):
    """Stand-in for the argparse namespace the Prober expects."""
    return types.SimpleNamespace(
        offline=False, use_cache=False, replay=True, smoke=True,
        budget=int(scenario.get("budget", 90)), timeout=5,
        report=os.devnull,
    )


def run_scenario(scenario, verbose=False):
    """Drive the real pipeline against one fixture. Returns a check list."""
    prober = cov.Prober(_args(scenario), scenario=scenario)
    cards = cov.select_cards(smoke=scenario.get("cards", "smoke") == "smoke")
    results, rows = cov.run_pipeline(prober, cards, quiet=not verbose)

    # Report generation is part of what we are protecting: a crash or a price
    # leak in the writer is an instrument regression too.
    report = cov.build_report(rows, prober, ran_live=True)
    cov.scrub_report(report, prober.safe_tokens)

    exp = scenario.get("expect", {})
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    verdicts = {r["combo"]: r["verdict"] for r in rows}
    total_confirmed = sum(r["catalog_absent_confirmed"] for r in rows)
    seen_classes = {a.get("body") for a in prober.attempts}

    if "confirmed_absences" in exp:
        want = exp["confirmed_absences"]
        check(f"confirmed absences == {want}", total_confirmed == want,
              f"got {total_confirmed}")

    if "games_complete" in exp:
        got = bool((prober.games or {}).get("complete"))
        check(f"games list complete is {exp['games_complete']}",
              got == exp["games_complete"], f"got {got}")

    if "games_count" in exp:
        got = len((prober.games or {}).get("games") or [])
        check(f"games discovered == {exp['games_count']}", got == exp["games_count"],
              f"got {got}")

    for key, want_id in (exp.get("game_mapped") or {}).items():
        game, lang = key.split(":")
        got = prober.tcgapi_game_slug.get((game, lang))
        check(f"{key} maps to game id {want_id}", str(got) == str(want_id), f"got {got!r}")

    for prov, cap in (exp.get("provider_requests_max") or {}).items():
        got = prober.providers[prov].requests
        check(f"{prov} made <= {cap} requests", got <= cap, f"got {got}")

    for prov in (exp.get("provider_rate_limited") or []):
        check(f"{prov} parked after 429", prober.providers[prov].rate_limited)

    for prov in (exp.get("provider_key_absent") or []):
        p = prober.providers[prov]
        check(f"{prov} reports key absent", not p.key and cov.KEY_ABSENT in p.status_note(),
              p.status_note())

    for cls in (exp.get("body_classes_seen") or []):
        check(f"body class {cls!r} observed", cls in seen_classes,
              f"saw {sorted(c for c in seen_classes if c)}")

    for combo, want in (exp.get("verdict_contains") or {}).items():
        got = verdicts.get(combo)
        check(f"{combo} verdict is {want}", got == want, f"got {got!r}")

    if "verdict_all" in exp:
        want = exp["verdict_all"]
        bad = {c: v for c, v in verdicts.items() if v != want}
        check(f"every combo verdict is {want}", not bad, f"exceptions {bad}")

    for banned in (exp.get("verdict_not") or {}).get("any", []):
        bad = [c for c, v in verdicts.items() if v == banned]
        check(f"no combo reports {banned}", not bad, f"got {bad}")

    if exp.get("discovery_aborted"):
        aborted = any(p.discovery_failed for p in prober.providers.values())
        check("discovery aborted for at least one provider", aborted)

    # Universal invariants -- true of every scenario, asserted for all of them.
    check("no network transport installed", isinstance(prober.transport, cov.ReplayTransport))
    unmatched = [e["url"] for e in prober.transport.log if e["rule"] is None]
    check("every request matched a fixture rule", not unmatched,
          f"unmatched: {unmatched[:3]}")
    bad_absence = [
        r["combo"] for r in rows
        if r["catalog_absent_confirmed"] and not any(
            cov.confirmed_empty(c["tcgapi_catalog"]) or cov.confirmed_empty(c["apitcg_catalog"])
            for c in r["cards"])]
    check("no absence claimed without a validated empty envelope", not bad_absence,
          f"offenders: {bad_absence}")

    return checks, verdicts, prober


def replay_from_out(verbose=False):
    """Re-run the pipeline over real payloads captured in probe/out/."""
    raw = os.path.join(cov.OUT_DIR, "raw")
    if not os.path.isdir(raw):
        print(f"no captured payloads in {raw} -- run the probe locally first, or rely on "
              "the fixtures (probe/out/ is gitignored, so CI never has these)")
        return 0
    rules, n = [], 0
    for path in sorted(glob.glob(os.path.join(raw, "*", "*.json"))):
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("json") is None:
            continue
        url = rec.get("url", "")
        # Exact-URL rule so replay reproduces the captured run faithfully.
        rules.append({"match": _escape(url), "status": rec.get("status", 200),
                      "body": rec["json"]})
        n += 1
    if not rules:
        print("captured payloads present but none had JSON bodies")
        return 0
    scenario = {"name": "captured-payloads", "cards": "full", "rules": rules,
                "keys": {"TCGAPI_KEY": "captured", "APITCG_KEY": "captured",
                         "PPT_KEY": "captured"},
                "expect": {}}
    checks, verdicts, prober = run_scenario(scenario, verbose)
    print(f"replayed {n} captured responses")
    for combo, v in verdicts.items():
        print(f"  {combo:<24} {v}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def _escape(url):
    import re as _re
    return "^" + _re.escape(url) + "$"


def contract_checks():
    """Unit-level assertions on the absence rule itself.

    The fixtures exercise absence through the whole pipeline, but some illegal
    states are hard to reach from a payload. These pin the contract directly,
    so loosening score_card() fails here even if no fixture happens to route
    through the affected branch.
    """
    def rec(body_class, found=False, status=200):
        return {"found": found, "http": {"status": status, "note": "",
                                         "body_class": body_class}}

    def build(a_cls, b_cls, a_found=None, b_found=None):
        # A BODY_OK response by definition carried a record, so "ok but found
        # nothing" is not a reachable state and must not be asserted over.
        a_found = (a_cls == cov.BODY_OK) if a_found is None else a_found
        b_found = (b_cls == cov.BODY_OK) if b_found is None else b_found
        return {
            "tcgapi_catalog": rec(a_cls, a_found),
            "apitcg_catalog": rec(b_cls, b_found),
            "price": {"raw_price": None, "conditions": {},
                      "http": {"status": 0, "note": "no card id resolved",
                               "body_class": cov.BODY_NONE}},
            "graded": {"grades": {}, "http": {"status": 200, "note": "",
                                              "body_class": a_cls}},
            "pop": {"populationByGrader": None, "totalPopulation": None,
                    "combinedGemRate": None,
                    "http": {"status": 200, "note": "", "body_class": a_cls}},
        }

    cases = [
        ("both sources validated-empty -> absence confirmed",
         build(cov.BODY_EMPTY, cov.BODY_EMPTY), cov.NONE, True),
        ("one empty, one error body -> NOT confirmed",
         build(cov.BODY_EMPTY, cov.BODY_ERROR), cov.UNTESTED, False),
        ("one empty, one unrecognised shape -> NOT confirmed",
         build(cov.BODY_EMPTY, cov.BODY_UNKNOWN), cov.UNTESTED, False),
        ("one empty, one no-response -> NOT confirmed",
         build(cov.BODY_EMPTY, cov.BODY_NONE), cov.UNTESTED, False),
        ("both error bodies -> NOT confirmed",
         build(cov.BODY_ERROR, cov.BODY_ERROR), cov.UNTESTED, False),
        ("found in one source -> not an absence at all",
         build(cov.BODY_OK, cov.BODY_ERROR, a_found=True), None, False),
    ]
    out = []
    for label, res, want_catalog, want_confirmed in cases:
        st = cov.score_card(res)
        ok = (st["catalog_absent_confirmed"] is bool(want_confirmed))
        if want_catalog is not None:
            ok = ok and st["catalog"] == want_catalog
        out.append((f"contract: {label}", ok,
                    f"catalog={st['catalog']} confirmed={st['catalog_absent_confirmed']}"))

    # Exhaustive over every pair of body classes: absence -- whether expressed
    # as catalog NONE or as a confirmed flag -- must require a validated empty
    # envelope from EVERY source. This is the invariant the project kept
    # violating, so it is asserted directly rather than only through fixtures.
    classes = [cov.BODY_OK, cov.BODY_EMPTY, cov.BODY_ERROR, cov.BODY_UNKNOWN, cov.BODY_NONE]
    violations = []
    for ca in classes:
        for cb in classes:
            st = cov.score_card(build(ca, cb))
            both_empty = (ca == cov.BODY_EMPTY and cb == cov.BODY_EMPTY)
            if st["catalog"] == cov.NONE and not both_empty:
                violations.append(f"catalog=NONE from ({ca},{cb})")
            if st["catalog_absent_confirmed"] and not both_empty:
                violations.append(f"confirmed from ({ca},{cb})")
    out.append(("contract: absence requires a validated empty envelope from every source "
                f"({len(classes) ** 2} combinations)", not violations, "; ".join(violations[:3])))
    return out


def main():
    ap = argparse.ArgumentParser(description="offline replay harness for the coverage probe")
    ap.add_argument("--fixture", help="run one fixture by name (without .json)")
    ap.add_argument("--from-out", action="store_true",
                    help="replay real captured payloads in probe/out/ instead of fixtures")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.from_out:
        return replay_from_out(args.verbose)

    paths = sorted(glob.glob(os.path.join(FIXTURE_DIR, "*.json")))
    if args.fixture:
        paths = [p for p in paths if os.path.basename(p)[:-5] == args.fixture]
        if not paths:
            print(f"no fixture named {args.fixture!r} in {FIXTURE_DIR}", file=sys.stderr)
            return 2
    if not paths:
        print(f"no fixtures found in {FIXTURE_DIR}", file=sys.stderr)
        return 2

    failed = 0
    contract = contract_checks()
    bad_contract = [(n, d) for n, ok, d in contract if not ok]
    if bad_contract:
        failed += 1
        print("  FAIL  absence contract")
        for n, d in bad_contract:
            print(f"          x {n}  --  {d}")
    else:
        print(f"  ok    absence contract  ({len(contract)} checks)")

    print(f"\nreplaying {len(paths)} fixture(s) with zero network access\n")
    for path in paths:
        with open(path, encoding="utf-8") as f:
            scenario = json.load(f)
        name = scenario.get("name", os.path.basename(path))
        try:
            checks, verdicts, _ = run_scenario(scenario, args.verbose)
        except Exception as e:                        # noqa: BLE001 - report, don't crash
            print(f"  FAIL  {name}\n          raised {e.__class__.__name__}: {e}")
            failed += 1
            continue
        bad = [(n, d) for n, ok, d in checks if not ok]
        if bad:
            failed += 1
            print(f"  FAIL  {name}")
            for n, d in bad:
                print(f"          x {n}" + (f"  --  {d}" if d else ""))
        else:
            print(f"  ok    {name}  ({len(checks)} checks)")
        if args.verbose:
            for n, ok, d in checks:
                print(f"          {'+' if ok else 'x'} {n}" + (f"  --  {d}" if d else ""))
            print(f"          verdicts: {verdicts}")

    print()
    if failed:
        print(f"{failed} of {len(paths)} fixtures FAILED -- instrument regression")
        return 1
    print(f"all {len(paths)} fixtures passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
