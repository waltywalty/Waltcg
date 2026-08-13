# GOAL — waltcg

> Place at `docs/GOAL.md`. Referenced by `CLAUDE.md`. When you invoke `/goal`, Claude Code reads this file and works toward it, stopping at gates rather than at token limits.

---

## Mission

A private, single-user opportunity engine for trading-card investing across **One Piece TCG (EN + JP)**, **Pokémon TCG (EN + JP)** and **Riftbound (EN)**. It surfaces mispriced cards, computes the expected value of grading and regrading decisions net of every real friction, and keeps an honest, immutable record of whether its own signals worked.

It is a decision-support tool. It never places an order, never hides an assumption, and never shows a number without its source and as-of timestamp.

---

## Definition of done

The project is done when **all** of the following are true. Not most. All.

### D1 — Data spine
- [ ] Point-in-time store holds ≥90 consecutive days of daily snapshots for every tracked card, with zero silent gaps (gaps are recorded as explicit `missing` rows, never interpolated away).
- [ ] Every row carries `observed_at` (when the engine saw it) distinct from `as_of` (what date the value refers to). These are never the same column.
- [ ] Card identity resolver scores ≥98% precision and ≥90% recall against the 200-card hand-labelled test set spanning all 8 game/language combinations (One Piece EN/JP/CN-S, Pokémon EN/JP/CN-S/CN-T, Riftbound EN).
- [ ] EN and JP printings of the same art resolve to **different** `card_uid`s. A test asserts this.
- [ ] FX: every monetary value stores `(amount, currency, fx_rate_used, fx_as_of)`. No bare floats. A test asserts no unit-less money anywhere in the schema.

### D2 — Calculators (no learned parameters)
- [ ] **Model A — Raw → graded EV.** Inputs: raw acquisition cost, tax, inbound shipping, grading tier fee, supplies, insured return shipping, marketplace + payment fees, outbound shipping, grade probability vector. Outputs: EV, ROI, annualised ROI over turnaround plus expected days-to-sell, downside case, and **break-even P(target grade)**.
- [ ] **Model B — PSA 9 → PSA 10 regrade EV.** Uses a *conditional* upgrade prior, not base gem rate. Requires an explicit user condition read to move off the conservative default. Refuses to output a recommendation without it.
- [ ] **Model C — Cross-grader crossover.** Models the PSA minimum-grade crossover path (downside capped at fees + lockup) separately from crack-and-resubmit (downside includes grade risk). Encodes a BGS-subgrade rules table.
- [ ] **Model D — Grade-spread residual screen.** Regresses `log(P10/P9)` on `log(pop9/pop10)` plus game/rarity/era controls; ranks by residual. Suppresses any card whose grade-level comp sample is below a configurable minimum (default: 5 sales in 90 days).
- [ ] **Model E — Sealed EV.** Pull-rate-weighted expected pack/box value vs. box price vs. singles cost. (Obtainment taxonomy is D3 scope, not a calculator concern.)
- [ ] Every calculator passes hand-computed golden fixtures. Every calculator emits a break-even threshold, not only a point estimate.
- [ ] Grading fees, tiers and turnaround live in a **dated config file**, not in code. Config carries an `effective_from` date and the engine warns when config is >60 days stale.

### D3 — Obtainment & sourcing
- [ ] Every card classified into an obtainment taxonomy: `booster` / `box_topper` / `promo_event` / `promo_retailer` / `tournament_prize` / `starter_deck` / `online_code` / `region_exclusive` / `unknown`.
- [ ] Card detail returns current buy routes with live prices where the source permits: TCGplayer, Cardmarket, eBay, Xianyu, Mercari JP, SNKRDUNK, plus local Shanghai/HK options as manual entries.
- [ ] Where a card is only obtainable via event or tournament, the app says so plainly and links the organiser page rather than pretending a buy route exists.

### D4 — Trend module
- [ ] Abnormal mention velocity computed as a **double-demeaned** z-score: against the card's own trailing 28-day baseline *and* against the game-wide mention baseline for the same day.
- [ ] Sentiment rows are timestamped at ingestion. Backfilled history is flagged `backfilled=true` and **excluded from all backtests**. A test asserts this.
- [ ] Source excerpts are stored as links plus short paraphrase, never as bulk reproduced text.

