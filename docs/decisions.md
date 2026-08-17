# Decisions

Architecture decision records for waltcg. Newest last. Each ADR records a
decision that was expensive to arrive at, so it does not have to be arrived at
again.

---

## ADR-0001 — A universal claim requires an answer from every source

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `probe/` and `engine/ev/`
- **Found by:** the offline replay harness, on its first run

### Context

The coverage probe kept producing confident absences that were not absences.
The same mistake appeared three times in three different disguises, and each
one cost roughly a day of provider quota to discover:

1. **A 2xx wrapping an error object read as an empty result.** apitcg.com
   answers auth failures with HTTP 200 and `{"error": ...}`. The probe read
   "the request succeeded and returned nothing" and concluded no Chinese
   printing existed. The evidence was an auth failure.
2. **A paginated list read as complete.** `/v1/games` returns 50 entries per
   page with `meta.has_more`. Page one was treated as the whole catalog, so a
   game on page two would have been reported as structurally absent.
3. **One source's answer standing in for all of them.** After fixing 1 and 2,
   absence was still confirmed when *one* catalog returned a validated empty
   result while the *other* errored. tcgapi.dev structurally lacking a Chinese
   game entry is real evidence; apitcg.com returning an error is not evidence
   of anything. The report nonetheless said "no Western source carries this
   printing."

The third was caught by `probe/replay.py` before it reached a live run — the
first of the three to cost nothing.

The common shape: **absence is a universal claim.** "No source has X" quantifies
over every source. A universal claim cannot be established from a subset of the
domain, and it especially cannot be established from a subset selected by which
requests happened to succeed. A failed request is not a data point about the
world; it is a data point about the request.

The failure mode is asymmetric and that is what makes it dangerous. An
existence claim ("this source has X") is settled by one positive observation,
so partial evidence is enough. A universal claim needs the whole domain, and
partial evidence produces a confident, plausible, wrong answer — one that reads
exactly like a finding.

### Decision

**A claim about every source requires an answer from every source. Any
inconclusive source yields `UNTESTED`, never a confirmed absence.**

Concretely, in the probe:

- A response supports an absence claim only when it classifies as
  `confirmed-empty`: a well-formed result envelope whose data array is
  genuinely zero-length. Error bodies, unrecognised shapes, non-2xx statuses
  and absent responses are all `UNTESTED`.
- A structural absence (a game the catalog does not list) counts as evidence
  **only when the enumeration behind it was read to completion**. A truncated
  list proves nothing about what is missing from it.
- `catalog == NONE` requires every consulted source to have answered. If any
  source is inconclusive, the result is `UNTESTED`, regardless of how strong
  the other sources' evidence is.
- Finding the thing anywhere still settles the question positively. The rule
  constrains absence, not presence.

### It generalises to the engine

This is not a probe-specific rule about HTTP. **"This card has no PSA 10
comps" is the same universal claim as "no Western source carries this
printing"**, and it fails in the same way: a thin or missing comp set gets read
as "worth nothing" rather than "unknown", and the model returns a number.

Applying the rule across `engine/ev/`:

- **Model A (`raw_to_graded_ev`)** — a grade carrying probability mass with no
  supplied comp now refuses. Previously it silently priced that branch at zero:
  with a PSA 10 comp absent and P(10) = 0.5, the model returned `EV -143.00`
  and `ok = True`, which reads as "do not grade this card" when the truth was
  "we do not know what a 10 sells for". Grades with zero weight need no comp —
  the rule is about branches that carry mass.
- **Model D (`grade_spread_residual`)** — already compliant. Suppresses any
  card whose *either*-grade comp sample is below the floor, reports sample size
  on every row, and refuses to fit rather than ranking what survives when too
  little does.
- **`grades.py`** — already compliant. Refuses when neither the card nor its
  set has population data, rather than inventing a grade distribution.
- **Models B and C** — already compliant. Both require every outcome branch to
  be priced before computing, and B additionally refuses without a complete
  condition read.

The engine expresses the rule through `Refusal`, a first-class result type
rather than an exception, for the same reason the probe reports `UNTESTED`
rather than dropping a row: "not enough evidence to answer" must survive into
the dashboard intact. Flattening it to a zero, a `None`, or a silently narrowed
average is how it stops being visible.

### Consequences

- Some questions now go unanswered that previously received an answer. That is
  the point. The previous answers were wrong.
- Absence is more expensive to establish: every source must be reached, and
  every enumeration must be read to the end. A rate-limited or unkeyed provider
  blocks an absence claim it would previously have been excluded from.
- Reports get more `UNTESTED` and more `INCONCLUSIVE`. Both are distinguished
  from `NONE` in the coverage matrix so the difference is legible at a glance.
- The distinction is enforced by tests, not convention:
  - `probe/fixtures/chinese-absence-needs-proof.json` reproduces the exact
    historical failure and asserts `INCONCLUSIVE`, never `MANUAL TIER`.
  - `probe/replay.py` runs an exhaustive contract check over all 25 body-class
    pairs, asserting that absence — as `catalog == NONE` or as a confirmed flag
    — requires a validated empty envelope from *every* source.
  - `tests/test_ev_models.py` asserts Model A refuses an un-comped weighted
    grade, and still computes when the un-comped grade carries zero weight.
- Mutation-tested: reintroducing the loosened gate fails both the fixture and
  the contract check.

### Notes

Two guards are deliberately redundant. `catalog == NONE` already implies every
source answered, so requiring `confirmed_empty` from each is belt-and-braces —
but the two conditions coincide only under the current classifier, and the
weaker one is the one that failed in production. The redundancy stays.

---

## ADR-0002 — `card_uid` is derived from the printing, not from any provider

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `resolve/`, `contracts/`, `store/`

### Context

Every card needs one stable identifier. The obvious candidate is a provider's id
— tcgapi has one, apitcg has one, TCGplayer had one. Using someone else's key is
free and immediate.

Three facts make it wrong here.

**Providers partition differently from us.** tcgapi.dev models language as a
*separate game entry*: Pokémon is game `55` and Pokémon Japan is game `19`. Its
identifier therefore encodes language inside the game, and it has no entry at all
for One Piece Japan — a printing that exists and that we track. A store keyed on
its ids literally cannot express part of our universe.

**Publishers reuse collector numbers across languages.** Bandai prints
`OP01-121` in English, Japanese and Simplified Chinese. Any scheme keyed on the
printed number alone merges three assets that trade in three separate markets.

**Providers close.** TCGplayer's API stopped accepting new applicants after the
eBay acquisition. Anything keyed on their ids would have needed a full re-key of
all history.

### Decision

```
card_uid = {game}:{set_code}:{number}:{variant}:{language}
game     ∈ {optcg, pkmn, riftbound}
language ∈ {EN, JP, CN-S, CN-T}
```

