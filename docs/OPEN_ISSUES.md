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
