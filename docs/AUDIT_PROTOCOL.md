# Audit Protocol — WaFT Cards

> Place at `docs/AUDIT_PROTOCOL.md`. Run the full suite between every Claude Code session and before any signal is acted on with real money.

The design principle: **an audit that Claude Code runs on its own work is worth something; an audit that runs in CI on every commit is worth much more.** Layers 1–4 are automated and block merges. Layers 5–7 are periodic and human-gated.

---

## Layer 1 — Math correctness (automated, blocking)

`tests/test_ev_models.py`, `tests/test_indices.py`

**Golden fixtures** — hand-computed on paper, checked into the repo with the working shown in comments:
- Obviously-worth-grading card (high raw/10 multiple, high pop-implied gem rate)
- Obviously-not-worth-grading card (low multiple, cheap raw)
- A card sitting exactly at break-even (tests the boundary)
- JPY acquisition → USD sale, full FX round trip, exact to the cent
- HKD acquisition → GBP sale (your actual situation from September)
- A zero-sample-size input (must refuse, not extrapolate)
- A stale-config input (must warn)

**Property tests** — these catch classes of bug that examples miss:
```
EV decreases monotonically in acquisition cost
EV increases monotonically in P(target grade)
annualised_roi decreases as turnaround_days increases
break_even_p ∈ [0, 1] or the function returns "impossible at any probability"
sum(grade_probs) == 1.0 ± 1e-9
no calculator output contains a bare float where money is expected
fee stack applied exactly once — never zero times, never twice
```

That last one deserves its own paragraph. Double-applying or dropping a fee is the single most common error in this category of tool and it is invisible in the output. Test it explicitly, in both directions.

---

## Layer 2 — Data integrity (automated, blocking)

`audit/checks/integrity.py`, run after every ingestion cycle.

| Check | Condition | Severity |
|---|---|---|
| Snapshot gap | any tracked card with no snapshot in 48h | ERROR |
| Future observation | `observed_at > now()` or `observed_at < as_of` | FATAL |
| History mutation | any pre-existing row changed since last run (hash the table) | FATAL |
| Cross-source divergence | two sources disagree >30% on the same card/grade/day | WARN → review queue |
| Price discontinuity | >5σ move vs. that card's own 90d vol with no volume | WARN → review queue |
| Coverage regression | tracked-card count drops >2% day-over-day | ERROR |
| Naked money | any monetary column with null currency | FATAL |
| FX staleness | `fx_as_of` >24h older than the price it converts | ERROR |
| Pop regression | pop count for a grade decreases (should be monotone up) | WARN — usually a scrape error |
| Config staleness | `grading.yaml` or `fees.yaml` `effective_from` >60d old | WARN |

FATAL halts the pipeline. ERROR fails CI. WARN opens an entry in `docs/OPEN_ISSUES.md` automatically.

---

## Layer 3 — Identity resolution (automated, blocking)

`tests/test_resolver.py` against `tests/fixtures/labelled_200.json`.

- Precision ≥0.98, recall ≥0.90 — regression on either fails CI
- **EN/JP separation test**: for every card in the set that exists in both languages, assert distinct `card_uid`s and assert their price series are not correlated above 0.99 (which would indicate accidental merging)
- Collision test: no two distinct real cards share a `card_uid`
- Every fuzzy-resolved card with confidence <0.9 is excluded from screen output — asserted, not assumed
- Manual review queue depth reported; alert if >50

---

## Layer 4 — Look-ahead and leakage (automated, blocking)

**This is the layer that matters most.** The Smart Money Detector failure was a leakage failure, not a modelling failure.

`tests/test_lookahead.py`:
```
For 500 random (card_uid, evaluation_date) pairs:
    full_result = run_all_screens(card_uid, evaluation_date, db=full_db)
    truncated_db = db.filter(observed_at <= evaluation_date)
    trunc_result = run_all_screens(card_uid, evaluation_date, db=truncated_db)
    assert full_result == trunc_result   # byte-identical
```
Any divergence is a leak. Fails CI, no exceptions, no "it's only in the trend module."

`tests/test_backfill_exclusion.py`:
```
assert backtest universe contains zero rows with backfilled=True
assert every sentiment row's observed_at == its ingestion timestamp,
       not the source post's creation timestamp
```

`tests/test_survivorship.py`:
```
Cards delisted, errata'd, or reclassified must remain in the historical universe.
Assert the tracked-card set on date D, reconstructed from history, equals the set
that actually existed on D — not today's set filtered backwards.
```

Survivorship is the quiet one. If cards that went to zero silently drop out of your history, every backtest is fiction.

---

## Layer 5 — Statistical discipline (periodic, human-gated)

Runs only at Session 6 and any time the score is re-fit.

**Pre-registration.** `docs/hypotheses.md` entry committed *before* the backtest runs, containing: exact feature list, target definition, horizon, universe, the three benchmarks, success threshold, and the number of variants that will be tested. A backtest without a prior committed hash is not evidence and the audit marks it as such.

**Splits.** Purged and embargoed time-series CV. Embargo ≥ the target horizon (90 days), so a training fold never overlaps the forward window of an adjacent test fold. Final holdout untouched until one single evaluation.

