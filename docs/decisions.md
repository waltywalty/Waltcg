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

> **AMENDED 2026-08-25 (see ADR-0054).** Everything below assumes GROUND TRUTH
> IS CORRECT, and never says so. Measured precision is capped at `(1 - e)`
> where `e` is the ground-truth error rate, so the table's thresholds are
> reachable only while `e` is small — and `e` has never been estimated. Three
> errors are already known in this set, all found by cross-batch comparison
> rather than by a check. At n=250 the 0.98 threshold allows five errors; if
> `e` is around 1%, label noise consumes half that budget before the resolver
> is asked anything. The numbers below are unchanged and still correct as
> arithmetic; what was missing is the premise.



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

---

## ADR-0021 — Run #5 was green with no prices in it

**2026-08-17.** 8,313 rows ingested, seal intact, exit 0 — and tcgapi, PPT and
apitcg each reported *"0 calls made this run"*. `ingest/targets.json` was still
the hand-authored stub with an empty card list for every price source, so each
adapter looped over nothing and returned nothing.

Two independent faults, and the second is the one worth the ADR.

**The ordering.** `python -m ingest.catalog --write` was never run in the
workflow. The catalog step now runs *before* the ingest step in the same job,
and the targets it wrote are summarised so a zero is visible at a glance.

**The status.** A source handed nothing returned nothing, which read as
`empty` — "reached the source, it had nothing to say" — and `empty` does not
fail a run. Meanwhile tcgdex had ingested thousands of catalog rows, so
`decide_exit` found a source that ingested and returned 0.

But those adapters were never *asked*. Never-asked and asked-and-empty are
different facts, and one of them means the day has no prices. `no_targets` is a
failure, and a price adapter now declares `requires_targets` so the runner can
tell. The ordering fix is the guard; this is the backstop, and the backstop is
the part that cannot be un-fixed by a future workflow edit.

`test_the_old_behaviour_would_have_passed` pins the bug: same two sources with
`empty` instead of `no_targets`, and the run goes green.

---

## ADR-0022 — HTTP 200 with an error body, for the ninth time

**2026-08-17.** Alpha Vantage rate-limited on run #5 against a free tier of 25
a day and **5 a minute**. The daily cap was never in play. Three things
conspired: five pairs where three are needed, `max_attempts = 4` behind each so
up to twenty requests in a couple of seconds, and — worst — a *retry on a
throttle*, the one error where retrying immediately is guaranteed to fail and
to deepen the hole.

Fixed with a 13-second floor between calls (5/min = one per 12s, plus a second
of headroom), `max_attempts = 1`, three pairs instead of five, and a same-day
rate cache so a run that loses the last pair does not also lose the ones it
already had. Losing a whole day to one throttle puts a gap in every converted
figure, and the engine refuses to convert without a rate.

Rate limiting is deliberately **separate from quota**. Quota is "how many are
left today"; rate is "how fast may I go right now", and a provider can refuse
you on the second while the first still says you have plenty.

### The part that generalises

The throttle arrived as **HTTP 200 with an `Information` key**. That is the
ninth time this project has met a 2xx carrying an error, across five providers.

The detection existed — and it was *worse than absent* where it looked
strongest. `FxAlphaVantageAdapter` declared:

```python
ERROR_KEYS = ("Error Message", "Note", "Information")
```

which **replaced** the base class list rather than extending it. So the FX
adapter gained Alpha Vantage's three markers and silently lost all five generic
ones, while every other adapter never learned that `Note` or `Information`
means "you are being throttled". A shared guarantee that a subclass can
overwrite by assignment is not shared.

Now: `ERROR_KEYS` is the shared vocabulary and `EXTRA_ERROR_KEYS` is how a
provider adds its dialect, with `error_keys()` merging both. Matching is on a
normalised key, because `Error Message`, `error_message` and `errorMessage` are
one marker arriving from three providers and a literal comparison catches one
of the three. A test asserts every registered adapter knows every shared
marker — the property, not the instance.

---

## ADR-0023 — tcgdex verified; cryst superseded; the Chinese combos automatable

**2026-08-17.** Run #5 measured what ADR-0017 could only guess at: **tcgdex
covers `pkmn:CN-S` (877 cards) and `pkmn:CN-T` (7,436).** `optcg:CN-S` remains
uncovered and stays manual.

**tcgdex loses its `unverified` flag.** It is now a hard dependency, which is
the correct state for the only catalog source either Chinese Pokémon printing
has: a failure there should fail the run.

**cryst is superseded, not deleted.** Its endpoint guess was wrong
(`tcg.mik.moe/api/sets` returned non-JSON) and tcgdex covers everything it was
for. Left in the rotation it would spend a request every run proving a
known-wrong URL is still wrong, and file the answer as a gap that reads like
missing data. It stays in `sources.yml` with `superseded_by` and a note,
because *"we tried this and it was superseded"* is a different fact from *"we
never considered it"* — the next session should not rediscover tcg.mik.moe from
scratch.

**wiki52poke stops counting as a gap.** Enrichment-only is a capability
statement, not a defect to fix. A run with nothing to enrich is
`enrichment_idle`. Filing it as a gap every day devalues the gap rows that mean
something.

### The 55 cards no longer have to be typed

`label_cli propose --source tcgdex` pulls both Chinese Pokémon combos live,
with the **Japanese** printing alongside — not as a target, but because the
sharpest test in the set is a Chinese card against its Japanese parent and you
cannot build that pair from one side of it.

This does not weaken ADR-0016, and the distinction matters: ADR-0016 refuses
*generating labels* from the catalog the resolver reads. This generates
*proposals* from it. The human verdict that breaks the circle is unchanged;
what changed is that the proposal no longer comes from memory.

**The two pairings need two mechanisms, because CN-T and CN-S are opposites.**
CN-T reuses the Japanese numbers, so parent and child land in the same bucket
and the existing number-keyed rule finds them — the *merge* case. CN-S
renumbers, so there is no shared number and that rule finds **nothing** — the
hardest pair in the set was invisible to the mechanism built for it. The new
rule keys on the illustrator, which does not change between printings.

That is a weaker join and it is labelled as one. Where several Japanese cards
share an illustrator, the candidate is proposed **without** a parent and says
the pairing is the open question. A wrong pairing rejected by a human costs one
click; a wrong pairing accepted silently costs the measurement.

---

## ADR-0024 — Run #7: the report that could not report

**2026-08-17.** The `no_targets` backstop fired exactly as designed — all three
price sources reported NEVER ASKED, FX was fixed, tcgdex ingested 8,313. And
the job summary contained **no catalog section at all**, so the one question
that mattered was unanswerable.

The catalog step was present and correctly ordered. It ran. It found zero
cards, and `ingest/catalog.py` returns 1 when the total is zero. GitHub runs
`bash -e`. The script aborted on that exit code, and the `{ ... } >>
$GITHUB_STEP_SUMMARY` block that would have **explained** the zero never
executed. `continue-on-error: true` then hid the failed step.

**This is run #4 repeating.** That failure was a Python heredoc inside YAML
that no test could reach; ADR-0020 moved the formatter into tested Python and
said so. Then the next thing that needed a report got a shell block, and the
shell block failed in a new way. Twice is a pattern, so the rule is now
asserted rather than remembered: `NoStepPutsLogicInAShell` parses the workflow
and fails on any step containing a heredoc. There are none left.

`ingest.catalog --summary` writes its report **before** the exit code is
returned. No exit code and no shell option can suppress it.

### What the zero was actually hiding

Walking the routing answered the real question. `ingest/catalog.py` reaches
tcgapi for `optcg:EN`, `pkmn:EN`, `pkmn:JP`, `riftbound:EN`; apitcg adds
`optcg:JP`; tcgdex serves the two Chinese Pokémon printings; `optcg:CN-S` has
nothing. So tcgapi and apitcg are **both catalog and price sources**, and the
ingest step's "0 calls" said nothing about whether the catalog step called them
— different adapter instances, separate accounting. The summary now reports the
catalog step's own call counts.

And the endpoints it calls were **never verified**. `probe/COVERAGE.md` records
a 200 from tcgapi `/v1/games` and `/v1/search`, and from apitcg
`/api/{game}/cards?name={name}`. It records nothing about `/v1/sets`,
`/v1/bulk`, `/v1/cards`, or apitcg enumeration by page. Those four were
invented in the catalog builder and used as facts.

That is the same class of guess as the superseded `cryst` adapter, with one
difference that mattered: **cryst was marked unverified, so its failure read as
a finding.** These were not, so a wrong URL came back as "this combination has
no chase cards" and the catalog quietly wrote nothing. They are probed now, in
the same way, and which candidate answered is reported.

### Zero has four meanings

| Verdict | Means |
|---|---|
| `ok` | cards found |
| `catalog_ran_empty` | asked, answered, nothing in a tracked rarity band |
| `source_unreachable` | asked, no answer — a wrong endpoint lands here |
| `no_catalog_source` | nothing serves this combination; it is manual |

Plus a fourth absence that is not a combo verdict at all: **the catalog never
ran**, which `describe_target_absence` detects from a missing `_generated_at`
and reports differently from all of the above.

One bug fell out of writing this down. `sets_for` recorded tcgapi's missing
game entry as `no_catalog_source`, which made `pkmn:CN-S` report "nothing
serves this" while tcgdex was serving it 877 cards. It is a fact about tcgapi,
not about the combination; it is `tcgapi_no_game_entry` now, and the
combo-level verdict is computed at the end from every source that was actually
asked.

---

## ADR-0025 — The filter read a field that was not there

**2026-08-17.** tcgdex's brief card object — what `GET /v2/{lang}/cards` and
the `cards[]` array inside `GET /v2/{lang}/sets/{setId}` return — carries `id`,
`localId`, `name` and `image`. **There is no `rarity`.** The catalog builder
filtered on `rarity` anyway, `rarity_band(None)` answered `base`, `base` is not
tracked, and 8,313 cards produced zero matches.

The filter was not too tight. It was reading a field that was never there, and
the absence looked exactly like "none of these are chase cards".

**The rule that follows is the whole thing: an absent rarity is UNKNOWN, never
"not a chase card".** `band_of(None)` returns `unknown`, `unknown` is a TRACKED
band, and the residue is counted and reported. Tracking a card we cannot
classify costs quota; dropping one loses a chase card and says nothing.
`test_the_old_behaviour_would_have_dropped_everything` pins the substitution.

### Verified from source, and the transcription was short

`interfaces.d.ts` fetched from raw.githubusercontent.com — reachable from here
even though `api.tcgdex.net` is not. The union has **43 members, not 29.** The
fourteen that were missing from the brief:

- `Triple Rare`
- **`Character Rare`, `Character Super Rare`** — Japanese Character Rares,
  since SM11b Dream League. These matter more here than anywhere: this project
  tracks JP and both Chinese printings, and omitting them repeats the exact bug.
- `Promo`
- ten Pokémon TCG Pocket rarities

Two classification calls that are mine, not the brief's, and worth arguing with:

- **`Double rare` is `rare`, not tracked.** It reads like a chase tier and is
  the ordinary two-star `ex` — a couple of dollars, several thousand per set.
- **The Pocket rarities get their own `digital` band.** Pokémon TCG Pocket is a
  digital game. There is no physical card to grade, no submission to make and
  no population to read. They are not cheap cards; they are not cards.

### What the live check is still for

`ingest.catalog --rarities` asks each dataset what it actually contains and
diffs it against English. It has NOT run — `api.tcgdex.net` is unreachable from
here. The documented enum and the populated one are different questions and
only the runner can answer the second.

### Three strategies, and the choice is measured

`?rarity=` server-side first, GraphQL second, per-card N+1 last. A query
parameter a service ignores returns the FULL list, which reads as "every card
is a Special Illustration Rare" — a filter that matched too much rather than
one that did not run. So `filter_is_honoured` compares a filtered count against
an unfiltered one before trusting it.

Writing that check found a bug in itself: it probed with a hardcoded
`Special illustration rare`, so any dataset not holding that rarity would
report "filter ignored" and pay 8,313 single-card fetches for the wrong answer.
It probes with a rarity the dataset actually lists.

### The SIR/SAR collapse

tcgdex normalises two different market conventions into one string. A `Special
illustration rare` is a SIR in English sets and a SAR in Japanese ones, and
this repository has always kept them apart — `pkmn:sv3:223/197:sir:EN` and
`pkmn:sv3:108/108:sar:JP` are the same art in two markets with two price
series. The provider cannot tell them apart, so the **language** does. It is
the only information that survives the normalisation.

---

## ADR-0026 — Two providers, two wrong endpoints, one readable spec

**2026-08-17.**

**apitcg was wrong in the host AND the path**, which is why every run got a
non-JSON body — `apitcg.com` serves an HTML single-page app. Read from
`raw.githubusercontent.com/apitcg/docs.apitcg.com/main/openapi.json`:

| | was | is |
|---|---|---|
| host | `apitcg.com` | `api.apitcg.com` |
| cards | `/api/{game}/cards` | **no such endpoint** — `/api/products?type=card` |
| paging | invented | `limit` (≤100) + `page`, with `total` in the envelope |
| rarity | top-level | `attributes.Rarity`, a free-form map |

Anything absent from that file is treated as non-existent rather than as
missing data. And `attributes` holds each game's OWN vocabulary — One Piece's
`R`/`SR`/`SEC`/`TR`, not tcgdex's normalised English — which surfaced a second
instance of the same bug: `SR` and `SEC` were scoring `base` and being dropped.

**tcgapi's set and card paths are slug-based and nested**, not numeric:
`/v1/games/{gameSlug}/sets/{setSlug}/cards`. The numeric ids address
`/v1/search` and `/v1/games` and nothing else, which is why all three
query-string shapes probed in run #8 returned 404.

The slugs are confirmed and the obvious guesses are wrong in the quietest
possible way: tcgapi calls One Piece `one-piece-card-game`, while **apitcg
calls the same game `one-piece`**. Two providers, two vocabularies for one
game — exactly what `resolve/identity.py` exists to keep apart.

Only English slugs are recorded. `pokemon-japan` is a plausible guess and
plausible guesses are what cost run #7, so any other language is resolved at
runtime from `/v1/games` — a verified endpoint — and a slug that cannot be
resolved is a gap, not an invention.

---

## ADR-0027 — Stop guessing rarity; read each game's vocabulary

**2026-08-17.** `rarity_band` was wrong twice — Art Rares and Treasure Rares
filed as ordinary rares, then One Piece `SR` and `SEC` filed as base. Both
times a regex over an OPEN set of strings guessed, and both times it guessed
LOW: a chase card classified as not worth tracking.

A third instance was already waiting, in the game I was least equipped to
guess about:

| Riftbound rarity | was | is |
|---|---|---|
| `Epic` | **base** | premium |
| `Showcase` | **base** | premium |
| `Overnumbered` | **base** | **chase** |
| `Alternate Art` | premium | premium |

`Overnumbered` is Riftbound's chase treatment, and `overnumbered` was already a
variant token in `resolve/identity.py` while the band table scored it `base`.
Three of seven, including the top one.

And it was not only Riftbound. `SCR` (Dragon Ball Secret Rare) — `\bsec\b`
never matched it. `LR` (Gundam Legendary Rare). `Rare Holo Star` — **Gold
Star**, among the most valuable Pokémon cards there are, scored `rare` because
the string contains the word.

### Read, don't imagine

`raw.githubusercontent.com` is reachable from here even though the provider
APIs are not, so the vocabularies come from the games' own data:
`github.com/apitcg/{game}-tcg-data`, every card file, distinct values of
`rarity`. **81 distinct strings across 7 games**, checked into
`contracts/rarity_vocabulary.json` and refreshable with
`python tools/rarity_vocabulary.py --write`.

Strings only — no counts, no prices, no payloads. A vocabulary is not provider
data and keeping counts out of it keeps that obviously true.

`tests/test_rarity.py::test_every_string_in_every_tracked_game_maps` asserts
every one of them maps to a named band. That test is the point of the whole
exercise: it is the thing that would have caught all three instances.

### One table per game, because the letters collide

`R` is Rare in One Piece and Union Arena. `P` is Promo in One Piece and Gundam.
`L` is Leader in One Piece and Legend in Dragon Ball. `LR` is Gundam's chase
tier and means nothing in Riftbound. One shared table would have to pick, and
picking is the guessing this ADR exists to stop.

apitcg's **Pokémon** vocabulary is TCGplayer-style and is *not* tcgdex's —
`Rare Ultra`, `Rare Secret`, `Rare Holo EX`, and a `Trainer Gallery Rare Holo`
that tcgdex does not have at all. Both are served, so both are mapped.

### An unmapped string is named, never dropped

New sets add rarities; that is not a failure. `band_of` answers `unknown`,
`unknown` is TRACKED, and `render_catalog_summary` **names** the string and the
combination it appeared in. The three earlier failures were all silent — a
finding that is not named is a finding that is lost.

### Two things found on the way

**Parallel markers were being thrown away.** Gundam writes `LR                +`
and Union Arena writes `SR★★`. Normalisation strips the marker for banding,
which is right — it is the same tier — but the marker is a *finish*, and the
finish is worth more than the tier. `variant_from_rarity` now reads it as
`parallel`, so the information moves rather than disappearing. Without that, a
parallel and its base card become one card.

**Digimon's repository carries no `rarity` on any card**, and
`star-wars-unlimited-tcg-data` is empty. Neither is a classification failure;
both are coverage facts, and they are recorded so the next session does not
re-derive them. Every Digimon card classifies `unknown`, which is tracked,
which is correct.

---

## ADR-0028 — Band is a function of the collector number, not the rarity string

**2026-08-17.** Checked against market data. My `Epic` call was right and the
`premium` instinct wrong — Riot's designer puts Epic at roughly one in four
packs, six a box, singles $5–55. But the ordering was the smaller half of it.

**Riftbound's `Showcase` is an umbrella covering three treatments at wildly
different values, all printing the same rarity string:**

