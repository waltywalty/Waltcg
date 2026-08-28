# Open issues

Severity tags: **S1** wrong numbers reach a decision · **S2** data lost or
merged silently · **S3** reported wrongly but recoverable · **S4** cosmetic.

Session ritual says this file is updated at the end of every session. It did
not exist until run #11; the entries below are the ones live at that point,
not a full history.

---

## S1 — the composite score is still disabled, and correctly so

`SCORE_ENABLED=false`. It has not been benchmarked out-of-sample against a
pre-registration, so nothing here is a signal yet. Unchanged, and not a defect.

## S2 — Celebrations prints four different cards at collector number 15

`cel25c-15_A1` .. `_A4` are Venusaur, *Here Comes Team Rocket!*, Rocket's
Zapdos and Claydol. Four **different cards**, one collector number, and the
provider disambiguates them with a suffix that looks exactly like One Piece's
parallel marker but means something else entirely.

Three card_uids collide as a result (`pkmn:cel25c:15:base:EN`). They are the
only collisions left in the Pokémon catalog after the One Piece fix.

**Not fixed, deliberately.** The One Piece rule is scoped to One Piece
(`ID_SUFFIX_VARIANT_GAMES`) because applying it here would label four distinct
cards as parallels of each other, which is worse than the collision. The right
fix is a set-specific rule for Celebrations, and it needs someone to look at
what the printed numbers actually are.

Cost of leaving it: three Classic Collection cards share a price series.

## S2 — One Piece CN-S has no catalog source

tcgdex is Pokémon-only; apitcg has no Chinese One Piece. Manual entry for v1.
Recorded rather than discovered from an empty screen.

## S3 — apitcg's rate limit is unknown

Not in `openapi.json`, not in a response header, not on the docs site. 250
calls succeeded on 2026-08-17; 16 were refused on 2026-08-18. Two data points,
recorded in `config/rate_limits.yaml`, and not enough for a daily quota — the
shape is more consistent with a per-minute or per-hour window.

Mitigated rather than solved: the catalog cache means a refusal costs nothing,
and the two-strike breaker means we stop asking. Add each run's numbers from
the ingest step's rate-limit table.

**ESCALATED 2026-08-27 to INC-001** (`docs/INCIDENTS.md`) — three of eight
combinations dark for ~7 weeks and 109 of 239 labelled rows unmeasurable is a
production incident, not a measurement finding. The incident entry carries the
timeline, the mechanism, and an explicit split between what is established from
committed artifacts and what is inferred.

**The inference in `config/rate_limits.yaml` is withdrawn.** Both observations
count the CATALOG step only; each workflow step is a separate process and the
next one was sending thousands of per-card requests to the same provider. "250
calls" excluded roughly 95% of what we sent that day. A daily cap fits the two
observations perfectly once the price step is counted — and so does an
anonymous per-IP quota if `APITCG_KEY` is unset.

**AMENDED 2026-08-27 (ADR-0062): the quota was not the binding constraint.**
`ApiTcgAdapter.fetch` was making one `?code=` request **per card** — 3,494 on
the current target list — for an `artist` field `/api/products` serves 100 at
a time. A 3,494-call run against a source that refused at 16 was never going
to finish. `index_by_code()` now sweeps the game once, `ceil(total/100)` calls
(~35 for One Piece), and serves every target from the index. Unproven against
the live service.

Still open, and now the right questions to ask in that order:

1. **Is `APITCG_KEY` actually set?** The plumbing is there — `key_env`,
   `x-api-key` confirmed in the OpenAPI `securitySchemes`, `ingest.yml` passes
   the secret. Whether the secret exists is not knowable from the sandbox. The
   preflight table prints key presence, length and first four characters every
   run; read it. An anonymous per-IP quota on a shared Actions runner egress
   IP would explain 250-then-16 better than any window we have hypothesised.
2. **Does a keyed sweep still get refused?** Only worth asking after 1 and the
   sweep, because the question has changed from "can we afford 3,494 calls" to
   "can we afford 35".
3. **Is there a paid tier?** Only if 2 comes back badly. Unverifiable here.

## S1 — Model A cannot run at all: three assumptions are null

Every tier on every route refuses with `ConfigIncomplete` on the same three:

```
assumptions.submission_selection_haircut.current_value
assumptions.empirical_bayes_prior_strength.current_value
assumptions.empirical_bayes_min_card_pop.current_value
```

23 tier/route pairs, no exceptions. These are the registered assumptions
CLAUDE.md calls known-fragile — the haircut is "a guess until calibrated
against my own submission results" — and the model refusing rather than
picking a plausible default is the correct behaviour, not a defect. But it
does mean **Model A produces nothing today**, and that is worth stating
plainly rather than leaving to be discovered from an empty screen.

Unblocking it is a decision, not a fix: put a number in with a calibration
plan, or leave it refusing.

## S2 — PSA's four Value tiers are null, and TAG has no route

`PSA.value_bulk`, `value`, `value_plus`, `value_max` each have a null `fee`,
`min_cards` and `turnaround_business_days` — PSA paused those tiers in June
2026, which is exactly why they live in dated config. Two more tiers block on
`turnaround_business_days` alone: `BGS.base`, `BGS.base_subgrades`, and all
four SGC tiers.

Separately, `config/grading.yaml` declares four routes — `cgc_uk`, `psa_us`,
`bgs_us`, `sgc_us` — and none of them is TAG. So TAG's four tiers are
unreachable from Model A regardless of their config: there is no route that
gets a card to them and back.

## RESOLVED — C6 has a kind, and the gate requires it

`same_printed_number_different_treatment`. Verbose on purpose: it names the
thing that matters and cannot be mistaken for `alt_art_variant`, which is C3
and requires the numbers to DIFFER. **Added to the gate's required kinds**,
because C6 is one of the three blocking failures and a gate that does not
demand a case for it is missing the class it most needs to measure.

14 rows carry it — 10 One Piece base-vs-parallel pairs plus the 4 re-tagged
Riftbound rows below — and all 14 are `verified`.

## RESOLVED — the four Riftbound rows were re-tagged C5 → C6

`299/298`, `299*/298`, `303/298`, `303*/298`. C5 is cards that share a name and
are genuinely different cards; these are two printings of ONE card, treatment
the only difference. The asterisk being printed INSIDE the number is a notation
detail, not a different class — Riftbound writes the treatment into the number,
One Piece writes it nowhere and leaves it to an image filename. Same
relationship, two conventions.

Each row records `reclassified_from` and a note saying why, because a re-tag
with no trace is indistinguishable from data that was always that way. The
guard test is inverted rather than deleted: it asserted C5 while they were
mis-tagged and asserts C6 now, so the next person to change them hits the same
wall.

`map-classes` recomputes `hard_cases` rather than merging into it, so the
re-tag **dropped** the stale `name_is_not_unique`. Merging would have left the
four claiming a gate requirement they no longer meet.

## RECORDED, NOT RECONCILED — two kinds no C class covers

`hard_case` kinds are the schema. The C classes were an **input** — a research
taxonomy built to decide what to collect — and the kinds were derived from
failure modes this repository has actually hit. Where they disagree, the
disagreement stands:

- **`same_number_different_rarity`** (3 rows). Adjacent to C6 and not the same:
  C6 is distinguished only by treatment, and an OP01-025 base SR and its
  parallel both read `SR`. Here the provider reports two different rarities at
  one number, which asks a different question — whether rarity can be trusted
  as a discriminator at all.
- **`box_code_vs_card_number`** (1 row). Not a printing relationship at all,
  which is why no class covers it: a parsing failure mode, found by ingest
  rather than by research.

Neither is forced into a class, and a test asserts neither ever is.

## S2 — the fourth reprint shape has no rows

`same_number_new_set_new_variant` is declared and REQUIRED by the gate, and
nothing carries it. That is the point: a gate that only demands what it already
has measures nothing, and this is the case a set-only test (Celebrations) and a
variant-only test (OP01-025) both miss — a resolver can pass each and still
mishandle the two together.

