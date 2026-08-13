# Claude Design — the brief

**Before you paste:** finish Claude Code Session 0. Then upload `contracts/screens.schema.json`, `contracts/assumptions.json` and all of `contracts/fixtures/*.json` into the Claude Design project. Start from the **mobile app** template.

Paste everything below the line as one message.

---

I'm designing **WaFT Cards**, a private iOS-first app I use to make buying and grading decisions on trading cards. Single user — me. Not a product, not a marketplace, no onboarding flow, no marketing page. Design for someone who opens this on a phone in a card shop in Shanghai with a card in his other hand and forty seconds to decide.

I've uploaded the real data contract and fixtures. **Design against those exact fields.** If a screen needs something the schema doesn't have, tell me instead of inventing it — the field probably doesn't exist because the data isn't gettable.

## What the app actually does

It tracks singles across One Piece TCG (English and Japanese), Pokémon TCG (English and Japanese) and Riftbound (English), and answers four questions:

1. Is this card mispriced relative to how scarce a high grade is?
2. If I buy this raw and send it to PSA, what probability of a 10 do I need for it to work?
3. Is there a cheaper slab from another grader I could cross into PSA profitably?
4. Is something starting to trend before it's priced in?

And a fifth, which is the one that keeps me honest: **did the last hundred things it told me actually work?**

## Design direction

Two constraints before aesthetics.

**Constraint one: every number on screen is uncertain, and the design has to say so without being timid about it.** Confidence, sample size, staleness and source are not footnotes here — they're primary data. A price built on three sales and a price built on three hundred should not look the same. A pop-report figure from last week and a market price from four minutes ago should not look the same. Find a visual language for uncertainty that is calm and structural rather than a wall of warning triangles.

**Constraint two: several key numbers depend on assumptions I've explicitly flagged as unvalidated** (see `assumptions.json` — the selection haircut, the regrade prior, pull rates). Anything downstream of one needs an affordance that opens the assumption, shows its current value, and lets me change it. This has to be visible but not nagging.

**The signature element — build the whole app around this.** A **grade ladder**: a vertical stack of rungs, one per grade — Raw, 8, 9, 10 — where each rung's horizontal extent encodes price and its weight or density encodes population. You read scarcity and value in one glance, and the gap between the 9 rung and the 10 rung is literally the trade. This motif appears at three sizes: full-bleed on Card Detail, compact in list rows, and as a one-line sparkline-equivalent in alerts. Make it beautiful and make it the thing the app is remembered for. Everything else stays quiet around it.

**Aesthetic.** Somewhere between a trading terminal and a card binder — dense, dark, precise, but with one place where the card art is allowed to actually breathe. The subject's own world gives you material: foil treatments, rarity stamps, set symbols, the specific typography of set codes (OP09-001, 186/086), the physical vocabulary of centering and corners and surface.

Three looks I've seen too many times and don't want: cream background with high-contrast serif and a terracotta accent; near-black with a single acid-green accent; broadsheet layout with hairline rules and zero border radius. If you land on one of those, spend the risk somewhere else.

**Propose before you build.** Give me a compact token system first — 4–6 named hex values, a display face, a body face, a tabular-figures utility face for all the numerals (non-negotiable: every number in this app is compared vertically against another number), a layout concept, and your take on the grade ladder. Show me two directions. I'll pick, then you build.

## The eight screens

**1. Home** — Portfolio value with day change. Alert count. Top three movers with grade ladders inline. One-tap access to Track Record — that link is never buried.

**2. Signals** — Ranked opportunity feed. Filterable by play type: *raw → 10*, *9 → 10*, *crossover*, *grade gap*, *thin float*, *trending early*. Each row: card, thumbnail, play type, the headline number for that play type (which differs per type — a break-even probability for grading plays, a spread residual for gap plays, a velocity z-score for trend plays), sample size, confidence. Design the row so heterogeneous headline numbers still scan as a single list.

**3. Card Detail** — The hero is the grade ladder, full-bleed, with card art behind it. Below: price history with raw/9/10 as three overlaid series, population pyramid, obtainment panel (how this card enters the world — booster, promo, tournament prize, region exclusive), and buy routes with landed cost including shipping to my region. Language toggle for EN/JP printings, which are separate cards with separate prices and must never be visually merged.

**4. Grading Lab** — The calculator. Input acquisition cost, grading tier, my own condition read (centering %, corners, edges, surface). **The primary output is a break-even probability, not a dollar EV** — "you need a 63% chance of a 10 for this to work; the population implies 41% before the selection haircut." Design that as a dial or gauge against the pop-implied probability, so the gap between what you need and what's likely is the visual. Secondary: dollar EV, annualised ROI accounting for a 50–60 business day turnaround, and the downside case if it comes back an 8.

**5. Arbitrage Board** — Cross-grader and cross-market spreads, sorted by net-of-friction margin. Two-column: gross spread and net spread, with the friction stack (fees, shipping, FX, tax) expandable. Crossover plays need a clear visual distinction between the PSA minimum-grade path (downside capped at fees) and crack-and-resubmit (full grade risk). Those are different trades and must not look alike.

**6. Trend Radar** — Abnormal mention velocity across Reddit, YouTube and search interest. Show the double-demeaned score, not raw mentions, and make the distinction legible: a card can be loudly discussed while being *less* discussed than the game as a whole. Source excerpts as links with short summaries.

**7. Track Record** — Every alert the app has ever fired, and what happened. Hit rate at 7/30/90 days, median excess return against the game index, and **the five worst calls, permanently visible, never collapsed**. This screen is the reason I'll trust the others. Design it with the same care as the hero screen, not as an afterthought settings page. If it looks like an admin panel, I'll stop reading it, and if I stop reading it the whole app becomes a confidence machine.

**8. Settings** — Fee schedules per marketplace, grading tier config, FX handling, the assumption registry with editable values, alert rules, and my aesthetic-rating scale. Assumptions get a real screen, not a nested list item.

## Non-negotiable interaction and display rules

- **Every monetary value shows currency symbol AND code.** `¥12,400 JPY`, not `¥12,400`. I once lost a factor of 7.8 in position sizing to an unlabelled currency and I'm not doing it twice. Design for the case where three currencies appear in one row.
- **Every data point carries source and as-of.** Design a compact badge; it appears hundreds of times so it has to be small and quiet and still readable.
- **Stale data renders visibly degraded** — >24h for prices, >7d for population. Not a warning icon. A material change in how it looks.
- **Tap targets ≥44×44pt.** Including in the dense list rows. Especially in the dense list rows.
- **Tabular figures everywhere.** Every numeral column aligns.
- **No fake data in any screen state.** Missing data gets a designed empty state that says which source failed and when it last succeeded.
- Dark by default. Legible at arm's length under card-shop fluorescent lighting.
- Design the loading, empty, error and stale states for all eight screens. In this app the degraded states are load-bearing, not edge cases.

## Deliverables

1. Two design directions with token systems, then the chosen one built out
2. All eight screens, mobile, all four states each
3. A component set: grade ladder (three sizes), confidence badge, source/as-of badge, assumption chip, money value, play-type tag, signal row
4. An interactive prototype covering: Home → Signals → Card Detail → Grading Lab → back, and Home → Track Record
5. A design system I can pull into Claude Code with `/design-sync`

When it's done I'll hand it to Claude Code, so keep components clean and consistently named, and note anywhere the design assumes data behaviour the schema doesn't guarantee.
