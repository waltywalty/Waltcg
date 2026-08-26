#!/usr/bin/env python3
"""Hard gate: no path may raise a row to `verified` without reaching the gate.

WHY THIS IS STRUCTURAL AND NOT A LIST. `resolve/corroboration.py` grew a
per-field admission standard over four ADRs -- composites, reader profiles,
checksums, blindness protocols -- fully tested and mutation-covered. And
`upgrade()` never called any of it: `second_source` was a free string, so
`--second-source "looked about right"` promoted a row exactly as readily as a
physical card did. The check fired perfectly, in a module nothing imported at
the moment of decision.

A hand-maintained list of decision points would be the same defect one level
up: it goes stale silently the first time somebody adds a command. So the
decision points are DISCOVERED. A new write path fails this check until it is
wired, whether or not anyone remembered to add it here.

WHAT A SITE IS. Not "writes into the set AND sets a confidence field" -- that
conjunction misses `ingest()`, which produced 238 of the 239 verified rows and
never touches a confidence field. It appends rows it did not construct. So:

    site(F)  <=>  (writes a confidence field  OR  admits an opaque row)
                  AND F is inside the persistence closure

where the persistence closure is every function that transitively calls a
write primitive, PLUS everything those functions transitively call -- because
a mutator whose caller persists is a decision point too, and splitting the
mutation from the save was the first evasion the red team found.

TWO CALL GRAPHS, OPPOSITE CONSERVATISM. This is the load-bearing choice.
Reaching a SINK must OVER-approximate: a missed edge means a missed site,
which is a silent pass. Reaching a GATE must UNDER-approximate: a spurious
edge means a fake guard, which is also a silent pass. Same AST, two edge sets,
deliberately different.

WHAT THIS CHECK CANNOT SEE -- stated here rather than discovered later,
because a check that reads as stronger than it is, is the exact defect this
file exists to catch:

  * It proves an edge to the gate EXISTS, not that the gate refuses. A gate
    called on one exemplar row and then applied to a batch passes here. Mutant
    `elevation: the batch gates one row and elevates the rest` covers that;
    this check does not.
  * `getattr`, `eval`, `exec`, `globals()[...]` are refused rather than
    resolved -- they produce their own violation instead of an edge.
  * A guard behind a condition (`if not args.force: gate(...)`) satisfies
    R-consume. Conditional guarding is not detected.
  * Decorator-based guarding counts only if the decorator is itself a pinned
    gate root.
  * It reads source, not behaviour. A path constructed at runtime by a library
    is invisible.

Usage:  python -m audit.checks.no_unguarded_elevation [--verbose] [--path DIR]
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

# -- the vocabulary --------------------------------------------------------

#: Confidence field names. `resolve/label_cli.py:CONFIDENCE` is the production
#: vocabulary; this is the KEY those values are stored under.
CONF_KEYS = ("confidence",)
#: The LABELLED SET's confidence vocabulary, pinned. This is what scopes the
#: check: `engine/ev/model_e.py` writes `"confidence": "low"` and
#: `store/db.py` writes `confidence=1.0`, on entirely different objects. A
#: constant outside this vocabulary is a different field wearing the same
#: name. A NON-constant value is always in scope -- that is the data-driven
#: case, and excluding it would reintroduce the hole that misses `ingest`.
#: `tests/test_unguarded_elevation.py` asserts this matches
#: `resolve.label_cli.CONFIDENCE`, so a new rung cannot be added there without
#: this noticing.
CONFIDENCE_VALUES = ("verified", "single_source", "in_repo", "unstated")
#: The row collection inside the persisted set.
ROW_COLLECTION_KEYS = ("cards",)
#: What makes a dict a labelled ROW rather than something else keyed `cards`.
#: `ingest/catalog.py` and `probe/coverage.py` both build `{"cards": [...]}`
#: for entirely different structures; requiring the row marker separates them
#: without an exemption. From `resolve/label_cli.py:REQUIRED_FIELDS`.
ROW_MARKER_KEYS = ("card_uid",)

#: Anything that puts bytes on disk. DELIBERATELY PATH-BLIND: the red team
#: defeated every path-based rule in turn -- argparse-supplied paths, f-string
#: joins, pathlib `/`, atomic write-and-rename. Over-approximating the sink is
#: the safe direction, and the second conjunct (a confidence write or an opaque
#: row admission) is what keeps the false-positive rate down.
WRITE_PRIMITIVES = {
    "dump", "dumps_to", "write_text", "write_bytes", "writelines",
    "safe_dump", "replace", "rename", "move", "copyfile", "copy2",
}
WRITE_NAMES = {"open"}

#: The functions a decision point must reach. A pinned GATE list is defensible
#: where a pinned SITE list is not -- removing a gate makes this check
#: STRICTER, which is the safe direction, and R-exists below refuses a stale
#: entry rather than passing everything.
#: Each maps to what it must itself reach, or None if it is a primitive
#: decider. A WRAPPER that stopped consulting the composite would pass
#: everything downstream while still looking like a gate, so the requirement
#: is declared per gate rather than applied to all of them -- `may_read` and
#: `field_is_established` are peers, not callers.
GATE_ROOTS = {
    "resolve.label_cli:second_source_is_admissible":
        "resolve.corroboration:row_is_verifiable",
    "resolve.corroboration:row_is_verifiable":
        "resolve.corroboration:field_is_established",
    "resolve.corroboration:field_is_established": None,
    "resolve.corroboration:may_read": None,
    "resolve.corroboration:physical_card_row_is_well_formed": None,
    "resolve.corroboration:art_call_admits_a_name": None,
}

_MARKER = re.compile(
    r"#\s*ELEVATION-EXEMPT\((?P<claim>[a-z-]+(?::[^)]+)?)\)\s*:\s*(?P<why>.+)")

#: THE ROSTER SEAL. Same instrument as `audit/mutant_seal.json`, pointed at
#: the exemptions: an exemption added without raising this count fails, so the
#: allowlist cannot grow silently. An allowlist that can be appended to
#: quietly is the defect this whole file is about.
EXPECTED_EXEMPTIONS = 1

DYNAMIC = {"getattr", "eval", "exec", "__import__"}


def tracked_files(root):
    """Every .py in the working tree, TRACKED OR NOT.

    `git ls-files` alone was this check's own inert bug, and it is the same
    one `no_provider_data` has: a brand-new module is untracked at the moment
    it is written, so a scan restricted to tracked files reports CLEAN on the
    exact file somebody just added. The audit exists to catch a new write
    path; the new write path is untracked when it is new.

    Verified by adding an unguarded elevation module and watching this report
    clean. `audit/defect_taxonomy.py` calls that species `inert by_scope`: the
    check works, it was never pointed at the thing.
    """
    listed = subprocess.run(["git", "ls-files", "*.py"], cwd=root,
                            capture_output=True, text=True)
    if listed.returncode != 0:
        raise SystemExit(f"git ls-files failed: {listed.stderr}")
    paths = {f for f in listed.stdout.splitlines() if f.strip()}
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "*.py"],
        cwd=root, capture_output=True, text=True)
    if untracked.returncode == 0:
        paths |= {f for f in untracked.stdout.splitlines() if f.strip()}
    return sorted(paths)


def module_name(path):
    return path[:-3].replace("/", ".").replace(os.sep, ".")


class Index:
    """Every function in the repository, by `module:qualname`."""

    def __init__(self, root, paths):
        self.root, self.functions, self.trees = root, {}, {}
        self.by_bare = {}
        for path in paths:
            try:
                with open(os.path.join(root, path), encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
            except (SyntaxError, OSError):
                continue
            self.trees[path] = tree
            self._walk(path, tree, [])

    def _walk(self, path, node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{module_name(path)}:{'.'.join(stack + [child.name])}"
                self.functions[qual] = (path, child)
                self.by_bare.setdefault(child.name, []).append(qual)
                self._walk(path, child, stack + [child.name])
            elif isinstance(child, ast.ClassDef):
                self._walk(path, child, stack + [child.name])
            else:
                self._walk(path, child, stack)


def _imports_in(tree, node):
    """name -> module, from imports at ANY depth.

    This repository lazy-imports inside functions -- `from
    resolve.corroboration import ...` sits inside
    `second_source_is_admissible`. A module-only scan silently deletes the one
    edge that matters.
    """
    bound = {}
    for sub in ast.walk(node):
        if isinstance(sub, ast.ImportFrom) and sub.module:
            for alias in sub.names:
                bound[alias.asname or alias.name] = f"{sub.module}:{alias.name}"
        elif isinstance(sub, ast.Import):
            for alias in sub.names:
                bound[alias.asname or alias.name.split(".")[0]] = alias.name
    return bound


def _call_targets(index, qual, must):
    """Edges out of `qual`. `must` under-approximates; otherwise over."""
    path, node = index.functions[qual]
    module = module_name(path)
    scoped = _imports_in(index.trees[path], index.trees[path])
    scoped.update(_imports_in(index.trees[path], node))
    edges, dynamic = set(), []

    def resolve(name):
        local = f"{module}:{name}"
        if local in index.functions:
            edges.add(local)
            return True
        target = scoped.get(name)
        if target and ":" in target and target.replace(":", ":") in index.functions:
            edges.add(target)
            return True
        if target and ":" in target:
            edges.add(target)
            return True
        return False

    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            while isinstance(func, (ast.Await, ast.Starred)):
                func = func.value
            if isinstance(func, ast.Name):
                if func.id in DYNAMIC:
                    dynamic.append((func.id, getattr(sub, "lineno", 0)))
                elif not resolve(func.id) and not must:
                    # Unresolved bare call: SAME MODULE ONLY. Reaching for
                    # every def in the repository with a matching name made
                    # the persistence closure nearly universal -- `engine/`
                    # and `store/` ended up inside it, and an
                    # over-approximation that swallows everything reports
                    # everything, which is as useless as reporting nothing.
                    if f"{module}:{func.id}" in index.functions:
                        edges.add(f"{module}:{func.id}")
            elif isinstance(func, ast.Attribute):
                base = func.value
                if isinstance(base, ast.Name) and base.id in scoped:
                    edges.add(f"{scoped[base.id]}:{func.attr}")
                if not must and isinstance(base, ast.Name) and base.id in (
                        "self", "cls"):
                    # Unresolved method dispatch stays wide, but only within
                    # this module: a class splitting mutation from persistence
                    # was the third evasion, and it lives in one file.
                    for cand in index.by_bare.get(func.attr, []):
                        if cand.startswith(f"{module}:"):
                            edges.add(cand)
        # Address-taken: `partial(f)`, `{"x": f}`, `map(f, ...)`. Only in the
        # over-approximate graph -- a mentioned callable may be invoked.
        # Address-taken: `partial(f)`, `{"x": f}`, `map(f, ...)`. Same module
        # only, and only in the over-approximate graph -- a callable mentioned
        # by name may be invoked by whatever receives it, which is how the
        # lambda sink table and the curried writer got past the proposal.
        if not must and isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            local = f"{module}:{sub.id}"
            if local in index.functions:
                edges.add(local)
    return {e for e in edges if e in index.functions}, dynamic


def _reaches(start, graph, targets):
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node in targets:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


def _closure(starts, graph):
    seen, stack = set(), list(starts)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return seen


# -- what makes a function a decision point --------------------------------

#: A write's target, classified. INVERSION 1: default-deny. Being unable to
#: tell WHERE a labelled row is going is a finding, not a clearance -- every
#: path-proving rule the red team was handed, it defeated (argparse defaults,
#: f-string joins, pathlib `/`, write-and-rename), and each defeat produced a
#: SILENT PASS on a function containing a literal elevation.
PERSISTED, DERIVED, UNRESOLVED = "persisted", "derived", "unresolved"
_LABELLED_PATH = re.compile(r"labelled_?\w*\.json$")


def _persisted_names(index):
    """Module-level names bound to the persisted set's path, to fixpoint."""
    names = set()
    for path, tree in index.trees.items():
        module = module_name(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            literal = any(
                isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                and _LABELLED_PATH.search(sub.value)
                for sub in ast.walk(node.value))
            if not literal:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
                    names.add(f"{module}:{target.id}")
    return names


def _sink_class(node, persisted):
    """Where does this write go?"""
    mentions, has_literal = set(), False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            mentions.add(sub.id)
        if isinstance(sub, ast.Attribute):
            mentions.add(sub.attr)
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if _LABELLED_PATH.search(sub.value):
                return PERSISTED
            # A MODE FLAG IS NOT A DESTINATION. `open(path, "w")` was being
            # read as a write to a named file because `"w"` is a string
            # constant, which classified every mode-carrying write as DERIVED
            # and defeated default-deny with an argument that is not a path.
            if "/" in sub.value or "." in sub.value:
                has_literal = True
    if mentions & persisted:
        return PERSISTED
    # A write to a named non-labelled file is a projection out of the set at
    # worst -- `store/waltcg.duckdb`, `probe/COVERAGE.md`, a report. A write
    # whose destination cannot be read at all keeps the obligation.
    return DERIVED if has_literal else UNRESOLVED


def _is_write(node):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        if func.id in WRITE_NAMES:
            for arg in list(node.args[1:2]) + [k.value for k in node.keywords
                                               if k.arg == "mode"]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return any(m in arg.value for m in "wax")
            return False
        return False
    if isinstance(func, ast.Attribute):
        return func.attr in WRITE_PRIMITIVES
    return False


def writes_anything(node):
    return any(_is_write(sub) for sub in ast.walk(node))


def _collection_aliases(node):
    """Names bound from a row collection: `cards = labelled["cards"]`.

    Without this, `cards.append(row)` is invisible -- aliasing the collection
    before mutating it was the first evasion found, and it appeared
    independently in three separate red-team passes.
    """
    aliases = set()
    for _ in range(3):                     # fixpoint; aliases of aliases
        before = len(aliases)
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign) or len(sub.targets) != 1:
                continue
            target, value = sub.targets[0], sub.value
            if not isinstance(target, ast.Name):
                continue
            if _is_collection_expr(value, aliases):
                aliases.add(target.id)
        if len(aliases) == before:
            break
    return aliases