C6 was NOT widened to absorb it. A widened C6 reads "variant differs, set may
or may not" — a disjunction, and disjunctive kinds are how C6 itself nearly got
buried inside `alt_art_variant`.

The five PRB pairs are the rows it wants. Their originals carry
`reprinted_in: prb01`/`prb02`; the PRB side is not minted because the variant
is the one field no source here supplies. apitcg would give `_p3`/`_p4`/`_p5`,
which is catalog-derived and excluded by rule.

## RESOLVED — OP01-120 `manga_rare` is correctly homed, and the refusal is why

**Closed 2026-08-25, confirmed correct.** The `?v=2` page's variant-scoped
product link reads:

    [Romance Dawn (OP01) Manga Art](/cards/op01-romance-dawn)

Manga is **`op01`**. The two `manga_rare` rows were right all along. Not
re-homed, and no correction event — there was no error to correct.

**The refused inference would have introduced the error.** Two separate
temptations pointed at `prb01` and both were declined:

1. *Order the slots and assume prb01 holds the later ones.* `attest()` writes
   no entry where a page does not name a product rather than falling back to
   slot order.
2. *Read the `reprinted in:` line as this printing's product.* The line
   `This variant has been reprinted in: One Piece The Best (PRB01)` appears
   **identically on the base page and on `?v=2`**, despite the words "this
   variant". It is card-level. Read as variant attribution it attests manga to
   `prb01` — precisely the wrong answer.

This is the one case where refusing to guess is checkable after the fact, so
it is worth stating plainly: the guess was available, it was specific, it was
consistent with everything known at the time, and **it was wrong**. Leaving
the rows counted rather than demoting them on a suspicion was also right —
demoting would have moved the gate numbers away from the truth.

What stays true is the *reason* the rows could not be confirmed earlier:
marketplace attribution for a retained-number reprint is untrustworthy by
construction (`resolve/corroboration.py` → `retained_number_reprint`), tier
`number_only`. That rule is unaffected by the answer turning out to be the
number's own product. It had to be checked against a source that could
discriminate, and it was.

## PRE-REGISTERED — the admission standard for `physical_card`, 2026-08-25

**Written before any row was collected under it.** Same discipline as the
backtest pre-registration: a rule written while looking at the rows it will
admit is a rule fitted to those rows. **If this standard is edited after the
CN-S batch arrives, the edit is the finding.**

`optcg:CN-S` is the last short combo (16 rows) and the only one below the
detection floor. Its candidates are `single_source` because their second
source is Bandai's shared numbering, which attests the *number* and is silent
on whether a Simplified Chinese printing exists.

### What changed, and what deliberately did not

Attestation is now recorded **per field**, not per source. The old tiers ran
two axes together — *which* field a source speaks to, and *how strongly*.
`number_only` meant "attests the number, silent on the printing"; a physical
card is the opposite shape, decisive about the printing and weak about the
number. Reusing the tier name would have made
`tier_counts_toward_verified` mean two different things depending on which
source asked.

**The load-bearing half of the original rule is untouched.** A documentary
EN/JP source still attests *nothing* about whether a CN-S printing exists.
What supplies that is a card in a hand. The rule that blocked these rows is
not being relaxed; a source class that satisfies it is being added, and it
generalises — the same composition works for EN, JP and CN-T.

### What the composition actually guards

The Bandai list and the printed card are **not causally independent** — the
card was printed from that database, so they are one fact observed twice. That
is the right design here, but it means the composite guards **transcription
error, not upstream error**. If the record and the card agreed on something
wrong, nothing here would catch it. Bandai *is* the authority for what the
number is, so that is acceptable — but the claim is "we recorded it
correctly", never "the number is correct".

### The checksum is the mechanism, not the arithmetic

Two partial attestations are not automatically one whole. `optical` composes
with `documentary` because their failure modes are disjoint, **and** because
the number and the name constrain each other: a transcription slip yields
either a number the record does not carry or one that names a different card.
`field_is_established` refuses the composition when the checksum did not run.

### The gap this standard does NOT close

There is no Simplified Chinese catalog source, so the documentary side gives
the **EN or JP** name for the number. Confirming that 阿修罗童子 renders
"Ashura Doji" is a **translation**, and a translation performed here is not a
source — it would be this repository corroborating itself.

So the SC **name** is attested optically only, with no second channel, and
every row carries `name_attestation: optical_only`. The name is not an
identity field — it drives `cross_language_name_disagreements`, which has
caught three errors, but it is not what the resolver is tested on. Registered
in `NOT_REACHED` and asserted by a test, so it cannot be quietly assumed
closed later.

### Protocol, recorded because memory is not a control

1. **The reader goes first.** The card's holder states number and name off the
   card; the documentary record is consulted **after**. Drafting a row and
   asking for confirmation is forbidden by name — a confirmation against a
   prior is the same defect as fixtures agreeing with the regexes they were
   written from, and it breaks the only thing making the composition worth
   more than its parts.
2. **Unsure is unresolved.** Ambiguous, damaged or uncertain printed text is
   recorded unresolved, never guessed and never filled from the EN row. If
   that yields 12 rows instead of 16, the set is 12 and the shortfall stays
   visible in the gate.

### Two reading methods, one channel

**`direct`** — the holder reads the card. **`photograph`** — the holder
photographs it and a second person reads the image.

A photograph removes the holder's transcription step on the **name**, which is
the one field with no checksum, and it is **not** the forbidden pattern: an
image carries no prior of the reader's to agree with. It does **not** add a
channel. Same optical evidence, one artifact, one reading, and
`physical_card` stays `optical` about the name either way. Two people reading
the same image is still one channel — they share every failure the artifact
has, and a cropped number is cropped for both. `composes` refuses
`optical` with `optical`.

**Two roles, recorded separately.** The photographer owns *which card* and
whether it is legible — wrong copy, cropped number, glare, focus. The reader
owns *transcription* and nothing else. One field for both would lose the
distinction that makes recording them worth anything, which is the mistake
`number_only` was making when it had to mean two things. So `imaged_by` and
`read_by` are separate fields, and `reading_method` is stated rather than
inferred from which fields happen to be present.

**The image makes the reading auditable.** The standard says a card in a hand
is not re-checkable — unlike a URL, nobody can go and look again. A photograph
changes that, and since a later CN-S catalog source disagreeing is the live
falsification risk, being able to re-read the glyphs is worth having. That
strengthens the **provenance**, not the tier: nothing about the composition
moves.

`image_ref` — a filename or content hash the holder keeps — identifies which
image was read. **The image itself is never committed**: it is a photograph of
copyrighted card art, the same redistribution rule provider data lives under.
A photograph nobody can find again is a card in a hand, and
`reading_is_re_checkable` returns false for one.

### The back door a photograph opens

The reader cannot make out a character and asks the holder *"is this 阿?"*

**That is the forbidden pattern arriving through the photograph instead of
through a drafted row.** The holder is now agreeing with a candidate rather
than reading, and the agreement carries no information. It is short enough to
walk without noticing, so it is named in `ILLEGIBLE_GLYPH_ROUTE` and closed.

Instead: take a fresh photograph — better light, closer, different angle — and
read that, or record the field **unresolved**. Asking the holder to read the
character aloud *without being offered a candidate* is fine; that is a
reading, not a confirmation. The distinction is whether a candidate was
supplied before the answer.

## FIXED — the resolver is never given the set totals it needs to bridge a number

**Found by the catalog-in measurement on its first run**, and it is exactly
the class of defect self-records cannot produce. Fixed 2026-08-27, ADR-0059.

`printed_from_bare("011", 78)` returned `011/078` correctly and nothing called
it. The catalog built `pkmn:swsh10.5:011:base:EN` from tcgdex's bare `11`
while the card — and the labelled row — both say `011/078`, so a price
fetched against the catalog uid landed on an identifier nothing else referred
to. That presents as a card with no price rather than as an error.

