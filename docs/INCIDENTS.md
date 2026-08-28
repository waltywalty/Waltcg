# Incidents

A production incident is a defect that **cost data or cost money in a live
run**, as distinct from a finding an audit made about code that had not yet
misbehaved. `docs/OPEN_ISSUES.md` carries findings; this file carries the ones
that ran.

Each entry states what happened, when, what it cost, and — separately and
explicitly — **what is established from committed artifacts versus what is
inferred**. The distinction is the point: this project has twice drawn a
conclusion from a number that excluded most of the evidence.

---

## INC-001 — Two client-side amplifiers spent the catalog budget, and one of them fired on a stop signal

**Opened:** 2026-08-27 · **Status:** both amplifiers fixed, neither proven
against the live service · **Severity:** S1 — three of eight game/language
combinations have had no catalog for weeks, and 109 of 239 labelled rows are
consequently unmeasurable.

### Two separate defects, in two different sources, conflated in one commit

They were fixed in the same commit and described together, and that was a
mistake in the write-up. They are not the same incident and only one of them
explains the outage:

| | **A. apitcg per-card fetch** | **B. tcgdex refusal-as-verdict** |
|---|---|---|
| Source | apitcg | tcgdex |
| Where | `ApiTcgAdapter.fetch` (price step) | `TcgdexAdapter.filter_is_honoured` (catalog step) |
| Shape | one `?code=` request per card, for a field `/api/products` serves 100 at a time | `except (AdapterGaveUp, RateLimited): return False` → caller reads "fall back" → per-card enumeration |
| Cost if triggered | ~3,494 requests where ~35 serve the same data | up to 8,313 single-card fetches |
| Games affected | optcg EN/JP, riftbound EN, pkmn | pkmn only — **tcgdex does not serve One Piece or Riftbound at all** |
| Evidence it fired | strong (below) | **none found** |

**Defect B cannot explain the empty-catalog arc.** `tcgdex` raises
`AdapterGaveUp("a Pokemon-only database")` for any non-Pokémon game, and
`_combo_status` for all three dark combos records
`tcgdex_does_not_serve_no_cards`. tcgdex was never going to enumerate One
Piece, rate limit or no rate limit. B is a real hazard with a documented price
tag and it is fixed, but it is a finding, not this incident. Every pkmn combo
it could have touched is `ok` or `ok_via_fallback`.

The rest of this entry is about **A**.

### Timeline — established from committed artifacts

| Date | Run | What the repository records |
|---|---|---|
| 2026-08-17 | #9 | "apitcg made 250 calls and supplied every combination it serves" (ADR-0029). tcgapi demoted to price-only; apitcg becomes the **sole** catalog source for optcg and riftbound. 5,582 cards in the target list. |
| 2026-08-17 | #10 | 250 apitcg calls, **no 429** (dated rate-limit record). |
| 2026-08-18 | #11 | 429 **after 16 calls**, four attempts behind each, so up to 64 requests reached the service. "Every apitcg-served combination went to zero." Two-strike breaker added (ADR-0031). |
| 2026-08-18 → | #12+ | Catalog persisted and served from cache, so a refusal stopped costing the day's data — **for combos that had ever been enumerated**. optcg and riftbound never had a cache entry to fall back to: `cache: absent`. |
| 2026-08-25 | last | `optcg:EN`, `optcg:JP`, `riftbound:EN` — `status: rate_limited`, `asked: ['apitcg']`, `reasons: ['apitcg_rate_limited', ...]`, `cache: absent`. `_counts` for all three: **0**. |
| 2026-08-27 | — | `optcg`/`riftbound` = 109 of 239 labelled rows with no catalog entry to measure against (ADR-0057). |

### The mechanism

The workflow runs the catalog step **before** the price step:

```
Build targets   (ingest.catalog --write)   apitcg: ~250 paged /api/products calls
Run adapters    (ingest.runner)            apitcg: one /api/products?code= per card
```

Every non-Chinese card routes to apitcg for pricing — 3,494 on the current
list, 5,582-ish at run #9. So each daily run asked apitcg for a few hundred
catalog pages and then, minutes later, **several thousand single-card
requests, for Pokémon cards, to fill in an `artist` field.**

Those two steps share nothing except the provider's quota. The Pokémon price
fetch and the One Piece catalog enumeration have no relationship to each other
in the design; they are coupled only through a ceiling nobody documents.

**The consequence is directional and it matches the outage exactly:** the
catalog step runs first and gets whatever budget is left from the *previous*
run's price step; the price step then spends the rest. The combos that went
dark are precisely the ones apitcg alone serves.

### What is inferred, and what would settle it

**Inferred, not established:** that our own price-step load caused the run #11
refusal. Two things are missing and neither is recoverable from the
repository:

1. **The job summary is not committed.** Per-run call counts exist only in
   GitHub Actions logs, and each workflow step is a separate process, so the
   250 in the dated record is **the catalog step's count alone**. The price
   step's several thousand requests were never written down anywhere.
2. **The window is unknown.** If apitcg's quota is per-minute, run N's price
   step cannot poison run N+1's catalog step 24 hours later. If it is daily or
   a rolling 24 hours, it certainly can.

**This is the load-bearing correction.** The dated rate-limit record reasons
from 250-then-16 to *"more consistent with a per-minute or per-hour window
than a daily one"* — and that inference was drawn from a call count that
**excluded roughly 95% of the requests we sent that day**. It is not
necessarily wrong; it is unsupported. A daily cap is entirely consistent with
"250 catalog calls fine on the 17th, refused at 16 on the 18th" once you add
several thousand price calls to each day.

A third hypothesis the numbers now permit, and which nothing in the repository
had raised: **`APITCG_KEY` may not be set at all.** The workflow passes
`secrets.APITCG_KEY`, and whether that secret exists is unknowable from the
sandbox. An anonymous per-IP quota, on a GitHub Actions runner sharing egress
IPs with every other job on that host, would explain 250-then-16 better than
any window we have hypothesised — because the ceiling would not be a function
of our call count at all.

### Cost

- **Three of eight combinations with no catalog** since run #11 — `optcg:EN`,
  `optcg:JP`, `riftbound:EN`, ~7 weeks.
- **109 of 239 labelled rows unmeasurable** by the catalog-in precision
  measurement, which is why its honest headline is a 95% lower bound of
  **0.5493 on n=5**.
- The arc consumed roughly fifteen sessions of diagnosis. Every one of them
  looked at the provider.

### Fixes, and the instrumentation that should have shown it

1. `ApiTcgAdapter.index_by_code` — one paged sweep per game,
   `ceil(total / 100)` calls, serving every target from the index. A refused
   sweep **propagates** rather than falling back to thousands of requests.
2. `TcgdexAdapter.filter_is_honoured` — `RateLimited` propagates;
   `AdapterGaveUp` returns `FILTER_UNMEASURED` and the strategy records that
   the probe was never taken. (Defect B.)
3. **The run report now carries `Cards`, `Batched` and `Amplification`
   columns.** A call count with no denominator reads as a provider ceiling;
   with the card count beside it, an amplification factor is arithmetic. On
   run #10 this table would have read `apitcg | 5582 | 5582 | 56 | 100x`.
4. **The preflight answers the key question in one word** — `key=yes/no/n/a`
   per source, presence only, never the key.

### What this incident is really about

Both amplifiers were client-side, and for seven weeks the diagnosis was
pointed at apitcg's quota. The run report could count how many times we were
refused and could not show how many requests we sent per card. **A limit you
cannot see yourself approaching reads as somebody else's limit.**

The order of operations from here is fixed and not negotiable by impatience:
read the preflight `key=` column, then run the sweep, then — and only then —
ask whether there is a paid tier.

---

## INC-002 — The mutation harness sabotaged its own baseline, twice

**Opened:** 2026-08-27 · **Status:** fixed · **Severity:** S3 — no data lost;
two verification results were wrong for about an hour.

`audit/mutate.py` edits source files in place and restores in a `finally`,
which **does not run on SIGTERM**. A run killed by a shell that stopped
waiting left `interval_properties.battery`'s `check()` as a bare `pass`. The
next two runs measured a baseline of `failures=11` instead of `failures=6`,
absorbed the sabotage into the number everything is compared against, and
reported two **false MISSED** results — `apitcg: the sweep stops after the
first page` and `headline: the gate quotes its own figure alone`. Both came
back CAUGHT once the tree was clean.

The per-mutant anchor check in `_run` would have caught it, **for a mutant in
the selected subset.** `--only "apitcg:"` never opens `interval_properties.py`.

Three fixes, all of them removing a subset exemption:

- `verify_tree()` checks **every** catalogued anchor before any baseline is
  measured, whatever `--only` says, and refuses rather than reporting.
- `check_seal()` is no longer skipped under `--only`. That exemption was the
  same defect one level up: a catalogue that silently halved read as a clean
  filtered run, and `--only` is how the harness is actually used.
- SIGTERM and SIGHUP are turned into exceptions so the restore path executes.

The harness docstring already said *"a harness that times out mid-mutation
leaves a sabotaged repository behind... That has happened."* It had happened
once, been written down, and happened again — the third time this exact lesson
has landed in one session, after the inverted bisection and the ADR-0045
table. **Recorded knowledge is not a control.**
