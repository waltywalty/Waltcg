#!/usr/bin/env python3
"""Hard gate: no PDFs in the tree, and no undeclared PDF-derived docs.

The failure this exists to stop is silent conversion. A document arrives as a
PDF, gets machine-extracted into Markdown, and lands in docs/ reading exactly
like something that was written there. Nothing in the file says a lossy
extraction step happened, so nothing downstream can weigh it. Six weeks later
a sentence that a ligature or a dropped column mangled is being quoted as
though it were typed.

Four rules:

  1. No PDF is tracked, anywhere. By extension, and by magic bytes -- a PDF
     renamed to .md is the same file.
  2. Every tracked docs/**/*.md is declared in docs/PROVENANCE.md with an
     origin. An undeclared doc fails. This is the rule that does the work:
     you cannot add a document without saying where its text came from.
  3. An origin of `pdf-extraction` requires a complete source note -- the
     source file, the extraction date, the tool, and how the result was
     verified. A partial note fails the same as no note.
  4. No docs file contains extraction artifacts: typographic ligatures, soft
     hyphens, zero-width characters, replacement characters, form feeds, or
     `(cid:N)` sequences. These are not things anyone types. They are what a
     PDF text layer leaves behind when it goes wrong, and they fail whatever
     the declared origin says.

What this check CANNOT do, stated plainly so nobody trusts it further than it
goes: it cannot detect a *clean* extraction that was declared as pasted text.
Rule 4 catches mangling, not derivation. Rules 2 and 3 make derivation a thing
you declare rather than a thing that gets inferred, and that is the whole of
the guarantee. The check makes silence impossible; it does not make a false
declaration impossible.

Usage:  python -m audit.checks.no_pdf_provenance [--verbose]
Exit 0 clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MANIFEST = "docs/PROVENANCE.md"
DOC_PATTERN = re.compile(r"^docs/.*\.md$")

# 1 -- PDFs. Extension catches the ordinary case; magic bytes catch the one
# that actually bites, a PDF saved under a text extension.
PDF_EXTENSION = re.compile(r"\.pdf$", re.IGNORECASE)
PDF_MAGIC = b"%PDF-"

# 2 -- the closed set of origins. Adding a value here is a deliberate act.
ORIGINS = {
    # Written directly in the repository.
    "authored",
    # Supplied as text -- pasted into chat, or uploaded already in a text
    # format -- and copied across without a conversion step.
    "verbatim-text",
    # Machine-extracted from a PDF. Requires the full source note, rule 3.
    "pdf-extraction",
}
ORIGINS_NEEDING_SOURCE_NOTE = {"pdf-extraction"}

# Cells that look filled in but say nothing.
PLACEHOLDERS = {"", "-", "--", "n/a", "na", "none", "tbd", "todo", "?", "unknown"}
EM_DASH = "—"

# A verification cell has to describe a method. Anything under this length is
# a word, not a method -- "cmp", "checked", "yes" tell a later reader nothing
# about what was actually compared against what.
MIN_VERIFICATION_CHARS = 20

# 4 -- characters a PDF text layer leaves behind. Built from escapes so this
# file never contains a literal one and can be quoted safely in a document.
ARTIFACTS = {
    "\ufb00": "ligature ff",
    "\ufb01": "ligature fi",
    "\ufb02": "ligature fl",
    "\ufb03": "ligature ffi",
    "\ufb04": "ligature ffl",
    "\ufb05": "ligature long-s t",
    "\ufb06": "ligature st",
    "\u00ad": "soft hyphen",
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\ufffd": "replacement character (text lost in decoding)",
    "\x0c": "form feed (page break)",
}
CID_ARTIFACT = re.compile(r"\(cid:\d+\)")


def tracked_files():
    # Tracked PLUS untracked-not-ignored: a doc written this minute is
    # untracked, and this check runs before the commit that would track it.
    # Same `inert / by_scope` bug as `no_provider_data` had. `*.pdf` is
    # gitignored, so `--exclude-standard` keeps a local PDF out of scope while
    # bringing an undeclared new `docs/*.md` in.
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"git ls-files failed: {out.stderr}")
    paths = {f for f in out.stdout.splitlines() if f.strip()}
    others = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=REPO, capture_output=True, text=True)
    if others.returncode == 0:
        paths |= {f for f in others.stdout.splitlines() if f.strip()}
    return sorted(paths)


def read_text(path):
    try:
        with open(os.path.join(REPO, path), encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, IsADirectoryError):
        return ""


def read_head(path, n=8):
    try:
        with open(os.path.join(REPO, path), "rb") as f:
            return f.read(n)
    except (OSError, IsADirectoryError):
        return b""


def blank(cell):
    """A cell that is present but says nothing."""
    return cell.strip().strip("`").replace(EM_DASH, "").strip().lower() in PLACEHOLDERS


def _tables(body):
    """Yield each Markdown table in the document as a list of cell-rows. A run
    of table lines ends at the first line that is not one."""
    block = []
    for line in body.split("\n") + [""]:
        s = line.strip()
        if s.startswith("|"):
            if not re.fullmatch(r"\|[\s|:-]+\|", s):    # skip separator rows
                block.append([c.strip() for c in s.strip("|").split("|")])
            continue
        if block:
            yield block
            block = []


def parse_manifest(body):
    """Read the register. Returns {path: {column: cell}} and its header.

    The document holds more than one table -- there is an origins legend above
    the register -- so the register is selected by its columns, not by position.
    Taking the first table found is what the first run of this parser did, and
    it read the legend's `Origin | Meaning` as the header."""
    for block in _tables(body):
        header = [c.lower() for c in block[0]]
        if "file" not in header or "origin" not in header:
            continue
        rows = {}
        for cells in block[1:]:
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells))
            path = row.get("file", "").strip().strip("`")
            if path:
                rows[path] = row
        return rows, header
    return {}, None