`ingest/catalog.py:bridge_numbers` now runs as a post-pass inside
`to_targets`, and `targets.json` carries `_number_bridge` per combo.

| | before | after |
|---|---:|---:|
| labelled rows whose uid appears in the catalog | 0 | 4 |
| catalog rows bridged bare → printed | 0 | 3,292 |
| refused, set total unknown | — | 419 |
| refused, no readable index | — | 168 |
| refused, would have merged two cards | — | 0 |

Only five labelled rows had a catalog row the bridge could speak to at all.
Four now agree. The fifth is below.

## S2 — the catalog calls `sv03.5:205/165` a base card and the label calls it `ur`

The one uid the number bridge did **not** close. Catalog says
`pkmn:sv03.5:205/165:base:EN`, the labelled row says
`pkmn:sv03.5:205/165:ur:EN` — same card, same number, different variant, so
still two price series.

The number is now right, so this is purely the rarity→variant mapping in
`resolve/identity.py:_RARITY_RULES`. **Not fixed by widening
`NUMBER_VARIANT_GAMES`**: it is `{riftbound}` deliberately, and deriving a
Pokémon variant from its number would export one game's conventions to
another. It needs a rarity rule, and it needs someone to check what tcgdex
actually sends for an Ultra Rare.

Cost of leaving it: one known card, and an unknown number of others in sets
the catalog does not yet cover.

## S3 — 587 catalog rows carry a number the bridge cannot read

Counted, named, and not defaulted — `_number_bridge` in `targets.json`.

* **419 have no set total.** All promo sets: `SV-P`, `M-P`, `mep`. Their
  printed denominator is a letter code, not a count, so no total exists to
  supply.
* **168 have no readable index.** `SV001` (Shining Fates Shiny Vault), `TG15`
  (Trainer Gallery), `CC001` (Celebrations Classic), `SH1` (Dragon Majesty
  Shiny). They print as `SV001/SV122` — a lettered numerator *and*
  denominator, which `parse_collector_number` does not read.

Both leave the row bare rather than guessing. A miss that is counted can be
fixed; a default cannot. The second group is the tractable one: it is a
parser rule, not missing data.

## RUNNING, UNCERTIFIED — precision, catalog entry in → labelled uid out

Built and running. Unlike the gated self-record figure, **this measurement can
fail.** Its first run resolved nothing at all — every pairable row refused —
and that turned out to be the wiring, not the resolver (ADR-0060).

| | first run | now |
|---|---:|---:|
| verified rows | 239 | 239 |
| catalog entries | 3,879 | 3,879 |
| pairable, `set_and_name` | 7 | 7 |
| pairable, `field` | 0 | **10** |
| resolved and usable | **0** | **7** |
| precision, `field` | undefined | 1.0000, 95% LB **0.5493** |

### THE HONEST HEADLINE IS 0.5493 ON n=5

Not 1.0000. The point estimate sits on five resolutions and is compatible with
a resolver that is wrong 45% of the time. **Quote the bound with its n,
everywhere** — `audit/checks/catalog_precision.py:headline` prints it above
any point estimate, `tests/test_resolver_gate.py:HONEST_HEADLINE` carries it
into the gate's own message, and both are tested.

It is also the first precision figure this project has ever produced that
*could* have come back bad. The gated 1.0000 on 239/239 is a
no-merge/no-collision check on self-records: the input is built from the
labelled row and the expected uid is derived from the same fields, so it
cannot fail. Four sessions read it as evidence.

### Getting the join right took three attempts, and two were wrong

**Name-only join — invalid.** It paired the labelled Base Set Blastoise with a
`bw8` Blastoise. Character names repeat across dozens of sets.

**Set+name, first match — invalid.** It paired labelled `sv03.5:003/165`
Venusaur ex with catalog `sv03.5/198`, a *different printing of the same
character in the same set*. Non-negotiable 3 says those are different cards,
and the pairing would have scored the resolver **wrong for being right**.

**Set+name, unique on both sides** — valid, and it leaves 7 rows. Ambiguity is
reported, never resolved by taking the first match.

That is the fundamental difficulty, stated rather than worked around: **you
cannot pair a catalog entry to a labelled row without using the number, and
the number is the thing being measured.** What remains is the subset where
set+name happens to be unique.

### What limits coverage, and none of it is this measurement's design

1. **`optcg` and `riftbound` have no catalog at all** — apitcg rate-limited
   for several consecutive runs, so 109 labelled rows have nothing to measure
   against.
2. **The catalog names cards in the local script**, the labelled set in Latin,
   so `pkmn:JP`, `pkmn:CN-S` and `pkmn:CN-T` cannot join on name.
3. **Set coverage barely overlaps** — 6 shared sets out of 31 labelled and 201
   catalogued.

### On the count

Deliberately **not** gated and asserts no threshold. The 250-row count
licenses a precision *claim*; taking the measurement never needed to wait for
it. The certified claim comes when the count closes; the interval is reported
now.

## S1 — ADR-0015's threshold assumes ground truth is correct, and that is unmeasured

**Measured precision is capped at `(1 - e)`**, where `e` is the ground-truth
error rate: a perfect resolver disagrees with a wrong label. ADR-0015 sets the
gate at 0.98 and never states the assumption underneath it — that `e` is
small enough not to matter.

**Three errors are already known in this set** — the OP01-002/003 name swap,
OP01-121 named as the wrong character, and the same card under two set-code
spellings. All were found by **cross-batch comparison, not by any check**, and
the coverage of that comparison is thin (`name_disagreement_coverage` reports
31 numbers ever actually compared). The uncaught rate has never been
estimated.

At 250 rows, 0.98 allows **5 errors**. If `e` is around 1%, label noise alone
consumes half that budget before the resolver is asked anything. The gate's
central number currently rests on an unestimated quantity.

### The measurement, and what N can bound

Blind re-verification, same shape as the art-call protocol: draw a sample,
send **`game / set_code / number / variant / language`** and withhold the
**name** — the field all three known errors live in, and the answer. The
researcher re-derives; the comparison is mechanical; disagreements are
findings, and nothing is corrected or demoted on their strength.

**N=30 cannot certify the threshold.** The arithmetic, computed rather than
asserted:

| N, zero disagreements | 95% bound on `e` |
|---:|---:|
| **30** | **≤ 9.5%** |
| 100 | ≤ 3.0% |
| **149** | **≤ 2.0%** ← what the gate needs |
| 239 (all of it) | ≤ 1.2% |

So thirty rows is a **screen**, not a certification: if `e` were 10% a clean
sample of 30 happens only 5% of the time, so it will find a gross problem
cheaply, and a clean result licenses nothing except moving on to a real
sample. Staged deliberately — if the screen finds two or more disagreements,
nobody needs 149 rows to know there is a problem.

Note the second option is nearly the whole set. At 149 of 239 you are 62% of
the way to re-verifying everything, and doing all 239 buys `e ≤ 1.2%`.

### The contamination is worse than optimistic

The researcher assembled most of this set and may recall a name rather than
re-derive it. That biases the estimate optimistic — a **floor** on `e`, never
unbiased. Sharper, and stated because it changes what the number is worth:
**where the recalled memory is of the original mistake, the re-derivation
reproduces it and the comparison agrees.** The bias is not even noise. It is
blind precisely to errors arising from the researcher's own systematic
habits — and all three known errors are exactly that class.

A fresh researcher, or a session with no access to this project, is the clean
instrument. This one bounds `e` from below.

### DECIDED 2026-08-25 — screen, then stop. The 149 is not run.

