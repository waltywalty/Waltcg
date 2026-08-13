# CLAUDE.md — WaFT Cards

Private, single-user TCG opportunity engine. One Piece TCG (EN + JP), Pokémon TCG (EN + JP), Riftbound (EN).

**Read `docs/GOAL.md` at the start of every session.** It defines done. `/goal` works toward it and stops at gates.

---

## Working agreement

- Stop at phase gates, not at token limits. A half-finished phase is worse than a finished smaller one.
- Never mark something done that hasn't passed its gate.
- When a data source can't supply a field, **delete the field**. Don't stub it, don't TODO it, don't fill it with a plausible default.
- When you're uncertain about an assumption, register it in `contracts/assumptions.json` and surface it in the UI. Never bury it in code.
- Report what's fragile at the end of every session, unprompted.
- If a task would require breaking a non-negotiable below, stop and ask.

---

## Non-negotiables

1. **No look-ahead.** Any value used at an evaluation timestamp must have `observed_at <= evaluation_timestamp`. Enforced by `tests/test_lookahead.py` on 500 pairs. Never bypass the shared query wrapper.
2. **No naked money.** Every monetary value is `{amount, currency, fx_rate_used, fx_as_of}`. No bare floats. Ever.
3. **EN and JP printings are different cards.** Different `card_uid`, different price series, never merged in a join, an aggregation, or a UI grouping.
4. **Grading fees, tiers and turnaround live in dated config**, never in code. PSA changed tier pricing in Feb 2026 and paused its Value tiers in June 2026; anything hardcoded is already wrong.
5. **Pop-report gem rate is biased upward.** People submit their best copies. Always apply `assumptions.submission_selection_haircut` to P(10) for a randomly-acquired raw card — once, never twice.
6. **P(10 | already graded 9) is not the base gem rate.** Model B uses a conditional prior and refuses to output a number without an explicit user condition read.
7. **The composite score ships disabled** (`SCORE_ENABLED=false`) until it beats all three benchmarks out-of-sample after Benjamini-Hochberg correction, against a pre-registration committed *before* the backtest ran. No re-tuning against the same holdout.
8. **The Track Record screen is permanent.** It cannot be removed, collapsed, or made optional. The worst five calls are always visible.
9. **No synthetic data past P1.** Fixtures exist to design against; delete them from the runtime path.
10. **Private repo.** Several upstream sources restrict redistribution. No public API, no publishing, no resale.

---

## Conventions

**Identity**
```
card_uid = {game}:{set_code}:{number}:{variant}:{language}
game     ∈ {optcg, pkmn, riftbound}
language ∈ {EN, JP}
```
External IDs live in `card_xref` with `confidence` and `resolved_by ∈ {exact, fuzzy, manual}`. Anything fuzzy below 0.9 confidence is excluded from all signals.

**Time**
- `as_of` — the date the value refers to
- `observed_at` — when we saw it
- `observed_at >= as_of` and `observed_at <= now()`, always, enforced at the DB layer
- History is append-only. Corrections are new rows with a `supersedes` reference. Nothing is ever UPDATEd or DELETEd.

**Uncertainty**
Every derived value carries `{value, source, as_of, confidence, sample_size}` with `confidence ∈ {high, medium, low, unvalidated}`. Anything downstream of a registered assumption carries `assumption_ids`.

**Output shape**
The API serves exactly `contracts/screens.schema.json`. A response that fails validation is a 500, not a warning.

---

## Layout

```
contracts/   schema, assumptions registry, fixtures, source map
ingest/      one adapter per source, uniform interface, raw response cache
store/       point-in-time DB, append-only, invariants as constraints
resolve/     card identity + manual review queue
engine/      ev/ (models A-E), screens/, index.py, obtainment.py, sourcing.py
score/       composite — disabled by default
backtest/    purged CV, embargo, holdout, BH correction
alerts/      rules, immutable ledger, forward scoring
api/         FastAPI, schema-validated
web/         front end from Claude Design handoff
audit/       integrity checks
config/      grading.yaml, fees.yaml, crossover_rules.yaml, sentiment.yaml — all dated
docs/        GOAL.md, AUDIT_PROTOCOL.md, DATA_SOURCES.md, OPEN_ISSUES.md,
             hypotheses.md, decisions.md, audits/
```

---

## Session ritual

Start: read `docs/GOAL.md`, `docs/OPEN_ISSUES.md`, and the previous `docs/audits/session_N.md`.

End: run the full audit suite, update `OPEN_ISSUES.md` with severity tags, write `docs/audits/session_N.md` covering what shipped / what's assumed / what's fragile / what the next session depends on, commit.

---

## Known-fragile — treat with suspicion, don't "fix"

- Submission selection haircut — a guess until calibrated against my own submission results
- Regrade conditional prior — same, with a smaller sample coming
- Pull rate estimates — community-sourced and often wrong
- Riftbound history — game launched late 2025; too short for statistical claims. Exploratory only, and the UI must say so.
- JP market coverage — no clean API; manual entry for v1
- Grade-level comp thinness — most of the universe has single-digit graded sales per quarter; check what fraction the minimum-sample filter excludes

---

## Context

I'm a finance student, ex-intern on an asset management sales desk, moving to London in September for an MSc in Banking and Digital Finance. I trade futures and build my own dashboards. I've had a signal falsified by my own backtest before and I'd rather that happen again in `docs/hypotheses.md` than happen with real money. Be direct about what doesn't work. A validated negative result is a good session.
