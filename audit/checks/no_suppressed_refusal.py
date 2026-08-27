#!/usr/bin/env python3
"""Hard gate: a refusal may not be caught and turned into a verdict.

THE THIRD SPECIES. `audit/defect_taxonomy.py` classified checks that read
green without being green as INERT (cannot fire) or ORPHANED (fires, nothing
calls it). This is neither, and both of their remedies pass it cleanly:

    SUPPRESSED  the check fires, something calls it, and its REFUSAL is
                caught and converted into a verdict.
                REMEDY: prove the refusal PROPAGATES, not that it fires.

The specimen is `catalog_precision._numbers_agree`:

    try:
        return numbers_denote_same_printing(a, b, set_total=total) is True
    except CannotBridge:
        return str(a) == str(b)

`CannotBridge` exists to stop a caller mistaking "we could not tell" for "they
are different cards" -- its own docstring says so. Four lines later the
handler does exactly that. A test that the bridge refuses passes. A test that
`_numbers_agree` is called passes. The refusal died between them.

WHAT COUNTS AS A REFUSAL TYPE -- DISCOVERED, NOT LISTED. Every exception class
defined in this repository. Over-approximating on purpose: a missed type is a
missed suppression, which is a silent pass, and a spurious one costs a
contract line. A hand-maintained list of `CannotBridge, NumberRequired,
UnsupportedGame` would go stale the first time somebody adds a fourth, which
is the ADR-0045 defect one level up.

WHEN A BARE `except Exception` IS IN SCOPE. Only when the `try` body calls
something that can refuse -- "a bare except around a call that can refuse is
the signature". `can refuse` is itself discovered: a function that raises a
refusal type, transitively closed over the call graph by name. The closure
OVER-approximates (name-matched, not resolved), because a missing edge means a
handler silently out of scope.

WHEN A HANDLER IS ACCEPTABLE. Four ways, and only four:

  1. It re-raises. The refusal propagates by definition.
  2. It increments a counter (`AugAssign`). A refusal that is counted is a
     refusal that survives into a report, which is the whole shape of
     `_number_bridge`'s `no_set_total` and `unreadable` buckets.
  3. Every value it produces is NOTHING KNOWN -- `None`, `{}`, `[]`, `()`,
     `""`, or a module-level name bound once to one of those (`CANNOT_TELL =
     None`). Note what is NOT on that list: `False` and `0`. `return False` on
     a `CannotBridge` is the specimen, and calling it "empty" is the mistake.
  4. It BINDS the exception (`as exc`) and uses that name. The refusal is
     carried somewhere rather than discarded -- `errors[language] =
     str(exc)[:200]`, `return Refusal(MODEL, "route freight unusable",
     str(e))`, `limited = isinstance(exc, RateLimited)`.

Rule 4 is the discriminating one in practice, and it is worth being blunt
about why: **the specimen does not bind the exception at all.** Neither does
the second finding. A handler that throws the exception object away and
returns a value computed from the original inputs has, structurally, decided
something it was told could not be decided.

WHAT THIS CANNOT SEE:

  * A handler that produces nothing at all -- `except CannotBridge: pass` --
    is reported as SILENT, not as a suppression. Whether a pre-set variable
    downstream amounts to a verdict is a dataflow question this does not ask.
  * A verdict produced by a helper CALLED in the handler, where the helper
    discards the exception. The value references no exception name, so it is
    caught only if the helper is itself in the tree and flagged.
  * `log(exc); return False` -- the exception is bound and used, so rule 4
    clears it, and the verdict still reaches the caller. This is the known
    hole. Tightening it to "the RETURNED value must carry the exception"
    was tried and produces false positives on the common and correct
    `detail = str(exc); return {"detail": detail}` idiom, so the check is
    deliberately the weaker of the two rather than one with an exemption
    roster that grows.
  * Suppression at a distance: a refusal converted two frames up by a caller
    that returns a default. That is the orphaned/inert boundary, not this.
  * Exception types imported from outside the repository. `requests`
    exceptions are not refusals in our vocabulary and are not scanned.

Usage:  python -m audit.checks.no_suppressed_refusal [--verbose]
Exit 0 clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

#: A class is an exception class if it inherits from something whose name ends
#: this way, or from another class already known to be one.
_EXC_BASE = re.compile(r"(Error|Exception)$")

#: Catch-alls. In scope only when the `try` body can refuse.
CATCH_ALL = {"Exception", "BaseException"}

#: What a handler may produce and still be saying "nothing is known".
#: `0` and `False` are NOT here: they are verdicts, and `return False` on a
#: `CannotBridge` is the specimen.
def _is_nothing_known(node, sentinels=()):
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return node.value is None or node.value == ""
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, ast.Name) and node.id in sentinels:
        # A NAMED sentinel. `CANNOT_TELL = None` at module level is better
        # code than a bare `return None` -- it says what the None means -- and
        # a check that forced the bare literal would be punishing the clearer
        # of the two. Only module-level names bound once to a nothing-known
        # literal qualify; see `module_sentinels`.
        return True
    return False


def module_sentinels(tree):
    """Module-level names bound EXACTLY ONCE to a nothing-known literal.

    Assigned more than once anywhere in the file, it is a variable and not a
    sentinel, and this refuses to read it as one.
    """
    assigned = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned[target.id] = assigned.get(target.id, 0) + 1
    sentinels = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Name) and assigned.get(target.id) == 1
                    and _is_nothing_known(node.value)):
                sentinels.add(target.id)
    return sentinels


_MARKER = re.compile(
    r"#\s*SUPPRESSION-EXEMPT\((?P<claim>[a-z-]+)\)\s*:\s*(?P<why>.+)")

#: THE ROSTER SEAL. Same instrument as `audit/mutant_seal.json`, pointed at
#: the exemptions. Zero: every handler in the tree either propagates its
#: refusal or has no refusal to propagate.
EXPECTED_EXEMPTIONS = 0


def tracked_files(root=REPO):
    """Every .py in the working tree, TRACKED OR NOT. A new suppression is
    untracked at the moment it is written."""
    listed = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                            capture_output=True, text=True)
    if listed.returncode != 0:
        raise SystemExit(f"git ls-files failed: {listed.stderr}")
    paths = {f for f in listed.stdout.splitlines() if f.strip()}
    other = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "*.py"],
        cwd=root, capture_output=True, text=True)
    if other.returncode == 0:
        paths |= {f for f in other.stdout.splitlines() if f.strip()}
    return sorted(paths)


def _called_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def refusal_types(trees):
    """Every exception class DEFINED in this repository.

    Two passes, because `CannotBridge(IdentityError)` only reads as an
    exception once `IdentityError` does.
    """
    found = set()
    for _rel, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = _called_name(base) or ""
                    if _EXC_BASE.search(name):
                        found.add(node.name)
    for _ in range(4):
        grew = False
        for _rel, tree in trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name not in found:
                    for base in node.bases:
                        if (_called_name(base) or "") in found:
                            found.add(node.name)
                            grew = True
        if not grew:
            break
    return found


def refusing_functions(trees, types):
    """Function names that can raise a refusal, transitively.

    By NAME, not by resolved symbol. Over-approximating is the safe direction
    here: a missing edge puts a bare `except Exception` out of scope, which is
    a silent pass.
    """
    raises, calls = {}, {}
    for _rel, tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            direct, called = False, set()
            for inner in ast.walk(node):
                if isinstance(inner, ast.Raise) and inner.exc is not None:
                    target = inner.exc
                    if isinstance(target, ast.Call):
                        target = target.func
                    if (_called_name(target) or "") in types:
                        direct = True
                if isinstance(inner, ast.Call):
                    name = _called_name(inner.func)
                    if name:
                        called.add(name)
            raises[node.name] = raises.get(node.name, False) or direct
            calls.setdefault(node.name, set()).update(called)

    can = {n for n, yes in raises.items() if yes}
    for _ in range(12):
        grew = {n for n, targets in calls.items()
                if n not in can and (targets & can)}
        if not grew:
            break
        can |= grew
    return can


def _try_can_refuse(node, refusers, types):
    """Does this `try` body call something that can refuse?"""
    for inner in ast.walk(ast.Module(body=list(node.body), type_ignores=[])):
        if isinstance(inner, ast.Call):
            name = _called_name(inner.func)
            if name and (name in refusers or name in types):
                return True
    return False


def _handler_types(handler):
    names = []

    def collect(node):
        if isinstance(node, ast.Name):
            names.append(node.id)
        elif isinstance(node, ast.Attribute):
            names.append(node.attr)
        elif isinstance(node, ast.Tuple):
            for element in node.elts:
                collect(element)
    if handler.type is not None:
        collect(handler.type)
    return names


def classify(handler, sentinels=()):
    """`ok`, `silent`, or `suppressed`, with the produced value that decided it.

    The four acceptances are in the module docstring. In code they are: a
    `Raise` anywhere, an `AugAssign` anywhere, every produced value being
    nothing-known, or the exception being bound AND that name used.
    """
    body = ast.Module(body=list(handler.body), type_ignores=[])
    bound = handler.name
    produced = []
    for node in ast.walk(body):
        if isinstance(node, ast.Raise):
            return "ok", None
        if isinstance(node, ast.AugAssign):
            # A counted refusal survives into a report.
            return "ok", None
        if isinstance(node, ast.Return):
            produced.append(node.value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            produced.append(node.value)
    if not produced:
        return "silent", None
    if all(_is_nothing_known(value, sentinels) for value in produced):
        return "ok", None
    if bound and any(_mentions(node, bound) for node in handler.body):
        # THE EXCEPTION WAS CARRIED SOMEWHERE. Not proof it reaches the
        # caller -- see the known hole in the docstring -- but proof it was
        # not thrown away, which is what separates every correct handler in
        # this tree from the two that are not.
        return "ok", None
    for value in produced:
        if not _is_nothing_known(value, sentinels):
            return "suppressed", value
    return "ok", None


def _mentions(node, name):
    if node is None:
        return False
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id == name:
            return True
    return False


def scan(root=REPO):
    """Returns (violations, report). Empty violations is a pass."""
    trees, sources = [], {}
    for rel in tracked_files(root):
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as handle:
                text = handle.read()
            trees.append((rel, ast.parse(text)))
            sources[rel] = text.splitlines()
        except (SyntaxError, UnicodeDecodeError):
            continue

    types = refusal_types(trees)
    refusers = refusing_functions(trees, types)

    violations, report, exemptions = [], [], []
    for rel, tree in trees:
        sentinels = module_sentinels(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body_refuses = _try_can_refuse(node, refusers, types)
            for handler in node.handlers:
                names = _handler_types(handler)
                named_refusal = any(n in types for n in names)
                catch_all = not names or set(names) <= CATCH_ALL
                if not named_refusal and not (catch_all and body_refuses):
                    continue
                verdict, value = classify(handler, sentinels)
                caught = "/".join(names) or "<bare>"
                where = f"{rel}:{handler.lineno}"
                if _exempt(sources[rel], handler.lineno):
                    exemptions.append(where)
                    continue
                report.append((where, caught, verdict))
                if verdict != "suppressed":
                    continue
                shown = ast.unparse(value) if value is not None else "?"
                violations.append(
                    f"SUPPRESSED {where}: `except {caught}` produces "
                    f"`{shown}` -- a verdict computed without the exception. "
                    f"A refusal means CANNOT TELL; this hands the caller a "
                    f"decision. Re-raise it, count it, or return a value that "
                    f"carries it.")

    if len(exemptions) != EXPECTED_EXEMPTIONS:
        violations.append(
            f"exemption roster: {len(exemptions)} marker(s) present, seal "
            f"says {EXPECTED_EXEMPTIONS}. An allowlist that can grow quietly "
            f"is the defect this check is about.")
    return violations, {"types": sorted(types), "refusers": len(refusers),
                        "handlers": report, "exemptions": exemptions}


def _exempt(lines, lineno):
    offset = lineno - 2
    while 0 <= offset < len(lines):
        text = lines[offset].strip()
        if not text.startswith("#"):
            return False
        if _MARKER.search(lines[offset]):
            return True
        offset -= 1
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    violations, report = scan()
    counts = {}
    for _where, _caught, verdict in report["handlers"]:
        counts[verdict] = counts.get(verdict, 0) + 1
    print(f"refusal types: {len(report['types'])}  "
          f"functions that can refuse: {report['refusers']}  "
          f"handlers in scope: {len(report['handlers'])} "
          f"({', '.join(f'{v} {k}' for k, v in sorted(counts.items())) or 'none'})")
    if args.verbose:
        print("  types: " + ", ".join(report["types"]))
        for where, caught, verdict in report["handlers"]:
            mark = "ok  " if verdict == "ok" else verdict
            print(f"  [{mark}] {where}  except {caught}")
    for line in violations:
        print(f"VIOLATION: {line}")
    if violations:
        print(f"\n{len(violations)} violation(s).")
        return 1
    print("clean: every refusal in scope propagates, is counted, or re-raises")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