Derived entirely from what is physically printed on the card. Built only by
`resolve.identity.card_uid()`, which refuses provider identifiers by name.
External ids live in `card_xref` with `confidence` and `resolved_by`, never
inside the uid.

**Invariant: no two language printings ever share a `card_uid`.** Enforced by
the constructor, by `tests/test_resolver.py`, and by the schema regex.

### Consequences

- Resolution is now work we own. A card must be matched to each provider's id
  once, with a confidence, and anything fuzzy below 0.9 is excluded from signals.
- Cards no source carries — the Chinese printings — still get identity, history
  and manual prices. An id-keyed store could not have represented them.
- The uid is long and human-readable, which is a feature in a debugging context
  and irrelevant in an index.
- One wrinkle found by the tests: a provider slug can coincide with an internal
  code (apitcg calls Riftbound `riftbound`, so do we). Coincident tokens are
  accepted; only unambiguously-external ones are rejected. Rejecting them would
  have rejected a legitimate internal code, which the first test run did.

---

## ADR-0003 — Money is an object, never a number

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** everything that touches a price

### Context

A bare number cannot say what it is. `12400` is ¥12,400 or $12,400 depending on
context that lives in a variable name, a column header, or someone's memory. The
cost of getting that wrong is not proportional to the error — it is the exchange
rate, which for JPY/USD is roughly two orders of magnitude. This has already
happened once on this desk, at a factor of 7.8 in position sizing.

JSON numbers make it worse: they are IEEE 754 binary floats, and cents do not
survive them. `0.1 + 0.2` is famously not `0.3`, and a fee stack is a chain of
exactly those additions.

### Decision

Every monetary value, everywhere, is:

```json
{"amount": "412.55", "currency": "USD", "fx_rate_used": null, "fx_as_of": null}
```

- `amount` is a **string**, not a JSON number. Parsed to `Decimal`.
- All four keys are required. `fx_rate_used` and `fx_as_of` are null together
  and set together — null means "no conversion happened", never "unknown".
- Cross-currency arithmetic raises `TypeError`. There is no implicit FX.
- The `Money` constructor **rejects Python floats outright**: a float has already
  lost precision and accepting one would launder the loss.
- FX round-trips are exact by provenance, not recomputation. Converting 15000 JPY
  to USD and back returns exactly 15000 — verified on a rate where plain Decimal
  arithmetic drifts.

### Consequences

- The contract is noisier. A price is four keys instead of one. This is the
  point: the noise is the information.
- Every screen can render currency symbol *and* code without inferring either,
  which GOAL D7 requires and which a bare number cannot support.
- Tests walk the entire fixture tree asserting no bare number sits under a
  monetary field, and that every `amount` is a string matching a decimal pattern.
- Money in a *display* string (`"$49.99/mo"` in config) is not this type and is
  not covered — the guard distinguishes our own subscription costs from observed
  card prices.

---

## ADR-0004 — The design brief was rewritten around uneven coverage

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `docs/CLAUDE_DESIGN_PROMPT.md`
- **Supersedes:** the v1 brief, in full

### Context

The first design brief was written before Session 0 ran a single request. It
assumed a world the probe then falsified, and it was specific enough about that
world to have produced a design that could not be built.

Three findings killed it.

**Population data exists for Pokémon only.** PokémonPriceTracker is
Pokémon-only by construction, and PSA has never exposed a population API. So
for One Piece and Riftbound there is no population at any grade, from any
source we can reach. That is not a gap in one panel: it is the input to the
grade ladder's rung weights, to Model A's prior, and to Model D's entire
regressor. The v1 brief described the ladder as a single artefact encoding
price *and* population. For two of the three games it can only encode price.

**The tcgapi catalog has no One Piece Japan entry.** Established by paginating
`/v1/games` to the end — the whole enumeration, per ADR-0001, because a
truncated list proves nothing about what is missing from it. tcgapi models
language as a separate game (`55` Pokémon, `19` Pokémon Japan); there is simply
no One Piece Japan row. A printing we track, and actively trade, is
structurally inexpressible to that source.

**The three Chinese printings are a manual tier.** Pokémon Simplified Chinese,
Pokémon Traditional Chinese and One Piece Simplified Chinese are all official
releases; One Piece Traditional Chinese is not. No Western source carries any
of them. Prices come from Xianyu, Taobao, Mercari JP and SNKRDUNK, typed in by
hand, and the EV models run on them unchanged.

Counted up: four of the eight game/language combinations have no population,
and four have no automated price at all. The degraded path is not the exception
in this app — it is most of it.

### Decision

**`docs/CLAUDE_DESIGN_PROMPT.md` is replaced by the v2 brief verbatim, not
merged.** The differences that matter:

- A coverage table sits near the top, before any screen is described, stating
  which of the eight combinations support what. Uneven coverage is framed as
  the constraint that shapes the design rather than an error state.
- The grade ladder's **no-population form is briefed as a first-class variant**,
  explicitly noted as appearing about as often as the full one.
- **Refusal is named as a design state**, alongside loading, empty, error and
  stale — five states per screen, not four. This follows the engine, where
  `Refusal` is a returned result type and not an exception, for the same reason:
  "not enough evidence" has to survive into the UI intact.
- A ninth screen, **Manual Entry**, was added, with the requirement that
  hand-entered rows stay visually distinguishable everywhere they later appear.
  Same engine, different provenance, different ageing.
- **Trend Radar's Reddit sourcing is gone.** v1 briefed abnormal mention
  velocity across Reddit, YouTube and search interest. The Reddit Data API
  application is not approved, card-level search interest was deleted from the
  schema for lack of a source, and a brief that names an unavailable source
  gets a screen designed around it.
- Arbitrage Board is marked Pokémon-only on the screen itself.
- Provisional-versus-verified is added to the display rules, because grading
  fees currently ship as `secondary, unverified` and that has to be visible
  where it changes a number.
- The name is `waltcg` throughout, and the brief points at the repo's real
  contract files rather than uploaded copies.

### Consequences

- The brief now instructs the designer to stop and ask rather than invent a
  field name. This is the same rule the schema session enforced by deleting
  every unsourceable field: an invented field becomes an empty box on a screen
  three weeks later, and by then something has been built on top of it.
- v1 is not kept alongside v2. Two briefs in `docs/` is an invitation to design
  against the wrong one; the diff lives in git and the reasoning lives here.
- The source was a PDF, so `cmp` cannot compare it to a Markdown file directly.
  Verified instead by normalising both to the same token stream — Markdown
  syntax stripped, whitespace collapsed — and running `cmp` on those: 9,306
  bytes of prose identical in order, and the coverage table identical as a word
  multiset, the table alone because the PDF lays it out column-major and
  Markdown row-major.