| number | treatment | value |
|---|---|---|
| `227*/221` asterisk | Signature | $300–3,090 |
| `227/221` above the set size, no asterisk | Overnumbered | $75–660 |
| `119a/298` `a` suffix | Alternate Art | $40–90 |

A $3,000 card and a $50 card, indistinguishable by rarity. **Parse the number.**

The evidence: of the top 16 most valuable singles, every one is Metal,
Signature, Ultimate or an event promo. No plain Overnumbered until #17. Zero
Epics and zero plain Alt-Art anywhere in it.

The observed apitcg data makes the same point from the other side —
`299*/298`, a Signature by the rule above, is labelled **`Alternate Art`**
there, while `Showcase` appears on runes. The string is unreliable in *both*
directions.

### Generalised, not special-cased

`NUMBER_DEPENDENT_GAMES` declares which games band on the number, and
`band_of` **raises `NumberRequired`** when called for one without it. Noisy on
purpose: banding a Riftbound card on its string cannot separate a $3,000
Signature from a $50 Alt-Art, and a wrong answer there is worth more than a
crash. The next game that does this gets added to one frozenset and every call
site is already correct.

`resolve/identity.py` gained `parse_collector_number`, and it is now the single
place the number is read — `variant_from_number` and the banding both consume
it. That closes the split that let the variant token know about `overnumbered`
for three sessions while the band table scored it `base`.

**One restriction is load-bearing.** `NUMBER_VARIANT_GAMES` is Riftbound only,
because in Pokémon a number above the set size is *ordinary* — every secret
rare is numbered that way, and `170/151` is an Art Rare. Applying Riftbound's
rule game-wide relabelled the entire Pokémon secret-rare tier, which is how the
test suite caught it.

### Two answers that are deliberately not answers

**Promo (`b` suffix) bands `unknown`.** The number says it is a promo and says
nothing about which; the range runs from a few dollars to $1,300, spanning
three bands. `unknown` is tracked and named, which is the honest output when
the evidence identifies the treatment but not the tier.

**Core-champion Alt-Art is unresolved.** The market separates a core champion's
alt-art from an ordinary one; no verified champion list exists, so
`RIFTBOUND_CORE_CHAMPIONS` is empty and every Alt-Art bands `rare`. This
UNDER-tracks — a $40–90 card is dropped — and that direction is deliberate, but
it is an error and it is registered rather than assumed away.

### Sets, and one thing recorded rather than fixed

Two main sets sat between Origins and Vendetta and neither was in our list.
`RIFTBOUND_SETS` now carries all five with base counts, which is what lets a
bare `OGN-301` be placed at all. Radiance has `base: None` — announced, not
released, and `above_set_size` answers `None` rather than `False` when the
ceiling is unknown.

**The apitcg data repository stops at Spiritforged**, so our catalog source is
two sets behind the game. `Signature`, `Metal`, `Prize Wall` and `Ultimate
Rare` are therefore in the band table but absent from the observed vocabulary —
which is why the coverage test asserts observed ⊆ mapped rather than equality.

**OPEN QUESTION, recorded and NOT acted on.** Simplified Chinese launched
*first* for Origins — August 2025 against October 2025 — with parity from
Vendetta. `GAME_LANGUAGES` still says Riftbound is English-only. Adding CN-S
creates a ninth game/language combination and changes the labelled-set targets
and the 250-card gate; that is a scope decision, not a correction, and it is
yours to make.

### Caveats recorded, not resolved

Registered as `riftbound_band_thresholds` (confidence `low`) and
`riftbound_core_champion_alt_art` (`unvalidated`), both with UI chips. The
calibration note is blunt about it: **the ordering is the claim, not the
prices.** Sub-one-year market, volatile, and the Alt-Art figures are mostly
asking prices rather than confirmed sales. The bands say which cards are worth
spending price quota on. They are not evidence about magnitudes and must never
be cited as such.

---

## ADR-0029 — Run #9: 5,582 cards, and three of them were routing

**2026-08-17.** First real target list. Four changes.

### The four named strings

`Rainbow Rare` and `Shiny Holo Rare` chase — the second is Shiny Vault / Gold
Star territory and reads like an ordinary holo, which is exactly the trap.
`Prism Rare` premium. `Unconfirmed` maps to **UNKNOWN deliberately**: it is a
placeholder the source writes when it does not know, so it *is* classified —
as "the source is not telling us" — and stops being reported as unmapped every
run while staying tracked.

One Piece `PR` is Parallel Rare: premium, and **also `variant=parallel`**,
since it is a foil treatment of a card that also exists plain — the same thing
the Gundam `+` and Union Arena `★` markers mean.

That needed a per-game variant rule, because **`PR` is Dragon Ball Fusion's
PROMO**. Two letters, two games, two meanings, which is the same argument that
put the band tables per-game in the first place. Vocabulary re-run afterwards:
nothing else moved.

### tcgapi demoted to price-only

apitcg made 250 calls and supplied every combination it serves; tcgapi made 1
and hit 0/100. It contributed nothing to the catalog and was the only thing
failing the run — and the 100 calls it burned there were 100 it did not spend
on prices, which is the one job it is still good at.

`role: price` in `sources.yml`, and the catalog builder never touches it. The
test is blunt about it: a tcgapi that raises on *every* attribute access must
not affect a catalog build.

### pkmn:JP was a routing bug with three causes

You asked whether tcgdex was unregistered for JP or apitcg's slug was
English-only. **Both, plus a third:**

1. `TcgdexAdapter.serves` listed only the two Chinese printings — while `LANG`
   mapped `JP → ja` and the rarities report showed 17 distinct Japanese
   rarities including Character Rare. The data was reachable; the registration
   was not there.
2. `APITCG_LANGUAGES["pkmn"] = ("EN",)`.
3. The fallback that would have caught it was **gated to CN-S and CN-T**.

Three things all pointing the same way, which is why the output looked
consistent. tcgdex now declares all four Pokémon printings, and the fallback
fires for any combination the commercial sources leave empty.

Splitting the fallback's failure reasons fell out of it. `{src}_no_cards`
covered four different outcomes and the status classifier read all of them as
unreachable, so "we asked and it had nothing" was reported as a broken
endpoint. Now `_unreachable` / `_empty` / `_does_not_serve` /
`_does_not_enumerate`, and only the first is unreachability.

### The English fallback was never wired up

CN-S carries 5 distinct rarities and CN-T 6, against English's 40, and between
them they produced one tracked card. Thin, not absent — so borrowing English's
rarity by id is how a Chinese card gets classified at all, not an occasional
patch. Promoted, and registered as `chinese_rarity_from_english` with a UI
chip.

**And it had never run.** `english_index()` existed and nothing called it, so
`resolve_rarity` was always handed `None` and every Chinese card without its
own rarity stayed unknown. Given how thin those datasets are, that was most of
them.

Writing the test for it surfaced a second bug: GraphQL returns `set` as an
object with an `id` while REST returns `set_id` as a string, and the code
stringified the object — producing `{'id': '151C'}` as a set code, which
`card_uid` rejected. **Every GraphQL row was being silently dropped**, so that
whole strategy looked like it returned nothing.

The assumption's calibration note records what it rests on: that tcgdex ids are
stable across languages, and that rarity is a plain enum rather than a
localised type so the English value is the *same* value rather than a
translation. The second is schema-derived and still unconfirmed against an
observed Chinese response body — re-check the `--rarities` diff each run, and
if the Chinese lists start growing toward English's 40, the borrowing should
stop and the printed value should win.

---

## ADR-0030 — Run #10: three regressions, one of them mine, and 24 boxes

**2026-08-18.** Run #10 reported Riftbound halved, `pkmn:JP` / `CN-S` / `CN-T`
at `no_tracked_cards`, and no sign of the English fallback. Three symptoms,
two causes, and a fourth thing found on the way that nobody had asked about.

### Riftbound 584 → 287 was not a bug

The suspicion was `NumberRequired` raising on a card whose collector number
would not parse, and it was wrong: measured against apitcg's full Riftbound
data (699 cards, three sets), **zero cards have an unparseable number**. The
drop is the reband from ADR-0028, working as instructed. In that sample:

- `Epic` premium → rare removes **88** cards
- `a`-suffix `Alternate Art` → rare removes **30**

118 of 699, which is the same proportion as the live 584 → 287.

The guard went in anyway, because "it does not happen yet" is not "it cannot
happen": `_riftbound_band` now returns UNKNOWN — which is TRACKED — for a
number it cannot read, whatever the rarity string says. The strings are chosen
in the test so the string table *could* have answered (`Common` → base,
`Overnumbered` → premium); banding on the word is precisely the failure for a
game whose band IS the number. Each such card is counted and its number
sampled into the summary, so the next time the answer is a measurement.

The measurement also found a real bug of its own: `RIFTBOUND_SETS` is keyed by
printed set code (`OGN`) and apitcg returns slugs (`origins`), so `set_size`
was `None` for every Riftbound card and no bare number could ever be placed
above the set. `RIFTBOUND_SET_ALIASES` maps them. Silent, because `None` is a
legitimate answer meaning "ceiling unknown".

### `no_tracked_cards` on three combos was one bug in three costumes

`GET /v2/{lang}/cards?rarity=` returns **brief objects** — `id`, `localId`,
`name`, `image`, and no set field of any kind. `_set_code_of` found no set,
`_catalog_row` refuses a row without one, and every row from the server-side
filter strategy was dropped. From outside that reads as "this combination has
no cards in a tracked band", which is a coverage fact, and it was a routing
fault. The set is recoverable: tcgdex ids are `{setId}-{localId}`.

This is the same shape as ADR-0029's GraphQL `set`-object drop, one strategy
over. That fix was real and did reach the Japanese path; it just was not the
strategy JP took.

**The test suite passed throughout, because the fixture invented a `set_id`
key the endpoint does not send.** The fixtures now carry the real brief shape,
and a test asserts the fixture has no set field — a guard on the guard.

The English fallback did run. It could not show, because the rows it enriched
were dropped afterwards for want of a set code.

### A drop that nothing counts will happen again

Both of the above were invisible for the same structural reason:
`enumerate_combo` returns survivors, so an adapter that fetched 7,436 cards and
dropped all 7,436 is indistinguishable from one that fetched nothing. The
adapter now counts `hits_seen` and `dropped_no_identity`, the builder folds
them into a per-combo stage table — provider_hits → dropped_no_identity →
fetched → dropped_no_number → dropped_no_set_code → dropped_not_a_card →
parsed → unreadable_number → dropped_bad_uid → tracked, plus the band split —
and the summary prints it. The en_fallback count prints even when it is zero,
with "NONE. Either no Chinese card needed it, or the English index did not
run" — the two things run #10 could not tell apart.

### `Showcase` and `Promo` are classified, not unclassified

Both map to UNKNOWN **on purpose**: the word cannot say. `Showcase` spans
Signature, Overnumbered and Alternate Art, $40 to $3,090. Listing them beside
strings nobody has looked at sends the reader to `GAME_BANDS` when the problem,
if there is one, is in the number parser. `deliberately_unknown()` separates
them, and the summary gives them their own section — "Classified rarity,
unreadable number" — with the offending numbers.

### 24 boxes were queued for pricing

Not asked for, found while measuring. apitcg's Riftbound set lists carry
`Origins - Booster Pack`, `Champion Deck (Jinx) Display`, `Riftbound: Bulk
Runes Case` and 21 others alongside the cards, each with a collector number and
a set. They have no rarity, absent rarity is UNKNOWN, and UNKNOWN is TRACKED —
so **24 of the 91 tracked Riftbound identities in the local sample were sealed
product**, 26% of the target list.

The rule that put them there is correct and stays. It is a rule about cards.

The discriminator is the provider's own: `cardType` **present and null** *and*
`rarity` null. Present-and-null is the entire test — a payload that omits the
field says nothing about card-ness, and reading silence as a verdict would
delete all 20,132 apitcg Pokémon rows and every tcgdex brief. Verified across
23,320 rows: 24 hits in Riftbound, 0 in One Piece, and Pokémon carries no such
field so the rule cannot reach it. Dropped, counted as `dropped_not_a_card`,
and each one named in the summary — a silent drop here is how a real card
leaves by the same door later.

Riftbound tracked, local three-set sample: **91 → 67**.

### The mutation harness sabotaged the repository

It timed out mid-mutation and left `deliberately_unknown` returning a constant
`False`, which the next test run reported as a regression in the code under
test. It now restores in a `finally`. All eleven guards above are mutation-
tested and all eleven are caught.

---

## ADR-0031 — Run #11: stop asking, and stop re-deriving

**2026-08-18.** The brief-object fix landed and pkmn:JP came back with 658
cards, CN-T with 3. That bug is closed. Then apitcg started refusing: 429 after
four attempts on 16 calls, where run #10 had made 250 without complaint. Every
apitcg-served combination went to zero. pkmn:EN survived only because tcgdex
covered it.

### Four attempts against a 429 is four ways to be refused

A 429 is not a failure. It is an **answer**, and the answer is "not now" —
which makes it categorically different from an endpoint that does not respond.
One is fixed by waiting; the other needs a code change. Retrying it four times
turns one refusal into four, and with 16 calls behind that budget, up to 64
requests reached a service that had already said no.