**The bound is largely redundant with the measurement it conditions.**
Ground-truth errors show up as disagreements, so if the resolver agrees with
the labels on fraction `p`, then `e ≲ 1 - p` — every ground-truth error either
appears in the disagreements or was masked by the resolver making the *same*
error. Measuring 0.99 bounds `e` near 1%. **Passing the gate at 0.98 bounds
`e ≲ 2%`, which is what the 149 would have certified.**

The relationship is not viciously circular; it is self-limiting. You cannot
measure 0.98 against ground truth carrying 8% errors. The one gap is
*correlated* error — resolver and labeller producing the same wrong answer —
and the set is built non-catalog-derived specifically to avoid that.

So the 149 buys almost nothing in the success case. It matters only in the
**failure** case: precision lands between roughly 0.90 and 0.98, resolver
debugging comes up empty, and blame has to be apportioned between the resolver
and the ruler. **Held in reserve with that trigger, not pre-paid.**

Independently: the resolver feeds EV models whose own error bars are far
wider — an uncalibrated submission-selection haircut, community-sourced pull
rates, single-digit grade-level comps. Spending a second labelled-set build to
tighten a label bound from 9.5% to 2% optimises the wrong term.

### The claim that ships instead

> Resolver precision is measured **against this ground truth**. A clean 30-row
> blind screen, run in a fresh session, bounds ground-truth error at
> `e ≤ 9.5%` (95%) — a **floor-biased** bound, because a contaminated reader
> cannot see its own systematic errors. `e` is **not** certified below the 2%
> the 0.98 threshold assumes, and any precision claim is conditional on that
> bound.
>
> The bound `e ≲ 1 − p` is **not available on the current measurement**.
> It requires the resolver's input to be independent of the label, and
> precision is measured on **self-records** — the row goes in and its own
> `card_uid` is expected back — so correlated error is total rather than
> residual. `name` is not even a component of the uid, so a name error, the
> class all three known errors belong to, cannot produce a disagreement at any
> resolver quality. The bound becomes available when precision is measured
> **catalog entry in → labelled uid out**.
>
> Consequently the **self-record figure of 1.0000 is a no-merge/no-collision
> result, not a resolution result**, and the 149-row sample is back on the
> table sooner than ADR-0055 implied: if a real `e` is needed while precision
> is still self-record-measured, there is no exoneration route.

Two things that wording fixes over the first draft: it is **conditional on the
screen coming back clean** rather than asserting the bound in advance, and it
says the 9.5% is itself optimistic rather than presenting it as `e`.

### Not decided here

**ADR-0015's 0.98 was chosen without `e` in the model.** A threshold derived
conditional on `e` is the principled fix and is deliberately NOT taken as a
side effect of this thread. Worth weighing when it is: given the argument
above it may move the number very little, since the binding constraint is the
same measurement either way. What it would change is the interpretation — the
gate stated honestly as a claim about **joint resolver-plus-label quality**,
which is what it has always measured.

### Status

The draw is committed in `contracts/reverification_draw.json` **before any
answer exists** — the blinding is a sequence, not an intention, and a sample
chosen after seeing results is not a sample. Seed pinned; a test asserts the
committed draw reproduces from it. It awaits a fresh session.

Does not block the CN-S rows.

## S1 — 238 of 239 verified rows have never been tested by the gate

**The retroactive sweep.** `ingest` is gated now — a claim about rows arriving
tomorrow. The 239 already in the set were admitted while the check was not
called, so "the gate is wired" and "ground truth passes the gate" are
different statements and only the first was true.

| Verdict | Rows |
|---|---:|
| PASS — the gate read evidence and approved it | **1** |
| VACUOUS — the gate approved because there was nothing to read | **238** |
| FAIL — the gate read evidence and refused it | **0** |

**Nothing fails. Nothing is demoted. And that is not reassurance.**

Zero rows carry `source_class`. One carries an `upgraded` block naming a
second source. So for 238 rows the gate returns `True` because there is no
input — not because the row passed. Reporting that as `239/239 PASS` would be
a clean bill of health issued without an examination, which is this project's
recurring defect arriving one layer above the checks it has been fixing.

**What the 239 actually carry:** `source: external_research` on all of them,
`attested_by` on 2, `upgraded` on 1. Nothing else. They were admitted under a
regime that recorded `confidence` as an **assertion** rather than as a
derivation from named sources, so there is no machine-readable record of which
two sources agreed for 238 of them.

The count is still 239. What has changed is what "239 verified" means: **239
rows asserted verified by a researcher, of which 1 can be re-checked from the
file.** Every combination is affected; the vacuity is uniform, not
concentrated.

S1 because ground truth is what the resolver is measured against and its
evidentiary basis is weaker than the number implies. Not S2: no row is known
wrong, and the sweep found no contradiction.

**Not fixed here, deliberately.** Backfilling `source_class` onto 238 rows
from their prose notes would be manufacturing the evidence the gate reads, and
the gate would then pass on values I wrote to make it pass. That is worse than
an honest vacuum. `audit/checks/sweep_ground_truth.py` is a REPORT, not a
gate — a description that can fail a build gets silenced rather than read.

## RESOLVED — the `git ls-files` scope bug, in both audits, actually fixed

**Noted in ADR-0042. Not fixed for three sessions. Then reproduced verbatim in
`no_unguarded_elevation`.**

`no_provider_data` and `no_pdf_provenance` both read `git ls-files`, which
returns TRACKED paths only. A payload or a document written this minute is
untracked — and these checks run *before* the commit that would track it. They
reported `clean` about a universe that excluded the file in question.

Both now read tracked files **plus untracked-not-ignored** ones: exactly what
the next `git add -A` would commit. `--exclude-standard` respects
`.gitignore`, so a payload sitting in `raw/` — where it belongs — is still out
of scope. Flagging that would train people to ignore the check, which is a
slower way of turning it off.

**Rule 1 of `no_provider_data` stays tracked-only on purpose.** Its claim is
"tracked at all means somebody used `--force`", and an untracked file under a
forbidden path is the system working.

Demonstrated failing before being called fixed — the `inert / by_scope` remedy
is *prove it can fail*, and this entry previously claimed a remedy that was a
sentence in a document.

## RESOLVED — `upgrade` existed and was wired to nothing

**Asked: is `physical_card` a valid `--second-source`? Answer: yes, and that
was the problem.**

`second_source` was a free string — stored verbatim, validated only for being
non-empty. Nothing hardcoded a documentary source, so the ten CN-S candidates
could always have moved. But nothing validated *anything*:
`--second-source "looked about right"` promoted a row to ground truth exactly
as readily as a physical card did.

**The entire per-field standard in `resolve/corroboration.py` was not
connected to the one command that promotes rows to `verified`.** Four ADRs of
composite rules, reader profiles, checksums and blindness protocols, and
`upgrade()` never called any of it. A control that is not wired to the thing
it controls, in its purest form.

Now `second_source_is_admissible` runs on both the single-row and batch paths:

- An unclassified string is **refused**, with the known classes listed.
- `other:<name>` is the deliberate escape hatch — accepted, and **recorded as
  unclassified**, which is a different thing from being waved through as if it
  had been checked.
- `physical_card` additionally requires the full provenance and must satisfy
  `row_is_verifiable` for the composite.

The one historical upgrade (`pkmn:csv3C:155/130:sar:CN-S`, PriceCharting) is
normalised to `other:PriceCharting` with a note. Not a change of claim —
PriceCharting was and is the second source. The prefix records that **nobody
has analysed what it attests per field**, which is different from it having
been checked and found sufficient.

### Batch upgrades, because the provenance does not exist yet

The single-row path reads provenance **off the card**, which cannot work for
rows that do not carry it — and none of the ten do. `upgrade --rows FILE`
supplies the provenance with the promotion, attaches it, validates the
composite, and refuses the row if it does not hold.

`UPGRADE_MAY_ADD` bounds what a batch entry may attach: reading method,
reader, checksum, attestation, source class. **Not `number`, `variant`,
`language` or `name`.** An upgrade records how a claim became better
evidenced; it never edits the claim, and an entry attempting to is refused
naming the fields.

