"""Mutation harness. A guard nothing catches is decoration.

WHY THIS LIVES IN THE REPOSITORY. It used to be a scratch file, and a scratch
file cannot be reviewed, cannot be re-run by anyone else, and cannot be
regression-tested. It compared each mutant's result against a HARDCODED
`failures=6` while the real baseline had moved to `failures=6, skipped=6` --
so the substring never matched, every mutant looked different from it, and
fourteen results came back CAUGHT that were nothing of the kind. The claim
"all mutations caught" had been load-bearing for weeks at that point.

Two rules follow from that, and both are enforced here rather than remembered:

  1. The baseline is MEASURED, once, at the start of the run. Never assumed,
     never hardcoded, never inferred from a previous session.
  2. The source file is restored in a `finally`. A harness that times out
     mid-mutation leaves a sabotaged repository behind, and the next test run
     reports the sabotage as a regression in the code under test. That has
     happened once already.

    python -m audit.mutate                 # every catalogued mutant
    python -m audit.mutate --only cache    # substring filter on the label
    python -m audit.mutate --list

Stale bytecode can only ever produce a FALSE MISSED -- the mutated source is
ignored and the tests pass -- so `__pycache__` is cleared between mutations.
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from audit.mutants import MUTANTS                              # noqa: E402


LOCK = ROOT / ".mutate.lock"


class AlreadyRunning(RuntimeError):
    """Another mutation run holds the working tree.

    This harness EDITS SOURCE FILES IN PLACE. A second run -- or an ordinary
    test run started while one is going -- reads a sabotaged tree and reports
    the sabotage as a regression. That is not hypothetical: it produced two
    phantom errors the first time these overlapped.
    """


SEAL = ROOT / "audit" / "mutant_seal.json"


def check_seal(discovered) -> bool:
    """Is the catalogue the size it is sealed at?

    The ledger seal exists because a store you cannot verify is a store you
    are trusting. Same argument, pointed at the auditor: "all mutations
    caught" over a catalogue that silently halved is a sentence with no
    content, and it looks identical to the real thing.
    """
    import json
    try:
        expected = json.loads(SEAL.read_text())["expected_mutants"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"SEAL UNREADABLE: {SEAL} ({exc}). A missing seal is a failure, "
              "not a pass -- it is exactly what a deleted catalogue looks "
              "like.")
        return False
    if discovered != expected:
        print(f"SEAL BROKEN: {discovered} mutants discovered, {expected} "
              f"expected. If mutants were added, raise `expected_mutants` in "
              f"{SEAL.name} IN THE SAME COMMIT -- a seal updated afterwards to "
              "match a broken run is not a seal. If they vanished, find out "
              "why before trusting any result below.")
        return False
    print(f"seal intact: {discovered} mutants")
    return True


def clear_bytecode():
    for cached in ROOT.rglob("__pycache__"):
        shutil.rmtree(cached, ignore_errors=True)


def run_suite() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
        cwd=ROOT, capture_output=True, text=True)
    lines = result.stderr.strip().splitlines()
    return lines[-1] if lines else "(no output)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="audit.mutate")
    parser.add_argument("--only", default=None,
                        help="run only mutants whose label contains this")
    parser.add_argument("--list", action="store_true",
                        help="print the catalogue and stop")
    parser.add_argument("--check-seal", action="store_true",
                        help="assert the catalogue is the size the seal says "
                             "and stop. Exit 1 on a mismatch")
    args = parser.parse_args(argv)

    if args.check_seal:
        return 0 if check_seal(len(MUTANTS)) else 1

    wanted = [m for m in MUTANTS
              if not args.only or args.only.lower() in m[0].lower()]
    # THE SEAL IS CHECKED ON EVERY RUN, FILTERED OR NOT. It used to be
    # `if not args.only`, and that exemption is the same defect as the
    # per-mutant anchor check: a SUBSET check cannot see a problem in the part
    # it did not select. A catalogue that silently halved reads as a clean
    # `--only` run, and `--only` is how this harness is actually used.
    #
    # A FULL RUN THAT IS QUIETLY SHORT IS THE FAILURE THIS GUARDS. Every
    # mutant reported CAUGHT and half the catalogue never loaded reads
    # exactly like a clean run.
    if not check_seal(len(MUTANTS)):
        return 1
    if args.list:
        for label, path, _old, _new in wanted:
            print(f"  {label}   [{path}]")
        print(f"\n{len(wanted)} mutant(s)")
        return 0

    if LOCK.exists():
        raise AlreadyRunning(
            f"{LOCK} exists. This harness edits source files in place, so a "
            "concurrent run -- or a plain test run started alongside one -- "
            "reads a sabotaged tree and reports the sabotage as a regression. "
            "Wait for it, or delete the lock if you are certain nothing is "
            "running.")
    LOCK.write_text("held by audit.mutate\n")
    # SIGTERM DOES NOT UNWIND. Without this the `finally` in `_run` never
    # runs when the harness is killed -- by a CI timeout, by a shell that
    # gave up waiting -- and the mutation is left in the working tree. Turn
    # the signal into an exception so the existing restore path executes.
    def _restore_and_die(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")
    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), _restore_and_die)
            except ValueError:                            # not the main thread
                pass
    try:
        return _run(wanted)
    finally:
        LOCK.unlink(missing_ok=True)
        clear_bytecode()


def verify_tree(mutants) -> list:
    """Every mutant's ORIGINAL text, present in its file, before anything runs.

    THE BASELINE IS ONLY HONEST OVER A CLEAN TREE. This harness edits source
    in place and restores in a `finally` -- which does not run on SIGTERM. A
    killed run therefore leaves one mutation applied, and the NEXT run
    measures a baseline that already contains it. Every subsequent mutant is
    then compared against a poisoned number: some read CAUGHT for the wrong
    reason and some read MISSED for no reason at all.

    That is not hypothetical. A run killed on 2026-08-27 left
    `interval_properties.battery`'s `check()` as a `pass`, and the next two
    runs measured `failures=11` instead of `failures=6` and reported two
    false MISSED results.

    `--only` made it worse rather than better: the per-mutant anchor check in
    `_run` would have caught it, but only for a mutant in the selected subset.
    So this checks ALL of them, always, regardless of the filter, and refuses
    to measure anything until the tree is what the catalogue says it is.
    """
    return [(label, relative) for label, relative, old, _new in mutants
            if old not in (ROOT / relative).read_text()]


def _run(wanted) -> int:
    # ALL of them, never `wanted`. The subset check is what let two false
    # MISSED results through on 2026-08-27: `--only "apitcg:"` does not touch
    # `interval_properties.py`, so it never noticed the mutation sitting there
    # from a killed run.
    dirty = verify_tree(MUTANTS)
    print(f"tree verified: {len(MUTANTS)} anchors present, "
          f"{len(wanted)} selected to run")
    if dirty:
        print("TREE NOT CLEAN -- refusing to measure a baseline. Every mutant "
              "below would be compared against a number that already contains "
              "somebody else's mutation.\n")
        for label, relative in dirty:
            print(f"  MISSING ANCHOR  {label}  [{relative}]")
        print("\nEither the code moved and the catalogue is stale, or a "
              "previous run was killed before its `finally` restored the "
              "file. `git diff` says which.")
        return 1

    clear_bytecode()
    baseline = run_suite()
    print(f"baseline (MEASURED, not assumed): {baseline}\n", flush=True)

    missed, errored = [], []
    for label, relative, old, new in wanted:
        path = ROOT / relative
        source = path.read_text()
        if old not in source:
            # An anchor that no longer matches is NOT a pass. The code moved
            # and the mutant now tests nothing, which is exactly the silence
            # this harness exists to break.
            errored.append(label)
            print(f"  ANCHOR  {label}: not found in {relative}", flush=True)
            continue
        try:
            path.write_text(source.replace(old, new, 1))
            clear_bytecode()
            outcome = run_suite()
        finally:
            path.write_text(source)
        caught = outcome != baseline
        if not caught:
            missed.append(label)
        print(f"  {'CAUGHT ' if caught else 'MISSED '} {label}  [{outcome}]",
              flush=True)

    print(f"\n{len(wanted) - len(missed) - len(errored)} caught, "
          f"{len(missed)} missed, {len(errored)} anchor(s) stale")
    for label in missed:
        print(f"  MISSED {label}")
    for label in errored:
        print(f"  STALE  {label}")
    return 1 if (missed or errored) else 0


if __name__ == "__main__":
    sys.exit(main())
