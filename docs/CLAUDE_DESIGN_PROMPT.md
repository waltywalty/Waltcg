# waltcg — design brief

Paste everything below the line into Claude Design, after starting from the mobile app template.

---

I’m designing **waltcg**, a private iOS-first tool I use to decide which trading cards to buy and which to send for grading. Single user — me. Not a product, no onboarding, no marketing surface, no sign-up. Design for someone standing in a card shop in Shanghai with a card in one hand and forty seconds to decide.

The backend exists. Read `contracts/screens.schema.json`, `contracts/fixtures/*.json` and `contracts/assumptions.json` from `github.com/waltywalty/Waltcg` and design against those exact fields. If you can’t reach the repo, stop and tell me — I’ll paste them. Do not design against guessed field names; the schema was built specifically to delete every field we couldn’t source, and inventing one puts an empty box on a screen.

## What it computes

Four things, in descending order of how much I trust them:

1. **Grading expected value.** Given a raw card’s price, current grading fees, turnaround, marketplace fees, shipping and FX, what probability of a gem-mint grade would I need for this submission to break even. The headline output is that probability, not a dollar figure.
2. **Regrade and crossover EV.** Whether cracking a PSA 9 for a 10, or crossing a CGC/BGS slab into PSA, clears its costs.
3. **Grade-spread screening.** Where the price gap between grades looks out of line with the population gap.
4. **Interest trend.** Whether discussion of a card is rising abnormally. Weakest of the four — the data source isn’t fully approved yet.

And a fifth thing that keeps the rest honest: did the last hundred calls actually work.

## The constraint that shapes everything: coverage is uneven

This is the most important thing about the design. The app covers eight game/language combinations and they are not equally supported:

| Combination | Catalog + price | Population | What works |
|---|---|---|---|
| Pokémon EN, Pokémon JP | yes | yes | everything |
| One Piece EN, Riftbound EN | yes | none | prices, screener, and grading EV only if I supply the grade probability myself |
| One Piece JP, Chinese ×3 | none | none | manual entry only — I type the price in by hand |

No source publishes population data outside Pokémon, and the catalog has no One Piece Japan entry at all. These aren’t edge cases to tuck into an error state — **two of the three games live in the middle row and four of the eight combinations live in the bottom row.** Design for them as first-class.

Practically this means the grade ladder often has no population weight, the Grading Lab often needs me to enter my own grade estimate, and a meaningful share of cards have hand-typed prices with a manual as-of date that ages differently from API data.

## Refusal is a first-class state, not an error

The engine is built to refuse rather than guess. If a marketplace fee is unconfigured, if a card has no comps for a grade the model needs, if I haven’t given a condition read on a regrade — it returns a refusal object naming exactly what’s missing, not a number with a warning attached.

This is deliberate, and it’s the behaviour I most need the design to respect. A refusal is useful output: it tells me precisely which of nine gaps to go fill. So it needs to look like a finished, purposeful state with a clear next action — not a greyed-out failure, not an empty skeleton, not a toast. Currently Model A names nine missing inputs on a real card. That screen should feel like a checklist, not a crash.

Related: several numbers depend on assumptions I’ve explicitly marked unvalidated — the submission-selection haircut, the regrade prior, pull rates, and the empirical-Bayes prior strength. Anything downstream of one carries an affordance that opens the assumption, shows its current value and source confidence, and lets me change it. Visible, not nagging.

## The signature element

A **grade ladder**: a vertical stack of rungs — Raw, 8, 9, 10 — where horizontal extent encodes price and rung weight encodes population. You read scarcity and value in one glance, and the gap between the 9 and 10 rungs is literally the trade.

**Design its degraded form with equal care**, because for One Piece and Riftbound there is no population at all — the ladder shows price rungs with no weight. That version will appear as often as the full one. It should look intentional and still informative, not like the real thing with something broken off.

Three sizes: full-bleed on Card Detail, compact in list rows, single-line in alerts.

## Aesthetic

Between a trading terminal and a card binder. Dense, dark, precise, with one place where the card art is allowed to breathe. The subject supplies material: foil treatments, rarity stamps, set symbols, the typography of set codes (`OP01-121`, `215/203`, `csv9.5C`), the physical vocabulary of centering and corners and surface.