### `unstated` is not upgradeable, and does not need to be

`UPGRADE_PATH` is only `single_source → verified`, and that is right:
**`unstated` means the source count was never recorded — not "one source".**
Promoting it on one physical card would claim two independent sources without
knowing the first exists or is independent.

The path already exists: **`ingest --supersede-unstated`**. A claim replacing
a non-claim, appended with a `supersedes` reference rather than editing in
place, carrying forward anything the new row does not supply (`hard_case`
tags, artist). So those rows arrive as **new rows with full provenance**, not
as upgrades.

Five rows sit at `unstated`, not four — `pkmn:csv6C:152/128:sar:CN-S` as well
as the four One Piece treasure rares. All five are eligible for supersede if a
physical copy exists.

### DECIDED — CN-S rows are admitted on the number alone, with NO name

**Both of us were reasoning about the wrong field.** Every existing CN-S row
carries a **Latin reference name** in `name`; the printed Simplified Chinese
characters live in `note`. The detector sees all 28, and one row already
states the policy verbatim: *"Printed Chinese name not verified by the
research; the reference name is recorded and the printed name is absent rather
than guessed."*

`cross_language_name_disagreements` is **Latin-only by construction** — it
skips a non-Latin name because comparing 阿修罗童子 to "Ashura Doji" is a
translation, which is the gap already registered in `NOT_REACHED`. So the SC
characters were never what the detector consumed, and the cost as originally
stated does not apply.

**But the alternative is worse than the stated cost.** The detector's power
comes from the CN-S Latin name being an **independent observation**: batch 2's
swap was catchable because the researcher transliterated from a CN-S source
and the result disagreed with EN/JP.

Fill `name` from Bandai's EN record instead, and **the detector can never
disagree** — the name was derived from the record it is compared against. It
runs, it passes, and its passing means nothing. That is the fifth instance of
this session's defect and the most expensive, because the check it disables is
the one that has caught three real errors. Registered as
`DERIVED_NAME_IS_INERT`.

**So: no name at all.** Not the printed characters, and not a Latin reference
copied from the documentary record. An absent name makes the row **visibly
skipped**; a copied one makes it vacuously passed. The rows are
identity-complete and name-absent, which is what "when a source cannot supply
a field, delete the field" already required.

**The names remain available and additive.** A transliteration of the printed
characters is an independent path to the Latin name, so it restores the
detector — it just must not hold up the identity rows, and it must not come
from a reader who cannot check it.

### ACCEPTED — `art_identification` as an independent path to the Latin name

Reading the **artwork** and naming the character is a different channel from
reading glyphs: the evidence is the picture, not the text. It is therefore
independent of Bandai's record, so a CN-S row named this way **can** disagree
with the EN or JP row at that number — which is what makes the detector live
again on rows admitted by number alone.

It also cross-checks the **number**: an art call disagreeing with the
documentary name for the transcribed number means either the number was
misread or the call was wrong, and that is a finding on the field that
otherwise has one channel.

Accepted with three tightenings.

**1. Blindness must cover the printed name, not just the number.** A
Simplified Chinese card name is a **phonetic transliteration** — 索隆 is
*Suǒlóng* is *Zoro*. The same partial read that disqualifies the glyph channel
is more than enough to anchor an art call. Withholding the number while
showing the name would leave the "independent" channel reading the answer off
the card in the script we established it reads badly. `ART_CALL_BLINDNESS`
withholds `number`, `card_uid`, `set_code`, `printed_name`,
`documentary_name` and `note`; the image is all that is shown.

Ordering is enforced as **sequence, not intention**: art calls are committed
before the checksum runs, and `art_call_admits_a_name` refuses a call whose
commit does not predate it. What anyone remembers about the order is not the
record.

**2. THIS SESSION MAY NOT MAKE THE CALLS.** Not *should abstain where
contaminated* — **must not call**. This conversation holds the OP01 cast, the
numbers from eight batches, the 014/015 dispute, and it **printed the CN-S
candidate list verbatim** a few turns ago while checking the detector.
Withholding the number from an image withholds nothing from a reader that
already has the list. The call would be matching pictures against names
already read, which is not weakened independence — it is none.

Abstention is not the remedy either: it presumes the reader can tell which of
its identifications came from the picture and which from the conversation. It
cannot. **The contamination is per-reader, not per-card.**

Calls come from a **fresh session** given the images and nothing else — no
numbers, no names, no project context, no prompt describing the batch. It is
recorded as a **distinct reader identity, never `Claude`**; a shared label
erases the only thing that makes the call worth anything.
`art_call_admits_a_name` refuses a call with no identity, an identity of
`Claude`, or no `fresh_session` declaration.

Two honest limits. The fresh session shares the same **training**, so the same
base ability and failure shape — expected, and not the issue; what differs is
conversational contamination. And **freshness is declared, not proven**:
nothing here can verify it, so the field records a claim and is labelled the
weakest link in the channel. It must not read as evidence.

Because this session knows the expected names, the comparison is computed by
`art_call_outcome` **mechanically**, never judged — a disagreement cannot be
rationalised away by the reader that knows what it should have said.

**3. The abstention rate is a WEAK instrument at n=16, and no longer gates.**
A 5% floor on 16 cards is 0.8 cards; it collapses to *abstained at least
once*, which a lucky easy batch passes and a careful one fails identically.
Worse:

| True abstention rate | P(zero abstentions in 16) |
|---:|---:|
| 5% | **0.44** |
| 10% | 0.19 |
| 17% | 0.05 |

**The old floor would have failed a correct reader nearly half the time.**
Zero abstentions is significant at n=16 only if the true rate is **≥17%**.

So `abstention_report` reports and gates nothing: it prints the count *with
the rate at which zero would have been surprising*, because a count without
its detectable floor reads as a verdict and at this sample size it is not one.
Zero abstentions is worth a human look, **not a failure, and not evidence of
contamination on its own**.

**The per-row disagreement rule carries the weight instead**, and it does not
depend on sample size at all: every row's call is checked against the
documentary name individually. What the abstention rate cannot do is separate
a careful reader on an easy batch from a contaminated one — at n=16 those are
statistically indistinguishable, which is exactly why the fresh-session
protocol is doing the work, and exactly why it is labelled unverifiable.

**4. Outcomes.** `agrees` → the Latin name is independently attested and the
detector is live on the row. `disagrees` → the row is **blocked**, admitted
with neither name, because a disagreement is the instrument working rather
than a vote to break. `abstains` → name absent, the row lands exactly as
option A, and abstention costs nothing and must never be discouraged.

Spelling differences are not disagreements — the claim being corroborated is
*which character*, not which orthography.

### The non-native reader profile

`human_nonnative_logographic`, `self_detecting: **False**`. Same failure shape
as the model, different cause: **no model of which strokes are load-bearing**.
A smudge is noticed; a wrong radical is not. The reader knows they are
copying, and that feels like appropriate caution — but the caution is about
legibility, not meaning, and the substitution happens in the part they cannot
check.

Under the allocation already set, that reader may read the **checksummed
number** and **may not supply the name**. No new rule; the existing one
applied. What *would* be self-detecting is a native reader of the script or a
Simplified Chinese catalog source, and neither is currently available.

So `optical_only_nonnative` is not needed: the case it would label is one the
standard already refuses.

### The detector could not report what it looked at

`cross_language_name_disagreements` returns disagreements. A caller could not
tell *examined 28 and found none* from *examined none* — and those read
identically, which is this repository's recurring failure exactly.

`name_disagreement_coverage` now reports both. On the live set: **103 rows
examined, 49 numbers seen, 31 actually compared, 18 carrying a single row**. A
number with one row cannot disagree with itself, so the clean report is over
31 comparisons, not 49 numbers — and it was being read as the latter.

### Who read it is an error-profile field