def _is_collection_expr(node, aliases=()):
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.slice.value in ROW_COLLECTION_KEYS
    if isinstance(node, ast.Name) and node.id in aliases:
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # `labelled.get("cards", [])`, `labelled.setdefault("cards", [])`
        if node.func.attr in ("get", "setdefault") and node.args:
            first = node.args[0]
            return (isinstance(first, ast.Constant)
                    and first.value in ROW_COLLECTION_KEYS)
    return False


def _value_kind(value):
    """Is this confidence value the labelled set's, somebody else's, or
    unknowable?

    A CONSTANT OUTSIDE THE VOCABULARY is a different field wearing the same
    name -- `engine/ev/model_e.py` writes `"confidence": "low"`, `store/db.py`
    writes `confidence=1.0`, and neither is a labelled row. A NON-CONSTANT is
    always in scope: that is the data-driven case, and excluding it would
    reintroduce the hole that misses `ingest`.
    """
    if isinstance(value, ast.Constant):
        if isinstance(value.value, str) and value.value in CONFIDENCE_VALUES:
            return "vocabulary"
        return "foreign"
    return "opaque"


def _row_like(node, aliases):
    """Is this expression plausibly a labelled ROW?

    `x.update(y)` on anything at all was 40 false positives -- stats counters,
    header dicts, adapter state. The receiver has to be something that came
    out of the row collection.
    """
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Subscript):
        return _is_collection_expr(node.value, aliases)
    return False