---

## ADR-0005 — Provenance belongs to the value, not to the row

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/screens.schema.json`, `contracts/fixtures/`
- **Found by:** Claude Design, auditing the contract before designing against it

### Context

Four gaps, reported by the designer rather than by a test. All four share one
mistake: **metadata was attached at the wrong altitude.** Something true of a
single number was recorded on the screen, on the row, or nowhere.

1. **`refusal.missing` was `array<string>`.** The brief calls refusal the
   behaviour it most needs the design to respect, and asks for a screen that
   reads as a checklist. A bare string gives a designer nothing to title a row
   with, nothing to group by, and nowhere to send the tap. Worse, no fixture
   exercised a refusal at all, so the one state most in need of design was the
   one nobody could see.
2. **Staleness was per-screen and per-row, one `kind` at a time.** A card's
   price is a live quote and its population is a weekly pop-report pull. They
   do not age together. A row holding both could report only one, so the other
   silently inherited the wrong freshness — and prices are the fast-moving half.
3. **`needs_primary_verification` existed only on `grading_tier_view`,** on the
   Settings screen. Grading fees today are `secondary, unverified`. A break-even
   probability computed with one is itself provisional, and the Grading Lab —
   where that number is the headline — had no way to say so.
4. **`entry_method` existed only on `buy_route`.** A hand-typed Xianyu price
   feeds a ladder rung and a signal row, and on both it rendered identically to
   an API quote. Four of the eight game/language combinations are manual tier;
   this is most of the app, not an edge.

### Decision

**Provenance is carried by `derived_value`.** It gains `staleness`,
`needs_primary_verification` and `entry_method`, all required. Every number the
engine computes or observes now states its own freshness, whether it rests on
unverified config, and how it reached us.

Row- and screen-level `staleness` is **deleted** from seven definitions rather
than kept alongside. It was a rollup of values already present in the payload,
which makes it a second source of truth that can disagree with the first.

**Refusal items are objects**: `{id, title, reason_code, fixable, deep_link}`.
Two parts carry the weight:

- `id` **is the assumption id** where the gap is a registered assumption, so the
  chip, the registry row and the refusal line are one thing to the UI. Enforced
  in `tests/test_contract.py`, which the schema cannot do across files.
- `fixable` separates "supply this and the number computes" from "no population
  source exists for One Piece". Rendering a structural absence as a checkbox
  tells the same lie every time the screen loads.

`reason_code` is a closed enum of ten, each grounded in a `Refusal` the models
actually raise or a `ConfigIncomplete` path — so a code cannot describe a gap
the engine has no way to produce.

### Where row-level markers survive, and why

`entry_method` is kept **on `signal_row` and `mover_row`** as well as on every
value. This looks like the rollup that was just deleted, and is not: a signal
row's headline is computed from inputs that do not all appear on the row, so a
row-level `mixed` carries information no per-field marker can. Staleness had no
such inputs — every stale field was already in the payload. The asymmetry is the
test for whether a row-level field is earning its place.

### Consequences

- **The engine now owes a mapping.** `Refusal.as_dict()` emits `missing` as a
  list of dotted paths — `fees.marketplaces.ebay.fee_schedule.bands`,
  `comps_by_grade['10']`. Those become `refusal_item.id`; the title, reason code,
  fixability and deep link do not exist in the engine and have to be derived at
  the `api/` boundary, which is not built yet. **The contract is deliberately
  ahead of the engine here.** Nothing enforces the correspondence today, and a
  test asserting every engine refusal path maps to a `reason_code` is owed when
  `api/` lands.
- Two fixtures were added rather than adapted: `grading_lab.refusal.json`, a
  nine-item checklist with seven fixable items and two structural ones, and a
  manual-tier signal row on `optcg:OP01:OP01-078:parallel:JP`. Fixtures now key
  on `<screen>.<state>.json`, so a screen may carry several.
- `contracts/fixtures/card_detail.json` deliberately ships a **12-day-old
  population beside a same-day price**. That combination was unrepresentable
  before this change, so it is now a fixture — the regression test for fix 2 is
  that it can be expressed at all.
- Staleness arithmetic is asserted: `is_stale == age_seconds >
  threshold_seconds` on every value in every fixture. A flag that disagrees with
  the badge printed beside it is worse than no flag.

### Two properties confirmed unchanged

Both were queried in the audit and both are deliberate.

**`grade_ladder.minItems: 1`.** A card with a raw price and no graded comps has
exactly one rung, so 1, 2, 3 and 4 rungs all have to render. A fixture now ships
a three-rung ladder so the degraded form is in front of whoever designs it.

**`price_history` guarantees no density.** No `minItems`, no cadence. Most of
the universe has single-digit graded sales per quarter, and any guaranteed
density could only be met by interpolating prices nobody paid. Because the
guarantee is absent, the series has to state what it actually returned:
`price_history_meta.sample_size` is the point count, so a two-point history
cannot be drawn as though it were a series.

**One thing the audit did not raise and should have:** nothing bounded the
ladder from above, and nothing enforced rung uniqueness or order. Seven rungs,
or two both graded 9, validated cleanly — `uniqueItems` cannot express
uniqueness on a property. `maxItems: 4` is now in the schema; uniqueness and
raw → 8 → 9 → 10 ordering are asserted in tests.

---

## ADR-0006 — The engine is the authority on every number in a fixture

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/fixtures/`, `tests/fixture_scenario.py`
- **Found by:** reading two fixtures side by side and noticing they described
  different worlds

### Context

Card Detail showed the worked Pokémon card with a PSA 9 at 320. Grading Lab
priced a submission on that same card at 224.54 all-in and reported it losing
96.20 if it came back a 9. A 9 selling for 43% more than the entire cost of
acquiring and grading the card is not a loss, and no arithmetic connects those
two screens.

Checked against the engine, **every derived figure in `grading_lab.json` was
invented**, and not by a little:

| Figure | Shipped | Engine |
|---|---|---|
| EV | −38.40 | **+210.36** |
| break-even P(10) | 0.412 | **0** |
| modelled P(10) | 0.286 | 0.199 |
| downside if 8 | −96.20 | −60.12 |

The break-even solving to zero is the tell: at a PSA 9 of 320 the submission
pays for itself without the card ever reaching a 10, so the Grading Lab's
signature gauge — what you need against what is likely — has nothing to draw.

Worse than any single number, `modelled_p_target` (0.286) sat **above**
`pop_implied_p_target` (0.249). The submission-selection haircut only ever moves
mass *down*, because people submit their best copies. Inverted, it reads as "the
population understates your chances", which is the opposite of CLAUDE.md
non-negotiable 5 and the single most dangerous thing this app could imply.