`read_by` is **not attribution**. Different readers fail differently, and the
difference decides what they may supply.

Recorded as `reader_reliability` — a profile key — and deliberately **not a
tier**. A tier says what a *source class* can establish; this says how a
*reader* fails. That conflation has already been corrected twice
(`number_only` meaning both "which field" and "how strongly", then per-source
tiers unable to distinguish SILENT from WEAK). A third instance is not needed.

| Profile | Failure mode | Self-detecting |
|---|---|---|
| `human_holder` | misreading, fatigue | yes |
| `human_from_image` | misreading, plus what the image lost | yes |
| `ai_from_image` | **confident substitution** of a visually similar character | **no** |

An AI reader's weakest case is dense-stroke Simplified Chinese at banner size
over foil, and the failure is not a visible stumble — it is a clean, assured,
wrong answer. An unclassified reader is **not** assumed reliable, the same
defaulting rule as an unknown corroboration tier.

This profile is about reading **glyphs off artwork**. Parsing text a server
sent us — `ingest/limitless.py` — is a different act and the profile does not
apply to it.

### `unsure_is_unresolved` needs a visible stumble

The protocol's main safeguard on the name assumes the reader **can notice
being unsure**. Where the failure mode is confident substitution, the escape
hatch is not weaker — it is **inoperative**. The reader does not abstain
because it does not know it should, and the row comes back looking clean.

So a note alone does not cover it. **If a reader cannot detect its own
failure, the mitigation cannot be self-report**; it has to be structural, and
the allocation follows the checksum:

- The **number** is checksummed against Bandai's record. A substituted digit
  yields a number that record does not carry, or one naming a different card.
  A non-self-detecting reader may read it — the checksum catches what the
  reader cannot.
- The **name** has no checksum. That is exactly where an undetectable
  substitution is unrecoverable, so a non-self-detecting reader **may not
  supply it**. It goes to a self-detecting reader or to
  `name_attestation: unresolved`.

`may_read(profile, field)` returns the refusal with its reason, and
`physical_card_row_is_well_formed` rejects a row whose reader supplied a field
it may not.

**The reader does not demote the source class.** `physical_card` is still
`optical` about the name; what changes is which reader may supply it. Those
are different questions and the code keeps them apart.

### Required provenance

Every `physical_card` row: `reading_method`, `read_by`, `read_on`, `checksum`,
`name_attestation`, `reader_reliability`. Plus `imaged_by` and `image_ref`
when the method is `photograph`. A `direct` row claiming an `imaged_by` is
refused — nothing was photographed, so there is no photographer to hold
responsible for the wrong copy.

### What would falsify this

A Simplified Chinese catalog source appearing and disagreeing with a row
admitted under this standard. That is a real possibility and the reason the
rows carry their provenance.

## RESOLVED — the Limitless endpoint was in the observed data all along

**Run 21 attested zero.** Every candidate URL failed:

    /cards/OP01/120       -> HTTP 500
    /cards/op/OP01/120    -> HTTP 404

All three candidates were guesses — while the page's own header and language
links carry **`/cards/OP01-120`**, which *is* the card page. That href was
observed two sessions ago and read as *signal 3*; it was never recognised as
the **endpoint**. The URL was sitting in the parser the whole time.

**The 500 was the diagnostic and it was ignorable.** A 404 says "no such
page"; a 500 says the host recognised enough to try and broke. Host right,
path shape wrong — which is exactly what it turned out to be.

Fixed: the observed shape is now the first candidate and is labelled as the
only non-guess in the list. A test asserts the adapter's own URL is
recognised by `_SELF_REF` — the endpoint it requests and the self-reference it
parses are now the same shape, which they were not, and that mismatch is the
whole bug.

**What worked:** the probe reported every URL tried with its status rather
than claiming the cards have no variants. Without that the run would have read
as "six cards, nothing attested" and the candidate list would not have been
diagnosable at all. That is the design earning its keep — but it does not
excuse three guesses when the answer was already in the repository.

## S2 — the daily ingest has crashed for five consecutive runs

```
http.client.InvalidURL: URL can't contain control characters.
'/v1/search?q=Rare Candy&game=55' (found at least ' ')
```

An unencoded card name in the tcgapi search URL. `Rare Candy` has a space,
`http.client` refuses a request line containing one, and it raised **from
inside the transport** — so it was not an adapter failure the runner could
record as a gap. It took the whole run down, on the first card whose name has
a space.

Runs 17–21 all failed here. GOAL D1 wants ≥90 consecutive days with zero
silent gaps; this was neither silent nor a gap — it was a crash — but it has
been costing a full run a day.

Fixed with `urllib.parse.quote`. Three tests: that the name is encoded, that
`http.client`'s own `_validate_path` accepts the result, and that it rejects
the unencoded form — the last one pins the diagnosis rather than trusting the
fix.

**Still S2, not resolved:** the fix is committed but unproven against the live
service. The next scheduled run is the evidence.

## S2 — apitcg and Limitless disagree on OP01-120's printings

**Still open. The fetch that would settle it was attempted and did not land.**

Limitless's print table lists **five printings across three products**:
`op01` base, `op01` alt art, `op01` manga, a **Championship 2023 Prize Cards
serial** — a third product this project did not know existed — and `prb01`
alt art.

The previous model, derived from apitcg's filename grouping, was six printings
across two products (`op01` base/`_p1`/`_p2`, `prb01` `_p3`/`_p4`/`_p5`).
**They disagree on `_p3`** and on the count.

**Not reconciled**, and the Prize Cards product is *still unattested*: the
label names it, no page has served a product slug for it. A request for
`?v=3` came back as the **`?v=2` page** — image `_p2`, body
`Romance Dawn (OP01) Manga Art`, `Romance Dawn manga` unlinked in the print
table. Refused rather than credited to slot 3.

The runner may or may not get further. **If it also lands on `?v=2`, that is
the finding**, and it will be reported as a slot mismatch rather than as an
absent product — which is the distinction that matters, because "no product
on the page" and "a different page answered" call for different next steps.

S2 rather than S1: no ground-truth row claims a Prize Cards or `prb01`
printing of OP01-120, so nothing wrong is being counted. It becomes S1 the
moment one is minted.

## S2 — a fetch can return a printing other than the one requested

Requesting `?v=3` for OP01-120 returned the `?v=2` page. Site redirect or
de-duping in the fetch path — **indistinguishable from outside, and it does
not need to be distinguished**, because the guard is identical either way.

This is the failure mode that would not have announced itself. A fetch that
silently returns a neighbour puts a wrong `(slot, product)` pair into
`printing_slots.json` with every check green, and everything downstream reads
it as sourced.

**Guarded, not assumed away.** `verify_slot` parses the slot *from the page*
and compares it to what was requested. Three signals, compared and never
merged:

1. **The gap in the `?v=` run.** Every row but the current printing carries a
   link, so on `?v=2` the links run 1, 3, 4 and the missing integer names the
   page. Assumes nothing about markup — which matters, because the page
   reaches the parser as rendered markdown down one path and raw HTML down
   another, and a rule about *which element lacks an anchor* has to be right
   about both. A missing integer is the same in either. **Abstains on a
   complete run**, which is equally the base page and the `?v=N+1` page.
2. **The image filename suffix** (`_pN`, absent for base), read from
   **`og:image` / `twitter:image` in the head** rather than the body `<img>`.
   Head-level, so body markup changes cannot break it, and it is the same
   string in either serialisation. The body image is the fallback for a
   rendered page with no head, and the source that answered is reported.