**Target.** Excess return vs. the game-level index. Never raw return. In a hobby-wide rally, raw-return targets make every model look brilliant.

**Benchmarks — beat all three or the score stays off:**
1. Equal-weight z-score composite (the null that a naive combination works just as well)
2. 90-day momentum alone (the null that you've built an expensive momentum proxy)
3. Random ranking (the null that you've built nothing)

**Multiple testing.** Benjamini-Hochberg across every variant tested. Report the denominator. If you tested forty feature combinations and one has p=0.03, you have found nothing.

**Failure handling.** A failed test is written into `docs/hypotheses.md` as a completed result and the score stays disabled. **Re-tuning and re-running against the same holdout is forbidden** — that is precisely how the last one broke. One pre-registration, one test, one answer. If you want another shot, you need new data, not new parameters.

---

## Layer 6 — Live paper record (continuous, the only real proof)

Everything above tests whether the code does what you meant. This tests whether what you meant was right.

- Every alert writes an immutable `alert_ledger` row at fire time
- Forward-scored automatically at +7d / +30d / +90d against the game index
- Surfaced on the Track Record screen — hit rate, median excess return, worst five calls
- **Do not act on any screen with real money until it has 50 scored alerts.** At n=20 you are reading noise. This will feel slow. It is the cheapest tuition available.

Monthly review question, written into `docs/audits/`: *for each screen, is the excess return distribution distinguishable from zero, and has the sample got large enough to say so?*

---

## Layer 7 — Adversarial red team (per phase, human-triggered)

Run this prompt in a **fresh Claude Code session** with no context from the build. Fresh context is the point — a session that just wrote the code is the worst possible auditor of it.

```
You are auditing a codebase you did not write and have no stake in. Assume it is
wrong. Your job is to find the errors, not to confirm the design.

Read docs/GOAL.md, docs/AUDIT_PROTOCOL.md, then the code.

Produce docs/audits/redteam_{date}.md with findings ranked by severity
(FATAL / HIGH / MEDIUM / LOW), each with: the exact file and line, a concrete
reproduction, the financial consequence in dollars if I traded on it, and the fix.

Hunt specifically for:

1. Any path where a fee, tax, shipping cost or FX conversion is applied twice or
   zero times. Trace one full raw-to-sold calculation by hand and compare to the code.
2. Any monetary value that loses its currency tag anywhere in the pipeline. Grep for
   bare float arithmetic on anything that could be money.
3. Any place a probability is used where the conditional probability is required —
   especially P(10) for a card that already graded 9.
4. Any use of pop-report gem rate that has not had the submission-selection haircut
   applied, or has had it applied twice.
5. Any query that could read a row with observed_at later than the evaluation
   timestamp. Check the shared query wrapper AND every place that bypasses it.
6. Any sentiment or trend value whose timestamp is the source post's creation time
   rather than our ingestion time.
7. Any screen or model that would produce a signal from a sample size below its
   stated minimum, or that reports a sample size it did not actually use.
8. Any place EN and JP printings could merge — in the resolver, in a join, in an
   aggregation, in a UI grouping.
9. Any hardcoded grading fee, tier, or turnaround that should be reading dated config.
   PSA changed tier pricing in Feb 2026 and paused Value tiers in June 2026; anything
   hardcoded is already wrong.
10. Any number displayed in the UI without a source, an as-of, or — where applicable —
    its assumption chip.
11. Performance: any function called per-card in a loop that hits the database or an
    API. Profile the screen run and report anything superlinear.
12. Silent failure: any except block that swallows, any default that masks a missing
    value, any fallback that substitutes a plausible number for an absent one.

For each finding, state whether it would have been caught by an existing test. If not,
write the test that would catch it and add it to the suite.

Do not fix anything. Report only. I will triage.
```

Findings triage into `docs/OPEN_ISSUES.md` with severity, owner and target session.

---

## Gate summary

| Layer | Frequency | Blocks | Owner |
|---|---|---|---|
| 1 Math | every commit | merge | CI |
| 2 Integrity | every ingestion | pipeline | CI |
| 3 Resolution | every commit | merge | CI |
| 4 Look-ahead | every commit | merge | CI |
| 5 Statistics | Session 6 + refits | score enablement | you |
| 6 Live record | continuous | real money | you |
| 7 Red team | per phase | phase advance | you |

---

## Known-fragile register

Track these in `docs/OPEN_ISSUES.md` from day one. They are not bugs — they are places where the system is honestly uncertain, and they need periodic re-examination rather than a fix.

1. **Submission selection haircut** — a guess until calibrated against your own submission outcomes. Log every card you actually submit and its result; after ~30 submissions you have a real number.
2. **Regrade conditional prior** — same, and harder, because you'll submit few of these.
3. **Pull rates** — community-sourced, frequently wrong, occasionally deliberately wrong.
4. **Riftbound thin history** — the game launched late 2025. There is not enough price history for any statistical claim. Treat Riftbound signals as exploratory only, and say so in the UI.
5. **JP market coverage** — no clean API. Whatever you build for SNKRDUNK/Mercari is fragile and will break when they change their markup.
6. **Grade-level comp thinness** — most cards outside the top few hundred have single-digit graded sales per quarter. The minimum-sample suppression is doing enormous work; check what fraction of your universe it excludes.