def _row_names(node, aliases):
    """Names bound by iterating the collection: `for card in cards:`."""
    bound = set(aliases)
    for sub in ast.walk(node):
        if isinstance(sub, (ast.For, ast.AsyncFor)):
            if _is_collection_expr(sub.iter, aliases) and isinstance(
                    sub.target, ast.Name):
                bound.add(sub.target.id)
        if isinstance(sub, ast.comprehension):
            if _is_collection_expr(sub.iter, aliases) and isinstance(
                    sub.target, ast.Name):
                bound.add(sub.target.id)
        if isinstance(sub, ast.Assign) and len(sub.targets) == 1:
            if isinstance(sub.targets[0], ast.Name) and isinstance(
                    sub.value, ast.Subscript):
                if _is_collection_expr(sub.value.value, aliases):
                    bound.add(sub.targets[0].id)
    return bound


def _confidence_writes(node, aliases=()):
    """B1 -- every shape that stores a confidence field, scoped by vocabulary
    and by whether the receiver is a labelled row."""
    hits = []
    rows = _row_names(node, aliases)

    def note(sub, how):
        hits.append((getattr(sub, "lineno", 0), how))

    for sub in ast.walk(node):
        if isinstance(sub, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = (sub.targets if isinstance(sub, ast.Assign)
                       else [sub.target])
            for target in targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value in CONF_KEYS):
                    if _value_kind(sub.value) != "foreign":
                        note(sub, "subscript assignment")
                if (isinstance(target, ast.Attribute)
                        and target.attr in CONF_KEYS):
                    if _value_kind(sub.value) != "foreign":
                        note(sub, "attribute assignment")
        if isinstance(sub, ast.Dict):
            for key, value in zip(sub.keys, sub.values):
                if isinstance(key, ast.Constant) and key.value in CONF_KEYS:
                    if _value_kind(value) != "foreign":
                        note(sub, "dict literal")
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name) and func.id == "setattr":
                if (len(sub.args) > 1 and isinstance(sub.args[1], ast.Constant)
                        and sub.args[1].value in CONF_KEYS):
                    note(sub, "setattr")
            if isinstance(func, ast.Name) and func.id == "dict":
                for keyword in sub.keywords:
                    if keyword.arg in CONF_KEYS and _value_kind(
                            keyword.value) != "foreign":
                        note(sub, "dict() keyword")
            if isinstance(func, ast.Attribute) and func.attr in ("update",
                                                                 "setdefault"):
                if any(k.arg in CONF_KEYS for k in sub.keywords if k.arg):
                    note(sub, "update() keyword")
                if func.attr == "setdefault" and sub.args:
                    first = sub.args[0]
                    if (isinstance(first, ast.Constant)
                            and first.value in CONF_KEYS):
                        note(sub, "setdefault")
                # `row.update(patch)` where patch is not a provable literal:
                # the data-driven in-place patch, which carries no literal
                # "verified" anywhere in the function. Scoped to a receiver
                # that came out of the row collection -- unscoped, this was 40
                # false positives on stats counters and adapter state.
                if _row_like(func.value, rows):
                    for arg in sub.args:
                        if isinstance(arg, ast.Dict):
                            if any(k is None for k in arg.keys):
                                note(sub, "update() with ** unpacking")
                        elif not isinstance(arg, ast.Constant):
                            note(sub, "update() with an opaque mapping")
                if any(k.arg in CONF_KEYS for k in sub.keywords if k.arg):
                    note(sub, "update() keyword")
    return hits


