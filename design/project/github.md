repo: waltywalty/Waltcg
branch: main
path: contracts

## Last sync

date: 2026-08-14T09:14:00Z

### Updated in this project

- Clickable prototype built (`Waltcg Prototype.dc.html`): Home → Signals → Card Detail → Grading Lab, with a feed-state switch that reaches stale and refusal inside the flow.
- Track Record by-play-type now carries n per row, plus the two thresholds (n ≥ 30 to display a median, n ≥ 50 before actionable).
- Crack & resubmit / 9 → 10 frozen as NOT BUILT — regrade model unwired, conditional prior P(10 | 9) is a different distribution from the base rate.
- State matrix (5 states × 8 screens) with loading, empty, error and stale drawn full-size.

## Screen map

| Project screen | Repo files |
|---|---|
| Waltcg Prototype.dc.html | contracts/fixtures/card_detail.json, contracts/fixtures/signals.json, contracts/fixtures/grading_lab.json, contracts/assumptions.json |
| Waltcg App.dc.html — 3a-3h eight screens + 4a-4d states | contracts/screens.schema.json, all fixtures, contracts/assumptions.json, docs/CLAUDE_DESIGN_PROMPT.md |
| Directions.dc.html — turns 1-2 | contracts/screens.schema.json, all fixtures, README.md |

## Sync history

- 2026-08-13T08:52:10Z — eight screens built on the locked pattern; hero rule split for user-supplied inputs.
- 2026-08-13T08:28:34Z — Grading Lab in three states; direction 1a chosen with three pulls from 1b.
- 2026-08-13T08:05:00Z — read schema, fixtures, assumption registry; built two directions.