def check(verbose=False):
    violations = []
    files = tracked_files()
    docs = sorted(f for f in files if DOC_PATTERN.match(f))
    if verbose:
        print(f"scanning {len(files)} tracked files, {len(docs)} under docs/")

    # 1 -- no PDF in the tree, by extension or by magic bytes.
    for f in files:
        if PDF_EXTENSION.search(f):
            violations.append(
                (f, "PDF committed to the repository",
                 "PDFs are not a source format here. Convert to Markdown, record the "
                 f"conversion in {MANIFEST}, and keep the PDF out of the tree."))
        elif read_head(f).startswith(PDF_MAGIC):
            violations.append(
                (f, "PDF committed under a non-PDF extension",
                 "the file begins with the PDF magic bytes. Renaming a PDF does not "
                 "convert it; the bytes are still a PDF."))

    # 2 and 3 -- the manifest.
    if MANIFEST not in files:
        violations.append(
            (MANIFEST, "provenance manifest is missing",
             "every document under docs/ must declare where its text came from. "
             f"Create {MANIFEST} with a table: File | Origin | Source | Extracted on | "
             f"Tool | Verification. Valid origins: {sorted(ORIGINS)}."))
        return violations

    rows, header = parse_manifest(read_text(MANIFEST))
    if header is None or "file" not in header or "origin" not in header:
        violations.append(
            (MANIFEST, "provenance manifest has no readable table",
             "expected a Markdown table whose first two columns are File and Origin."))
        return violations

    for f in docs:
        row = rows.get(f)
        if row is None:
            violations.append(
                (f, "document is not declared in the provenance manifest",
                 f"add a row to {MANIFEST} saying where this text came from. If it was "
                 "extracted from a PDF, say so -- that is the whole point of this gate."))
            continue

        origin = row.get("origin", "").strip().strip("`").lower()
        if origin not in ORIGINS:
            violations.append(
                (f, f"unrecognised origin {origin!r}",
                 f"valid origins are {sorted(ORIGINS)}."))
            continue

        if origin in ORIGINS_NEEDING_SOURCE_NOTE:
            for column in ("source", "extracted on", "tool", "verification"):
                if column not in header:
                    violations.append(
                        (MANIFEST, f"manifest has no {column!r} column",
                         f"an origin of {origin!r} requires it."))
                elif blank(row.get(column, "")):
                    violations.append(
                        (f, f"origin is {origin!r} but {column!r} is blank",
                         "a PDF-derived document needs a complete source note: which "
                         "file, when, with what tool, and how the result was checked. "
                         "A partial note is not a note."))
            v = row.get("verification", "")
            if not blank(v) and len(v.strip()) < MIN_VERIFICATION_CHARS:
                violations.append(
                    (f, "verification note is too short to be a method",
                     f"{v!r} does not say what was compared against what. Extraction is "
                     "lossy; the note is how a later reader judges how lossy."))

    # Rows for documents that no longer exist are stale, not dangerous, but a
    # manifest nobody prunes is a manifest nobody reads.
    for path in sorted(rows):
        if DOC_PATTERN.match(path) and path not in docs:
            violations.append(
                (MANIFEST, f"stale row for {path}",
                 "the file is not tracked. Remove the row, or restore the file."))

    # 4 -- extraction artifacts anywhere under docs/.
    for f in docs:
        body = read_text(f)
        for ch, name in ARTIFACTS.items():
            if ch in body:
                line = body[:body.index(ch)].count("\n") + 1
                violations.append(
                    (f, f"extraction artifact on line {line}: {name}",
                     f"U+{ord(ch):04X} is not typed by hand. It is what a PDF text layer "
                     "leaves behind. Fix the text; do not commit mangled extraction "
                     "output."))
        cid = CID_ARTIFACT.search(body)
        if cid:
            line = body[:cid.start()].count("\n") + 1
            violations.append(
                (f, f"extraction artifact on line {line}: {cid.group(0)}",
                 "an unmapped glyph id. The extractor could not resolve these characters "
                 "at all, so this passage is not the source text."))

    return violations


def main():
    ap = argparse.ArgumentParser(
        description="refuse committed PDFs and undeclared PDF-derived documents")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    violations = check(args.verbose)
    if not violations:
        print("no-pdf-provenance: clean")
        print("  no PDFs tracked; every docs/ file declares where its text came from")
        return 0

    print(f"no-pdf-provenance: {len(violations)} VIOLATION(S)\n", file=sys.stderr)
    for path, what, detail in violations:
        print(f"  {path}\n      {what}\n      {detail}\n", file=sys.stderr)
    print("This is a hard gate. Nothing merges until it is clean.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