def _mentions_rows(node):
    """Does this function ever name a labelled row's marker field?"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value in ROW_MARKER_KEYS:
                return True
        if isinstance(sub, ast.Attribute) and sub.attr in ROW_MARKER_KEYS:
            return True
    return False


def _opaque_admissions(node, aliases, builds_and_writes=False):
    """B2 -- a row enters the collection whose confidence cannot be proved
    absent. This is what makes `ingest` a decision point with no literal
    anywhere in it."""
    hits = []
    mentions_rows = _mentions_rows(node)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr in ("append", "extend", "insert"):
                if _is_collection_expr(sub.func.value, aliases):
                    payload = sub.args[-1] if sub.args else None
                    if not _provably_confidence_free(payload):
                        hits.append((getattr(sub, "lineno", 0),
                                     f"{sub.func.attr}() of an opaque row"))
        if isinstance(sub, ast.Assign):
            for target in sub.targets:
                # A PLAIN NAME TARGET IS THE ALIAS BINDING ITSELF --
                # `cards = labelled["cards"]` is a read, not a write, and
                # flagging it made every reporter in the file a decision
                # point.
                if isinstance(target, ast.Name):
                    continue
                if _is_collection_expr(target, aliases):
                    if not _provably_confidence_free(sub.value):
                        hits.append((getattr(sub, "lineno", 0),
                                     "the collection is replaced wholesale"))
        # `json.dump({"cards": rows}, handle)` -- a whole set built inline
        # and written. No append, no subscript assignment, and it is what a
        # brand-new module writes.
        # Only where THIS function also does the writing. `load_cached_catalog`
        # builds `{"cards": [...], "as_of": ...}` -- targets.json's envelope,
        # not the labelled set -- and never writes anything. Requiring the
        # build and the write in one place keeps the rule aimed at a module
        # that constructs a whole set and dumps it.
        if isinstance(sub, ast.Dict) and mentions_rows and builds_and_writes:
            for key, value in zip(sub.keys, sub.values):
                if (isinstance(key, ast.Constant)
                        and key.value in ROW_COLLECTION_KEYS
                        and not _provably_confidence_free(value)):
                    hits.append((getattr(sub, "lineno", 0),
                                 "a collection is built inline from opaque "
                                 "rows"))
        if isinstance(sub, ast.AugAssign) and _is_collection_expr(sub.target,
                                                                  aliases):
            if not _provably_confidence_free(sub.value):
                hits.append((getattr(sub, "lineno", 0),
                             "the collection is extended in place"))
    return hits


def _provably_confidence_free(node):
    """Only an inline literal with constant keys and no confidence key.

    Anything else -- a name, a comprehension, a call result, a `**` unpack --
    is opaque. Depth-1 folding deliberately: the moment this starts chasing
    values across statements it becomes a dataflow engine that is wrong in
    ways nobody can audit.
    """
    if node is None:
        return False
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            return False
        for key in node.keys:
            if not isinstance(key, ast.Constant):
                return False
            if key.value in CONF_KEYS:
                return False
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return all(_provably_confidence_free(e) for e in node.elts)
    return False


# -- the gate, and whether a decision point reaches it ---------------------

def _gate_problems(index, must_graph):
    """R-exists, R-refuses, R-composite.

    A pinned gate list is only defensible if these hold. Removing a gate makes
    the check stricter, which is safe; a gate that cannot refuse, or one gutted
    to `return True, ""`, would pass everything downstream while looking
    exactly like a gate.
    """
    problems = []
    for root, must_reach in GATE_ROOTS.items():
        if root not in index.functions:                      # R-exists
            problems.append((root, "is pinned as a gate and does not exist. "
                                   "A stale gate entry is a hard failure, "
                                   "never a silent pass."))
            continue
        _path, node = index.functions[root]
        refuses = False
        for sub in ast.walk(node):                           # R-refuses
            if isinstance(sub, ast.Raise):
                refuses = True
            if isinstance(sub, ast.Return):
                value = sub.value
                if isinstance(value, ast.Constant) and not value.value:
                    refuses = True
                if isinstance(value, ast.Tuple) and value.elts:
                    first = value.elts[0]
                    if isinstance(first, ast.Constant) and not first.value:
                        refuses = True
                if isinstance(value, ast.UnaryOp) and isinstance(value.op,
                                                                ast.Not):
                    refuses = True
                # `return not problems, problems` -- the refusal is the first
                # element of a tuple and is computed, not constant.
                if isinstance(value, ast.Tuple) and value.elts:
                    first = value.elts[0]
                    if isinstance(first, ast.UnaryOp) and isinstance(
                            first.op, ast.Not):
                        refuses = True
                # `return {"verified": not missing, ...}` -- a decider that
                # answers in a field rather than in the return shape.
                if isinstance(value, ast.Dict):
                    for key, val in zip(value.keys, value.values):
                        if not isinstance(key, ast.Constant):
                            continue
                        if isinstance(val, ast.UnaryOp) and isinstance(
                                val.op, ast.Not):
                            refuses = True
                        if isinstance(val, ast.Constant) and val.value is False:
                            refuses = True
        if not refuses:
            problems.append((root, "has no refusing exit. A function that "
                                   "cannot say no is not a gate."))
        if must_reach:                                       # R-composite
            if not _reaches(root, must_graph, {must_reach}):
                problems.append(
                    (root, f"does not reach {must_reach}. A wrapper that "
                           "stopped consulting the decider would pass "
                           "everything downstream and still look like a "
                           "gate."))
    return problems


def _consumes_result(node, gate_names):
    """R-consume: the gate's answer must be able to stop the elevation.

    `ok, why = gate(...)` followed by `if not ok: return` counts.
    `_ = gate(...)` does not -- calling a gate and ignoring it is the orphaned
    defect with an extra step.
    """
    bound = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Call):
            called = sub.value.func
            name = (called.attr if isinstance(called, ast.Attribute)
                    else getattr(called, "id", None))
            if name in gate_names:
                for target in sub.targets:
                    for inner in ast.walk(target):
                        if isinstance(inner, ast.Name):
                            bound.add(inner.id)
        if isinstance(sub, (ast.If, ast.Assert, ast.While, ast.IfExp)):
            test = sub.test
            for inner in ast.walk(test):
                if isinstance(inner, ast.Name) and inner.id in bound:
                    return True
                if isinstance(inner, ast.Call):
                    called = inner.func
                    name = (called.attr if isinstance(called, ast.Attribute)
                            else getattr(called, "id", None))
                    if name in gate_names:
                        return True
    return False


def _markers(root, path):
    """Exemptions, by line. In-code at the defect, never a config file."""
    found = {}
    try:
        with open(os.path.join(root, path), encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return found
    for number, line in enumerate(lines, start=1):
        hit = _MARKER.search(line)
        if not hit:
            continue
        found[number] = hit.group("claim")
        # It applies to the next STATEMENT, skipping the rest of its own
        # comment block. A marker still has to sit at the defect -- a
        # module-level or def-level one is not found by this at all, because
        # an exemption that floats near the problem is an exemption nobody
        # can locate when the problem moves.
        cursor = number
        while cursor < len(lines):
            text = lines[cursor].strip()
            if text and not text.startswith("#"):
                found[cursor + 1] = hit.group("claim")
                break
            cursor += 1
    return found


# -- the check -------------------------------------------------------------

def check(root=REPO, verbose=False, include_tests=False):
    paths = tracked_files(root)
    index = Index(root, paths)

    may_graph, must_graph, dynamic_uses = {}, {}, []
    for qual in index.functions:
        may, dyn = _call_targets(index, qual, must=False)
        must, _ = _call_targets(index, qual, must=True)
        may_graph[qual], must_graph[qual] = may, must
        for name, line in dyn:
            dynamic_uses.append((qual, name, line))

    # SINKS OVER-APPROXIMATE. A missed edge here is a missed site, which is a
    # silent pass -- so the may-graph, and the closure of everything those
    # functions call, because a mutator whose caller persists is a decision
    # point too.
    persisted = _persisted_names(index)
    writers, unresolved_writers = set(), []
    for qual, (path, node) in index.functions.items():
        for sub in ast.walk(node):
            if not _is_write(sub):
                continue
            where = _sink_class(sub, persisted)
            if where == PERSISTED:
                writers.add(qual)
            elif where == UNRESOLVED:
                # DEFAULT-DENY, but not a closure root. Reported on its own
                # merits: being unable to say where a write goes keeps the
                # obligation, while expanding the callee closure of every
                # unreadable write drags half the repository in and reports
                # everything -- which is as useless as reporting nothing.
                unresolved_writers.append(
                    (qual, path, getattr(sub, "lineno", 0)))
    persisters = {q for q in index.functions
                  if _reaches(q, may_graph, writers)}
    # SIBLING METHODS COUNT. Splitting the mutation from the save across two
    # methods of one class was the third evasion, and it defeats a closure
    # built only from callees: `raise_row` mutates, `save` persists, and
    # neither calls the other. If any method of a class persists, every method
    # of that class is inside the closure -- they share `self`.
    owners = {}
    for qual in index.functions:
        module, _sep, tail = qual.partition(":")
        if "." in tail:
            owners.setdefault(f"{module}:{tail.rsplit('.', 1)[0]}",
                              []).append(qual)
    unresolved_owners = {q for q, _p, _l in unresolved_writers}
    for _owner, methods in owners.items():
        if any(method in persisters or method in unresolved_owners
               for method in methods):
            # An UNRESOLVED writer pulls in its own siblings but not the wider
            # callee tree: the class shares `self`, so the split is real, while
            # expanding every unreadable write's callees drags the repository
            # in.
            persisters.update(methods)
    in_closure = _closure(persisters, may_graph)
    # An unreadable write is a decision point IN ITSELF, but not a root for
    # expansion -- it goes through the same loop as everything else so it gets
    # the same marker verification and the same test/production split.
    in_closure |= {q for q, _p, _l in unresolved_writers}

    gate_names = {r.split(":")[-1].split(".")[-1] for r in GATE_ROOTS}
    violations, informational, exemptions = [], [], []

    for qual in sorted(index.functions):
        path, node = index.functions[qual]
        if qual not in in_closure:
            continue
        aliases = _collection_aliases(node)
        writes_here = any(_is_write(sub) for sub in ast.walk(node))
        hits = ([(line, f"writes a confidence field ({how})")
                 for line, how in _confidence_writes(node, aliases)]
                + [(line, f"admits a row that could carry one ({how})")
                   for line, how in _opaque_admissions(node, aliases,
                                                       writes_here)])
        if not hits:
            continue
        # GUARDS UNDER-APPROXIMATE. A spurious edge here is a fake guard.
        #
        # R-consume is checked ON THE PATH, not only in the site: `ingest`
        # calls `row_is_admissible`, which calls the gate and acts on its
        # answer. Requiring the site itself to consume would refuse every
        # wrapper and push callers to inline the gate, which is worse code
        # for no more safety.
        guarded = _reaches(qual, must_graph, set(GATE_ROOTS)) and any(
            _consumes_result(index.functions[on_path][1], gate_names)
            for on_path in _closure({qual}, must_graph)
            if on_path in index.functions
            and set(must_graph.get(on_path, ())) & set(GATE_ROOTS))
        marks = _markers(root, path)
        line = min(h[0] for h in hits)
        is_test = path.startswith("tests/") or "/tests/" in path
        record = {"qualname": qual, "file": path, "line": line,
                  "why": "; ".join(sorted({h[1] for h in hits}))}
        if guarded:
            continue
        if any(number in marks for number, _ in hits):
            claim = next(marks[n] for n, _ in hits if n in marks)
            # THE CLAIM IS MACHINE-VERIFIED WHERE IT CAN BE. An exemption
            # asserting something false is worse than no exemption: it reads
            # as a considered decision.
            wrote = _confidence_writes(node, aliases)
            if claim == "no-confidence-write" and wrote:
                violations.append(dict(
                    record, why=record["why"] + " -- and its exemption claims "
                    "`no-confidence-write`, which is false: a confidence "
                    f"write was detected at line {wrote[0][0]}"))
                continue
            exemptions.append(dict(record, claim=claim))
            continue
        if is_test and not include_tests:
            informational.append(record)
        else:
            violations.append(record)

    problems = _gate_problems(index, must_graph)
    # Dynamic dispatch matters only where a decision is actually being made.
    # Reported once per function: `render_catalog_summary` uses getattr twice
    # and is not a decision point at all.
    site_names = {entry["qualname"] for entry in violations + exemptions}
    seen_dynamic = set()
    for qual, name, line in dynamic_uses:
        if qual in seen_dynamic or qual not in site_names:
            continue
        seen_dynamic.add(qual)
        violations.append({
            "qualname": qual, "file": index.functions[qual][0], "line": line,
            "why": f"uses {name}() while deciding. Dynamic dispatch is "
                   "refused rather than resolved -- this check cannot follow "
                   "it, so it cannot certify it."})

    return violations, informational, exemptions, problems


def report(violations, informational, exemptions, problems, verbose=False):
    if problems:
        print("THE GATE ITSELF IS BROKEN:")
        for root_, why in problems:
            print(f"  {root_}\n      {why}")
        print()
    if violations:
        print(f"UNGUARDED ELEVATION -- {len(violations)} path(s) can raise a "
              "row to `verified` without reaching the gate:\n")
        for entry in violations:
            print(f"  {entry['file']}:{entry['line']}  {entry['qualname']}")
            print(f"      {entry['why']}")
            print(f"      does not reach any of: "
                  f"{', '.join(sorted(GATE_ROOTS)[:2])} ...")
        print()
    if exemptions:
        print(f"EXEMPT -- {len(exemptions)} marked path(s):")
        for entry in exemptions:
            print(f"  {entry['file']}:{entry['line']}  {entry['qualname']}"
                  f"  [{entry['claim']}]")
        if len(exemptions) != EXPECTED_EXEMPTIONS:
            print(f"  ROSTER BROKEN: {len(exemptions)} exemptions, "
                  f"{EXPECTED_EXEMPTIONS} expected. Raise "
                  "EXPECTED_EXEMPTIONS in the same commit that adds one -- an "
                  "allowlist that grows silently is the defect this check is "
                  "about.")
        print()
    if informational and verbose:
        print(f"TEST-SIDE -- {len(informational)} path(s) under tests/ "
              "construct or admit rows without the gate. Not a failure: a "
              "fixture is allowed to. Reported so the count cannot grow "
              "unnoticed.")
        for entry in informational:
            print(f"  {entry['file']}:{entry['line']}  {entry['qualname']}")
        print()
    if not (violations or problems):
        print("no-unguarded-elevation: clean")
        print("  every path that can raise a row to `verified` reaches the "
              "corroboration gate")
    return 1 if (violations or problems
                 or len(exemptions) != EXPECTED_EXEMPTIONS) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="audit.checks.no_unguarded_elevation")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--path", default=REPO)
    parser.add_argument("--include-tests", action="store_true",
                        help="fail on test-side paths too, instead of "
                             "reporting them")
    args = parser.parse_args(argv)
    return report(*check(args.path, args.verbose, args.include_tests),
                  verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
