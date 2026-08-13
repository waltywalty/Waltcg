#!/usr/bin/env python3
"""Hard gate: no provider data may be committed.

The rule (GOAL non-negotiable 7, CLAUDE.md non-negotiable 10,
DATA_SOURCES section 4): **no provider data is ever committed. Code may be
public; data never is.**

Repository visibility is not a control. It can be flipped by anyone with
settings access, it does not survive a fork, and it says nothing about what is
already in the history. This check is the control. It runs on every push,
including pushes made by workflows, and it fails the build rather than
warning.

Three things it refuses:

  1. Data files by path or extension -- anything matching the data patterns
     .gitignore already covers. Tracked at all means someone used --force.
  2. Provider payload signatures in data files -- response keys that only
     appear in a real payload (salesByGrade, populationByGrader, marketPrice
     and friends) inside committed .json/.csv/.yaml.
  3. Money-shaped values in generated reports -- probe/COVERAGE.md and
     probe/STRUCTURE.md carry statuses and counts, never prices.

What it deliberately allows: our own subscription costs in config and docs
(they are what we pay, not what a card sold for), money in test fixtures and
engine code (Money("15000","JPY") is a type constructor, not a price
observation), and the synthetic replay fixtures under probe/fixtures/, which
must declare themselves synthetic.

Usage:  python -m audit.checks.no_provider_data [--verbose]
Exit 0 clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1. Data files that must never be tracked, whatever .gitignore says.
FORBIDDEN_PATH_PATTERNS = [
    re.compile(r"(^|/)probe/out/"),
    re.compile(r"\.(db|sqlite|sqlite3|parquet|feather|arrow)$"),
    re.compile(r"\.csv$"),
    re.compile(r"\.tsv$"),
    re.compile(r"(^|/)results\.json$"),
    re.compile(r"(^|/)raw/.*\.json$"),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)store/.*\.(json|db)$"),
]

# 2. Keys that only appear in a real provider payload.
PROVIDER_PAYLOAD_KEYS = [
    "salesByGrade", "sales_by_grade", "populationByGrader", "population_by_grader",
    "combinedGemRate", "combined_gem_rate", "totalPopulation", "total_population",
    "marketPrice", "market_price", "tcgplayer_id", "lowPrice", "midPrice",
    "directLowPrice", "apiCallsConsumed", "daily_remaining",
]
DATA_EXTENSIONS = (".json", ".csv", ".yaml", ".yml", ".ndjson")

# Files allowed to mention payload keys because they are synthetic fixtures or
# schema/config describing the shape rather than carrying an observation.
PAYLOAD_KEY_ALLOWLIST = [
    re.compile(r"^probe/fixtures/.*\.json$"),      # synthetic, marker-checked below
    re.compile(r"^contracts/.*\.json$"),           # schema and assumption registry
    re.compile(r"^config/.*\.ya?ml$"),             # dated config, our own costs
]

# probe/fixtures must say they are synthetic, so a real payload cannot be
# dropped in under cover of the allowlist.
SYNTHETIC_MARKERS = ("fixture", "synthetic", "no fixture matched")

# 3. Generated reports that must carry statuses and counts only.
GENERATED_REPORTS = ["probe/COVERAGE.md", "probe/STRUCTURE.md"]
MONEY_SHAPED = re.compile(
    r"[$£¥€]\s?\d"
    r"|\b\d+\.\d{2}\b"
    r"|\b(?:USD|JPY|EUR|GBP|CNY|HKD)\s?\d",
    re.IGNORECASE,
)


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"git ls-files failed: {out.stderr}")
    return [f for f in out.stdout.splitlines() if f.strip()]


def read(path):
    try:
        with open(os.path.join(REPO, path), encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, IsADirectoryError):
        return ""


def check(verbose=False):
    violations = []
    files = tracked_files()
    if verbose:
        print(f"scanning {len(files)} tracked files")

    # 1 -- forbidden paths
    for f in files:
        for pat in FORBIDDEN_PATH_PATTERNS:
            if pat.search(f):
                violations.append(
                    (f, "data file is tracked",
                     f"matches {pat.pattern!r}. Provider data and local stores are never "
                     "committed; if this was added with `git add --force`, remove it and "
                     "purge it from history."))
                break

    # 2 -- provider payload signatures in data files
    for f in files:
        if not f.endswith(DATA_EXTENSIONS):
            continue
        allowed = any(p.match(f) for p in PAYLOAD_KEY_ALLOWLIST)
        body = read(f)
        hits = sorted({k for k in PROVIDER_PAYLOAD_KEYS if k in body})
        if not hits:
            continue
        if not allowed:
            violations.append(
                (f, "provider payload keys in a committed data file",
                 f"found {hits}. This looks like a cached response. Raw payloads live in "
                 "probe/out/, which is gitignored."))
        elif f.startswith("probe/fixtures/"):
            low = body.lower()
            if not any(m in low for m in SYNTHETIC_MARKERS):
                violations.append(
                    (f, "fixture carries payload keys but does not declare itself synthetic",
                     f"found {hits} with no synthetic marker. Add one, or move the file "
                     "out of the allowlist."))

    # 3 -- money-shaped values in generated reports
    for f in GENERATED_REPORTS:
        if f not in files:
            continue
        body = read(f)
        bad = MONEY_SHAPED.findall(body)
        if bad:
            violations.append(
                (f, "money-shaped values in a generated report",
                 f"found {bad[:5]}. Reports carry coverage status and sample counts only; "
                 "price values stay in probe/out/."))

    return violations


def main():
    ap = argparse.ArgumentParser(description="refuse to commit provider data")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    violations = check(args.verbose)
    if not violations:
        print("no-provider-data: clean")
        print("  code may be public; data never is -- enforced here, not by repo settings")
        return 0

    print(f"no-provider-data: {len(violations)} VIOLATION(S)\n", file=sys.stderr)
    for path, what, detail in violations:
        print(f"  {path}\n      {what}\n      {detail}\n", file=sys.stderr)
    print("This is a hard gate. Nothing merges until it is clean.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
