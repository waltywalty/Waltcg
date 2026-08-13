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