Now: `Retry-After` is read if sent (both RFC 9110 forms — delta-seconds and
HTTP-date, because reading only the integer turns a date into "no Retry-After
sent", an answer misread as silence, which is this project's oldest bug shape).
Exponential backoff otherwise. **After the second refusal the adapter is closed
for the rest of the run** and every later call raises `RateLimited` without
touching the network. A `Retry-After` longer than the run can wait closes it on
the first.

`RateLimited` is deliberately not a subclass of `AdapterGaveUp`, and a combo
that hit one is `rate_limited`, never `source_unreachable`. Filing a refusal as
unreachability sends the next session hunting for a broken endpoint that works
fine.

### We still do not know apitcg's quota, and now we are measuring it

It is not in `openapi.json`, not on the docs site, and not in any header — and
we would not have known about the header either, because `_send` returned
`(status, body)` and threw the response headers away one frame below where they
were needed. It returns them now, every rate-related header is kept **verbatim**
(names as sent, values as sent — a tidied header is one we have already begun
interpreting), and the job summary prints them.

`config/rate_limits.yaml` is the dated record. Two observations so far — 250
calls on the 17th, refused after 16 on the 18th — and the honest reading is
written down with them: that shape is more consistent with a per-minute or
per-hour window than a daily quota, and two points is not enough to say. The
adapters do not read this file. It is a record, not a knob; enforcing a guessed
ceiling would make one bad day's observation permanent.

A provider that publishes nothing is recorded as publishing nothing. That is
the measurement which justifies inferring a ceiling from call counts at all.

### The catalog is persisted, and that is the actual fix

Sets release monthly. Re-enumerating all eight combinations every morning spent
the entire provider budget re-deriving an answer that had not changed — and
then had nothing at all when the provider started refusing.

`ingest/targets.json` (already tracked; card identities only) now carries a
per-combination `as_of`. A combination younger than seven days is served from
it and **no provider is called at all**. The status is `catalog_from_cache`
with its age, never `ok` — a cached catalog and a fresh one are different facts
even when the cards are identical. `--force` re-enumerates everything.

The cache is reconstructed from the per-source card lists rather than stored a
second time: every target row already carries its own `game` and `language`, so
a duplicate copy would be one more thing that can disagree with itself.

Three details that are the whole design:

- **A failed refresh falls back to the cache** and reports
  `catalog_from_cache_stale` with `refresh_failed`. That is the point — a
  throttled provider costs nothing, because yesterday's answer is still the
  answer.
- **Unknown age is never fresh.** `cache_age_days` returns `None`, not zero,
  for an entry with no `as_of`. Treating unknown as fresh is exactly how a
  stale catalog starts looking like a fresh one.
- **A cached combination carries its original stamp forward.** Restamping it
  with today would make it immortal: refreshing its own timestamp every run
  without ever being rebuilt.

The commit-back is guarded three ways, because the failure mode is asymmetric —
a bad commit here overwrites the cache and makes one bad day permanent.
`--persist-check` refuses a file with zero cards or an undated combination; the
commit runs only if that check passed (a step-level `if:`, not a bash
conditional); and the data guard has already run. Default branch only.

The step uses `if git diff --cached --quiet; then` rather than
`git diff --quiet && echo && exit 0`. GitHub runs `bash -eo pipefail`, and a
failing AND-list as a standalone statement aborts the step — so the "there ARE
changes" branch would have died instead of committing. That is runs #4 and #7
for a third time, caught before it shipped, and there is a test asserting no
step contains the pattern.

### Which source served this, against which one should have

`tcgdex` under pkmn:EN read as ordinary operation. It meant apitcg had been
refused and the fallback caught it. The expected source is now **declared**
(`primary_source`) rather than inferred from what happened, precisely so the
difference is visible: a combination served by anything else is
`ok_via_fallback`, with its own summary section naming the primary and why it
did not deliver.

### 234 One Piece card_uids were collisions

Found by round-tripping the cache: 737 rows went in and 451 came out. Not a
cache bug — the catalog had been merging them all along, and deduping by
`card_uid` hid it.

`EB01-006`, `EB01-006_p1` and `EB01-006_p2` are three printings of one card at
**one collector number**, all carrying rarity `SR`. Neither the number nor the
rarity string can separate them, so all three collapsed into
`optcg:eb01:EB01-006:base:EN`. 286 rows swallowed — 39% of the One Piece
catalog — and the parallels are the expensive ones. Non-negotiable 3 says every
printing is a different card, never merged in a join or an aggregation. This
was a merge.

The suffix is Bandai's own: the official card-list images are `EB01-006.png`
and `EB01-006_p1.png`. `_p1` → `parallel`, `_p2` → `parallel2`, up to
`parallel8` in the observed data; `_r1` → `reprint`. A suffix we do not
recognise becomes `unknown_{suffix}` — **not** `base`, because falling back to
base is the merge this exists to stop, and inventing a name is the other way to
be wrong.

Scoped to One Piece, and the restriction is load-bearing. Pokémon uses an
identical-looking suffix for something entirely different: `cel25c-15_A1`
through `_A4` are Venusaur, *Here Comes Team Rocket!*, Rocket's Zapdos and
Claydol — four **different cards** that Celebrations printed at collector
number 15. Calling those parallels of each other would be worse than the
collision it fixed. They are the only three collisions left in the Pokémon
catalog, and they are in `docs/OPEN_ISSUES.md` as S2, unfixed on purpose.

One Piece EN, measured on apitcg's full data: 451 → **737** distinct cards,
414 of them parallels.

### Also

`docs/OPEN_ISSUES.md` did not exist. The session ritual has called for it since
the beginning. It exists now.

All 22 new guards are mutation-tested and all 22 are caught.

---

## ADR-0032 — Run #12: the cache was empty because it had never been written

**2026-08-18.** Rate limiting behaved as designed: two 429s, breaker tripped,
`rate_limited` rather than `source_unreachable`, and apitcg confirmed to send
no `Retry-After` at all. That question is closed and the answer is in
`config/rate_limits.yaml`.

The cache did not serve, and it was **chicken-and-egg, not a bug**. Run #12
checked out `b6ad779`, where `ingest/targets.json` was still the hand-authored
stub — no `_catalog_cache`, no `_counts`, zero cards in every source list. The
cache was genuinely empty, every combination was correctly re-enumerated, and
the persist step then committed `cbdaae6`: 2,673 cards across three stamped
combinations. Run #13 is the first run that can serve from it.

Worth stating plainly because the same evidence would have looked identical if
the token scope had been wrong: **the commit-back ran and pushed**, on a run
that exited 1.

### An empty age column meant three things

`--` rendered identically for "no entry", "an entry with no date", and "an
entry that was re-enumerated anyway", and only the third is a fault. That is
the same silent collapse the verdict taxonomy exists to prevent, one column
over.

Six states now, recorded at the moment the decision to call a provider was
taken: `absent`, `empty`, `undated`, `stale`, `forced`, `fresh`. The seventh
case — `fresh` and enumerated anyway — is the bug, and it gets its own section
headed **BUG** rather than being left to be inferred from a blank cell.
`--force` reports as `forced` and is explicitly not the fault; there is a test
for that, because a fault report that fires on a deliberate action is a fault
report nobody reads.

The threshold boundary falls toward re-asking: seven days old against a
seven-day threshold is `stale`.

### Preservation and freshness are different questions

The real trap. The persist step is not gated on the run's exit code — correct,
and run #12 proved it — but the file it commits is written from **this** run's
catalog, and a combination that failed contributes zero cards to it. Committing
that zero erases yesterday's good answer for that combination, the next run
re-enumerates it, and a provider having a bad morning costs the catalog
permanently. A throttled provider was supposed to cost nothing; that path made
it cost everything.

`build()` already falls back to the cache when a refresh fails, but only when
it was *given* a cache — and `--no-cache` gives it none. So the same rule now
also applies at the file boundary, where it holds regardless:

- `previous` is loaded **unconditionally**. Nothing justifies erasing a
  combination that worked yesterday.
- `cache` is what freshness decisions may consult, and that is the only thing
  `--no-cache` suppresses.

`preserve_from_cache` puts back any combination that came back empty and had
cards before, as `catalog_from_cache_preserved`, carrying its original `as_of`
and recording `preserved_over` — the status it was rescued from. That last
field matters: `rate_limited` preserved is a provider having a bad day;
`source_unreachable` preserved is a bug the cache is now hiding, and the two
have to stay tellable apart.

**Zero is the failure signature, and only zero.** A combination that comes back
smaller has genuinely shrunk — a set delisted, a rarity reclassified — and that
lands. Otherwise the catalog could never get smaller.

Verified end to end against the real committed file under the harshest
conditions available: `--no-cache` with every provider unreachable. All 2,673
cards kept, all three stamps carried forward, all three statuses distinct from
`ok`.

### Also

`docs/OPEN_ISSUES.md` was added last session without a row in
`docs/PROVENANCE.md`, and `no_pdf_provenance` hard-failed on it — the
undeclared-document gate doing exactly its job, on a file I wrote. Declared now.

All 14 new guards are mutation-tested and all 14 are caught.

---

## ADR-0033 — Confidence is a field, not a footnote

**2026-08-18.** Externally-researched identities arrive with a source count,
and that count decides what they are allowed to do.

### `verified` is the only thing that scores

Two independent external sources agreeing is ground truth. One source is a
**candidate** — and a candidate is one transcription error away from being
wrong, so a precision figure computed over it measures the source rather than
the resolver. Four values, and the three that are not `verified` all score
nothing:

- `verified` — counted against the 250 gate, scored for precision.
- `single_source` — reported, never promoted. Promotion is a deliberate edit
  backed by a second source; a re-import cannot do it silently.
- `in_repo` — provenance is elsewhere in this repository. Not circular (these
  are hand-authored EV fixtures, not a catalog the resolver reads) but not
  independent corroboration either.
- `unstated` — seeded before the field existed, source count never recorded.

Both counts are reported everywhere: `label_cli status`, the gate's failure
messages, the ingest report. The pool size must never be hidden by the
ground-truth size, and must never be mistaken for it.

**The honest consequence: the set went from "21 of 250" to "0 verified, 21 in
the pool".** `ResolverQuality` now SKIPS with an explicit reason rather than
reporting a precision of 1.00 over zero rows — a skip that says why is a
finding; a green tick over nothing is a lie.

The nine existing `external_research` rows are `unstated` rather than
back-filled. Assigning them `verified` would invent the exact thing the field
exists to state.

### The loader refuses rather than repairs

An identity is the one thing in this project that must not be guessed at, and
a loader that fills in a plausible variant is how a wrong card enters ground
truth wearing the costume of a verified one. `label_cli ingest` refuses a row
that is missing `source` or `confidence`, carries an unknown confidence or an
unknown variant, is already present, or — the important one — **whose stated
`card_uid` disagrees with its own fields**. The uid is derived and compared,
never trusted.

Rejections print and the command still exits 0: the report is the deliverable,
and a red step would hide it.

### The three numbering rules, asserted in all three directions

Worth more than the rows, and each fails a different way, so each is asserted
forwards, backwards, and adversarially.

1. **Traditional Chinese is the Japanese set code + `F`, with IDENTICAL
   collector numbers.** `sv2a` → `SV2aF`, `s7R` → `S7RF`. Charizard ex SIR is
   `201/165` in *both*. The number is not a distinguishing feature here and
   `language` is the only thing keeping the two apart — which is precisely the
   merge non-negotiable 3 exists to prevent.

   The casing is kept as **data**, not folded into a rule. `sv2a → SV2aF`
   uppercases the alphabetic prefix and leaves the trailing `a`; two examples
   do not establish that, so comparison is case-insensitive and
   `OBSERVED_TC_SET_CODES` records the printed forms.

2. **English diverges from the JP family on secret rares.** Same card, same
   art: EN `199/165` against JP/TC `201/165`, and EN prints SIR where JP prints
   SAR. Three printings, three identities. Nothing in the uid says they are the
   same picture and nothing should — that relationship belongs in `card_xref`
   with a confidence.

3. **Simplified Chinese has its own codes AND its own denominators.** Pikachu
   AR is `173/165` in EN/JP/TC and `173/151` in SC `151C`. The index matches
   and the total does not, which is the trap: comparing on the index alone
   calls them the same card. Normalising `173/151` to `173/165` "to match the
   family" would turn CN-S's failure mode from a miss into a merge.

### Three blocking failures, armed before the set exists

Not scored, not averaged, not traded against precision. A resolver at 0.99 that
commits one of these is not a resolver at 0.99 with a rough edge — it is a
confident price on the wrong asset, and nothing downstream looks wrong.

- EN `199/165` resolving to the same uid as JP `201/165`.
- One Piece `OP01-025`, which exists as a base SR *and* an alt-art SR, both
  **printed** `OP01-025`, collapsing into one identity. Plus the realistic
  version: a record that says only `OP01-025` must REFUSE, not guess `base`.
- Riftbound `303/298` against `303*/298` — same art, same rules, an asterisk
  and a foil signature apart, and hundreds of dollars apart. The parser is
  asserted directly too: if the asterisk is dropped on the way in, nothing
  downstream can recover it.

They run against a synthetic three-card set on purpose, so they hold from the
first commit and regardless of what the labelled set contains. A blocking
failure that only arms once you have 250 rows was never armed. A meta-test
asserts they cannot reach `precision_threshold`, `_gate`, or `load()`.

**All six pass today.** The resolver already handles all three merges.

### Two corrections recorded

**`_p1` / `_p2` / `_r1` are Bandai image filenames surfaced by apitcg — a
provider convention, not a printed identifier.** Nothing on the card says
`_p1`, and a seller reading the card in hand will never type it; marketplaces
render the same distinction as an `a` suffix or "(Parallel)". Splitting on it
is still right, and the reason is worth being exact about: the suffix is
*evidence* of a distinct printing, not the *name* of one. What it must never do
is reach a user-facing field or a matching key a marketplace record could be
expected to carry — `OP01-025a`, `OP01-025 (Parallel)` and `_p1` all describe
one printing and the resolver has to accept all three spellings. ADR-0031's
wording implied the suffix was printed; it is not.

**Rayquaza VMAX s7R is `083/067`.** The `083/069` in listings is the KOREAN
printing's denominator. Dangerous precisely because it parses: it looks like a
collector number, reads like one, and points at a printing this project does
not track — so it is not "a card we do not have", it is a number that must
resolve to nothing. Recorded in `KNOWN_CONFUSABLE_NUMBERS` with the correct
value beside it, enforced by the loader, and checked against the labelled set.
If Korean is ever added to `LANGUAGES` a test fails and the entry has to be
re-decided.

16 new guards, all mutation-tested, all caught.

---

## ADR-0034 — 86 researched rows, 68 landed, 18 held at the vocabulary

**2026-08-18.** The first real external research file. 57 `verified`, 29
`single_source`, card_uids derived rather than typed.

**68 accepted, 18 rejected, every rejection on the variant vocabulary.** Not
one row failed on a derived uid, a confusable number, or a malformed field —
which is the loader saying the file is clean, not that the loader is lax.

### The nine unknown tokens are reported, not coerced

`sr` ×5, `ur` ×3, `hr` ×2, `manga` ×2, `rainbow_secret` ×2, `gold_secret`,
`ssr`, `holo`, `sp`. Mapping `sr` onto `parallel` because both mean "special"
would put two printings in one bucket, which is the merge every other guard
here exists to prevent. `manga` is the odd one: we already have `manga_rare`,
so it is a rename rather than a new concept.

Held, and named with the token, awaiting a decision. Listed in
`docs/OPEN_ISSUES.md` as S2.

### The set code is a key, not a claim

`sv151` and `swsh07` were the two the source normalised from set NAMES, and
neither matches the catalog. `SET_CODE_ALIASES` maps them — and each entry
records what it was **verified against**, because "SV: 151 is probably sv151"
is a guess and "sv03.5 holds 199 Charizard ex and 205 Mew ex, which is what the
row says" is a check.

- `sv151` → `sv03.5`, confirmed against catalog rows 199 Charizard ex, 205 Mew ex
- `swsh07` → `swsh7`, confirmed against 94 Umbreon V, 95 Umbreon VMAX, 111 Rayquaza VMAX

The card_uid is rebuilt around the new code, the original spelling is kept as
`set_code_as_sourced`, and every application is printed. An unknown code passes
through untouched: the table lists spellings we have *reconciled*, not sets
that exist, and a code absent from it is one nobody has checked.

### `unstated` is not a competing claim

Four rows collided with seeded `unstated` ones. `unstated` means "seeded before
the field existed and the source count was never recorded" — there is no
information in it a sourced row lacks, so this is a claim replacing a
non-claim, not a promotion. `--supersede-unstated` makes it deliberate; the new
row carries a `supersedes` reference per the append-only convention; a
`single_source`, `verified` or `in_repo` row is never superseded by an import.

**The first attempt lost data.** Superseding replaced the row wholesale, and
the old rows carried `hard_case: name_is_not_unique` and `artist: Oswaldo
KATO`. `TheNameIsNotAKey` selected on that tag and went from four cards to
zero. Superseding is a *correction*, not a deletion: the new row now inherits
whatever it does not supply, except provenance — `confidence`, `source`,
`verified_from` never carry forward, or a discarded claim would survive its own
replacement.

### Zero blocking failures, on real data

All six groups the file was built to stress resolve to themselves at
confidence 1.00:

- One Piece `OP01-025` base and parallel × EN and JP — four rows, four
  identities, all printed `OP01-025`
- the same for `OP01-001`
- Riftbound `303/298` against `303*/298`, and `299/298` against `299*/298`
- `173/165` (EN, CN-T) against `173/151` (CN-S) — same index, different total
- EN `199/165` against JP and CN-T `201/165` — same art

`BlockingFailuresAgainstTheRealSet` runs the same three merges against the
labelled set and skips per group when the set lacks both halves — a skip says
"not yet tested", a pass over one row would say "tested and fine". A guard on
the guards fails if *every* group skips, because a file that has gone quiet
reads exactly like one that is passing.

### Precision 1.0000 is not a passing gate

51 of 51, zero errors — and the 95% lower bound at n=51 is **0.9430**, against
a 0.98 threshold. n=250 gives 0.9881 and survives one mistake, which is what
ADR-0015 sized the set on. `PrecisionIsReportedWithItsInterval` asserts the
bound is below the threshold while the set is short, so "1.00" can never be
read as "met".

### The mutation harness was reporting false CAUGHTs

It compared each mutant's result against a hardcoded `failures=6`. The baseline
had moved to 5, so every mutant differed from a string that no longer appeared
and 9 of 11 were reported CAUGHT when they were MISSED. It compares against the
measured baseline now.

The 9 real misses were all the same mistake: the tests asserted the *committed
file* rather than the loader's behaviour, so mutating the loader changed
nothing they looked at. A snapshot is not a test of the thing that produced it.

One assertion was then removed rather than defended: the blocking check
asserted both that each row resolves to itself *and* that the results are
distinct. The first implies the second, so no mutant could ever kill the second
alone. A guard nothing catches is decoration.

19 new guards; every one mutation-tested against the measured baseline, and all
19 caught.

---

## ADR-0035 — The verification backbone was unverified

**2026-08-18.** Three things, and the first one is the one that matters.

### How far the mutation lie reached

Measured, not assumed. The suite's failure count at every commit on `main`:

| commit | baseline |
|---|---|
| `eefa1c3` | 4 |
| `ee81ce6` .. `0b2e7d3` (10 commits) | **6** |
| `b6ad779` (run #11) | **7** |
| `ca8008b` .. `a4c46dc` | 6 |
| `045a3c2` | 5 |

The harness compared each mutant against the literal `"failures=6)"`. That is
**correct logic for a baseline of exactly `FAILED (failures=6)`**, which held
for batches 1, 2 and 3 — the harness printed the measured baseline each run and
it read `FAILED (failures=6)` on all three. Those results stand.

**Batch 4 is where it broke, and it broke completely.** By then the baseline
was `FAILED (failures=6, skipped=6)` — the confidence split had made
`ResolverQuality` skip. The substring `failures=6)` does not appear in
`failures=6, skipped=6`. So the check `"failures=6)" not in tail` was **true for
every mutant that left the baseline unchanged**, and false only for the one
mutant that genuinely changed it. The report was **inverted**: 13 reported
CAUGHT were untested, and the single MISSED was the only real catch.

Every batch has now been re-run against the measured baseline. **All 63 are
caught.** The guards were sound; the report was worthless. That distinction is
the whole finding — a verification backbone that cannot be re-run is a claim,
not a check.

`b6ad779` at 7 is a separate, smaller thing: `docs/OPEN_ISSUES.md` shipped
without a `PROVENANCE.md` row and the undeclared-document gate failed on it.
Fixed the same session. No mutation batch ran at that commit.

### The harness now lives in the repository

`audit/mutate.py` and `audit/mutants.py`, 87 catalogued mutants,
`python -m audit.mutate`. It was a scratch file — unreviewable, un-re-runnable,
and gone the moment the session ended, while "all mutations caught" was being
treated as the backbone. Two rules are now enforced rather than remembered:

- **The baseline is measured once, at the start of the run.** Never hardcoded.
- **A stale anchor is a FAILURE, not a pass.** A mutant whose anchor no longer
  matches is a guard that has silently stopped testing anything, which is the
  same silence in a different costume. Two anchors had already drifted; the
  harness caught both on its first run.

### The number bridge, one direction only

tcgdex sends `199`; the card says `199/165`. `printed_from_bare` derives the
second from the first using the set's official card count.

**There is deliberately no function for the reverse**, and a test asserts the
absence by name. Stripping `173/151` and `173/165` to `173` makes Simplified
Chinese Pikachu and its English counterpart one string — the denominator is the
*only* thing separating them, and discarding it recreates precisely the merge
the blocking failures exist to catch. A refusal is a miss; a bare-vs-bare match
is a merge.

Where the count is unknown the bridge raises `CannotBridge` rather than
returning `False`, because "we could not tell" and "they are different cards"
are both non-matches and only one of them is a fact.

Two holes surfaced while testing it, both merges:

- **Two naked indices.** `173` against `173` compared equal. Refused now.
- **The parser drops set prefixes.** `parse_collector_number("OGN-030")` reads
  index 30 and discards `OGN-`, so `OGN-030` and `SFD-030` compared equal.
  Harmless for banding, which only ever asks about one set; a cross-set merge
  here. Two numbers that both carry a prefix are now compared **as given**.

`set_totals()` reads tcgdex's `cardCount.official` — the printed denominator,
not `total`, which includes secret rares and would make every secret rare fail
to bridge while looking like it worked. A set publishing no count is omitted,
never defaulted: an absent entry makes the bridge refuse, and a guessed one
makes it match the wrong card.

### The variant vocabulary is per game, for the third time

Rarity letters, then the band tables, now variants. One Piece `SR` is a
**rarity band** — an ordinary Super Rare, one of the commonest cards worth
tracking. Pokémon `SR` is a **printing treatment**, a full-art textured finish.
A shared table has to pick one meaning, and picking is guessing.

`SHARED_VARIANTS` for treatments that mean the same thing everywhere;
`GAME_VARIANTS` for the rest. `is_variant("sr", "optcg")` is False, and
`why_not_a_variant` says *why*:

> variant `'sr'` is valid for `pkmn` but not for `optcg`. The same letters mean
> different things per game — One Piece `SR` is a RARITY BAND, Pokemon `SR` is
> a printing treatment — so either the row names the wrong game or it wants a
> different token.

"Unknown variant" sends you to guess. Naming the other game tells you the row
is wrong rather than the vocabulary.

Eight tokens extended (`sr` `ur` `hr` `ssr` `rainbow_secret` `gold_secret` to
pkmn, `holo` shared, `sp` to riftbound); `manga` **renamed** to the existing
`manga_rare` rather than added beside it, because one treatment with two names
splits its price series.

All 86 researched rows are now in: 57 `verified`, 29 `single_source`.

---

## ADR-0036 — Two vocabularies for one taxonomy, and the class that has neither

**2026-08-18.** The researched rows arrive tagged `C1`..`C6`; this repository
has always tagged them `hard_case`. Both are needed and neither is wrong: the C
class says *why a row was collected*, the kind says *which gate requirement it
satisfies*.

`resolve/hard_cases.py` is the bridge, and it is a **translation, not an
inference** — each entry quotes the class definition it came from, so a later
reader can check the two against each other rather than trust that somebody
once matched them up. Five map exactly: C1 → `same_art_different_language`,
C2 → `reprint`, C3 → `alt_art_variant`, C4 → `promo_vs_set`,
C5 → `name_is_not_unique`.

### C6 has no kind, and is not being given the nearest one

C3 is two printings whose numbers **differ** — `095/203` base against `215/203`
alt art. C6 is two printings at the **identical** number, distinguished only by
treatment — `OP01-025` base SR against `OP01-025` alt-art SR.

Mapping C6 onto `alt_art_variant` would lose precisely the distinction that
makes it one of the three blocking failures, and it would do so while making
the gate *look* satisfied. That is the worst available outcome: a requirement
marked met by the rows least able to meet it.

So it is named as a gap. Ten rows carry C6 and count toward nothing until it
has a name. All ten are One Piece base-vs-parallel pairs.

The gap runs the other way too: `same_number_different_rarity` (3 rows) and
`box_code_vs_card_number` (1) are kinds no C class describes.

### `hard_case` had to become plural

18 of the 57 researched rows carry two classes — `C1,C6`, `C3,C5`, `C2,C4`. A
single-valued field has to drop one of them, and *which one it drops silently
decides which gate requirement goes unmet*. `hard_cases_of()` reads the plural
field and the legacy singular one, so nothing already recorded is lost.

Result: verified rows carrying a hard case went from **1 to 47**, against a
target of 60. Three of the four required kinds are now present in verified
rows; `reprint` is the exception — two rows carry it and both are
`single_source`.

Two existing kinds are narrower C1 cases and were kept rather than collapsed
into it: `same_number_three_languages` is C1 where the numbers match, and
`renumbered_into_combined_set` is C1 where the denominators differ. Collapsing
them would lose which of C1's three shapes a row actually exercises.

### Four Riftbound rows contradict their own tag

`299*/298`, `299/298`, `303*/298` and `303/298` are tagged C5 — "cards sharing
an identical printed name that are genuinely different cards … **NOT printings
of one card**". Their own notes read "asterisk only difference from 299/298"
and "same art/rules as 303/298". They are printings of one card.

**Flagged, not fixed.** Reclassifying someone's research from the outside is
the same coercion refused four times already this session — for variant tokens,
for set codes, for confusable numbers, for C6. A test asserts the rows are
still tagged C5, so the contradiction fails loudly the moment they are
re-tagged instead of being quietly forgotten.

They are also the rows the C6 definition set aside as "C1-adjacent — your
call", and that call depends on the C6 kind name.

92 mutants catalogued, all caught.

---

## ADR-0037 — C6 gets a name, four rows get corrected, two kinds keep their disagreement

**2026-08-18.** Four decisions, all the user's.

### `same_printed_number_different_treatment`

Verbose, and that is the point: it names the thing that matters and cannot be
mistaken for `alt_art_variant`. **Added to the gate's required kinds**, because
C6 is one of the three blocking failures and a gate that does not demand a case
for it is missing the class it most needs to measure.

Carrying it as a named GAP for one session was what made this possible. Had it
been folded into `alt_art_variant` when the mapping was first written, the gate
would have gone green on the requirement it was least able to meet, and nothing
would have said so.

14 rows carry it, all `verified`.

### The four Riftbound rows were mis-tagged, and the fix is recorded on them

`299/298`, `299*/298`, `303/298`, `303*/298` were C5 — "cards that share a name
and are genuinely different cards". They are two printings of ONE card,
treatment the only difference; their own notes said so. Re-tagged C6.

**The asterisk being printed inside the number is a notation detail, not a
different class.** Riftbound writes the treatment into the number; One Piece
writes it nowhere and leaves it to an image filename. Same relationship, two
conventions — and a taxonomy that split on where the discriminator happens to
sit would be describing the notation rather than the cards.

Each row carries `reclassified_from` and a note. A re-tag with no trace is
indistinguishable from data that was always that way.

**The guard test was inverted, not deleted.** It asserted C5 while the rows
were mis-tagged and asserts C6 now, so the next person to change them hits the
same wall and has to say why.

That correction surfaced a bug in `map-classes`: it MERGED into `hard_cases`,
so a re-tag would have left `name_is_not_unique` behind and the four rows would
have gone on satisfying a gate requirement they no longer meet. `hard_cases` is
now fully recomputed from `difficulty_class` — derived, idempotent, and
re-runnable — while `hard_case`, the legacy hand-set field, is never touched.

### The kinds are the schema; the classes were an input

Where the two vocabularies disagree the disagreement is **recorded, not
reconciled**. The C classes were built to decide what research to collect; the
kinds were derived from failure modes this repository has actually hit.

- `same_number_different_rarity` is C6's nearest neighbour and not the same
  thing: C6 is distinguished only by treatment, and an OP01-025 base SR and its
  parallel both read `SR`. A differing rarity at one number asks whether rarity
  can be trusted as a discriminator at all.
- `box_code_vs_card_number` is not a printing relationship — a parsing failure
  mode, found by ingest rather than by research.

Neither is forced into a class, and a test asserts neither ever is.

### `reprint` stays red

Two rows carry it, both `single_source`, because the PRB01 Shanks reprint
number could not be second-sourced. Left failing: a required kind with no
verified example is exactly what the gate exists to catch. The alternative is
a gate that passes while the class it names is untested.

Verified rows with a hard case: **51 of 60**. Four of the five required kinds
present.

94 mutants catalogued, all caught.

---

## ADR-0038 — 75 verified rows, three shapes of reprint, and a set code that cannot be derived

**2026-08-18.** Batch 2: 75 rows, all `verified`, two named independent sources
per collector number. **75 accepted, 0 rejected.**

### The pre-ingest check

Asked for, and it found nothing to stop the ingest. No shared `card_uid`
between the batches. One flag on `(op01, OP01-016, CN-S)` — batch 1 has Nami as
`alt_art`, batch 2 as `base` — which is not a disagreement but two printings of
one card, and they carry different uids.

On 151C specifically the two batches are **disjoint and consistent**: batch 1
holds 170–173/151 (Pikachu ARs), batch 2 holds 1–38/151 (base), no overlapping
numbers, same `/151` denominator. And every one of batch 2's fifteen indices
matches the National Pokédex exactly — independent corroboration of the "own
scheme" claim rather than a restatement of it.

### Three shapes of reprint, declared and then verified

All three are C2 and they fail three different ways:

- **`same_art_new_number`** — SV1 013/198 Sprigatito against McDonald's
  001/015. Two identifiers for one picture: matching on art merges them,
  matching on number never finds the pair.
- **`same_number_new_set`** — Base 4/102 Charizard against Celebrations
  4/102. **The hard one.** Two rows differing in a single field, and it is
  `set_code`, the field most likely to be dropped or normalised on the way in.
- **`new_art_new_number`** — Radiant Charizard PGO 011/078 (Negishi) against
  CRZ 020/159 (Saitou). The inverse mistake: they share a name and nothing
  else.

The shapes are **declared** from the research and **cross-checked** against the
rows — a pair claiming `same_number_new_set` must actually share a number and
the other two must not. A declaration nothing verifies is a comment. One test
asserts the hard shape differs in `set_code` **and nothing else**.

### `same_number_different_product`, and One Piece

Added, and required by the gate. Same argument as C6's kind: it is the shape
where two rows differ in exactly one field. C6 differs by `variant`; this
differs by `set_code`; both are one edit from a merge.

It is also the answer to the One Piece question. PRB-01 reprints of OP01-120,
OP01-024, OP02-004, OP03-123 and OP04-044 all keep their `OPxx-xxx`, and
`PRB01-xxx` is used only for that set's new cards — so a One Piece reprint
produces **no new identifier**, exactly like Celebrations retaining Base Set
numbering. One kind for both rather than a game-specific one, because a
game-specific kind would have split one failure mode in two and hidden that
they are the same shape.

### Simplified Chinese cannot be derived from Japanese

`set_code_is_derivable` is True for CN-T and **False for CN-S**. TC mirrors JP
exactly, so `sv2a` → `SV2aF` works. SC has its own scheme: National Pokédex
order, 192 cards, printed denominator `/151`. Pikachu is `025/165` in JP, EN
and TC and `025/151` in SC — asserted against four real rows in the set, four
distinct uids.

### Set codes: five aliased on evidence, three refused

Aliased with the cards that confirmed them: `sv1` → `sv01`, `cel` → `cel25cc`,
`tr` → `base5`, `pgo` → `swsh10.5`, `crz` → `swsh12.5`. The last two are the
strongest — the catalog holds `swsh10.5:011` and `swsh12.5:020` both named
Radiant Charizard, matching the rows index for index.

`base1` and `pop5` needed no alias; the catalog already uses them.

`mcd2023`, `s10b` and `s12a` could **not** be verified and are recorded in
`UNVERIFIED_SET_CODES` rather than guessed. An unaliased code and an
unverifiable one behave identically; recording the second is how you tell later
that somebody looked.

**And a finding: tcgdex renumbers the Classic Collection.** The card says
`4/102`; tcgdex says `CC002`. The printed number is the identity, so the row
keeps `4/102` — which means the hardest reprint shape has no catalog
counterpart to be tested against, and the bridge refuses rather than guessing.

### Where the gate stands

132 verified of 250. Precision and recall 1.0000; the 95% lower bound at n=132
is **0.9776**, just under the 0.98 threshold. Hard cases **116 of 60** — that
gate now passes. All six required kinds have verified examples.

Three failures left: total count, per-combo targets, and the 20-row floor.
`pkmn:EN` is 2 rows short of its target and is the first combo to clear the
floor.

100 mutants catalogued, all caught.

---

## ADR-0039 — Batch 3: a caught error, the error it uncovered, and the error that uncovered

**2026-08-18.** 38 rows, 37 verified. What matters is not the rows.

### Cross-batch disagreement, made a mechanism

Batch 2 had `OP01-002` as Monkey D. Luffy and `OP01-003` as Trafalgar Law in
Simplified Chinese; English, Japanese and apitcg all have them the other way
round. A clean swap between two real cards at two real numbers — **nothing in
either row was wrong on its own.** The uid was right, the number was right, the
name was a real card's name. Only the pairing was wrong, and only across
languages was it visible.

So it became a check rather than a fix. Bandai runs one code system across EN,
JP and CN-S, so `cross_language_name_disagreements` asserts that one number
names one card, for games in `SHARED_NUMBERING_GAMES`.

Three things it must not do, each of which would have buried the real finding:

- **Not Pokémon.** `173/165` and `173/151` are different cards; running this
  there would report every Simplified Chinese row as a contradiction.
- **Not across scripts.** `路飞` *is* `Monkey.D.Luffy` and nothing here can
  know that. A cross-script pair is NOT COMPARABLE — a third answer, and the
  reason `is_latin_name` exists.
- **Not on punctuation.** `Monkey.D.Luffy` and `Monkey D. Luffy` are one card
  written two ways.

### It immediately found a second error, in this repository

Three `in_repo` rows named `OP01-121` as Monkey.D.Luffy. The card is **Yamato**
— apitcg agrees, and `contracts/card_uid.md` names Monkey.D.Luffy at
`OP05-119`, not `OP01-121`. The seeding attached the wrong example's name.
These rows are `in_repo` and score nothing, so no gate was measuring them; the
check found them anyway.

### And fixing that uncovered a third

Correcting the name removed the only thing distinguishing
`optcg:OP01:OP01-121:base:EN` from `optcg:op01:OP01-121:base:EN` — **the same
card under two set-code spellings.** The resolver went from picking the wrong
one to picking neither, and `test_every_language_printing_resolves_to_its_own_uid`
failed. A latent split, visible only once the name stopped hiding it.

Ten One Piece rows used uppercase set codes where the catalog and the other 33
use lowercase (apitcg stores them as `op01.json`). Re-cased; the three that
then collided with a `verified` row were dropped, recorded, and the better
provenance kept. Every correction is a logged event with its evidence and what
caught it — a correction with no record is indistinguishable from data that was
always right.

### The PRB reprints are not the shape Celebrations is

apitcg's `prb01.json` confirms the rule emphatically: **317 of 319 cards keep
their original `OPxx-xxx`**, only 2 use the `PRB01-` scheme. But the reprints
appear as `OP05-119_p3`, `_p4`, `_p5` — Bandai's *parallel* suffixes. PRB-01
contains **new treatments**, not plain reprints.

So the pair differs in `set_code` **and** `variant`, which is neither
`same_number_new_set` nor C6. I had already tagged the five originals
`same_number_new_set` by analogy before checking. **Backed out**, and recorded
as an open question rather than resolved by widening a shape to fit.

The PRB rows are not minted. The variant is the one field no source here
supplies, and reading it from apitcg would make the row catalog-derived — the
circularity the labelled set exists to avoid.

### Riftbound writes its numbers two ways

`OGN-030a/298` did not parse **at all** — a set prefix with a denominator was
unreadable, so a card offered in that form had no identity. It parses now, and
the prefix is kept rather than discarded.

`numbers_denote_same_printing` reconciles the prefixed and denominated forms
*within one set*: the prefix and the denominator are redundant here, each
naming the set, and marketplaces use both. A reconciliation, not a
normalisation — neither form is rewritten, `OGN-030A` against `SFD-030a/298`
is False, and a scheme with no common ground still refuses.

### The upgrade path

`single_source` → `verified`, and nothing else. Not part of `ingest`: a
re-import must never promote, or a single-source row becomes ground truth
because somebody sent the same file twice. `--second-source` is required and
recorded on the row — `verified` claims two independent sources agree, and an
unnamed one cannot be checked.

First upgrade: `pkmn:csv3C:155/130:sar:CN-S`, second source PriceCharting.

### The interval test was passing for the wrong reason

At n=170 with a clean sweep the 95% lower bound is **0.9825**, which clears
0.98 — so the test asserting "the bound must not clear the threshold early"
fired. It was right to fire and wrong in what it measured: ADR-0015 sized the
set on the **error budget**, not the count. The question is whether ONE wrong
match would still clear the threshold.

Computing that exposed a worse bug: the bisection was **inverted** and returned
`0.0` for every input — which passes an `assertLess` silently. A guard that
returns zero is a guard that always agrees with you.

Fixed, and pinned to ADR-0015's own arithmetic: 250 rows survive one error at
0.9812, 200 at 0.9765, and 200 clean at 0.9851. All three reproduce exactly.
At n=170 one error gives 0.9724, so the count is still the binding constraint.

### Where the gate stands

170 verified of 250. Precision and recall 1.0000. Hard cases **129 of 60**.
All six required kinds have verified examples. Three failures: total count,
per-combo targets, and the 20-row floor — `pkmn:EN` and `optcg:EN` and
`pkmn:JP` have cleared the floor, `riftbound:EN` is 4 short of it.

111 mutants catalogued, all caught.

---

## ADR-0040 — A fourth shape, a seal on the auditor, and a dispute settled against the claimant

**2026-08-18.** Batch 4: 72 rows ingested, 3 quarantined and adjudicated.

### `same_number_new_set_new_variant`, and C6 stays narrow

Both axes moving is a distinct failure mode. A resolver can pass set-only
(Celebrations `4/102` in two sets) and variant-only (`OP01-025` base against
its parallel) and **still mishandle the two together**, because each of those
tests holds one axis fixed.

C6 was not widened to cover it. A widened C6 reads "variant differs, set may or
may not" — a **disjunction**, and disjunctive kinds are exactly how C6 itself
nearly got buried inside `alt_art_variant`. A kind that means two things
measures neither.

Required by the gate with zero rows carrying it, deliberately. A gate that only
demands what it already has measures nothing.

### The note parser is deleted

`reprint_shape` and `pair_id` are real fields. The prose-derived values were
migrated once — 24 rows, 12 pairs — and the parser went the same day. It read
`"pair MCD-1"` out of free text, so a note reworded at source silently dropped
a shape, and the cross-check catches a *wrong* shape rather than a missing one.
`reprint_shape_of` now returns `None` for a note and refuses an unrecognised
value.

### The seal, pointed at the auditor

`.github/workflows/mutate.yml`: full run, weekly plus any change to `audit/**`.
Filtered local subsets are fine — they are how the harness is actually used —
as long as the whole catalogue runs somewhere nobody can quietly not run it.

And a **mutant-count seal**. A run that discovers half the catalogue and
reports every one of them CAUGHT looks exactly like a clean run, so the
discovered count is asserted against `audit/mutant_seal.json` before anything
else happens. A silently-skipped subset reads as FAILURE, not as green. Same
instrument as the ledger seal, pointed at the thing doing the auditing.

A missing seal fails rather than passes: a missing seal is precisely what a
deleted catalogue looks like. The seal is raised in the same commit that adds
mutants — one updated afterwards to match a broken run is not a seal.

118 mutants, sealed.

### The dispute went against the claimant

Pass 4 claimed `OP01-014` = Tony Tony.Chopper and `OP01-015` = Jinbe, in EN and
JP, dual-sourced. Bandai's list has **`OP01-014` = Jinbe and `OP01-015` = Tony
Tony.Chopper**. The existing verified EN row is right; pass 4 has the pair
swapped — the same failure shape as batch 2's OP01-002/003, arriving from the
other direction.

So neither branch of the expected outcome happened: no existing row was
corrected, and the three rows did not land. They are recorded in `_disputes`
with the evidence, and correct rows for OP01-014 EN/JP and OP01-015 JP still
need sourcing afresh — minting them from apitcg would make them
catalog-derived, which is the circularity the labelled set exists to avoid.

Worth naming: the detector was **not** what caught this one. The researcher
caught it pre-ingest by comparing passes. The machinery's value here was
settling it, not spotting it.

### OP01-120 is worse than suspected, and not resolvable here

The hypothesis was that the two `manga_rare` rows are PRB-01 printings homed to
`op01`. The ambiguity is real and larger than expected: **OP01-120 has six
printings across two products** — `op01` holds `OP01-120`, `_p1`, `_p2`;
`prb01` holds `_p3`, `_p4`, `_p5`. A listing reading `OP01-120 Manga` cannot
pick between six.

**Not re-homed.** apitcg carries no treatment names — every One Piece rarity
field is null — so nothing available says which of the six is the manga
printing. Re-homing to `prb01` on the strength of "OP-01 predates manga" would
be an inference, and inference is what put the row in `op01` to begin with.
Flagged on the rows, recorded as S1, left counted rather than demoted: demoting
moves the gate numbers on a suspicion.

### `_status` was reading the pool as ground truth

At 285 rows the file's own status line flipped to COMPLETE while ground truth
stood at 234 — the same "pool size read as ground-truth size" mistake the
confidence split exists to prevent, surviving in the one line a reader is most
likely to trust. `_needed` had the same problem from the other end: a seed
value written once, still reporting `short_by: 229`. Both are recomputed now.

### Where the gate stands

**234 verified of 250**, and exactly three shorts — `optcg:CN-S` 16,
`pkmn:EN` 2, `optcg:JP` 1. Seven of eight combos have cleared the detection
floor. Hard cases 129 of 60.

Two failures are now about one combination: `optcg:CN-S` is 16 short and the
only one below the floor. Its 8 new rows are `single_source` **by this
project's rule rather than the researcher's** — their second source is Bandai's
shared numbering, which corroborates the NUMBER and not the Simplified Chinese
printing. Recorded, not counted, and that is the rule working.

---

## ADR-0041 — A source class that cannot answer, and the one that can

**Date:** 2026-08-25
**Status:** Accepted. The fetch is deferred to the runner; the classification
is not.

### The thing that was hiding

`verified` means two independent sources agree. The question nobody was asking
is what they agreed **about** — and there is a whole class of second source
that confirms one field of a row and is structurally silent on the rest.

Two instances, arrived at from opposite directions and identical in shape:

- **Shared numbering.** One Piece prints `OP01-032` on the English, Japanese
  and Simplified Chinese printings. An English source confirms the number
  exists and names Ashura Doji. It says nothing whatever about whether a
  Simplified Chinese printing was ever made. This one was already known — it is
  why batch 4's eight CN-S rows are `single_source`.
- **Retained-number reprints.** PRB-01 reprints keep their `OPxx-xxx`. So a
  marketplace listing reading `OP01-120 Manga` is attributed to *Romance Dawn*
  **as a set name**, because the seller reads the number and the number says
  `OP01`. Live eBay listings do exactly this.

The second is the more dangerous, and the asymmetry is worth stating plainly:
the first announces itself — nobody mistakes an English page for evidence about
a Chinese printing — while the second **arrives wearing the answer**. It is a
listing with a product name on it. It looks like product attribution. It is the
number, restated.

The consequence is the part that matters for counting: the attribution is
*derived from* the number, so it carries no information the number did not
already carry, and **two listings agreeing is two sources performing one
derivation, not two observations**. Independence is what `verified` is buying,
and derivation from a shared input destroys it silently.

### Decision

`resolve/corroboration.py` names two corroboration tiers — `full` and
`number_only` — and only `full` counts toward `verified`. An **unknown tier
does not count**: a source class nobody has classified is not a licence to
assume the strongest one, which is the same defaulting mistake as `base`,
`slot 1` and `parallel`.

`STRUCTURALLY_NUMBER_ONLY` records the situations where a source class is
number-only **by construction** — not because a particular source was thin, but
because the inference it is making cannot distinguish what needs
distinguishing. Both instances above are registered there. The generalisation
is that this is a property of the numbering scheme rather than of any
particular row, so it recurs on every retained-number reprint; the entry is
written to say so.

### The discriminating source

Naming a source class that cannot answer is only half a finding. The other half
is which class can — otherwise the entry reads as *unknowable* and the row
never resolves. A test enforces that the reprint entry names one.

**Limitless serves a separate variant page per printing, each naming its own
product.** That is a source that can tell `op01` from `prb01`; a marketplace
listing cannot, at any volume. `ingest/limitless.py` fetches those pages, and
the step is wired into `ingest.yml` rather than run here — the sandbox proxy
answers 403 to CONNECT for limitlesstcg.com, the same wall as the Chinese
catalogs. The URL shape is **probed, not assumed**: four adapters in this
project have been written against a guessed endpoint and three guesses were
wrong, so `card_page` walks its candidates and a card that answers nowhere is a
gap **naming every URL it tried**, never "the card has no variants".

### Two levels, and only one of them is certain

- **PRODUCT is certain**, because it is what the page is *for*: a variant page
  is served per printing and titled with its own product. That claim lands at
  tier `full`.
- **SLOT is a reconciliation**, not a rule. Where a semantic treatment has to
  map onto a provider's positional `_pN`, it is recorded as a per-`(set,
  number)` entry in `contracts/printing_slots.json` **citing the page that
  attested it** — data, not a rule, because there is no rule; the ordering is
  whatever apitcg happened to do.

Ground truth **keeps the semantic token**. `manga_rare`, not `_p4`. A
positional token would make the identity scheme catalog-derived, which is
precisely what the labelled set exists to avoid.

### The refusal is the load-bearing part

Where a page does not name a product, `attest()` writes **no entry** and
records a failure saying so. It does not order the slots and call the first one
the base.

That temptation is not hypothetical — ordering the slots is the exact inference
that homed `OP01-120` to `op01` in the first place. An absent entry in
`printing_slots.json` means *we have not established this*, never *slot 1*, and
the file says so in `_refusal_is_the_default`. An adapter that guesses when the
page is silent is the marketplace listing with a better hostname.

Fifteen mutants cover all of it, and the ones worth naming are the abstention
mutants — a silent page read as attested, an unnamed slot falling back to slot
order, the refusal made silent, an unreachable card recorded as *no variants*.
All fifteen caught.

### The seal was never in the repository

Found while raising the mutant count: `audit/mutant_seal.json` — added last
session, sealed at 118, and **never committed**. `.gitignore` line 25 is a
blanket `*.json` with a negation list, and `audit/**` was not on it.

The seal's whole function is to be a committed count that a skipped subset
cannot match. Uncommitted, it was a file on one machine. `mutate.yml` checks
the seal first and treats an unreadable seal as a failure, so the first runner
pass would have gone red with `SEAL UNREADABLE` — the right alarm for entirely
the wrong reason, and one that reads as a broken workflow rather than a missing
control.

`!audit/**/*.json` added, deliberately **not** added to the
`no_provider_data` payload-key allowlist so the seal is scanned like any
unprivileged JSON. Verified by planting `market_price` in it: untracked, the
check did not see it at all; tracked, the check fails. Worth keeping in view —
that check reads `git ls-files`, so **an untracked file is not scanned**, and
"the guard passed" says nothing about a file the guard never opened.

### What this does not do

It does not re-home `OP01-120` and it does not mint the five PRB reprint-side
rows. Both wait on pages this environment cannot fetch. The tier is decided,
the refusal is built and tested, and the fetch is one runner pass away — but
S1 stays open, and the two rows stay counted rather than demoted, because
demoting on a suspicion moves the gate numbers on a suspicion.

**Gate unchanged at 237 verified of 250.** Two shorts: `optcg:CN-S` 16 and
`pkmn:EN` 2.

---

## ADR-0042 — The parser was wrong on every page, and the tests agreed with it

**Date:** 2026-08-25
**Status:** Accepted. Corrects ADR-0041's adapter. The corroboration tiers it
introduced are unchanged and were not what failed.

### What real pages showed

ADR-0041 shipped a Limitless adapter I could not run — the sandbox proxy
answers 403 to CONNECT — and I flagged the URL shape and the title format as
fragile. The pages were then fetched. The fragility was not a risk that might
have bitten; it was **a certainty that would have**.

The real title is:

    Shanks (OP01-120) • Romance Dawn – Limitless

The first parenthesised token is **the card number**. Always. The parser took
"the first parenthesised code in the title" as the product code, so it would
have attested **every printing to a product code equal to its own number**, on
100% of pages, and reported each one at tier `full`.

The product is instead in a body link, and the code has to come off the
**HREF**, not the text:

    [Romance Dawn (OP01) Manga Art](/cards/op01-romance-dawn)
    [One Piece The Best (PRB01) …](/cards/prb01-premium-booster-one-piece-the-best)

Set code = the slug's leading token. The bracketed code in the link text is
kept **only as a cross-check**, and a slug disagreeing with its own text is
refused rather than averaged — text is what the title lies with.

### The part worth sitting with

Twenty tests passed. Fifteen mutants were caught. Two of those mutants —
"a silent page is read as attested", "the reprint relationship is read as this
page's product" — were *confirming a broken product read*, because they were
evaluated against fixtures I had written to match the regexes I had written.

I flagged this in the session report as "my fixtures agreeing with my regexes
is not evidence", and that was correct but far too weak. **A green mutation
run over self-authored fixtures measures internal consistency and nothing
else.** It cannot distinguish a parser that reads the right field from one
that reads the wrong field consistently. Mutation testing answers "do my tests
detect changes to my code"; it is silent on "does my code match the world",
and I let the first stand in for the second because the number was reassuring.

The fixtures now carry the observed shapes and say where they came from.

### Three more corrections from the same fetch

**One fetch per card, not per variant.** Every page carries the full Print
table — a labelled `?v=` link per printing. Probing variant numbers was walking
a list the first response already handed over. Six cards, six requests.

**The slot vocabulary is now evidenced, not assumed.** The image served on
`?v=2` is `OP01-120_p2_EN.webp`. The asset URL carries the suffix, so
"Limitless's `?v=N` is apitcg's `_pN`" is an observation rather than an
inference from the order two sources happen to list things in. What is *not*
claimed: that a filename with no `_pN` means the base printing. That is a
convention we hold about apitcg's naming, so `image_slot` reports such a page
as slot `None` **with the filename attached**.

**The pages carry prices** — USD/EUR columns, TCGplayer and Cardmarket links,
a price history block. `_get_text` called `Adapter.cache_raw`, which writes the
body to `raw/`. Now parsed in memory and never persisted. Bounded in practice —
`raw/` is gitignored and the artifact upload takes only `store/` and
`ingest-results.json` — so nothing reached the repository, but it wrote priced
provider HTML to disk on every fetch, which is the thing the non-negotiable
forbids independent of where the file happens to sit. The fixtures are
hand-written with the price table omitted, the rule `probe/fixtures/` already
lives under, and a test enforces it.

### The trap, which is the whole module in one line

    This variant has been reprinted in: One Piece The Best (PRB01)

appears **identically on the base page and on `?v=2`**, despite saying "this
variant". It is card-level. Anything reading it as the current printing's
product attests the manga printing to `prb01`.

That is exactly the wrong answer, arrived at from the discriminating source
rather than from a marketplace — which is the more dangerous route, because the
source is the one we trust. `reprint_note()` returns it labelled `scope:
"card"` and the variant product comes only from the bracketed product link.

### S1 closes, and the refusal is the reason

`?v=2` names `/cards/op01-romance-dawn`. **Manga is `op01`.** Both
`manga_rare` rows were right all along: not re-homed, and no correction event,
because there was no error to correct.

Two temptations pointed at `prb01` and both were declined — ordering the slots
and assuming `prb01` holds the later ones, and reading the reprint line as
variant-scoped. Either would have introduced the error.

This is the rare case where declining to guess is checkable after the fact, so
it is worth stating without hedging: **the guess was available, specific,
consistent with everything known at the time, and wrong.** Leaving the rows
counted rather than demoting them on a suspicion was also right — demoting
would have moved the gate numbers away from the truth.

The rule that made the rows unconfirmable is unaffected by which way the answer
went. Marketplace attribution for a retained-number reprint is still
`number_only` and still does not count toward `verified`; that is a claim about
what a source class *can establish*, not about which answer it points at. It
had to be checked against a source that could discriminate, and it was.

### The model was wrong in the other direction too

Not six printings across two products. **Five printings across three.**

| Slot | Label | Product |
|---|---|---|
| — | Romance Dawn | `op01` |
| `?v=1` | Romance Dawn aa | `op01` |
| `?v=2` | Romance Dawn manga | `op01` |
| `?v=3` | Prize Cards serial | **Championship 2023 — a third product** |
| `?v=4` | One Piece The Best aa | `prb01` |

A product nobody had. The apitcg-derived model put `_p3` in `prb01`;
Limitless puts slot 3 in Prize Cards, and lists five printings where the old
model assumed six.

**Recorded, not reconciled** (`contracts/printing_slots.json` →
`_disagreements`). Both cannot be right, neither is checkable from here, and
averaging them or quietly preferring the newer source produces a number no
source states. Filed **S2 rather than S1**: no ground-truth row currently
claims a Prize Cards or `prb01` printing of OP01-120, so nothing wrong is
being counted. It becomes S1 the moment one is minted. One fetch of `?v=3`
settles it.

### What still cannot be claimed

The print table gives every printing a **label**, and labels carry product
*names*. Codes come from slugs, and one fetch attests one slug. So
`build_product_index` accumulates name → code across every page fetched, and
`reconcile` resolves labels against it — a lookup of something a page stated,
never an inference from the label's own text. Where the name was never seen in
a slug, the entry records `product_set_code: null` and says which page would
resolve it. `Prize Cards` is currently exactly that: named in a label, attested
in no slug, left unresolved.

**Gate unchanged at 237 verified of 250.** Shorts: `optcg:CN-S` 16,
`pkmn:EN` 2. The five PRB reprint-side rows are still unminted, so
`same_number_new_set_new_variant` still has no verified example — but its
blocker is now a runner pass rather than an open question.

---

## ADR-0043 — Requested is not observed, and n=1 is not a mapping

**Date:** 2026-08-25
**Status:** Accepted. Corrects two claims in ADR-0042 and adds the guard the
fetch exposed.

### The fetch that answered the wrong question

`?v=3` was requested for OP01-120 to settle the Prize Cards product. What came
back was **the `?v=2` page**: image `_p2`, body `Romance Dawn (OP01) Manga
Art`, and `Romance Dawn manga` unlinked in the print table. Site redirect, or
de-duping somewhere in the fetch path — **indistinguishable from outside**.

It does not need to be distinguished, and that is the point worth keeping:
the guard is the same either way, so diagnosing the cause is optional and
comparing the response to the request is not.

This is the failure mode that does not announce itself. Ask for slot 3, get
slot 2's product, write `(3, op01, "Manga Art")` into `printing_slots.json`,
and every check downstream is green over a pair that is simply false. It is
the same shape as the two failures this module already exists to prevent —
attribution derived from something other than the thing being attributed — and
it arrives through the source we trust rather than through a marketplace.

### The guard: three signals, compared and never merged

`verify_slot` parses the slot **from the page** and refuses on mismatch.

1. **The gap in the `?v=` run.** Every row but the current printing carries a
   link to go there, so on `?v=2` the links run 1, 3, 4 — and the missing
   integer names the page.
2. **The image filename suffix** (`_pN`, absent for base).
3. **The page's own canonical `?v=`.** Weakest of the three; the tag's
   presence is assumed rather than observed, so it never runs alone.

Signal 1 is deliberately read as *a missing integer* rather than *which
element lacks an anchor*, and that choice comes straight from the correction
below: the page arrives as rendered markdown down one path and raw HTML down
another, and a rule about markup has to be right about both. A gap in a
sequence is the same in either.

**Two abstentions matter more than the votes.** A complete run 1..N cannot
discriminate — it is equally the base page (base has no `?v=` of its own to
omit) and the `?v=N+1` page (nothing past the end is missing from 1..N) — so
signal 1 returns nothing there rather than guessing "base". A signal that
cannot tell two printings apart must not pick one, because it would then
out-vote the signal that can. And where two signals speak and disagree, the
result is *none* with the disagreement attached: a page that cannot say which
printing it is must not be recorded as any printing.

The follow-up fetch is bounded the same way it was before — only slots whose
product no page has attested are requested — and a mismatched response leaves
the entry unresolved with `slot_mismatch: {requested, observed}` rather than
taking the answering page's product.

### Two claims downgraded

**`?v=N` ↔ `_pN` is confirmed at n=1.** One pairing on one card (`?v=2` /
`_p2`), plus base/no-suffix. ADR-0042 stated it as established; it is a single
observation. Rather than delete it, the adapter now **re-confirms it per card**
from the image filename and every run reports confirmations against
contradictions. A card where it fails is **evidence about the mapping, not
about that card** — that sentence is in the report text, because the tempting
reading of one contradiction is "this card is odd", and that reading is how a
mapping survives its own counterexamples.

**The page shape was never observed.** What reached the parser was
`web_fetch`'s *rendered markdown*, not Limitless's HTML. The slug structure and
the image filenames are real; **the anchor nesting is not**. So both
serialisations parse, nothing depends on which arrived, and a test asserts the
two produce identical readings. ADR-0042 said the fixtures "carry the observed
shapes" — half right, and the half that was wrong is the half I had already
been burned by.

### The counting bug that the guard exposed

A page omits its own `?v=` row, so the links always undercount by one. Adding
the current printing back requires knowing which one it is — so
`count_printings` reports a **lower bound with `printing_count_exact: false`**
where the signals cannot place the page, instead of a number that reads as a
total. Five printings is now derivable from the base page, from `?v=2` and
from `?v=4` independently.

### S2 stays open

The Prize Cards product is **still unattested**: its label names it, no page
has served a slug for it, and the fetch that would have was the one that came
back wrong. Left open rather than closed on a plausible reading.

If the runner also lands on `?v=2`, **that is the finding** — and it will be
reported as a slot mismatch, not as an absent product. The two call for
different next steps, and collapsing them would turn a fetch-path problem into
a permanent "this product cannot be sourced".

### What this run cost, and what it bought

Three sessions on one card. What it bought is not the answer to OP01-120 —
that answer was `op01`, which is where the row already sat. It bought the
three guards that made the wrong answers refusable: product from the slug and
not the title, card-level reprint line labelled as such, and now response
compared to request. Each of those was found by a fetch, and none of them was
found by a test.

**Gate unchanged at 237 verified of 250.** Shorts: `optcg:CN-S` 16,
`pkmn:EN` 2.

---

## ADR-0044 — Signal 3 was looking in the wrong place, and absent is not agreement

**Date:** 2026-08-25
**Status:** Accepted. Corrects ADR-0043's third signal and strengthens the
second.

### A signal that could never speak

ADR-0043 built signal 3 on `rel=canonical` and flagged it as "the tag's
presence is assumed rather than observed". It is worse than assumed: **there
is no `rel=canonical` on these pages.** The head holds `description`, `og:*`,
`twitter:*`, `viewport` and `title` — nothing else.

So signal 3 returned `absent` on every page, forever. It never voted, never
disagreed, and never failed a test, because "absent is reported as absent" is
exactly what a well-behaved abstaining signal looks like. **A signal that
cannot speak is indistinguishable from one that agrees**, and the design
document said "three signals" while the code had two.

Worth naming as a class, because it is the third variant of the same mistake
in three sessions: a check that cannot fire reads as a check that passed.
The seal that was never committed, the mutants that confirmed a broken parser,
and now a signal wired to an element that does not exist.

### Where the self-reference actually is

In the **body**, three times over:

    header card-name link  ->  /cards/OP01-120?v=2
    language link EN       ->  /cards/en/OP01-120?v=2
    language link JP       ->  /cards/jp/OP01-120?v=2

On the base page all three carry no query. And on the `?v=3` request that
served `?v=2`, **all three said `?v=2`** — they report what was *served*, not
what was asked for, which is the entire property this signal exists to
provide.

Three instances also means the page can be checked against itself: if the
header and the two language links disagree, that is a **page-level anomaly**
and the signal returns nothing. Two links claiming different printings of one
card is not a majority to take; it is a page that should not be read.

### The collision, and the coupling it forces

The header link may share a print row's URL shape exactly — nothing in the URL
separates `/cards/OP01-120?v=2` used as "this page" from the same shape used
as "go to printing 2". Left in the print table it does real damage: it adds a
"printing" labelled with the card's *name*, and it fills the gap that
identifies the page, so signal 1 goes quiet.

Self-references are excluded by **multiplicity** — the served slot carries
several `/cards/{number}` links where every print row carries exactly one.
That works whether or not the shapes collide, and it uses only the structure
of the links themselves.

It is still a coupling, and it is recorded as one rather than smoothed over:
where the shapes collide, signal 1 depends on that exclusion running first.
Never the other direction — the self-reference signal does not read the print
table. Claiming three independent signals when two share a dependency would be
the same overstatement as claiming three signals when one could not speak.

### Signal 2 moved to the head

`og:image` and `twitter:image` both carry `_pN`. Reading the slot there rather
than from the body `<img>` means body markup changes cannot break it, and it
is the same string in either serialisation — which matters because the page
arrives rendered down one path and raw down another. The body image stays as
the fallback for a rendered page with no head, and **the source that answered
is reported**, because which field a value came from is what turns a
disagreement into a diagnosis.

### A fourth check that is deliberately not a signal

`og:title` carries the product **name**: `Shanks (OP01-120) • Romance Dawn` on
`?v=2`, `• One Piece The Best` on `?v=4`. It can corroborate a slug and must
never supply one. Turning a name into a set code requires a lookup, and doing
that lookup here would make the title a product source again — which is the
bug this module opened with, arriving by a different route. A test asserts
that an `og:title` alone yields no product code.

### What the fixtures now carry

The observed head (`description`, `og:*`, `twitter:*`, `viewport`, `title`,
and **no canonical**), the three body self-references, and the print table
with the current printing unlinked. A test asserts the fixtures contain no
`canonical` — if one ever appears, the assumption this signal replaced has
come back.

All three signals now vote on `?v=2`, and the printing count comes back exact
from the base page, from `?v=2` and from `?v=4` independently.

**Gate unchanged at 237 verified of 250.** Shorts: `optcg:CN-S` 16,
`pkmn:EN` 2. S2 remains open: Prize Cards is still unattested.

---

## ADR-0045 — The collision is the case, and a pattern that cannot match must say so

**Date:** 2026-08-25
**Status:** Accepted. Batch 6 lands; ADR-0044's conditional coupling becomes
unconditional; the adapter declares its game.

### Batch 6

Two verified Pokémon rows — `sv03.5:002/165` Ivysaur and `sv03.5:005/165`
Charmeleon, each dual-sourced and each pairing with an existing verified
`sv2a` JP row. **`pkmn:EN` closes at 40/40.**

**239 verified of 250, and exactly one short: `optcg:CN-S`, 16 rows.** Seven
of eight combos have cleared both their target and the detection floor;
`optcg:CN-S` remains the only combo below it. Its shortfall is not a
collection problem but the corroboration rule working as designed — its
candidates are `single_source` because their second source is Bandai's shared
numbering, which attests the *number* and is silent on whether a Simplified
Chinese printing exists.

### The print rows carry the header's URL shape

Observed:

    [Romance Dawn](/cards/OP01-120)
    [Romance Dawn aa](/cards/OP01-120?v=1)
    [Prize Cards serial](/cards/OP01-120?v=3)

identical in form to the header card-name link. ADR-0044 hedged this as "the
header self-link *may* share a print row's URL shape" and described signal 1's
dependency on the multiplicity exclusion as holding "where the shapes
collide".

**They always collide.** The hedge is now a statement, and the branch that
assumed otherwise is gone — `self_reference_slot` had a path where bare links
voted if their slots were unanimous, which cannot happen when every print row
contributes a distinct bare slot. It was dead code reachable only from
fixtures I wrote.

That is the same class of defect as the two before it, and it is worth
counting them together because the pattern is now unmistakable:

| What | How it read | What it was |
|---|---|---|
| The mutant seal | committed and enforcing | never in the repository |
| Signal 3 (`rel=canonical`) | present and abstaining | wired to an element that does not exist |
| Bare-link voting branch | a handled case | unreachable on every real page |

**An untaken branch tested only against fixtures is a third thing that cannot
fire.** Each of these read as coverage.

The exclusion itself is unchanged and correct: the print table omits the
printing being displayed, so the served slot is carried three times — header
plus two language links — where every print row carries its slot once.
Multiplicity separates them, and it now also counts the base printing, so the
header link is recognised on a base page the same way it is on a variant page.

Signal 1's dependency is therefore **permanent**. Recorded as such. It remains
one-directional: the self-reference signal does not read the print table.

### The adapter now declares its game

`_SELF_REF` is `[A-Za-z]{2,4}\d{2}-\d{2,4}`. It cannot match `OGN-030` — no
digits before the dash — or `025/165`, which has no letters at all.

That is correct for a host called `onepiece.limitlesstcg.com`, and it was
enforced by nothing. A Pokémon or Riftbound card would not have raised; it
would have matched no self-reference and returned a page that could not
identify itself — a *finding*, apparently, about that page.

`refuse_other_games` raises `UnsupportedGame` at both entry points before any
request is made, and names both numbers that cannot match. The adapter also
declares `game = "optcg"` so a caller can check rather than discover.

This is the same failure family as the canonical tag, which is why it is worth
fixing now rather than when a second game arrives: **a pattern that can never
match is indistinguishable from one that looked and found nothing.** The
distinction only exists if something asserts it.

### Where this leaves the fetch

Unchanged. S2 stays open — Prize Cards is still unattested, and the `?v=3`
page is still the thing that would settle it. All three signals vote on the
observed shape, and the printing count comes back exact from the base page,
from `?v=2` and from `?v=4` independently.

**239 verified of 250. One short: `optcg:CN-S` 16.**

---

## ADR-0046 — An admission standard, written before the rows

**Date:** 2026-08-25
**Status:** Accepted and **pre-registered**. No row has been collected under
it. If it is edited after the CN-S batch arrives, the edit is the finding.

### The question

`optcg:CN-S` is the last short combo and the only one below the detection
floor. Its candidates sit at `single_source` because their second source is
Bandai's shared numbering, which attests the *number* and is structurally
silent on whether a Simplified Chinese printing exists.

The proposal: admit a new source class `physical_card` — a copy in hand, read
by a person — and let it compose with the documentary record.

### Is this the rule bending to reach a number?

I do not think so, and the test I applied was: *would this rule have been
written the same way without the CN-S problem in view, and does it weaken
anything that currently holds?*

**It generalises.** A card in hand plus a documentary number composes
identically for EN, JP and CN-T. Nothing about it is CN-S-specific.

**It leaves the load-bearing half untouched.** The documentary source still
attests nothing about whether a CN-S printing exists. What supplies that is a
physical artifact, which is the strongest evidence available for existence —
stronger than any catalog. The rule that blocked these rows is not relaxed; a
source that satisfies it is added.

Both halves of that matter. A rule that had to be *weakened* to admit the
rows would be bending; a rule that admits them because better evidence turned
up is the rule working.

### The correction

`number_only` already meant "attests the number, silent on the printing". A
physical card is the opposite shape — decisive about the printing, weak about
the number, because transcription is where it can go wrong. Calling both
`number_only` would make `tier_counts_toward_verified` mean two different
things depending on which source asked.

So attestation is recorded **per field**. That separates two axes the tiers
ran together: *which* field a source speaks to, and *how strongly* — and it
distinguishes SILENT from WEAK, which the per-source tier could not. The
proposal was already describing this; the schema had to catch up.

### What the composition guards, stated precisely

The Bandai list and the printed card are **not causally independent**: the
card was printed from that database, so they are one fact observed twice.

That is not a flaw — two observation channels of one underlying fact is
exactly right for catching *observation* error — but it bounds the claim. The
composite guards **transcription error, not upstream error**. If the record
and the card agreed on something wrong, nothing here would notice. Bandai is
the authority for what the number is, so that is acceptable; the claim being
made is "we recorded it correctly", never "the number is correct".

### The addition: the checksum is the mechanism

Two `partial` attestations composing to `full` needs an argument, or it is
arithmetic on tier labels. `optical` composes with `documentary` because their
failure modes are disjoint — a misread glyph and a wrong-record error have no
common cause — **and** because the number and the name constrain each other. A
transcription slip yields either a number the record does not carry or one
that names a different card.

`field_is_established` therefore refuses the composition when the checksum did
not run. Agreement that is never checked is not agreement. A channel also does
not compose with itself, and a pair nobody has argued for does not compose at
all.

### The gap the standard does not close

There is no Simplified Chinese catalog source, so the documentary side gives
the **EN or JP** name for the number — not the SC name. Confirming that the SC
characters render the EN name is a **translation**, and a translation
performed here is not a source; it would be this repository corroborating
itself.

The SC name is therefore attested optically only, with no second channel, and
every row carries `name_attestation: optical_only`. The name is not an
identity field — it drives `cross_language_name_disagreements`, which has
caught three errors, but the resolver is not tested on it. Registered in
`NOT_REACHED` with its reason and asserted by a test, because the failure mode
this repository keeps producing is a gap that reads as covered.

### The protocol is a control, so it is written down

**The reader goes first.** The holder states number and name off the card; the
record is consulted after. Drafting a row and asking for confirmation is
forbidden *by name* in `PHYSICAL_CARD_PROTOCOL`, because a confirmation
against a prior carries no information — the same defect as fixtures agreeing
with the regexes they were written from, which cost this project two sessions.

**Unsure is unresolved.** Ambiguous, damaged or uncertain text is recorded
unresolved, never guessed and never filled from the EN row. A guess there
would be indistinguishable from a reading and would be laundered to
`verified` by a checksum it was constructed to pass. Twelve rows collected
this way beats sixteen with four guesses in them.

Every `physical_card` row must carry `read_by`, `read_on`, `checksum` and
`name_attestation`. A card in a hand is not re-checkable by anyone else later
— unlike a URL, nobody can go and look again.

### The procedural fix

Batch 6 landed clean and left the suite one failure worse: its `C1` tags had
not become kinds, and the gate reads kinds. `ingest` now runs the translation
itself, with `--no-map-classes` to opt out. `map_classes` recomputes rather
than merging, so this is idempotent.

Not a runbook entry. **A step you have to remember is a step that reads as
done when it was not** — the same shape as the uncommitted seal, the canonical
tag, and the unreachable branch.

**239 verified of 250.** One short: `optcg:CN-S` 16, awaiting rows collected
under this standard.

---

## ADR-0047 — A photograph is one channel with two hands on it

**Date:** 2026-08-25
**Status:** Accepted. Extends ADR-0046's pre-registration before any row was
collected under it.

### The question

Walton photographs the card; I read the characters off the image. Still
`optical_only`? Who is `read_by`?

### The three claims, all correct

**Still one channel.** Same optical evidence, one artifact, one reading.
`physical_card` stays `optical` about the name and the number however the
glyphs reached the reader. Nothing about the composition moves.

**It removes a transcription step on the one field with no checksum.** The
number is checksummed against Bandai's record, so a slip there is already
caught. The **name** has no second channel — there is no Simplified Chinese
catalog source — so removing a human hop on the name is exactly where the gain
is, and it is a real one.

**It is not the forbidden pattern.** The prohibition is on *confirmation
against a prior*. A photograph carries no prior of the reader's to agree with;
it is a fresh artifact. Correct, and the reasoning generalises: what makes the
drafted-row case worthless is that the answer was supplied before the
question.

### The answer: both, in two fields

Not one field holding two names. **The photographer and the reader fail
differently, and they fail on different things.**

- **`imaged_by`** owns *which card* — the wrong copy off a stack, a cropped
  number, glare, focus. That is a **selection and legibility** error, and it
  can make the whole row about a different card.
- **`read_by`** owns *transcription* and nothing else — glyph to text.

Collapsing them into `read_by` would record two error sources under one name
and lose which one to look at when a row turns out wrong. That is precisely
the mistake `number_only` was making when it had to mean both "attests the
number" and "weak about the number", and it is the reason ADR-0046 moved to
per-field attestation in the first place. The same argument applies to roles.

`reading_method` is stated explicitly rather than inferred from which fields
are present — absent means unknown, so which method was used has to be
declared, not deduced. A `direct` row carrying an `imaged_by` is refused:
nothing was photographed, so there is no photographer to hold responsible.

### What the photograph changes that was not asked about

**It makes the reading auditable.** ADR-0046 states that a card in a hand is
not re-checkable — unlike a URL, nobody can go and look again — and treats
that as the reason provenance must be written down at the time. A photograph
undoes that limitation. Given that the registered falsification condition is
*a Simplified Chinese catalog source appearing later and disagreeing*, being
able to go back and re-read the glyphs is worth having.

This strengthens the **provenance**, not the tier. `image_ref` — a filename or
content hash — identifies which image was read, and
`reading_is_re_checkable` returns false without it, because a photograph
nobody can find again is a card in a hand.

**The image itself is never committed.** It is a photograph of copyrighted
card art, which is the same redistribution rule provider data lives under. The
reference is what makes the reading auditable without putting the artwork in a
public repository.

### The back door, which is the part worth catching

A photograph is not the forbidden pattern, but it **opens a new route back to
it**, and the route is short enough to walk without noticing:

> The reader cannot make out a character and asks the holder *"is this 阿?"*

That is a confirmation against a prior arriving through the photograph instead
of through a drafted row. The holder is now agreeing with a candidate rather
than reading, and the agreement carries no information — identical in kind to
the case the protocol already forbids, and harder to spot because it feels
like diligence.

Named in `ILLEGIBLE_GLYPH_ROUTE` and closed. The permitted moves: take a fresh
photograph and read that, or record the field **unresolved**. Asking the
holder to read the character aloud *without being offered a candidate* is
fine — that is a reading. **The distinction is whether a candidate was
supplied before the answer**, and it is the same line the drafted-row rule
draws.

### Also recorded

Two people reading the same image is still one channel and does not promote
the field — they share every failure the artifact has, and a cropped number is
cropped for both. Worth recording when it happens, because it lowers the
practical error rate and a disagreement between two readers is a finding, but
`composes` refuses `optical` with `optical` and that is deliberate.

**239 verified of 250.** One short: `optcg:CN-S` 16, awaiting rows.

---

## ADR-0048 — Who read it is an error profile, and one profile breaks the safeguard

**Date:** 2026-08-25
**Status:** Accepted. Extends ADR-0046/0047's pre-registration, still before
any row.

### The observation

`read_by` is not attribution. A model reading glyphs off card artwork fails
differently from a person holding the card: its weakest case is dense-stroke
Simplified Chinese at banner size over foil, and its failure mode is
**confident substitution of a visually similar character** — not a visible
stumble.

So `optical_only` understates it when the reader is a model. The name has no
second channel **and** the single channel it has is a poor instrument for that
script.

### It is not a tier, and that is the right call

Recorded as `reader_reliability`, a profile on the row.

A tier says what a **source class** can establish. This says how a **reader**
fails. They are different questions, and folding one into the other is the
conflation this project has now corrected twice: `number_only` meaning both
*which field* and *how strongly*, then per-source tiers unable to distinguish
SILENT from WEAK. A third instance would have been the same mistake in the
same place.

Concretely, keeping them apart means a poor reader **does not demote
`physical_card`**. The class is still `optical` about the name; what changes
is which reader may supply it. A test asserts no profile key ever appears
where a tier or channel is expected.

### The consequence that a note alone would not cover

The protocol's main safeguard on the name is `unsure_is_unresolved`, and that
rule **assumes the reader can notice being unsure**. A visible stumble fires
it. A confident wrong character does not.

So on exactly the case described, the escape hatch is not weaker — it is
**inoperative**. The reader does not abstain because it does not know it
should, and the row comes back looking clean. That is the worst available
failure shape for this pipeline, because every other control here is
downstream of a reader who flags their own doubt.

**If a reader cannot detect its own failure, the mitigation cannot be
self-report.** It has to be structural.

### The allocation follows the checksum

- The **number** is checksummed against Bandai's record. A substituted digit
  produces a number the record does not carry, or one naming a different card.
  A non-self-detecting reader may read it: the checksum catches what the
  reader cannot.
- The **name** has no checksum — there is no Simplified Chinese catalog
  source, which is the gap ADR-0046 registered. That is precisely where an
  undetectable substitution is unrecoverable, so a non-self-detecting reader
  **may not supply it**. It goes to a self-detecting reader, or to
  `name_attestation: unresolved`.

This reuses machinery that already existed rather than adding a mechanism:
`unresolved` was already the standard's answer for a field that could not be
read, and this makes it reachable for the case that needs it most.

An unclassified reader is refused for **both** fields — the same defaulting
rule as an unknown corroboration tier and an unknown variant token.
Unclassified is not a licence to assume the favourable case.

### Scope

The profile is about reading **glyphs off artwork**. Parsing text a server
sent us — `ingest/limitless.py` — is a different act with different failure
modes, and the entry says so, because a profile that quietly widened to cover
every read would be doing what these tiers keep doing.

### Where this leaves the CN-S batch

Unchanged in scope, sharper in what it will record. Rows whose name a model
read come in with `name_attestation: unresolved` rather than a character
string, and the identity fields — which are what the resolver is tested on —
are unaffected. If that makes the SC names thinner than hoped, that is the
standard reporting what it actually knows.

**239 verified of 250.** One short: `optcg:CN-S` 16.

---

## ADR-0049 — A copied name cannot disagree

**Date:** 2026-08-25
**Status:** Accepted. Decides the CN-S admission question posed against
ADR-0046's pre-registration. Still before any row.

### Both framings were about the wrong field

The choice offered was: admit on the number alone with the name unresolved
(losing the cross-language disagreement check), or take the names with a
non-native reader profile.

Neither is what the set does. **Every existing CN-S row carries a Latin
reference name in `name`; the printed Simplified Chinese characters live in
`note`.** The detector sees all 28 of them, and one row already states the
policy: *"Printed Chinese name not verified by the research; the reference
name is recorded and the printed name is absent rather than guessed."*

`cross_language_name_disagreements` is **Latin-only by construction** — it
skips a non-Latin name, because comparing 阿修罗童子 to "Ashura Doji" is a
translation, the gap `NOT_REACHED` already registers. The SC characters were
never what it consumed, so the stated cost does not apply as stated.

### What replaces it is worse, and it is the fifth instance

The detector's power comes from the CN-S Latin name being an **independent
observation**. Batch 2's swap was catchable because the researcher
transliterated from a CN-S source and the result disagreed with EN and JP.

Fill `name` from Bandai's EN record instead — the obvious move once the number
is checksummed against it — and **the detector can never disagree**. The name
was derived from the record it is being compared against. It runs, it passes,
and its passing carries no information.

That is this session's defect for the fifth time, and the most expensive,
because the check it disables is the one that has caught three real errors:

| What | Read as | Was |
|---|---|---|
| The mutant seal | committed and enforcing | never in the repository |
| Signal 3 (`rel=canonical`) | present and abstaining | wired to a tag that does not exist |
| Bare-link voting branch | a handled case | unreachable on every real page |
| Limitless `CARD_CANDIDATES` | probed endpoints | three guesses, with the answer already in the parser |
| A name copied from EN | a passing check | a check that cannot fail |

### Decision: no name at all

Not the printed characters, and **not a Latin reference copied from the
documentary record**. An absent name makes the row **visibly skipped**; a
copied one makes it **vacuously passed**, and the second is strictly worse
because it produces a clean report.

This is also what the project's own rule already required — *when a source
cannot supply a field, delete the field* — applied to a case where the
plausible default was not a guess at the value but a copy of it from
somewhere that could not corroborate it.

The rows are identity-complete and name-absent. `name` is not an identity
field; the gate and the resolver do not read it.

**The names stay available and additive.** A transliteration of the printed
characters is an independent path to the Latin name and would restore the
detector on those rows. It must not hold up the identity rows, and it must not
come from a reader who cannot check it.

### The non-native reader, and why the proposed label is unnecessary

`human_nonnative_logographic`, **`self_detecting: False`**. Same failure shape
as the model, different cause: **no model of which strokes are load-bearing**.
A smudge is noticed; a wrong radical is not. The reader knows they are
copying, which feels like appropriate caution — but the caution is about
legibility, not meaning, and the substitution lands in the part they cannot
check.

Under the allocation set in ADR-0048 that reader may read the **checksummed
number** and **may not supply the name**. No new rule was needed; the existing
one applied to a new profile. So `optical_only_nonnative` is not required —
the case it would have labelled is one the standard already refuses, and a
label for a refused case is a caveat with nothing enforcing it.

What *would* be self-detecting is named: a native reader of the script, or a
Simplified Chinese catalog source. Neither is currently available.

### The detector could not report what it looked at

Found while checking the above. `cross_language_name_disagreements` returns
disagreements. A caller could not distinguish *examined 28 rows and found
none* from *examined none* — and in a report those read identically.

`name_disagreement_coverage` reports both. On the live set: **103 rows
examined, 49 numbers seen, 31 actually compared, 18 carrying a single row.** A
number with one row cannot disagree with itself, so the clean result stands on
31 comparisons rather than 49 numbers — and it had been read as the latter.

**239 verified of 250.** One short: `optcg:CN-S` 16, awaiting rows admitted on
the number alone.

---

## ADR-0050 — Naming the picture, and the transliteration that would have leaked the answer

**Date:** 2026-08-25
**Status:** Accepted with three tightenings. Additive to ADR-0049; rows still
land name-absent where this channel abstains.

### Why it is not too soft

The objection to invite was *a model naming cartoon characters is not evidence*.
It is, and the reason is structural rather than a claim about accuracy: the
evidence is **the picture, not the text**, so the channel is independent of
Bandai's record in the way ADR-0049 identified as the whole point. A CN-S row
named from artwork **can** disagree with the EN or JP row at that number.
A name copied from the record cannot. That difference is the detector.

It also cross-checks the **number**, which currently has one channel. An art
call disagreeing with the documentary name for the transcribed number means
either the number was misread or the call was wrong — a finding either way,
and the number is the field where a finding is most valuable.

### Tightening 1: blindness must cover the printed name

The proposal made the art call blind to the number. That is not enough, and
the hole would have voided the channel.

**A Simplified Chinese card name is a phonetic transliteration.** 索隆 is
*Suǒlóng* is *Zoro*. The same partial read that disqualifies the glyph channel
— ADR-0048 established this reader gets SC glyphs confidently wrong — is more
than sufficient to *anchor* an art call. Unreliable is not the same as
uninformative, and the trap is that a channel disqualified for accuracy can
still be perfectly adequate for leakage.

So `ART_CALL_BLINDNESS` withholds `number`, `card_uid`, `set_code`,
`printed_name`, `documentary_name` and `note`. The image is what is shown.

Ordering is enforced as **sequence, not intention**, which the proposal got
right and which is worth restating because it is the pattern that makes these
protocols real: the calls are committed *before* the checksum runs, and
`art_call_admits_a_name` refuses a call whose commit does not predate it. The
git history is the evidence. What anyone remembers about the order is not.

### Tightening 2: `partial` is a measurement, not a label

`self_detecting: partial` is the dangerous middle, and naming it that way is
the honest framing: **the occasions when a partial abstention fails to fire
are exactly the confident-substitution occasions**. A property that works most
of the time and fails silently on its worst case is not much better than one
that never works, if nothing measures which case you are in.

So `failure_is_self_detecting` returns **false** for `partial` — it is not a
licence — and `may_read` routes it through the art-call protocol instead of
granting it on the strength of the word.

`abstention_is_credible` is the instrument, and its shape matters:
**zero abstentions across a batch is the red flag, not the success.** A One
Piece set is not all Luffy and Zoro; it contains minor crew, background
figures and alternate-art stylisation, which is precisely where this reader
said it is weakest. A run that recognised every card recognised some it could
not. Floor at 5%; below it the batch is **unmeasured**, not clean.

That inverts the usual reading of a clean sweep, deliberately. This project
has spent a session finding checks that could not fail; a recognition rate of
100% on a task with genuinely hard cases is the same shape.

### Tightening 3: what each outcome does

- **`agrees`** — the Latin name is independently attested, and the detector is
  live on that row.
- **`disagrees`** — the row is **blocked**. Not admitted with either name. A
  disagreement is the instrument working, not a vote to break, and picking a
  side would discard the finding.
- **`abstains`** — no name, the row lands exactly as ADR-0049 has it, and
  **abstention costs nothing and must never be discouraged.** That is written
  into the outcome table because the pressure to close the last sixteen rows
  is exactly the pressure that turns an abstention into a guess.

Spelling differences are not disagreements: the claim being corroborated is
*which character*, not which orthography.

### The conflict worth naming

The reader in this pipeline is the same agent that designed the standard it is
judged by. The abstention-rate instrument is the mitigation — it is a
measurement over the output that someone else can run and that the reader
cannot satisfy by trying harder, only by actually abstaining.

**239 verified of 250.** One short: `optcg:CN-S` 16. The rows land under
ADR-0049 whatever this channel returns; this only decides whether they land
with names.

---

## ADR-0051 — The caller cannot be this session, and 0.8 of a card is not a floor

**Date:** 2026-08-25
**Status:** Accepted. Corrects two defects in ADR-0050, both raised against
it before any call was made.

### The blinding hole was structural, not incidental

ADR-0050 built a blindness rule around withholding the number and the printed
name. Both are necessary. Neither is sufficient, because **the reader already
holds the set's cast.**

This conversation contains OP01-001 Zoro, 003 Luffy, 014 Jinbe, 015 Chopper,
120 Shanks, 121 Yamato, the 014/015 dispute in full — and it **printed the
CN-S candidate rows verbatim** a few turns ago while checking what the
detector actually compares. An art call made here would be matching pictures
against a list already read. That is not a weakened independence; it is none,
and the blindness protocol would have dressed it as the strong kind.

**Abstention is not the remedy.** It presumes the reader can tell which of its
identifications came from the picture and which from the conversation. It
cannot — the contamination is **per-reader, not per-card**, so there is no
subset of calls that survives it.

So: this session must not call. `CONTAMINATED_READER` records the refusal and
names concretely what is known here, because a rule stated abstractly gets
reasoned around.

### The fresh session, and two limits on it

Calls come from a session opened fresh, given the images and nothing else, and
recorded as a **distinct reader identity — never `Claude`**. A shared label
erases the only property that makes the call worth anything, and
`art_call_admits_a_name` refuses an absent identity, `Claude`, or a call with
no `fresh_session` declaration.

Two things stated rather than assumed:

**Shared training is not the contamination.** A fresh session has the same base
ability and the same failure shape, and that is expected — the profile
describes the model class. What differs is conversational context, which is
the entire issue.

**Freshness is declared, not proven.** Nothing in this repository can verify
that a session was fresh. The field records a claim, and it is labelled the
weakest link in this channel so it cannot read as evidence. Same class as *the
reader goes first* — worth stating because it can be followed, worth labelling
because it cannot be checked.

And because this session knows the expected names, the comparison is done
**mechanically** by `art_call_outcome`, never by judgement. A reader that knows
what the answer should have been must not be the one deciding whether a
disagreement counts.

### 0.8 of a card is not a floor

The 5% abstention floor was arithmetic nonsense at n=16 — 0.8 cards, which
collapses to *abstained at least once*. A lucky easy batch passes it; a
careful batch fails it identically.

The power calculation is worse than that, and it is worth writing down:

| True abstention rate | P(zero abstentions in 16) |
|---:|---:|
| 5% | **0.44** |
| 10% | 0.19 |
| 17% | 0.05 |

**A reader whose true rate is exactly the floor would have failed it 44% of the
time.** Zero abstentions at n=16 is significant only if the true rate is
≥17%.

So the abstention rate is **demoted from a gate to a report**.
`abstention_report` prints the count *with the rate at which zero would have
been surprising* — because a count without its detectable floor reads as a
verdict, which is the same defect as a detector that could not say how many
rows it compared. Zero abstentions is worth a human look, not a failure, and
not evidence of contamination on its own.

`zero_abstention_detectable_rate` computes the floor rather than asserting it,
so the claim in the docstring is checkable.

### What carries the weight instead

**The per-row disagreement rule**, which does not depend on sample size at
all: every call is checked against the documentary name for its own row, and a
disagreement blocks that row. Sixteen rows means sixteen independent checks,
not one underpowered statistic.

What the abstention rate cannot do — and this is the honest limit — is
separate a careful reader on an easy batch from a contaminated one. Both agree
with everything and abstain on nothing, and at n=16 those are statistically
indistinguishable. That is precisely why the fresh-session protocol carries
the anti-contamination load, and precisely why it is labelled unverifiable
rather than presented as a control.

### The pattern, again

Both defects are the same one this session keeps finding: a control that reads
as stronger than it is. A blindness rule that blinds nothing because the
reader already knows; a floor that would fail the thing it was built to pass.
Neither was caught by a test — both were caught by someone doing the
arithmetic and asking what the reader already holds.

**239 verified of 250.** One short: `optcg:CN-S` 16.

---

## ADR-0052 — The standard was wired to nothing

**Date:** 2026-08-25
**Status:** Accepted.

### The question, and why the answer is bad news

*Is the `physical_card` composite a valid `--second-source` for an existing
`single_source` row, or does `upgrade` hardcode a documentary second source?*

Source-agnostic. The ten CN-S candidates could always have moved.

But `second_source` was a **free string**, stored verbatim and validated only
for being non-empty. `--second-source "looked about right"` promoted a row to
ground truth exactly as readily as a physical card would have.

So the answer is worse than a yes: **four ADRs of composite rules, per-field
attestation, reader profiles, checksums and blindness protocols existed in
`resolve/corroboration.py`, and `upgrade()` never called any of it.** The
standard was complete, tested, mutation-covered — and connected to nothing.

That is the seventh instance of this session's defect and the cleanest
specimen of it. The others were checks that could not fire. This one is a
check that fires perfectly, in a module nothing imports at the moment of
decision.

Worth noting how it was found: not by a test, and not by me. It was found by
someone asking whether a command written before a standard still honoured it.
The tests all passed because they tested the standard and tested the upgrade,
separately, and never asked whether one reached the other.

### The wiring

`second_source_is_admissible`, on both the single-row and batch paths:

- an unclassified string is **refused**, listing the known classes;
- `other:<name>` is accepted and **recorded as unclassified** — a visible
  escape hatch, because an invisible one is indistinguishable from a check;
- `physical_card` additionally requires its full provenance and must satisfy
  `row_is_verifiable` for the composite.

The single historical upgrade is normalised to `other:PriceCharting` with a
note. Not a change of claim — PriceCharting was and is the second source. The
prefix records that nobody has analysed what it attests *per field*, which is
a different thing from having checked it and found it sufficient. Classifying
it properly would mean doing that analysis; inventing a class to make a test
pass would be the vocabulary rotting.

### Batch upgrades exist because the provenance does not

The single-row path reads provenance off the card. None of the ten candidate
rows carry it, so `upgrade --rows FILE` supplies it with the promotion.

`UPGRADE_MAY_ADD` bounds what an entry may attach — reading method, reader,
checksum, attestation, source class — and pointedly **not** `number`,
`variant`, `language` or `name`. An upgrade records how a claim became better
evidenced; it never edits the claim. An entry attempting to is refused naming
the fields it tried to change, because a promotion that can also rewrite the
row is a re-adjudication wearing a promotion's name.

### `unstated` needs no upgrade path

`UPGRADE_PATH` remains `single_source → verified` alone, and the existing
reasoning holds: **`unstated` means the source count was never recorded, not
"one source".** Promoting it on one physical card would claim two independent
sources agree without knowing the first exists or is independent of the
second.

`ingest --supersede-unstated` is the route, and it is the better one anyway: a
claim replacing a non-claim, appended with a `supersedes` reference rather
than edited in place, carrying forward whatever the new row does not supply.
The superseding row arrives with its own full provenance instead of inheriting
an unknown one.

Five rows are at `unstated`, not four: `pkmn:csv6C:152/128:sar:CN-S` alongside
the four One Piece treasure rares.

**239 verified of 250.** One short: `optcg:CN-S` 16 — ten upgrades and six new
rows, on the split identified from the file.

---

## ADR-0053 — The audit that discovers decision points, and shipped inert

**Date:** 2026-08-25
**Status:** Accepted. Answers "don't find #8 by hand — build the audit that
finds all of them at once."

### Two species, because they need different tests

The ADR-0045 table held one kind. It holds two, and they read identically
green:

**INERT** — the check cannot fire. Nothing it could be run against would make
it complain. *Remedy: prove it can fail.* Two shapes, because their remedies
differ: **by construction** (an unreachable branch, a signal wired to an
element that does not exist) and **by scope** (it fires, over a universe that
excludes the target — a scanner reading `git ls-files` never sees an untracked
file).

**ORPHANED** — the check fires perfectly. Nothing calls it at the moment of
decision. *Remedy: prove something invokes it — at the decision point.*

A test written for the wrong species passes and teaches nothing. Exercising an
orphaned check directly proves it works, which was never in doubt; asserting
an inert check is reachable proves it is called, which was also never in
doubt.

`audit/defect_taxonomy.py` holds all seven instances with the remedy actually
applied, and `tests/test_defect_taxonomy.py` **asserts the named remedy test
exists** — a registry of remedies whose remedies have been renamed away is the
stale list it exists to catalogue.

### The audit

`audit/checks/no_unguarded_elevation.py`. Decision points are **discovered**:

    site(F) <=> (writes a confidence field OR admits an opaque row)
                AND F is inside the persistence closure

Not "writes to the set AND sets confidence" — that conjunction misses
`ingest()`, which produced **238 of the 239 verified rows** and never touches
a confidence field. It appends rows it did not construct.

**Two call graphs, opposite conservatism.** Reaching a sink over-approximates
(a missed edge is a missed site, a silent pass); reaching a gate
under-approximates (a spurious edge is a fake guard, also a silent pass).

**Default-deny sinks.** Every path-proving rule the red team was handed, it
defeated — argparse defaults, f-string joins, `pathlib` `/`, write-and-rename
— and each defeat produced a silent pass on a function containing a literal
elevation. So a write whose destination cannot be read keeps the obligation.

Designed against **21 evasions** from three adversarial passes. The ones that
shaped it: aliasing the collection before mutating it, a class splitting
mutation from persistence across sibling methods, and a data-driven patch with
no literal anywhere.

### It shipped inert, and that is the finding

The first working version reported **clean** against a brand-new module
containing an unguarded elevation. `git ls-files` returns only *tracked*
files, and a new module is untracked at the moment it is written — so the
audit built to catch a new write path could not see a new write path.

That is `inert / by_scope`, the species catalogued an hour earlier in the same
commit, in `no_provider_data`, which has the identical bug.

Three more of its own defects surfaced the same way: a mode flag counted as a
path (`open(p, "w")` classified as a named destination, defeating default-deny
with an argument that is not a path); the alias-*binding* statement read as a
collection write, making every reporter a decision point; and R-consume
checked in the site rather than along the path, which refused every wrapper.

None was caught by a test. All four were caught by attacking the audit with
the corpus it was designed against — which is the only thing that separates a
check that can fail from one that cannot.

### What it found

**`ingest` was unguarded**, exactly as predicted. A row arriving with
`confidence: verified` was taken at its word. Now `row_is_admissible` runs at
the point of admission: a row naming a classified source class is judged by
the standard, and one naming an unclassified source must say so with `other:`
rather than being waved through.

`review` is exempt with a **machine-verified** claim — `no-confidence-write`,
refused by the audit if a confidence write is detected — and the exemption
roster is count-sealed, so an allowlist cannot grow silently.

### What this audit still cannot see

Stated here because a check that reads as stronger than it is, is the defect
it exists to catch:

  * It proves an edge to the gate **exists**, not that the gate refuses. A
    gate called on one exemplar row and applied to a batch passes.
  * `getattr`, `eval`, `exec` are refused rather than resolved.
  * A guard behind a condition satisfies R-consume; conditional guarding is
    not detected.
  * It reads source, not behaviour.

**239 verified of 250.** One short: `optcg:CN-S` 16.

---

## ADR-0054 — The threshold assumed the labels were right

**Date:** 2026-08-25
**Status:** Accepted. Amends ADR-0015. The measurement is drawn and committed;
the answers do not exist yet.

### The premise nobody wrote down

Measured precision is capped at **`(1 - e)`**, where `e` is the ground-truth
error rate — a perfect resolver disagrees with a wrong label. ADR-0015 sets
the gate at 0.98 and never states that this only works while `e` is small.

Three errors are already known in this set, all found by **cross-batch
comparison rather than by any check**, and that comparison's coverage is thin:
31 numbers were ever actually compared. The uncaught rate has never been
estimated. At n=250 the 0.98 threshold allows five errors; if `e` is around
1%, label noise consumes half the budget before the resolver is asked
anything.

The arithmetic in ADR-0015 is unchanged and still correct. What was missing is
its premise, and it now carries an amendment note at the top pointing here.

### N=30 screens; it does not certify

Computed rather than asserted, and pinned by a test because the last bisection
in this repository was inverted and returned 0.0 for every input:

| N, zero disagreements | 95% bound on `e` |
|---:|---:|
| **30** | **≤ 9.5%** |
| 100 | ≤ 3.0% |
| **149** | **≤ 2.0%** ← what the gate needs |
| 239 | ≤ 1.2% |

Thirty rows is four to five times too coarse for the threshold. It is a good
**screen**: at `e = 10%` a clean sample of 30 happens only 5% of the time. So
it finds a gross problem cheaply and licenses nothing else, and if it returns
two or more disagreements nobody needs 149 rows to know there is a problem.

Worth noticing the shape of the alternative: 149 is 62% of the whole verified
set, so the real choice is *screen* or *re-verify essentially everything*.
There is not much useful ground in between.

`render()` prints this table beside every result, because a rate without its
interval reads as a measurement.

### The contamination is targeted, not noisy

The proposal stated it as optimistic bias — the researcher assembled most of
this set and may recall rather than re-derive. True, and sharper than that:
**where the recalled memory is of the original mistake, the re-derivation
reproduces it and the comparison agrees.**

So the bias is not evenly distributed noise. It is blind precisely to errors
arising from the researcher's own systematic habits — and all three known
errors are exactly that class. The instrument is least sensitive to what it is
most needed for. A fresh researcher, or a session with no access to this
project, is the clean version; this one bounds `e` **from below**.

Every render says so, and a mutant fails the build if that sentence is
softened to "an estimate".

### Protocol

The name is withheld — the field all three known errors live in, and the
answer. A test asserts no drawn row's name appears anywhere in the request.

The draw is **committed before any answer exists**
(`contracts/reverification_draw.json`, seed pinned, reproducibility asserted).
The blinding is a sequence, not an intention: a sample chosen after seeing
results is not a sample. Same discipline as the art calls.

Comparison is mechanical, orthography normalised — the claim under test is
*which card*, not which spelling. Abstentions leave the denominator rather
than counting as agreement, because counting them is how a thin sample reads
as a clean one. Disagreements are **findings**: a disagreement says two
readings differ, not which one is the error, and nothing is corrected or
demoted on its strength.

### What this does not do

It does not block the sixteen CN-S rows, and it does not fix anything. It
measures what the gate's central number is worth.

**239 verified of 250**, of which 1 is machine-checkable and `e` is
unestimated.

---

## ADR-0055 — Screen, then stop, and say what the number is conditional on

**Date:** 2026-08-25
**Status:** Accepted. Closes the question ADR-0054 opened without closing the
gap it found — deliberately.

### The call

Run the 30-row blind screen in a fresh session. **Do not run the 149.** Record
the limitation as a bounded, conditional claim rather than spending a second
labelled-set build to remove the condition.

### Why, and it is not mainly cost

The strongest argument is not the price of 149 re-derivations. It is that
**the 149 is largely redundant with the measurement it would license.**

Ground-truth errors show up as disagreements. If the resolver agrees with the
labels on fraction `p`, then `e ≲ 1 - p`: every ground-truth error either
falls in the disagreements or was masked by the resolver making the same
error. So measuring precision 0.99 bounds `e` near 1%, and **passing the gate
at 0.98 bounds `e ≲ 2%` — precisely what the 149 was for.**

The circularity is not vicious, it is self-limiting: you cannot measure 0.98
against ground truth carrying 8% errors. The one real gap is *correlated*
error, resolver and labeller producing the same wrong answer, and the labelled
set is built non-catalog-derived specifically so that the two do not share a
source.

Which relocates the whole question. The 149 buys nothing in the success case.
It buys something only in the **failure** case — precision lands roughly
0.90–0.98, resolver debugging comes up empty, and blame must be apportioned
between the resolver and the ruler. That is a real scenario and a real use,
and it has a trigger, so it is held in reserve rather than pre-paid.

> **CORRECTED 2026-08-25 (ADR-0056).** The precondition above is not met, and
> the trigger as stated is wrong. `e ≲ 1 - p` requires the resolver's INPUT to
> be independent of the label. Precision today is measured on SELF-RECORDS —
> the row goes in and its own uid is expected back — so correlated error is
> total and the bound carries no information at all. The trigger is therefore
> not "precision lands low"; it is "we need `e` and no independent measurement
> exists yet.

The error-budget argument stands on its own and is worth keeping: this
resolver feeds EV models carrying an uncalibrated submission-selection
haircut, community-sourced pull rates, and single-digit grade-level comps.
Tightening a label bound from 9.5% to 2% optimises the wrong term by a wide
margin.

### Two corrections to the claim as first drafted

**It has to be conditional on the screen coming back clean.** The first
drafting asserted `e ≤ 9.5%` before the screen had run.

**And 9.5% is itself optimistic.** A clean sample from a contaminated reader
bounds *the error rate that reader can still re-derive*, not `e` — which is
the whole reason the screen goes to a fresh session. Presenting it as `e`
would be the familiar defect: a bound that reads stronger than it is.

### What is deliberately not decided

ADR-0015's 0.98 was chosen without `e` in the model, and a threshold derived
conditional on `e` is the principled fix. It is **not** taken here, because
re-deriving the gate's central number as a side effect of a thread about
sampling is how a number stops meaning what its ADR says.

When it is taken up: the argument above suggests it may move the number very
little, since the binding constraint is the same measurement either way. What
it would change is the interpretation — the gate stated honestly as a claim
about **joint resolver-plus-label quality**, which is what it has measured all
along.

### What was not built

Nothing. No module, no tests, no mutants. The request was a judgement call and
the answer is a paragraph; building an apparatus to hold it would have been
the wrong response to "not more machinery".

**239 verified of 250.** One short: `optcg:CN-S` 16.

---

## ADR-0056 — `e ≲ 1 − p` needs an independent input, and there isn't one

**Date:** 2026-08-25
**Status:** Accepted. Corrects ADR-0055, which recorded the bound without its
precondition and built a reserve trigger on top of it.

### The correction

ADR-0055 argued that ground-truth errors show up as disagreements, so
`e ≲ 1 − p`, so passing the gate at 0.98 largely certifies its own premise.
The algebra is fine. **The precondition is not met, and I did not state it.**

The bound requires the resolver's **input to be independent of the label**.
Precision today is measured on **self-records**: `_self_records` builds the
input from the labelled row's own fields and expects that row's own
`card_uid`. Input and expectation are the same data twice. A wrong label is
fed in and expected back, so correlated error is not residual — **it is
total**, and `1 − p` carries no information about `e` whatsoever.

Sharper than that, and this is the part that settles it: `card_uid` is
`{game}:{set_code}:{number}:{variant}:{language}`. **`name` is not in it.** A
row naming the wrong character resolves exactly as well as a correct one, at
any resolver quality. All three known errors in this set are name errors. The
measurement is *structurally incapable* of seeing the error class we have
actually observed.

So the argument is not conditional-and-currently-unmet. On this instrument it
is **void**.

### What the self-record number actually is

**1.0000, on 239 of 239.** It is a **no-merge / no-collision check**: it proves
the resolver keeps 290 distinct rows distinct and does not fold two printings
into one. That is a real property and precisely the one that broke when
`_p1`/`_p2` suffixes were dropped and 286 rows merged into 234 collisions.

It is **not a resolution check**, because nothing independent is being
identified. Quoting 1.0000 as "resolver precision" overstates it by a wide
margin, and the number now carries that caveat at the point it is computed,
in the assertion message, and in `_self_records`' docstring — not only here,
because a caveat that lives in an ADR is not attached to the number a reader
sees.

### When the bound becomes available

When precision is measured **catalog entry in → labelled uid out**. Then a
wrong label disagrees with a correctly resolved catalog entry and lands in
`1 − p`, and correlated error drops to the genuinely residual case of the
resolver and the labeller making the *same* mistake from *different* inputs.

That measurement does not exist yet. Building it is the precondition for the
whole ADR-0055 argument, and it is a larger and more useful piece of work than
the 149 re-derivations — it measures the thing the resolver is for.

### The reserve trigger changes shape

ADR-0055 held the 149-row sample in reserve behind "precision lands low and
the resolver is exonerated." That exoneration route runs through `e ≲ 1 − p`
and is therefore unavailable.

Corrected: **if precision is still self-record-measured when a real number is
needed, the 149 is back on the table sooner than ADR-0055 implies** — because
there is no other route to `e`. The cheaper path is the catalog-in
measurement, which both makes the bound available and measures resolution;
the 149 is the fallback if that is not built.

### The pattern

Three corrections in three turns, each one arithmetic or a premise I could
have checked and didn't: the abstention floor at n=16, the contaminated art
caller, the N=30 bound. This is the fourth, and it is the worst of them,
because I used the unstated premise to argue *against* doing more work. An
argument that concludes "we can stop here" deserves more scrutiny than one
that concludes "do more", and it got less.

**239 verified of 250.** Self-record precision 1.0000, which is not a
resolution measurement.

---

## ADR-0057 — The measurement that can fail, and the three joins it took to get there

**Date:** 2026-08-25
**Status:** Accepted. Builds what ADR-0056 named as the precondition. Runs
uncertified.

### Decoupling the count from the work

The 250-row threshold licenses a precision **claim**. It was never a
prerequisite for taking a measurement, and the current gated figure is void
anyway — self-records cannot fail. So the next step did not need row 240.

`optcg:CN-S` is marked **`blocked_on_external`** with a reason and a review
date, and **the target is unchanged at 30**. The gate stays honestly red.
Moving the line to fit what is reachable is the same move as backfilling
`source_class` onto 238 rows: the number goes green and nothing is known that
was not known before. The block is a label on the red, and the assertion still
fails — it just now tells a reader that the work is waiting on an object
rather than on somebody's attention.

### Three joins, two of them wrong

The measurement feeds a provider's own presentation and expects our uid. To
score it you must pair a catalog entry with a labelled row, and the pairing
must not be the thing being measured.

**Name only — invalid.** Paired the labelled Base Set Blastoise with a `bw8`
Blastoise. Character names repeat across dozens of sets.

**Set + name, first match — invalid, and worse.** Paired labelled
`sv03.5:003/165` Venusaur ex with catalog `sv03.5/198`: a different printing
of the same character in the same set. Non-negotiable 3 says those are
different cards, and the pairing would have scored the resolver **wrong for
being right** — a measurement that manufactures failures is worse than one
that manufactures passes, because it sends someone to fix code that works.

**Set + name, unique on both sides — valid**, and it yields 7 rows.

That is the fundamental difficulty and it is stated in the module rather than
worked around: **you cannot pair a catalog entry to a labelled row without
using the number, and the number is what needs measuring.** What survives is
the subset where set and name happen to be unique.

### The result, and it is a real one

**7 pairable of 239. All 7 refused. Precision undefined** — an empty
denominator is not a result, and reporting it as 1.0 would be the
clean-report-over-zero-comparisons defect one more time.

Where the self-record figure is 1.0000 on 239 of 239, this one cannot resolve
a single pairable row. Both numbers are correct; they measure different
things, and only one of them can fail.

**It found a resolver defect on its first run.** `printed_from_bare("011", 78)`
returns `011/078` correctly, but `numbers_denote_same_printing("011",
"011/078")` returns `CannotBridge` because the set total is never passed —
and `ingest/targets.json` carries `_set_totals` that nothing connects to the
resolver. Filed S2. **Not fixed here**: it is a change to the thing being
measured, found by the measurement, and it deserves its own decision rather
than being folded into the commit that built the instrument.

### Coverage is blocked by three things, none of them design

109 rows have no catalog at all (`optcg` and `riftbound`, apitcg rate-limited
for several consecutive runs). The catalog names cards in the local script
while the labelled set uses Latin, so the Japanese and Chinese combos cannot
join on name. And set coverage barely overlaps — 6 shared of 31 labelled
against 201 catalogued.

All three are live items with owners. None is a reason to not have built this.

### The bisection was inverted, in the function warning about inverted bisections

`clopper_pearson_lower` returned `0.0000` for every imperfect input while the
perfect cases passed on a closed-form early return — so `250/250 → 0.9881`
looked right and `249/250 → 0.0000` was never seen. The docstring warning
about exactly this failure sat directly above it.

Caught because the test pins the **one-error** case against ADR-0015's own
table, not only the clean sweep. Pinning only the clean sweep would have
passed. That is the `inert` remedy working: a test that asserts the check can
be wrong, not only that it can be right.

**239 verified of 250.** `optcg:CN-S` blocked_on_external, target unchanged,
review 2026-10-06.