Three looks I’ve seen too many times: cream background with high-contrast serif and terracotta accent; near-black with a single acid-green accent; broadsheet layout with hairline rules and no border radius. Spend the risk elsewhere.

## Screens

**1. Home** — Portfolio value with day change. Active alerts. Top movers with inline grade ladders. One-tap to Track Record, never buried.

**2. Signals** — Ranked opportunity feed, filterable by play type: raw → 10, 9 → 10, crossover, grade gap, trending. Each row shows a headline number that differs by play type — a break-even probability, a spread residual, a velocity z-score. Make heterogeneous headline numbers still scan as one list. Show sample size and confidence per row.

**3. Card Detail** — Grade ladder as hero with art behind it. Price history with raw/9/10 overlaid. Population pyramid where population exists. Obtainment panel — booster, promo, tournament prize, region exclusive. Buy routes with landed cost. A language selector across EN / JP / CN-S / CN-T where printings exist; these are separate cards with separate prices and must never visually merge.

**4. Grading Lab** — Input acquisition cost, grading tier, and my condition read (centering %, corners, edges, surface). Primary output is a break-even probability rendered against the population-implied probability, so the gap between what I need and what’s likely is the visual. Two modes: population-derived (Pokémon) and manual grade estimate (everything else). Secondary: dollar EV, annualised ROI across a 50–60 business day turnaround plus time to sell, and the downside if it returns an 8.

**5. Manual Entry** — For One Piece JP and the three Chinese printings I type prices in myself from Xianyu, Taobao, Mercari JP and SNKRDUNK. Fast, phone-friendly, capturing price, currency, source, condition and date. These rows must be visually distinguishable everywhere they later appear — same engine, different provenance, and they age differently.

**6. Arbitrage Board** — Cross-grader and cross-market spreads sorted by net-of-friction margin. Gross and net columns with the friction stack expandable — fees are banded and tiered, not flat percentages, so the expansion has to show real structure. Visually separate the PSA minimum-grade crossover path (downside capped at fees) from crack-and-resubmit (full grade risk). Pokémon only; say so.

**7. Track Record** — Every alert ever fired and what happened. Hit rate at 7/30/90 days, median excess return against the game index, and the five worst calls, permanently visible, never collapsed. Design this with the care of a hero screen. If it looks like an admin panel I’ll stop reading it, and then the whole app becomes a confidence machine.

**8. Settings** — Fee schedules per marketplace, grading tiers, FX, the assumption registry with editable values and confidence levels, alert rules. Assumptions get a real screen, not a nested list item.

## Non-negotiable display rules

- **Currency symbol and code on every monetary value.** `¥12,400 JPY`, not `¥12,400`. I once lost a factor of 7.8 in position sizing to an unlabelled currency. Design for three currencies in one row.
- **Source and as-of on every data point.** A compact badge appearing hundreds of times — small, quiet, still readable.
- **Stale renders visibly degraded** — >24h prices, >7d population. A material change in appearance, not an icon.
- **Provisional values look different from verified ones.** Grading fees are currently sourced from secondary summaries pending verification against PSA’s own page; that distinction has to be visible where it affects a number.
- **Tap targets ≥44×44pt**, including in dense rows. Especially there.
- **Tabular figures throughout.** Every numeral column aligns.
- **No synthetic data in any state.** Missing data gets a designed empty state naming which source failed and when it last succeeded.
- **Dark by default**, legible under card-shop fluorescent light.
- Design loading, empty, refusal, error and stale states for all eight screens. In this app the degraded states are load-bearing.

## How to proceed

**First message: no screens.** Give me two directions — each with 4–6 named hex values, a display face, a body face, a tabular-figure face for numerals, a layout concept, and your take on the grade ladder in both its full and no-population forms. I’ll pick one, then you build.

**Then:** all eight screens, all five states each, a component set (grade ladder ×3, confidence badge, source/as-of badge, assumption chip, money value, play-type tag, manual-entry marker, signal row), an interactive prototype covering Home → Signals → Card Detail → Grading Lab and Home → Track Record, and a design system I can pull into Claude Code with `/design-sync`.

Flag anywhere the design assumes data behaviour the schema doesn’t guarantee.
