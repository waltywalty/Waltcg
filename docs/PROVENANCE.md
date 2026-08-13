# Provenance of documents under `docs/`

Every Markdown file under `docs/` declares where its text came from. Enforced by
`audit/checks/no_pdf_provenance.py`, which fails the build on any undeclared
document, and by CI on every push.

This exists because a PDF that gets machine-extracted into Markdown lands in the
repository reading exactly like something that was written there. Extraction is
lossy — ligatures, dropped columns, reordered table cells, unmapped glyphs — and
a file that does not say it was extracted cannot be weighed by anyone reading it
later. The manifest makes the conversion a thing you declare rather than a thing
someone has to guess.

## Origins

| Origin | Meaning |
|---|---|
| `authored` | Written directly in the repository. No external source document. |
| `verbatim-text` | Supplied as text — pasted into chat, or uploaded already in a text format — and copied across with no conversion step. |
| `pdf-extraction` | Machine-extracted from a PDF. **Requires a complete source note**: source file, extraction date, tool, and verification method. |

`pdf-extraction` is the only origin that should ever be rare. The standing
convention (CLAUDE.md § Conventions → *Document handoffs*) is that source
documents arrive as pasted text.

## The register

| File | Origin | Source | Extracted on | Tool | Verification |
|---|---|---|---|---|---|
| `docs/AUDIT_PROTOCOL.md` | verbatim-text | uploaded `04_AUDIT_PROTOCOL.md` | — | — | byte-identical to the upload (`cmp`, 0 differences) |
| `docs/CLAUDE_DESIGN_PROMPT.md` | pdf-extraction | `03b_CLAUDE_DESIGN_PROMPT_v2.pdf`, 82,428 bytes | 2026-08-13 | pdfminer.six 20260107, `extract_text` | Both sides normalised to one token stream (Markdown syntax stripped, whitespace collapsed, code-span padding removed symmetrically) and compared with `cmp`: 9,306 bytes of prose identical in order; the coverage table identical as a word multiset, compared that way alone because the PDF lays it out column-major and Markdown row-major. Method and its limits in ADR-0004. |
| `docs/DATA_SOURCES.md` | verbatim-text | uploaded `05_DATA_SOURCES.md` | — | — | added byte-identical, then amended by reconciliation decision 1 (repo-visibility rescope): 4 lines changed, in git history |
| `docs/GOAL.md` | verbatim-text | uploaded `01_GOAL.md` | — | — | added byte-identical, then amended by reconciliation decisions 1, 2 and 4 (visibility rescope, language enum, name): 10 lines changed, in git history |
| `docs/PROVENANCE.md` | authored | — | — | — | — |
| `docs/decisions.md` | authored | — | — | — | — |

Two documents outside `docs/` came from uploads and are recorded here for
completeness, though the check does not scope to them: `CLAUDE.md` (uploaded as
text, then amended by decisions 1, 2 and 4 — 6 lines) and `README.md` (authored,
replacing a `README.pdf` that was deleted for the reason this file exists).

## What the check cannot tell you

It cannot detect a *clean* extraction declared as pasted text. The artifact rule
catches mangling, not derivation — a PDF whose text layer converts perfectly
produces Markdown indistinguishable from typed Markdown, and no static check
will separate them. What the manifest guarantees is that no document can enter
`docs/` without an origin being written down. Silence is impossible; a false
declaration is not.

The artifacts it does catch are conclusive rather than heuristic: typographic
ligatures (U+FB00–FB06), soft hyphens, zero-width characters, replacement
characters, form feeds, and `(cid:N)` glyph-id sequences. None of these are
produced by typing. Each one means a passage is not the source text.