This matters more than it looks. A designer tuning visual weight against these
fixtures is not learning the numbers — those get replaced. They are learning the
**relationships**: how wide the needed-versus-likely gap usually is, whether a
negative EV is a near miss or a rout, what a normal grade spread looks like.
Those lessons survive into the layout and outlive every value in the file.

### Decision

**The engine computes the fixtures. Nothing derived is typed by hand.**

`tests/fixture_scenario.py` declares the one scenario every fixture is computed
under, and draws a hard line through it:

- **Real, from dated config.** The PSA Regular fee (79.99), its 60 business-day
  turnaround, and the whole eBay banded schedule — 13.25% on item plus shipping
  plus tax, tiered fixed fees, the discount band at 1000 — come from
  `config/*.yaml` as shipped. Fee arithmetic in the fixtures is the real fee
  arithmetic.
- **Declared, because config ships them null.** Submission costs, the selection
  haircut, prior strength, tax rate, days-to-sell. Every one is null in the
  repository on purpose so the engine refuses rather than defaults. A fixture
  needs *some* number to exist at all, so the scenario states which it used and
  why, in one place. They are illustrative and none is a claim about the world.

`tests/regenerate_fixtures.py` rewrites the derived figures;
`tests/test_fixture_arithmetic.py` recomputes them independently and fails on
disagreement. 31 assertions, mutation-tested against the exact numbers that
shipped: all of them are caught.

### Which half was wrong

The ladder, not the Lab. The Lab's figures (EV −38.40, ROI −0.152, annualised
−0.418) describe a coherent and very typical card — one where a 9 sells for
roughly what the card cost raw, and only a 10 pays. The ladder described a
different one. Reconciled toward the Lab, because a **marginal** submission is
the case that screen exists for: `raw 140 / 8 88 / 9 142 / 10 540` reproduces
its story with arithmetic that holds — needed P(10) 0.301 against a modelled
0.199, EV −35.67, annualised −0.425.

### What cannot be recomputed, and is now written down

Five figures have no path back to their inputs, because the inputs are not in
the payload: portfolio value (no holdings list), per-mover 24h change (no prior
price), the three hit rates and median excess return (31 scored alerts, 6
visible by design), and `suppressed_count` (counts rows that were filtered
before serialisation). They are listed in `NOT_RECOMPUTABLE` with a reason each,
and a test asserts the reasons are reasons rather than labels. **An unchecked
figure that nobody has written down is exactly how this happened.**

### Consequences

- `arbitrage_row` gains `buy_cost`. Without it `net_margin_pct` had no
  recomputable denominator and the marketplace fee had no base to be charged on
  — and the shipped rows had a flat 13.25% applied above 1000, where the real
  schedule halves it. A friction stack you cannot recompute is the thing the
  expandable stack exists to prevent.
- Changing one number in the scenario moves every fixture together, which is
  the property that was missing.
- The fixtures are still synthetic and still marked `_fixture: true`. Synthetic
  now means *derived under a stated scenario*, not *arbitrary*.

---

## ADR-0007 — Manual Entry is the ninth screen

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/screens.schema.json`

### Context

The v2 design brief lists nine screens. The contract had eight. The missing one
was Manual Entry, which is not a peripheral utility: **four of the eight
game/language combinations have no automated price source at all** — One Piece
JP, whose printing tcgapi's catalog cannot even express, and the three Chinese
printings that no Western source carries. Their prices are typed in from Xianyu,
Taobao, Mercari JP and SNKRDUNK.

The absence had already started bending things around it. `deep_link.screen`
could not name Manual Entry, so a `manual_price_required` refusal — "I cannot
price this until you type something in" — had nowhere honest to send the tap and
pointed at Card Detail instead. A workaround in a contract becomes a workaround
in the app.

### Decision

`screen_manual_entry`, with two lists and nothing else:

- `awaiting` — cards the app cannot price on its own, each with the
  `unavailable_reason` that put it there and the last price I entered, if any.
- `recent_entries` — `manual_price_entry` records: card, price, venue,
  condition, `as_of`, `observed_at`, note, `supersedes`.

`supersedes` rather than an edit, because history is append-only (CLAUDE.md
§Conventions) — a mistyped price is corrected by a new row citing the old one,
and the fixture demonstrates exactly that.

`deep_link.screen` gains `manual_entry`, and the schema now **pins** it: a
refusal item whose `reason_code` is `manual_price_required` must deep-link to
`manual_entry`, enforced by an `if`/`then`. The workaround cannot come back.

### What was deliberately left out

`venues` and `condition_options` as payload fields. Both are already closed
enums in the schema, so serving them would be the API telling the UI something
the UI can read off the contract — a field that exists to be redundant is the
first step toward two lists that disagree.

---

## ADR-0008 — A transcribed price and an invented prior are different provenance

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/screens.schema.json`
- **Found by:** Claude Design, building against the contract

### Context

`entry_method` marks a price I typed in. Nothing marked a *probability* I typed
in, and the two are not the same thing at all:

- A hand-entered price is an **observation of a real market** that happens to
  have no API behind it. Someone paid ¥5,000 for that card on Mercari. The
  number is soft because it is one listing, not because it is imaginary.
- A hand-supplied P(10) is **my own judgement with nothing behind it**. No
  population source exists for Riftbound or One Piece, so there is no data to
  derive it from and none to check it against.

Both are "manual", and reporting them the same way would tell a designer they
carry the same kind of uncertainty. They do not. One is thin evidence; the other
is not evidence.

An enum could not absorb this, because a Riftbound card routinely needs **both**
at once — a typed price *and* a typed prior. `entry_method: manual` would have
had to mean either or both, and the row could never say which.

### Decision

`estimate_basis`, alongside `entry_method` and independent of it:

| Value | Meaning |
|---|---|
| `population` | Derived from a pop report, shrunk and haircut. |
| `user_estimate` | I typed the probability. No population source exists for this printing. |
| `config_rule` | From the dated crossover rules. |
| `none` | This figure rests on no grade probability at all. |

`none` is not a null. A **break-even threshold is solved from prices and costs
alone** — it carries no probability input, which is precisely why it is the
trustworthy half of the Grading Lab's gauge. The screen shows a hard number
against a soft one, and the marker is how it can say so.

Carried on every `derived_value`, and at row level on `signal_row`,
`ledger_entry` and `arbitrage_row` — same test as `entry_method`: a row's
headline is computed from inputs that do not all appear on the row.

**`trend_row` deliberately does not get it.** A velocity z-score never involves
a grade probability, so the field would read `none` on every row forever. A
constant field is decoration, and decoration eventually gets believed.

### What it exposed

Adding the marker forced two things into the fixtures that were missing:

- **A signal row resting on a supplied P(10).** Riftbound has no population, so
  model A had to run in its second mode — distribution supplied rather than
  derived. It computes: needed P(10) 0.527 against a typed 0.15, EV −62.28. That
  mode is named in the design brief and no fixture had exercised it.
- **Three of the five worst calls now say they rest on a typed prior.** A bad
  call built on my own guess is a different lesson from a bad call built on a
  pop report, and the Track Record screen exists to teach exactly that
  difference. Asserted at three, not "at least one".

A supplied prior is also barred from dressing itself up: `sample_size` must be
null and `confidence` `unvalidated` on any figure marked `user_estimate`. A
typed guess carrying a sample size is the most misleading thing this app could
render. Mutation-tested.

---

## ADR-0009 — The assumption registry carries its own reverse index

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/screens.schema.json`, `contracts/fixtures/settings.json`

### Context

Every `derived_value` already carries `assumption_ids` — the forward edge, from
a figure to what it depends on. The registry had no edge back. So the one
question worth asking at the moment of change — *if I move the submission
haircut from 0.80, what moves with it?* — had no answer anywhere in the
contract, and the honest way to find out was to read the engine.

That is the moment the answer is needed. An assumption is edited from the
Settings screen, and the consequence lands on screens the user is not looking at.

### Decision

`assumption_entry_view` gains `used_by` and `used_by_count`. `used_by` lists
**figures, not card instances**: `{screen, field, label}`. "Used by 6 figures"
should answer "what moves", and the actionable answer is a set of places in the
app, not a count of rows — the same haircut feeds one signal row or four
thousand, and that number tells you nothing.

**It is derived, never typed.** `collect_usage()` walks every fixture, indexes
`assumption_id → {(screen, field)}` from the `assumption_ids` already present,
and drops array indices — `rows[0].headline` and `rows[3].headline` are one
figure seen twice. A hand-kept reverse index is a second list that drifts from
the first, and it fails silently: you change a haircut believing four figures
move when six do.

`tests/test_fixture_arithmetic.py` asserts set equality in both directions —
every citation listed back, and no entry claiming a dependant that does not cite
it. Mutation-tested against a dropped edge, an invented edge and a count that
disagrees with its list; all three caught.

### What the index immediately showed

Four registry entries feed nothing: `regrade_conditional_prior`,
`regrade_downgrade_probability`, `regrade_condition_adjustments` and
`empirical_bayes_min_card_pop`. The first three are model B, which no screen
surfaces yet — the Regrade play type exists in `play_type` but no fixture
carries one. That is a real gap in the contract, found by building the index
rather than by reading the schema.

Orphans surface as a warning on the Settings payload rather than rendering as a
quiet zero. An assumption with no dependants is either dead or a screen nobody
built, and both are worth seeing.

---

## ADR-0010 — A play type is either wired to its model or it is not in the contract

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/`, `engine/ev/model_b.py`
- **Found by:** the orphan count in ADR-0009's reverse index

### Context

Three registry entries fed nothing: `regrade_conditional_prior`,
`regrade_downgrade_probability`, `regrade_condition_adjustments`. I read that as
"model B has no screen yet". It was worse than that. The play was **not absent
— it was half-present**:

- `nine_to_10` sat in the `play_type` enum, so Signals offered a 9 → 10 filter.
- `crack_resubmit` sat in the arbitrage `path` enum, so the board rendered a
  CRACK & RESUBMIT panel.
- No payload anywhere carried model B's output.

So the panel showed **model A's figures under a regrade label** — the worked
card's −$38.40 and its 0.301 / 0.199 probabilities. Those describe grading a
*raw* card. A card already slabbed at 9 is not a random card: PSA examined it
and declined a 10, and using the base gem rate re-uses information the grader
has already acted on. That is CLAUDE.md non-negotiable 6, and the screen was
breaking it while looking entirely normal.

A play type that looks live on another model's numbers is worse than one that
is absent, because nothing about it looks wrong.

### Decision

**(a): wire it.** Model B was already written, complete, with the conditional
prior and the refusal discipline. Removing the play from the contract would
have deleted a working capability that the brief ranks second of four.

Its own figures, on the same card: **needed P(10) 0.306 against a modelled
0.173**, EV −46.44. Model A on the raw card says 0.301 against 0.199 and −35.67.
The modelled probability is the one that matters — **0.173 is below the base
rate of 0.199**, which is the conditional prior doing exactly its job.

Concretely:

- `arbitrage_row` gains `regrade_detail` — break-even, modelled probability,
  the condition read, all three outcome branches, and a refusal slot. The
  schema **pins** it: a `crack_resubmit` row without it fails validation, so
  the half-present state cannot come back.
- `signal_row` gains `refusal`. Model B will not price a regrade without a
  complete condition read, and most rows in a 9 → 10 feed will not have one, so
  a feed row has to be able to refuse. The fixture ships both states.
- `friction_stack` gains `supplies`. A regrade row would otherwise have had to
  hide it inside shipping.

### The bug underneath the bug

Model B could not have run against shipped config **at all**, for a reason
having nothing to do with the regrade prior. Its `required_paths` demanded
`final_value_fee_pct` / `payment_pct` / `payment_fixed` — the flat fee trio.
eBay's config supplies a banded `fee_schedule` instead, and those keys are
null. Model A branched on which form a venue uses; model B never did.

So model B would have raised `ConfigIncomplete` on eBay forever. Worse, had
someone filled the flat trio to make it run, **two models would have priced the
same venue's fees two different ways** and two screens would have disagreed
about eBay. Model B now uses the same schedule as model A.

### Consequences

- The three orphan assumptions have dependants, and the reverse index says so.
- `estimate_basis: config_rule` covers a registered prior as well as a dated
  crossover rule — both mean "a rule, not this card's own data".
- Mutation-tested: the panel showing model A's P(10) again, the row netting to
  model A's EV, a `crack_resubmit` row with no detail, and a 9 → 10 row priced
  with no condition read are each caught.

---