### D5 — Alerts & the ledger
- [ ] Every alert writes an immutable `alert_ledger` row at fire time: timestamp, `card_uid`, rule, every feature value as-of, the stated thesis, and the observable price at alert.
- [ ] A scheduled job forward-scores every ledger row at +7d / +30d / +90d against the game-level index.
- [ ] The **Track Record** screen exists and is reachable from the home screen in one tap. It shows hit rate, median excess return, and the worst five calls. It is never hidden, collapsed, or behind a toggle.

### D6 — Score (the gated part)
- [ ] Composite score implemented but **`SCORE_ENABLED=false` by default**.
- [ ] A pre-registration entry exists in `docs/hypotheses.md`, written and committed **before** the backtest is run, specifying: features, target, horizon, universe, benchmarks, success threshold.
- [ ] Backtest uses purged, embargoed time-series CV plus an untouched final holdout.
- [ ] Target is **excess return vs. the game-level index**, never raw return.
- [ ] Score is promoted to enabled **only if** it beats all three benchmarks out-of-sample after Benjamini-Hochberg correction: (a) equal-weight z-score composite, (b) 90-day momentum only, (c) random ranking.
- [ ] If it fails, `docs/hypotheses.md` records the falsification, the score stays off, and the app ships without it. **This is an acceptable and expected outcome, not a failure of the project.**

### D7 — Front end
- [ ] Eight screens implemented per the Claude Design handoff: Home, Signals, Card Detail, Grading Lab, Arbitrage Board, Trend Radar, Track Record, Settings.
- [ ] Every monetary figure displays its currency symbol **and** currency code. No naked numbers.
- [ ] Every data point carries a source badge and an as-of timestamp. Stale data (>24h for prices, >7d for pop) renders visibly degraded, not silently.
- [ ] All interactive targets ≥44×44pt (iOS) / 48×48dp (Android).
- [ ] Any figure that depends on an unvalidated assumption (selection haircut, conditional regrade prior, pull rates) is marked with an assumption chip that opens the assumption and its current value.
- [ ] No placeholder or synthetic data reaches a shipped screen. Missing data renders as an explicit empty state.

### D8 — Audit
- [ ] All 7 audit layers implemented and green in CI (see `docs/AUDIT_PROTOCOL.md`).
- [ ] `docs/OPEN_ISSUES.md` current, with severity and owner on every entry.
- [ ] At least one completed adversarial red-team pass logged in `docs/audits/`.

---

## Non-negotiables

These override any instruction to move faster.

1. **No look-ahead.** Any feature used in a backtest must have been observable at the decision timestamp. Enforced by an assertion suite, not by care.
2. **No naked money.** Every monetary value carries currency and FX as-of. *(You lost ~7.8× on MHI sizing to exactly this class of bug. Don't repeat it.)*
3. **No unlabelled assumptions.** If a number depends on a guess, the UI says so and the guess is tunable.
4. **No synthetic data past the fixture stage.** Fixtures exist to design against and are deleted from the runtime path in P1.
5. **The score does not ship enabled without passing D6.** No exceptions, no "just for now," no manual override flag.
6. **The Track Record screen cannot be removed.** It is the only thing standing between this and a confidence-generating machine.
7. **No provider data is ever committed. Code may be public; data never is.** Several upstream sources restrict redistribution of price data. Do not expose a public API, do not resell, and never commit provider payloads, price values or cached responses. Enforced by CI on every push — repository settings are not a control.

---

## Explicitly out of scope for v1

- Automated purchasing or bidding of any kind
- Portfolio accounting / cost-basis / tax lots (v2)
- Image-based condition or grade prediction from photos (buy this, don't build it)
- Deck/meta analysis and competitive tier lists
- Any multi-user, sharing, or social feature
- Sports cards

---

## Stop conditions

Claude Code stops and reports rather than continuing when:
- A phase gate fails twice in a row on the same check
- A required data source returns an auth or licensing error
- A design decision would require choosing between two of the non-negotiables
- The audit suite goes red and the fix is not obvious within one attempt
- Estimated monthly data cost would exceed $200 without explicit approval