3. **The page's own self-reference links.** *Corrected 2026-08-25:* there is
   **no `rel=canonical`** — the head holds `description`, `og:*`, `twitter:*`,
   `viewport` and `title`, nothing else. Looking for a canonical element
   returns absent on every page, which is a signal that never speaks
   masquerading as a signal that agrees.

   The self-reference is in the **body**, three times: the header card-name
   link and the two language links (`/cards/OP01-120?v=2`,
   `/cards/en/…`, `/cards/jp/…`). All three report **what was served**, not
   what was requested — on the `?v=3` request that returned `?v=2`, all three
   said `?v=2`. That is precisely the property this signal needs.

   Three instances means the page checks itself: if the header and the two
   language links disagree, that is a **page-level anomaly** and the signal
   returns nothing. Two links claiming different printings of one card is not
   a majority to take.

Where two speak and disagree, the answer is *none* with the disagreement
attached. A page that cannot say which printing it is must not be recorded as
any printing.

**One coupling, permanent and stated rather than papered over.** *Observed
2026-08-25:* the print rows carry **the same URL shape as the header
self-link** —

    [Romance Dawn](/cards/OP01-120)
    [Romance Dawn aa](/cards/OP01-120?v=1)
    [Prize Cards serial](/cards/OP01-120?v=3)

so nothing in a URL separates "this page" from "go to printing N". Left in the
table the header link adds a "printing" labelled with the card's *name* and
refills the gap that identifies the page — which is exactly what happened, and
it silenced signal 1 on every fixture until it was fixed.

Self-references are excluded by **multiplicity**: the print table omits the
printing being displayed, so the served slot is carried by the header link and
the two language links — three times — while every print row carries its slot
once.

**Signal 1's dependency on that exclusion is permanent, not conditional.** The
earlier wording ("where the shapes collide") implied a branch for the case
where they do not; they always do, and that branch has been removed. An
untaken branch tested only against fixtures is a third thing that cannot fire.
It is still never the other direction — the self-reference signal does not
read the print table.

A weak fourth check exists and is deliberately not a signal: **`og:title`
carries the product NAME** ("Shanks (OP01-120) • Romance Dawn"). A name can
corroborate a slug and must never supply one — turning a name into a set code
needs a lookup, and doing that lookup here makes the title a product source
again, which is the bug this module opened with.

Open rather than resolved because the cause is unknown and it may recur on any
card. Every run reports mismatches.

## S3 — the `?v=N` ↔ `_pN` binding is confirmed at n=1

`?v=2` serves `OP01-120_p2_EN.webp`. That is **one pairing on one card**, plus
base/no-suffix. It was carried into the previous session's write-up as
established; it is a single observation of the mapping, not the mapping.

**Downgraded and instrumented rather than deleted.** The adapter re-confirms
the binding per card from the image filename on every page it reads
(`slot_binding_evidence`), and every run reports confirmations against
contradictions. A card where it fails is **evidence about the mapping, not
about that card** — that distinction is in the report text, because the
tempting reading of a single contradiction is "this card is odd".

S3 because nothing currently depends on the binding holding beyond n=1: the
slot entries cite the page that attested each product, and the binding is what
lets `?v=N` be *compared* to `_pN`, not what supplies a product.

## RESOLVED — the Limitless adapter refuses other games at entry

`_SELF_REF` is `[A-Za-z]{2,4}\d{2}-\d{2,4}`. It cannot match `OGN-030` — no
digits before the dash — or `025/165`, which has no letters at all. That is
correct for an adapter whose host is `onepiece.limitlesstcg.com`, but it was
enforced by *nothing*: a Pokémon or Riftbound card would not have failed, it
would have silently matched no self-reference and come back as a page that
could not identify itself.

**Same failure family as the canonical tag.** A pattern that can never match
reads exactly like one that looked and found nothing. Now `refuse_other_games`
raises `UnsupportedGame` at every entry point — `LimitlessAdapter.card_page`
and `attest` — before any request is made, and the message names both numbers
that cannot match and says why.

## S3 — tcgdex renumbers the Celebrations Classic Collection

The printed card says `4/102`. tcgdex calls it `CC002`. Both describe the same
Charizard, and the printed number is the identity, so the labelled row keeps
`4/102` and the catalog keeps `CC002`.

The consequence: `cel` aliases to `cel25cc` correctly and the rows still cannot
match a catalog row, because the numbering schemes have nothing in common. The
bridge refuses rather than guessing, which is right — but it means the
`same_number_new_set` pairs, the hardest of the three reprint shapes, have no
catalog counterpart to be tested against.

## S3 — three set codes could not be verified

`mcd2023`, `s10b`, `s12a`. Recorded in `UNVERIFIED_SET_CODES` with the reason
and passed through untouched. The local apitcg snapshot stops at `mcd22` and
holds English only, and the catalog's Japanese set codes come from a different
scheme entirely (`SM10`, `SM12a`, `SV11B`).

An unaliased code and an unverifiable one behave identically — both pass
through — and only one of them is a decision. This is how you tell later that
somebody looked.

## S3 — 57 rows carry a `difficulty_class` the gate cannot read

The 86 researched rows tag themselves `C1`..`C6` — 28 `C1`, 21 `C5`, 10 `C3`,
10 `C6`, 4 `C4`, 2 `C2`. The gate counts `hard_case`, and requires four named
kinds: `same_art_different_language`, `reprint`, `alt_art_variant`,
`promo_vs_set`.

**RESOLVED** by the definitions above. **51 of 57** verified rows now carry a
hard case, against a target of 60.

`hard_case` had to become plural to do it: 18 of the 57 rows carry two classes
(`C1,C6`, `C3,C5`, `C2,C4`), and a single-valued field has to drop one —
silently deciding which gate requirement goes unmet. `hard_cases_of()` reads
both fields so nothing already recorded is lost.

`reprint` (C2) is the one required kind still absent from verified rows — see
above; that gate failure is deliberate.

## S2 — nine variant tokens are rejected and 18 rows are waiting on them

The 86-row external research file uses 18 variant tokens. Nine are not in
`resolve.identity.VARIANTS`, so 18 rows are held out of the set:

**RESOLVED.** Eight extended, one renamed, and the vocabulary is now PER GAME
— `SHARED_VARIANTS` plus `GAME_VARIANTS`, exactly like the rarity band tables.
`sr` is valid for `pkmn` and invalid for `optcg`, where those two letters name
a rarity band instead, and the rejection message says so rather than "unknown".
All 86 rows are in.

## S3 — the catalog carries no set totals yet, so the bridge refuses everything

The catalog is tcgdex-derived and stores BARE collector numbers — `199`, `95`,
`173`. The labelled set stores what is printed on the card — `199/165`,
`095/203`, `173/165`. Neither is wrong and neither should change: the printed
number is the identity, and tcgdex's `localId` is what the provider sends.

`printed_from_bare` bridges them, one direction only, using the set's official
card count. **The count is not in `targets.json` yet** — `set_totals()` was
added to the tcgdex adapter this session and populates `_set_totals` on the
next Actions run.

Until then the bridge REFUSES every comparison, which is the designed
behaviour: 10 refusals, 0 matches, 0 merges. With the counts simulated
(`sv03.5` 165, `swsh7` 203) three rows bridge immediately — `199/165`
Charizard ex, `205/165` Mew ex, `095/203` Umbreon VMAX.

Set codes are bridged, for two sets, by `SET_CODE_ALIASES`. Nothing bridges
the rest: `sv2a`, `s6a`, `s7R`, `151C`, `SV2aF`, `op01`, `op08`, `OGN`, `VEN`
all have no counterpart in the current catalog — mostly because apitcg has been
throttled and optcg/riftbound catalogs are empty, so there is nothing to
reconcile against yet. 93 of 103 labelled rows have no candidate at all.

## S3 — the labelled set is 103 rows, 57 of them ground truth

`tests/test_resolver_gate.py` is deliberately red. Six failures in every run,
and they are the only six. Candidates must be adjudicated by hand
(`python -m resolve.label_cli propose`); generating them from the catalogs the
resolver reads would make the precision score a measurement of the catalog.