## ADR-0011 — Track Record is computed from a ledger it ships

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/fixtures/track_record.json`, `screens.schema.json`

### Context

Hit rate, median excess return, per-play breakdown and the worst-five ordering
were all typed by hand, on the one screen whose entire purpose is honesty about
the app's record. `NOT_RECOMPUTABLE` even said so out loud: 31 scored alerts, 6
visible, so no rate could be checked against anything.

### Decision

The payload ships **`ledger`: every alert ever fired, newest first** — which is
the brief's own description of the screen. Every figure above it is derived from
it and asserted: the three hit rates, the median, `by_play_type`, and
`worst_five` membership *and* order.

Returns come from a deterministic integer sequence, **untuned**. Picking numbers
that land on a flattering 52% would be the same failure as the invented EV, one
layer up. They fall where they fall: 0.516 at 7 days, 0.464 at 30, 0.500 at 90.

`recent` is deleted. It was a second copy of the newest ledger rows — two lists,
one truth.

### What shipping the ledger immediately exposed

**The three hit rates cannot rest on the same number of alerts.** The fixture
claimed all three covered 31. An alert fired ten days ago has no 90-day return
and will not have one for eighty more days. Derived from the ledger the
denominators are 31 / 28 / **18** — the 90-day rate, the one that reads as most
authoritative, rests on the fewest alerts and had been rendering as if it rested
on the most.

That needed a new `unavailable_reason`: **`horizon_not_elapsed`**. It is
categorically different from every other reason in that enum, all of which mean
"we cannot get this". This one means "it does not exist yet". Counting an
unmatured alert as a zero, or dropping it from the denominator permanently,
both bias the number the screen exists to report.

### Per-play rates carry n

`by_play_type` gives each play its own `hit_rate_30d` and
`median_excess_return_30d`, each a `derived_value` with its `sample_size`
populated — no new sample-size concept, just the one every other figure already
uses. Across 31 alerts and six plays every bucket is n=4–5, and the payload says
so in a warning and drops confidence to `low` below n=10. Grade gap at 40% on
five alerts is the honest rendering of grade gap at 40%.

---

## ADR-0012 — `observed_at` was in the conventions and missing from the contract

- **Status:** Accepted
- **Date:** 2026-08-13
- **Scope:** `contracts/screens.schema.json`

CLAUDE.md § Conventions → Time has always specified the pair: `as_of` is the
date the value refers to, `observed_at` is when we saw it, and
`observed_at >= as_of` always. The contract shipped only `as_of`.

With one timestamp, "as of 11:04" and "fetched at 11:04" collapse into the same
claim, and they are not the same claim — one is about the market, the other is
about us. During an outage they diverge, and that divergence *is* the error
state: a price can be perfectly valid as of yesterday's last trade while we have
not reached the source since.

`observed_at` is now required on every `derived_value` and mirrored onto
`staleness` so a badge needs one object. Asserted: never earlier than `as_of`,
always mirrored, and at least one ladder rung must show the two differing —
otherwise the design has no reason to render two timestamps and will render one.

---

## Note — per-field staleness, verified

Queried whether the ADR-0005 fix reached `signal_row` and `grade_rung`. It did,
in `b1b002b`. Evidence:

- The only `$def` in the schema with a `staleness` property is `derived_value`.
  `signal_row` has none; `grade_rung` has none.
- A `grade_rung` carries two independent `derived_value`s, and in the shipped
  fixture they disagree: `price_meta` is fresh (43,200s against an 86,400s
  threshold), `population` is stale (1,036,800s against 604,800s). One rung,
  two answers — the case that was previously unrepresentable.

The design brief is working from a pre-`b1b002b` schema. Nothing to fix here.

---

## ADR-0013 — Cross-grader comps are flagged, not refused

- **Status:** Accepted
- **Date:** 2026-08-14
- **Scope:** `engine/ev/comps.py`, models A/B/C, `contracts/`

### Context

The route comparison prices one card through CGC UK and PSA US against a single
set of comps. Those comps are PSA sales. A CGC 10 and a PSA 10 are different
assets with different premiums, so the CGC row is optimistic by exactly the gap
between them — a gap for which there is no data in this repository.

Refusing would have been consistent with how this codebase handles most
uncertainty, and it would have been wrong here. Holding the comps fixed is not
a defect of the comparison; it is **the method**. It is precisely how the cost
of a route — fees, freight, import charges — gets isolated from slab premium.
Refuse and the question the whole import-charge term was built to answer
becomes unanswerable.

The failure mode is narrower than "the number is wrong". The number is right
for one question and wrong for another:

- **"What does this route cost?"** — fixed comps are correct.
- **"Which slab should I own?"** — fixed comps answer it wrongly, and
  confidently.

### Decision

`comp_basis`, on every model result and on the Grading Lab and Arbitrage rows.
A flag, never a refusal.

Three states, not two:

| State | Meaning |
|---|---|
| `match` | Comps are from the route's own grader. |
| `mismatch` | Comps are from a named different grader. |
| `unstated` | Nobody said which grader supplied them. |

**`unstated` raises the flag exactly like `mismatch`.** Silence is not
agreement, and treating an unstated comp source as a match would be the silent
default this repository keeps refusing to take. One boolean, `flag`, is true for
both — because to a reader they mean the same thing.

**It names the grader.** "Mismatch" alone is not actionable; the reader needs to
know whose sales the number rests on. The name is carried both as a structured
field and in the note, and mutation-testing removes each independently.

Case and surrounding whitespace never decide a mismatch. `comps_grader` is free
text I type; the route grader is a config key. A flag raised by capitalisation
is noise, and noise gets ignored along with the real ones.

### Consequences

- The CGC UK row in the route comparison now carries a mismatch flag naming PSA
  as the comp source, while still producing its break-even of 0.125. That is the
  intended shape: usable, and impossible to mistake for a slab recommendation.
- Every existing call site that does not state a comp source now flags
  `unstated`. That is not a regression — it is the contract discovering that
  nobody had said.

---

## ADR-0014 — eBay UK's VAT is charged on the fee, not on the sale

- **Status:** Accepted
- **Date:** 2026-08-14
- **Scope:** `engine/ev/fees.py`, `config/fees.yaml`

`config/fees.yaml` recorded eBay UK's 20% VAT-on-fee and the engine ignored it,
understating the venue by about 2.5 points of the sale. Recorded-but-unmodelled
is the worst of the three options: it looks handled.

Implemented rather than refused, because the arithmetic is unambiguous once the
base is named correctly. **It is a fee-on-fee.** It multiplies the selling fee
and never the sale price:

```
fee_before_vat = commission + payment + fixed
vat_on_fee     = fee_before_vat * 0.20
```

So a 12.8% selling fee costs 15.36% of the fee base, and 15.40% of a £1,000 sale
once the 30p is counted. A private seller cannot reclaim it, so it is a real
cost rather than a pass-through.

Both components are itemised on the result — a fee stack whose parts you cannot
see is a fee stack you cannot check. Venues with no `vat_on_fee_pct` are
unaffected, and a rate written as `20` rather than `0.20` is rejected rather
than charging 2,000%.

**Not resolved and deliberately so:** PSA's membership price. Two of PSA's own
pages disagree ($149/$199 against $99). A conflict between two primary sources
is not settled by picking one, so the entry stays flagged
`needs_primary_verification` with a CONFLICT note until it is confirmed at
checkout.

---

## ADR-0015 — 250 labelled cards, and why the split is not proportional

- **Status:** Accepted
- **Date:** 2026-08-17
- **Scope:** `tests/fixtures/labelled_200.json`, `resolve/candidates.py`

### The number

200 was picked arbitrarily and is very nearly right, but for a reason worth
being explicit about: **the binding constraint is the error budget, not the
sample size.**

One-sided 95% Clopper-Pearson lower bounds on precision:

| n | 0 errors | 1 error | 2 errors |
|---|---|---|---|
| 150 | 0.9802 | 0.9688 | 0.9586 |
| **200** | **0.9851** | **0.9765** | 0.9689 |
| **250** | **0.9881** | **0.9812** | 0.9750 |
| 300 | 0.9901 | 0.9843 | 0.9792 |

At n=200 a *perfect* sweep clears 0.98. **One wrong match drops it to 0.9765
and the gate fails.** So 200 is a zero-error budget dressed as a sample size:
the first genuine mistake invalidates the claim and there is nothing to do but
label fifty more cards.

**250 survives exactly one error.** That is the whole argument for the change.
The smallest n clearing 0.98 with zero errors is 149; with one error, 236; with
two, 313. Going beyond 250 buys a second error's headroom for another 63 cards
of hand review, which is not worth it — if the resolver is making two mistakes
in 250 it should fail.

### The split, and why it is not proportional to the universe

| Combo | n | Exact match available? |
|---|---|---|
| `pkmn:EN` | 40 | yes (tcgapi 55) |
| `pkmn:JP` | 35 | yes (tcgapi 19) |
| `optcg:EN` | 35 | yes (tcgapi 11) |
| `optcg:JP` | 35 | apitcg only — tcgapi has no entry |
| `optcg:CN-S` | 30 | **no** |
| `pkmn:CN-S` | 30 | **no** |
| `pkmn:CN-T` | 25 | **no** |
| `riftbound:EN` | 20 | yes (tcgapi 5) |

The driver is not how many cards exist. It is **which combos can resolve
exactly.**

An exact match on a provider id cannot be wrong about identity — it is wrong
only if the xref itself is wrong, which is a different failure with a different
fix. A combo with no provider id resolves **fuzzily every single time**, so the
fuzzy path — the only path that can produce a confident wrong answer — carries
100% of that combo's load rather than a fraction of it.

The three Chinese printings are a rounding error in the card universe and get
**34% of the labelled set**, because they are the only combos where every
single resolution runs through the code that can fail.

`riftbound:EN` sits at the floor for the opposite reason: English only, so the
most dangerous failure mode — one art merging across languages — cannot occur
there at all.

### The floor: 20

Below this a combo can be meaningfully broken and still show a clean sweep. If
a combo's true precision is 0.80, the chance of seeing no errors is:

| n | P(clean sweep at 80% true precision) |
|---|---|
| 10 | 11% |
| 14 | 4% |
| **20** | **1.2%** |
| 29 | 0.2% (this is the n for detecting 90%) |

At n=14 a one-in-five failure rate hides 4% of the time. At 20 it hides 1.2%.
**A combo below 20 is untested, not lightly tested**, and the gate now says so
separately from the total.

### What this does NOT claim

Per-combo precision is not gateable at 0.98 at any realistic n — a 40-card
combo with zero errors supports only ≥0.93. The per-combo counts exist to
**detect a broken combo**, not to certify each one. The 0.98 claim is global
and stays global.

---

## ADR-0016 — The labelled set is adjudicated, never generated

- **Status:** Accepted
- **Date:** 2026-08-17
- **Scope:** `resolve/candidates.py`, `resolve/label_cli.py`

### Context

The labelled set must not be generated from the catalogs the resolver reads.
If it were, scoring the resolver against it would measure **agreement with its
own inputs**, not correctness: a card the catalog got wrong would be labelled
wrong and scored right, and the precision number would be highest exactly when
the catalog was worst.

But hand-authoring 250 cards from nothing is its own failure — slow enough that
it does not happen, and biased toward whatever the author happens to remember.

### Decision

Split the work at the point where the circularity actually lives.

**The generator proposes. The resolver states its own answer. The human
adjudicates.** `resolve/candidates.py` produces candidates with the resolver's
proposed identity attached; `resolve/label_cli.py` presents each one for
confirm / correct / reject. The human verdict is what breaks the circle, and it
is the only part that cannot be automated without reintroducing the problem.

Candidates are weighted toward five failure modes, most dangerous first:

1. `same_art_across_languages` — one number in two or more markets. The failure
   is silent and total: three assets merge and every downstream number inherits
   the blend.
2. `reprint_across_sets` — distinguished only by a field providers disagree on.
3. `alt_art_vs_base` — one number, two variants, very different prices.
4. `promo_vs_set` — shares a name, different asset.
5. `lowest_confidence` — wherever the resolver is least sure. Not a known trap,
   which is exactly the point: it is the only priority that can surface a
   failure mode nobody enumerated.

A random sample would be overwhelmingly cards that resolve trivially, and 250
easy cards measure nothing.

### Two things the tooling refuses to hide

**A correction records what the resolver said.** The disagreement is the most
valuable row in the set and overwriting it would discard the finding.

**`status` warns when every adjudication agreed.** A set with zero corrections
means either the candidates were too easy or the review was not real — and a
set with no corrections cannot distinguish those two. The warning fires above
20 confirmations with no corrections.

---

## ADR-0017 — Three open catalog sources, and none of them close One Piece

**2026-08-17.** The three Chinese combinations were recorded as having no
catalog source. That was true of the five commercial providers and false of the
open ecosystem, and I did not check the open ecosystem. Adapters added, in the
priority order they are tried:

| Source | Serves | Enumerates? |
|---|---|---|
| `tcgdex` | `pkmn:CN-T`, `pkmn:CN-S` | yes |
| `cryst` | `pkmn:CN-S` | yes |
| `wiki52poke` | `pkmn:CN-S`, `pkmn:CN-T` | **no** — names only |

**The headline is the one that is easy to skip past: all three are Pokémon.**
`optcg:CN-S` — Simplified Chinese One Piece, the printing that four of the nine
externally-verified seed identities belong to — still has no catalog source.
Calling these "the Chinese sources" would paper over exactly the gap that
matters most, so `TheFallbackStopsAtTheFirstSourceThatDelivers.test_no_open_
source_covers_one_piece` asserts it and TCGdex's refusal message says it in
prose.

### They are alternatives, not supplements

The fallback stops at the first source that returns cards. Merging two catalogs
that disagree about a collector number would manufacture cards neither of them
lists — and the two Chinese Pokémon printings are precisely where two databases
are most likely to disagree, because one of them renumbers.

### 52poke refuses a capability rather than half-implementing it

It has the standard MediaWiki action API and is the best Chinese-language
reference for both printings, so enumerating a set is *nearly* possible: pick a
category title and page through it. The problem is that the category titles are
in Chinese and I have verified none of them, and **a guessed category title
returns an empty page that is indistinguishable from an empty set.** That is
the exact confusion `ingest_gap` exists to prevent, arriving through the front
door. So `can_enumerate = False` and the adapter offers name enrichment only.

Under CLAUDE.md's rule about fields a source cannot supply: rather than an
enumerate path that half-works, there is no enumerate path.

---

## ADR-0018 — An unverified source failing is a gap, not a failed run

**2026-08-17.** None of the three adapters in ADR-0017 has ever reached its live
service. The environment they were written in cannot: the egress proxy answers
403 to CONNECT for all three hosts. Every URL in them is a candidate, and each
adapter `probe()`s a list rather than hardcoding one guess.

That leaves a real question: what should happen on run #1 when a guess is
wrong? Two bad options and one good one.

- Mark them `expected: true` — a wrong guess fails the run, and one speculative
  source takes down four working providers. That is the bug fixed in `eefa1c3`,
  reintroduced in a new costume.
- Mark them `expected: false` — a wrong guess is silent, and the one experiment
  that could establish the endpoint shape produces nothing to act on.

So: a third status. `unverified: true` in `ingest/sources.yml` downgrades a
first-contact failure to `unverified_failed` — a gap row, exit code unchanged,
**and its own section in the job summary carrying the full error.** The error is
the coverage finding. Run #1 is the experiment; the summary is the result.

Removing `unverified` promotes the source to a hard dependency, which is the
correct state the moment it returns a row. It is one line, and it should be
flipped the day the coverage report comes back positive.

**What is NOT claimed:** that any of this parses a real payload correctly. It
cannot be, until a real payload arrives. What the tests assert is narrower and
is the part that matters now — that every path which does not know something
says so: unreachable is not empty, empty is not unreachable, and a combination
a source does not serve is neither.

---

## ADR-0019 — The collector number is not a key, and the rarity filter proved it

**2026-08-17.** Four documented printing practices, each verified outside this
repository, each breaking naive matching, now asserted in
`tests/test_identity_rules.py`: Treasure Rares and serialized parallels printed
at a base card's number; a Simplified Chinese One Piece box code that does not
correspond to the printed card number and that PSA slabs under; and the two
Chinese Pokémon printings numbering themselves in *opposite* directions. Full
statement in `contracts/card_uid.md`.

Three columns follow: `box_code`, `serialized`, `foil`. `serialized` is
redundant with the variant deliberately — the engine reads the boolean, the uid
reads the variant, and a `CHECK` stops them drifting. `foil` is three-state and
only ever scored when both sides state it.

### The bug this found

`rarity_band()` matched substrings, and every one of the relevant abbreviations
is a substring of the word `rare`: `"ar" in "rare"` is `True`. So **Art Rares
were filed as ordinary rares, and Treasure Rares fell through to `rare` too.**
`ingest/catalog.py` tracks only `chase` and `premium`, which means the target
builder was excluding the top chase rarity in One Piece and the entire Art Rare
tier in Pokémon — the cards this whole engine exists to price. Now regexes with
word boundaries, with a regression test naming the collision.

It went unnoticed because the catalog builder has never run against a live
catalog. A filter that has only ever been applied to nothing looks correct.

### What was deliberately not asserted

The Japanese counterpart numbers for the Simplified Chinese seeds came back
unverified, so no seed claims one. Both verified Simplified set codes end in
`C`; that is two observations, not a naming rule, and `SET_CODE_SUFFIX` records
only the documented CN-T `F` rule. A test asserts the absence, so a later
session cannot add the pattern without deciding to.

---

## ADR-0020 — Run #4 died in a report, and reports cannot be allowed to fail

**2026-08-17.** Fifteen seconds, exit 1, no database, no results file, empty
summary. Not a missing dependency and not an import error — a clean venv built
from `requirements.txt` alone imports every adapter and runs all 420 tests.

`Adapter.preflight()` returned a **different shape** for a keyless source:

```python
if self.key_env is None:
    return {"source": ..., "key_required": False, "ready": True}   # short
