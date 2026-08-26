"""The PDF provenance gate, tested by making it fail.

A guard that has only ever been seen passing is not evidence of anything. Every
rule here is proved on a scratch repository seeded with the exact violation it
is supposed to catch, and each assertion checks the message names the right
thing -- a check that fails for the wrong reason is a check that will pass for
the wrong reason later.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(REPO, "audit", "checks", "no_pdf_provenance.py")

sys.path.insert(0, REPO)
from audit.checks import no_pdf_provenance as guard  # noqa: E402

HEADER = ("| File | Origin | Source | Extracted on | Tool | Verification |\n"
          "|---|---|---|---|---|---|\n")
AUTHORED = "| `docs/{}` | authored | — | — | — | — |\n"
SELF = "| `docs/PROVENANCE.md` | authored | — | — | — | — |\n"

# A complete, passing pdf-extraction row, used as the base for the rows that
# should fail. Each failing case removes exactly one thing from it.
GOOD_EXTRACTION = ("| `docs/{}` | pdf-extraction | `brief.pdf` | 2026-08-13 | "
                   "pdfminer.six 20260107 | normalised both sides to one token "
                   "stream and compared with cmp, identical |\n")


class Scratch:
    """A throwaway git repository with the checker copied in, so the module's
    own REPO resolution points at the scratch tree rather than the real one."""

    def __enter__(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "audit", "checks"))
        os.makedirs(os.path.join(self.dir, "docs"))
        shutil.copy(CHECK, os.path.join(self.dir, "audit", "checks"))
        for pkg in (("audit",), ("audit", "checks")):
            open(os.path.join(self.dir, *pkg, "__init__.py"), "w").close()
        subprocess.run(["git", "init", "-q", "."], cwd=self.dir, check=True)
        for k, v in (("user.email", "ci@ci"), ("user.name", "ci")):
            subprocess.run(["git", "config", k, v], cwd=self.dir, check=True)
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, path, body, binary=False):
        full = os.path.join(self.dir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode, enc = ("wb", None) if binary else ("w", "utf-8")
        with open(full, mode, encoding=enc) as f:
            f.write(body)

    def manifest(self, register):
        self.write("docs/PROVENANCE.md", "# Provenance\n\n" + HEADER + register)

    def run(self):
        subprocess.run(["git", "add", "-A", "-f"], cwd=self.dir,
                       check=True, capture_output=True)
        p = subprocess.run([sys.executable, "-m", "audit.checks.no_pdf_provenance"],
                           cwd=self.dir, capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


class GateFires(unittest.TestCase):

    def assertRejected(self, scratch, phrase):
        code, out = scratch.run()
        self.assertEqual(code, 1, f"gate passed a violation it should catch:\n{out}")
        self.assertIn(phrase, out, f"rejected, but not for the stated reason:\n{out}")

    def test_a_clean_tree_passes(self):
        """The baseline every other case is a single mutation away from."""
        with Scratch() as s:
            s.write("docs/notes.md", "# Notes\n\nWritten here.\n")
            s.manifest(AUTHORED.format("notes.md") + SELF)
            code, out = s.run()
            self.assertEqual(code, 0, out)

    def test_pdf_by_extension_is_rejected(self):
        with Scratch() as s:
            s.write("docs/brief.pdf", b"%PDF-1.4\nnot really\n", binary=True)
            s.manifest(SELF)
            self.assertRejected(s, "PDF committed to the repository")

    def test_pdf_anywhere_not_just_docs_is_rejected(self):
        with Scratch() as s:
            s.write("reference/spec.PDF", b"%PDF-1.7\n", binary=True)
            s.manifest(SELF)
            self.assertRejected(s, "PDF committed to the repository")

    def test_pdf_renamed_to_markdown_is_rejected(self):
        """The case that actually bites: the extension is a claim, the bytes
        are the fact."""
        with Scratch() as s:
            s.write("docs/brief.md", b"%PDF-1.4\n%\xc7\xec\x8f\xa2\n", binary=True)
            s.manifest(AUTHORED.format("brief.md") + SELF)
            self.assertRejected(s, "under a non-PDF extension")

    def test_undeclared_document_is_rejected(self):
        with Scratch() as s:
            s.write("docs/notes.md", "# Notes\n")
            s.write("docs/smuggled.md", "# Arrived from somewhere\n")
            s.manifest(AUTHORED.format("notes.md") + SELF)
            self.assertRejected(s, "not declared in the provenance manifest")

    def test_missing_manifest_is_rejected(self):
        with Scratch() as s:
            s.write("docs/notes.md", "# Notes\n")
            self.assertRejected(s, "provenance manifest is missing")

    def test_manifest_without_a_register_table_is_rejected(self):
        with Scratch() as s:
            s.write("docs/notes.md", "# Notes\n")
            s.write("docs/PROVENANCE.md", "# Provenance\n\nEverything is fine.\n")
            self.assertRejected(s, "no readable table")

    def test_unrecognised_origin_is_rejected(self):
        with Scratch() as s:
            s.write("docs/notes.md", "# Notes\n")
            s.manifest("| `docs/notes.md` | vibes | — | — | — | — |\n" + SELF)
            self.assertRejected(s, "unrecognised origin")

    def test_stale_row_for_a_deleted_document_is_rejected(self):
        with Scratch() as s:
            s.manifest(AUTHORED.format("deleted-last-week.md") + SELF)
            self.assertRejected(s, "stale row")


class ExtractionNeedsAFullSourceNote(unittest.TestCase):
    """Rule 3. A partial note fails the same as no note -- half a source note
    is the shape of a record without the content of one."""

    def _missing(self, column, cell_index):
        with Scratch() as s:
            s.write("docs/brief.md", "# Brief\n\nSome text.\n")
            row = GOOD_EXTRACTION.format("brief.md")
            cells = row.strip().strip("|").split("|")
            cells[cell_index] = " — "
            s.manifest("|" + "|".join(cells) + "|\n" + SELF)
            code, out = s.run()
            self.assertEqual(code, 1, f"accepted a note missing {column}:\n{out}")
            self.assertIn(f"{column!r} is blank", out, out)

    def test_a_complete_note_passes(self):
        with Scratch() as s:
            s.write("docs/brief.md", "# Brief\n\nSome text.\n")
            s.manifest(GOOD_EXTRACTION.format("brief.md") + SELF)
            code, out = s.run()
            self.assertEqual(code, 0, out)

    def test_missing_source_file_is_rejected(self):
        self._missing("source", 2)

    def test_missing_extraction_date_is_rejected(self):
        self._missing("extracted on", 3)

    def test_missing_tool_is_rejected(self):
        self._missing("tool", 4)

    def test_missing_verification_is_rejected(self):
        self._missing("verification", 5)

    def test_a_one_word_verification_is_rejected(self):
        """'checked' is not a method. The note is how a later reader judges how
        lossy the extraction was, and it cannot do that from a word."""
        with Scratch() as s:
            s.write("docs/brief.md", "# Brief\n")
            row = GOOD_EXTRACTION.format("brief.md")
            cells = row.strip().strip("|").split("|")
            cells[5] = " checked "
            s.manifest("|" + "|".join(cells) + "|\n" + SELF)
            code, out = s.run()
            self.assertEqual(code, 1, out)
            self.assertIn("too short to be a method", out)

    def test_placeholders_do_not_count_as_filled_in(self):
        for placeholder in ("TODO", "TBD", "n/a", "?", "-"):
            with self.subTest(placeholder=placeholder), Scratch() as s:
                s.write("docs/brief.md", "# Brief\n")
                row = GOOD_EXTRACTION.format("brief.md")
                cells = row.strip().strip("|").split("|")
                cells[4] = f" {placeholder} "
                s.manifest("|" + "|".join(cells) + "|\n" + SELF)
                code, out = s.run()
                self.assertEqual(code, 1, f"{placeholder!r} accepted as a tool:\n{out}")


class ArtifactsAreRejectedWhateverTheDeclaration(unittest.TestCase):
    """Rule 4. These characters are not typed. Their presence means a passage
    is not the source text, so the declared origin is irrelevant."""

    def test_every_known_artifact_is_caught(self):
        for ch, name in guard.ARTIFACTS.items():
            with self.subTest(artifact=name), Scratch() as s:
                s.write("docs/notes.md", f"# Notes\n\nThe of{ch}ce is open.\n")
                s.manifest(AUTHORED.format("notes.md") + SELF)
                code, out = s.run()
                self.assertEqual(code, 1, f"{name} slipped through:\n{out}")
                self.assertIn("extraction artifact", out)

    def test_unmapped_glyph_ids_are_caught(self):
        with Scratch() as s:
            s.write("docs/notes.md", "# Notes\n\nThe (cid:145)(cid:146) is open.\n")
            s.manifest(AUTHORED.format("notes.md") + SELF)
            code, out = s.run()
            self.assertEqual(code, 1, out)
            self.assertIn("(cid:145)", out)

    def test_an_artifact_is_caught_even_when_the_origin_is_declared(self):
        """Declaring the extraction does not license shipping mangled output."""
        with Scratch() as s:
            s.write("docs/brief.md", "# Brief\n\nThe ofﬁce is open.\n")
            s.manifest(GOOD_EXTRACTION.format("brief.md") + SELF)
            code, out = s.run()
            self.assertEqual(code, 1, out)
            self.assertIn("extraction artifact", out)

    def test_the_reported_line_number_is_right(self):
        with Scratch() as s:
            s.write("docs/notes.md", "# Notes\n\nfine\nfine\nofﬁce\n")
            s.manifest(AUTHORED.format("notes.md") + SELF)
            code, out = s.run()
            self.assertEqual(code, 1, out)
            self.assertIn("line 5", out)

    def test_ordinary_typography_is_not_an_artifact(self):
        """Curly quotes, em dashes, accents and CJK are typed every day. A rule
        that flagged them would be turned off within a week."""
        with Scratch() as s:
            s.write("docs/notes.md",
                    "# Notes\n\nIt’s fine — Pokémon, ¥12,400 JPY, "
                    "≥44×44pt, 50–60 days, 小米.\n")
            s.manifest(AUTHORED.format("notes.md") + SELF)
            code, out = s.run()
            self.assertEqual(code, 0, out)


class TheCheckerIsItselfClean(unittest.TestCase):

    def test_the_checker_contains_no_literal_artifact_characters(self):
        """It has to be quotable in a document without failing rule 4 there."""
        with open(CHECK, encoding="utf-8") as f:
            body = f.read()
        found = sorted({hex(ord(c)) for c in body if c in guard.ARTIFACTS})
        self.assertFalse(found, f"literal artifacts in the checker source: {found}")

    def test_the_real_repository_passes(self):
        self.assertFalse(guard.check(), "the repository itself fails the gate")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheScopeIncludesFilesNotYetTracked(unittest.TestCase):
    """`inert / by_scope`, and the remedy the taxonomy demands for it: prove
    it can fail.

    Both audits read `git ls-files`, which returns TRACKED paths only. A
    document written this minute is untracked, and these checks run BEFORE the
    commit that would track it -- so they reported `clean` about a universe
    that excluded the file in question. Noted in ADR-0042, not fixed for three
    sessions, then reproduced verbatim in `no_unguarded_elevation`.
    """

    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _probe(self, relative, body):
        path = os.path.join(self.REPO, relative)
        self.assertFalse(os.path.exists(path), f"{relative} already exists")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_an_undeclared_doc_is_caught_before_it_is_tracked(self):
        from audit.checks import no_pdf_provenance
        self._probe("docs/_probe_undeclared.md",
                    "# A document nobody declared the provenance of\n")
        violations = no_pdf_provenance.check()
        self.assertTrue(
            any("_probe_undeclared" in str(v) for v in violations),
            "an untracked docs/ file was invisible to the provenance check")

    def test_a_payload_is_caught_before_it_is_tracked(self):
        from audit.checks import no_provider_data
        self._probe("audit/_probe_payload.json",
                    '{"card_uid": "x", "marketPrice": 9.99}\n')
        violations = no_provider_data.check()
        self.assertTrue(
            any("_probe_payload" in str(v) for v in violations),
            "an untracked payload was invisible to the data guard")

    def test_a_gitignored_payload_stays_out_of_scope(self):
        """`--exclude-standard` respects .gitignore, so a payload sitting in
        `raw/` -- where it belongs -- is still not scanned. Flagging it would
        train people to ignore this check, which is a slower way of turning it
        off."""
        from audit.checks import no_provider_data
        os.makedirs(os.path.join(self.REPO, "raw"), exist_ok=True)
        self._probe("raw/_probe_payload.json", '{"marketPrice": 9.99}\n')
        violations = no_provider_data.check()
        self.assertFalse(any("_probe_payload" in str(v) for v in violations))

    def test_rule_one_stays_tracked_only(self):
        """Its claim is `tracked at all means somebody used --force`. An
        untracked file under a forbidden path is the system working."""
        from audit.checks import no_provider_data
        source = open(os.path.join(self.REPO, "audit", "checks",
                                   "no_provider_data.py"), encoding="utf-8").read()
        self.assertIn("for f in tracked:", source)
        self.assertIn("TRACKED-ONLY ON PURPOSE", source)