57 `verified`, 29 `single_source`, 12 `in_repo`, 5 `unstated`. Precision and
recall are 1.0000 over the 57 — and that is a point estimate, not a passing
gate. Zero errors at n=57 gives a 95% lower bound of **0.9488**, against a
0.98 threshold. n=250 gives 0.9881 and survives one mistake, which is what
ADR-0015 sized the set on.

Every combination now has verified rows, and every combination is still below
the 20-row detection floor.

Five `unstated` rows remain, down from nine: four were superseded by sourced
rows. The rest need re-adjudication or discarding.

## S3 — the seven-day catalog threshold is a guess

`DEFAULT_MAX_AGE_DAYS = 7`. Sets release monthly, so a week is comfortably
inside the cadence, but it is a starting point and not a measurement. A set
that drops mid-week is missed until the refresh; `--force` exists for that day.

---

# Known-fragile

Carried from CLAUDE.md, still true. Treat with suspicion, do not "fix":

- Submission selection haircut — a guess until calibrated against my own
  submission results
- Regrade conditional prior — same, smaller sample coming
- Pull rate estimates — community-sourced and often wrong
- Riftbound history — sub-1-year market. Exploratory only, and the UI says so
- JP market coverage — no clean API; manual entry for v1
- Grade-level comp thinness — most of the universe has single-digit graded
  sales per quarter

## FIXED — the same inverted bisection shipped twice

Wilson/beta at `c333ec3`, Clopper-Pearson at `ea2f9a4`, and the second was
written inside the docstring warning about the first. Both returned `0.0` for
every sample with an error in it, and `0.0` passes an `assertLess` silently.

Closed 2026-08-27 by `audit/checks/interval_properties.py` (ADR-0058): one
battery, applied to every interval estimator in the tree, roster **discovered
by name rather than listed**, pins anchored to the binomial's defining
equation and carrying the one-error cases that both bugs failed. A new
estimator is a failure until it is declared.

Found on its first run: the gate's own `_lower_bound` raised
`ZeroDivisionError` on an empty sample while the other two answered `0.0`.
Fixed in the same commit.

**Not done:** the three implementations are still three implementations. The
battery makes the duplication checked, not safe. If a fourth appears,
consolidate.

## S2 — the `set_and_name` join produces wrong pairs and cannot tell

Two of the five `set_and_name` refusals are
`pkmn:sv03.5:003/165` ← catalog `sv03.5/198` and `pkmn:sv03.5:009/165` ←
catalog `sv03.5/200`. Those are **different printings of the same character in
the same set** — the hazard `pair()`'s ambiguity rule exists to catch,
arriving in the shape the rule does not cover: one labelled row, one catalog
entry, same name, different printing.

Had the resolver answered, it would have answered **correctly** and been
scored **wrong**. The 2/2 on that join is luck, not evidence.

This is the argument for committing the pairing to an adjudicated artifact
with its own provenance rather than re-deriving it each run: the join is a
known source of wrong pairs, and nothing downstream can detect one.

Cost of leaving it: the `set_and_name` precision figure is not trustworthy in
either direction. The `field` join is unaffected — it pairs on numbers, which
is a weaker independence claim but not a wrong-pair generator.

## S3 — the resolver refuses every Japanese row on the name, not the number

All five `field`-join refusals are `pkmn:JP` rows whose numbers now bridge
cleanly (`S12a/014` → `014/172`). The name comparison fails: the catalog names
cards in the local script, the labelled set uses Latin, and `name_similarity`
scores those near zero.

Relocated, not new — it was ADR-0057's blocker 2, previously showing up as
"cannot pair". It is in a better place now: visible in a bucket with a reason
attached rather than absent from the denominator.

The fix is a transliteration or a JP-name column on the labelled rows, and it
is worth more pairs than any refinement of the join.

## FIXED — the publisher's id and the illustrator were read and thrown away

`_catalog_row` fetched `find(hit, "id", "card_id")` to derive the variant and
never stored it, so **all 10,867 rows in `targets.json` carry
`external_id: ""`.** It also read `illustrator` into `artist`, which `_cn_row`
then dropped.

Both now reach `targets.json`, with `rarity` alongside. The illustrator is the
strongest pairing oracle available: it has nothing to do with the number, the
set or the name — and the number is what the catalog-in measurement measures,
so the join cannot use it.

`score()` feeds `rarity` to the resolver and **not** `external_id`: rarity is
what production has, while `external_id` reaches the xref path and an xref
table built from our own labelling would answer the question with the answer.

Data lands on the next ingest run; the plumbing is committed. Fixed
2026-08-27, ADR-0062.

## FIXED — a refusal caught and turned into a verdict, twice

The third defect species. `audit/defect_taxonomy.py` had INERT and ORPHANED
and **both of their remedies pass this cleanly** — the check fires, something
calls it, and the refusal dies in between.

- `catalog_precision._numbers_agree` caught `CannotBridge` and returned
  `str(a) == str(b)`, four lines below the docstring saying that exact
  confusion is why the exception exists. 4 rows on the current catalog were
  being counted as cards the catalog does not carry.
- `TcgdexAdapter.filter_is_honoured` caught `RateLimited` and returned
  `False`, which the caller reads as "fall back" — 8,313 single-card fetches,
  started because the source had just said stop.

`audit/checks/no_suppressed_refusal.py` is the audit, wired into
`data-guard.yml` as a hard gate. The refusal vocabulary is discovered (14
types), `can refuse` is a transitive closure over the call graph (1,229
functions), and a bare `except Exception` is in scope only around a call that
can refuse.

**Known hole, stated rather than papered over:** `log(exc); return False`
binds and uses the exception and still hands the caller a verdict. Tightening
to "the returned value must carry the exception" false-positives on the
correct `detail = str(exc); return {"detail": detail}` idiom, so the check is
the weaker of the two rather than one with a growing exemption roster.

## FIXED — a killed mutation run poisoned the next two runs' baselines

Written up as INC-002 in `docs/INCIDENTS.md`.

`audit/mutate.py` edits source in place and restores in a `finally`, which
**does not run on SIGTERM**. A run killed on 2026-08-27 left
`interval_properties.battery`'s `check()` as a `pass`. The next two runs then
measured `failures=11` instead of `failures=6` and reported two false MISSED
results — the sabotage had been normalised into the baseline, so mutants that
were caught looked identical to it.

`--only` made it worse rather than better: `_run`'s per-mutant anchor check
would have caught the missing anchor, but only for a mutant in the **selected
subset**, and a filtered run never touches the file holding the sabotage.

Two fixes: `verify_tree()` checks **every** catalogued anchor before a baseline
is measured and refuses to run if any is missing, regardless of the filter; and
SIGTERM/SIGHUP are turned into exceptions so the existing restore path
executes. Both mutated.

The docstring already said "that has happened once already." It had now
happened twice, which is the same lesson as ADR-0058: a comment describing a
failure mode is not a control against it.

## FIXED — the run report could not show that we were the load

Both quota findings this project has produced were **client-side**, and for
seven weeks the diagnosis pointed at the provider. The rate-limit table counted
CALLS and 429s with no denominator, so 3,494 requests for 3,494 cards looked
exactly like 35 requests for 3,494 cards.

Three columns added, and the arithmetic does the rest:

| Source | Cards | Calls | Batched | Amplification | 429s |
|---|---:|---:|---:|---:|---:|
| `apitcg` | 5582 | 5582 | 56 | **100x** | 2 |

`cards_per_request` is declared on the adapter (1 by default, 100 for apitcg's
`/api/products`), so a source with no batched form reads `1x` rather than being
flagged as noise. When any source exceeds its own batched equivalent the report
says **"We are the load"** and names it.

The preflight now answers the first question in every quota conversation in one
word: `key=yes` / `key=no` / `key=NO` / `key=n/a` per source, presence only,
never the key. A `key=NO` source is calling the provider **anonymously**, which
on a shared runner egress IP shares a quota with everyone else on that host.

**A limit you cannot see yourself approaching reads as somebody else's limit.**