```

and the workflow's reporting step read `key_length` on its `ready` branch. Five
key-bearing adapters had exercised that branch for months. The three keyless
catalog sources were the first to reach it, and `KeyError: 'key_length'` ended
the job before any provider ran.

Three separate faults, and fixing only the first would have left the shape of
the failure intact.

### 1. A contract whose shape depends on a branch

`preflight()` now returns every key always. A contract that varies by branch
only holds on the branches something has exercised, and nothing had ever
exercised the keyless one.

### 2. The report lived where no test could reach it

It was a Python heredoc inside a YAML file. Nothing in `tests/` can import a
heredoc, so no test could have caught this — and the step that explains a
failure is exactly the step that must not have untested code in it. Moved to
`ingest.runner.render_preflight()`, invoked as `python -m ingest.runner
--preflight`, and exercised against a keyless adapter, an adapter whose
`preflight()` raises, and a module that will not import. It is also
`continue-on-error` now: **a report must never be able to fail the run it is
reporting on.**

### 3. New code executed in the same breath as working code

The real fault. A single line in the newest, least-verified adapters stopped
four providers that had nothing to do with it.

`ingest/registry.py` now imports each adapter module independently, inside a
try, and the three unverified adapters live in their own module
(`ingest/catalog_sources.py`) so a syntax error there is containable at all.
The result mirrors what `sources.yml` already does for absent keys:

| | outcome |
|---|---|
| import fails, source `unverified` | gap with the traceback, run continues |
| import fails, source expected | failure — but **after** the others ran and the summary rendered |

Containment is not forgiveness. A verified provider whose code broke still
exits 1. What changed is that it no longer exits 1 *early and silently*.

The runner iterates `ALL_SOURCE_NAMES`, not `ADAPTERS`. A broken source is
absent from `ADAPTERS`, and iterating that would make it vanish from the run
entirely — no row, no gap, no line in the summary. That is the same silent
disappearance the gap rows exist to prevent, arriving through a different door.

Verified by breaking `catalog_sources.py` on purpose: preflight named the
syntax error and its line, all eight sources produced results, the database and
results file were written, and the three broken sources came back
`unverified_failed` without failing the run. Seven mutations, all caught.

### The check that should have existed

`60ade11` — CI red for days because `jsonschema` was undeclared and the session
environment happened to have it — was verified in a clean venv **once, by
hand**, and never made permanent. It is now a workflow step: every adapter
module must import from `requirements.txt` alone, and a broken one is reported
with its traceback. A one-off verification is a verification of one commit.
